"""taskq task store — atomic JSON R/W + threading.Lock + secret redaction.

[FR-01] [FR-02] [NFR-03] [NFR-04]
Handles tasks.json with atomic writes (tmp + os.replace) and a shared Lock.
Redacts sensitive patterns in stdout_tail/stderr_tail before persistence.
"""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Optional

from taskq._atomic import atomic_write
from taskq.config import Config, validate_config
from taskq.models import Task, TaskStatus

# Backward-compat alias: previous code/tests imported _atomic_write from store.
_atomic_write = atomic_write

_LOCK = threading.Lock()

_REDACT_PATTERN = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|token=\S+)")


def load_tasks(cfg: Config) -> dict[str, Task]:
    """Load all tasks from $TASKQ_HOME/tasks.json.

    [FR-01] [FR-02] Returns a dict of id → Task.
    Raises SystemExit(1) with stderr 'store corrupted' if JSON is invalid.
    """
    _ = validate_config(cfg)
    path = os.path.join(cfg.home, "tasks.json")
    if not os.path.exists(path):
        return {}
    with _LOCK:
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError:
            import sys
            print("store corrupted", file=sys.stderr)
            raise SystemExit(1)
    return {tid: _dict_to_task(tid, data) for tid, data in raw.items()}


def load_task(task_id: str, cfg: Config) -> Task:
    """Load a single task by id from tasks.json.

    [FR-01] [FR-02] Raises SystemExit(2) with 'unknown task: <id>' if not found.
    """
    _ = validate_config(cfg)
    tasks = load_tasks(cfg)
    if task_id not in tasks:
        import sys
        print(f"unknown task: {task_id}", file=sys.stderr)
        raise SystemExit(2)
    return tasks[task_id]


def save_task(task: Task, cfg: Config) -> None:
    """Atomically write a task to $TASKQ_HOME/tasks.json.

    [FR-01] [FR-02] [NFR-03] [NFR-04]
    Thread-safe via module-level Lock. Redacts secrets before persistence.
    Uses tmp + os.replace for atomicity.
    """
    _ = validate_config(cfg)
    path = os.path.join(cfg.home, "tasks.json")
    with _LOCK:
        # Load existing
        existing: dict = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                existing = {}
        # Merge
        existing[task.id] = _task_to_dict(task)
        atomic_write(path, existing)


def _redact(text: Optional[str]) -> Optional[str]:
    """Redact sensitive patterns line-by-line from output text.

    [NFR-04] Replaces lines matching sk-*/token=* with '[REDACTED]'.
    """
    if text is None:
        return None
    lines = text.splitlines(keepends=True)
    result = []
    for line in lines:
        if _REDACT_PATTERN.search(line):
            result.append("[REDACTED]\n")
        else:
            result.append(line)
    return "".join(result)


def _task_to_dict(task: Task) -> dict:
    """Serialise a Task to a JSON-safe dict, applying secret redaction.

    [NFR-04] stdout_tail and stderr_tail are redacted before serialisation.
    """
    return {
        "command": task.command,
        "name": task.name,
        "status": task.status.value if hasattr(task.status, "value") else task.status,
        "created_at": task.created_at,
        "exit_code": task.exit_code,
        "stdout_tail": _redact(task.stdout_tail),
        "stderr_tail": _redact(task.stderr_tail),
        "duration_ms": task.duration_ms,
        "finished_at": task.finished_at,
        "cached": task.cached,
    }


def _dict_to_task(task_id: str, data: dict) -> Task:
    """Deserialise a dict from tasks.json back to a Task.

    [FR-01] [FR-02]
    """
    status_val = data.get("status", "pending")
    try:
        status = TaskStatus(status_val)
    except ValueError:
        status = TaskStatus.pending
    return Task(
        id=task_id,
        command=data.get("command", ""),
        name=data.get("name"),
        status=status,
        created_at=data.get("created_at", ""),
        exit_code=data.get("exit_code"),
        stdout_tail=data.get("stdout_tail"),
        stderr_tail=data.get("stderr_tail"),
        duration_ms=data.get("duration_ms"),
        finished_at=data.get("finished_at"),
        cached=data.get("cached", False),
    )
