"""[FR-01]

CLI entry-point for `python -m taskq`.

Citations:
- SPEC.md §3 FR-03 (argparse dispatch + exit-code mapping).
- SPEC.md §3 FR-01 corruption-detection clause (exit 1 + stderr "store corrupted").
"""

from __future__ import annotations

import sys

from taskq.cli.cli import main

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
