"""[FR-02] 任務執行器 — subprocess execution + state machine.

Runs a pending task's command via ``subprocess.run(shlex.split(command),
capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)`` — never with a
shell (NFR-02, ``shell`` stays False) — and transitions the on-disk record
through the state machine ``pending → running → done | failed | timeout``.
Result fields ``exit_code`` / ``stdout_tail`` / ``stderr_tail`` /
``duration_ms`` / ``finished_at`` are persisted atomically under a shared
``threading.Lock``.

[FR-03] retry loop + circuit-breaker hook.

The ``run_task`` path now wraps ``_execute`` in ``retry`` (bounded by
``$TASKQ_RETRY_LIMIT`` with exponential backoff
``$TASKQ_BACKOFF_BASE × 2^n`` before the n-th retry) and persists an
``attempts`` counter on the record. The ``sleep`` callable is injected
through the module-level ``executor.sleep`` attribute so tests can
substitute a no-op / recording mock via ``monkeypatch.setattr`` per
SPEC §3 FR-03 design note ``sleep 函式必須可注入以利測試``.

Citations:
  SPEC §3 FR-02 (exec form, state machine, result fields, --all concurrency,
  single-task timeout → exit 4).
  SPEC §3 FR-03 (retry/breaker contract; backoff sequence; attempts counter).
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
from typing import Any, Callable

# Result-shape invariant (SPEC §3 FR-02 / NFR-04): stdout_tail / stderr_tail
# hold the LAST 2000 chars of captured output.
_TAIL_CHARS: int = 2000

# Default per-task deadline when ``TASKQ_TASK_TIMEOUT`` is unset (seconds).
_DEFAULT_TIMEOUT: float = 300.0

# Default ThreadPoolExecutor width when ``TASKQ_MAX_WORKERS`` is unset.
_DEFAULT_MAX_WORKERS: int = 4

# Default retry budget (SPEC §3 FR-03 — 0 = no retries).
_DEFAULT_RETRY_LIMIT: int = 0

# Default backoff base (seconds) — multiplied by ``2 ** n`` before retry n.
_DEFAULT_BACKOFF_BASE: float = 1.0


# ---------------------------------------------------------------------------
# Module-level injection point (SPEC §3 FR-03 — ``sleep`` must be injectable
# so unit tests can substitute a no-op or recording mock).
# ---------------------------------------------------------------------------
sleep: Callable[[float], None] = time.sleep


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


def _retry_limit() -> int:
    """Resolve ``$TASKQ_RETRY_LIMIT`` (>= 0); fall back to the default."""
    raw = os.environ.get("TASKQ_RETRY_LIMIT")
    if raw is None or raw.strip() == "":
        return _DEFAULT_RETRY_LIMIT
    return max(0, int(raw))


def _backoff_base() -> float:
    """Resolve ``$TASKQ_BACKOFF_BASE`` (>= 0 seconds); fall back to default."""
    raw = os.environ.get("TASKQ_BACKOFF_BASE")
    if raw is None or raw.strip() == "":
        return _DEFAULT_BACKOFF_BASE
    return max(0.0, float(raw))


def _resolve_sleep(sleep_override: Callable[[float], None] | None) -> Callable[[float], None]:
    """Return the override if given, else the module-level ``sleep`` (monkeypatchable)."""
    if sleep_override is not None:
        return sleep_override
    return globals()["sleep"]


def _build_result(
    status: str,
    exit_code: int | None,
    stdout: str | None,
    stderr: str | None,
    start: float,
) -> dict[str, Any]:
    """Assemble a terminal-state result record with timing + tails.

    Captures ``duration_ms`` (``int`` milliseconds since ``start``) and
    ``finished_at`` (ISO-8601 timestamp) at a SINGLE instant so the two
    fields stay consistent across records.
    """
    return {
        "status": status,
        "exit_code": exit_code,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
        "duration_ms": int((time.monotonic() - start) * 1000),
        "finished_at": _iso_now(),
    }


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
        return _build_result(
            "timeout",
            None,
            exc.stdout if isinstance(exc.stdout, str) else None,
            exc.stderr if isinstance(exc.stderr, str) else None,
            start,
        )

    return _build_result(
        "done" if completed.returncode == 0 else "failed",
        completed.returncode,
        completed.stdout,
        completed.stderr,
        start,
    )


def _retry_with_attempts(
    command: str,
    sleep_fn: Callable[[float], None],
) -> tuple[dict[str, Any], int]:
    """Run ``retry``-style loop and return (last_result, attempts_count).

    Identical to ``retry`` but exposes both the full last result dict (for
    persistence under the lock) and the attempt count (for the ``attempts``
    record field). ``run_task`` calls this; the public ``retry`` shim
    delegates here for the canonical return type.

    Citations:
      SPEC §3 FR-03 (retry loop + backoff formula; sleep must be injectable).
    """
    limit = _retry_limit()
    backoff_base = _backoff_base()
    last_result: dict[str, Any] = {}
    attempts = 0
    for n in range(limit + 1):
        if n > 0:
            sleep_fn(backoff_base * (2 ** n))
        attempts += 1
        last_result = _execute(command)
        if last_result["status"] == "done":
            break
    return last_result, attempts


def retry(command: str, *, sleep: Callable[[float], None] | None = None) -> str:
    """Run ``command`` with retry + exponential backoff; return final status.

    The n-th retry (1-based; ``n=1..retry_limit``) is preceded by a call to
    ``sleep(BACKOFF_BASE × 2 ** n)``. The initial attempt is NOT preceded by
    a sleep. Loop exits early on the first ``done``; otherwise it runs
    ``1 + retry_limit`` attempts and returns the last terminal status.

    The ``sleep`` parameter shadows the module-level ``sleep`` attribute
    intentionally: callers (e.g. the FR-03 unit test) pass an explicit
    recording mock, while the ``run_task`` path passes ``None`` and falls
    back to the module attribute (which ``monkeypatch.setattr`` can
    replace for end-to-end coverage). Delegates to ``_retry_with_attempts``
    so the retry loop body lives in exactly one place.
    """
    sleep_fn = _resolve_sleep(sleep)
    last_result, _attempts = _retry_with_attempts(command, sleep_fn)
    return last_result["status"]


def run_task(
    task_id: str,
    tasks_file: Path,
    load_tasks,
    atomic_write,
    lock: threading.Lock,
    *,
    sleep: Callable[[float], None] | None = None,
    breaker: Any | None = None,
) -> str | None:
    """Execute a pending task with retry + breaker hook; persist terminal state.

    Reads the command from the store under ``lock``, calls ``before_run`` on
    the breaker (if provided) — a False return short-circuits with NO write
    to ``tasks.json`` (the task stays ``pending`` per SPEC §3 FR-03 AC-04).
    The retry loop runs outside the lock so concurrent tasks overlap; the
    final record (status + result fields + ``attempts``) is merged back and
    atomically rewritten under the lock. The breaker is then informed of the
    terminal outcome (success → ``record_success``; failure/timeout →
    ``record_failure``).

    Returns the terminal status string (``done`` / ``failed`` / ``timeout``),
    or ``None`` if the breaker rejected the run before any subprocess call.
    """
    if breaker is not None and not breaker.before_run():
        return None

    sleep_fn = _resolve_sleep(sleep)

    with lock:
        tasks = load_tasks(tasks_file)
        record = tasks.get(task_id)
        command = record.get("command", "") if record else ""

    last_result, attempts = _retry_with_attempts(command, sleep_fn)
    last_status = last_result["status"]

    if breaker is not None:
        if last_status == "done":
            breaker.record_success()
        else:
            breaker.record_failure()

    with lock:
        tasks = load_tasks(tasks_file)
        record = tasks.get(task_id, {})
        record.update(last_result)
        record["attempts"] = attempts
        tasks[task_id] = record
        atomic_write(tasks_file, tasks)

    return last_status


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
