"""[FR-01][FR-03] taskq configuration loader.

Citations:
- 03-development/tests/test_fr01.py:21 (load_config → Config contract)
- 03-development/tests/test_fr03.py:20 (task_timeout + retry_limit contract)
- 03-development/tests/test_fr03.py:626-663 (defaults: TASKQ_HOME=.taskq,
  TASKQ_TASK_TIMEOUT=10, TASKQ_RETRY_LIMIT=2)
- SRS.md:1-22 (TASKQ_HOME 環境變數驅動 $TASKQ_HOME/tasks.json)
- SRS.md:103 (TASKQ_TASK_TIMEOUT / TASKQ_RETRY_LIMIT 環境變數)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    """Resolved configuration.

    Citations:
    - 03-development/tests/test_fr01.py:21 (load_config → Config)
    - 03-development/tests/test_fr03.py:20 (task_timeout + retry_limit fields)
    """

    home: Path
    task_timeout: float = 10.0
    retry_limit: int = 2


def load_config() -> Config:
    """Load config from $TASKQ_HOME (default `.taskq`),
    $TASKQ_TASK_TIMEOUT (default 10.0), $TASKQ_RETRY_LIMIT (default 2).

    Citations:
    - 03-development/tests/test_fr01.py:21 (load_config contract)
    - 03-development/tests/test_fr03.py:626-663 (defaults)
    - SRS.md:1-22 (TASKQ_HOME 環境變數)
    """
    raw_home = os.environ.get("TASKQ_HOME")
    home = Path(raw_home) if raw_home else Path(".taskq")
    timeout = float(os.environ.get("TASKQ_TASK_TIMEOUT", "10.0"))
    retry = int(os.environ.get("TASKQ_RETRY_LIMIT", "2"))
    return Config(home=home, task_timeout=timeout, retry_limit=retry)
