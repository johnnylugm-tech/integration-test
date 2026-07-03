#!/usr/bin/env python3
import subprocess
import sys
r = subprocess.run([sys.executable, "-m", "ruff", "check", "03-development/src/", "--extend-ignore", "RUF001,RUF002,RUF003"], capture_output=True, text=True, cwd="/Users/johnny/projects/integration-test")
sys.stdout.write(r.stdout)
sys.stdout.write("---STDERR---\n")
sys.stdout.write(r.stderr)
sys.stdout.write("EXIT_CODE: %d\n" % r.returncode)
sys.exit(r.returncode)