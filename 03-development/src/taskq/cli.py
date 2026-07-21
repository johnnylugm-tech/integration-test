"""[FR-01] Command-line interface for ``taskq``.

Dispatches ``submit`` subcommand and persists pending tasks to
``$TASKQ_HOME/tasks.json`` via an atomic tmp-file + ``os.replace`` write.

Citations:
  SPEC §3 FR-01 (validation rules + AC-FR01-01..09).
  SAD §3.1 (cli / store split + atomic-write boundary; lines 82, 222).
  ADR-002 (storage layout — single ``tasks.json`` keyed by 8-hex id),
  ADR-004 (atomic-write primitive: tmp + ``os.replace``),
  ADR-011 (id format = ``uuid4().hex[:8]``).
  NFR-02 injection blacklist — `;&$><\\`` rejected before write.
  NFR-03 atomic-write invariant — pre-existing content preserved on failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from taskq import breaker as breaker_mod
from taskq import executor

# NFR-02: shell-metacharacter blacklist. Each char in this set is a hard
# reject — submitting a command containing ANY of them exits 2 with stderr
# and never touches the store. (SPEC §3 FR-01 row 3; SAD line 304.)
_INJECTION_CHARS: frozenset[str] = frozenset(";|&$><`")

# SPEC §3 FR-01 row 2: command length must not exceed 1000 chars.
_MAX_COMMAND_LEN: int = 1000

# ADR-011: task id = first 8 hex chars of uuid4 (16^8 = 4.29B namespace).
_ID_LEN: int = 8

# Active task statuses that hold a name lock (SPEC §3 FR-01 row 4).
_ACTIVE_STATUSES: frozenset[str] = frozenset({"pending", "running"})


def _iso_now() -> str:
    """Return current UTC time as ISO-8601 (matches test regex)."""
    return datetime.now(timezone.utc).isoformat()


def _taskq_home() -> Path:
    """Resolve ``$TASKQ_HOME``; default to ``.`` if unset (test fixture always sets it)."""
    home = os.environ.get("TASKQ_HOME")
    return Path(home) if home else Path(".")


def _tasks_path() -> Path:
    """Return the on-disk tasks.json path under ``$TASKQ_HOME``."""
    return _taskq_home() / "tasks.json"


def _load_tasks(path: Path) -> dict[str, dict]:
    """Load tasks.json; return empty dict if missing or corrupt."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write_json(path: Path, data: dict) -> None:
    """Atomic write: dump to ``<path>.tmp`` then ``os.replace`` onto ``path``.

    NFR-03 invariant (SAD line 222): on ``OSError`` from ``os.replace`` the
    destination is NEVER truncated — only the sibling ``.tmp`` is created and
    cleaned up. The failure propagates so the caller can surface a non-zero
    exit code without corrupting on-disk state.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True))
    try:
        os.replace(tmp_path, path)
    except OSError:
        # Best-effort cleanup of the orphan temp; never raise from cleanup.
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def _validate_command(command: str) -> str | None:
    """Return an error message if the command violates a FR-01 rule, else None."""
    if not command or not command.strip():
        return "command must not be empty or whitespace-only"
    if len(command) > _MAX_COMMAND_LEN:
        return (
            f"command length ({len(command)}) exceeds maximum "
            f"({_MAX_COMMAND_LEN}) characters"
        )
    for ch in _INJECTION_CHARS:
        if ch in command:
            return f"command contains forbidden character: {ch!r}"
    return None


def submit_command(argv: Sequence[str]) -> int:
    """Handle ``taskq submit [--json] [--name NAME] COMMAND``.

    Returns 0 on success (id or JSON printed to stdout), 2 on validation
    failure (error message printed to stderr), 1 on storage failure
    (error printed to stderr, on-disk state preserved).
    """
    parser = argparse.ArgumentParser(prog="taskq submit", add_help=False)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--name", default="")
    parser.add_argument("command", nargs=1)
    args = parser.parse_args(list(argv))
    command = args.command[0]

    err = _validate_command(command)
    if err is not None:
        print(f"error: {err}", file=sys.stderr)
        return 2

    name = args.name
    tasks_file = _tasks_path()

    tasks = _load_tasks(tasks_file)
    if name:
        for record in tasks.values():
            if record.get("name") == name and record.get("status") in _ACTIVE_STATUSES:
                print(
                    f"error: name {name!r} already in use by an active task",
                    file=sys.stderr,
                )
                return 2

    task_id = uuid.uuid4().hex[:_ID_LEN]
    new_record: dict[str, str] = {
        "command": command,
        "name": name,
        "status": "pending",
        "created_at": _iso_now(),
    }

    tasks[task_id] = new_record
    try:
        _atomic_write_json(tasks_file, tasks)
    except OSError as exc:
        print(f"error: failed to persist task: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"id": task_id, "status": "pending"}))
    else:
        print(task_id)
    return 0


def run_command(argv: Sequence[str]) -> int:
    """Handle ``taskq run <id>`` and ``taskq run --all`` [FR-02].

    Single-task mode: runs one task by id and returns 4 iff the task hit the
    ``timeout`` terminal state (SPEC §3 FR-02 single-task timeout → exit 4),
    else 0 (the run itself completed, even for a ``failed`` inner command).
    ``--all`` mode: runs every pending task concurrently and returns 0.

    Citations:
      SPEC §3 FR-02 (run <id> / run --all, state machine, exit 4 on timeout).
      NFR-08 (shared Lock across ThreadPoolExecutor writers).
    """
    parser = argparse.ArgumentParser(prog="taskq run", add_help=False)
    parser.add_argument("--all", action="store_true", dest="run_all")
    parser.add_argument("task_id", nargs="?")
    args = parser.parse_args(list(argv))

    tasks_file = _tasks_path()
    lock = threading.Lock()

    if args.run_all:
        executor.run_all(tasks_file, _load_tasks, _atomic_write_json, lock)
        return 0

    if not args.task_id:
        print("error: run requires a task id or --all", file=sys.stderr)
        return 2

    breaker = breaker_mod.Breaker()
    status = executor.run_task(
        args.task_id,
        tasks_file,
        _load_tasks,
        _atomic_write_json,
        lock,
        breaker=breaker,
    )
    if status is None:
        # FR-03 AC-04: ``breaker open`` → exit 3, no subprocess, no task
        # transition. The substring ``breaker open`` is asserted by tests.
        print("error: breaker open", file=sys.stderr)
        return 3
    return 4 if status == "timeout" else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Top-level CLI dispatcher.

    Returns the process exit code for ``python -m taskq <args>``.
    """
    if argv is None:
        argv = sys.argv[1:]
    subcommand = argv[0]
    if subcommand == "submit":
        return submit_command(argv[1:])
    if subcommand == "run":
        return run_command(argv[1:])
    print(f"error: unknown command {subcommand!r}", file=sys.stderr)
    return 2