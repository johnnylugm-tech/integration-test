"""[FR-02] taskq.executor — task execution + retry state machine.

Citations:
- 03-development/tests/test_fr02.py:13-17 (public API contract)
- 03-development/tests/test_fr02.py:119-187 (state machine)
- 03-development/tests/test_fr02.py:194-214 (subprocess shell=False NFR-02)
- 03-development/tests/test_fr02.py:222-233 (timeout → exit_code=4)
- 03-development/tests/test_fr02.py:264-286 (failed retry up to TASKQ_RETRY_LIMIT)
- 03-development/tests/test_fr02.py:294-317 (timeout retry up to TASKQ_RETRY_LIMIT)
- 03-development/tests/test_fr02.py:325-347 (stdout/stderr tail max 2000 chars)
- 03-development/tests/test_fr02.py:355-364 (duration_ms / finished_at ISO)
- 03-development/tests/test_fr02.py:399-427 (orphan cleanup NFR-15)
- SRS.md:61-80 (FR-02 任務執行與重試)
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime

from taskq.config import load_config
from taskq.executor import runner as _runner
from taskq.redact import redact
from taskq.store import get_task
from taskq.store.persistence import save_task


class InvalidTransition(Exception):
    """Raised when an event is illegal for the current task status.

    Citations:
    - 03-development/tests/test_fr02.py:14 (InvalidTransition contract)
    - 03-development/tests/test_fr02.py:179-187 (running + RESET_TO_PENDING → raise)
    """


# (current_status, event) → next_status
# Citations: 03-development/tests/test_fr02.py:119-187
_TRANSITIONS: dict[tuple[str, str], str] = {
    ("pending", "RUN"): "running",
    ("running", "DONE"): "done",
    ("running", "FAILED"): "failed",
    ("running", "TIMEOUT"): "timeout",
}


def apply_transition(task, event: str) -> None:
    """Mutate ``task.status`` per the (status, event) → status map.

    Raise :class:`InvalidTransition` on illegal or unknown transition.

    Citations:
    - 03-development/tests/test_fr02.py:13 (apply_transition contract)
    - 03-development/tests/test_fr02.py:119-187 (valid transitions)
    - 03-development/tests/test_fr02.py:179-187 (illegal transition → raise)
    """
    key = (task.status, event)
    if key not in _TRANSITIONS:
        raise InvalidTransition(
            f"cannot apply event {event!r} to status {task.status!r}"
        )
    task.status = _TRANSITIONS[key]


@dataclass
class RunResult:
    """Outcome of :func:`run_task`.

    Citations:
    - 03-development/tests/test_fr02.py:89-96 (exit_code, status)
    - 03-development/tests/test_fr02.py:222-233 (timeout: exit_code=4, status=timeout)
    - 03-development/tests/test_fr02.py:325-347 (stdout_tail, stderr_tail)
    - 03-development/tests/test_fr02.py:355-364 (duration_ms int, finished_at ISO)
    """

    status: str
    exit_code: int
    stdout_tail: str
    stderr_tail: str
    duration_ms: int
    finished_at: str


def _tail(text: str | bytes | None, n: int) -> str:
    """Return the last ``n`` characters of ``text`` (or ``text`` if shorter).

    Tolerates ``bytes | None`` from :class:`subprocess.TimeoutExpired` (the
    type stub on the exception is not narrowed by ``text=True``).

    Citations:
    - 03-development/tests/test_fr02.py:325-333 (stdout tail max 2000)
    - 03-development/tests/test_fr02.py:339-347 (stderr tail max 2000)
    - SRS.md:74 (stdout_tail / stderr_tail 末 2000 字元)
    """
    if text is None:
        return ""
    decoded = text.decode("utf-8", errors="replace") if isinstance(text, bytes) else text
    return decoded[-n:] if len(decoded) > n else decoded


def run_task(task_id: str) -> RunResult:
    """Execute a pending task and persist the outcome.

    State machine: ``pending → running → {done, failed, timeout}``.
    Retry: ``1 + TASKQ_RETRY_LIMIT`` attempts on failed/timeout.

    Citations:
    - 03-development/tests/test_fr02.py:13 (run_task contract)
    - 03-development/tests/test_fr02.py:264-286 (failed retry count)
    - 03-development/tests/test_fr02.py:294-317 (timeout retry count)
    - 03-development/tests/test_fr02.py:399-427 (orphan cleanup)
    - SRS.md:69-77 (state machine + retry behaviour)
    """
    task = get_task(task_id)
    if task is None:  # pragma: no cover  # defensive check; CLI pre-validates so this branch is unreachable from spec-mandated paths
        raise ValueError(f"unknown task: {task_id}")

    cfg = load_config()
    timeout_s = cfg.task_timeout
    retry_limit = cfg.retry_limit
    max_attempts = 1 + retry_limit

    # pending → running
    apply_transition(task, "RUN")
    task.started_at = datetime.now(UTC).isoformat()
    save_task(task_id, task)

    start_ts = datetime.now(UTC)
    final_status = "failed"
    final_exit = 1
    final_stdout = ""
    final_stderr = ""

    for _attempt in range(max_attempts):
        try:
            proc = _runner.run_subprocess(task.command, timeout_s)
            final_stdout = _tail(proc.stdout, 2000)
            final_stderr = _tail(proc.stderr, 2000)
            if proc.returncode == 0:
                final_status = "done"
                final_exit = 0
                break
            final_status = "failed"
            final_exit = proc.returncode
        except subprocess.TimeoutExpired as exc:
            final_stdout = _tail(exc.stdout, 2000)
            final_stderr = _tail(exc.stderr, 2000)
            final_status = "timeout"
            final_exit = 4

    # NFR-03: redact secret-bearing lines from stdout/stderr BEFORE persisting.
    # Citations: 03-development/tests/test_fr03.py:484-510 (redaction in tails)
    final_stdout = redact(final_stdout)
    final_stderr = redact(final_stderr)

    # running → {done, failed, timeout} (one final transition)
    if final_status == "done":
        apply_transition(task, "DONE")
    elif final_status == "failed":
        apply_transition(task, "FAILED")
    else:
        apply_transition(task, "TIMEOUT")

    end_ts = datetime.now(UTC)
    task.exit_code = final_exit
    task.stdout_tail = final_stdout
    task.stderr_tail = final_stderr
    task.duration_ms = int((end_ts - start_ts).total_seconds() * 1000)
    task.finished_at = end_ts.isoformat()
    save_task(task_id, task)

    return RunResult(
        status=final_status,
        exit_code=final_exit,
        stdout_tail=final_stdout,
        stderr_tail=final_stderr,
        duration_ms=task.duration_ms,
        finished_at=task.finished_at,
    )


__all__ = [
    "InvalidTransition",
    "apply_transition",
    "run_task",
    "RunResult",
]
