"""Lint check helper script."""
import subprocess
import sys

result = subprocess.run(
    ["./.venv/bin/ruff", "check", "03-development/src/taskq/", "--extend-ignore", "RUF001,RUF002,RUF003"],
    capture_output=True,
    text=True,
)
print(result.stdout)
print("STDERR:", result.stderr)
print("EXIT:", result.returncode)
sys.exit(result.returncode)