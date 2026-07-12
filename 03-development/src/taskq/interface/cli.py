"""taskq CLI — argument parsing, validation, and exit code mapping.

[FR-01, FR-05, NFR-02, NFR-05, NFR-07]
Citations: SPEC.md line 57 (FR-01 task submission + validation),
           SPEC.md line 73 (8-hex id / pending / atomic write / --json output),
           SPEC.md line 106 (argparse subcommand table),
           SAD.md line 86 (cli submit/run + exit code mapping),
           TEST_SPEC.md line 61-70 (FR01 sub-assertions).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Sequence

from taskq.core.models import RunResult, TaskStatus
from taskq.runtime.executor import execute
from taskq.storage.store import Store


# NFR-02 injection blacklist — six shell metacharacters.
INJECTION_CHARS = (";", "|", "&", "$", ">", "<", "`")

# FR-01 length cap.
MAX_COMMAND_LENGTH = 1000

# Default TASKQ_HOME relative to CWD (SPEC §5 line 146).
DEFAULT_HOME = ".taskq"


def _default_home() -> Path:
    env = os.environ.get("TASKQ_HOME")
    return Path(env) if env else Path.cwd() / DEFAULT_HOME


def _validate_command(command: str) -> Optional[str]:
    """Return an error message string if command is invalid, else None.

    [FR-01, NFR-02]
    Citations: SPEC.md line 57 (validation rules),
               TEST_SPEC.md line 63-70 (FR01 sub-assertions).
    """
    if len(command) == 0:
        return "command must not be empty"
    if command.strip() == "":
        return "command must not be whitespace-only"
    if len(command) > MAX_COMMAND_LENGTH:
        return f"command exceeds {MAX_COMMAND_LENGTH} characters"
    for ch in INJECTION_CHARS:
        if ch in command:
            return f"command contains forbidden injection character: {ch!r}"
    return None


def _check_name_unique(store: Store, name: str) -> Optional[str]:
    """Reject duplicate names against pending/running tasks.

    [FR-01]
    Citations: SPEC.md line 57 (name-unique rule).
    """
    active = (TaskStatus.PENDING.value, TaskStatus.RUNNING.value)
    for task in store.load().values():
        if task.get("name") != name:
            continue
        status = task.get("status")
        if status in active:
            return f"task name {name!r} already exists (status={status})"
    return None


def _emit_submit_result(task_id: str, as_json: bool) -> None:
    """Write the submit result to stdout (default id-only, or --json).

    [FR-01, FR-05]
    Citations: SPEC.md line 73 (stdout id / --json payload).
    """
    if as_json:
        sys.stdout.write(json.dumps({"id": task_id, "status": "pending"}) + "\n")
    else:
        sys.stdout.write(task_id + "\n")


def _cmd_submit(args: argparse.Namespace) -> int:
    """Submit subcommand handler. Returns process exit code.

    [FR-01, FR-05, NFR-02, NFR-03]
    Citations: SPEC.md line 57 (FR-01 rules),
               SPEC.md line 73 (atomic write),
               SAD.md line 128 (inject-char blacklist enforced in cli before store).
    """
    command: str = args.command
    name: Optional[str] = args.name

    err = _validate_command(command)
    if err is not None:
        sys.stderr.write(f"error: {err}\n")
        return 2

    home = _default_home()
    store = Store(home)

    if name is not None:
        err = _check_name_unique(store, name)
        if err is not None:
            sys.stderr.write(f"error: {err}\n")
            return 2

    try:
        task = store.submit(command, name=name)
    except OSError as exc:
        sys.stderr.write(f"error: failed to persist task: {exc}\n")
        return 1

    _emit_submit_result(task.id, as_json=bool(args.json))
    return 0


def _task_timeout() -> float:
    """Return the per-task subprocess timeout in seconds (TASKQ_TASK_TIMEOUT).

    [FR-02, NFR-06]
    Citations: SPEC.md line 132 (TASKQ_TASK_TIMEOUT default 10.0).
    """
    return float(os.environ.get("TASKQ_TASK_TIMEOUT", "10.0"))


def _max_workers() -> int:
    """Return the run --all concurrency worker count (TASKQ_MAX_WORKERS).

    [FR-02, NFR-06]
    Citations: SPEC.md line 131 (TASKQ_MAX_WORKERS default 4).
    """
    return int(os.environ.get("TASKQ_MAX_WORKERS", "4"))


def _run_one(store: Store, task: dict, timeout: float) -> RunResult:
    """Execute a single task: mark running, run it, persist the result.

    [FR-02, NFR-03]
    Citations: SPEC.md line 88 (state machine pending->running->done|failed|timeout),
               SAD.md line 210 (executor -> store write-back).
    """
    store.update_status(task["id"], status=TaskStatus.RUNNING.value)
    result = execute(task["command"], timeout=timeout)
    store.update_status(task["id"], **result.to_fields())
    return result


def _cmd_run(args: argparse.Namespace) -> int:
    """Run subcommand: `run <id>` (single) or `run --all` (concurrent pending).

    [FR-02, FR-05]
    Citations: SPEC.md line 88 (run <id> / run --all; single-task timeout exit 4),
               SPEC.md line 106 (exit code map),
               SAD.md line 129 (executor is FR-02 primary module).
    """
    home = _default_home()
    store = Store(home)

    if args.run_all:
        timeout = _task_timeout()
        pending = [
            t for t in store.load().values()
            if t.get("status") == TaskStatus.PENDING.value
        ]
        with ThreadPoolExecutor(max_workers=_max_workers()) as pool:
            futures = [pool.submit(_run_one, store, t, timeout) for t in pending]
            for fut in as_completed(futures):
                fut.result()  # propagate any worker exception
        return 0

    task_id: Optional[str] = args.task_id
    if task_id is None:
        sys.stderr.write("error: run requires a task id or --all\n")
        return 2
    task = store.get(task_id)
    if task is None:
        sys.stderr.write(f"error: unknown task: {task_id}\n")
        return 2

    result = _run_one(store, task, _task_timeout())
    # SPEC §5: single-task timeout maps to exit 4; a task that ran (done/failed)
    # is not itself a CLI failure, so those return 0.
    if result.status == TaskStatus.TIMEOUT:
        return 4
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Status subcommand: print all persisted fields of a single task.

    [FR-02, FR-05]
    Citations: SPEC.md line 106 (status <id> outputs full task fields),
               SPEC.md line 106 (unknown task id -> exit 2).
    """
    home = _default_home()
    store = Store(home)
    task = store.get(args.task_id)
    if task is None:
        sys.stderr.write(f"error: unknown task: {args.task_id}\n")
        return 2
    if args.json:
        sys.stdout.write(json.dumps(task) + "\n")
    else:
        for key, value in task.items():
            sys.stdout.write(f"{key}: {value}\n")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taskq")
    sub = parser.add_subparsers(dest="subcommand")

    submit_p = sub.add_parser("submit", help="submit a new task")
    submit_p.add_argument("command", help="shell command to run")
    submit_p.add_argument("--name", default=None, help="optional task name (must be unique)")
    submit_p.add_argument("--json", action="store_true", help="emit JSON to stdout")

    run_p = sub.add_parser("run", help="run a task by id, or --all pending tasks")
    run_p.add_argument("task_id", nargs="?", default=None, help="task id to run")
    run_p.add_argument("--all", action="store_true", dest="run_all",
                       help="run all pending tasks concurrently")
    run_p.add_argument("--json", action="store_true", help="emit JSON to stdout")

    status_p = sub.add_parser("status", help="show all fields of a task")
    status_p.add_argument("task_id", help="task id to inspect")
    status_p.add_argument("--json", action="store_true", help="emit JSON to stdout")

    # Stubs for FR-05 subcommands not owned by FR-02. They exit with code 3
    # (per SAD exit code map: not implemented for this phase).
    for name in ("list", "clear"):
        p = sub.add_parser(name, add_help=True)
        p.add_argument("rest", nargs=argparse.REMAINDER)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point.

    [FR-01, FR-02, FR-05, NFR-05]
    Citations: SAD.md line 86 (cli.main + exit code mapping),
               SAD.md line 195 (submit entry point flow),
               SPEC.md line 88 (FR-02 run/status dispatch).
    """
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.subcommand == "submit":
        return _cmd_submit(args)
    if args.subcommand == "run":
        return _cmd_run(args)
    if args.subcommand == "status":
        return _cmd_status(args)
    if args.subcommand in ("list", "clear"):
        sys.stderr.write(f"error: subcommand {args.subcommand!r} not implemented yet\n")
        return 3
    parser.print_help(sys.stderr)
    return 4