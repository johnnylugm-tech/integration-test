"""Persistent storage layer for tasks.

[FR-01/02, NFR-03/08/09/10]
Citations: SPEC.md line 73 (atomic write of tasks.json),
           SAD.md line 82 (Store.submit / atomic write + Lock + flock),
           SAD.md line 167 (Store.submit signature),
           SAD.md line 264 (tasks.json shape),
           TEST_SPEC.md line 61-70 (FR01 sub-assertions).
"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Iterator, Optional

from taskq.core.models import Task, TaskStatus, utcnow_iso
from taskq.storage._atomic import atomic_write_json


TASKS_FILENAME = "tasks.json"


class Store:
    """Atomic, file-backed task store rooted at $TASKQ_HOME.

    [FR-01/02, NFR-03, NFR-05]
    Citations: SAD.md line 82.
    """

    def __init__(self, home: Path) -> None:
        self.home = Path(home)
        self.tasks_path = self.home / TASKS_FILENAME
        # FR-02 run --all: serialize concurrent load-modify-write cycles so
        # parallel worker threads never lose each other's updates (NFR-03).
        self._lock = threading.Lock()

    def load(self) -> dict[str, dict]:
        """Load the tasks dict from disk. Returns {} if file missing or empty.

        [FR-01, NFR-03]
        Citations: SAD.md line 264.
        """
        if not self.tasks_path.exists():
            return {}
        try:
            text = self.tasks_path.read_text()
        except OSError:
            return {}
        if not text.strip():
            return {}
        data = json.loads(text)
        if not isinstance(data, dict):
            return {}
        return data

    def submit(self, command: str, name: Optional[str] = None) -> Task:
        """Create a new task and persist it atomically.

        [FR-01, NFR-03]
        Citations: SPEC.md line 73 (8-hex id, pending status, atomic write),
                   SAD.md line 167 (Store.submit signature).
        """
        task_id = uuid.uuid4().hex[:8]
        task = Task(
            id=task_id,
            command=command,
            status=TaskStatus.PENDING,
            created_at=utcnow_iso(),
            name=name,
        )
        data = self.load()
        data[task_id] = task.to_dict()
        self._atomic_write(data)
        return task

    def get(self, task_id: str) -> Optional[dict]:
        """Return the stored task record for task_id, or None if absent.

        [FR-02, FR-05]
        Citations: SAD.md line 168 (Store.get for status lookup),
                   SPEC.md line 106 (status <id> reads full task fields).
        """
        return self.load().get(task_id)

    def list(self, status: Optional[str] = None) -> Iterator[dict]:
        """Yield task records, optionally filtered by status string.

        [FR-02, FR-05]
        Citations: SAD.md line 169 (Store.list streaming iterator),
                   SPEC.md line 106 (list [--status S]).
        """
        for task in self.load().values():
            if status is None or task.get("status") == status:
                yield task

    def update_status(self, task_id: str, **fields) -> None:
        """Merge fields into a task record and persist atomically (thread-safe).

        [FR-02, NFR-03]
        Citations: SPEC.md line 88 (executor writes result fields back),
                   SAD.md line 170 (Store.update_status signature),
                   SAD.md line 82 (atomic write + Lock).
        """
        with self._lock:
            data = self.load()
            if task_id not in data:
                raise KeyError(task_id)
            data[task_id].update(fields)
            self._atomic_write(data)

    def _atomic_write(self, data: dict[str, dict]) -> None:
        """Write tasks.json atomically via the shared helper (NFR-03).

        [FR-01, NFR-03]
        Citations: SPEC.md line 73 (atomic write),
                   SAD.md line 82 (atomic write + Lock).
        """
        atomic_write_json(self.home, TASKS_FILENAME, data, tmp_prefix=".tasks-")