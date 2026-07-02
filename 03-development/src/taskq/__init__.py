"""taskq — local task-queue CLI.

[FR-01] Module re-exports for direct unit tests (so coverage picks up
the package surface without going through `python -m taskq`).
"""

from __future__ import annotations

from taskq.config import (
    retry_limit,
    task_timeout,
    taskq_home,
    tasks_json_path,
)
from taskq.executor import (
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_REJECTED,
    EXIT_TIMEOUT,
    UnknownTaskError,
    run_task,
)
from taskq.models import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_TIMEOUT,
    VALID_STATUSES,
    Task,
    make_task_id,
    now_iso,
)
from taskq.redact import redact
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
    "EXIT_INTERNAL",
    "EXIT_OK",
    "EXIT_REJECTED",
    "EXIT_TIMEOUT",
    "INJECTION_CHARS",
    "STATUS_DONE",
    "STATUS_FAILED",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "STATUS_TIMEOUT",
    "StoreCorruptedError",
    "Task",
    "UnknownTaskError",
    "VALID_STATUSES",
    "append_task",
    "atomic_write_tasks",
    "load_tasks_or_die",
    "make_task_id",
    "now_iso",
    "redact",
    "retry_limit",
    "run_task",
    "task_timeout",
    "taskq_home",
    "tasks_json_path",
    "validate_command",
]