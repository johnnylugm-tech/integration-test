"""Task executor — runs a task's command under a controlled subprocess.

[FR-02, NFR-02, NFR-04, NFR-05]
Citations: SPEC.md line 88 (FR-02 executor: subprocess.run + shlex.split, no
               shell invocation; pending -> running -> done|failed|timeout;
               result fields; single-task timeout exit 4),
           SPEC.md line 141 (NFR-04 stdout/stderr tail redaction),
           SAD.md line 83 (executor public surface),
           SAD.md line 172 (execute() signature),
           SAD.md line 323 (NFR-04 redaction regex).
"""
from __future__ import annotations

import re
import shlex
import subprocess
import time

from taskq.core.models import RunResult, TaskStatus, utcnow_iso

# FR-02: tails are truncated to the last 2000 characters before persistence.
TAIL_MAX_CHARS = 2000

# NFR-04: any line matching a secret pattern is replaced wholesale with the
# sentinel below, before the tail is ever written to disk.
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|token=\S+)")
_REDACTED = "[REDACTED]"


def _tail(text: str | None) -> str:
    """Return the last TAIL_MAX_CHARS characters of text ("" for None).

    [FR-02]
    Citations: SPEC.md line 88 (stdout_tail / stderr_tail = last 2000 chars).
    """
    return (text or "")[-TAIL_MAX_CHARS:]


def _redact(text: str) -> str:
    """Replace any line containing a secret with the [REDACTED] sentinel.

    [NFR-04]
    Citations: SPEC.md line 141 (redact sk-*/token= lines before disk write),
               SAD.md line 323 (line-by-line redaction regex).
    """
    lines = text.split("\n")
    return "\n".join(_REDACTED if _SECRET_RE.search(line) else line for line in lines)


def execute(command: str, *, timeout: float) -> RunResult:
    """Run command in a subprocess and return its RunResult.

    [FR-02, NFR-02, NFR-04]
    Uses ``subprocess.run(shlex.split(command), ..., shell=False)`` — the command
    is tokenized with shlex and never handed to a shell (NFR-02). Maps the exit
    outcome onto the task state machine: exit 0 -> done, non-zero -> failed,
    ``TimeoutExpired`` -> timeout. On timeout, ``subprocess.run`` kills and reaps
    the child, so no orphan process is left behind. Tails are truncated to the
    last 2000 chars and secret-redacted (NFR-04) before being returned.

    Citations: SPEC.md line 88 (FR-02 execution + state machine + result fields),
               SAD.md line 172 (execute signature).
    """
    argv = shlex.split(command)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = (time.monotonic() - start) * 1000.0
        return RunResult(
            status=TaskStatus.TIMEOUT,
            exit_code=None,
            stdout_tail=_redact(_tail(exc.stdout)),
            stderr_tail=_redact(_tail(exc.stderr)),
            duration_ms=duration_ms,
            finished_at=utcnow_iso(),
        )
    duration_ms = (time.monotonic() - start) * 1000.0
    status = TaskStatus.DONE if proc.returncode == 0 else TaskStatus.FAILED
    return RunResult(
        status=status,
        exit_code=proc.returncode,
        stdout_tail=_redact(_tail(proc.stdout)),
        stderr_tail=_redact(_tail(proc.stderr)),
        duration_ms=duration_ms,
        finished_at=utcnow_iso(),
    )
