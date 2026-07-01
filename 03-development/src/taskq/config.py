"""[FR-01] [FR-02]

Centralised `TASKQ_*` environment-variable reader.

Citations:
- SPEC.md §5 — `TASKQ_HOME` (default `.taskq`); single source of truth for env vars.
- SPEC.md §3 FR-02 — `TASKQ_TASK_TIMEOUT` (default 10.0), `TASKQ_RETRY_LIMIT` (default 2).
"""

from __future__ import annotations

import os
from pathlib import Path

# Default lives next to process cwd, NOT $HOME, so the test sandbox (which
# overrides TASKQ_HOME explicitly) keeps working without surprise writes.
_DEFAULT_HOME = ".taskq"


def taskq_home() -> Path:
    """Return the directory holding `tasks.json`, creating it if missing.

    Citations:
        - SPEC.md §5 (TASKQ_HOME default `.taskq`).
    """
    raw = os.environ.get("TASKQ_HOME", _DEFAULT_HOME)
    home = Path(raw).expanduser()
    home.mkdir(parents=True, exist_ok=True)
    return home


def tasks_file() -> Path:
    """Return `$TASKQ_HOME/tasks.json`.

    Citations:
        - SPEC.md §3 FR-01 (atomic write target is `$TASKQ_HOME/tasks.json`).
    """
    return taskq_home() / "tasks.json"


def task_timeout() -> float:
    """Return `$TASKQ_TASK_TIMEOUT` as float, default 10.0.

    Citations:
        - SPEC.md §3 FR-02 (TASKQ_TASK_TIMEOUT default 10.0).
    """
    return float(os.environ.get("TASKQ_TASK_TIMEOUT", "10.0"))


def retry_limit() -> int:
    """Return `$TASKQ_RETRY_LIMIT` as int, default 2.

    Citations:
        - SPEC.md §3 FR-02 (TASKQ_RETRY_LIMIT default 2).
    """
    return int(os.environ.get("TASKQ_RETRY_LIMIT", "2"))
