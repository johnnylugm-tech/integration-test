"""[FR-01] python -m taskq entry.

Citations:
- 03-development/tests/test_fr01.py:65-75 (subprocess: `python -m taskq <argv>`)
"""
from __future__ import annotations

import sys

from taskq.cli import main

if __name__ == "__main__":
    sys.exit(main())
