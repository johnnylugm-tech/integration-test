"""Configuration helpers — TASKQ_HOME environment.

[FR-01] Citations:
- SPEC.md §3 FR-01 ("$TASKQ_HOME/tasks.json"): `taskq_home`, `tasks_json_path`.
- SPEC.md §5 (`TASKQ_HOME` default `.taskq`): `taskq_home`.
"""

from __future__ import annotations

import os
from pathlib import Path


def taskq_home() -> Path:
    """Return the TASKQ_HOME directory, defaulting to ~/.taskq.

    [FR-01] SPEC.md §3 FR-01 ("$TASKQ_HOME/tasks.json").
    [FR-01] SPEC.md §5 (env var TASKQ_HOME default `.taskq`).
    """
    raw = os.environ.get("TASKQ_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".taskq"


def tasks_json_path() -> Path:
    """Return the canonical tasks.json path under TASKQ_HOME.

    [FR-01] SPEC.md §3 FR-01 ("$TASKQ_HOME/tasks.json").
    """
    return taskq_home() / "tasks.json"
