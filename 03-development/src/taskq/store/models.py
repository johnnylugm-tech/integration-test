"""[FR-01][FR-02] Data models for the task store.

Citations:
- 03-development/tests/test_fr01.py:14-15 (Task / StoreCorrupted contract)
- 03-development/tests/test_fr01.py:175-180 (status=pending、command round-trip)
- 03-development/tests/test_fr02.py:222-233 (exit_code / status after run)
- 03-development/tests/test_fr02.py:325-347 (stdout_tail / stderr_tail)
- 03-development/tests/test_fr02.py:355-364 (duration_ms / finished_at)
- SRS.md:1-22 (FR-01 status=pending、command、created_at 欄位)
- SRS.md:61-80 (FR-02 result fields: exit_code / tails / duration_ms / finished_at)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Task:
    """Persistent task record.

    Citations:
    - 03-development/tests/test_fr01.py:175-180 (status=pending、command round-trip)
    - 03-development/tests/test_fr02.py:222-233 (exit_code, status after run)
    - 03-development/tests/test_fr02.py:325-364 (stdout_tail, stderr_tail, duration_ms, finished_at)
    """

    command: str
    status: str = "pending"
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    exit_code: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "status": self.status,
            "created_at": self.created_at,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        return cls(
            command=data["command"],
            status=data.get("status", "pending"),
            created_at=data.get(
                "created_at", datetime.now(UTC).isoformat()
            ),
            exit_code=data.get("exit_code"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            duration_ms=data.get("duration_ms"),
            stdout_tail=data.get("stdout_tail", ""),
            stderr_tail=data.get("stderr_tail", ""),
        )


class StoreCorrupted(Exception):
    """Raised when tasks.json cannot be parsed as JSON.

    Citations:
    - 03-development/tests/test_fr01.py:15 (StoreCorrupted contract)
    - SRS.md:1-22 (損壞偵測 → exit 1、不得靜默重建)
    """
