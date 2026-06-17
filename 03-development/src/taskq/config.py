"""[FR-01] taskq configuration loader.

Citations:
- 03-development/tests/test_fr01.py:21 (load_config → Config contract)
- SRS.md:1-22 (TASKQ_HOME 環境變數驅動 $TASKQ_HOME/tasks.json)
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
    """

    home: Path


def load_config() -> Config:
    """Load config from $TASKQ_HOME (default ~/.taskq).

    Citations:
    - 03-development/tests/test_fr01.py:21 (load_config contract)
    - SRS.md:1-22 (TASKQ_HOME 環境變數)
    """
    home = Path(os.environ.get("TASKQ_HOME", str(Path.home() / ".taskq")))
    return Config(home=home)
