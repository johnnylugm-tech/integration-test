import subprocess, os
os.chdir("/Users/johnny/projects/integration-test")
VENV = "/Users/johnny/projects/integration-test/.venv/bin/pytest"
result = subprocess.run(
    [VENV, "tests/test_fr01.py",
     "--cov=03-development/src", "--cov-report=term-missing", "-q"],
    capture_output=True, text=True,
)
out = result.stdout + "\n" + result.stderr
with open("/Users/johnny/projects/integration-test/.cov_output.txt", "w") as f:
    f.write(out)
print("EXIT:", result.returncode)
print(out[-3000:])
