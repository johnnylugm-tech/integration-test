"""Run full pytest suite, capture output."""
import subprocess
import sys

r = subprocess.run(
    [".venv/bin/pytest", "03-development/tests/", "-q", "--tb=short"],
    cwd="/Users/johnny/projects/integration-test",
    capture_output=True, text=True, timeout=180,
    env={"PYTHONPATH": "03-development/src", "PATH": "/usr/bin:/bin"},
)
sys.stdout.write(r.stdout)
sys.stderr.write(r.stderr)
sys.exit(r.returncode)
