"""Configuration helpers — TASKQ_* environment readers.

[FR-01] Citations:
- SPEC.md §3 FR-01 ("$TASKQ_HOME/tasks.json"): `taskq_home`, `tasks_json_path`.
- SPEC.md §5 (`TASKQ_HOME` default `.taskq`): `taskq_home`.

[FR-02] Citations:
- SPEC.md §3 FR-02 ("subprocess.run(..., timeout=TASKQ_TASK_TIMEOUT)"):
  `task_timeout`.
- SPEC.md §3 FR-02 ("上限 TASKQ_RETRY_LIMIT 次(預設 2)"): `retry_limit`.
- SPEC.md §5: env-var defaults applied here.
"""

from __future__ import annotations

import os
from pathlib import Path


# [FR-02] SPEC.md §5: TASKQ_TASK_TIMEOUT default `10.0`.
_DEFAULT_TASK_TIMEOUT = 10.0

# [FR-02] SPEC.md §5: TASKQ_RETRY_LIMIT default `2`.
_DEFAULT_RETRY_LIMIT = 2


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


def task_timeout() -> float:
    """Return TASKQ_TASK_TIMEOUT (per-attempt subprocess timeout, seconds).

    [FR-02] SPEC.md §3 FR-02 ("subprocess.run(..., timeout=TASKQ_TASK_TIMEOUT)").
    [FR-02] SPEC.md §5 (default 10.0).
    """
    raw = os.environ.get("TASKQ_TASK_TIMEOUT")
    if raw is None or raw == "":
        return _DEFAULT_TASK_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_TASK_TIMEOUT


def retry_limit() -> int:
    """Return TASKQ_RETRY_LIMIT (max retries on failed/timeout; default 2).

    [FR-02] SPEC.md §3 FR-02 ("上限 TASKQ_RETRY_LIMIT 次(預設 2)").
    [FR-02] SPEC.md §5 (default 2).

    Per SAD §2.3 / D-02: TASKQ_RETRY_LIMIT retries on top of the initial
    execution → `attempts` may reach `TASKQ_RETRY_LIMIT + 1`.
    """
    raw = os.environ.get("TASKQ_RETRY_LIMIT")
    if raw is None or raw == "":
        return _DEFAULT_RETRY_LIMIT
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_RETRY_LIMIT
