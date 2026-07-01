"""[FR-02]

Task executor: `run_task(task_id)` runs a pending task via subprocess with
retry on failure/timeout.

Citations:
    - SPEC.md §3 FR-02 (subprocess invocation, state machine, retry, exit codes).
    - SPEC.md §3 FR-02 (single-task mode: timeout → exit 4; unhandled → exit 1).
    - tests/test_fr02.py (GREEN contract — RunResult field set).
"""

from __future__ import annotations

import shlex
import subprocess
from datetime import datetime, timezone

from taskq.config import retry_limit, task_timeout
from taskq.core.models import RunResult
from taskq.io.store import load_tasks, save_tasks


def run_task(task_id: str) -> RunResult:
    """Execute the pending task identified by `task_id`.

    Citations:
        - SPEC.md §3 FR-02 (subprocess.run with shlex.split, capture_output,
          text=True, timeout=TASKQ_TASK_TIMEOUT).
        - SPEC.md §3 FR-02 (state machine: pending→running→done|failed|timeout).
        - SPEC.md §3 FR-02 (retry on failed/timeout up to TASKQ_RETRY_LIMIT).
        - SPEC.md §3 FR-02 (single-task mode exit codes: 0=done, 1=unhandled, 4=timeout).
    """
    tasks = load_tasks()
    task_dict = next((t for t in tasks if t["id"] == task_id), None)
    if task_dict is None:
        return RunResult(
            exit_code=1,
            status="failed",
            finished_at=datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            ),
            attempts=0,
        )

    command = task_dict["command"]
    timeout = task_timeout()
    limit = retry_limit()

    # Transition: pending → running.
    task_dict["status"] = "running"
    save_tasks(tasks)

    exit_code = 1
    status = "failed"
    stdout_tail = ""
    stderr_tail = ""
    duration_ms = 0
    finished_at = ""

    start = datetime.now(timezone.utc)

    attempt: int = 0
    for attempt in range(limit + 1):  # 1 initial + N retries
        try:
            proc = subprocess.run(
                shlex.split(command),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            elapsed = datetime.now(timezone.utc) - start
            duration_ms = int(elapsed.total_seconds() * 1000)
            finished_at = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            )
            stdout_tail = _tail(proc.stdout, 2000)
            stderr_tail = _tail(proc.stderr, 2000)

            if proc.returncode == 0:
                exit_code = 0
                status = "done"
            else:
                exit_code = proc.returncode
                status = "failed"

        except subprocess.TimeoutExpired:
            elapsed = datetime.now(timezone.utc) - start
            duration_ms = int(elapsed.total_seconds() * 1000)
            finished_at = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            )
            status = "timeout"
            exit_code = 4

        except Exception:
            # FileNotFoundError, PermissionError, etc. — treat as failed,
            # but exit_code 1 per single-task-mode spec (unhandled exception).
            elapsed = datetime.now(timezone.utc) - start
            duration_ms = int(elapsed.total_seconds() * 1000)
            finished_at = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            )
            status = "failed"
            exit_code = 1

        if status == "done":
            break

    # Persist the terminal status.
    task_dict["status"] = status
    save_tasks(tasks)

    return RunResult(
        exit_code=exit_code,
        status=status,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        duration_ms=duration_ms,
        finished_at=finished_at,
        attempts=attempt + 1,
    )


def _tail(text: str | None, n: int) -> str:
    """Return the last *n* characters of *text*, or "" if *text* is None/empty."""
    if not text:
        return ""
    return text[-n:]
