"""taskq executor — subprocess runner with shlex.split (NFR-02).

[FR-02] Citations: SPEC.md §3 FR-02 (subprocess.run signature; state
machine pending → running → done | failed | timeout; result fields;
single-mode timeout → exit 4); NFR-02 (shell=True forbidden in
``executor.py`` — enforced by ``test_fr02_no_shell_true``).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Union

# Default subprocess timeout in seconds (SPEC §5.1 TASKQ_TASK_TIMEOUT).
_DEFAULT_TIMEOUT = "10.0"

# tail length for stdout/stderr capture (SPEC §3 FR-02 result fields).
_TAIL_LEN = 2000


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 ``Z`` string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cmd_of(task: Union[Any, dict]) -> str:
    """Read ``command`` from either a dataclass-style Task or a plain dict."""
    if isinstance(task, dict):
        return task["command"]
    return task.command


def run_task(task: Union[Any, dict]) -> dict[str, Any]:
    """Execute ``task.command`` via subprocess and return the result dict.

    Per SPEC §3 FR-02:

    * ``subprocess.run(shlex.split(command), capture_output=True,
      text=True, timeout=TASKQ_TASK_TIMEOUT)`` — and **no** path uses
      ``shell=True`` (NFR-02).
    * exit 0 → ``status="done"``; non-zero → ``"failed"``;
      ``TimeoutExpired`` → ``"timeout"``.
    * Result dict carries ``status`` / ``exit_code`` / ``stdout_tail``
      (last 2000 chars) / ``stderr_tail`` (last 2000 chars) /
      ``duration_ms`` / ``finished_at``.
    """
    cmd_str = _cmd_of(task)
    args = shlex.split(cmd_str)
    timeout = float(os.environ.get("TASKQ_TASK_TIMEOUT", _DEFAULT_TIMEOUT))

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