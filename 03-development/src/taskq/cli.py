"""taskq.cli — argv-driven entry point. Current scope: FR-01 `submit`.

Citations:
- SPEC.md §3 FR-01 lines 55-72: submit syntax + 4-rule validation
- SPEC.md §3 FR-01 line 72: stdout prints id; `--json` prints single-line JSON
- SPEC.md §3 FR-05 lines 104-112: full CLI surface (submit/run/status/list/clear)
- TEST_SPEC.md FR-01 cases 1-6 (lines 87-114): exit 0 / exit 2 contracts
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from taskq import store
from taskq.models import Task

# FR-01 rule 3 (NFR-02) — injection blacklist (SPEC §3 line 65).
_INJECTION_CHARS = set(";|&$><`")

# FR-01 rule 2 — command length cap (SPEC §3 line 64).
_MAX_COMMAND_LEN = 1000

# FR-01 / SPEC §6 line 183 — validation rejection exit code.
_EXIT_VALIDATION = 2


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="taskq")
    sub = p.add_subparsers(dest="command", required=False)
    submit = sub.add_parser("submit")
    submit.add_argument("task_command", help="shell-style command string to validate + persist")
    submit.add_argument("--name", default=None, help="optional human-friendly task name")
    submit.add_argument("--json", action="store_true", dest="json_mode", help="emit single-line JSON")
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


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code (0 / 2 / ...)."""
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "submit":
        return _cmd_submit(args)
    # No subcommand provided — keep behaviour minimal for FR-01 scope.
    parser.print_help(sys.stderr)
    return 2