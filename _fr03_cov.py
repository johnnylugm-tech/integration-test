import os
import subprocess
os.chdir("/Users/johnny/projects/integration-test")
r = subprocess.run(
    ["pytest", "03-development/tests/test_fr03.py", "--cov=03-development/src",
     "--cov-report=term-missing", "-q", "--no-header", "-p", "no:cacheprovider",
     "--tb=line"],
    capture_output=True, text=True, timeout=180,
)
with open("_fr03_cov_result.txt", "w") as f:
    f.write("=== STDOUT ===\n" + r.stdout + "\n=== STDERR ===\n" + r.stderr + "\n=== EXIT ===\n" + str(r.returncode) + "\n")