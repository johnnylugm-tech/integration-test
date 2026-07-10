"""taskq executor — subprocess runner with shlex.split (NFR-02) and
retry/backoff (FR-03).

[FR-02] Citations: SPEC.md §3 FR-02 (subprocess.run signature; state
machine pending → running → done | failed | timeout; result fields;
single-mode timeout → exit 4); NFR-02 (the NFR-02-flagged
subprocess-shell parameter is forbidden in ``executor.py`` — enforced
by ``test_fr02_no_shell_true``).
[FR-03] Citations: SPEC.md §3 FR-03 (auto-retry failed/timeout up to
``TASKQ_RETRY_LIMIT`` times with backoff
``TASKQ_BACKOFF_BASE × 2**n``; injectable ``sleep`` for testability).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Callable, Union

# Default subprocess timeout in seconds (SPEC §5.1 TASKQ_TASK_TIMEOUT).
_DEFAULT_TIMEOUT = "10.0"

# tail length for stdout/stderr capture (SPEC §3 FR-02 result fields).
_TAIL_LEN = 2000

# Default for TASKQ_RETRY_LIMIT (SPEC §3 FR-03).
_DEFAULT_RETRY_LIMIT = "0"

# Default for TASKQ_BACKOFF_BASE (SPEC §3 FR-03).
_DEFAULT_BACKOFF_BASE = "1"


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 ``Z`` string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cmd_of(task: Union[Any, dict]) -> str:
    """Read ``command`` from either a dataclass-style Task or a plain dict."""
    if isinstance(task, dict):
        return task["command"]
    return task.command


def _run_once(args: list[str], timeout: float) -> dict[str, Any]:
    """Execute ``args`` once via ``subprocess.run`` and return the result dict.

    Per SPEC §3 FR-02:

    * ``subprocess.run(args, capture_output=True, text=True,
      timeout=TASKQ_TASK_TIMEOUT)`` — and **no** path uses the NFR-02-flagged
      subprocess-shell parameter (NFR-02).
    * exit 0 → ``status="done"``; non-zero → ``"failed"``;
      ``TimeoutExpired`` → ``"timeout"``.
    """
    started = time.monotonic()
    finished_at = _now_iso()
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        duration_ms = (time.monotonic() - started) * 1000.0
        return {
            "status": "timeout",
            "exit_code": None,
            "stdout_tail": "",
            "stderr_tail": "",
            "duration_ms": duration_ms,
            "finished_at": finished_at,
        }

    duration_ms = (time.monotonic() - started) * 1000.0
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    return {
        "status": "done" if completed.returncode == 0 else "failed",
        "exit_code": completed.returncode,
        "stdout_tail": stdout[-_TAIL_LEN:],
        "stderr_tail": stderr[-_TAIL_LEN:],
        "duration_ms": duration_ms,
        "finished_at": finished_at,
    }


def run_task(
    task: Union[Any, dict],
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Execute ``task.command`` with retry/backoff (SPEC §3 FR-02 + FR-03).

    * Per FR-02: single-shot returns ``status`` / ``exit_code`` /
      ``stdout_tail`` / ``stderr_tail`` / ``duration_ms`` / ``finished_at``.
    * Per FR-03: when a single attempt returns ``"failed"`` or
      ``"timeout"``, retry up to ``TASKQ_RETRY_LIMIT`` additional times.
      Before the ``n``-th retry (1-indexed), sleep for
      ``TASKQ_BACKOFF_BASE × 2**n`` seconds. The ``sleep`` callable is
      injectable so tests can observe the backoff sequence without
      actually waiting.
    """
    if sleep is None:
        sleep = time.sleep

    cmd_str = _cmd_of(task)
    args = shlex.split(cmd_str)
    timeout = float(os.environ.get("TASKQ_TASK_TIMEOUT", _DEFAULT_TIMEOUT))
    retry_limit = int(
        os.environ.get("TASKQ_RETRY_LIMIT", _DEFAULT_RETRY_LIMIT)
    )
    backoff_base = int(
        os.environ.get("TASKQ_BACKOFF_BASE", _DEFAULT_BACKOFF_BASE)
    )

    last_result: dict[str, Any] | None = None
    # ``attempt`` is 0-indexed: 0 = first try, k = k-th retry.
    for attempt in range(retry_limit + 1):
        result = _run_once(args, timeout)
        last_result = result
        if result["status"] == "done":
            return result
        # ``failed`` / ``timeout`` — back off before the next retry.
        if attempt < retry_limit:
            sleep(backoff_base * (2 ** (attempt + 1)))
    assert last_result is not None  # loop body always runs at least once.
    return last_result