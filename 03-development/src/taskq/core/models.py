"""Domain model for the taskq command-queue runtime.

[FR-01] Citations:
- SPEC.md §3 FR-01 通過驗證 (id format, status, fields).
- SPEC.md §3 FR-01 驗證規則 row 3 (injection char blacklist, NFR-02).
- SAD §3.2 (Task record shape on the submit path).

[FR-02] Citations:
- SPEC.md §3 FR-02 狀態機 — pending → running → done | failed | timeout.
- SPEC.md §3 FR-02 結果欄位 — exit_code, stdout_tail, stderr_tail,
  duration_ms, finished_at.
- SAD §3.3 (TaskResult shape returned from runner.run_task).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


# SPEC.md §3 FR-01 驗證規則 row 3 / NFR-02 — shell metacharacter blacklist.
# Verbatim from spec: ; | & $ > < `
INJECTION_FORBIDDEN: set[str] = {";", "|", "&", "$", ">", "<", "`"}


class TaskStatus(str, Enum):
    """Lifecycle status of a Task.

    [FR-01] Citations: SPEC.md §3 FR-01 通過驗證 — 狀態 `pending`.
    [FR-02] Citations: SPEC.md §3 FR-02 狀態機 — `done` / `failed` / `timeout`.
    """

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class Task:
    """A queued command.

    [FR-01] Citations:
    - SPEC.md §3 FR-01 通過驗證 bullet 1 — id(uuid4 前 8 hex), status pending.
    - SPEC.md §3 FR-01 通過驗證 bullet 3 — records command + created_at.
    """

    id: str
    command: str
    status: TaskStatus
    created_at: datetime


@dataclass(frozen=True)
class TaskResult:
    """The terminal result of a runner.run_task invocation.

    [FR-02] Citations:
    - SPEC.md §3 FR-02 結果欄位 (exit_code, stdout_tail, stderr_tail,
      duration_ms, finished_at).
    - SPEC.md §3 FR-02 狀態機 — ``status`` ∈ {done, failed, timeout}.
    """

    status: TaskStatus
    exit_code: int
    stdout_tail: str
    stderr_tail: str
    duration_ms: int
    finished_at: datetime
