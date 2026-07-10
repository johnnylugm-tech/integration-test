"""Run FR-03 coverage via subprocess, output to file."""
import subprocess

result = subprocess.run(
    [".venv/bin/pytest", "03-development/tests/test_fr03.py",
     "--cov=03-development/src", "--cov-report=term-missing", "-q"],
    cwd="/Users/johnny/projects/integration-test",
    capture_output=True, text=True, timeout=120,
)
with open("/tmp/cov_out.txt", "w") as f:
    f.write("STDOUT:\n")
    f.write(result.stdout)
    f.write("\n\nSTDERR:\n")
    f.write(result.stderr)
    f.write(f"\n\nEXIT: {result.returncode}\n")
print("WROTE /tmp/cov_out.txt, exit", result.returncode)