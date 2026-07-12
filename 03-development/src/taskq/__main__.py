"""python -m taskq entry point.

[FR-05, NFR-05]
Citations: SAD.md line 58 (python -m taskq boot → cli.main).
"""
from __future__ import annotations

import sys

from taskq.interface.cli import main


if __name__ == "__main__":
    sys.exit(main())