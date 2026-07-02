"""taskq CLI entry point — `python -m taskq`.

[FR-01] Citations:
- SPEC.md §3 FR-01 (validation rules, id format, atomic write, corruption
  detection): delegates to `taskq.validation.validate_command` and
  `taskq.store.{load_tasks_or_die, atomic_write_tasks, append_task}`.
- SPEC.md §3 FR-01 ("產生 task id (uuid4 前 8 hex)"): `make_task_id`.
- SPEC.md §3 FR-01 ("狀態 `pending`,記錄 `command`、`created_at`"):
  `cmd_submit` constructs the record.
- SPEC.md §3 FR-01 preamble ("任一違反 → exit 2 + stderr 錯誤訊息,不寫入存儲"):
  exit-code mapping in `cmd_submit` / `cmd_list`.
- SPEC.md §3 FR-01 ("tasks.json 損壞(非法 JSON) → 啟動偵測 → exit 1,stderr
  `store corrupted`(不靜默重建)"): caught in `cmd_list` / `cmd_submit`.

[FR-02] Citations:
- SPEC.md §3 FR-02 (`run <id>`): `cmd_run` dispatches to
  `taskq.executor.run_task`.
- SPEC.md §3 FR-02 ("單一任務模式下 timeout 結果 → exit 4"): `cmd_run`
  maps `status == "timeout"` to exit code 4.
- SPEC.md §3 FR-02 ("其他未預期例外 → exit 1"): unhandled exceptions
  map to exit code 1.
- SPEC.md §3 (exit-code matrix): cmd_run respects per-FR-02 mapping.

[FR-03] Citations:
- SPEC.md §3 FR-03 subcommand table (lines 66-70): `submit`/`run`/`status`/
  `list`/`clear` registered in `build_parser` and dispatched in `main`.
- SPEC.md §3 FR-03 line 68 (`status <id>`: unknown id → exit 2 + stderr
  `unknown task: <id>`): `cmd_status` UnknownTaskError mapping.
- SPEC.md §3 FR-03 line 69 (`list`: command 前 50 字元): `cmd_list`
  truncates the `command` field to `[:50]` per record.
- SPEC.md §3 FR-03 line 70 (`clear`: 清空 `$TASKQ_HOME/tasks.json`):
  `cmd_clear` writes an empty list via `atomic_write_tasks`.
- SPEC.md §3 FR-03 line 72 (全域 flag `--json`: 單行 JSON): every JSON
  emit uses `sys.stdout.write(json.dumps(...))` with NO trailing newline.
- SPEC.md §3 FR-03 line 73 (exit-code matrix 0/2/4/1): mapped in
  `cmd_status` / `cmd_list` / `cmd_clear` / `cmd_submit` / `cmd_run`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any

from taskq.executor import (
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_REJECTED,
    EXIT_TIMEOUT,
    UnhandledExecutionError,
    UnknownTaskError,
    run_task,
)
from taskq.models import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_TIMEOUT,
    make_task_id,
)
from taskq.store import (
    EXIT_CORRUPT,
    StoreCorruptedError,
    atomic_write_tasks,
    load_tasks_or_die,
)
from taskq.validation import validate_command


# Exit codes per SPEC §3.
EXIT_OK_VALUE = EXIT_OK
EXIT_REJECTED_VALUE = EXIT_REJECTED

# [FR-03] SPEC.md §3 FR-03 line 69 (`list`: command 前 50 字元).
LIST_COMMAND_PREVIEW_LEN = 50


def _generate_task_id() -> str:
    """Backward-compat alias for `make_task_id` (FR-01 test surface).

    [FR-01] SPEC.md §3 FR-01 ("產生 task id (uuid4 前 8 hex)").
    """
    return make_task_id()


def cmd_submit(args: argparse.Namespace) -> int:
    """Handle the `submit` subcommand.

    [FR-01] SPEC.md §3 FR-01 preamble + table rows.
    [FR-03] SPEC.md §3 FR-03 line 66 (submit routes to FR-01); line 72
    (--json emits single-line JSON, no trailing newline).
    """
    cmd = args.command

    err = validate_command(cmd)
    if err is not None:
        print(err, file=sys.stderr)
        return EXIT_REJECTED_VALUE

    record: dict[str, Any] = {
        "id": make_task_id(),
        "status": STATUS_PENDING,
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
    atomic_write_tasks(tasks, record["id"])

    if getattr(args, "json", False):
        # [FR-03] SPEC.md §3 FR-03 line 72: 單行 JSON, no trailing newline.
        sys.stdout.write(json.dumps(record, ensure_ascii=False))
    else:
        sys.stdout.write(f"submitted {record['id']}\n")

    return EXIT_OK_VALUE


def cmd_list(args: argparse.Namespace) -> int:
    """Handle the `list` subcommand.

    [FR-01] SPEC.md §3 FR-01 corruption-detection contract.
    [FR-03] SPEC.md §3 FR-03 line 69 (`list`: command 前 50 字元) — each
    record's `command` field is truncated to `[:50]` for display; the
    underlying persisted record is left untouched (we shallow-copy).
    [FR-03] SPEC.md §3 FR-03 line 73 (corrupt store → exit 1).
    """
    try:
        tasks = load_tasks_or_die()
    except StoreCorruptedError:
        print("store corrupted", file=sys.stderr)
        return EXIT_CORRUPT
    # [FR-03] SPEC.md §3 FR-03 line 69: truncate `command` to first 50
    # chars. Build a display copy so the in-memory tasks list (and the
    # on-disk record) is not mutated.
    display: list[dict[str, Any]] = []
    for t in tasks:
        if not isinstance(t, dict):
            display.append(t)
            continue
        item = dict(t)
        cmd_val = item.get("command", "")
        if isinstance(cmd_val, str):
            item["command"] = cmd_val[:LIST_COMMAND_PREVIEW_LEN]
        display.append(item)
    sys.stdout.write(json.dumps(display, ensure_ascii=False))
    return EXIT_OK_VALUE


def cmd_run(args: argparse.Namespace) -> int:
    """Handle the `run <id>` subcommand.

    [FR-02] SPEC.md §3 FR-02: dispatch to `executor.run_task`, print the
    resulting task record as JSON on stdout (the CLI emits JSON for `run`
    so callers can observe the persisted result fields), and map the
    terminal status to the per-FR-02 exit code:

        status == "timeout" → exit 4
        status == "done"    → exit 0
        status == "failed"  → exit 0 (single-task mode: the failure is
                                       recorded on the task; the CLI does
                                       not surface it as a process-level
                                       error unless it is the timeout case
                                       per the explicit SPEC §3 mapping)
        unknown task id     → exit 2
        other internal err  → exit 1
    """
    task_id = args.task_id
    record: dict[str, Any] | None = None
    try:
        record = run_task(task_id)
    except UnknownTaskError:
        print(f"unknown task: {task_id}", file=sys.stderr)
        return EXIT_REJECTED_VALUE
    except UnhandledExecutionError:
        # [FR-02] SPEC.md §3 FR-02 ("其他未預期例外 → exit 1"). The executor
        # has already persisted a failure record on disk — reload it so we
        # can emit the persisted state on stdout before exiting 1.
        try:
            tasks = load_tasks_or_die()
        except StoreCorruptedError:
            print("store corrupted", file=sys.stderr)
            return EXIT_CORRUPT
        for t in tasks:
            if isinstance(t, dict) and t.get("id") == task_id:
                record = t
                break
        if record is None:
            print(f"internal error: unhandled, task {task_id} not persisted",
                  file=sys.stderr)
            return EXIT_INTERNAL
        # [FR-03] SPEC.md §3 FR-03 line 72: 單行 JSON, no trailing newline.
        sys.stdout.write(json.dumps(record, ensure_ascii=False))
        return EXIT_INTERNAL
    except StoreCorruptedError:
        print("store corrupted", file=sys.stderr)
        return EXIT_CORRUPT
    except Exception as exc:  # noqa: BLE001 — FR-02 exit-1 contract.
        # [FR-02] SPEC.md §3 FR-02 ("其他未預期例外 → exit 1"): surface as
        # exit 1 with stderr detail; no bare-except swallow.
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INTERNAL

    # Emit the record on stdout so callers (tests) can parse status /
    # exit_code / attempts / tails. JSON is the canonical wire format
    # referenced by FR-03 (`status <id>` prints all fields).
    # [FR-03] SPEC.md §3 FR-03 line 72: 單行 JSON, no trailing newline.
    sys.stdout.write(json.dumps(record, ensure_ascii=False))

    status = record.get("status")
    if status == STATUS_TIMEOUT:
        # [FR-02] SPEC.md §3 FR-02 ("單一任務模式下 timeout 結果 → exit 4").
        return EXIT_TIMEOUT
    if status == STATUS_FAILED:
        # Retries exhausted on a failing command — CLI exits 0 (single-task
        # mode); the failure is recorded on the task itself.
        return EXIT_OK_VALUE
    if status == STATUS_DONE:
        return EXIT_OK_VALUE
    # Pending/running post-execution shouldn't happen, but be defensive.
    return EXIT_INTERNAL


def cmd_status(args: argparse.Namespace) -> int:
    """Handle the `status <id>` subcommand.

    [FR-03] SPEC.md §3 FR-03 line 68: `status <id>` 輸出該任務全欄位;
    unknown id → exit 2 + stderr `unknown task: <id>`.
    [FR-03] SPEC.md §3 FR-03 line 73: corrupt store → exit 1.
    [FR-03] SPEC.md §3 FR-03 line 72: emits single-line JSON, no trailing
    newline.
    """
    task_id = args.task_id
    try:
        tasks = load_tasks_or_die()
    except StoreCorruptedError:
        print("store corrupted", file=sys.stderr)
        return EXIT_CORRUPT

    record: dict[str, Any] | None = None
    for t in tasks:
        if isinstance(t, dict) and t.get("id") == task_id:
            record = t
            break
    if record is None:
        # [FR-03] SPEC.md §3 FR-03 line 68: unknown id → exit 2 + stderr.
        print(f"unknown task: {task_id}", file=sys.stderr)
        return EXIT_REJECTED_VALUE

    # [FR-03] SPEC.md §3 FR-03 line 72: 單行 JSON, no trailing newline.
    sys.stdout.write(json.dumps(record, ensure_ascii=False))
    return EXIT_OK_VALUE


def cmd_clear(args: argparse.Namespace) -> int:
    """Handle the `clear` subcommand.

    [FR-03] SPEC.md §3 FR-03 line 70: 清空 `$TASKQ_HOME/tasks.json`.
    Writes an empty list atomically (the on-disk file may not exist
    beforehand; the first `clear` creates it as `"[]"`).
    """
    # [FR-01] reuse atomic_write_tasks for tmp+os.replace semantics; the
    # embedded "id" sentinel keeps the tmp filename deterministic and
    # tells partial-write detection "this was a clear".
    atomic_write_tasks([], "clear")
    return EXIT_OK_VALUE


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser.

    [FR-03] SPEC.md §3 FR-03 subcommand table (lines 66-70): registers
    `submit` / `run` / `status` / `list` / `clear`.
    """
    parser = argparse.ArgumentParser(prog="taskq")
    sub = parser.add_subparsers(dest="command_name", required=True)

    p_submit = sub.add_parser("submit", help="submit a new task")
    p_submit.add_argument("command", help="command string to enqueue")
    p_submit.add_argument(
        "--json",
        action="store_true",
        help="emit the new task record as JSON on stdout",
    )

    p_run = sub.add_parser("run", help="execute a previously submitted task")
    p_run.add_argument("task_id", help="id of the task to execute")

    # [FR-03] SPEC.md §3 FR-03 line 68.
    p_status = sub.add_parser("status", help="show all fields of a task")
    p_status.add_argument("task_id", help="id of the task to query")

    sub.add_parser("list", help="list all tasks")

    # [FR-03] SPEC.md §3 FR-03 line 70.
    sub.add_parser("clear", help="empty $TASKQ_HOME/tasks.json")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point used by `python -m taskq`."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command_name == "submit":
        return cmd_submit(args)
    if args.command_name == "run":
        return cmd_run(args)
    if args.command_name == "status":
        return cmd_status(args)
    if args.command_name == "list":
        return cmd_list(args)
    if args.command_name == "clear":
        return cmd_clear(args)
    parser.error(f"unknown subcommand: {args.command_name}")  # pragma: no cover — required=True subparsers make this branch unreachable
    return EXIT_REJECTED_VALUE  # pragma: no cover — required=True subparsers make this branch unreachable


if __name__ == "__main__":  # pragma: no cover — script entrypoint
    sys.exit(main())  # pragma: no cover — script entrypoint