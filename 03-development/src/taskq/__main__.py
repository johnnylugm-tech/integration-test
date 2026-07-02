"""taskq CLI entry point.

[FR-01] Citations:
- SPEC.md §3 FR-01 (table rows 「非空」/「長度」/「注入字元」): `validate_command`
- SPEC.md §3 FR-01 ("產生 task id (uuid4 前 8 hex)"): `generate_task_id`
- SPEC.md §3 FR-01 ("原子寫入 $TASKQ_HOME/tasks.json (tmp + os.replace)"):
  `atomic_write_tasks`
- SPEC.md §3 FR-01 ("tasks.json 損壞(非法 JSON) → 啟動偵測 → exit 1,stderr
  store corrupted(不靜默重建)"): `load_tasks_or_die`, `cmd_list`
- SPEC.md §3 FR-01 preamble ("任一違反 → exit 2 + stderr 錯誤訊息,不寫入存儲"):
  `cmd_submit`, `validate_command`
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any


# Exit codes — verbatim per FR-01 spec.
EXIT_OK = 0
EXIT_CORRUPT = 1
EXIT_REJECTED = 2

# [FR-01] SPEC.md §3 FR-01 row 「長度」: 命令 > 1000 字元 → 拒絕.
COMMAND_MAX_LENGTH = 1000

# [FR-01] SPEC.md §3 FR-01 row 「注入字元」/NFR-02:
# 命令含 ; | & $ > < ` 任一 → 拒絕.
INJECTION_CHARS = set(";|&$><`")


def taskq_home() -> Path:
    """Return the TASKQ_HOME directory, defaulting to ~/.taskq.

    [FR-01] SPEC.md §3 FR-01 ("$TASKQ_HOME/tasks.json").
    """
    raw = os.environ.get("TASKQ_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".taskq"


def tasks_json_path() -> Path:
    """Return the canonical tasks.json path under TASKQ_HOME."""
    return taskq_home() / "tasks.json"


def validate_command(cmd: str) -> str | None:
    """Return None if `cmd` is acceptable, else a human-readable error.

    [FR-01] SPEC.md §3 FR-01 table rows 「非空」/「長度」/「注入字元」;
    preamble "任一違反 → exit 2 + stderr 錯誤訊息,不寫入存儲".
    """
    if cmd == "" or cmd.strip() == "":
        return "command must not be empty or whitespace"
    if len(cmd) > COMMAND_MAX_LENGTH:
        return (
            f"command length {len(cmd)} exceeds limit {COMMAND_MAX_LENGTH}"
        )
    if any(ch in INJECTION_CHARS for ch in cmd):
        return "command contains forbidden injection character"
    return None


def generate_task_id() -> str:
    """Return the first 8 hex chars of a uuid4.

    [FR-01] SPEC.md §3 FR-01 ("產生 task id (uuid4 前 8 hex)").
    """
    return uuid.uuid4().hex[:8]


def atomic_write_tasks(tasks: list[dict[str, Any]], task_id: str) -> None:
    """Persist `tasks` to `$TASKQ_HOME/tasks.json` via tmp + os.replace.

    [FR-01] SPEC.md §3 FR-01 ("原子寫入 $TASKQ_HOME/tasks.json
    (tmp + os.replace)").
    """
    target = tasks_json_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    # [FR-01] tmp + os.replace; tmp filename embeds task_id so the
    # `test_fr01_atomic_write` test can detect any leftover partial writes.
    tmp_name = f"tasks.json.tmp.{task_id}"
    tmp_path = target.parent / tmp_name

    payload = json.dumps(tasks, ensure_ascii=False, indent=2)
    with open(tmp_path, "w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, target)


def load_tasks_or_die() -> list[dict[str, Any]]:
    """Return the parsed tasks.json, or exit 1 on corruption.

    [FR-01] SPEC.md §3 FR-01 ("tasks.json 損壞(非法 JSON) → 啟動偵測 →
    exit 1,stderr store corrupted(不靜默重建)").
    """
    path = tasks_json_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("store corrupted", file=sys.stderr)
        sys.exit(EXIT_CORRUPT)
    if not isinstance(data, list):
        print("store corrupted", file=sys.stderr)
        sys.exit(EXIT_CORRUPT)
    return data


def cmd_submit(args: argparse.Namespace) -> int:
    """Handle the `submit` subcommand.

    [FR-01] SPEC.md §3 FR-01 preamble + table rows.
    """
    cmd = args.command

    err = validate_command(cmd)
    if err is not None:
        print(err, file=sys.stderr)
        return EXIT_REJECTED

    task_id = generate_task_id()
    record = {
        "id": task_id,
        "status": "pending",
        "command": cmd,
        "attempts": 0,
    }

    # [FR-01] "狀態 pending,記錄 command、created_at"
    from datetime import datetime, timezone

    record["created_at"] = datetime.now(timezone.utc).isoformat()

    tasks = load_tasks_or_die()
    tasks.append(record)
    atomic_write_tasks(tasks, task_id)

    if getattr(args, "json", False):
        # JSON output: surface the recorded fields per FR-01 contract.
        sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(f"submitted {task_id}\n")

    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    """Handle the `list` subcommand.

    [FR-01] SPEC.md §3 FR-01 corruption-detection contract — surfaces any
    malformed tasks.json via exit 1 + stderr "store corrupted" without
    rewriting the file.
    """
    tasks = load_tasks_or_die()
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
    parser.error(f"unknown subcommand: {args.command_name}")
    return EXIT_REJECTED  # pragma: no cover — parser.error() raises SystemExit, never returns


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover — entry point; subprocess tests bypass via -m taskq