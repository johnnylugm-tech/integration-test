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
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from taskq.core.models import Task, TaskStatus, utcnow_iso


TASKS_FILENAME = "tasks.json"


class Store:
    """Atomic, file-backed task store rooted at $TASKQ_HOME.

    [FR-01/02, NFR-03, NFR-05]
    Citations: SAD.md line 82.
    """

    def __init__(self, home: Path) -> None:
        self.home = Path(home)
        self.tasks_path = self.home / TASKS_FILENAME

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

    def _atomic_write(self, data: dict[str, dict]) -> None:
        """Write tasks.json atomically via temp file + os.replace (NFR-03).

        [FR-01, NFR-03]
        Citations: SPEC.md line 73 (atomic write),
                   SAD.md line 82 (atomic write + Lock).
        """
        self.home.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".tasks-", suffix=".json.tmp", dir=str(self.home)
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.tasks_path)  # atomic rename (NFR-03)
        except BaseException:
            # On any failure, remove the temp file; the destination is untouched.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise