import subprocess
result = subprocess.run(
    [".venv/bin/pytest", "tests/test_fr01.py",
     "--cov=03-development/src", "--cov-report=term-missing", "-q"],
    capture_output=True, text=True,
)
out = result.stdout + "\n" + result.stderr
with open(".cov_check_output.txt", "w") as f:
    f.write(out)
print("EXIT:", result.returncode)
print(out[-3000:])
