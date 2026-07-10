"""Run pytest with coverage and write output to a project file for reading."""
import sys
from pytest import console_main

sys.argv = [
    "pytest",
    "03-development/tests/test_fr01.py",
    "--cov=taskq",
    "--cov-report=term-missing",
    "-q",
    "--no-header",
]

with open("03-development/tests/.coverage_output.txt", "w") as f:
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = f
    sys.stderr = f
    try:
        rc = console_main()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

with open("03-development/tests/.coverage_rc.txt", "w") as f:
    f.write(str(rc))

sys.exit(rc)
