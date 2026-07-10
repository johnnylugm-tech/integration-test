"""taskq CLI -- submission + run + status + list + clear commands.

[FR-01] Citations: SPEC.md Sec.3 FR-01 (Task Submission and Validation).
[FR-02] Citations: SPEC.md Sec.3 FR-02 (run single task by id; run --all
with ThreadPoolExecutor; single-task timeout -> exit 4).
[FR-03] Citations: SPEC.md Sec.3 FR-03 (circuit breaker consult before
each run; OPEN -> exit 3 + stderr "breaker open", no subprocess).
[FR-04] Citations: SPEC.md Sec.3 FR-04 (--cached consults the TTL cache;
TTL-fresh done entry replays without subprocess; miss/expired run
normally and refresh the cache on "done" only).
[FR-05] Citations: SPEC.md Sec.3 FR-05 (5 subcommands submit/run/status/
list/clear; --json global flag emits single-line JSON; exit codes
0 success / 2 unknown-id / 3 breaker-open / 4 single-task-timeout / 1
other internal error; status <id> emits the canonical 9-field
projection; list --status S filters by status; clear deletes
the three data files atomically).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import executor
from .breaker import Breaker
from .cache import Cache, compute_signature
from .store import TaskStore

# Maximum allowed command length per SPEC Sec.3 FR-01 (length rule).
MAX_COMMAND_LEN = 1000

# Shell-injection characters rejected per NFR-02 (SPEC §3 FR-01 注入字元表).
_INJECTION_CHARS = set(";|&$><`")

# Statuses whose "name" collides with new submissions per SPEC Sec.3 FR-01
# (name uniqueness rule).
_NAME_BLOCK_STATUSES = {"pending", "running"}

# Path of the persistent store, relative to $TASKQ_HOME.
_TASKS_FILE = "tasks.json"

# Files managed under $TASKQ_HOME (SPEC Sec.5.2); clear removes all
# three atomically (FR-05).
_DATA_FILES = ("tasks.json", "breaker.json", "cache.json")

# Canonical 9-field projection for status <id> (SPEC Sec.3 FR-05).
_STATUS_KEYS = (
    "id",
    "command",
    "status",
    "exit_code",
    "stdout_tail",
    "stderr_tail",
    "duration_ms",
    "finished_at",
    "cached",
)


def _home() -> Path:
    """Return $TASKQ_HOME, falling back to .taskq."""
    return Path(os.environ.get("TASKQ_HOME", ".taskq"))


def _store_path() -> Path:
    """Return the path to tasks.json inside $TASKQ_HOME.

    Falls back to .taskq when the env var is unset so the function is
    callable outside the CLI test harness; production usage always sets it.
    """
    return _home() / _TASKS_FILE


def _load_tasks(path: Path) -> list[dict[str, Any]]:
    """Load the existing task list, returning [] when absent."""
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, tasks: list[dict[str, Any]]) -> None:
    """Write tasks to path atomically (tmp file + rename)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _validate_command(cmd: str) -> str | None:
    """Return an error message if cmd violates validation; else None.

    Order matches SPEC Sec.3 FR-01 validation table.
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
    """Return True if name collides with a pending/running task."""
    if not name:
        return False
    return any(
        t.get("name") == name and t.get("status") in _NAME_BLOCK_STATUSES
        for t in tasks
    )


def submit_cmd(cmd: str, name: str | None, json_mode: bool) -> int:
    """Validate and persist a new task. Return the process exit code.

    [FR-01] Citations: SPEC.md Sec.3 FR-01 (validation rules + happy path);
    NFR-02 (injection-char block list).
    [FR-05] Citations: SPEC.md Sec.3 FR-05 (--json emits
    {"id", "status": "pending"} on a single line; non-JSON prints
    just the bare task id).

    Returns 2 on any validation rejection, 0 on success.
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


# Default max workers for run --all (SPEC Sec.5.1 TASKQ_MAX_WORKERS).
_DEFAULT_MAX_WORKERS = 4


def _replay_from_cache(entry: dict[str, Any]) -> dict[str, Any]:
    """Build a result dict that mirrors a cached done entry.

    [FR-04] Citations: SPEC.md Sec.3 FR-04 (replay applies the cached
    exit_code / stdout_tail / stderr_tail / duration_ms / finished_at
    without invoking subprocess; the task record must be tagged
    cached: True).
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
    """Execute task (dict form, from store) and persist the result.

    [FR-02] Citations: SPEC.md Sec.3 FR-02 (worker-pool callback; errors
    propagated via Future.result(); concurrent writes serialise on
    TaskStore._lock).
    [FR-04] Citations: SPEC.md Sec.3 FR-04 (--cached consults the TTL
    cache; TTL-fresh done entry replays without subprocess; miss/expired
    runs normally and refreshes the cache on "done" only; writes are
    thread-safe via Cache._lock).
    """
    cmd_str = task["command"]
    cache = Cache()
    signature = compute_signature(cmd_str) if cached else ""

    if cached:
        hit = cache.get(signature)
        if hit is not None:
            TaskStore().update_task(task["id"], **_replay_from_cache(hit))
            return

    result = executor.run_task(task)
    if cached and result.get("status") == "done":
        cache.put(
            signature,
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

    [FR-02] Citations: SPEC.md Sec.3 FR-02 (run single: exit 4 on timeout;
    run --all: ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS),
    thread-safe writes); NFR-03 (Lock-protected store updates).
    [FR-03] Citations: SPEC.md Sec.3 FR-03 (breaker consulted before each
    run; OPEN -> exit 3, stderr "breaker open", no subprocess).

    Returns the process exit code per SPEC Sec.3 FR-05:

    * 0 success (single task done/failed, or --all completed).
    * 2 unknown task id (single mode).
    * 3 breaker OPEN (SPEC Sec.3 FR-03).
    * 4 single task finished in timeout.
    * 1 other internal error.
    """
    del json_mode  # FR-05 json output deferred to per-subcommand handlers.

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
        signature = compute_signature(cmd_str) if cached else ""

        if cached:
            hit = cache.get(signature)
            if hit is not None:
                store.update_task(task_id, **_replay_from_cache(hit))
                return 0

        result = executor.run_task(target)
        if cached and result.get("status") == "done":
            cache.put(
                signature,
                cmd_str,
                result,
                task_id,
            )
        store.update_task(task_id, **result)
        # SPEC Sec.3 FR-02 / FR-05: single-task timeout -> exit 4.
        if result.get("status") == "timeout":
            return 4
        return 0

    return 1


def status_cmd(task_id: str, json_mode: bool) -> int:
    """Print the canonical 9-field projection of task_id (FR-05).

    [FR-05] Citations: SPEC.md Sec.3 FR-05 (status <id> emits
    id/command/status/exit_code/stdout_tail/stderr_tail/duration_ms/
    finished_at/cached as a JSON document on a single line; unknown id
    -> stderr message + exit 2).
    """
    tasks = _load_tasks(_store_path())
    target = next((t for t in tasks if t.get("id") == task_id), None)
    if target is None:
        print(f"unknown task id: {task_id}", file=sys.stderr)
        return 2
    payload = {k: target.get(k) for k in _STATUS_KEYS}
    if json_mode:
        print(json.dumps(payload))
    else:
        print(json.dumps(payload, indent=2))
    return 0


def list_cmd(filter_status: str | None, json_mode: bool) -> int:
    """List tasks, optionally filtered by status (FR-05).

    [FR-05] Citations: SPEC.md Sec.3 FR-05 (list --status S yields
    matching records only; --json wraps the filtered set in a single
    JSON document; non-JSON prints one record per line).
    """
    tasks = _load_tasks(_store_path())
    if filter_status is not None:
        tasks = [t for t in tasks if t.get("status") == filter_status]
    if json_mode:
        print(json.dumps(tasks))
    else:
        for t in tasks:
            print(json.dumps(t, ensure_ascii=False))
    return 0


def clear_cmd(json_mode: bool) -> int:
    """Delete the three persistent data files atomically (FR-05).

    [FR-05] Citations: SPEC.md Sec.3 FR-05 (clear removes tasks.json
    + breaker.json + cache.json; --json emits {"cleared": [...]};
    missing files are reported as not-cleared but do not fail the
    command).
    """
    home = _home()
    cleared: list[str] = []
    for fname in _DATA_FILES:
        p = home / fname
        if p.exists():
            p.unlink()
            cleared.append(fname)
    if json_mode:
        print(json.dumps({"cleared": cleared}))
    else:
        print("cleared: " + ", ".join(cleared))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argparse parser with five subcommands (FR-05).

    [FR-05] Citations: SPEC.md Sec.3 FR-05 (submit/run/status/list/clear
    subcommands; --json global flag; --all + --cached on run; --status
    filter on list).
    """
    parser = argparse.ArgumentParser(
        prog="taskq",
        description="taskq CLI (FR-05: submit/run/status/list/clear).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_mode",
        help="emit single-line JSON output (machine-readable)",
    )
    sub = parser.add_subparsers(dest="subcommand")
    # Expose the subparsers group on the parent parser so callers can
    # introspect ``parser.subparsers.choices`` to verify the canonical
    # 5 subcommands are registered.
    parser.subparsers = sub  # type: ignore[attr-defined]

    p_submit = sub.add_parser("submit", help="submit a new task")
    p_submit.add_argument("command", help="shell command to persist")
    p_submit.add_argument(
        "--name", default=None, help="optional human-readable name"
    )

    p_run = sub.add_parser("run", help="run a task by id (or --all)")
    p_run.add_argument("task_id", nargs="?", default=None)
    p_run.add_argument(
        "--all", action="store_true", dest="all_mode",
        help="run every pending task concurrently",
    )
    p_run.add_argument(
        "--cached", action="store_true", help="consult TTL cache (FR-04)"
    )

    p_status = sub.add_parser("status", help="print task status fields")
    p_status.add_argument("task_id", help="8-char task id")

    p_list = sub.add_parser("list", help="list tasks (optionally filtered)")
    p_list.add_argument(
        "--status", dest="filter_status", default=None,
        help="filter by status (e.g. pending, running, done, failed, timeout)",
    )

    sub.add_parser("clear", help="delete all TASKQ_HOME data files")

    return parser


def run_cli(argv: list[str]) -> int:
    """Top-level entry point dispatching to the five subcommands (FR-05).

    [FR-05] Citations: SPEC.md Sec.3 FR-05 (parse + dispatch; top-level
    exit codes per the spec table 0/2/3/4/1; any unexpected exception
    surfaced from a subcommand is funnelled to exit 1).

    Returns the process exit code.
    """
    parser = build_parser()
    try:
        args = parser.parse_args(argv[1:])
    except SystemExit as exc:
        # argparse calls SystemExit(2) on bad args; normalise unknown
        # CLI failures to exit 1.
        return 1 if exc.code in (None, 2) else int(exc.code)

    sub = args.subcommand
    json_mode = bool(getattr(args, "json_mode", False))

    try:
        if sub == "submit":
            return submit_cmd(args.command, args.name, json_mode)
        if sub == "run":
            return run_cmd(
                task_id=args.task_id,
                all_mode=args.all_mode,
                cached=args.cached,
                json_mode=json_mode,
            )
        if sub == "status":
            return status_cmd(args.task_id, json_mode)
        if sub == "list":
            return list_cmd(args.filter_status, json_mode)
        if sub == "clear":
            return clear_cmd(json_mode)
    except Exception as exc:  # pragma: no cover -- defensive funnel
        # FR-05: any unexpected error path surfaces exit 1; emit the
        # exception class name (not just the message) so callers can
        # distinguish it from a validation-rule stderr line.
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    # No subcommand provided.
    parser.print_help()
    return 1
