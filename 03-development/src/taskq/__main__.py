"""[FR-05] taskq.__main__ — ``python -m taskq`` entry point.

Delegates to :func:`taskq.cli.main` and propagates its exit code via
``sys.exit`` (SAD §2.5.8 — no business logic here).
"""

from __future__ import annotations  # pragma: no cover
  # pragma: no cover
import sys  # pragma: no cover
  # pragma: no cover
from taskq.cli import main  # pragma: no cover
  # pragma: no cover
if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))  # pragma: no cover
