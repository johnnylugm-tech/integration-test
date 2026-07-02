import os, sys, subprocess
os.chdir("/Users/johnny/projects/integration-test")
env = os.environ.copy()
env["PATH"] = "/Users/johnny/projects/integration-test/.venv/bin:" + env.get("PATH","")
p = subprocess.run(
    ["/Users/johnny/projects/integration-test/.venv/bin/python","-m","pytest",
     "03-development/tests/test_fr03.py",
     "--cov=03-development/src","--cov-report=term-missing","-q",
     "--no-header","-p","no:cacheprovider","--override-ini=cache_dir="],
    capture_output=True, text=True, env=env
)
with open("/tmp/cov_out.txt","w") as f:
    f.write("STDOUT\n"+p.stdout+"\nSTDERR\n"+p.stderr+"\nEXIT "+str(p.returncode))
print("written to /tmp/cov_out.txt, exit", p.returncode)