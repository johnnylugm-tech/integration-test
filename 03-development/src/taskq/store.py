"""taskq.store — atomic `$TASKQ_HOME/tasks.json` load/save (NFR-03).

Citations:
- SPEC.md §3 FR-01 line 71: atomic write of `tasks.json`
- SPEC.md §5.2 line 151: `tasks.json` is `id → full record` map
- SAD: store.py line 166 — `threading.Lock` for concurrent writers
- SAD: store.py line 187 — corrupt JSON detected at boot → exit 1
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Iterable, Optional

from taskq import config
from taskq.models import Task

# Single in-process lock guarding all reads/writes (FR-02 --all needs it).
_LOCK = threading.Lock()


class StoreCorruptedError(RuntimeError):
    """Raised when tasks.json exists but is not valid JSON (SPEC §6 line 187)."""


def _ensure_home() -> Path:
    home = config.taskq_home()
    home.mkdir(parents=True, exist_ok=True)
    return home


def load_tasks(path: Optional[Path] = None) -> dict[str, dict]:
    """Load tasks.json as a `{id: record}` dict.

    Returns `{}` when the file is absent or empty. Raises `StoreCorruptedError`
    on non-empty but non-parseable content so the CLI can exit 1 with stderr
    `store corrupted` (SPEC §6 line 187).
    """
    target = path or config.tasks_path()
    if not target.exists():
        return {}
    raw = target.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StoreCorruptedError(str(exc)) from exc
    if not isinstance(parsed, dict):
        # SPEC §5.2 says `tasks.json` is `id → record` map; anything else
        # means the on-disk shape drifted (manual edit, crashed partial
        # write). Treat as corruption rather than silently re-initialising.
        raise StoreCorruptedError(f"tasks.json root must be object, got {type(parsed).__name__}")
    return parsed


def save_tasks(tasks: dict[str, dict], path: Optional[Path] = None) -> None:
    """Atomically persist `tasks` to tasks.json (tmp + `os.replace`)."""
    target = path or config.tasks_path()
    _ensure_home()
    # Atomic write: write to a sibling tmp file then os.replace for POSIX
    # atomicity (FR-01 line 71 + NFR-03 isolation).
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def add_task(task: Task) -> dict[str, dict]:
    """Append `task` under `_LOCK` and return the new full state."""
    with _LOCK:
        tasks = load_tasks()
        tasks[task.id] = task.to_dict()
        save_tasks(tasks)
        return tasks


def find_active_by_name(name: str) -> Optional[dict]:
    """Return the first pending/running task with matching name, else None.

    FR-01 rule 4 (line 66): `--name` collision only matters while the prior
    task is still pending/running — `done`/`failed`/`timeout` names are free.
    """
    if not name:
        return None
    with _LOCK:
        tasks = load_tasks()
    for record in tasks.values():
        if record.get("name") == name and record.get("status") in {"pending", "running"}:
            return record
    return None