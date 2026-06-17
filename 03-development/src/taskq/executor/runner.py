"""[FR-02] taskq.executor.runner — subprocess invocation.

Citations:
- 03-development/tests/test_fr02.py:16 (run_subprocess(command, timeout) -> CompletedProcess)
- 03-development/tests/test_fr02.py:194-214 (shell=False NFR-02 invariant)
- 03-development/tests/test_fr02.py:222-233 (timeout path)
- 03-development/tests/test_fr02.py:399-427 (orphan subprocess cleanup NFR-15)
- SRS.md:67 (shell=False NFR-02)
"""
from __future__ import annotations

import shlex
import subprocess


def run_subprocess(command: str, timeout: float) -> subprocess.CompletedProcess:
    """Execute `command` with shell=False and capture stdout/stderr.

    The command is tokenized via shlex.split so multi-word commands
    (e.g. ``python3 -c '...'``) work without a shell. On
    :class:`subprocess.TimeoutExpired`, subprocess.run kills the child
    and reaps it, satisfying NFR-15 (no orphan subprocesses).

    Citations:
    - 03-development/tests/test_fr02.py:16 (signature)
    - 03-development/tests/test_fr02.py:194-214 (shell=False NFR-02)
    - 03-development/tests/test_fr02.py:222-233 (TimeoutExpired path)
    - 03-development/tests/test_fr02.py:399-427 (orphan cleanup NFR-15)
    - SRS.md:66-67 (shlex.split + shell=False)
    """
    args = shlex.split(command)
    return subprocess.run(
        args,
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
