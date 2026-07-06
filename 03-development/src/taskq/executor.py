"""[FR-02] taskq.executor — subprocess execution + state machine + concurrency.

Citations:
  - SRS.md §3 FR-02 (functional): taskq run <id> / run --all
  - SPEC.md §3 FR-02 (run state machine pending → running → done|failed|timeout)
  - SPEC.md §4 NFR-02 (no shell-True; shlex.split only)
  - SAD.md §2.5.4 (single subprocess call site; CLI exit-code constant)
  - SAD.md §3.3 (run flow: subprocess.run + status mapping)

Public API:
    ExecutionResult   — dataclass returned by ``execute`` / ``run_all``.
    EXIT_TIMEOUT = 4  — CLI exit code for single-run timeout (SPEC §7).
    execute(command, timeout=None)               → ExecutionResult
    run_all(commands, max_workers, timeout=None) → list[ExecutionResult]
"""

from __future__ import annotations

import shlex
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

__all__ = [
    "ExecutionResult",
    "EXIT_TIMEOUT",
    "MAX_TAIL_LEN",
    "execute",
    "run_all",
]


# CLI-side exit code for single-run timeout (SPEC.md §7 / FR-02 AC-FR-02-05).
EXIT_TIMEOUT = 4

# Subprocess stdout/stderr are truncated to the last N chars per SPEC.md §3 FR-02
# ("結果欄位: ... stdout_tail (末 2000 字元)、stderr_tail (末 2000 字元)").
MAX_TAIL_LEN = 2000


@dataclass
class ExecutionResult:
    """[FR-02] Outcome of executing a single shell command via ``execute()``.

    Fields mirror SPEC.md §3 FR-02 result fields:

    * ``command``     — the original command string (echoed for caller clarity).
    * ``exit_code``   — subprocess exit code, or ``None`` when the subprocess
                        was killed by timeout (no rc is produced).
    * ``stdout_tail`` — last ``MAX_TAIL_LEN`` chars of subprocess stdout.
    * ``stderr_tail`` — last ``MAX_TAIL_LEN`` chars of subprocess stderr.
    * ``duration_ms`` — wall-clock duration of the subprocess in milliseconds.
    * ``finished_at`` — ISO-8601 UTC timestamp marking when execution ended.
    * ``status``      — FR-02 state machine value:
                        ``"done"`` / ``"failed"`` / ``"timeout"``.
    """

    command: str
    exit_code: int | None
    stdout_tail: str
    stderr_tail: str
    duration_ms: int | float
    finished_at: str
    status: str


def _tail(text: str, n: int = MAX_TAIL_LEN) -> str:
    """Return the last ``n`` characters of ``text`` (FR-02 result field)."""

    if len(text) <= n:
        return text
    return text[-n:]


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (FR-02 finished_at)."""

    return datetime.now(timezone.utc).isoformat()


def execute(command: str, timeout: float | None = None) -> ExecutionResult:
    """[FR-02] Run ``command`` in a subprocess and return its ``ExecutionResult``.

    Implementation contract (SPEC.md §3 FR-02 + NFR-02):

    * Shells out via ``subprocess.run(shlex.split(command), capture_output=True,
      text=True, timeout=timeout, shell=False)``. The ``shell`` kwarg is
      **always** False (NFR-02 forbids the True form anywhere in the codebase).
      (single subprocess call site per SAD §2.5.4 + architecture constraint).
    * State mapping:
        exit 0                  → ``status="done"``
        non-zero exit           → ``status="failed"``
        ``TimeoutExpired``      → ``status="timeout"`` (exit_code is ``None``)

    ``timeout`` is optional; when ``None`` no subprocess timeout is applied
    (defaults are owned by ``config.get_task_timeout()`` in FR-03 callers).
    """

    args = shlex.split(command)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int(round((time.monotonic() - started) * 1000))
        stdout_partial = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr_partial = exc.stderr if isinstance(exc.stderr, str) else ""
        return ExecutionResult(
            command=command,
            exit_code=None,
            stdout_tail=_tail(stdout_partial),
            stderr_tail=_tail(stderr_partial),
            duration_ms=duration_ms,
            finished_at=_now_iso(),
            status="timeout",
        )

    duration_ms = int(round((time.monotonic() - started) * 1000))
    status = "done" if completed.returncode == 0 else "failed"
    return ExecutionResult(
        command=command,
        exit_code=completed.returncode,
        stdout_tail=_tail(completed.stdout or ""),
        stderr_tail=_tail(completed.stderr or ""),
        duration_ms=duration_ms,
        finished_at=_now_iso(),
        status=status,
    )


def run_all(
    commands: list[str],
    max_workers: int,
    timeout: float | None = None,
) -> list[ExecutionResult]:
    """[FR-02] Execute every ``command`` concurrently and return results in input order.

    Uses ``concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)`` per
    SPEC.md §3 FR-02 (``ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS)``).
    Results are returned in the same order as ``commands`` so the caller can
    correlate by index. No shared mutation of the task store is performed here —
    FR-02's "執行緒安全" guarantee refers to OTHER write paths (FR-01
    ``store.add_task`` + future FR-03 retry / breaker side-effects) that share
    ``store.lock()``; this function is a pure subprocess fan-out.
    """

    if not commands:
        return []

    workers = max(1, int(max_workers))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(execute, cmd, timeout) for cmd in commands]
        return [f.result() for f in futures]
