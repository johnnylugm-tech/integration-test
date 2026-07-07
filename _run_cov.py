"""Run pytest with coverage via Python API and dump the report."""
import sys
from io import StringIO

import coverage
import pytest

cov = coverage.Coverage(source=["03-development/src"])
cov.start()

# Run pytest programmatically
sys.argv = [
    "pytest",
    "03-development/tests/test_fr01.py",
    "-v",
    "--tb=short",
]
rc = pytest.main(sys.argv[1:])

cov.stop()
cov.save()

out = StringIO()
try:
    percentage = cov.report(file=out, show_missing=True)
except coverage.misc.NoSource:
    print("NoSource error")
    sys.exit(2)

print(out.getvalue())
print(f"RC: {rc}")
print(f"COVERAGE: {percentage:.2f}%")
