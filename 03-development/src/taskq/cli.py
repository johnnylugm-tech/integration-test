"""taskq CLI — submission + run commands.

[FR-01] Citations: SPEC.md §3 FR-01 (Task Submission and Validation).
[FR-02] Citations: SPEC.md §3 FR-02 (run single task by id; run --all
with ThreadPoolExecutor; single-task timeout → exit 4).
[FR-03] Citations: SPEC.md §3 FR-03 (circuit breaker consult before
each run; ``OPEN`` → exit 3 + stderr ``breaker open``, no subprocess).
[FR-04] Citations: SPEC.md §3 FR-04 (--cached consults the TTL cache;
TTL-fresh done entry replays without subprocess; miss/expired run
normally and refresh the cache on ``done`` only).
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .breaker import Breaker
from .cache import Cache, compute_signature
from .executor import run_task
from .store import TaskStore

# Maximum allowed command length per SPEC §3 FR-01 (長度規則).
MAX_COMMAND_LEN = 1000

# Shell-injection characters rejected per NFR-02.
_INJECTION_CHARS = set(";|$>`<")

# Statuses whose ``name`` collides with new submissions per SPEC §3 FR-01
# (名稱唯一規則).
_NAME_BLOCK_STATUSES = {"pending", "running"}

# Path of the persistent store, relative to $TASKQ_HOME.
_TASKS_FILE = "tasks.json"


def _store_path() -> Path:
    """Return the path to ``tasks.json`` inside ``$TASKQ_HOME``.

    Falls back to ``.taskq`` when the env var is unset so the function is
    callable outside the CLI test harness; production usage always sets it.
    """
    home = Path(os.environ.get("TASKQ_HOME", ".taskq"))
    return home / _TASKS_FILE


def _load_tasks(path: Path) -> list[dict[str, Any]]:
    """Load the existing task list, returning ``[]`` when absent."""
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, tasks: list[dict[str, Any]]) -> None:
    """Write ``tasks`` to ``path`` atomically (tmp file + rename)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _validate_command(cmd: str) -> str | None:
    """Return an error message if ``cmd`` violates validation; else ``None``.

    Order matches SPEC §3 FR-01 validation table.
    """
    if not cmd or not cmd.strip():
        return "command must not be empty"
    if len(cmd) > MAX_COMMAND_LEN:
        return f"command exceeds {MAX_COMMAND_LEN} chars"
    bad = sorted(c for c in cmd if c in _INJECTION_CHARS)
    if bad:
        return f"command contains forbidden characters: {''.join(bad)}"
    return None


def _name_conflicts(tasks: list[dict[str, Any]], name: str | None) -> bool:
    """Return True if ``name`` collides with a pending/running task."""
    if not name:
        return False
    return any(
        t.get("name") == name and t.get("status") in _NAME_BLOCK_STATUSES
        for t in tasks
    )


def submit_cmd(cmd: str, name: str | None, json_mode: bool) -> int:
    """Validate and persist a new task. Return the process exit code.

    [FR-01] Citations: SPEC.md §3 FR-01 (validation rules + happy path);
    NFR-02 (injection-char block list).

    Returns ``2`` on any validation rejection, ``0`` on success.
    """
    path = _store_path()

    err = _validate_command(cmd)
    if err is not None:
        print(err, file=sys.stderr)
        return 2

    tasks = _load_tasks(path)
    if _name_conflicts(tasks, name):
        print(f"name already in use: {name}", file=sys.stderr)
        return 2

    task_id = uuid.uuid4().hex[:8]
    task: dict[str, Any] = {
        "id": task_id,
        "status": "pending",
        "name": name,
        "command": cmd,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    tasks.append(task)
    _atomic_write(path, tasks)

    if json_mode:
        print(json.dumps({"id": task_id, "status": "pending"}))
    else:
        print(task_id)
    return 0


# Default max workers for ``run --all`` (SPEC §5.1 TASKQ_MAX_WORKERS).
_DEFAULT_MAX_WORKERS = 4


def _replay_from_cache(entry: dict[str, Any]) -> dict[str, Any]:
    """Build a result dict that mirrors a cached ``done`` entry.

    [FR-04] Citations: SPEC.md §3 FR-04 (replay applies the cached
    exit_code / stdout_tail / stderr_tail / duration_ms / finished_at
    without invoking subprocess; the task record must be tagged
    ``cached: True``).
    """
    return {
        "status": entry.get("status"),
        "exit_code": entry.get("exit_code"),
        "stdout_tail": entry.get("stdout_tail"),
        "stderr_tail": entry.get("stderr_tail"),
        "duration_ms": entry.get("duration_ms"),
        "finished_at": entry.get("finished_at"),
        "cached": True,
    }


def _run_for_store(task: dict, cached: bool) -> None:
    """Execute ``task`` (dict form, from store) and persist the result.

    [FR-02] Citations: SPEC.md §3 FR-02 (worker-pool callback; errors
    propagated via ``Future.result()``; concurrent writes serialise on
    ``TaskStore._lock``).
    [FR-04] Citations: SPEC.md §3 FR-04 (--cached consults the TTL
    cache; TTL-fresh done entry replays without subprocess; miss/expired
    runs normally and refreshes the cache on ``done`` only; writes are
    thread-safe via ``Cache._lock``).
    """
    cmd_str = task["command"]
    cache = Cache()

    if cached:
        signature = compute_signature(cmd_str)
        hit = cache.get(signature)
        if hit is not None:
            TaskStore().update_task(task["id"], **_replay_from_cache(hit))
            return

    result = run_task(task)
    if cached and result.get("status") == "done":
        cache.put(
            signature if cached else compute_signature(cmd_str),
            cmd_str,
            result,
            task["id"],
        )
    TaskStore().update_task(task["id"], **result)


def run_cmd(
    task_id: str | None,
    all_mode: bool,
    cached: bool,
    json_mode: bool,
) -> int:
    """Run a single task by id, or all pending tasks concurrently.

    [FR-02] Citations: SPEC.md §3 FR-02 (run single: exit 4 on timeout;
    run --all: ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS),
    thread-safe writes); NFR-03 (Lock-protected store updates).
    [FR-03] Citations: SPEC.md §3 FR-03 (breaker consulted before each
    run; ``OPEN`` → exit 3, stderr ``breaker open``, no subprocess).

    Returns the process exit code per SPEC §3 FR-05:

    * ``0`` success (single task done/failed, or --all completed).
    * ``2`` unknown task id (single mode).
    * ``3`` breaker OPEN (SPEC §3 FR-03).
    * ``4`` single task finished in ``timeout``.
    * ``1`` other internal error.
    """
    del json_mode  # FR-05 json output deferred to FR-05 implementation.

    # FR-03: consult the global breaker before doing any work. OPEN
    # state rejects the run immediately, without invoking subprocess.
    breaker = Breaker()
    if not breaker.try_acquire():
        print("breaker open", file=sys.stderr)
        return 3

    store = TaskStore()

    if all_mode:
        workers = int(os.environ.get("TASKQ_MAX_WORKERS", _DEFAULT_MAX_WORKERS))
        tasks = store.load_tasks()
        pending = [t for t in tasks if t.get("status") == "pending"]
        if not pending:
            return 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run_for_store, t, cached) for t in pending]
            for fut in futures:
                # Propagate exceptions so the pool surfaces failures.
                fut.result()
        return 0

    if task_id is not None:
        tasks = store.load_tasks()
        target = next((t for t in tasks if t.get("id") == task_id), None)
        if target is None:
            print(f"unknown task id: {task_id}", file=sys.stderr)
            return 2
        cmd_str = target["command"]
        cache = Cache()

        if cached:
            signature = compute_signature(cmd_str)
            hit = cache.get(signature)
            if hit is not None:
                store.update_task(task_id, **_replay_from_cache(hit))
                return 0

        result = run_task(target)
        if cached and result.get("status") == "done":
            cache.put(
                signature if cached else compute_signature(cmd_str),
                cmd_str,
                result,
                task_id,
            )
        store.update_task(task_id, **result)
        # SPEC §3 FR-02 / FR-05: single-task timeout → exit 4.
        if result.get("status") == "timeout":
            return 4
        return 0

    return 1