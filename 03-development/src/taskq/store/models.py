"""[FR-01] Data models for the task store.

Citations:
- 03-development/tests/test_fr01.py:14-15 (Task / StoreCorrupted contract)
- SRS.md:1-22 (status=pending、command、created_at 欄位)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Task:
    """Persistent task record.

    Citations:
    - 03-development/tests/test_fr01.py:175-180 (status=pending、command round-trip)
    """

    command: str
    status: str = "pending"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(
            command=data["command"],
            status=data.get("status", "pending"),
            created_at=data.get(
                "created_at", datetime.now(timezone.utc).isoformat()
            ),
        )


class StoreCorrupted(Exception):
    """Raised when tasks.json cannot be parsed as JSON.

    Citations:
    - 03-development/tests/test_fr01.py:15 (StoreCorrupted contract)
    - SRS.md:1-22 (損壞偵測 → exit 1、不得靜默重建)
    """
