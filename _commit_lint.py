"""Helper: stage and commit lint fixes."""
import subprocess

# Stage only src/ files (per task: git add 03-development/src/)
r1 = subprocess.run(
    ["git", "add", "03-development/src/taskq/__main__.py",
     "03-development/src/taskq/cli.py"],
    capture_output=True, text=True
)
print("ADD:", r1.returncode, r1.stdout, r1.stderr)

# Confirm what's staged
r2 = subprocess.run(
    ["git", "diff", "--cached", "--stat"],
    capture_output=True, text=True
)
print("STAGED:", r2.returncode, r2.stdout, r2.stderr)

# Commit
r3 = subprocess.run(
    ["git", "commit", "-m", "fix(FR-01): resolve ruff linting violations"],
    capture_output=True, text=True
)
print("COMMIT:", r3.returncode, r3.stdout, r3.stderr)

# Get hash
r4 = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    capture_output=True, text=True
)
print("HEAD:", r4.stdout.strip())