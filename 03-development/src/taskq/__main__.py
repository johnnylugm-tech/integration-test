"""[FR-01] Entry point for `python -m taskq`.

Citations: SPEC.md §3 FR-01
"""
from taskq.cli import main

if __name__ == "__main__":
    raise SystemExit(main())