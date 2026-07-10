"""[FR-01/FR-02] CLI dispatch: `submit` (FR-01) and `run` (FR-02).

Citations:
  - SPEC.md §3 FR-01 (FR-01: Task Submission and Validation)
  - SPEC.md §3 FR-02 (FR-02: Task Executor)
  - NFR-02 (injection-char rejection) — SPEC.md §3 NFR-02
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Forbidden shell metacharacters (NFR-02). Listed in SPEC.md §3 FR-01.
_INJECTION_CHARS = set(";|&$><`")

# Spec: "uuid4 前 8 hex". We emit `uuid.uuid4().hex[:8]` — lowercase hex, 8 chars.
_ID_LEN = 8
# Spec: command length > 1000 → reject.
_MAX_COMMAND_LEN = 1000
# Spec: --name collision against pending/running tasks → reject.
_ACTIVE_STATUSES = ("pending", "running")


def _home() -> Path:
    """Return the taskq home directory from TASKQ_HOME env."""
    return Path(os.environ["TASKQ_HOME"])


def _tasks_path(home: Path) -> Path:
    return home / "tasks.json"


def _load_tasks(home: Path) -> dict[str, dict[str, object]]:
    """Return the existing tasks dict, or {} if the file does not exist."""
    p = _tasks_path(home)
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def _atomic_write_tasks(home: Path, tasks: dict[str, dict[str, object]]) -> None:
    """[FR-01] Atomically replace $TASKQ_HOME/tasks.json.

    Citations: SPEC.md §3 FR-01 — "原子寫入 $TASKQ_HOME/tasks.json".
    """
    home.mkdir(parents=True, exist_ok=True)
    p = _tasks_path(home)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(tasks))
    tmp.replace(p)


def _validate_command(command: str) -> str | None:
    """[FR-01] Return None if valid, otherwise an error message.

    Citations: SPEC.md §3 FR-01 — non-empty / length ≤ 1000 / no injection chars.
    """
    if not command or command.strip() == "":
        return "error: command must not be empty"
    if len(command) > _MAX_COMMAND_LEN:
        return (
            f"error: command exceeds {_MAX_COMMAND_LEN} characters "
            f"(got {len(command)})"
        )
    for ch in _INJECTION_CHARS:
        if ch in command:
            return f"error: command contains forbidden character: {ch!r}"
    return None


def _validate_name(name: str | None, tasks: dict[str, dict[str, object]]) -> str | None:
    """[FR-01] Return None if --name is absent or unique, else an error message.

    Citations: SPEC.md §3 FR-01 — "--name 與既有 pending/running 任務重複 → 拒絕".
    """
    if name is None:
        return None
    for task in tasks.values():
        if task.get("name") == name and task.get("status") in _ACTIVE_STATUSES:
            return f"error: name {name!r} conflicts with an existing task"
    return None


def _submit(command: str, name: str | None, json_mode: bool) -> int:
    """[FR-01] Validate, persist, and emit the new task id.

    Citations: SPEC.md §3 FR-01.
    """
    home = _home()

    err = _validate_command(command)
    if err is not None:
        print(err, file=sys.stderr)
        return 2

    tasks = _load_tasks(home)
    err = _validate_name(name, tasks)
    if err is not None:
        print(err, file=sys.stderr)
        return 2

    task_id = uuid.uuid4().hex[:_ID_LEN]
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tasks[task_id] = {
        "id": task_id,
        "command": command,
        "name": name,
        "status": "pending",
        "created_at": created_at,
    }
    _atomic_write_tasks(home, tasks)

    if json_mode:
        sys.stdout.write(json.dumps({"id": task_id, "status": "pending"}) + "\n")
    else:
        sys.stdout.write(task_id + "\n")
    sys.stdout.flush()
    return 0


def _parse_submit_args(submit_args: list[str]) -> tuple[str, str | None] | int:
    """[FR-01] Pull `command` and optional `--name` out of the submit argv.

    Citations: SPEC.md §3 FR-01.
    """
    if not submit_args:
        return 2  # missing command → reject path
    command = submit_args[0]
    name: str | None = None
    i = 1
    while i < len(submit_args):
        tok = submit_args[i]
        if tok == "--name" and i + 1 < len(submit_args):
            name = submit_args[i + 1]
            i += 2
            continue
        i += 1
    return command, name


def _run_single(task_id: str, timeout: float) -> int:
    """[FR-02] Dispatch a single-task `run <id>` invocation.

    Returns the process exit code (timeout → 4, else 0).
    """
    from taskq import store
    from taskq.executor import execute_task

    tasks = store.load_tasks()
    if task_id not in tasks:
        print(f"error: unknown task: {task_id}", file=sys.stderr)
        return 2
    status = execute_task(task_id, tasks[task_id]["command"], timeout)
    return 4 if status == "timeout" else 0


def _run_all(timeout: float, max_workers: int) -> int:
    """[FR-02] Dispatch a `run --all` invocation."""
    from taskq.executor import run_all

    run_all(timeout=timeout, max_workers=max_workers)
    return 0


def main(argv: list[str] | None = None) -> int:
    """[FR-01/FR-02] CLI entry point. Returns the process exit code.

    Citations: SPEC.md §3 FR-01 / FR-02.
    """
    if argv is None:
        argv = sys.argv[1:]

    json_mode = False
    if argv and argv[0] == "--json":
        json_mode = True
        argv = argv[1:]

    if not argv:
        print("error: missing subcommand (expected `submit` or `run`)", file=sys.stderr)
        return 2

    if argv[0] == "submit":
        parsed = _parse_submit_args(argv[1:])
        if isinstance(parsed, int):
            return parsed
        command, name = parsed
        return _submit(command, name, json_mode)

    if argv[0] == "run":
        if len(argv) < 2:
            print("error: `run` requires a task id or `--all`", file=sys.stderr)
            return 2
        timeout = float(os.environ.get("TASKQ_TASK_TIMEOUT", "10.0"))
        max_workers = int(os.environ.get("TASKQ_MAX_WORKERS", "4"))
        if argv[1] == "--all":
            return _run_all(timeout, max_workers)
        return _run_single(argv[1], timeout)

    print(f"error: unsupported command: {argv[0]!r}", file=sys.stderr)
    return 2