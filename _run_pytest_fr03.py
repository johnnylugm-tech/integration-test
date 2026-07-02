import subprocess
import sys

result = subprocess.run(
    ["/Users/johnny/projects/integration-test/.venv/bin/pytest",
     "03-development/tests/test_fr03.py",
     "--cov=03-development/src",
     "--cov-report=term-missing",
     "-q",
     "--no-header",
     "-p", "no:cacheprovider"],
    cwd="/Users/johnny/projects/integration-test",
    capture_output=True,
    text=True,
)

sys.stdout.write("=== STDOUT ===\n")
sys.stdout.write(result.stdout)
sys.stdout.write("\n=== STDERR ===\n")
sys.stdout.write(result.stderr)
sys.stdout.write("\n=== EXIT CODE ===\n")
sys.stdout.write(str(result.returncode))
sys.stdout.write("\n")
sys.stdout.flush()