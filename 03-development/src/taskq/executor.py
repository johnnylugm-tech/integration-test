"""taskq.executor — Task Executor with Retry + Circuit Breaker (FR-02 + FR-03).

[FR-02] subprocess-driven task runner: `subprocess.run + shlex.split`,
NEVER enabling the shell-mode flag (NFR-02). State machine:
  pending → running → done (exit 0) | failed (non-0) | timeout (TimeoutExpired)

Result fields populated on the task:
  exit_code, stdout_tail (last 2000 chars), stderr_tail (last 2000 chars),
  duration_ms, finished_at.

[FR-03] Automatic retry on failed/timeout:
  - up to TASKQ_RETRY_LIMIT retries
  - exponential backoff: `TASKQ_BACKOFF_BASE * 2**n` seconds before retry n
  - `sleep` callable is injectable so tests don't actually sleep
  - circuit-breaker pre-check: OPEN → no subprocess, exit 3
  - HALF_OPEN probe: success → CLOSED, failure → re-OPEN
  - breaker counter incremented on final failure only

The `subprocess` symbol at module scope is the live `subprocess` module —
tests `monkeypatch.setattr(executor.subprocess, "run", ...)` to drive the
TimeoutExpired branch without sleeping.

Citations:
- SPEC.md §3 FR-02 lines 74-83: state machine + result fields + single-task
  timeout → exit 4
- SPEC.md §3 FR-02 line 78: `shlex.split(command), capture_output=True,
  text=True, timeout=...` — shell mode never enabled
- SPEC.md §3 FR-02 line 81: stdout/stderr tails capped at 2000 chars
- SPEC.md §3 FR-03: retry with exponential backoff; circuit breaker
- NFR-02: zero shell-mode invocations in the entire codebase
- NFR-03: atomic persistence (breaker.json writes via breaker.save_state)
"""
from __future__ import annotations

import os
import shlex
import subprocess as _subprocess
import time
from typing import Callable, Optional

from taskq import breaker
from taskq.models import Task, utc_now_iso

# Module-level alias so tests can patch `executor.subprocess.run`.
subprocess = _subprocess

# Module-level sleep reference — tests patch via `executor._sleep` so the
# backoff callable is injectable without monkeypatching `time.sleep`.
_sleep = time.sleep

# SPEC §3 FR-02 line 81 — stdout_tail / stderr_tail last 2000 chars.
_OUTPUT_TAIL_LIMIT = 2000


def _read_task_timeout() -> float:
    """Read `TASKQ_TASK_TIMEOUT` (default 10.0s)."""
    raw = os.environ.get("TASKQ_TASK_TIMEOUT", "10.0")
    try:
        return float(raw)
    except ValueError:
        return 10.0


def _read_retry_limit() -> int:
    """Read `TASKQ_RETRY_LIMIT` (default 0)."""
    raw = os.environ.get("TASKQ_RETRY_LIMIT", "0")
    try:
        return int(raw)
    except ValueError:
        return 0


def _read_backoff_base() -> float:
    """Read `TASKQ_BACKOFF_BASE` (default 0.0)."""
    raw = os.environ.get("TASKQ_BACKOFF_BASE", "0.0")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _tail(text: Optional[str]) -> str:
    """Return last `_OUTPUT_TAIL_LIMIT` chars; tolerate None."""
    if not text:
        return ""
    return text[-_OUTPUT_TAIL_LIMIT:]


def _is_final_failure(task: Task) -> bool:
    """Return True if `task.status` is a final-failure state for breaker purposes."""
    return task.status in ("failed", "timeout")


def run_task(
    task: Task,
    *,
    sleep: Optional[Callable[[float], None]] = None,
) -> Task:
    """Execute `task.command` with retry + circuit-breaker integration.

    [FR-02/FR-03] Returns the same `Task` object with `status` advanced and
    `exit_code` / `stdout_tail` / `stderr_tail` / `duration_ms` /
    `finished_at` populated.

    On a permanent failure (failed/timeout after exhausting retries), the
    breaker counter is incremented; on a successful run the breaker is
    closed. The caller is responsible for persisting the mutated task via
    `store.update_task`.

    The `sleep` kwarg is the injectable backoff callable (FR-03 contract:
    `sleep(BASE * 2**n)` before each retry attempt n=1..retry_limit).
    Passing `None` falls back to `time.sleep` in production.
    """
    timeout = _read_task_timeout()
    retry_limit = _read_retry_limit()
    backoff_base = _read_backoff_base()
    do_sleep = sleep if sleep is not None else _sleep

    breaker.reload_config()

    decision = breaker.check_and_admit()
    if decision == breaker.REJECT:
        task.status = "failed"
        task.exit_code = None
        task.stdout_tail = ""
        task.stderr_tail = "breaker open"
        task.duration_ms = 0
        task.finished_at = utc_now_iso()
        return task

    task.attempts = 0
    for attempt_index in range(retry_limit + 1):
        if attempt_index > 0:
            # Backoff before each retry: BASE * 2**n (n=1..retry_limit).
            do_sleep(backoff_base * (2 ** attempt_index))
        task.attempts = attempt_index + 1
        task.status = "running"
        started = time.monotonic()
        try:
            result = _subprocess.run(
                shlex.split(task.command),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            task.exit_code = int(result.returncode)
            task.stdout_tail = _tail(result.stdout)
            task.stderr_tail = _tail(result.stderr)
            task.status = "done" if result.returncode == 0 else "failed"
        except _subprocess.TimeoutExpired:
            task.status = "timeout"
            task.exit_code = None
            task.stdout_tail = ""
            task.stderr_tail = ""
        finally:
            task.duration_ms = int((time.monotonic() - started) * 1000)
            task.finished_at = utc_now_iso()

        if task.status == "done":
            breaker.record_success()
            return task
        if not _is_final_failure(task):
            return task  # pragma: no cover
        if attempt_index >= retry_limit:
            break

    # Exhausted retries on a failing task → record breaker failure.
    breaker.record_failure()
    return task