"""[FR-01]

Atomic JSON persistence for `tasks.json`.

Citations:
- SPEC.md §3 FR-01 (`tasks.json` 損壞 → 啟動偵測 → exit 1 + stderr `store corrupted`, 不靜默重建).
- SPEC.md §4 NFR-03 (atomic write — tmp + `os.replace`).
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import List, Dict, Any

from taskq.config import tasks_file


class CorruptStoreError(Exception):
    """Raised when `tasks.json` exists but is not valid JSON.

    Citations:
        - SPEC.md §3 FR-01 corruption-detection clause.
    """


def load_tasks() -> List[Dict[str, Any]]:
    """Return the on-disk task list.

    Citations:
        - SPEC.md §3 FR-01 (起動偵測; no silent rebuild).

    Raises:
        CorruptStoreError: `tasks.json` exists but is not valid JSON.
    """
    path = tasks_file()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise CorruptStoreError(str(exc)) from exc
    if not isinstance(payload, dict) or "tasks" not in payload:
        return []
    tasks = payload["tasks"]
    return tasks if isinstance(tasks, list) else []


def save_tasks(tasks: List[Dict[str, Any]]) -> None:
    """Atomically persist `tasks` to `$TASKQ_HOME/tasks.json`.

    Citations:
        - SPEC.md §3 FR-01 (原子寫入 — tmp + os.replace).
        - SPEC.md §4 NFR-03 (進程中斷後仍為合法 JSON).

    Method:
        write to a same-directory tmp file, fsync, then `os.replace` so a
        crash mid-write leaves the previous valid file untouched.
    """
    path = tasks_file()
    payload = {"tasks": list(tasks)}
    data = json.dumps(payload, ensure_ascii=False, indent=2)

    # NamedTemporaryFile on the same filesystem guarantees os.replace is atomic.
    fd, tmp_name = tempfile.mkstemp(
        prefix=".tasks.", suffix=".json.tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup of the orphan tmp; never let it shadow the real file.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
