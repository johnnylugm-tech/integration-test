"""Task data model — in-memory representation of one task record.

[FR-01] Citations:
- SPEC.md §3 FR-01 ("產生 task id (uuid4 前 8 hex)"): `make_task_id`.
- SPEC.md §3 FR-01 ("狀態 pending,記錄 command、created_at"): pending defaults.

[FR-02] Citations:
- SPEC.md §3 FR-02 status enum: pending | running | done | failed | timeout.
- SPEC.md §3 FR-02 result fields: exit_code, stdout_tail, stderr_tail,
  duration_ms, finished_at.
- SAD.md §2.3 Task dataclass field set (id, command, status, created_at,
  attempts, exit_code, stdout_tail, stderr_tail, duration_ms, finished_at).

Tasks are persisted as plain dicts (JSON-serializable) by `taskq.store`. This
module's `Task` dataclass is a typed view; `to_dict` and `from_dict` convert
between the two representations so the rest of the package can pass typed
objects while the store stays JSON-native.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


# [FR-01] SPEC.md §3 FR-01 ("產生 task id (uuid4 前 8 hex)").
ID_HEX_LEN = 8


# [FR-02] SPEC.md §3 FR-02 status enum.
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_TIMEOUT = "timeout"

VALID_STATUSES = frozenset(
    {STATUS_PENDING, STATUS_RUNNING, STATUS_DONE, STATUS_FAILED, STATUS_TIMEOUT}
)


def make_task_id() -> str:
    """Return the first 8 lowercase hex chars of a uuid4.

    [FR-01] SPEC.md §3 FR-01 ("產生 task id (uuid4 前 8 hex)").
    """
    return uuid.uuid4().hex[:ID_HEX_LEN]


def now_iso() -> str:
    """Return current UTC time as ISO-8601 string with offset."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Task:
    """Typed view of a task record.

    [FR-01] [FR-02] SAD.md §2.3 Task fields.
    """

    id: str
    command: str
    status: str = STATUS_PENDING
    created_at: str = field(default_factory=now_iso)
    attempts: int = 0
    exit_code: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_ms: int | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict view of this task."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """Build a Task from a persisted dict (missing fields default)."""
        return cls(
            id=str(data.get("id", "")),
            command=str(data.get("command", "")),
            status=str(data.get("status", STATUS_PENDING)),
            created_at=str(data.get("created_at", now_iso())),
            attempts=int(data.get("attempts", 0)),
            exit_code=data.get("exit_code"),
            stdout_tail=str(data.get("stdout_tail", "")),
            stderr_tail=str(data.get("stderr_tail", "")),
            duration_ms=data.get("duration_ms"),
            finished_at=data.get("finished_at"),
        )