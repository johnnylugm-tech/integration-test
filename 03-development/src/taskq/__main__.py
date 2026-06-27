"""[FR-01] ``python -m taskq <args>`` entry point.

Citations:
  - 03-development/tests/test_fr01.py:54   _run_cli uses ``python -m taskq``
"""
from __future__ import annotations

import sys

from taskq.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
