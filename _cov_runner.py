import subprocess
import sys
import os
os.chdir("/Users/johnny/projects/integration-test")
result = subprocess.run(
    [sys.executable, "-m", "pytest", "03-development/tests/test_fr01.py",
     "--cov=03-development/src", "--cov-report=term-missing", "-q"],
    capture_output=True, text=True,
)
out = "STDOUT:\n" + result.stdout + "\nSTDERR:\n" + result.stderr + "\nEXIT: %d\n" % result.returncode
with open("/Users/johnny/projects/integration-test/.cov_output.txt", "w") as f:
    f.write(out)