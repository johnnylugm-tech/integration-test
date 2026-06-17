"""[FR-01] Persistence layer: atomic write + corruption detection.

Citations:
- 03-development/tests/test_fr01.py:9-15 (load_store/get_task/clear_store contract)
- SRS.md:1-22 (原子寫入:tmp + os.replace;tasks.json 損壞 → 不得靜默重建)
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from taskq.config import load_config
from taskq.store.ids import generate_task_id
from taskq.store.models import StoreCorrupted, Task
from taskq.store.validation import validate_command

TASKS_FILENAME = "tasks.json"


def _store_path() -> Path:
    cfg = load_config()
    return cfg.home / TASKS_FILENAME


def _load_raw() -> dict[str, dict]:
    """Read + JSON-parse tasks.json. Raise StoreCorrupted on parse failure.

    Citations:
    - 03-development/tests/test_fr01.py:188-194 (corrupt content → 必須 raise,不得重建)
    """
    path = _store_path()
    if not path.exists():
        return {}
    text = path.read_text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StoreCorrupted(f"tasks.json is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise StoreCorrupted("tasks.json root must be a JSON object")
    return data


def _atomic_write(data: dict[str, dict]) -> None:
    """Atomically write data to tasks.json via tmp + os.replace.

    Citations:
    - 03-development/tests/test_fr01.py:238-240 (no leftover .tmp after success)
    - SRS.md:1-22 (原子寫入)
    """
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{TASKS_FILENAME}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        # Clean up tmp on failure to honor "no leftover .tmp" invariant.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_store() -> dict[str, Task]:
    """Load all tasks as {id: Task}. Raise StoreCorrupted on invalid JSON.

    Citations:
    - 03-development/tests/test_fr01.py:9 (load_store contract)
    - 03-development/tests/test_fr01.py:215-221 (8 distinct ids round-trip)
    """
    raw = _load_raw()
    return {tid: Task.from_dict(rec) for tid, rec in raw.items()}


def get_task(task_id: str) -> Optional[Task]:
    """Return Task for task_id, or None if absent.

    Citations:
    - 03-development/tests/test_fr01.py:10 (get_task contract)
    - 03-development/tests/test_fr01.py:175-180 (initial pending state)
    """
    raw = _load_raw()
    rec = raw.get(task_id)
    return Task.from_dict(rec) if rec is not None else None


def submit_task(command: str) -> str:
    """Validate + persist a new task, return the generated id.

    Citations:
    - 03-development/tests/test_fr01.py:8 (submit_task contract)
    - 03-development/tests/test_fr01.py:175-180 (status=pending round-trip)
    - SRS.md:1-22 (原子寫入,id 8 hex)
    """
    validate_command(command)

    # 為了降低碰撞機率,即使本測試只用 in-process 也保持重試。
    raw = _load_raw()
    for _ in range(16):
        tid = generate_task_id()
        if tid not in raw:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not generate unique task id")

    raw[tid] = Task(command=command).to_dict()
    _atomic_write(raw)
    return tid


def clear_store() -> None:
    """Reset the store to empty.

    Citations:
    - 03-development/tests/test_fr01.py:10 (clear_store contract)
    - 03-development/tests/test_fr01.py:9 (原子寫入一致)
    """
    _atomic_write({})


__all__ = [
    "load_store",
    "get_task",
    "submit_task",
    "clear_store",
    "StoreCorrupted",
    "Task",
]
