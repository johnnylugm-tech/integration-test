"""[FR-02] Task executor — subprocess runner + concurrent fan-out.

Citations: SPEC.md §3 FR-02 (line 74-83).
"""
from __future__ import annotations

import shlex
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from taskq import store

# SPEC.md §3 FR-02 — stdout/stderr 末 2000 字元.
_TAIL_LEN = 2000


def _now_iso() -> str:
    """[FR-02] UTC ISO-8601 timestamp string for finished_at."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_subprocess(
    command: str, timeout: float
) -> tuple[int | None, str, str, float, str]:
    """[FR-02] Execute one command via subprocess.run + shlex.split.

    Returns (exit_code, stdout_tail, stderr_tail, duration_ms, status).
    """
    started = time.perf_counter()
    argv = shlex.split(command)
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = (time.perf_counter() - started) * 1000
        stdout_tail = (exc.stdout or "")[-_TAIL_LEN:]
        stderr_tail = (exc.stderr or "")[-_TAIL_LEN:]
        return None, stdout_tail, stderr_tail, duration_ms, "timeout"

    duration_ms = (time.perf_counter() - started) * 1000
    stdout_tail = (proc.stdout or "")[-_TAIL_LEN:]
    stderr_tail = (proc.stderr or "")[-_TAIL_LEN:]
    status = "done" if proc.returncode == 0 else "failed"
    return proc.returncode, stdout_tail, stderr_tail, duration_ms, status


def execute_task(task_id: str, command: str, timeout: float) -> str:
    """[FR-02] Run one task to completion and persist the result.

    The task transitions pending → running → done|failed|timeout.
    Returns the final status string.
    """
    store.update_task(task_id, status="running")
    exit_code, stdout_tail, stderr_tail, duration_ms, status = _run_subprocess(
        command, timeout
    )
    store.update_task(
        task_id,
        status=status,
        exit_code=exit_code,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        duration_ms=duration_ms,
        finished_at=_now_iso(),
    )
    return status


def run_all(timeout: float, max_workers: int) -> dict[str, str]:
    """[FR-02] Concurrently execute every pending task.

    Uses ThreadPoolExecutor(max_workers=max_workers) as required by
    AC-FR-02-4. Returns {task_id: final_status} for everything attempted.
    """
    tasks = store.load_tasks()
    pending = [
        (tid, t["command"])
        for tid, t in tasks.items()
        if t.get("status") == "pending"
    ]
    results: dict[str, str] = {}
    if not pending:
        return results
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            tid: pool.submit(execute_task, tid, cmd, timeout) for tid, cmd in pending
        }
        for tid, fut in futures.items():
            results[tid] = fut.result()
    return results
