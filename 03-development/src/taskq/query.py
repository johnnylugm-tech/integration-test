"""[FR-03]

Query operations: status, list, clear.

Citations:
- SPEC.md S3 FR-03 (status <id>, list, clear subcommands).
- 02-architecture/SAD.md S2.3 (query.py responsibilities).
- tests/test_fr03.py (GREEN contract — structured results).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from taskq.config import tasks_file
from taskq.io.store import load_tasks


class UnknownTaskError(Exception):
    """[FR-03] Raised when `status(task_id)` cannot find the task id.

    Citations:
        - SPEC.md S3 FR-03 (unknown id -> exit 2 + "unknown task: <id>").
    """


def status(task_id: str) -> Dict[str, Any]:
    """[FR-03] Return the full task record for *task_id*.

    Citations:
        - SPEC.md S3 FR-03 (status <id> outputs all task fields).
        - tests/test_fr03.py case 24 (unknown_id -> exit 2 + stderr message).

    Raises:
        UnknownTaskError: no task with the given id exists.
    """
    tasks = load_tasks()
    for t in tasks:
        if t.get("id") == task_id:
            return t
    raise UnknownTaskError(task_id)


def list_tasks() -> List[Dict[str, Any]]:
    """[FR-03] Return all tasks as (id, status, command[:50]) projections.

    Citations:
        - SPEC.md S3 FR-03 (list: id + status + command first 50 chars).
        - tests/test_fr03.py case 25 (truncation at 50 chars).
    """
    tasks = load_tasks()
    result = []
    for t in tasks:
        result.append({
            "id": t.get("id", ""),
            "status": t.get("status", ""),
            "command": (t.get("command", "") or "")[:50],
        })
    return result


def clear() -> None:
    """[FR-03] Delete $TASKQ_HOME/tasks.json.

    Idempotent: no error if the file does not exist.

    Citations:
        - SPEC.md S3 FR-03 (clear: empty $TASKQ_HOME/tasks.json).
        - 02-architecture/SAD.md D-01 (hard-unlink, not load+filter+rewrite).
        - tests/test_fr03.py case 26 (post-clear json_valid == False).
    """
    path = tasks_file()
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def format_task_human(task: Dict[str, Any]) -> str:
    """[FR-03] Return a human-readable string for one task (all fields).

    Citations:
        - SPEC.md S3 FR-03 (status <id> prints all task fields).
    """
    lines = []
    for key, value in task.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def format_task_json(task: Dict[str, Any]) -> str:
    """[FR-03] Return a single-line JSON string for one task.

    Citations:
        - SPEC.md S3 FR-03 (--json flag: machine-readable single-line JSON).
    """
    return json.dumps(task, ensure_ascii=False, separators=(",", ":"))


def format_list_human(tasks: List[Dict[str, Any]]) -> str:
    """[FR-03] Return a human-readable table of tasks (id, status, command[:50]).

    Citations:
        - SPEC.md S3 FR-03 (list: id + status + command first 50 chars).
    """
    if not tasks:
        return ""
    lines = []
    for t in tasks:
        lines.append(f"{t['id']}\t{t['status']}\t{t['command']}")
    return "\n".join(lines)


def format_list_json(tasks: List[Dict[str, Any]]) -> str:
    """[FR-03] Return a single-line JSON array of task projections.

    Citations:
        - SPEC.md S3 FR-03 (--json flag: machine-readable single-line JSON).
    """
    return json.dumps(tasks, ensure_ascii=False, separators=(",", ":"))
