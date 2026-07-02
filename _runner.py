import os
import sys
import subprocess

os.chdir("/Users/johnny/projects/integration-test")
sys.path.insert(0, "03-development/src")

# Run the test command via subprocess
p = subprocess.Popen(
    ["/Users/johnny/Library/Python/3.9/bin/pytest", "03-development/tests/test_fr01.py",
     "--cov=03-development/src", "--cov-report=term-missing", "-q"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
)
out, _ = p.communicate()
with open("/tmp/cov_output.txt", "w") as f:
    f.write(out)
print("DONE")
print("Exit:", p.returncode)