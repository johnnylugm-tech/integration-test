"""[FR-05] taskq.__main__ — ``python -m taskq`` entry point.

Delegates to :func:`taskq.cli.main` and propagates its exit code via
``sys.exit`` (SAD §2.5.8 — no business logic here).
"""

from __future__ import annotations

import sys

from taskq.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
