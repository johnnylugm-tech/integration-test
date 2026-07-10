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

from taskq import breaker, cache, store

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
    """[FR-02/FR-03/FR-04] Run one task to completion with retry + cache.

    Transitions pending → running → done|failed|timeout. On
    ``failed``/``timeout`` the task is retried up to
    ``TASKQ_RETRY_LIMIT`` times with exponential backoff
    ``TASKQ_BACKOFF_BASE * 2**n`` between attempts (``n`` is the
    zero-based retry index). The sleeper is injectable via
    ``executor.time.sleep`` so tests do not actually wait.

    FR-04 cache: before invoking the subprocess, consult
    ``taskq.cache.Cache.get(sig)``. A TTL-fresh hit short-circuits
    the run — no subprocess is invoked, the task is marked
    ``done`` with ``cached: true`` and the cached stdout_tail /
    stderr_tail / exit_code are replayed. After a fresh ``done``
    run, the result is written to ``cache.json``.

    Citations:
      - SPEC.md §3 FR-02 — pending → running → done|failed|timeout
      - SPEC.md §3 FR-03 — retry with exponential backoff
      - SPEC.md §3 FR-04 — sha256(command) + TTL replay + cache.json

    Returns the final status string.
    """
    # FR-04: cache short-circuit. A TTL-fresh entry replays the prior
    # done result without invoking subprocess.run. Mark the task done
    # with `cached: true` so subsequent status reads can distinguish
    # a replay from a fresh execution.
    sig = cache.signature(command)
    cache_obj = cache.Cache()
    cached = cache_obj.get(sig)
    if cached is not None:
        store.update_task(
            task_id,
            status="done",
            exit_code=cached.exit_code,
            stdout_tail=cached.stdout_tail,
            stderr_tail=cached.stderr_tail,
            duration_ms=0.0,
            finished_at=_now_iso(),
            cached=True,
        )
        return "done"

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

    # FR-04: cache the fresh done result so future replay short-circuits.
    if status == "done" and exit_code is not None:
        cache_obj.put(
            sig,
            cache.CacheEntry(
                signature=sig,
                exit_code=exit_code,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            ),
        )

    store.update_task(
        task_id,
        status=status,
        exit_code=exit_code,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        duration_ms=duration_ms,
        finished_at=_now_iso(),
        cached=False,
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
