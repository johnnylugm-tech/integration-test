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


@dataclass
class RunResult:
    """Outcome of executing a task's command (FR-02 result shape).

    [FR-02, NFR-05]
    Citations: SPEC.md line 88 (FR-02 result fields: exit_code, stdout_tail,
                   stderr_tail, duration_ms, finished_at + status machine),
               SAD.md line 161 (RunResult dataclass),
               TEST_SPEC.md line 77-101 (FR02 sub-assertions).
    """
    status: TaskStatus
    exit_code: Optional[int]
    stdout_tail: str
    stderr_tail: str
    duration_ms: float
    finished_at: str

    def to_fields(self) -> dict:
        """Return the result as a flat dict to merge into a task record.

        [FR-02, NFR-05]
        Citations: SPEC.md line 88 (persisted result fields),
                   SAD.md line 170 (Store.update_status(**fields)).
        """
        return {
            "status": self.status.value,
            "exit_code": self.exit_code,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "duration_ms": self.duration_ms,
            "finished_at": self.finished_at,
        }