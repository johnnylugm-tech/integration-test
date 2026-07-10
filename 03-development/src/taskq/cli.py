"""taskq.cli — argv-driven entry point. Current scope: FR-01 `submit`.

This module exposes the argparse-based entry point. The FR-01 surface
(`taskq submit "<cmd>" [--name N] [--json]`) validates 4 rules and writes a
pending task to `$TASKQ_HOME/tasks.json` per SPEC §3.

FR coverage:
  - [FR-01] submit command + 4-rule validation + atomic write via store
  - [FR-05] argparse subcommand dispatcher scaffold (full surface in later FRs)

Citations:
- SPEC.md §3 FR-01 lines 55-72: submit syntax + 4-rule validation
- SPEC.md §3 FR-01 line 72: stdout prints id; `--json` prints single-line JSON
- SPEC.md §3 FR-05 lines 104-112: full CLI surface (submit/run/status/list/clear)
- TEST_SPEC.md FR-01 cases 1-6 (lines 87-114): exit 0 / exit 2 contracts
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Sequence

from taskq import executor, store
from taskq.models import Task

# FR-01 rule 3 (NFR-02) — injection blacklist (SPEC §3 line 65).
_INJECTION_CHARS = set(";|&$><`")

# FR-01 rule 2 — command length cap (SPEC §3 line 64).
_MAX_COMMAND_LEN = 1000

# FR-01 / SPEC §6 line 183 — validation rejection exit code.
_EXIT_VALIDATION = 2

# FR-05 / SPEC §3 FR-05 line 115 — exit codes table.
_EXIT_BREAKER = 3
_EXIT_TIMEOUT = 4


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="taskq")
    sub = p.add_subparsers(dest="command", required=False)
    submit = sub.add_parser("submit")
    submit.add_argument("task_command", help="shell-style command string to validate + persist")
    submit.add_argument("--name", default=None, help="optional human-friendly task name")
    submit.add_argument("--json", action="store_true", dest="json_mode", help="emit single-line JSON")

    run = sub.add_parser("run")
    run.add_argument("task_id", nargs="?", default=None, help="task id (omit when using --all)")
    run.add_argument("--all", action="store_true", help="run every pending task concurrently")
    run.add_argument("--cached", action="store_true", help="use FR-04 cache when available")
    run.add_argument("--json", action="store_true", dest="json_mode", help="emit single-line JSON")
    return p


def _validate(command: str) -> str | None:
    """Return error message on first violation, else None (SPEC §3 FR-01).

    Order matches TEST_SPEC cases 1-4:
      1. empty / whitespace-only
      2. length > 1000
      3. injection char present
    Name uniqueness is handled separately because it needs the current
    store state, not just the input string.
    """
    if not command or not command.strip():
        return "command must not be empty or whitespace"
    if len(command) > _MAX_COMMAND_LEN:
        return f"command exceeds {_MAX_COMMAND_LEN} chars"
    bad = [c for c in command if c in _INJECTION_CHARS]
    if bad:
        return f"command contains forbidden injection chars: {''.join(sorted(set(bad)))}"
    return None


def _cmd_submit(args: argparse.Namespace) -> int:
    err = _validate(args.task_command)
    if err is not None:
        print(f"error: {err}", file=sys.stderr)
        return _EXIT_VALIDATION

    if args.name:
        existing = store.find_active_by_name(args.name)
        if existing is not None:
            print(
                f"error: name '{args.name}' collides with active task {existing.get('id')}",
                file=sys.stderr,
            )
            return _EXIT_VALIDATION

    task = Task.new_pending(command=args.task_command, name=args.name)
    store.add_task(task)

    if args.json_mode:
        # SPEC §3 FR-01 line 72 — single-line JSON output (NP-04).
        sys.stdout.write(json.dumps({"id": task.id, "status": task.status}) + "\n")
    else:
        sys.stdout.write(task.id + "\n")
    sys.stdout.flush()
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """[FR-02] Execute a single pending task, or every pending task via `--all`.

    Single-task mode: exit 0 on done/failed, exit 4 on timeout.
    `--all` mode: ThreadPoolExecutor with `TASKQ_MAX_WORKERS` workers; each
    worker re-reads + re-writes `tasks.json` under the shared store lock,
    so concurrent writers never corrupt the file (NFR-03 + NP-13).
    """
    if args.all:
        pending = store.list_pending()
        max_workers = int(os.environ.get("TASKQ_MAX_WORKERS", "4"))

        def _run_one(record: dict) -> None:
            task = Task(**record)
            executor.run_task(task)
            store.update_task(task)

        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
            list(pool.map(_run_one, pending))

        if args.json_mode:
            sys.stdout.write(json.dumps({"ran": len(pending)}) + "\n")
            sys.stdout.flush()
        return 0

    # Single-task mode.
    if not args.task_id:
        print("error: run requires a task id or --all", file=sys.stderr)
        return _EXIT_VALIDATION

    record = store.get_task(args.task_id)
    if record is None:
        print(f"error: unknown task id '{args.task_id}'", file=sys.stderr)
        return _EXIT_VALIDATION

    task = Task(**record)
    executor.run_task(task)
    store.update_task(task)

    if args.json_mode:
        sys.stdout.write(json.dumps(task.to_dict()) + "\n")
        sys.stdout.flush()

    if task.status == "timeout":
        return _EXIT_TIMEOUT
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code (0 / 2 / ...)."""
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "submit":
        return _cmd_submit(args)
    if args.command == "run":
        return _cmd_run(args)
    # No subcommand provided — keep behaviour minimal for FR-01 scope.
    parser.print_help(sys.stderr)
    return 2