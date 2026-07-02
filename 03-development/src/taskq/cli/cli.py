"""[FR-01] [FR-02] [FR-03]

CLI implementation: argparse subcommands for `python -m taskq`.

Citations:
- SPEC.md S3 FR-01 (validation rules, persisted shape, exit-code mapping).
- SPEC.md S3 FR-02 (taskq run <id> -- single-task mode).
- SPEC.md S3 FR-03 (subcommands: submit, run, status, list, clear; --json flag; exit codes).
- tests/test_fr01.py module docstring (SubmitResult field contract -- GREEN).
- tests/test_fr02.py module docstring (run_task contract -- GREEN).
- tests/test_fr03.py module docstring (FR-03 CLI surface -- GREEN).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from typing import Sequence

from taskq.core.models import SubmitResult, Task, RunResult
from taskq.core.validation import validate
from taskq.io.store import load_tasks, save_tasks, CorruptStoreError
from taskq.executor import run_task
from taskq.query import (
    UnknownTaskError,
    status as query_status,
    list_tasks as query_list,
    clear as query_clear,
    format_task_human,
    format_task_json,
    format_list_human,
    format_list_json,
)

__all__ = ["submit", "main", "build_parser", "run_task"]


def submit(cmd: object) -> SubmitResult:
    """Validate, persist, and return a `SubmitResult`.

    Citations:
        - SPEC.md S3 FR-01 (rules + atomic write).
        - tests/test_fr01.py GREEN contract (SubmitResult field set).

    Exit-code mapping (SPEC.md S3 FR-01, S3 FR-03 unified exit codes):
        0 -- success
        2 -- validation reject (any violation -> exit 2)
    """
    outcome = validate(cmd)
    if not outcome.ok:
        return SubmitResult(exit_code=2, stderr=outcome.reason + "\n")

    # Contract says cmd is a non-empty str by this point, but the type
    # signature allows `object`; narrow for the type-checker / downstream.
    assert isinstance(cmd, str)
    new_task = Task.new(_new_id(), cmd)
    tasks = load_tasks()
    tasks.append(new_task.to_dict())
    save_tasks(tasks)

    return SubmitResult(
        exit_code=0,
        id=new_task.id,
        command=new_task.command,
        status=new_task.status,
        attempts=0,
    )


def _new_id() -> str:
    """uuid4 first 8 lowercase hex chars (SPEC.md S3 FR-01 first 8 hex rule)."""
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# CLI entry (`python -m taskq`)
# ---------------------------------------------------------------------------

def build_parser() -> "argparse.ArgumentParser":
    """Construct the argparse parser for `taskq` subcommands.

    Citations:
        - SPEC.md S3 FR-03 (argparse subcommand table).
    """
    parser = argparse.ArgumentParser(
        prog="taskq",
        description="local task-queue CLI (FR-01..FR-03).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="machine-readable single-line JSON output (FR-03)",
    )
    sub = parser.add_subparsers(dest="cmd_name", required=True)

    p_status = sub.add_parser("status", help="show a task by id (FR-03)")
    p_status.add_argument("task_id", help="8-hex task id")

    p_submit = sub.add_parser("submit", help="submit a command (FR-01)")
    p_submit.add_argument("command", help="command string (FR-01 validation rules apply)")

    p_run = sub.add_parser("run", help="run a task by id (FR-02)")
    p_run.add_argument("task_id", help="8-hex task id")

    p_list = sub.add_parser("list", help="list all tasks (FR-03)")
    p_list  # no extra args -- reference for linter

    p_clear = sub.add_parser("clear", help="clear all tasks (FR-03)")
    p_clear  # no extra args -- reference for linter

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run as `python -m taskq <subcmd> [...]`; return process exit code.

    Citations:
        - SPEC.md S3 FR-01 (corruption -> exit 1 + stderr "store corrupted").
        - SPEC.md S3 FR-03 (status <id> -> unknown id -> exit 2).
        - SPEC.md S3 FR-03 (exit codes: 0/2/4/1).
        - SPEC.md S3 FR-03 (--json flag: single-line JSON output).
    """
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    use_json: bool = getattr(args, "json_output", False)

    if args.cmd_name == "submit":
        result = submit(args.command)
        if result.exit_code != 0:
            sys.stderr.write(result.stderr)
        else:
            if use_json:
                import json as _json

                sys.stdout.write(
                    _json.dumps(
                        {
                            "id": result.id,
                            "command": result.command,
                            "status": result.status,
                            "attempts": result.attempts,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
            else:
                sys.stdout.write(f"{result.id}\n")
        return result.exit_code

    if args.cmd_name == "status":
        # FR-01 corruption-detection clause: load_tasks() raises CorruptStoreError;
        # the CLI MUST surface that as exit 1 + stderr "store corrupted".
        try:
            task = query_status(args.task_id)
        except CorruptStoreError:
            sys.stderr.write("store corrupted: tasks.json is not valid JSON\n")
            return 1
        except UnknownTaskError:
            sys.stderr.write(f"unknown task: {args.task_id}\n")
            return 2

        if use_json:
            sys.stdout.write(format_task_json(task))
        else:
            sys.stdout.write(format_task_human(task) + "\n")
        return 0

    if args.cmd_name == "run":
        try:
            run_result: RunResult = run_task(args.task_id)
        except Exception:
            # Unhandled exception in single-task mode -> exit 1 (no bare except).
            sys.stderr.write("unhandled exception during task execution\n")
            return 1

        if run_result.exit_code != 0:
            if not use_json:
                sys.stderr.write(
                    f"task {args.task_id!r} finished with status={run_result.status!r}"
                    f" exit={run_result.exit_code}\n"
                )
        else:
            if not use_json:
                sys.stdout.write(
                    f"task {args.task_id!r} finished: {run_result.status!r}\n"
                )
        return run_result.exit_code

    if args.cmd_name == "list":
        try:
            tasks = query_list()
        except CorruptStoreError:
            sys.stderr.write("store corrupted: tasks.json is not valid JSON\n")
            return 1

        if use_json:
            sys.stdout.write(format_list_json(tasks))
        else:
            sys.stdout.write(format_list_human(tasks) + "\n")
        return 0

    if args.cmd_name == "clear":
        query_clear()
        return 0

    return 1  # pragma: no cover -- argparse `required=True` rejects unknown cmd_name before dispatch


if __name__ == "__main__":  # pragma: no cover -- normal entry is __main__.py
    sys.exit(main())
