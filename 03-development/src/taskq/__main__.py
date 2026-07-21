"""[FR-01] ``python -m taskq`` entry point.

Citations:
  SPEC §3 FR-01 (CLI entry surface).
  SAD §3.1 module layout (cli / store / models).
"""

import sys

from taskq import cli

if __name__ == "__main__":
    sys.exit(cli.main(sys.argv[1:]))