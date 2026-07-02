import subprocess
import sys
result = subprocess.run(
    [sys.executable, "-m", "pytest", "03-development/tests/test_fr03.py",
     "--cov=03-development/src", "--cov-report=term-missing", "-q"],
    cwd="/Users/johnny/projects/integration-test",
    capture_output=True, text=True
)
print("STDOUT:")
print(result.stdout)
print("STDERR:")
print(result.stderr)
print("EXIT:", result.returncode)