"""Entry shim for python -m taskq.

[FR-05] Delegates to cli.main().
"""
from taskq.cli import main  # noqa: F401

if __name__ == "__main__":  # pragma: no cover
    main()
