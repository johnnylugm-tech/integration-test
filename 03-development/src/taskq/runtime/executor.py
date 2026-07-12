"""Task executor — runs a task's command under a controlled subprocess.

[FR-02, FR-03, NFR-02, NFR-04, NFR-05]
Citations: SPEC.md line 88 (FR-02 executor: subprocess.run + shlex.split, no
               shell invocation; pending -> running -> done|failed|timeout;
               result fields; single-task timeout exit 4),
           SPEC.md line 89 (FR-03 retry up to TASKQ_RETRY_LIMIT with
               TASKQ_BACKOFF_BASE x 2^n exponential backoff),
           SPEC.md line 141 (NFR-04 stdout/stderr tail redaction),
           SAD.md line 83 (executor public surface),
           SAD.md line 172 (execute() signature),
           SAD.md line 223 (retry only on failed/timeout while budget remains),
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


def _tail(text: str | bytes | None) -> str:
    """Return the last TAIL_MAX_CHARS characters of text ("" for None).

    [FR-02]
    Accepts bytes as well as str: ``subprocess.TimeoutExpired.stdout`` is typed
    ``bytes | None`` in the stdlib stubs (and can be bytes at runtime even under
    ``text=True``), so bytes are decoded defensively before truncation.
    Citations: SPEC.md line 88 (stdout_tail / stderr_tail = last 2000 chars).
    """
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return text[-TAIL_MAX_CHARS:]


def _redact(text: str) -> str:
    """Replace any line containing a secret with the [REDACTED] sentinel.

    [NFR-04]
    Citations: SPEC.md line 141 (redact sk-*/token= lines before disk write),
               SAD.md line 323 (line-by-line redaction regex).
    """
    lines = text.split("\n")
    return "\n".join(_REDACTED if _SECRET_RE.search(line) else line for line in lines)


def _elapsed_ms(start: float) -> float:
    """Return milliseconds elapsed since ``start`` (a time.monotonic() reading)."""
    return (time.monotonic() - start) * 1000.0


def _build_result(
    status: TaskStatus,
    *,
    exit_code: int | None,
    stdout: str | bytes | None,
    stderr: str | bytes | None,
    duration_ms: float,
) -> RunResult:
    """Assemble a RunResult, applying tail truncation and secret redaction.

    [FR-02, NFR-04]
    Single source of truth for the RunResult shape so the timeout and
    normal-exit branches don't drift apart.
    """
    return RunResult(
        status=status,
        exit_code=exit_code,
        stdout_tail=_redact(_tail(stdout)),
        stderr_tail=_redact(_tail(stderr)),
        duration_ms=duration_ms,
        finished_at=utcnow_iso(),
    )


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
        return _build_result(
            TaskStatus.TIMEOUT,
            exit_code=None,
            stdout=exc.stdout,
            stderr=exc.stderr,
            duration_ms=_elapsed_ms(start),
        )
    status = TaskStatus.DONE if proc.returncode == 0 else TaskStatus.FAILED
    return _build_result(
        status,
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        duration_ms=_elapsed_ms(start),
    )


def run_with_retry(
    command: str,
    *,
    timeout: float,
    retry_limit: int,
    backoff_base: float,
) -> RunResult:
    """Run command, retrying on failed/timeout outcomes up to retry_limit times.

    [FR-03]
    Before the n-th retry (1-indexed), sleeps ``backoff_base * 2**n`` seconds
    via the module-level ``time.sleep`` (patchable by tests for determinism).
    Returns the final RunResult once the outcome is DONE, or once the retry
    budget is exhausted.

    Citations: SPEC.md line 89 (retry cap + exponential backoff formula),
               SAD.md line 223 (retry only on failed/timeout while budget remains).
    """
    attempt = 0
    while True:
        result = execute(command, timeout=timeout)
        if result.status not in (TaskStatus.FAILED, TaskStatus.TIMEOUT):
            return result
        if attempt >= retry_limit:
            return result
        attempt += 1
        time.sleep(backoff_base * (2 ** attempt))
