"""Atomic JSON store for the task queue.

[FR-01] Citations:
- SPEC.md §3 FR-01 通過驗證 bullet 4 — 原子寫入 ``$TASKQ_HOME/tasks.json``
  via tmp + ``os.replace``.
- SPEC.md §3 FR-01 通過驗證 bullet 5 — ``tasks.json`` 損壞偵測 → exit 1,
  stderr ``store corrupted``(不靜默重建).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from taskq.core.models import Task, TaskStatus

_STORE_FILENAME = "tasks.json"


class StoreCorrupted(Exception):
    """Raised when tasks.json exists but is not valid JSON.

    [FR-01] Citations: SPEC.md §3 FR-01 通過驗證 bullet 5.
    """


def save_tasks_atomic(path: Path, tasks: dict[str, Task]) -> None:
    """Serialize ``tasks`` to ``path/tasks.json`` atomically.

    Writes to a sibling tempfile first, then ``os.replace``s it onto the
    target — readers either observe the previous payload or the new one,
    never a partial write.

    [FR-01] Citations: SPEC.md §3 FR-01 通過驗證 bullet 4 (NFR-03).
    """
    base = Path(path)
    base.mkdir(parents=True, exist_ok=True)
    target = base / _STORE_FILENAME

    payload = {
        tid: {
            "id": t.id,
            "command": t.command,
            "status": t.status.value,
            "created_at": t.created_at.isoformat(),
        }
        for tid, t in tasks.items()
    }

    fd, tmp_name = tempfile.mkstemp(
        dir=str(base), prefix=".tasks.", suffix=".json.tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def load_tasks(path: Path) -> dict[str, Task]:
    """Load tasks from ``path/tasks.json``.

    Missing file → empty dict. Invalid JSON → :class:`StoreCorrupted`
    (never a silent rebuild — SPEC.md §3 FR-01 通過驗證 bullet 5).

    [FR-01] Citations: SPEC.md §3 FR-01 通過驗證 bullets 4-5.
    """
    base = Path(path)
    target = base / _STORE_FILENAME

    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StoreCorrupted(
            f"tasks.json is not valid JSON: {exc.msg}"
        ) from exc

    if not isinstance(data, dict):
        raise StoreCorrupted("tasks.json root must be an object")

    result: dict[str, Task] = {}
    for tid, obj in data.items():
        if not isinstance(obj, dict):
            raise StoreCorrupted(f"task entry {tid!r} is not an object")
        result[tid] = Task(
            id=obj["id"],
            command=obj["command"],
            status=TaskStatus(obj["status"]),
            created_at=datetime.fromisoformat(obj["created_at"]),
        )
    return result