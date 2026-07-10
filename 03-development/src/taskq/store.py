"""taskq store — atomic tasks.json with thread-safe Lock (NFR-03).

[FR-02] Citations: SPEC.md §3 FR-02 (concurrent --all writes must be
thread-safe); NFR-03 (atomic write: tmp + os.replace, crash leaves valid JSON);
§5.2 data file ``tasks.json``.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

_TASKS_FILE = "tasks.json"


def _store_path() -> Path:
    """Return the path to ``tasks.json`` inside ``$TASKQ_HOME``.

    Falls back to ``.taskq`` when the env var is unset so the module is
    importable outside the CLI test harness; production usage always
    sets ``TASKQ_HOME``.
    """
    home = Path(os.environ.get("TASKQ_HOME", ".taskq"))
    return home / _TASKS_FILE


class TaskStore:
    """Thread-safe JSON store for ``tasks.json`` (SPEC §5.2, NFR-03).

    All read-modify-write operations take ``self._lock`` so concurrent
    callers (FR-02 ``run --all`` worker pool) cannot interleave a stale
    read with a write and corrupt the file. Writes are atomic (tmp +
    ``os.replace``); an interrupted process leaves either the old file
    or the new file, never a half-written one.
    """

    def __init__(self) -> None:
        # NFR-03 contract: every TaskStore instance exposes a
        # ``threading.Lock`` for serialising concurrent writers.
        self._lock = threading.Lock()

    # ----- public API --------------------------------------------------

    def load_tasks(self) -> list[dict[str, Any]]:
        """Load the task list under the store lock.

        Returns ``[]`` when the file is absent (first-run / cleared).
        """
        with self._lock:
            return self._load_unsafe()

    def save_tasks(self, tasks: list[dict[str, Any]]) -> None:
        """Atomically replace the task list under the store lock."""
        with self._lock:
            self._save_unsafe(tasks)

    def update_task(
        self, task_id: str, **fields: Any
    ) -> Optional[dict[str, Any]]:
        """Update fields of a single task under the store lock.

        Returns the updated task dict, or ``None`` when no task with
        ``task_id`` exists. Read-modify-write is performed inside the
        lock so concurrent updaters cannot lose each other's changes.
        """
        with self._lock:
            tasks = self._load_unsafe()
            updated: Optional[dict[str, Any]] = None
            for task in tasks:
                if task.get("id") == task_id:
                    task.update(fields)
                    updated = task
                    break
            if updated is not None:
                self._save_unsafe(tasks)
            return updated

    # ----- unsafe helpers (caller MUST hold ``self._lock``) ------------

    def _load_unsafe(self) -> list[dict[str, Any]]:
        path = _store_path()
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def _save_unsafe(self, tasks: list[dict[str, Any]]) -> None:
        path = _store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(tasks, fh, ensure_ascii=False)
        os.replace(tmp, path)