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
from taskq import cache as cache_mod
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


class _CorruptStoreError(Exception):
    """[FR-05] Raised when ``tasks.json`` holds invalid JSON.

    SPEC §7 maps ``其他內部錯誤`` (internal error) → exit 1: a corrupt store
    must surface the failure (NFR-03 forbids a silent rebuild), so the strict
    loader raises this instead of swallowing the ``JSONDecodeError`` the way
    the lenient :func:`_load_tasks` does for the write-side FR-01 path.

    Citations:
      SPEC §3 FR-05 / §7 (exit-code map — internal error → exit 1 + stderr).
      NFR-03 (no silent rebuild of a corrupt data file).
    """


def _load_tasks_strict(path: Path) -> dict[str, dict]:
    """[FR-05] Load tasks.json, raising ``_CorruptStoreError`` on bad JSON.

    A missing file is a legitimate empty store (``{}``); only invalid JSON is
    an internal error. Used by the read-side subcommands (``status`` / ``list``
    / ``run``) so corruption maps to exit 1 rather than a silent empty view.

    Citations:
      SPEC §3 FR-05 / §7 (unknown / internal error exit-code map — lines
      referenced in TEST_SPEC.md §FR-05).
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise _CorruptStoreError(
            f"corrupt task store {path}: {exc}"
        ) from exc
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


def _cache_path() -> Path:
    """Return the on-disk cache.json path under ``$TASKQ_HOME`` [FR-04]."""
    return _taskq_home() / "cache.json"


def run_command(argv: Sequence[str]) -> int:
    """Handle ``taskq run <id>`` and ``taskq run --all`` [FR-02][FR-04].

    Single-task mode: runs one task by id and returns 4 iff the task hit the
    ``timeout`` terminal state (SPEC §3 FR-02 single-task timeout → exit 4),
    else 0 (the run itself completed, even for a ``failed`` inner command).
    ``--all`` mode: runs every pending task concurrently and returns 0.

    [FR-04] ``--cached`` (single-task only) consults the TTL result cache
    before executing: a fresh ``sha256(command)`` hit replays the cached
    result with ``cached: true`` and NO subprocess. Successful runs (both
    single and ``--all``) populate the cache regardless of ``--cached``.

    Citations:
      SPEC §3 FR-02 (run <id> / run --all, state machine, exit 4 on timeout).
      SPEC §3 FR-04 (--cached replay + TTL cache write).
      NFR-08 (shared Lock across ThreadPoolExecutor + cache writers).
    """
    parser = argparse.ArgumentParser(prog="taskq run", add_help=False)
    parser.add_argument("--all", action="store_true", dest="run_all")
    parser.add_argument("--cached", action="store_true")
    parser.add_argument("task_id", nargs="?")
    args = parser.parse_args(list(argv))

    tasks_file = _tasks_path()
    # [FR-05] Surface a corrupt store as exit 1 (SPEC §7) before any run.
    _load_tasks_strict(tasks_file)
    lock = threading.Lock()
    cache = cache_mod.Cache(_cache_path())

    if args.run_all:
        executor.run_all(
            tasks_file, _load_tasks, _atomic_write_json, lock, cache=cache
        )
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
        cache=cache,
        use_cache=args.cached,
    )
    if status is None:
        # FR-03 AC-04: ``breaker open`` → exit 3, no subprocess, no task
        # transition. The substring ``breaker open`` is asserted by tests.
        print("error: breaker open", file=sys.stderr)
        return 3
    return 4 if status == "timeout" else 0


def status_command(argv: Sequence[str]) -> int:
    """Handle ``taskq status [--json] <id>`` [FR-05].

    Prints every field of the task record (id + command + name + status +
    result fields + created_at/finished_at) in a human-readable form, or a
    single-line JSON object under ``--json`` (NFR-06 machine-readable
    contract). An unknown id exits 2 with ``unknown task: <id>`` on stderr
    (SPEC §7 ``unknown task id → 2``); a corrupt store raises
    ``_CorruptStoreError`` → exit 1 via :func:`main`.

    Citations:
      SPEC §3 FR-05 (AC-FR05-01 all fields / AC-FR05-02 --json / AC-FR05-06
      unknown id → exit 2 + stderr ``unknown task: <id>``).
      SPEC §7 (exit-code map — validation error / internal error).
    """
    parser = argparse.ArgumentParser(prog="taskq status", add_help=False)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("task_id", nargs=1)
    args = parser.parse_args(list(argv))
    task_id = args.task_id[0]

    tasks = _load_tasks_strict(_tasks_path())
    record = tasks.get(task_id)
    if record is None:
        print(f"unknown task: {task_id}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"id": task_id, **record}))
    else:
        print(f"id: {task_id}")
        for key, value in record.items():
            print(f"{key}: {value}")
    return 0


def list_command(argv: Sequence[str]) -> int:
    """Handle ``taskq list [--json] [--status S]`` [FR-05].

    Emits one row per task (``id  status  command``); ``--status S`` keeps
    only records whose ``status`` equals ``S``. An empty store prints nothing
    and still exits 0. A corrupt store raises ``_CorruptStoreError`` → exit 1
    via :func:`main`.

    Citations:
      SPEC §3 FR-05 (AC-FR05-03 list happy / AC-FR05-04 --status done filter).
    """
    parser = argparse.ArgumentParser(prog="taskq list", add_help=False)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--status", default=None)
    args = parser.parse_args(list(argv))

    tasks = _load_tasks_strict(_tasks_path())
    rows = [
        {"id": task_id, **record}
        for task_id, record in tasks.items()
        if args.status is None or record.get("status") == args.status
    ]

    if args.json:
        print(json.dumps(rows))
    else:
        for row in rows:
            print(f"{row['id']}\t{row.get('status', '')}\t{row.get('command', '')}")
    return 0


def clear_command(argv: Sequence[str]) -> int:
    """Handle ``taskq clear`` — remove all ``$TASKQ_HOME`` data files [FR-05].

    Deletes ``tasks.json`` / ``cache.json`` / ``breaker.json`` (and their
    sibling ``.tmp`` files) so a subsequent ``list`` yields empty output.
    Removing the files satisfies the SPEC §3 FR-05 ``清空 $TASKQ_HOME 全部
    資料檔`` contract (an absent file is a valid "empty" state).

    Citations:
      SPEC §3 FR-05 (AC-FR05-05 — clear empties all data files).
    """
    home = _taskq_home()
    for name in ("tasks.json", "cache.json", "breaker.json"):
        for target in (home / name, home / f"{name}.tmp"):
            if target.exists():
                target.unlink()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Top-level CLI dispatcher.

    Returns the process exit code for ``python -m taskq <args>``. A
    ``_CorruptStoreError`` from any read-side subcommand is mapped to exit 1
    with a stderr message (SPEC §7 ``其他內部錯誤 → exit 1``).

    Citations:
      SPEC §3 FR-05 (subcommand table + global exit-code map).
      SPEC §7 (exit codes 0/1/2/3/4).
    """
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print("error: no command given", file=sys.stderr)
        return 2
    subcommand = argv[0]
    try:
        if subcommand == "submit":
            return submit_command(argv[1:])
        if subcommand == "run":
            return run_command(argv[1:])
        if subcommand == "status":
            return status_command(argv[1:])
        if subcommand == "list":
            return list_command(argv[1:])
        if subcommand == "clear":
            return clear_command(argv[1:])
    except _CorruptStoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"error: unknown command {subcommand!r}", file=sys.stderr)
    return 2