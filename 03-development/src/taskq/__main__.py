"""taskq CLI entry point — `python -m taskq`.

[FR-01] Citations:
- SPEC.md §3 FR-01 (validation rules, id format, atomic write, corruption
  detection): delegates to `taskq.validation.validate_command` and
  `taskq.store.{load_tasks_or_die, atomic_write_tasks, append_task}`.
- SPEC.md §3 FR-01 ("產生 task id (uuid4 前 8 hex)"): `_generate_task_id`.
- SPEC.md §3 FR-01 ("狀態 `pending`,記錄 `command`、`created_at`"):
  `cmd_submit` constructs the record.
- SPEC.md §3 FR-01 preamble ("任一違反 → exit 2 + stderr 錯誤訊息,不寫入存儲"):
  exit-code mapping in `cmd_submit` / `cmd_list`.
- SPEC.md §3 FR-01 ("tasks.json 損壞(非法 JSON) → 啟動偵測 → exit 1,stderr
  `store corrupted`(不靜默重建)"): caught in `cmd_list` / `cmd_submit`.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from taskq.store import (
    EXIT_CORRUPT,
    StoreCorruptedError,
    atomic_write_tasks,
    load_tasks_or_die,
)
from taskq.validation import validate_command


# Exit codes per SPEC §3.
EXIT_OK = 0
EXIT_REJECTED = 2


def _generate_task_id() -> str:
    """Return the first 8 hex chars of a uuid4.

    [FR-01] SPEC.md §3 FR-01 ("產生 task id (uuid4 前 8 hex)").
    """
    return uuid.uuid4().hex[:8]


def cmd_submit(args: argparse.Namespace) -> int:
    """Handle the `submit` subcommand.

    [FR-01] SPEC.md §3 FR-01 preamble + table rows.
    """
    cmd = args.command

    err = validate_command(cmd)
    if err is not None:
        print(err, file=sys.stderr)
        return EXIT_REJECTED

    task_id = _generate_task_id()
    record: dict[str, Any] = {
        "id": task_id,
        "status": "pending",
        "command": cmd,
        "attempts": 0,
    }
    # [FR-01] "狀態 pending,記錄 command、created_at".
    record["created_at"] = datetime.now(timezone.utc).isoformat()

    try:
        tasks = load_tasks_or_die()
    except StoreCorruptedError:
        # Mirror the corruption-detection contract on the write path too.
        print("store corrupted", file=sys.stderr)
        return EXIT_CORRUPT
    tasks.append(record)
    atomic_write_tasks(tasks, task_id)

    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(f"submitted {task_id}\n")

    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    """Handle the `list` subcommand.

    [FR-01] SPEC.md §3 FR-01 corruption-detection contract.
    """
    try:
        tasks = load_tasks_or_die()
    except StoreCorruptedError:
        print("store corrupted", file=sys.stderr)
        return EXIT_CORRUPT
    sys.stdout.write(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(prog="taskq")
    sub = parser.add_subparsers(dest="command_name", required=True)

    p_submit = sub.add_parser("submit", help="submit a new task")
    p_submit.add_argument("command", help="command string to enqueue")
    p_submit.add_argument(
        "--json",
        action="store_true",
        help="emit the new task record as JSON on stdout",
    )

    sub.add_parser("list", help="list all tasks")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point used by `python -m taskq`."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command_name == "submit":
        return cmd_submit(args)
    if args.command_name == "list":
        return cmd_list(args)
    parser.error(f"unknown subcommand: {args.command_name}")  # pragma: no cover — required=True subparsers make this branch unreachable
    return EXIT_REJECTED  # pragma: no cover — required=True subparsers make this branch unreachable


if __name__ == "__main__":  # pragma: no cover — script entrypoint
    sys.exit(main())  # pragma: no cover — script entrypoint
