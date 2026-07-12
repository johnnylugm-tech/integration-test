"""taskq CLI — argument parsing, validation, and exit code mapping.

[FR-01, FR-05, NFR-02, NFR-05, NFR-07]
Citations: SPEC.md line 57 (FR-01 task submission + validation),
           SPEC.md line 73 (8-hex id / pending / atomic write / --json output),
           SPEC.md line 106 (argparse subcommand table),
           SAD.md line 86 (cli submit/run + exit code mapping),
           TEST_SPEC.md line 61-70 (FR01 sub-assertions).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from taskq.storage.store import Store


# NFR-02 injection blacklist — six shell metacharacters.
INJECTION_CHARS = (";", "|", "&", "$", ">", "<", "`")

# FR-01 length cap.
MAX_COMMAND_LENGTH = 1000

# Default TASKQ_HOME relative to CWD (SPEC §5 line 146).
DEFAULT_HOME = ".taskq"


def _default_home() -> Path:
    env = os.environ.get("TASKQ_HOME")
    return Path(env) if env else Path.cwd() / DEFAULT_HOME


def _validate_command(command: str) -> Optional[str]:
    """Return an error message string if command is invalid, else None.

    [FR-01, NFR-02]
    Citations: SPEC.md line 57 (validation rules),
               TEST_SPEC.md line 63-70 (FR01 sub-assertions).
    """
    if len(command) == 0:
        return "command must not be empty"
    if command.strip() == "":
        return "command must not be whitespace-only"
    if len(command) > MAX_COMMAND_LENGTH:
        return f"command exceeds {MAX_COMMAND_LENGTH} characters"
    for ch in INJECTION_CHARS:
        if ch in command:
            return f"command contains forbidden injection character: {ch!r}"
    return None


def _check_name_unique(store: Store, name: str) -> Optional[str]:
    """Reject duplicate names against pending/running tasks.

    [FR-01]
    Citations: SPEC.md line 57 (name-unique rule).
    """
    data = store.load()
    for task in data.values():
        if task.get("name") != name:
            continue
        status = task.get("status")
        if status in ("pending", "running"):
            return f"task name {name!r} already exists (status={status})"
    return None


def _emit_submit_result(task_id: str, as_json: bool) -> None:
    """Write the submit result to stdout (default id-only, or --json).

    [FR-01, FR-05]
    Citations: SPEC.md line 73 (stdout id / --json payload).
    """
    if as_json:
        sys.stdout.write(json.dumps({"id": task_id, "status": "pending"}) + "\n")
    else:
        sys.stdout.write(task_id + "\n")


def _cmd_submit(args: argparse.Namespace) -> int:
    """Submit subcommand handler. Returns process exit code.

    [FR-01, FR-05, NFR-02, NFR-03]
    Citations: SPEC.md line 57 (FR-01 rules),
               SPEC.md line 73 (atomic write),
               SAD.md line 128 (inject-char blacklist enforced in cli before store).
    """
    command: str = args.command
    name: Optional[str] = args.name

    err = _validate_command(command)
    if err is not None:
        sys.stderr.write(f"error: {err}\n")
        return 2

    home = _default_home()
    store = Store(home)

    if name is not None:
        err = _check_name_unique(store, name)
        if err is not None:
            sys.stderr.write(f"error: {err}\n")
            return 2

    try:
        task = store.submit(command, name=name)
    except OSError as exc:
        sys.stderr.write(f"error: failed to persist task: {exc}\n")
        return 1

    _emit_submit_result(task.id, as_json=bool(args.json))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taskq")
    sub = parser.add_subparsers(dest="subcommand")

    submit_p = sub.add_parser("submit", help="submit a new task")
    submit_p.add_argument("command", help="shell command to run")
    submit_p.add_argument("--name", default=None, help="optional task name (must be unique)")
    submit_p.add_argument("--json", action="store_true", help="emit JSON to stdout")

    # Stubs for FR-02..05 — unimplemented at this step. They exit with code 3
    # (per SAD exit code map: 3 = "command not implemented for this phase").
    for name in ("run", "status", "list", "clear"):
        p = sub.add_parser(name, add_help=True)
        p.add_argument("rest", nargs=argparse.REMAINDER)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point.

    [FR-01, FR-05, NFR-05]
    Citations: SAD.md line 86 (cli.main + exit code mapping),
               SAD.md line 195 (submit entry point flow).
    """
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.subcommand == "submit":
        return _cmd_submit(args)
    if args.subcommand in ("run", "status", "list", "clear"):
        sys.stderr.write(f"error: subcommand {args.subcommand!r} not implemented yet\n")
        return 3
    parser.print_help(sys.stderr)
    return 4