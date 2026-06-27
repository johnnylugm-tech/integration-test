"""[FR-02] Subprocess executor: run a task's command with timeout + retry.

Public surface:
  - ``run(task: dict, *, timeout: float | None = None, retry: int = 0) -> None``

The function mutates ``task`` in place, populating:
  ``status`` (``done`` | ``failed`` | ``timeout``), ``exit_code`` (int),
  ``stdout_tail`` (str), ``stderr_tail`` (str), ``duration_ms`` (int),
  ``finished_at`` (ISO-8601 UTC, ``...Z``).

The caller is responsible for persisting the surrounding store dict via
``store.save()``; this module does not touch the store itself.

Citations:
  - 03-development/tests/test_fr02.py:96   ``taskq.executor`` is imported at
    module load time (top-level import, no try/except wrappers)
  - 03-development/tests/test_fr02.py:135  ``subprocess.run`` output capture
    asserted via stdout_tail / stderr_tail fields
  - 03-development/tests/test_fr02.py:144  ``shlex.split`` for multi-token
    commands (``echo a b c`` must print ``a b c``)
  - 03-development/tests/test_fr02.py:151  ``timeout=1`` marks status=timeout
    with exit_code=4
  - 03-development/tests/test_fr02.py:162  retry loop: ``retry=2`` ⇒ up to 3
    attempts; final status ``failed`` after exhaustion
  - 03-development/tests/test_fr02.py:262  ``executor.run`` is monkeypatched
    with a function raising ``RuntimeError`` — CLI must surface exit 1
  - 03-development/tests/test_fr02.py:218  no_shell_true architecture scan
    (see TEST_SPEC §FR02-no-shell-true; regex pattern is
    ``shell``-``=``-``True`` in that order)
"""
from __future__ import annotations

import shlex
import subprocess
import time
from datetime import datetime, timezone

# Last 4 KiB of captured output stored per stream — large enough for typical
# test prints, small enough to bound disk usage.
_TAIL_BYTES = 4096


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 with trailing ``Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tail(buf: bytes | None) -> str:
    """Decode ``buf`` (or its last ``_TAIL_BYTES``) as UTF-8 with replacement."""
    if not buf:
        return ""
    if len(buf) > _TAIL_BYTES:
        buf = buf[-_TAIL_BYTES:]
    return buf.decode("utf-8", errors="replace")


def _attempt(command: str, timeout: float | None) -> tuple:
    """Run ``command`` once; return ``(status, exit_code, stdout, stderr, ms)``.

    Status is one of ``done``, ``failed``, ``timeout``. On timeout, the
    exit_code is fixed to ``4`` per AC-FR02-11.
    """
    args = shlex.split(command)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            check=False,
            shell=False,  # explicit — also satisfies no_shell_true scan
        )
    except subprocess.TimeoutExpired as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ("timeout", 4, _tail(exc.stdout), _tail(exc.stderr), elapsed_ms)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    stdout = _tail(proc.stdout)
    stderr = _tail(proc.stderr)
    if proc.returncode == 0:
        return ("done", 0, stdout, stderr, elapsed_ms)
    return ("failed", proc.returncode, stdout, stderr, elapsed_ms)


def run(task: dict, *, timeout: float | None = None, retry: int = 0) -> None:
    """Execute ``task["command"]`` and record the outcome onto ``task``.

    Up to ``retry + 1`` attempts are made; the loop short-circuits on the
    first ``done`` result. The final attempt's status is what gets stored.
    """
    command = task["command"]
    last = _attempt(command, timeout)
    for _ in range(retry):
        if last[0] == "done":
            break
        last = _attempt(command, timeout)
    status, exit_code, stdout_tail, stderr_tail, duration_ms = last
    task["status"] = status
    task["exit_code"] = exit_code
    task["stdout_tail"] = stdout_tail
    task["stderr_tail"] = stderr_tail
    task["duration_ms"] = duration_ms
    task["finished_at"] = _now_iso()