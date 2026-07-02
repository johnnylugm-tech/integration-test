import sys, os
sys.path.insert(0, "/Users/johnny/projects/integration-test")
os.chdir("/Users/johnny/projects/integration-test")

# Use coverage programmatically + pytest.main
import coverage
cov = coverage.Coverage(source=["03-development/src"], data_suffix=True)
cov.start()

import importlib
mod = importlib.import_module("pytest")
rc = mod.main([
    "03-development/tests/test_fr03.py",
    "-q",
    "--no-header",
    "-p", "no:cacheprovider",
    "--tb=line",
])

cov.stop()
cov.save()

# Print coverage report
sys.stdout.write("\n\n=== COVERAGE REPORT ===\n")
sys.stdout.write(cov.report(show_missing=True))
sys.stdout.write("\n")

sys.exit(rc)