"""[FR-01] Path configuration for the taskq store.

Resolves ``$TASKQ_HOME/tasks.json``. Defaults to ``~/.taskq/tasks.json`` when
``TASKQ_HOME`` is unset.

Citations:
  - 03-development/tests/test_fr01.py:64  fixture tmp_home sets TASKQ_HOME
  - 03-development/tests/test_fr01.py:122  tasks.json read after submit
"""
from __future__ import annotations

import os

_TASKS_FILENAME = "tasks.json"


def home_dir() -> str:
    """Return the TASKQ_HOME directory (creating it is the caller's job)."""
    return os.environ.get("TASKQ_HOME", os.path.expanduser("~/.taskq"))


def tasks_path() -> str:
    """Return the absolute path to ``tasks.json`` under TASKQ_HOME."""
    return os.path.join(home_dir(), _TASKS_FILENAME)
