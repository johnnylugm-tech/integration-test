"""taskq CLI — submission command.

[FR-01] Citations: SPEC.md §3 FR-01 (Task Submission and Validation).
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Maximum allowed command length per SPEC §3 FR-01 (長度規則).
MAX_COMMAND_LEN = 1000

# Shell-injection characters rejected per NFR-02.
_INJECTION_CHARS = set(";|$>`<")

# Statuses whose ``name`` collides with new submissions per SPEC §3 FR-01
# (名稱唯一規則).
_NAME_BLOCK_STATUSES = {"pending", "running"}

# Path of the persistent store, relative to $TASKQ_HOME.
_TASKS_FILE = "tasks.json"


def _store_path() -> Path:
    """Return the path to ``tasks.json`` inside ``$TASKQ_HOME``.

    Falls back to ``.taskq`` when the env var is unset so the function is
    callable outside the CLI test harness; production usage always sets it.
    """
    home = Path(os.environ.get("TASKQ_HOME", ".taskq"))
    return home / _TASKS_FILE


def _load_tasks(path: Path) -> list[dict[str, Any]]:
    """Load the existing task list, returning ``[]`` when absent."""
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, tasks: list[dict[str, Any]]) -> None:
    """Write ``tasks`` to ``path`` atomically (tmp file + rename)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _validate_command(cmd: str) -> str | None:
    """Return an error message if ``cmd`` violates validation; else ``None``.

    Order matches SPEC §3 FR-01 validation table.
    """
    if not cmd or not cmd.strip():
        return "command must not be empty"
    if len(cmd) > MAX_COMMAND_LEN:
        return f"command exceeds {MAX_COMMAND_LEN} chars"
    bad = sorted(c for c in cmd if c in _INJECTION_CHARS)
    if bad:
        return f"command contains forbidden characters: {''.join(bad)}"
    return None


def _name_conflicts(tasks: list[dict[str, Any]], name: str | None) -> bool:
    """Return True if ``name`` collides with a pending/running task."""
    if not name:
        return False
    return any(
        t.get("name") == name and t.get("status") in _NAME_BLOCK_STATUSES
        for t in tasks
    )


def submit_cmd(cmd: str, name: str | None, json_mode: bool) -> int:
    """Validate and persist a new task. Return the process exit code.

    [FR-01] Citations: SPEC.md §3 FR-01 (validation rules + happy path);
    NFR-02 (injection-char block list).

    Returns ``2`` on any validation rejection, ``0`` on success.
    """
    path = _store_path()

    err = _validate_command(cmd)
    if err is not None:
        print(err, file=sys.stderr)
        return 2

    tasks = _load_tasks(path)
    if _name_conflicts(tasks, name):
        print(f"name already in use: {name}", file=sys.stderr)
        return 2

    task_id = uuid.uuid4().hex[:8]
    task: dict[str, Any] = {
        "id": task_id,
        "status": "pending",
        "name": name,
        "command": cmd,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    tasks.append(task)
    _atomic_write(path, tasks)

    if json_mode:
        print(json.dumps({"id": task_id, "status": "pending"}))
    else:
        print(task_id)
    return 0