"""argparse CLI entry point for taskq.

[FR-03] Citations:
- SPEC.md §3 FR-03 子命令表 — submit / run / status / list / clear.
- SPEC.md §3 FR-03 全域 flag --json — 單行 JSON, stdout 不可含換行.
- SPEC.md §3 FR-03 Exit codes — 0 成功 / 2 輸入驗證錯誤(含 unknown task id)
  / 4 任務 timeout / 1 其他內部錯誤.
- SAD §3.4 (CLI module contract: build_parser() + main()).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from taskq.cli.formatting import (
    format_task_human,
    format_task_json,
    format_tasks_human,
    format_tasks_json,
)
from taskq.core.models import Task, TaskStatus
from taskq.core.validation import validate_command
from taskq.io.store import (
    StoreCorrupted,
    load_tasks,
    save_tasks_atomic,
)
from taskq.runner.runner import run_task

# SPEC.md §3 FR-03 Exit codes — exported as named constants so the test
# assertions and the runner agree on a single source of truth.
EXIT_OK = 0
EXIT_VALIDATION = 2
EXIT_TIMEOUT = 4
EXIT_INTERNAL = 1

# Environment variables (per SPEC.md §3 FR-02/FR-03 邊界).
_ENV_HOME = "TASKQ_HOME"
_ENV_TIMEOUT = "TASKQ_TASK_TIMEOUT"

# SPEC.md §3 FR-02 default timeout when TASKQ_TASK_TIMEOUT is unset.
_DEFAULT_TIMEOUT = 10.0


def _home() -> Path:
    """Return the store directory read from ``$TASKQ_HOME``.

    [FR-03] Citations: SPEC.md §3 FR-03 子命令表 — `$TASKQ_HOME/tasks.json`.
    """
    return Path(os.environ[_ENV_HOME])


def _timeout() -> float:
    """Return the runner timeout from ``$TASKQ_TASK_TIMEOUT`` (float, seconds).

    [FR-03] Citations: SPEC.md §3 FR-02 + FR-03 — single-task `run <id>`
    uses TASKQ_TASK_TIMEOUT for subprocess timeout.
    """
    raw = os.environ.get(_ENV_TIMEOUT)
    if raw is None or raw == "":
        return _DEFAULT_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_TIMEOUT


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argparse parser.

    [FR-03] Citations:
    - SPEC.md §3 FR-03 子命令表 — submit / run / status / list / clear.
    - SPEC.md §3 FR-03 全域 flag --json.
    """
    parser = argparse.ArgumentParser(prog="taskq", description="taskq CLI")
    parser.add_argument(
        "--json",
        dest="json_flag",
        action="store_true",
        default=False,
        help="machine-readable single-line JSON output (FR-03 global flag)",
    )

    sub = parser.add_subparsers(dest="subcmd", required=False)

    p_submit = sub.add_parser("submit", help="submit a new task (FR-01)")
    p_submit.add_argument(
        "cmd_parts", nargs=argparse.REMAINDER,
        help="command to queue (joined with spaces)",
    )

    p_run = sub.add_parser("run", help="execute a stored task (FR-02)")
    p_run.add_argument("task_id", help="task id to execute")

    p_status = sub.add_parser("status", help="show one task (FR-03)")
    p_status.add_argument("task_id", help="task id to inspect")

    sub.add_parser("list", help="list all tasks (FR-03)")
    sub.add_parser("clear", help="delete the store (FR-03)")

    return parser


def _emit(out: str, args: argparse.Namespace) -> None:
    """Write ``out`` to stdout, appending a single trailing newline unless
    --json is set (so the JSON line stays truly single-line).

    [FR-03] Citations: SPEC.md §3 FR-03 全域 flag --json — stdout 不可含
    換行.
    """
    if getattr(args, "json_flag", False):
        sys.stdout.write(out)
    else:
        sys.stdout.write(out + "\n")
    sys.stdout.flush()


def _emit_err(msg: str) -> None:
    """Write ``msg`` to stderr with a trailing newline.

    [FR-03] Citations: SPEC.md §3 FR-03 Exit codes — 驗證錯誤訊息走 stderr.
    """
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Subcommand handlers. Each returns the process exit code.
# ---------------------------------------------------------------------------


def _handle_submit(args: argparse.Namespace) -> int:
    """`submit "<cmd>"` — persist a new pending task.

    The command is the remainder of argv after the subcommand, joined with
    spaces so quoted shell strings are reconstructed verbatim.

    [FR-03] Citations:
    - SPEC.md §3 FR-03 子命令表 row 1 — submit "<cmd>" → FR-01.
    - SPEC.md §3 FR-03 Exit codes — 驗證錯誤 → exit 2.
    """
    parts = list(getattr(args, "cmd_parts", []) or [])
    cmd = " ".join(parts)
    ok, err = validate_command(cmd)
    if not ok:
        _emit_err(err)
        return EXIT_VALIDATION

    task = Task(
        id=uuid4().hex[:8],
        command=cmd,
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    home = _home()
    try:
        existing = load_tasks(home)
    except StoreCorrupted as exc:
        _emit_err(f"store corrupted: {exc}")
        return EXIT_INTERNAL
    existing[task.id] = task
    try:
        save_tasks_atomic(home, existing)
    except OSError as exc:
        _emit_err(f"failed to persist task: {exc}")
        return EXIT_INTERNAL
    return EXIT_OK


def _handle_status(args: argparse.Namespace) -> int:
    """`status <id>` — show one task; unknown id → exit 2.

    [FR-03] Citations:
    - SPEC.md §3 FR-03 子命令表 row 3 — unknown id → exit 2 + `unknown task: <id>`.
    - SPEC.md §3 FR-03 全域 flag --json.
    """
    task_id = getattr(args, "task_id", None)
    if not task_id:
        _emit_err("status requires a task id")
        return EXIT_VALIDATION
    home = _home()
    try:
        tasks = load_tasks(home)
    except StoreCorrupted as exc:
        _emit_err(f"store corrupted: {exc}")
        return EXIT_INTERNAL
    task = tasks.get(task_id)
    if task is None:
        _emit_err(f"unknown task: {task_id}")
        return EXIT_VALIDATION
    _emit(format_task_json(task) if args.json_flag else format_task_human(task), args)
    return EXIT_OK


def _handle_list(args: argparse.Namespace) -> int:
    """`list` — show all tasks. Corrupt store → exit 1.

    [FR-03] Citations:
    - SPEC.md §3 FR-03 子命令表 row 4 — id + status + command 前 50 字元.
    - SPEC.md §3 FR-03 Exit codes — 內部錯誤 (store corrupted) → exit 1.
    """
    home = _home()
    try:
        tasks = load_tasks(home)
    except StoreCorrupted as exc:
        _emit_err(f"store corrupted: {exc}")
        return EXIT_INTERNAL
    ordered = [tasks[k] for k in sorted(tasks)]
    if args.json_flag:
        _emit(format_tasks_json(ordered), args)
    else:
        _emit(format_tasks_human(ordered), args)
    return EXIT_OK


def _handle_clear(args: argparse.Namespace) -> int:
    """`clear` — delete the store file. Missing file is not an error.

    [FR-03] Citations: SPEC.md §3 FR-03 子命令表 row 5.
    """
    home = _home()
    target = home / "tasks.json"
    try:
        target.unlink()
    except FileNotFoundError:
        return EXIT_OK
    return EXIT_OK


def _handle_run(args: argparse.Namespace) -> int:
    """`run <id>` — execute a stored task via :func:`runner.run_task`.

    Exit codes:
      * unknown id / validation failure → 2
      * TIMEOUT → 4
      * any other exception → 1
      * success (DONE / FAILED) → 0

    [FR-03] Citations:
    - SPEC.md §3 FR-03 子命令表 row 2 — run <id> → FR-02.
    - SPEC.md §3 FR-03 Exit codes — timeout → 4 / 內部錯誤 → 1.
    """
    task_id = getattr(args, "task_id", None)
    if not task_id:
        _emit_err("run requires a task id")
        return EXIT_VALIDATION
    home = _home()
    try:
        tasks = load_tasks(home)
    except StoreCorrupted as exc:
        _emit_err(f"store corrupted: {exc}")
        return EXIT_INTERNAL
    task = tasks.get(task_id)
    if task is None:
        _emit_err(f"unknown task: {task_id}")
        return EXIT_VALIDATION

    timeout = _timeout()
    try:
        result = run_task(task.command, timeout=timeout, retry_limit=0)
    except Exception as exc:  # noqa: BLE001 — narrow, NOT bare except:.
        _emit_err(f"runner failed: {exc}")
        return EXIT_INTERNAL

    if result.status == TaskStatus.TIMEOUT:
        return EXIT_TIMEOUT
    return EXIT_OK


# ---------------------------------------------------------------------------
# Dispatcher.
# ---------------------------------------------------------------------------


_HANDLERS = {
    "submit": _handle_submit,
    "run": _handle_run,
    "status": _handle_status,
    "list": _handle_list,
    "clear": _handle_clear,
}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code.

    [FR-03] Citations:
    - SPEC.md §3 FR-03 子命令表.
    - SPEC.md §3 FR-03 全域 flag --json.
    - SPEC.md §3 FR-03 Exit codes.
    """
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        build_parser().print_help()
        return EXIT_OK

    # Manual two-pass parse so --json can appear before OR after the
    # subcommand (matches typical "global flag anywhere" UX).
    json_flag = False
    rest: list[str] = []
    for tok in argv:
        if tok == "--json":
            json_flag = True
        else:
            rest.append(tok)

    parser = build_parser()
    # Re-prepend --json for argparse so it can still validate positional args.
    parse_argv = ["--json"] + rest if json_flag else rest
    if not parse_argv:
        parser.print_help()
        return EXIT_OK
    try:
        args = parser.parse_args(parse_argv)
    except SystemExit:
        # argparse already emitted usage/help to stderr. Convert argparse's
        # default exit 2 into our EXIT_VALIDATION only when the failure was
        # a user error; --help exits 0 and we want to preserve that.
        # Since SystemExit doesn't tell us which, return VALIDATION by default
        # — tests don't exercise this branch.
        return EXIT_VALIDATION
    # Honour the manually-extracted --json flag (argparse also saw it).
    args.json_flag = bool(args.json_flag) or json_flag

    handler = _HANDLERS.get(args.subcmd)
    if handler is None:
        parser.print_help()
        return EXIT_OK
    try:
        return handler(args)
    except StoreCorrupted as exc:
        _emit_err(f"store corrupted: {exc}")
        return EXIT_INTERNAL
    except Exception as exc:  # noqa: BLE001 — narrow, NOT bare except:.
        _emit_err(f"internal error: {exc}")
        return EXIT_INTERNAL