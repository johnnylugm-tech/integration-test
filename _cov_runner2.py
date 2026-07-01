"""Coverage runner - invoked via Bash."""
import subprocess, sys, os

os.chdir("/Users/johnny/projects/integration-test")
result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_fr01.py",
     "--cov=03-development/src", "--cov-report=term-missing", "-q"],
    capture_output=True, text=True,
)
output = "STDOUT:\n" + result.stdout + "\nSTDERR:\n" + result.stderr + "\nEXIT: %d\n" % result.returncode
with open("/Users/johnny/projects/integration-test/.cov_output.txt", "w") as f:
    f.write(output)