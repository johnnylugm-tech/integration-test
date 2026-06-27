"""Auto-start coverage in subprocesses when COVERAGE_PROCESS_START is set.

Pytest-cov only measures the parent pytest process. Integration tests
spawn ``python -m taskq`` subprocesses whose source-tree coverage must
also be measured. This module is imported by Python at startup when it's
on ``sys.path``; if ``COVERAGE_PROCESS_START`` points at a config file,
coverage.process_startup() runs and writes parallel data files that
``coverage combine`` later merges.
"""
import os

if os.environ.get("COVERAGE_PROCESS_START"):
    try:
        import coverage

        coverage.process_startup()
    except Exception:
        # Don't crash the child if coverage isn't installed.
        pass