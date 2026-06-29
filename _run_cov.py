import sys, os, subprocess
os.chdir("/Users/johnny/projects/integration-test")
p = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_fr03.py",
     "--cov=03-development/src", "--cov-report=term-missing", "-q"],
    capture_output=True, text=True,
)
with open("/Users/johnny/projects/integration-test/.covout.txt", "w") as f:
    f.write("RC=" + str(p.returncode) + "\n")
    f.write(p.stdout)
    f.write("\n---STDERR---\n")
    f.write(p.stderr)
print("DONE", p.returncode)