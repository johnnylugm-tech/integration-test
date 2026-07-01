"""[FR-01] [FR-02]

Domain primitives: the persisted `Task` record, the in-memory
`SubmitResult` returned to API callers, and the `RunResult` from
the executor.

Citations:
- SPEC.md §3 FR-01 (uuid4 first 8 hex, status=pending, command, created_at).
- SPEC.md §3 FR-02 (RunResult fields: exit_code, stdout_tail, stderr_tail,
  duration_ms, finished_at).
- tests/test_fr01.py module docstring (SubmitResult field contract).
- tests/test_fr02.py module docstring (RunResult field contract — GREEN).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict


@dataclass
class SubmitResult:
    """Return value of `taskq.cli.cli.submit()`.

    Citations:
        - tests/test_fr01.py (GREEN contract).
        - SPEC.md §3 FR-01 (exit-code mapping: 0=ok, 2=validation reject, 1=corruption).
    """

    exit_code: int
    stderr: str = ""
    id: str = ""
    command: str = ""
    status: str = ""
    attempts: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Task:
    """Persisted task record shape.

    Citations:
        - SPEC.md §3 FR-01 (id = uuid4 first 8 hex; status=pending;
          fields {command, created_at}).
    """

    id: str
    command: str
    status: str
    created_at: str

    @staticmethod
    def new(id_: str, command: str) -> "Task":
        """Build a fresh pending task; created_at stamps UTC ISO 8601 with `Z` suffix."""
        return Task(
            id=id_,
            command=command,
            status="pending",
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "command": self.command,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass
class RunResult:
    """[FR-02] Return value of `taskq.executor.run_task()`.

    Citations:
        - SPEC.md §3 FR-02 (result fields: exit_code, stdout_tail,
          stderr_tail, duration_ms, finished_at).
        - tests/test_fr02.py (GREEN contract — RunResult field set).
    """

    exit_code: int
    status: str
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_ms: int = 0
    finished_at: str = ""
    attempts: int = 1
