"""Run ruff and report violations."""
import subprocess
import sys

result = subprocess.run(
    [".venv/bin/ruff", "check", "03-development/src/", "--extend-ignore", "RUF001,RUF002,RUF003"],
    capture_output=True,
    text=True,
)
print("EXIT:", result.returncode)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
sys.exit(result.returncode)