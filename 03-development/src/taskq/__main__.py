"""[FR-01] ``python -m taskq <args>`` entry point.

Citations:
  - 03-development/tests/test_fr01.py:54   _run_cli uses ``python -m taskq``
"""
from __future__ import annotations  # pragma: no cover

import sys  # pragma: no cover

from taskq.cli import main  # pragma: no cover

if __name__ == "__main__":  # pragma: no cover — entry point only fires under `python -m taskq`, not under pytest import
    sys.exit(main(sys.argv[1:]))
