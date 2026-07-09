"""taskq.config — $TASKQ_HOME resolution + canonical data-file paths.

Citations:
- SPEC.md §5.1 line 138: `TASKQ_HOME` env var, default `.taskq`
- SPEC.md §5.2 line 147: `tasks.json` / `breaker.json` / `cache.json` layout
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_HOME = Path(".taskq")


def taskq_home() -> Path:
    """Resolve $TASKQ_HOME; fall back to ./taskq (SPEC §5.1 default)."""
    raw = os.environ.get("TASKQ_HOME")
    return Path(raw).expanduser() if raw else DEFAULT_HOME


def tasks_path() -> Path:
    """Canonical `$TASKQ_HOME/tasks.json` location (SPEC §5.2)."""
    return taskq_home() / "tasks.json"


def breaker_path() -> Path:
    """Canonical `$TASKQ_HOME/breaker.json` location (SPEC §5.2)."""
    return taskq_home() / "breaker.json"


def cache_path() -> Path:
    """Canonical `$TASKQ_HOME/cache.json` location (SPEC §5.2)."""
    return taskq_home() / "cache.json"