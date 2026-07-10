"""`python -m taskq` entry point — forwards to cli.main.

Created so SAD §1.1's `smoke` target (`make verify-system` → `python -m
taskq --help`) has a working module entry point without changing the
production CLI surface (cli.main stays the single source of truth for
FR-05).
"""
from __future__ import annotations  # pragma: no cover

import sys  # pragma: no cover

from taskq import cli  # pragma: no cover

if __name__ == "__main__":  # pragma: no cover
    sys.exit(cli.main(sys.argv[1:]))  # pragma: no cover
