#!/usr/bin/env python3
"""Helper to run ruff via subprocess and write output to file."""
import sys
import subprocess

result = subprocess.run(
    [sys.executable, "-m", "ruff", "check", "03-development/src/", "--extend-ignore", "RUF001,RUF002,RUF003"],
    capture_output=True,
    text=True,
    cwd="/Users/johnny/projects/integration-test",
)
with open("/Users/johnny/projects/integration-test/.ruff_output.txt", "w") as f:
    f.write("STDOUT:\n")
    f.write(result.stdout)
    f.write("\n---STDERR---\n")
    f.write(result.stderr)
    f.write(f"\nEXIT_CODE: {result.returncode}\n")