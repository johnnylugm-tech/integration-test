"""taskq CLI — subcommands and output formatting.

[FR-01] [FR-02] [FR-03] [FR-04] [FR-05]
Entry: python -m taskq <subcommand> [options]

Exit codes: 0 success / 2 input validation / 3 breaker open / 4 timeout / 1 internal error.

CLI Architecture:
  - cmd_submit: Submits a task to the queue with validation.
  - cmd_status: Displays the full status of a task.
  - cmd_list: Lists all tasks, optionally filtered by status.
  - cmd_clear: Clears all task data (tasks.json, breaker.json, cache.json).
  - _dispatch_subcommand: Routes parsed CLI arguments to handlers.
  - main: Entry point; parses arguments and dispatches.

Command validation rules:
  - Command must be non-empty and <= 1000 characters (FR-01).
  - Command cannot contain shell injection chars outside quotes (NFR-02).
  - Task names must be unique among pending/running tasks (FR-01).
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

from taskq.config import Config, get_config, validate_config
from taskq.models import Task, TaskStatus
from taskq.store import load_tasks, save_task, load_task

# FR-01 injection character blacklist (NFR-02)
_INJECTION_CHARS: frozenset[str] = frozenset(";|&$><`")


def _get_status_value(status) -> str:
    """Extract status string from Task.status enum or string.

    Handles both enum.value and direct string representations.
    """
    return status.value if hasattr(status, "value") else status


def _format_task_dict(task: Task) -> dict:
    """Convert a Task object to a dictionary for display/JSON.

    [FR-05] Serializes all task fields including status normalization.
    """
    return {
        "id": task.id,
        "command": task.command,
        "name": task.name,
        "status": _get_status_value(task.status),
        "created_at": task.created_at,
        "exit_code": task.exit_code,
        "stdout_tail": task.stdout_tail,
        "stderr_tail": task.stderr_tail,
        "duration_ms": task.duration_ms,
        "finished_at": task.finished_at,
        "cached": task.cached,
    }


def _check_injection(command: str) -> None:
    """Raise SystemExit(2) if command contains injection characters outside quotes.

    [FR-01] [NFR-02] Scans single-quoted and double-quoted spans, rejecting
    characters in _INJECTION_CHARS found in unquoted regions.
    """
    in_single = False
    in_double = False
    for ch in command:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double and ch in _INJECTION_CHARS:
            print(f"error: command contains forbidden character {ch!r}", file=sys.stderr)
            raise SystemExit(2)


def _check_name_unique(name: str, cfg: Config) -> None:
    """Raise SystemExit(2) if a pending/running task with the same name exists.

    [FR-01] Prevents duplicate names among active tasks.
    """
    tasks = load_tasks(cfg)
    for task in tasks.values():
        if task.name == name and task.status in (TaskStatus.pending, TaskStatus.running):
            print(
                f"error: a task named {name!r} already exists with status"
                f" {task.status.value}",
                file=sys.stderr,
            )
            raise SystemExit(2)


def _validate_submit_command(command: str) -> None:
    """Validate command string for submit.

    [FR-01] Checks non-empty, length <= 1000, and injection-char restrictions.
    Raises SystemExit(2) on failure.
    """
    if not command or not command.strip():
        print("error: command must not be empty", file=sys.stderr)
        raise SystemExit(2)

    if len(command) > 1000:
        print("error: command exceeds 1000 characters", file=sys.stderr)
        raise SystemExit(2)

    _check_injection(command)


def _make_pending_task(command: str, name: Optional[str]) -> Task:
    """Create a pending Task object with generated id and timestamp.

    [FR-01] Does not persist; caller must save.
    """
    task_id = uuid.uuid4().hex[:8]
    created_at = datetime.now(tz=timezone.utc).isoformat()

    return Task(
        id=task_id,
        command=command,
        name=name,
        status=TaskStatus.pending,
        created_at=created_at,
    )


def cmd_submit(command: str, name: Optional[str], cfg: Config) -> Task:
    """Validate and submit a new task to the queue.

    [FR-01] Validates the command against non-empty, length, injection-char,
    and name-uniqueness rules. On pass, writes a pending task atomically to
    $TASKQ_HOME/tasks.json and returns the Task object.

    Raises SystemExit(2) on any validation failure (no storage write occurs).
    """
    _ = validate_config(cfg)
    _validate_submit_command(command)

    if name is not None:
        _check_name_unique(name, cfg)

    task = _make_pending_task(command, name)
    save_task(task, cfg)
    return task


def cmd_status(task_id: str, cfg: Config, json_output: bool = False) -> None:
    """Display all fields of a task.

    [FR-05] Fetches the task from the store and prints its fields.
    Raises SystemExit(2) if the task id is unknown.
    """
    _ = validate_config(cfg)
    task = load_task(task_id, cfg)
    data = _format_task_dict(task)
    if json_output:
        print(json.dumps(data))
    else:
        for key, value in data.items():
            print(f"{key:12} {value}")


def cmd_list(status_filter: Optional[str], cfg: Config, json_output: bool = False) -> None:
    """List tasks, optionally filtered by status.

    [FR-05] Reads all tasks and prints them (optionally filtering by status).
    """
    _ = validate_config(cfg)
    tasks = load_tasks(cfg)
    results = []
    for task in tasks.values():
        status_val = _get_status_value(task.status)
        if status_filter is None or status_val == status_filter:
            results.append(
                {
                    "id": task.id,
                    "name": task.name,
                    "status": status_val,
                    "command": task.command,
                }
            )
    if json_output:
        print(json.dumps(results))
    else:
        for item in results:
            print(
                f"{item['id']}  {item['status']:<10}  {item['name'] or '(unnamed)'}  {item['command']}"
            )


def cmd_clear(cfg: Config) -> None:
    """Clear all data files in $TASKQ_HOME.

    [FR-05] Removes tasks.json, breaker.json, and cache.json if present.
    """
    import os

    _ = validate_config(cfg)
    for filename in ("tasks.json", "breaker.json", "cache.json"):
        path = os.path.join(cfg.home, filename)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def _fmt_submit(task: Task, json_output: bool) -> str:
    """Format cmd_submit result for stdout.

    [FR-01] Returns 8-hex id or JSON shape based on the --json flag.
    """
    _ = validate_config(get_config())
    if json_output:
        return json.dumps({"id": task.id, "status": _get_status_value(task.status)})
    return task.id


def _handle_run_subcommand(args, cfg: Config) -> None:
    """Handle run subcommand with --all or single task id.

    [FR-02] [FR-03] Routes to executor.run_all or executor.run_task.
    """
    try:
        from taskq.executor import run_task, run_all as executor_run_all  # type: ignore[import]
    except ImportError:  # pragma: no cover
        print("error: executor not yet implemented", file=sys.stderr)
        raise SystemExit(1)
    if args.all:
        executor_run_all(cfg=cfg, cached=args.cached)
    else:
        if not args.id:  # pragma: no cover
            print("error: provide a task id or --all", file=sys.stderr)
            raise SystemExit(2)
        exit_code = run_task(args.id, cfg=cfg, cached=args.cached, json_output=args.json)
        raise SystemExit(exit_code)


def _dispatch_subcommand(args, cfg: Config) -> None:
    """Router: dispatch parsed args.

    [FR-05] Routes submit, run, status, list, clear to their handlers.
    """
    if args.subcommand == "submit":
        task = cmd_submit(args.command, name=args.name, cfg=cfg)
        print(_fmt_submit(task, args.json))
    elif args.subcommand == "run":
        _handle_run_subcommand(args, cfg)
    elif args.subcommand == "status":
        cmd_status(args.id, cfg=cfg, json_output=args.json)
    elif args.subcommand == "list":
        cmd_list(args.status_filter, cfg=cfg, json_output=args.json)
    elif args.subcommand == "clear":
        cmd_clear(cfg=cfg)


def main() -> None:
    """CLI entry point — parse args and dispatch subcommands.

    [FR-05] Parses arguments and routes to _dispatch_subcommand.
    """
    _ = validate_config(get_config())
    from taskq.parser import build_parser
    parser = build_parser()
    args = parser.parse_args()
    cfg = get_config()
    _dispatch_subcommand(args, cfg)
