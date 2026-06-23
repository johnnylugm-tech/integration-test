"""taskq domain data classes — Task, TaskStatus, BreakerState, BreakerRecord, CacheEntry.

[FR-01] [FR-02] [FR-03] [FR-04] [FR-05]
Pure data carriers with no business logic or import-time side effects.
models.py is exempt from the per-function-body hub-call rule (SAD §2.1 note).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TaskStatus(str, Enum):
    """Lifecycle states for a taskq task.

    [FR-02] State machine: pending → running → done | failed | timeout
    """

    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    timeout = "timeout"


class BreakerState(str, Enum):
    """Circuit breaker FSM states.

    [FR-03] CLOSED → OPEN → HALF_OPEN → CLOSED
    """

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class Task:
    """A taskq task record.

    [FR-01] [FR-02] Fields: id, command, name, status, created_at,
    plus optional result fields populated after execution.
    """

    id: str
    command: str
    name: Optional[str]
    status: TaskStatus
    created_at: str
    exit_code: Optional[int] = None
    stdout_tail: Optional[str] = None
    stderr_tail: Optional[str] = None
    duration_ms: Optional[float] = None
    finished_at: Optional[str] = None
    cached: bool = False


@dataclass
class BreakerRecord:
    """Persisted circuit breaker state.

    [FR-03] Holds FSM state, consecutive failure counter, and open timestamp.
    """

    state: BreakerState = BreakerState.CLOSED
    consecutive_failures: int = 0
    opened_at: Optional[float] = None


@dataclass
class CacheEntry:
    """A TTL cache entry keyed by sha256(command).

    [FR-04] Stores the cached result fields and the timestamp of caching.
    """

    exit_code: int
    stdout_tail: str
    stderr_tail: str
    cached_at: float
