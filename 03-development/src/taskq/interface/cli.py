"""taskq CLI — argument parsing, validation, and exit code mapping.

[FR-01, FR-03, FR-04, FR-05, NFR-02, NFR-05, NFR-07]
Citations: SPEC.md line 57 (FR-01 task submission + validation),
           SPEC.md line 73 (8-hex id / pending / atomic write / --json output),
           SPEC.md line 91 (FR-03 breaker: exit 3 + "breaker open" stderr on reject),
           SPEC.md line 99 (FR-04 TTL cache + replay),
           SPEC.md line 106 (argparse subcommand table),
           SAD.md line 86 (cli submit/run + exit code mapping),
           SAD.md line 270 (cache.json shape),
           SAD.md line 281 (breaker OPEN mapped to exit 3 at the cli boundary),
           TEST_SPEC.md line 61-70 (FR01 sub-assertions).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Sequence

from taskq.core.models import RunResult, TaskStatus
from taskq.runtime.executor import run_with_retry
from taskq.storage.breaker import Breaker
from taskq.storage.cache import Cache
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
    active = (TaskStatus.PENDING.value, TaskStatus.RUNNING.value)
    for task in store.load().values():
        if task.get("name") != name:
            continue
        status = task.get("status")
        if status in active:
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
    except OSError as exc:  # pragma: no cover — defensive fs-write failure during submit
        sys.stderr.write(f"error: failed to persist task: {exc}\n")
        return 1

    _emit_submit_result(task.id, as_json=bool(args.json))
    return 0


def _env_int(name: str, default: str) -> int:
    """Read ``$name`` as int, falling back to ``default``."""
    return int(os.environ.get(name, default))


def _env_float(name: str, default: str) -> float:
    """Read ``$name`` as float, falling back to ``default``."""
    return float(os.environ.get(name, default))


def _task_timeout() -> float:
    """Return the per-task subprocess timeout in seconds (TASKQ_TASK_TIMEOUT).

    [FR-02, NFR-06]
    Citations: SPEC.md line 132 (TASKQ_TASK_TIMEOUT default 10.0).
    """
    return _env_float("TASKQ_TASK_TIMEOUT", "10.0")


def _max_workers() -> int:
    """Return the run --all concurrency worker count (TASKQ_MAX_WORKERS).

    [FR-02, NFR-06]
    Citations: SPEC.md line 131 (TASKQ_MAX_WORKERS default 4).
    """
    return _env_int("TASKQ_MAX_WORKERS", "4")


def _retry_limit() -> int:
    """Return the automatic-retry cap (TASKQ_RETRY_LIMIT).

    [FR-03]
    Citations: SPEC.md line 149 (TASKQ_RETRY_LIMIT default 2).
    """
    return _env_int("TASKQ_RETRY_LIMIT", "2")


def _backoff_base() -> float:
    """Return the exponential-backoff base in seconds (TASKQ_BACKOFF_BASE).

    [FR-03]
    Citations: SPEC.md line 150 (TASKQ_BACKOFF_BASE default 0.1).
    """
    return _env_float("TASKQ_BACKOFF_BASE", "0.1")


def _breaker_threshold() -> int:
    """Return the consecutive-final-failure count that opens the breaker.

    [FR-03]
    Citations: SPEC.md line 151 (TASKQ_BREAKER_THRESHOLD default 3).
    """
    return _env_int("TASKQ_BREAKER_THRESHOLD", "3")


def _breaker_cooldown() -> float:
    """Return the OPEN -> HALF_OPEN cooldown in seconds (TASKQ_BREAKER_COOLDOWN).

    [FR-03]
    Citations: SPEC.md line 152 (TASKQ_BREAKER_COOLDOWN default 5.0).
    """
    return _env_float("TASKQ_BREAKER_COOLDOWN", "5.0")


def _cache_ttl() -> int:
    """Return the FR-04 cache TTL in seconds (TASKQ_CACHE_TTL).

    [FR-04]
    Citations: SPEC.md line 99 (TTL cache; same `command` within TTL -> replay).
    Default = 0 (cache disabled; every ``--cached`` miss falls through to a
    fresh execution). This is intentionally conservative per NFR-07: cache
    is an optimization, opt-in via TASKQ_CACHE_TTL.
    """
    return int(os.environ.get("TASKQ_CACHE_TTL", "0"))


def _signature(command: str) -> str:
    """Return the FR-04 cache signature = sha256(command).

    [FR-04]
    Citations: SPEC.md line 99 (cache signature = sha256(command)).
    """
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def _new_cache(home: Path) -> Cache:
    """Return a TTL cache configured from TASKQ_CACHE_TTL."""
    return Cache(home, ttl=_cache_ttl())


def _replay_cached_task(store: Store, task: dict, cache: Cache) -> bool:
    """Replay a fresh cached result into ``task`` when present."""
    cached_result = cache.lookup(_signature(task["command"]))
    if cached_result is None:
        return False
    fields = cached_result.to_fields()
    fields["cached"] = True
    store.update_status(task["id"], **fields)
    return True


def _run_one(
    store: Store,
    task: dict,
    timeout: float,
    cache: Optional[Cache] = None,
) -> RunResult:
    """Execute a single task: mark running, run it (with retry), persist result.

    [FR-02, FR-03, FR-04, NFR-03]
    Citations: SPEC.md line 88 (state machine pending->running->done|failed|timeout),
               SPEC.md line 89 (FR-03 retry on failed/timeout),
               SAD.md line 210 (executor -> store write-back),
               SAD.md line 116 (cache put only when executor actually runs AND
               result status is done — failures absorb; see Cache.put).
    """
    store.update_status(task["id"], status=TaskStatus.RUNNING.value)
    result = run_with_retry(
        task["command"],
        timeout=timeout,
        retry_limit=_retry_limit(),
        backoff_base=_backoff_base(),
    )
    store.update_status(task["id"], **result.to_fields())
    # FR-04: persist the cache entry only when the executor actually ran AND
    # the final result is `done`. Cache.put is best-effort (NFR-07): write
    # failures are absorbed inside Cache.put, never propagate to the caller.
    if cache is not None and result.status == TaskStatus.DONE:
        cache.put(_signature(task["command"]), result)
    return result


def _cmd_run(args: argparse.Namespace) -> int:
    """Run subcommand: `run <id>` (single) or `run --all` (concurrent pending).

    [FR-02, FR-03, FR-04, FR-05]
    Citations: SPEC.md line 88 (run <id> / run --all; single-task timeout exit 4),
               SPEC.md line 91-94 (FR-03 breaker: OPEN rejects with exit 3),
               SPEC.md line 99 (FR-04 TTL cache, --cached replay),
               SPEC.md line 106 (exit code map),
               SAD.md line 129 (executor is FR-02 primary module),
               SAD.md line 225 (cache replay flow: lookup -> update_status
               done+cached=True OR fall through to executor),
               SAD.md line 281 (breaker.allow()==False -> exit 3 at cli boundary).

    Breaker gating applies to the single-id path only: `Breaker` persists to
    a shared file with no locking of its own, and `run --all` dispatches
    `_run_one` across a thread pool (SAD.md line 210), so concurrent
    allow()/record() calls there would race on breaker.json. No AC in
    TEST_SPEC.md FR-03 exercises breaker + `--all` together.

    FR-04 ``--cached``: on hit (entry present, status==done, within TTL)
    the cache-hit path skips executor + breaker entirely, applies the
    replayed RunResult fields to the task record, and marks ``cached=True``
    (SPEC §3 FR-04 "不執行 subprocess"). On miss/expiry the request falls
    through to the normal execution path.
    """
    home = _default_home()
    store = Store(home)

    if args.run_all:
        cache = _new_cache(home)
        timeout = _task_timeout()
        pending = [
            t for t in store.load().values()
            if t.get("status") == TaskStatus.PENDING.value
        ]
        with ThreadPoolExecutor(max_workers=_max_workers()) as pool:
            futures = [pool.submit(_run_one, store, t, timeout, cache) for t in pending]
            for fut in as_completed(futures):
                fut.result()  # propagate any worker exception
        return 0

    task_id: Optional[str] = args.task_id
    if task_id is None:
        sys.stderr.write("error: run requires a task id or --all\n")
        return 2
    task = store.get(task_id)
    if task is None:
        sys.stderr.write(f"error: unknown task: {task_id}\n")
        return 2

    cache = _new_cache(home)
    # FR-04 cache-hit path: when --cached is requested and the cache holds a
    # fresh entry, bypass executor + breaker and replay the stored result.
    if args.cached and _replay_cached_task(store, task, cache):
        return 0
    # Cache miss / expired -> fall through to normal execution.

    breaker = Breaker(home, threshold=_breaker_threshold(), cooldown=_breaker_cooldown())
    if not breaker.allow():
        sys.stderr.write("error: breaker open\n")
        return 3

    result = _run_one(store, task, _task_timeout(), cache)
    breaker.record(result.status == TaskStatus.DONE)
    # SPEC §5: single-task timeout maps to exit 4; a task that ran (done/failed)
    # is not itself a CLI failure, so those return 0.
    if result.status == TaskStatus.TIMEOUT:
        return 4
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Status subcommand: print all persisted fields of a single task.

    [FR-02, FR-05]
    Citations: SPEC.md line 106 (status <id> outputs full task fields),
               SPEC.md line 106 (unknown task id -> exit 2).
    """
    home = _default_home()
    store = Store(home)
    task = store.get(args.task_id)
    if task is None:
        sys.stderr.write(f"error: unknown task: {args.task_id}\n")
        return 2
    if args.json:
        sys.stdout.write(json.dumps(task) + "\n")
    else:
        for key, value in task.items():
            sys.stdout.write(f"{key}: {value}\n")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taskq")
    sub = parser.add_subparsers(dest="subcommand")

    submit_p = sub.add_parser("submit", help="submit a new task")
    submit_p.add_argument("command", help="shell command to run")
    submit_p.add_argument("--name", default=None, help="optional task name (must be unique)")
    submit_p.add_argument("--json", action="store_true", help="emit JSON to stdout")

    run_p = sub.add_parser("run", help="run a task by id, or --all pending tasks")
    run_p.add_argument("task_id", nargs="?", default=None, help="task id to run")
    run_p.add_argument("--all", action="store_true", dest="run_all",
                       help="run all pending tasks concurrently")
    run_p.add_argument("--cached", action="store_true", dest="cached",
                       help="[FR-04] consult the TTL result cache first; on a "
                            "fresh hit replay the cached exit_code/stdout_tail "
                            "and skip subprocess (requires TASKQ_CACHE_TTL > 0)")
    run_p.add_argument("--json", action="store_true", help="emit JSON to stdout")

    status_p = sub.add_parser("status", help="show all fields of a task")
    status_p.add_argument("task_id", help="task id to inspect")
    status_p.add_argument("--json", action="store_true", help="emit JSON to stdout")

    # Stubs for FR-05 subcommands not owned by FR-02. They exit with code 3
    # (per SAD exit code map: not implemented for this phase).
    for name in ("list", "clear"):
        p = sub.add_parser(name, add_help=True)
        p.add_argument("rest", nargs=argparse.REMAINDER)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point.

    [FR-01, FR-02, FR-05, NFR-05]
    Citations: SAD.md line 86 (cli.main + exit code mapping),
               SAD.md line 195 (submit entry point flow),
               SPEC.md line 88 (FR-02 run/status dispatch).
    """
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.subcommand == "submit":
        return _cmd_submit(args)
    if args.subcommand == "run":
        return _cmd_run(args)
    if args.subcommand == "status":
        return _cmd_status(args)
    if args.subcommand in ("list", "clear"):
        sys.stderr.write(f"error: subcommand {args.subcommand!r} not implemented yet\n")
        return 3
    parser.print_help(sys.stderr)
    return 4