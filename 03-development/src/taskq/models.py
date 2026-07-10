"""taskq.models — Task record dataclass.

[FR-01] Task and `new_pending` factory — the on-disk row shape written by
`taskq.cli.submit` (SPEC §3 FR-01 line 70: command, name, created_at, id).
Result-side fields below are scaffolded for the FR-02 executor (lines 81).

Citations:
- SPEC.md §3 FR-01 line 69: id = first 8 hex of `uuid4()`
- SPEC.md §3 FR-01 line 70: pending task records `command`, `name`, `created_at`, `id`
- SPEC.md §3 FR-02 line 79: state machine `pending → running → done | failed | timeout`
- SPEC.md §3 FR-02 line 81: result fields `exit_code`, `stdout_tail`, `stderr_tail`,
  `duration_ms`, `finished_at`
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


def new_task_id() -> str:
    """8-hex task id per SPEC §3 FR-01 line 69."""
    return uuid.uuid4().hex[:8]


def utc_now_iso() -> str:
    """UTC timestamp in ISO-8601 (no microseconds, `Z` suffix)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class Task:
    """Task record as persisted in `$TASKQ_HOME/tasks.json` (SPEC §5.2)."""

    id: str
    command: str
    status: str
    created_at: str
    name: Optional[str] = None
    # FR-02 result fields (None while pending/running):
    exit_code: Optional[int] = None
    stdout_tail: Optional[str] = None
    stderr_tail: Optional[str] = None
    duration_ms: Optional[int] = None
    finished_at: Optional[str] = None
    # Internal: attempt counter for FR-03 retry bookkeeping.
    attempts: int = 0
    last_error: Optional[str] = field(default=None)
    # [FR-04] cache-replay flag — True when run --cached served this task
    # from $TASKQ_HOME/cache.json (defaults False on live execution).
    cached: bool = False

    @classmethod
    def new_pending(cls, command: str, name: Optional[str]) -> "Task":
        """Create a new pending task with id + created_at pre-filled (FR-01)."""
        return cls(
            id=new_task_id(),
            command=command,
            name=name,
            status="pending",
            created_at=utc_now_iso(),
        )

    def to_dict(self) -> dict:
        """[FR-01] Serialise the Task to a plain dict for $TASKQ_HOME/tasks.json."""
        return asdict(self)

    @classmethod
    def from_dict(cls, record: dict) -> "Task":
        """Re-hydrate a `Task` from a persisted JSON record (FR-02 lookup)."""
        # `attempts` is internal — pre-GREEN records may not carry it; default 0.
        kwargs = {k: v for k, v in record.items() if k in cls.__dataclass_fields__}
        return cls(**kwargs)