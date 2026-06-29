import subprocess
result = subprocess.run(
    ["python", "-m", "pytest", "tests/test_fr03.py", "--cov=03-development/src", "--cov-report=term-missing", "-q"],
    capture_output=True, text=True
)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("RC:", result.returncode)
