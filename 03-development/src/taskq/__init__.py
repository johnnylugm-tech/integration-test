"""taskq — local task-queue CLI.

[FR-01] Module re-exports for direct unit tests (so coverage picks up
the package surface without going through `python -m taskq`).
"""

from __future__ import annotations

from taskq.config import taskq_home, tasks_json_path
from taskq.store import (
    EXIT_CORRUPT,
    StoreCorruptedError,
    append_task,
    atomic_write_tasks,
    load_tasks_or_die,
)
from taskq.validation import (
    COMMAND_MAX_LENGTH,
    INJECTION_CHARS,
    validate_command,
)

__all__ = [
    "COMMAND_MAX_LENGTH",
    "EXIT_CORRUPT",
    "INJECTION_CHARS",
    "StoreCorruptedError",
    "append_task",
    "atomic_write_tasks",
    "load_tasks_or_die",
    "taskq_home",
    "tasks_json_path",
    "validate_command",
]
