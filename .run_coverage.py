#!/usr/bin/env python3
"""Run pytest coverage and print results."""
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "pytest",
     "03-development/tests/test_fr03.py",
     "--cov=03-development/src",
     "--cov-report=term-missing",
     "-q",
     "--no-header",
     "-p", "no:cacheprovider",
     "--override-ini=cache_dir="],
    capture_output=True, text=True
)
print("=== STDOUT ===")
print(result.stdout)
print("=== STDERR ===")
print(result.stderr)
print("=== EXIT CODE ===")
print(result.returncode)