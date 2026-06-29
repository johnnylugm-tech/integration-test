"""Domain model for the taskq command-queue runtime.

[FR-01] Citations:
- SPEC.md §3 FR-01 通過驗證 (id format, status, fields).
- SPEC.md §3 FR-01 驗證規則 row 3 (injection char blacklist, NFR-02).
- SAD §3.2 (Task record shape on the submit path).
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
    """

    PENDING = "pending"


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