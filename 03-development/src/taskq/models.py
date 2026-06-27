"""[FR-01] Domain models: task id generation and record shape.

Citations:
  - 03-development/tests/test_fr01.py:165  new_task_id() returns 8 lowercase hex
  - 03-development/tests/test_fr01.py:198  new_record() shape: status/command/created_at
  - 03-development/tests/test_fr01.py:209  created_at must be ISO-8601 with tzinfo
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def new_task_id() -> str:
    """Return the first 8 hex chars of a fresh uuid4 (lowercase)."""
    return uuid.uuid4().hex[:8]


def new_record(command: str) -> dict:
    """Return a fresh task record: status=pending, command, created_at (UTC)."""
    return {
        "status": "pending",
        "command": command,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
