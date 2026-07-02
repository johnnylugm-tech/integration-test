"""Task execution with timeout, retry, and redaction.

[FR-02] Citations:
- SPEC.md §3 FR-02 ("subprocess.run(shlex.split(command), capture_output=True,
  text=True, timeout=TASKQ_TASK_TIMEOUT)"): `_run_once`.
- SPEC.md §3 FR-02 ("任何路徑不得使用 shell=True"): enforced here as the sole
  subprocess chokepoint per SAD §4.2 / NFR-02.
- SPEC.md §3 FR-02 status machine: pending → running → done | failed | timeout.
- SPEC.md §3 FR-02 result fields: exit_code, stdout_tail (last 2000 chars),
  stderr_tail (last 2000 chars), duration_ms, finished_at.
- SPEC.md §3 FR-02 retry: run 結果為 failed/timeout 時自動重試,上限
  TASKQ_RETRY_LIMIT 次(預設 2). Per SAD §2.3 / D-02:
  TASKQ_RETRY_LIMIT retries on top of the initial execution →
  total attempts ∈ [1, TASKQ_RETRY_LIMIT + 1].
- SPEC.md §4 NFR-03: stdout_tail/stderr_tail redacted via `redact.redact`
  before persistence.
- SAD.md §4.2: this module is the SOLE chokepoint for subprocess invocation.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from taskq.redact import redact as _redact_fn
from taskq.config import retry_limit, task_timeout
from taskq.store import (
    StoreCorruptedError,
    atomic_write_tasks,
    load_tasks_or_die,
)


# [FR-02] SPEC.md §3 FR-02 ("stdout_tail (末 2000 字元)、stderr_tail (末 2000
# 字元)"): tail truncation cap.
_TAIL_LIMIT = 2000


# [FR-02] SPEC.md §3 exit-code mapping (single-task mode):
#   0  success / failed-exhausted
#   4  timeout-exhausted
#   1  other internal error / unhandled exception
#   2  unknown task id (validation-level reject)
EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_REJECTED = 2
EXIT_TIMEOUT = 4


def _truncate_tail(text: str | None) -> str:
    """Return the trailing `len <= 2000` chars of `text`.

    [FR-02] SPEC.md §3 FR-02 ("stdout_tail (末 2000 字元)、stderr_tail
    (末 2000 字元)").
    """
    if not text:
        return ""
    return text[-_TAIL_LIMIT:]


def _now_iso() -> str:
    """Return current UTC time in ISO-8601 (with timezone offset)."""
    return datetime.now(timezone.utc).isoformat()


class UnknownTaskError(Exception):
    """Raised when the requested task id is not present in the store.

    [FR-02] SPEC.md §3 (status <id>: unknown id → exit 2 + stderr message).
    """


class TaskNotFoundError(UnknownTaskError):
    """[FR-02] Alias used by the `run` dispatch to map to exit 2."""


def _save_task(tasks: list[dict[str, Any]], task_id: str) -> None:
    """Persist `tasks` atomically; surface corruption as StoreCorruptedError.

    [FR-01] SPEC.md §3 FR-01 ("原子寫入 $TASKQ_HOME/tasks.json
    (tmp + os.replace)").
    """
    atomic_write_tasks(tasks, task_id)


def _run_once(command: str, timeout: float) -> dict[str, Any]:
    """Execute one subprocess invocation and return a partial result dict.

    [FR-02] SPEC.md §3 FR-02: subprocess.run(shlex.split(command),
    capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT).
    NO `shell=True` (NFR-02 invariant — SAD §4.2).

    Returns a dict with keys: status, exit_code, stdout_tail, stderr_tail,
    duration_ms, finished_at.
    """
    started = time.monotonic()
    start_iso = _now_iso()
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        # Malformed shell quoting is a user-input error → not retriable.
        return {
            "status": "failed",
            "exit_code": None,
            "stdout_tail": "",
            "stderr_tail": f"command parse error: {exc}",
            "duration_ms": 0,
            "finished_at": start_iso,
            "_error": "parse",
        }

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,  # explicit per NFR-02; never set shell=True.
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        # `exc.stdout` / `exc.stderr` may be bytes or str depending on
        # capture mode; we passed text=True, so str.
        stdout_partial = str(exc.stdout or "")
        stderr_partial = str(exc.stderr or "")
        return {
            "status": "timeout",
            "exit_code": None,
            "stdout_tail": _redact_fn(_truncate_tail(stdout_partial)),
            "stderr_tail": _redact_fn(_truncate_tail(stderr_partial)),
            "duration_ms": duration_ms,
            "finished_at": _now_iso(),
        }
    except (subprocess.SubprocessError, OSError):
        # Other subprocess / OS-level errors (including FileNotFoundError
        # when the binary path is missing) propagate so `run_task` can
        # record the partial-failure state and re-raise as
        # UnhandledExecutionError → CLI exit 1.
        raise

    duration_ms = int((time.monotonic() - started) * 1000)
    rc = proc.returncode
    if rc == 0:
        status = "done"
    else:
        status = "failed"
    return {
        "status": status,
        "exit_code": rc,
        "stdout_tail": _redact_fn(_truncate_tail(proc.stdout or "")),
        "stderr_tail": _redact_fn(_truncate_tail(proc.stderr or "")),
        "duration_ms": duration_ms,
        "finished_at": _now_iso(),
    }


class UnhandledExecutionError(Exception):
    """Raised when subprocess invocation fails outside the retry contract.

    [FR-02] SPEC.md §3 FR-02 ("其他未預期例外 → exit 1"): the CLI maps this
    to exit code 1. Carries the persisted task record so the CLI can emit
    it on stdout (callers still want to observe the failure state).
    """


def run_task(task_id: str) -> dict[str, Any]:
    """Execute `task_id` with timeout + retry + redaction.

    [FR-02] SPEC.md §3 FR-02: load the task, mark running, subprocess.run,
    transition to done/failed/timeout, truncate + redact tails, persist;
    retry on failed/timeout up to TASKQ_RETRY_LIMIT times (so total
    attempts ≤ TASKQ_RETRY_LIMIT + 1 per D-02).

    Returns the final task record (dict) with all FR-02 result fields
    populated. The caller (`cli.cmd_run`) maps the terminal status to
    the appropriate process exit code. If the underlying subprocess
    raises an unhandled exception (e.g. binary not found — FileNotFoundError),
    the task is persisted with status='failed' and this function re-raises
    `UnhandledExecutionError` so the CLI can emit exit code 1.
    """
    try:
        tasks = load_tasks_or_die()
    except StoreCorruptedError:
        raise

    target: dict[str, Any] | None = None
    for t in tasks:
        if isinstance(t, dict) and t.get("id") == task_id:
            target = t
            break
    if target is None:
        raise UnknownTaskError(f"unknown task: {task_id}")

    timeout = task_timeout()
    max_retries = retry_limit()
    # Per SAD §2.3 / D-02: total attempts ≤ retry_limit + 1 (1 initial + N
    # retries). We loop while attempts < max_retries + 1.
    attempts = int(target.get("attempts", 0))

    # Unhandled exceptions must propagate so the CLI maps them to exit 1
    # (no bare except: swallowing). Capture the original exception so we
    # can persist a partial failure record before re-raising.
    unhandled_exc: Exception | None = None

    while attempts < max_retries + 1:
        # Mark running.
        target["status"] = "running"
        target["attempts"] = attempts
        _save_task(tasks, task_id)

        try:
            result = _run_once(target["command"], timeout)
        except FileNotFoundError as exc:
            # The requested binary does not exist on disk — this is not a
            # retry-able failure (the path is fixed for this task). Mark
            # the task failed once, persist, then bubble up so the CLI
            # emits exit 1.
            started_mono = time.monotonic()
            target["status"] = "failed"
            target["exit_code"] = None
            target["stdout_tail"] = ""
            target["stderr_tail"] = _redact_fn(
                _truncate_tail(f"{type(exc).__name__}: {exc}")
            )
            target["duration_ms"] = int((time.monotonic() - started_mono) * 1000)
            target["finished_at"] = _now_iso()
            attempts += 1
            target["attempts"] = attempts
            _save_task(tasks, task_id)
            unhandled_exc = exc
            break

        # Apply the partial result fields to the persisted task.
        target["status"] = result["status"]
        # [FR-02] SPEC.md §3 FR-02 exit-code mapping: timeout → exit 4.
        # Encode that on the task's `exit_code` field too so status-query
        # callers see the same value the CLI emits.
        if result["status"] == "timeout":
            target["exit_code"] = EXIT_TIMEOUT
        else:
            target["exit_code"] = result["exit_code"]
        target["stdout_tail"] = result["stdout_tail"]
        target["stderr_tail"] = result["stderr_tail"]
        target["duration_ms"] = result["duration_ms"]
        target["finished_at"] = result["finished_at"]

        attempts += 1
        target["attempts"] = attempts
        _save_task(tasks, task_id)

        # Decide whether to retry.
        if result["status"] in {"failed", "timeout"} and attempts < max_retries + 1:
            # Loop: reset status back to running on next iteration via
            # the assignment above.
            continue
        break

    if unhandled_exc is not None:
        # [FR-02] SPEC.md §3 FR-02 ("其他未預期例外 → exit 1"): the CLI
        # catches `UnhandledExecutionError` and exits 1; the persisted
        # record is still returned so the CLI can write it to stdout.
        raise UnhandledExecutionError(str(unhandled_exc)) from unhandled_exc

    return target