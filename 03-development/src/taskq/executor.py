"""[FR-02] 任務執行器 — subprocess execution + state machine.

Runs a pending task's command via ``subprocess.run(shlex.split(command),
capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)`` — never with a
shell (NFR-02, ``shell`` stays False) — and transitions the on-disk record
through the state machine ``pending → running → done | failed | timeout``.
Result fields ``exit_code`` / ``stdout_tail`` / ``stderr_tail`` /
``duration_ms`` / ``finished_at`` are persisted atomically under a shared
``threading.Lock``.

Citations:
  SPEC §3 FR-02 (exec form, state machine, result fields, --all concurrency,
  single-task timeout → exit 4).
  NFR-02 (no ``shell`` invocation anywhere in ``src/taskq/``).
  NFR-03 (atomic write of tasks.json after each terminal transition).
  NFR-08 (cross-thread shared Lock for the store write boundary).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Result-shape invariant (SPEC §3 FR-02 / NFR-04): stdout_tail / stderr_tail
# hold the LAST 2000 chars of captured output.
_TAIL_CHARS: int = 2000

# Default per-task deadline when ``TASKQ_TASK_TIMEOUT`` is unset (seconds).
_DEFAULT_TIMEOUT: float = 300.0

# Default ThreadPoolExecutor width when ``TASKQ_MAX_WORKERS`` is unset.
_DEFAULT_MAX_WORKERS: int = 4


def _iso_now() -> str:
    """Return current UTC time as an ISO-8601 string (matches test regex)."""
    return datetime.now(timezone.utc).isoformat()


def _tail(text: str | None) -> str:
    """Return the last ``_TAIL_CHARS`` chars of ``text`` ("" if None)."""
    if not text:
        return ""
    return text[-_TAIL_CHARS:]


def _timeout_seconds() -> float:
    """Resolve ``$TASKQ_TASK_TIMEOUT`` (seconds); fall back to the default."""
    raw = os.environ.get("TASKQ_TASK_TIMEOUT")
    if raw is None or raw.strip() == "":
        return _DEFAULT_TIMEOUT
    return float(raw)


def _max_workers() -> int:
    """Resolve ``$TASKQ_MAX_WORKERS`` (>=1); fall back to the default."""
    raw = os.environ.get("TASKQ_MAX_WORKERS")
    if raw is None or raw.strip() == "":
        return _DEFAULT_MAX_WORKERS
    return max(1, int(raw))


def _execute(command: str) -> dict[str, Any]:
    """Run ``command`` and return the terminal result fields.

    Uses the exec form (``shlex.split``) with the shell disabled — NFR-02
    forbids shell invocation on every path. Maps exit 0 → done, non-zero →
    failed, ``TimeoutExpired`` → timeout.
    """
    start = time.monotonic()
    argv = shlex.split(command)
    try:
        completed = subprocess.run(  # noqa: S603 — exec form, no shell (NFR-02)
            argv,
            capture_output=True,
            text=True,
            timeout=_timeout_seconds(),
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return {
            "status": "timeout",
            "exit_code": None,
            "stdout_tail": _tail(exc.stdout if isinstance(exc.stdout, str) else None),
            "stderr_tail": _tail(exc.stderr if isinstance(exc.stderr, str) else None),
            "duration_ms": duration_ms,
            "finished_at": _iso_now(),
        }

    duration_ms = int((time.monotonic() - start) * 1000)
    status = "done" if completed.returncode == 0 else "failed"
    return {
        "status": status,
        "exit_code": completed.returncode,
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
        "duration_ms": duration_ms,
        "finished_at": _iso_now(),
    }


def run_task(
    task_id: str,
    tasks_file: Path,
    load_tasks,
    atomic_write,
    lock: threading.Lock,
) -> str:
    """Execute a single pending task and persist its terminal result.

    Reads the command from the store under ``lock``, runs it outside the
    lock (so concurrent tasks overlap), then merges the result back into the
    record and atomically rewrites the store under ``lock``. Returns the
    terminal status string (``done`` / ``failed`` / ``timeout``).
    """
    with lock:
        tasks = load_tasks(tasks_file)
        record = tasks.get(task_id)
        command = record.get("command", "") if record else ""

    result = _execute(command)

    with lock:
        tasks = load_tasks(tasks_file)
        record = tasks.get(task_id, {})
        record.update(result)
        tasks[task_id] = record
        atomic_write(tasks_file, tasks)

    return result["status"]


def run_all(
    tasks_file: Path,
    load_tasks,
    atomic_write,
    lock: threading.Lock,
) -> dict[str, str]:
    """Run every ``pending`` task concurrently via ``ThreadPoolExecutor``.

    ``max_workers`` comes from ``$TASKQ_MAX_WORKERS`` (NFR-08). All store
    writes funnel through the shared ``lock`` so ``tasks.json`` never lands
    in a half-written state. Returns ``{task_id: terminal_status}``.
    """
    tasks = load_tasks(tasks_file)
    pending_ids = [tid for tid, rec in tasks.items() if rec.get("status") == "pending"]

    results: dict[str, str] = {}
    if not pending_ids:
        return results

    with ThreadPoolExecutor(max_workers=_max_workers()) as pool:
        futures = {
            pool.submit(run_task, tid, tasks_file, load_tasks, atomic_write, lock): tid
            for tid in pending_ids
        }
        for future in futures:
            tid = futures[future]
            results[tid] = future.result()
    return results
