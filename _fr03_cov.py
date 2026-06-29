import subprocess, sys
r = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_fr03.py",
     "--cov=03-development/src", "--cov-report=term-missing", "-q"],
    capture_output=True, text=True,
    cwd="/Users/johnny/projects/integration-test",
)
with open("/Users/johnny/projects/integration-test/.covout.txt", "w") as f:
    f.write("STDOUT:\n")
    f.write(r.stdout)
    f.write("\nSTDERR:\n")
    f.write(r.stderr)
print("EXIT", r.returncode)