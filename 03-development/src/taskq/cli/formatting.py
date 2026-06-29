"""Output formatting helpers for the taskq CLI.

[FR-03] Citations:
- SPEC.md §3 FR-03 全域 flag --json — 單行 JSON, stdout 不可含換行.
- SPEC.md §3 FR-03 子命令表 list row — id + status + command 前 50 字元.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable

from taskq.core.models import Task

_LIST_CMD_LIMIT = 50


def _task_to_jsonable(task: Task) -> dict:
    """Project a :class:`Task` onto the JSON-serialisable dict used by --json.

    [FR-03] Citations: SPEC.md §3 FR-03 全域 flag --json (機器可讀輸出).
    """
    created = task.created_at
    if isinstance(created, datetime):
        created = created.isoformat()
    return {
        "id": task.id,
        "command": task.command,
        "status": task.status.value,
        "created_at": created,
    }


def format_task_json(task: Task) -> str:
    """Return a single-line JSON serialisation of ``task``.

    [FR-03] Citations: SPEC.md §3 FR-03 全域 flag --json — 單行 JSON,
    stdout 不可含換行.
    """
    return json.dumps(_task_to_jsonable(task), ensure_ascii=False)


def format_tasks_json(tasks: Iterable[Task]) -> str:
    """Return a single-line JSON array of all ``tasks``.

    [FR-03] Citations: SPEC.md §3 FR-03 全域 flag --json — 單行 JSON.
    """
    return json.dumps([_task_to_jsonable(t) for t in tasks], ensure_ascii=False)


def format_task_human(task: Task) -> str:
    """Return the human-readable single-line view of ``task``.

    [FR-03] Citations: SPEC.md §3 FR-03 status <id> — 輸出該任務全欄位.
    """
    return (
        f"id={task.id} status={task.status.value} "
        f"command={task.command!r} created_at={task.created_at.isoformat()}"
    )


def format_tasks_human(tasks: Iterable[Task]) -> str:
    """Return the human-readable ``list`` output.

    [FR-03] Citations: SPEC.md §3 FR-03 子命令表 list row — id + status +
    command 前 50 字元.
    """
    lines = []
    for task in tasks:
        cmd = task.command
        if len(cmd) > _LIST_CMD_LIMIT:
            cmd = cmd[:_LIST_CMD_LIMIT]
        lines.append(f"{task.id}\t{task.status.value}\t{cmd}")
    return "\n".join(lines)