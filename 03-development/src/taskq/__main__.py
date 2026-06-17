"""[FR-01] python -m taskq entry.

Citations:
- 03-development/tests/test_fr01.py:65-75 (subprocess: `python -m taskq <argv>`)
"""
from __future__ import annotations  # pragma: no cover

import sys  # pragma: no cover

from taskq.cli import main  # pragma: no cover

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())  # pragma: no cover
