import subprocess, sys, os
os.chdir("/Users/johnny/projects/integration-test")
result = subprocess.run(
    ["pytest", "03-development/tests/test_fr02.py",
     "--cov=03-development/src", "--cov-report=term-missing", "-q"],
    capture_output=True, text=True,
)
with open("/Users/johnny/projects/integration-test/_task_cov_out.txt", "w") as f:
    f.write("STDOUT:\n" + result.stdout + "\nSTDERR:\n" + result.stderr + "\nEXIT: %d\n" % result.returncode)
