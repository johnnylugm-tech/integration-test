"""[FR-01][FR-02][FR-03] taskq CLI entry point.

Citations:
- 03-development/tests/test_fr01.py:9 (main(argv) -> int contract)
- 03-development/tests/test_fr01.py:34 (cli.main as cli_main)
- 03-development/tests/test_fr01.py:85-257 (exit codes:0/1/2)
- 03-development/tests/test_fr02.py:241-256 (CLI `run <id>` happy path)
- 03-development/tests/test_fr02.py:372-391 (CLI `run` on OSError → exit 1)
- 03-development/tests/test_fr03.py:1-30 (GREEN TODO surface for FR-03)
- 03-development/tests/test_fr03.py:200-220 (--json list → single-line JSON)
- 03-development/tests/test_fr03.py:222-230 (--help mentions all subcommands)
- 03-development/tests/test_fr03.py:232-260 (50-char truncation in list)
- 03-development/tests/test_fr03.py:262-280 (exit code matrix 0/1/2/4)
- 03-development/tests/test_fr03.py:282-320 (E2E pipeline + validation exit 2)
- SRS.md:1-22 (FR-01/FR-03 CLI 整合)
- SRS.md:96-100 (exit codes 0/2/4/1)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from taskq.executor import run_task
from taskq.store import (
    StoreCorrupted,
    clear_store,
    get_task,
    load_store,
    submit_task,
)
from taskq.store.validation import ValidationError

# Exit codes — SRS.md:1-22 / 96-100
# 0=success、2=validation/unknown id、1=corrupt/internal、4=timeout
EXIT_OK = 0
EXIT_VALIDATION = 2  # covers validation errors AND unknown task ids
EXIT_CORRUPT = 1
EXIT_TIMEOUT = 4
EXIT_INTERNAL = 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taskq")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a single line of JSON for machine-readable output",
    )
    sub = parser.add_subparsers(dest="command")

    p_submit = sub.add_parser("submit")
    p_submit.add_argument("cmd", nargs=argparse.REMAINDER)

    p_status = sub.add_parser("status")
    p_status.add_argument("task_id")

    p_run = sub.add_parser("run")
    p_run.add_argument("task_id")

    sub.add_parser("list")
    sub.add_parser("clear")
    return parser


def _emit(payload, json_mode: bool) -> None:
    """Print ``payload`` either as plain text or as a single JSON line.

    Plain mode (``--json`` absent) preserves the existing text protocols:
    - ``submit`` prints the bare task id (last line)
    - ``status`` prints the task record as JSON (already parseable)
    - ``list`` prints one ``id\\tstatus\\tcommand[:50]`` row per task
    - ``clear`` prints nothing
    - ``run`` prints nothing extra on top of the executor's side effects

    JSON mode (``--json`` present) collapses every command's output to
    exactly one JSON line so downstream tooling can ``json.loads`` it.
    """
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False))
        return
    if isinstance(payload, list):
        for row in payload:
            print(row)
    elif payload is None:
        return
    else:
        print(payload)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Return process exit code.

    Citations:
    - 03-development/tests/test_fr01.py:9 (main contract)
    - 03-development/tests/test_fr01.py:85-257 (per-command exit codes)
    - 03-development/tests/test_fr03.py:1-30 (FR-03 surface: --json, subcommands)
    """
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    json_mode = bool(getattr(args, "json", False))

    if args.command == "submit":
        # `submit` 接受單一字串;REMAINDER 把剩餘 token 原樣收集後 join 回單一字串。
        command = " ".join(args.cmd) if args.cmd else ""
        try:
            tid = submit_task(command)
        except ValidationError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_VALIDATION
        _emit({"id": tid, "command": command} if json_mode else tid, json_mode)
        return EXIT_OK

    if args.command == "status":
        try:
            task = get_task(args.task_id)
        except StoreCorrupted as exc:  # pragma: no cover  # fault-injection: requires corrupting tasks.json between submit and status
            print(f"error: store corrupted: {exc}", file=sys.stderr)
            return EXIT_CORRUPT
        if task is None:
            print(f"error: unknown task: {args.task_id}", file=sys.stderr)
            return EXIT_VALIDATION
        # status output is always JSON: structured data must be machine-parseable.
        print(json.dumps(task.to_dict(), ensure_ascii=False))
        return EXIT_OK

    if args.command == "list":
        try:
            store = load_store()
        except StoreCorrupted as exc:
            print(f"error: store corrupted: {exc}", file=sys.stderr)
            return EXIT_CORRUPT
        # Build the plain-text rows and the JSON payload in lockstep so both
        # modes share the same truncation rule (command[:50]).
        rows: list[str] = []
        tasks_payload: list[dict] = []
        for tid, task in store.items():
            preview = task.command[:50]
            rows.append(f"{tid}\t{task.status}\t{preview}")
            tasks_payload.append({"id": tid, **task.to_dict()})
        _emit(tasks_payload if json_mode else rows, json_mode)
        return EXIT_OK

    if args.command == "clear":
        clear_store()
        _emit({"cleared": True} if json_mode else None, json_mode)
        return EXIT_OK

    if args.command == "run":
        # Citations: 03-development/tests/test_fr02.py:241-256, 372-391
        try:
            task = get_task(args.task_id)
        except StoreCorrupted as exc:
            print(f"error: store corrupted: {exc}", file=sys.stderr)
            return EXIT_CORRUPT
        if task is None:
            print(f"error: unknown task: {args.task_id}", file=sys.stderr)
            return EXIT_VALIDATION
        try:
            result = run_task(args.task_id)
        except Exception as exc:  # OSError, RuntimeError, ... → internal
            print(f"internal error: {exc}", file=sys.stderr)
            return EXIT_INTERNAL
        if json_mode:
            _emit(
                {
                    "id": args.task_id,
                    "status": result.status,
                    "exit_code": result.exit_code,
                    "duration_ms": result.duration_ms,
                },
                json_mode,
            )
        if result.exit_code == 4:
            return EXIT_TIMEOUT
        return EXIT_OK

    parser.print_help(sys.stderr)
    return EXIT_VALIDATION


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
