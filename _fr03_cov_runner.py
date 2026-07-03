"""Run FR-03 coverage and write to a file."""
import subprocess
import os
os.chdir("/Users/johnny/projects/integration-test")
result = subprocess.run(
    ["pytest", "03-development/tests/test_fr03.py",
     "--cov=03-development/src",
     "--cov-report=term-missing",
     "-q",
     "--tb=short",
     "--no-header",
     "-p", "no:cacheprovider"],
    capture_output=True, text=True, timeout=180,
)
with open("/Users/johnny/projects/integration-test/_fr03_cov_out.txt", "w") as f:
    f.write("STDOUT:\n" + result.stdout + "\nSTDERR:\n" + result.stderr + "\nEXIT: %d\n" % result.returncode)