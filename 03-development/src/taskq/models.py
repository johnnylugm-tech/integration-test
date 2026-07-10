"""taskq models — Task dataclass and Status enum.

[FR-02] Citations: SPEC.md §3 FR-02 (state machine pending → running →
done | failed | timeout); §5 data file `tasks.json` (per-task record).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Status(str, Enum):
    """Task lifecycle status (SPEC.md §3 FR-02 state machine).

    String-valued so JSON serialisation round-trips without an extra
    converter and ``Status.PENDING.value == "pending"`` holds.
    """

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class Task:
    """A single taskq task record.

    Fields ``id`` / ``name`` / ``command`` / ``status`` / ``created_at``
    are populated at submission time (FR-01). The result fields
    (``exit_code`` / ``stdout_tail`` / ``stderr_tail`` / ``duration_ms``
    / ``finished_at``) are populated after execution (FR-02).
    """

    id: str
    name: Optional[str]
    command: str
    status: Status = Status.PENDING
    created_at: str = ""
    # Result fields — populated after run_task (SPEC §3 FR-02).
    exit_code: Optional[int] = None
    stdout_tail: Optional[str] = None
    stderr_tail: Optional[str] = None
    duration_ms: Optional[float] = None
    finished_at: Optional[str] = None