"""Core data models for taskq.

[FR-01..04, NFR-05]
Citations: SPEC.md line 57 (FR-01 task shape),
           SAD.md line 160 (Task dataclass signature),
           SAD.md line 162 (TaskStatus enum values),
           TEST_SPEC.md line 61-70 (FR01 sub-assertions).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class TaskStatus(str, Enum):
    """Lifecycle states of a task.

    [FR-01..02, NFR-05]
    Citations: SAD.md line 162.
    """
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class Task:
    """A submitted task record persisted in $TASKQ_HOME/tasks.json.

    [FR-01, NFR-05]
    Citations: SPEC.md line 73 (FR-01 record fields),
               SAD.md line 160 (Task dataclass).
    """
    id: str
    command: str
    status: TaskStatus
    created_at: str
    name: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize for JSON storage.

        [FR-01, NFR-05]
        Citations: SAD.md line 264 (Task JSON shape).
        """
        d: dict = {
            "id": self.id,
            "command": self.command,
            "status": self.status.value,
            "created_at": self.created_at,
        }
        if self.name is not None:
            d["name"] = self.name
        return d


def utcnow_iso() -> str:
    """Return current UTC time in ISO 8601 format.

    [FR-01, NFR-05]
    Citations: SPEC.md line 73 (created_at ISO timestamp).
    """
    return datetime.utcnow().isoformat()