"""taskq CLI — argparse subcommands and output formatting.

[FR-01] [FR-02] [FR-03] [FR-04] [FR-05]
Entry: python -m taskq <subcommand> [options]

Exit codes: 0 success / 2 input validation / 3 breaker open / 4 timeout / 1 internal error.
"""
from __future__ import annotations

import argparse
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


def cmd_submit(command: str, name: Optional[str], cfg: Config) -> Task:
    """Validate and submit a new task to the queue.

    [FR-01] Validates the command against non-empty, length, injection-char,
    and name-uniqueness rules. On pass, writes a pending task atomically to
    $TASKQ_HOME/tasks.json and returns the Task object.

    Raises SystemExit(2) on any validation failure (no storage write occurs).
    """
    _ = validate_config(cfg)

    # Non-empty check
    if not command or not command.strip():
        print("error: command must not be empty", file=sys.stderr)
        raise SystemExit(2)

    # Length check
    if len(command) > 1000:
        print("error: command exceeds 1000 characters", file=sys.stderr)
        raise SystemExit(2)

    # Injection-character check (NFR-02)
    # Scan characters outside quoted strings only (single or double quotes).
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

    # Name-uniqueness check (pending/running tasks)
    if name is not None:
        tasks = load_tasks(cfg)
        for task in tasks.values():
            if task.name == name and task.status in (
                TaskStatus.pending,
                TaskStatus.running,
            ):
                print(
                    f"error: a task named {name!r} already exists with status"
                    f" {task.status.value}",
                    file=sys.stderr,
                )
                raise SystemExit(2)

    # Generate task id: uuid4 first 8 hex chars
    task_id = uuid.uuid4().hex[:8]
    created_at = datetime.now(tz=timezone.utc).isoformat()

    task = Task(
        id=task_id,
        command=command,
        name=name,
        status=TaskStatus.pending,
        created_at=created_at,
    )
    save_task(task, cfg)
    return task


def cmd_status(task_id: str, cfg: Config, json_output: bool = False) -> None:
    """Display all fields of a task.

    [FR-05] Fetches the task from the store and prints its fields.
    Raises SystemExit(2) if the task id is unknown.
    """
    _ = validate_config(cfg)
    task = load_task(task_id, cfg)
    if json_output:
        data = {
            "id": task.id,
            "command": task.command,
            "name": task.name,
            "status": task.status.value if hasattr(task.status, "value") else task.status,
            "created_at": task.created_at,
            "exit_code": task.exit_code,
            "stdout_tail": task.stdout_tail,
            "stderr_tail": task.stderr_tail,
            "duration_ms": task.duration_ms,
            "finished_at": task.finished_at,
            "cached": task.cached,
        }
        print(json.dumps(data))
    else:
        print(f"id:          {task.id}")
        print(f"command:     {task.command}")
        print(f"name:        {task.name}")
        status_val = task.status.value if hasattr(task.status, "value") else task.status
        print(f"status:      {status_val}")
        print(f"created_at:  {task.created_at}")
        print(f"exit_code:   {task.exit_code}")
        print(f"duration_ms: {task.duration_ms}")
        print(f"finished_at: {task.finished_at}")
        print(f"cached:      {task.cached}")


def cmd_list(status_filter: Optional[str], cfg: Config, json_output: bool = False) -> None:
    """List tasks, optionally filtered by status.

    [FR-05] Reads all tasks and prints them (optionally filtering by status).
    """
    _ = validate_config(cfg)
    tasks = load_tasks(cfg)
    results = []
    for task in tasks.values():
        status_val = task.status.value if hasattr(task.status, "value") else task.status
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
        status_val = task.status.value if hasattr(task.status, "value") else task.status
        return json.dumps({"id": task.id, "status": status_val})
    return task.id


def main() -> None:
    """CLI entry point — parse args and dispatch subcommands.

    [FR-05] Dispatches submit / run / status / list / clear.
    """
    _ = validate_config(get_config())

    parser = argparse.ArgumentParser(prog="taskq", description="Local task queue CLI")
    parser.add_argument("--json", action="store_true", default=False, help="Machine-readable JSON output")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # submit
    p_submit = sub.add_parser("submit", help="Submit a new task")
    p_submit.add_argument("command", help="Shell command to queue")
    p_submit.add_argument("--name", default=None, help="Optional task name (must be unique)")

    # run
    p_run = sub.add_parser("run", help="Execute a task or all pending tasks")
    p_run_group = p_run.add_mutually_exclusive_group(required=True)
    p_run_group.add_argument("id", nargs="?", default=None, help="Task id to run")
    p_run_group.add_argument("--all", action="store_true", default=False, help="Run all pending tasks")
    p_run.add_argument("--cached", action="store_true", default=False, help="Use TTL cache if available")

    # status
    p_status = sub.add_parser("status", help="Show all fields for a task")
    p_status.add_argument("id", help="Task id")

    # list
    p_list = sub.add_parser("list", help="List tasks")
    p_list.add_argument("--status", default=None, dest="status_filter", help="Filter by status")

    # clear
    sub.add_parser("clear", help="Clear all data files")

    args = parser.parse_args()
    cfg = get_config()

    if args.subcommand == "submit":
        task = cmd_submit(args.command, name=args.name, cfg=cfg)
        print(_fmt_submit(task, args.json))

    elif args.subcommand == "run":
        # FR-02/03/04 — executor not implemented in FR-01 scope;
        # stub for CLI wiring; will be implemented in FR-02+.
        try:
            from taskq.executor import run_task, run_all as executor_run_all  # type: ignore[import]
        except ImportError:
            print("error: executor not yet implemented", file=sys.stderr)
            raise SystemExit(1)
        if args.all:
            executor_run_all(cfg=cfg, cached=args.cached)
        else:
            if not args.id:
                print("error: provide a task id or --all", file=sys.stderr)
                raise SystemExit(2)
            exit_code = run_task(args.id, cfg=cfg, cached=args.cached, json_output=args.json)
            raise SystemExit(exit_code)

    elif args.subcommand == "status":
        cmd_status(args.id, cfg=cfg, json_output=args.json)

    elif args.subcommand == "list":
        cmd_list(args.status_filter, cfg=cfg, json_output=args.json)

    elif args.subcommand == "clear":
        cmd_clear(cfg=cfg)
