"""[FR-01]

Centralised `TASKQ_*` environment-variable reader.

Citations:
- SPEC.md §5 — `TASKQ_HOME` (default `.taskq`); single source of truth for env vars.
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
