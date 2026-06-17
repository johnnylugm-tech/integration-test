"""[FR-01] taskq CLI entry point.

Citations:
- 03-development/tests/test_fr01.py:9 (main(argv) -> int contract)
- 03-development/tests/test_fr01.py:34 (cli.main as cli_main)
- 03-development/tests/test_fr01.py:85-257 (exit codes:0/1/2)
- SRS.md:1-22 (FR-01/FR-03 CLI 整合)
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from taskq.store import (
    StoreCorrupted,
    clear_store,
    get_task,
    load_store,
    submit_task,
)
from taskq.store.validation import ValidationError


# Exit codes — SRS.md:1-22 (0=success、2=validation、1=corrupt)
EXIT_OK = 0
EXIT_VALIDATION = 2
EXIT_CORRUPT = 1
EXIT_UNKNOWN_TASK = 2  # 與 validation 共用 exit 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taskq")
    sub = parser.add_subparsers(dest="command")

    p_submit = sub.add_parser("submit")
    p_submit.add_argument("cmd", nargs=argparse.REMAINDER)

    p_status = sub.add_parser("status")
    p_status.add_argument("task_id")

    sub.add_parser("list")
    sub.add_parser("clear")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Return process exit code.

    Citations:
    - 03-development/tests/test_fr01.py:9 (main contract)
    - 03-development/tests/test_fr01.py:85-257 (per-command exit codes)
    """
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "submit":
        # `submit` 接受單一字串;REMAINDER 把剩餘 token 原樣收集後 join 回單一字串。
        command = " ".join(args.cmd) if args.cmd else ""
        try:
            tid = submit_task(command)
        except ValidationError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_VALIDATION
        print(tid)
        return EXIT_OK

    if args.command == "status":
        try:
            task = get_task(args.task_id)
        except StoreCorrupted as exc:
            print(f"error: store corrupted: {exc}", file=sys.stderr)
            return EXIT_CORRUPT
        if task is None:
            print(f"error: unknown task: {args.task_id}", file=sys.stderr)
            return EXIT_UNKNOWN_TASK
        print(json.dumps(task.to_dict(), ensure_ascii=False))
        return EXIT_OK

    if args.command == "list":
        try:
            store = load_store()
        except StoreCorrupted as exc:
            print(f"error: store corrupted: {exc}", file=sys.stderr)
            return EXIT_CORRUPT
        for tid, task in store.items():
            preview = task.command[:50]
            print(f"{tid}\t{task.status}\t{preview}")
        return EXIT_OK

    if args.command == "clear":
        clear_store()
        return EXIT_OK

    parser.print_help(sys.stderr)
    return EXIT_VALIDATION


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
