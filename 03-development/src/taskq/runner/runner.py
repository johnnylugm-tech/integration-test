"""Subprocess execution + retry loop for taskq.

[FR-02] Citations:
- SPEC.md §3 FR-02 第一段 — `subprocess.run(shlex.split(command),
  capture_output=True, text=True, timeout=T)`; **any path that uses
  ``shell=True`` is forbidden (NFR-02)**.
- SPEC.md §3 FR-02 狀態機 — exit 0 → done, non-zero → failed,
  ``TimeoutExpired`` → timeout.
- SPEC.md §3 FR-02 結果欄位 — exit_code, stdout_tail (末 2000 字元),
  stderr_tail (末 2000 字元), duration_ms, finished_at.
- SPEC.md §3 FR-02 重試 — failed/timeout 自動重試, 上限
  ``TASKQ_RETRY_LIMIT`` 次 (預設 2). 成功的任務不重試.
- SPEC.md §3 FR-02 單一任務模式 — timeout → exit 4, 其他未預期例外 → exit 1
  (不得裸 ``except:`` 吞噬).
- SAD §3.3 — runner contract.

The runner deliberately calls ``subprocess.run`` via ``import subprocess`` (NOT
``from subprocess import run``) so tests can monkeypatch the call site
deterministically with ``monkeypatch.setattr("taskq.runner.runner.subprocess.run", ...)``
and intercept every invocation without executing real commands.
"""
from __future__ import annotations

import shlex
import subprocess
import time
from datetime import datetime, timezone

from taskq.core.models import TaskResult, TaskStatus


# SPEC.md §3 FR-02 結果欄位 — stdout/stderr tails are bounded to the last
# 2000 characters.
_TAIL_LIMIT = 2000


def _bounded_tail(text: str | None) -> str:
    """Return the last 2000 chars of ``text`` (handles None safely).

    [FR-02] Citations: SPEC.md §3 FR-02 結果欄位 — 「末 2000 字元」.
    """
    if not text:
        return ""
    return text[-_TAIL_LIMIT:]


def _run_once(command: str, timeout: float) -> tuple[TaskStatus, int, str, str]:
    """Invoke ``subprocess.run`` exactly once and map the outcome.

    Returns ``(status, exit_code, stdout_tail, stderr_tail)`` where:
      * status ∈ {DONE, FAILED, TIMEOUT}
      * on TIMEOUT, ``exit_code`` is 0 (no exit code was produced).

    [FR-02] Citations:
    - SPEC.md §3 FR-02 第一段 (subprocess 呼叫形式, no shell=True).
    - SPEC.md §3 FR-02 狀態機 (exit / TimeoutExpired mapping).
    - SPEC.md §3 FR-02 結果欄位 (tail truncation).
    """
    argv = shlex.split(command)
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # SPEC §3 FR-02 狀態機: TimeoutExpired → timeout.
        return TaskStatus.TIMEOUT, 0, "", ""

    stdout_tail = _bounded_tail(completed.stdout)
    stderr_tail = _bounded_tail(completed.stderr)

    if completed.returncode == 0:
        return TaskStatus.DONE, completed.returncode, stdout_tail, stderr_tail
    # SPEC §3 FR-02 狀態機: 非 0 → failed.
    return TaskStatus.FAILED, completed.returncode, stdout_tail, stderr_tail


def run_task(command: str, *, timeout: float, retry_limit: int = 2) -> TaskResult:
    """Execute ``command`` with retry-on-failure semantics.

    Retries on FAILED or TIMEOUT outcomes up to ``retry_limit`` additional
    attempts (so the total attempt count is ``1 + retry_limit``). Done
    outcomes short-circuit; they are never retried even when
    ``retry_limit`` is large.

    [FR-02] Citations:
    - SPEC.md §3 FR-02 重試 — failed/timeout 自動重試, 上限 TASKQ_RETRY_LIMIT.
    - SPEC.md §3 FR-02 結果欄位 — populated ``TaskResult`` fields.
    """
    started = time.monotonic()
    last_status = TaskStatus.FAILED
    last_exit_code = 1
    last_stdout_tail = ""
    last_stderr_tail = ""

    total_attempts = 1 + max(0, int(retry_limit))
    for _ in range(total_attempts):
        status, exit_code, stdout_tail, stderr_tail = _run_once(command, timeout)
        last_status = status
        last_exit_code = exit_code
        last_stdout_tail = stdout_tail
        last_stderr_tail = stderr_tail
        # SPEC §3 FR-02: 成功的任務不重試, 即使 retry_limit > 0.
        if status == TaskStatus.DONE:
            break

    duration_ms = int((time.monotonic() - started) * 1000)
    return TaskResult(
        status=last_status,
        exit_code=last_exit_code,
        stdout_tail=last_stdout_tail,
        stderr_tail=last_stderr_tail,
        duration_ms=duration_ms,
        finished_at=datetime.now(timezone.utc),
    )


def run_single_task(command: str, *, timeout: float | None = None) -> int:
    """CLI entry point: run one task, return a process exit code.

    Mapping (SPEC.md §3 FR-02):
      * subprocess timeout → ``4``
      * other unexpected exception → ``1`` (catches ``Exception``, NEVER
        bare ``except:`` — must not swallow ``KeyboardInterrupt`` /
        ``SystemExit``)
      * otherwise → the subprocess's own ``returncode``.

    [FR-02] Citations: SPEC.md §3 FR-02 單一任務模式 + 未預期例外處理.
    """
    effective_timeout = 10.0 if timeout is None else timeout
    try:
        argv = shlex.split(command)
    except ValueError:
        # Malformed shell-like command (e.g. unmatched quote). Not a
        # timeout, not a successful run — surface as a generic failure.
        return 1

    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
    except subprocess.TimeoutExpired:
        # SPEC §3 FR-02 單一任務模式: timeout → exit 4.
        return 4
    except Exception:  # noqa: BLE001 — narrow, NOT bare except:.
        # SPEC §3 FR-02 未預期例外: → exit 1. Spec forbids bare `except:`
        # which would also swallow KeyboardInterrupt / SystemExit.
        return 1

    return completed.returncode
