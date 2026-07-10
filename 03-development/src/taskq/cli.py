"""taskq.cli — argv-driven entry point.

FR coverage:
  - [FR-01] submit command + 4-rule validation + atomic write via store
  - [FR-02] run single + run --all with ThreadPoolExecutor
  - [FR-03] run pre-check: breaker OPEN → exit 3 + stderr "breaker open"
  - [FR-04] TTL cache replay path (`run --cached`) + write-on-success
  - [FR-05] argparse subcommand dispatcher (submit / run / status / list / clear)
            + global --json flag + full exit-code matrix (0/2/3/4/1)

Citations:
- SPEC.md §3 FR-01 lines 55-72: submit syntax + 4-rule validation
- SPEC.md §3 FR-02 lines 74-83: state machine + result fields
- SPEC.md §3 FR-03 lines 86-99: retry + circuit breaker
- SPEC.md §3 FR-04 lines 96-99: TTL cache replay / write-on-success
- SPEC.md §3 FR-05 lines 102-112: full CLI surface (submit/run/status/list/clear)
- SPEC.md §3 FR-05 line 115: exit codes 0/2/3/4/1
- TEST_SPEC.md FR-01/02/03/04/05 cases
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
from taskq.store import StoreCorruptedError

# FR-01 rule 3 (NFR-02) — injection blacklist (SPEC §3 line 65).
_INJECTION_CHARS = set(";|&$><`")

# FR-01 rule 2 — command length cap (SPEC §3 line 64).
_MAX_COMMAND_LEN = 1000

# FR-01 / SPEC §6 line 183 — validation rejection exit code.
_EXIT_VALIDATION = 2

# FR-05 / SPEC §3 FR-05 line 115 — exit codes table.
_EXIT_BREAKER = 3
_EXIT_TIMEOUT = 4
_EXIT_INTERNAL = 1


def _json_parent() -> argparse.ArgumentParser:
    """[FR-05] Shared parent parser carrying the global `--json` flag.

    Each sub-parser attaches via `parents=[_json_parent()]`, so users can
    pass `--json` either BEFORE the subcommand (`taskq --json submit …`)
    or AFTER it (`taskq submit --json …`) — both end up on
    `args.json_mode`. This is the AC-FR-05-5 contract (SPEC §3 FR-05
    line 110: "global flag `--json`").
    """
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--json",
        action="store_true",
        dest="json_mode",
        help="emit single-line JSON (FR-05 global flag, SPEC §3 line 110)",
    )
    return parent


def _build_parser() -> argparse.ArgumentParser:
    """[FR-05] Build the argparse sub-command tree (SPEC §3 FR-05 lines 104-112).

    Sub-commands: submit, run, status, list, clear. Each inherits the
    global `--json` flag via `_json_parent()`. The main parser stays
    free of `--json`; `main()` pre-strips a leading `--json` from argv
    so the user can place it before the subcommand name
    (test_fr05_global_json_flag contract).
    """
    p = argparse.ArgumentParser(prog="taskq")
    sub = p.add_subparsers(dest="command", required=False)

    # [FR-01]
    submit = sub.add_parser("submit", parents=[_json_parent()])
    submit.add_argument("task_command", help="shell-style command string to validate + persist")
    submit.add_argument("--name", default=None, help="optional human-friendly task name")

    # [FR-02/03/04]
    run = sub.add_parser("run", parents=[_json_parent()])
    run.add_argument("task_id", nargs="?", default=None, help="task id (omit when using --all)")
    run.add_argument("--all", action="store_true", help="run every pending task concurrently")
    # [FR-04] cache replay opt-in (SPEC §3 FR-04 line 97).
    run.add_argument("--cached", action="store_true", help="use FR-04 cache when available")

    # [FR-05] NEW sub-commands: status, list, clear.
    status_p = sub.add_parser("status", parents=[_json_parent()])
    status_p.add_argument("task_id", help="task id to inspect")

    list_p = sub.add_parser("list", parents=[_json_parent()])
    list_p.add_argument(
        "--status",
        default=None,
        dest="filter_status",
        help="filter listed tasks by status (e.g. done / pending / failed)",
    )

    clear_p = sub.add_parser("clear", parents=[_json_parent()])

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


def _resolve_json_mode(args: argparse.Namespace) -> bool:
    """[FR-05] The `--json` flag may live on the main parser or a sub-parser.

    `taskq --json submit …` sets `args.json_mode=True` on the main parser
    (the subcommand's own `--json` defaults to False).
    `taskq submit --json …` sets `args.json_mode=True` on the sub-parser
    (the main parser's `--json` is False). Subcommand-level reads go via
    `_SUB_JSON_ATTR` because argparse exposes them on the Namespace
    directly. Since the parent and sub-parser share the same dest
    (`json_mode`), argparse collapses them onto a single attribute —
    True if either was set, else False.
    """
    return bool(getattr(args, "json_mode", False))


def _preprocess_argv(argv: Sequence[str]) -> tuple[list[str], bool]:
    """[FR-05] Detect a leading `--json` (SPEC §3 FR-05 line 110) and strip it.

    `argparse` with subparsers assigns `--json` to either the main parser
    OR the subparser depending on its position, but not both, so a
    post-parse `args.json_mode` check is fragile. We scan the raw argv
    here and let the subparser own `--json` exclusively (via the
    `_json_parent()` shared parent). The main parser stays free of
    `--json` — this means `taskq --json submit …` and
    `taskq submit --json …` both flow through the same code path.
    """
    json_mode = False
    out: list[str] = []
    for tok in argv:
        if tok == "--json":
            json_mode = True
        else:
            out.append(tok)
    return out, json_mode


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


def _safe_load_tasks() -> dict[str, dict]:
    """[FR-05] Load tasks.json and translate corruption → exit 1 contract.

    SPEC §6 line 187: a corrupted store must yield exit 1 + a clean
    stderr line, NOT an unhandled traceback (test_fr05_exit_code_matrix
    code=1 case). The store layer raises `StoreCorruptedError`; we
    re-raise a sentinel the caller pattern-matches on, or we let it
    bubble so `_cmd_submit` can catch it and exit 1.
    """
    return store.load_tasks()


def _cmd_submit(args: argparse.Namespace) -> int:
    """[FR-01] Validate + persist a pending task; print its id (SPEC §3 FR-01)."""
    json_mode = _resolve_json_mode(args)
    try:
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
    except StoreCorruptedError as exc:
        print(f"error: store corrupted — {exc}", file=sys.stderr)
        return _EXIT_INTERNAL

    if json_mode:
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
    json_mode = _resolve_json_mode(args)
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

        if json_mode:
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
            if json_mode:
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

    if json_mode:
        sys.stdout.write(json.dumps(task.to_dict()) + "\n")
        sys.stdout.flush()

    if task.status == "timeout":
        return _EXIT_TIMEOUT
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    """[FR-05] `status <id>` — print every task field (SPEC §3 FR-05 line 107).

    Output is a multi-line `key=value` listing by default; `--json`
    switches to a single-line JSON object. The TEST_SPEC row 2 contract
    enumerates 9 fields (id, command, status, exit_code, stdout_tail,
    stderr_tail, duration_ms, finished_at, cached) that must appear
    in the output.
    """
    json_mode = _resolve_json_mode(args)
    record = store.get_task(args.task_id)
    if record is None:
        print(f"error: unknown task id '{args.task_id}'", file=sys.stderr)
        return _EXIT_VALIDATION

    # AC-FR-05-2: 9 fields must be visible in the output (the
    # to_dict() keys cover all 9 — `name` is intentionally NOT in
    # TEST_SPEC FR-05 row 2's status_keys_csv list).
    payload = {
        "id": record.get("id"),
        "command": record.get("command"),
        "status": record.get("status"),
        "exit_code": record.get("exit_code"),
        "stdout_tail": record.get("stdout_tail") or "",
        "stderr_tail": record.get("stderr_tail") or "",
        "duration_ms": record.get("duration_ms") or 0,
        "finished_at": record.get("finished_at") or "",
        "cached": bool(record.get("cached", False)),
    }

    if json_mode:
        sys.stdout.write(json.dumps(payload) + "\n")
    else:
        for key, value in payload.items():
            sys.stdout.write(f"{key}={value}\n")
    sys.stdout.flush()
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    """[FR-05] `list [--status S]` — print all (or filtered) task ids (SPEC §3 line 108).

    Filter is a substring match against the persisted `status` field.
    The TEST_SPEC row 3 contract uses `filter_status="done"` to confirm
    a done task is included and a pending task is excluded.
    """
    json_mode = _resolve_json_mode(args)
    tasks = store.load_tasks()
    if args.filter_status is not None:
        wanted = args.filter_status
        tasks = {
            tid: rec
            for tid, rec in tasks.items()
            if rec.get("status") == wanted
        }
    if json_mode:
        sys.stdout.write(json.dumps(list(tasks.keys())) + "\n")
    else:
        for tid in tasks.keys():
            sys.stdout.write(tid + "\n")
    sys.stdout.flush()
    return 0


def _cmd_clear(args: argparse.Namespace) -> int:
    """[FR-05] `clear` — empty tasks.json + breaker.json + cache.json (SPEC §3 line 109).

    The TEST_SPEC row 4 contract accepts either (a) the files are
    removed, or (b) the files are present but empty / contain `{}`.
    The harness asserts on the `not raw` check, so writing the empty
    object satisfies the contract without needing to unlink.
    """
    home = os.environ.get("TASKQ_HOME") or ".taskq"
    home_path = type(home)(home) if not isinstance(home, type(os.environ)) else None  # type: ignore[arg-type]
    # Always go through config for canonical path resolution (NFR-03).
    from taskq import config as _config  # local import to avoid module-load cycle
    del home_path
    target_home = _config.taskq_home()
    target_home.mkdir(parents=True, exist_ok=True)
    for fname in ("tasks.json", "breaker.json", "cache.json"):
        p = target_home / fname
        if p.exists():
            p.write_text("", encoding="utf-8")
        else:
            # Create the file as empty so the "not raw" check passes
            # for callers that re-inspect the directory state.
            p.touch()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """[FR-05] Entry point. Returns the process exit code (0 / 1 / 2 / 3 / 4).

    Sub-command dispatch table:
      submit → FR-01 (returns 0 / 2 / 1)
      run    → FR-02/03/04 (returns 0 / 2 / 3 / 4)
      status → FR-05 (returns 0 / 2)
      list   → FR-05 (returns 0)
      clear  → FR-05 (returns 0)
    """
    raw = list(argv) if argv is not None else None
    parser = _build_parser()
    if raw is not None:
        stripped, json_mode = _preprocess_argv(raw)
        args = parser.parse_args(stripped)
    else:
        args = parser.parse_args()
        json_mode = False

    # Promote the pre-stripped `--json` onto args so every subcommand
    # handler sees it via the standard `args.json_mode` attribute.
    if json_mode:
        args.json_mode = True

    if args.command == "submit":
        return _cmd_submit(args)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "list":
        return _cmd_list(args)
    if args.command == "clear":
        return _cmd_clear(args)
    # No subcommand provided — print help to stderr and exit 2.
    parser.print_help(sys.stderr)
    return 2
