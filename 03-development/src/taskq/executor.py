"""taskq.executor — Task Executor (FR-02).

[FR-02] subprocess-driven task runner: `subprocess.run + shlex.split`,
NEVER enabling the shell-mode flag (NFR-02). State machine:
  pending → running → done (exit 0) | failed (non-0) | timeout (TimeoutExpired)

Result fields populated on the task:
  exit_code, stdout_tail (last 2000 chars), stderr_tail (last 2000 chars),
  duration_ms, finished_at.

The `subprocess` symbol at module scope is the live `subprocess` module —
tests `monkeypatch.setattr(executor.subprocess, "run", ...)` to drive the
TimeoutExpired branch without sleeping.

Citations:
- SPEC.md §3 FR-02 lines 74-83: state machine + result fields + single-task
  timeout → exit 4
- SPEC.md §3 FR-02 line 78: `shlex.split(command), capture_output=True,
  text=True, timeout=...` — shell mode never enabled
- SPEC.md §3 FR-02 line 81: stdout/stderr tails capped at 2000 chars
- NFR-02: zero shell-mode invocations in the entire codebase
- SAD §2.4 executor.py signature: `run_task(task, *, sleep=_sleep) -> Task`
"""
from __future__ import annotations

import os
import shlex
import subprocess as _subprocess
import time
from typing import Callable, Optional

from taskq.models import Task, utc_now_iso

# Module-level alias so tests can patch `executor.subprocess.run`.
subprocess = _subprocess

# SPEC §3 FR-02 line 81 — stdout_tail / stderr_tail last 2000 chars.
_OUTPUT_TAIL_LIMIT = 2000


def _read_task_timeout() -> float:
    """Read `TASKQ_TASK_TIMEOUT` (default 10.0s)."""
    raw = os.environ.get("TASKQ_TASK_TIMEOUT", "10.0")
    try:
        return float(raw)
    except ValueError:
        return 10.0


def _tail(text: Optional[str]) -> str:
    """Return last `_OUTPUT_TAIL_LIMIT` chars; tolerate None."""
    if not text:
        return ""
    return text[-_OUTPUT_TAIL_LIMIT:]


def run_task(
    task: Task,
    *,
    sleep: Optional[Callable[[float], None]] = None,
) -> Task:
    """Execute `task.command` and stamp result fields in-place.

    [FR-02] Returns the same `Task` object with `status` advanced and
    `exit_code` / `stdout_tail` / `stderr_tail` / `duration_ms` /
    `finished_at` populated. The caller is responsible for persisting the
    mutated task back to the store (see `store.update_task`).

    The `sleep` kwarg is reserved for FR-03 retry/backoff injection; FR-02
    itself does not call it, but the signature is preserved for the
    upcoming FR-03 step.
    """
    timeout = _read_task_timeout()
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
    return task