"""[FR-01] Entry point for `python -m taskq`.

Citations: SPEC.md §3 FR-01
"""
from taskq.cli import main  # pragma: no cover

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())  # pragma: no cover