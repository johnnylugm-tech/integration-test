"""[FR-02/FR-03] Task executor — subprocess runner + retries + breaker-aware fan-out.

Citations:
  - SPEC.md §3 FR-02 (line 74-83) — task executor
  - SPEC.md §3 FR-03 (line 84-100) — retry + circuit breaker
"""
from __future__ import annotations

import os
import shlex
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from taskq import breaker, store

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
    """[FR-02/FR-03] Run one task to completion with retry.

    Transitions pending → running → done|failed|timeout. On
    ``failed``/``timeout`` the task is retried up to
    ``TASKQ_RETRY_LIMIT`` times with exponential backoff
    ``TASKQ_BACKOFF_BASE * 2**n`` between attempts (``n`` is the
    zero-based retry index). The sleeper is injectable via
    ``executor.time.sleep`` so tests do not actually wait.

    Citations:
      - SPEC.md §3 FR-02 — pending → running → done|failed|timeout
      - SPEC.md §3 FR-03 — retry with exponential backoff

    Returns the final status string.
    """
    store.update_task(task_id, status="running")

    limit = int(os.environ.get("TASKQ_RETRY_LIMIT", "0"))
    base = float(os.environ.get("TASKQ_BACKOFF_BASE", "1.0"))

    exit_code: int | None = None
    stdout_tail = ""
    stderr_tail = ""
    duration_ms = 0.0
    status = "failed"

    retries = 0
    while True:
        exit_code, stdout_tail, stderr_tail, duration_ms, status = _run_subprocess(
            command, timeout
        )
        if status == "done":
            break
        if retries >= limit:
            break
        time.sleep(base * (2 ** retries))
        retries += 1

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
    """[FR-02/FR-03] Concurrently execute every pending task under breaker supervision.

    Uses ``ThreadPoolExecutor(max_workers=max_workers)`` so concurrent
    workers do not serialise wall-clock time (AC-FR-02-4). The breaker
    state is shared across worker threads via a single ``Breaker``
    instance and a ``bp_lock``; mutations and atomic file saves are
    serialised by that lock. Workers whose ``try_acquire`` returns
    ``False`` (breaker open) are skipped.

    Returns ``{task_id: final_status}`` for tasks that were actually
    attempted; tasks skipped by an open breaker are omitted.

    Citations:
      - SPEC.md §3 FR-02 — concurrent fan-out
      - SPEC.md §3 FR-03 — circuit breaker supervision
    """
    home = store.home()
    breaker_path = home / "breaker.json"

    tasks = store.load_tasks()
    pending = [
        (tid, t["command"])
        for tid, t in tasks.items()
        if t.get("status") == "pending"
    ]
    results: dict[str, str] = {}
    if not pending:
        return results

    bp = breaker.load(breaker_path)
    bp_lock = threading.Lock()

    def _run_one(tid: str, cmd: str) -> str | None:
        with bp_lock:
            if not bp.try_acquire():
                return None  # breaker open → skip this task
            breaker.save(breaker_path, bp)
        status = execute_task(tid, cmd, timeout)
        with bp_lock:
            if status == "done":
                bp.record_success()
            else:
                bp.record_failure()
            breaker.save(breaker_path, bp)
        return status

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            tid: pool.submit(_run_one, tid, cmd) for tid, cmd in pending
        }
        for tid, fut in futures.items():
            r = fut.result()
            if r is not None:
                results[tid] = r
    return results
