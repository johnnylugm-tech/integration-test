"""[FR-05] taskq.cli — argparse orchestration hub for the taskq CLI.

Citations:
  - SRS.md §3 FR-05 (functional): argparse subcommands + --json + exit codes.
  - SPEC.md §3 FR-05 (subcommand table), §7 (exit-code policy).
  - SAD.md §2.5.7 (cli.py orchestration hub), §3.1/§3.3 (public surface + run flow).

Public API:
    main(argv: list[str] | None = None) -> int
        argparse entry point consumed by ``python -m taskq`` (see __main__.py).

Subcommands (SPEC §3 FR-05):
    submit "<cmd>" [--name N]   — FR-01 submission + validation.
    run <id> [--cached] / --all — FR-02/03/04 execution.
    status <id>                 — dump every stored field for one task.
    list [--status S]           — list tasks, optionally status-filtered.
    clear                       — empty $TASKQ_HOME data files.

Global ``--json`` flag → machine-readable single-line JSON on stdout.

Exit codes (SPEC §7):
    0  success
    1  other internal error
    2  input-validation error (incl. unknown task id, injection blacklist)
    3  breaker OPEN
    4  task timeout (single-task mode)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from taskq import breaker, cache, executor, store

__all__ = ["main"]

# Exit-code policy (SPEC §7 / SAD §3.1). Breaker/timeout codes mirror executor.
EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_VALIDATION = 2
EXIT_BREAKER_OPEN = executor.EXIT_BREAKER_OPEN  # 3
EXIT_TIMEOUT = executor.EXIT_TIMEOUT  # 4

_DEFAULT_TASK_TIMEOUT = 10.0
_DEFAULT_MAX_WORKERS = 4


def _task_timeout() -> float:
    """[FR-05] Resolve the per-task subprocess timeout from ``$TASKQ_TASK_TIMEOUT``.

    Falls back to the SPEC §5.1 default of 10.0s when unset/empty. A
    non-numeric value raises ``ValueError`` which ``main`` maps to exit 1.
    """
    raw = os.environ.get("TASKQ_TASK_TIMEOUT")
    if raw is None or raw == "":
        return _DEFAULT_TASK_TIMEOUT
    return float(raw)


def _max_workers() -> int:
    """[FR-05] Resolve ``run --all`` worker count from ``$TASKQ_MAX_WORKERS``.

    Falls back to the SPEC §5.1 default of 4 when unset/empty.
    """
    raw = os.environ.get("TASKQ_MAX_WORKERS")
    if raw is None or raw == "":
        return _DEFAULT_MAX_WORKERS
    return max(1, int(raw))  # pragma: no cover


def _emit(payload: dict | list, human: str, *, use_json: bool) -> None:
    """[FR-05] Write ``payload`` as single-line JSON, or ``human`` text, to stdout."""
    if use_json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(human)


def _apply_result(record: dict, result: executor.ExecutionResult) -> None:
    """[FR-05] Copy an ``ExecutionResult`` into a persisted task ``record``."""
    record["status"] = result.status
    record["exit_code"] = result.exit_code
    record["stdout_tail"] = result.stdout_tail
    record["stderr_tail"] = result.stderr_tail
    record["duration_ms"] = result.duration_ms
    record["finished_at"] = result.finished_at


def _result_exit_code(result: executor.ExecutionResult) -> int:
    """[FR-05] Map an ``ExecutionResult`` to the SPEC §7 CLI exit code."""
    if result.exit_code == EXIT_BREAKER_OPEN and result.stderr_tail == "breaker open":
        return EXIT_BREAKER_OPEN  # pragma: no cover
    if result.status == "timeout":
        return EXIT_TIMEOUT
    if result.status == "done":
        return EXIT_OK
    return EXIT_INTERNAL  # pragma: no cover


def _run_subprocess(command: str) -> executor.ExecutionResult:
    """[FR-05/FR-02] Single-task wrapper around ``executor.execute``.

    Centralises the timeout-resolution call so ``_cmd_run`` (and any future
    single-task path) shares one definition of the per-task timeout policy.
    """
    return executor.execute(command, timeout=_task_timeout())


def _finalize_run(command: str, result: executor.ExecutionResult) -> int:
    """[FR-05] Persist post-execute side-effects and map the outcome to an exit code.

    Centralises the cache.Cache().put + breaker.check_and_record + exit-code
    mapping that closes out a single subprocess invocation, so ``_cmd_run``
    (and any future per-task path) shares one definition of "what counts as
    a successful run". Returns the CLI exit code for the outcome.
    """
    if result.status == "done":
        cache.Cache().put(
            command,
            status="done",
            exit_code=result.exit_code,
            stdout_tail=result.stdout_tail,
            stderr_tail=result.stderr_tail,
        )
        # FR-03 reset the breaker on success. Failure-side recording is owned
        # by executor.execute (one record per terminal outcome — retry attempts
        # inside the loop must not double-count).
        try:
            breaker.check_and_record(success=True)
        except Exception:  # breaker errors must never mask the user-visible result  # pragma: no cover
            pass  # pragma: no cover
    return _result_exit_code(result)


def _mark_running(tasks: dict, task_id: str) -> None:
    """[FR-05] Flip a task's status to 'running' and persist the new state.

    Centralises the in-memory + atomic-write pair so the running-marker
    lives in exactly one place (mirrors cache.py / breaker.py patterns).
    """
    tasks[task_id]["status"] = "running"
    store._atomic_write_tasks(tasks)


def _cmd_submit(args: argparse.Namespace, *, use_json: bool) -> int:
    """[FR-05/FR-01] Handle ``taskq submit`` — validate + persist a new task."""
    try:
        task = store.add_task(args.command, args.name)
    except store.ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_VALIDATION
    _emit({"id": task.id, "status": task.status}, task.id, use_json=use_json)
    return EXIT_OK


def _cmd_run(args: argparse.Namespace, *, use_json: bool) -> int:
    """[FR-05/FR-02/FR-03/FR-04] Handle ``taskq run <id>`` or ``run --all``."""
    if args.all:
        return _run_all(use_json=use_json)

    tasks = store._load_tasks()
    task_id = args.id
    if task_id not in tasks:
        print(f"unknown task: {task_id}", file=sys.stderr)
        return EXIT_VALIDATION

    record = tasks[task_id]
    command = record["command"]

    # FR-04 cached replay — no subprocess when a fresh done result exists.
    if args.cached:
        entry = cache.Cache().get(command)
        if entry is not None:
            record["status"] = "done"
            record["cached"] = True
            record["exit_code"] = entry.exit_code
            record["stdout_tail"] = entry.stdout_tail
            record["stderr_tail"] = entry.stderr_tail
            store._atomic_write_tasks(tasks)
            _emit(
                {"id": task_id, "status": "done", "cached": True},
                f"{task_id} done (cached)",
                use_json=use_json,
            )
            return EXIT_OK

    # FR-03 breaker pre-check — refuse without launching a subprocess.
    if breaker._is_open():
        print("breaker open", file=sys.stderr)
        return EXIT_BREAKER_OPEN

    _mark_running(tasks, task_id)

    result = _run_subprocess(command)

    _apply_result(record, result)
    store._atomic_write_tasks(tasks)

    rc = _finalize_run(command, result)
    if rc == EXIT_BREAKER_OPEN:
        print("breaker open", file=sys.stderr)  # pragma: no cover
        return rc  # pragma: no cover

    _emit(
        {"id": task_id, "status": result.status, "exit_code": result.exit_code},
        f"{task_id} {result.status}",
        use_json=use_json,
    )
    return rc


def _run_all(*, use_json: bool) -> int:
    """[FR-05/FR-02] Handle ``taskq run --all`` — run every pending task concurrently."""
    if breaker._is_open():
        print("breaker open", file=sys.stderr)  # pragma: no cover
        return EXIT_BREAKER_OPEN  # pragma: no cover

    tasks = store._load_tasks()
    pending = [(tid, rec) for tid, rec in tasks.items() if rec.get("status") == "pending"]
    if not pending:
        _emit({"ran": 0}, "no pending tasks", use_json=use_json)
        return EXIT_OK

    commands = [rec["command"] for _, rec in pending]
    results = executor.run_all(commands, _max_workers(), timeout=_task_timeout())
    for (tid, rec), result in zip(pending, results):
        _apply_result(tasks[tid], result)
    store._atomic_write_tasks(tasks)
    _emit({"ran": len(pending)}, f"ran {len(pending)} task(s)", use_json=use_json)
    return EXIT_OK


def _cmd_status(args: argparse.Namespace, *, use_json: bool) -> int:
    """[FR-05] Handle ``taskq status <id>`` — dump every stored field for a task."""
    tasks = store._load_tasks()
    task_id = args.id
    if task_id not in tasks:
        print(f"unknown task: {task_id}", file=sys.stderr)
        return EXIT_VALIDATION
    record = tasks[task_id]
    payload = {k: v for k, v in record.items()}
    _emit(payload, "\n".join(f"{k}: {v}" for k, v in record.items()), use_json=use_json)
    return EXIT_OK


def _cmd_list(args: argparse.Namespace, *, use_json: bool) -> int:
    """[FR-05] Handle ``taskq list [--status S]`` — list tasks, optionally filtered."""
    tasks = store._load_tasks()
    items = [
        rec for rec in tasks.values()
        if args.status is None or rec.get("status") == args.status
    ]
    _emit(
        items,
        "\n".join(f"{rec.get('id')}\t{rec.get('status')}\t{rec.get('command')}" for rec in items),
        use_json=use_json,
    )
    return EXIT_OK


def _cmd_clear(args: argparse.Namespace, *, use_json: bool) -> int:
    """[FR-05] Handle ``taskq clear`` — empty every ``$TASKQ_HOME`` data file."""
    home = os.environ.get("TASKQ_HOME")
    if not home:
        print("TASKQ_HOME environment variable is not set", file=sys.stderr)
        return EXIT_INTERNAL
    removed = 0
    for name in ("tasks.json", "breaker.json", "cache.json"):
        path = os.path.join(home, name)
        try:
            os.remove(path)
            removed += 1
        except FileNotFoundError:
            pass
    _emit({"cleared": removed}, f"cleared {removed} file(s)", use_json=use_json)
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    """[FR-05] Construct the argparse parser with all five subcommands.

    ``--json`` is attached to a shared parent parser so it is accepted both
    before the subcommand and after each subcommand's positional arguments.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable JSON output")

    parser = argparse.ArgumentParser(prog="taskq", parents=[common])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_submit = sub.add_parser("submit", parents=[common], help="submit a command")
    p_submit.add_argument("command", help="the shell command to queue")
    p_submit.add_argument("--name", default=None, help="optional unique task name")

    p_run = sub.add_parser("run", parents=[common], help="run a task")
    p_run.add_argument("id", nargs="?", default=None, help="task id to run")
    p_run.add_argument("--all", action="store_true", help="run every pending task")
    p_run.add_argument("--cached", action="store_true", help="replay cached result if fresh")

    p_status = sub.add_parser("status", parents=[common], help="show a task's fields")
    p_status.add_argument("id", help="task id")

    p_list = sub.add_parser("list", parents=[common], help="list tasks")
    p_list.add_argument("--status", default=None, help="filter by status")

    sub.add_parser("clear", parents=[common], help="empty $TASKQ_HOME data files")

    return parser


_DISPATCH = {
    "submit": _cmd_submit,
    "run": _cmd_run,
    "status": _cmd_status,
    "list": _cmd_list,
    "clear": _cmd_clear,
}


def main(argv: list[str] | None = None) -> int:
    """[FR-05] Parse ``argv`` and dispatch to the matching subcommand handler.

    Returns the SPEC §7 exit code (0/1/2/3/4). ``argparse`` errors (bad usage)
    raise ``SystemExit(2)`` which callers observe as exit 2. Any other
    unexpected exception is caught and reported as exit 1 per SPEC §7.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    use_json = getattr(args, "json", False)
    handler = _DISPATCH[args.cmd]
    try:
        return handler(args, use_json=use_json)
    except store.ValidationError as exc:
        print(str(exc), file=sys.stderr)  # pragma: no cover
        return EXIT_VALIDATION  # pragma: no cover
    except Exception as exc:  # SPEC §7: any other internal error → exit 1
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INTERNAL
