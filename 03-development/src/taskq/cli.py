"""taskq.cli — argv-driven entry point.

FR coverage:
  - [FR-01] submit command + 4-rule validation + atomic write via store
  - [FR-02] run single + run --all with ThreadPoolExecutor
  - [FR-03] run pre-check: breaker OPEN → exit 3 + stderr "breaker open"
  - [FR-04] TTL cache replay path (`run --cached`) + write-on-success
  - [FR-05] argparse subcommand dispatcher scaffold

Citations:
- SPEC.md §3 FR-01 lines 55-72: submit syntax + 4-rule validation
- SPEC.md §3 FR-02 lines 74-83: state machine + result fields
- SPEC.md §3 FR-03 lines 86-99: retry + circuit breaker
- SPEC.md §3 FR-04 lines 96-99: TTL cache replay / write-on-success
- SPEC.md §3 FR-05 lines 104-112: full CLI surface (submit/run/status/list/clear)
- TEST_SPEC.md FR-01/02/03/04 cases (lines 87-245)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Sequence

from taskq import breaker, cache, executor, store
from taskq.models import Task, utc_now_iso

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
    """[FR-05] Build the argparse sub-command tree (SPEC §3 FR-05 lines 104-112)."""
    p = argparse.ArgumentParser(prog="taskq")
    sub = p.add_subparsers(dest="command", required=False)
    submit = sub.add_parser("submit")
    submit.add_argument("task_command", help="shell-style command string to validate + persist")
    submit.add_argument("--name", default=None, help="optional human-friendly task name")
    submit.add_argument("--json", action="store_true", dest="json_mode", help="emit single-line JSON")

    run = sub.add_parser("run")
    run.add_argument("task_id", nargs="?", default=None, help="task id (omit when using --all)")
    run.add_argument("--all", action="store_true", help="run every pending task concurrently")
    # [FR-04] cache replay opt-in (SPEC §3 FR-04 line 97).
    run.add_argument("--cached", action="store_true", help="use FR-04 cache when available")
    run.add_argument("--json", action="store_true", dest="json_mode", help="emit single-line JSON")
    return p


def _validate(command: str) -> str | None:
    """[FR-01] Return error message on first violation, else None (SPEC §3 FR-01).

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


def _cache_write(task: Task) -> None:
    """[FR-04] Persist a successful task result into ``$TASKQ_HOME/cache.json``.

    Writes a fresh entry under ``sha256(task.command)`` so future
    ``run --cached`` invocations can replay without running the
    subprocess (SPEC §3 FR-04 line 98). Failures (failed/timeout)
    are never cached — only ``done`` results are replay-eligible.
    """
    cache.put(
        task.command,
        {
            "command": task.command,
            "exit_code": task.exit_code,
            "stdout_tail": task.stdout_tail or "",
            "stderr_tail": task.stderr_tail or "",
            "duration_ms": int(task.duration_ms or 0),
            "finished_at": task.finished_at or utc_now_iso(),
        },
    )


def _cmd_submit(args: argparse.Namespace) -> int:
    """[FR-01] Validate + persist a pending task; print its id (SPEC §3 FR-01)."""
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
    """[FR-02/FR-03/FR-04] Execute a pending task, or every pending task via `--all`.

    Single-task mode: exit 0 on done/failed, exit 4 on timeout, exit 3 if
    the breaker is OPEN (no subprocess executed).
    `--all` mode: ThreadPoolExecutor with `TASKQ_MAX_WORKERS` workers; each
    worker re-reads + re-writes `tasks.json` under the shared store lock,
    so concurrent writers never corrupt the file (NFR-03 + NP-13).

    [FR-04] When `--cached` is set: consults ``cache.replay(command)``
    for a TTL-fresh entry first. Hit → replay exit_code/stdout_tail,
    mark task status=done + cached=true, exit 0, NO subprocess invoked.
    Miss/expired → falls through to normal live execution. On a
    successful live run, writes a fresh entry to ``cache.json`` so a
    future ``--cached`` run can replay (SPEC §3 FR-04 + SAD §3.1).
    """
    breaker.reload_config()

    if args.all:
        pending = store.list_pending()
        max_workers = int(os.environ.get("TASKQ_MAX_WORKERS", "4"))

        def _run_one(record: dict) -> None:
            task = Task(**record)
            executor.run_task(task)
            store.update_task(task)
            if task.status == "done":
                _cache_write(task)

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

    # [FR-04] cache replay path — only when --cached is explicitly set.
    if args.cached:
        hit = cache.replay(task.command)
        if hit is not None:
            task.status = "done"
            task.exit_code = int(hit.get("exit_code", 0))
            task.stdout_tail = hit.get("stdout_tail") or ""
            task.stderr_tail = hit.get("stderr_tail") or ""
            task.duration_ms = int(hit.get("duration_ms") or 0)
            task.finished_at = hit.get("finished_at") or utc_now_iso()
            task.attempts = 0
            task.cached = True
            store.update_task(task)
            if args.json_mode:
                sys.stdout.write(json.dumps(task.to_dict()) + "\n")
                sys.stdout.flush()
            return 0
        # Fall through to live execution when --cached misses.

    decision = breaker.check_and_admit()
    if decision == breaker.REJECT:
        print("breaker open", file=sys.stderr)
        return _EXIT_BREAKER

    executor.run_task(task)
    store.update_task(task)

    if task.status == "done":
        _cache_write(task)

    if args.json_mode:
        sys.stdout.write(json.dumps(task.to_dict()) + "\n")
        sys.stdout.flush()

    if task.status == "timeout":
        return _EXIT_TIMEOUT
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """[FR-05] Entry point. Returns the process exit code (0 / 2 / 3 / 4)."""
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "submit":
        return _cmd_submit(args)
    if args.command == "run":
        return _cmd_run(args)
    # No subcommand provided — keep behaviour minimal for FR-01 scope.
    parser.print_help(sys.stderr)
    return 2
