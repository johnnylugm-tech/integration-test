"""[FR-01] [FR-02]

CLI implementation: `submit()` + `run` subcommand + entry-point glue for
`python -m taskq`.

Citations:
- SPEC.md §3 FR-01 (validation rules, persisted shape, exit-code mapping).
- SPEC.md §3 FR-02 (taskq run <id> — single-task mode).
- SPEC.md §3 FR-03 (`status <id>` subcommand parity).
- tests/test_fr01.py module docstring (SubmitResult field contract — GREEN).
- tests/test_fr02.py module docstring (run_task contract — GREEN).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from typing import Sequence

from taskq.core.models import SubmitResult, Task
from taskq.core.validation import validate
from taskq.io.store import load_tasks, save_tasks

__all__ = ["submit", "main", "build_parser"]


def submit(cmd: object) -> SubmitResult:
    """Validate, persist, and return a `SubmitResult`.

    Citations:
        - SPEC.md §3 FR-01 (rules + 原子寫入).
        - tests/test_fr01.py GREEN contract (SubmitResult field set).

    Exit-code mapping (SPEC.md §3 FR-01, §3 FR-03 統一出口碼):
        0 — success
        2 — validation reject (任一違反 → exit 2)
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
    """uuid4 first 8 lowercase hex chars (SPEC.md §3 FR-01 first 8 hex rule)."""
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# CLI entry (`python -m taskq`)
# ---------------------------------------------------------------------------

def build_parser() -> "argparse.ArgumentParser":
    """Construct the argparse parser for `taskq` subcommands.

    Citations:
        - SPEC.md §3 FR-03 (argparse 子命令表).
    """
    parser = argparse.ArgumentParser(
        prog="taskq",
        description="local task-queue CLI (FR-01..FR-03).",
    )
    sub = parser.add_subparsers(dest="cmd_name", required=True)

    p_status = sub.add_parser("status", help="show a task by id (FR-03)")
    p_status.add_argument("task_id", help="8-hex task id")

    p_submit = sub.add_parser("submit", help="submit a command (FR-01)")
    p_submit.add_argument("command", help="command string (FR-01 validation rules apply)")

    p_run = sub.add_parser("run", help="run a task by id (FR-02)")
    p_run.add_argument("task_id", help="8-hex task id")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run as `python -m taskq <subcmd> [...]`; return process exit code.

    Citations:
        - SPEC.md §3 FR-01 (corruption → exit 1 + stderr "store corrupted").
        - SPEC.md §3 FR-03 (status <id> → unknown id → exit 2).
    """
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.cmd_name == "submit":
        result = submit(args.command)
        if result.exit_code != 0:
            sys.stderr.write(result.stderr)
        else:
            sys.stdout.write(f"{result.id}\n")
        return result.exit_code

    if args.cmd_name == "status":
        # FR-01 corruption-detection clause: load_tasks() raises CorruptStoreError;
        # the CLI MUST surface that as exit 1 + stderr "store corrupted".
        from taskq.io.store import CorruptStoreError  # late import keeps module-top flat

        try:
            tasks = load_tasks()
        except CorruptStoreError:
            sys.stderr.write("store corrupted: tasks.json is not valid JSON\n")
            return 1

        match = next((t for t in tasks if t.get("id") == args.task_id), None)
        if match is None:
            sys.stderr.write(f"unknown task: {args.task_id}\n")
            return 2
        sys.stdout.write(repr(match) + "\n")
        return 0

    if args.cmd_name == "run":
        from taskq.executor import run_task  # late import keeps module-top flat

        try:
            result = run_task(args.task_id)
        except Exception:
            # Unhandled exception in single-task mode → exit 1 (no bare except).
            sys.stderr.write("unhandled exception during task execution\n")
            return 1

        if result.exit_code != 0:
            sys.stderr.write(
                f"task {args.task_id!r} finished with status={result.status!r}"
                f" exit={result.exit_code}\n"
            )
        else:
            sys.stdout.write(
                f"task {args.task_id!r} finished: {result.status!r}\n"
            )
        return result.exit_code

    return 1


if __name__ == "__main__":  # pragma: no cover — normal entry is __main__.py
    sys.exit(main())
