"""[FR-01/FR-02] Atomic tasks.json store with thread-safe writes.

Citations:
  - SPEC.md §3 FR-01 (line 50-72) — 原子寫入 $TASKQ_HOME/tasks.json
  - SPEC.md §3 FR-02 (line 74-83) — 存儲寫入必須執行緒安全(共享 Lock)
  - SPEC.md §3 NFR-03 (line 125) — 進程中斷後檔案仍為合法 JSON
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

# Process-wide lock guarding every read-modify-write of tasks.json.
# FR-02 requires thread-safe writes when --all fans out across workers.
_lock = threading.Lock()

_HOME: Path | None = None


def home() -> Path:
    """Return TASKQ_HOME, memoised for the life of the process."""
    global _HOME
    if _HOME is None:
        _HOME = Path(os.environ["TASKQ_HOME"])
    return _HOME


def tasks_path() -> Path:
    """[FR-01] Path to $TASKQ_HOME/tasks.json."""
    return home() / "tasks.json"


def load_tasks() -> dict[str, dict[str, object]]:
    """[FR-01] Return the tasks dict, or {} if the file is absent.

    Citations: SPEC.md §3 FR-01.
    """
    p = tasks_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def save_tasks(tasks: dict[str, dict[str, object]]) -> None:
    """[FR-01] Atomically replace tasks.json under the shared Lock.

    Citations: SPEC.md §3 FR-01 (原子寫入).
    """
    h = home()
    h.mkdir(parents=True, exist_ok=True)
    p = tasks_path()
    tmp = p.with_suffix(".json.tmp")
    with _lock:
        tmp.write_text(json.dumps(tasks))
        os.replace(tmp, p)


def update_task(task_id: str, **fields: object) -> None:
    """[FR-02] Atomically merge fields into one task entry.

    The full read-modify-write sequence is performed under the shared
    Lock so concurrent worker threads cannot tear the file or lose
    updates.

    Citations: SPEC.md §3 FR-02 — 存儲寫入必須執行緒安全(共享 Lock).
    """
    h = home()
    h.mkdir(parents=True, exist_ok=True)
    p = tasks_path()
    tmp = p.with_suffix(".json.tmp")
    with _lock:
        tasks: dict[str, dict[str, object]] = {}
        if p.exists():
            tasks = json.loads(p.read_text())
        if task_id in tasks:
            tasks[task_id].update(fields)
            tmp.write_text(json.dumps(tasks))
            os.replace(tmp, p)
