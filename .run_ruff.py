#!/usr/bin/env python3
"""Helper to run ruff via subprocess and capture output."""
import sys
import subprocess

result = subprocess.run(
    ["ruff", "check", "03-development/src/", "--extend-ignore", "RUF001,RUF002,RUF003"],
    capture_output=True,
    text=True,
    cwd="/Users/johnny/projects/integration-test",
)
sys.stdout.write(result.stdout)
sys.stdout.write("---STDERR---\n")
sys.stdout.write(result.stderr)
sys.stdout.write(f"EXIT_CODE: {result.returncode}\n")
sys.exit(result.returncode)