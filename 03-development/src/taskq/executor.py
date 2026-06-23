"""taskq task executor — subprocess execution with retry, breaker, and ThreadPoolExecutor.

[FR-02] Implements single-task and batch execution with proper state machine:
    pending → running → done | failed | timeout

[FR-03] Adds retry (exponential backoff, injectable sleep) and circuit breaker
    integration. The sleep function is injectable via `sleep_fn` for test isolation.

Uses subprocess.run with shlex.split; shell=True is never used (NFR-02).
Concurrent writes to tasks.json are protected by the store module's Lock.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, Optional

from taskq.config import Config, validate_config
from taskq.models import TaskStatus
from taskq.store import load_task, load_tasks, save_task


def run_task(
    task_id: str,
    cfg: Config,
    cached: bool = False,
    json_output: bool = False,
    sleep_fn: Optional[Callable[[float], None]] = None,
) -> int:
    """Execute a single task by id, with retry and circuit breaker (FR-03).

    [FR-02] [FR-03] State machine: pending → running → done | failed | timeout
    - exit 0 → done; non-zero → failed; TimeoutExpired → timeout
    - Result fields populated: exit_code, stdout_tail, stderr_tail,
      duration_ms, finished_at.
    - subprocess.run is called with shlex.split(command); shell=True is
      never used (NFR-02).
    - In single-task mode, returns 4 if task ends as timeout, else 0.
    - Retries up to TASKQ_RETRY_LIMIT times on failed/timeout with
      exponential backoff: sleep_fn(backoff_base * 2^n) before retry n.
    - sleep_fn defaults to time.sleep; injectable for tests (FR-03).
    - Checks circuit breaker before executing; returns 3 if breaker OPEN (FR-03).

    Returns:
        0 on done, 3 if breaker is OPEN, 4 on final timeout, else 0.
    """
    _ = validate_config(cfg)
    if sleep_fn is None:
        sleep_fn = time.sleep

    # Circuit breaker check (FR-03)
    from taskq.breaker import Breaker
    breaker = Breaker(cfg)
    if breaker.is_open():
        print("breaker open", file=sys.stderr)
        return 3

    task = load_task(task_id, cfg)

    retry_limit = cfg.retry_limit
    backoff_base = cfg.backoff_base

    final_exit_code = 0

    for attempt in range(retry_limit + 1):
        # Mark running on first attempt; re-mark on retries
        task.status = TaskStatus.running
        save_task(task, cfg)

        # Re-check breaker for HALF_OPEN slot: only the first task in HALF_OPEN
        # passes through. Subsequent tasks in HALF_OPEN still need to be checked.
        if attempt > 0:
            if breaker.is_open():
                print("breaker open", file=sys.stderr)
                return 3

        start = time.monotonic()
        try:
            result = subprocess.run(
                shlex.split(task.command),
                capture_output=True,
                text=True,
                timeout=cfg.task_timeout,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            finished_at = datetime.now(tz=timezone.utc).isoformat()

            task.exit_code = result.returncode
            task.stdout_tail = result.stdout[-2000:] if result.stdout else ""
            task.stderr_tail = result.stderr[-2000:] if result.stderr else ""
            task.duration_ms = elapsed_ms
            task.finished_at = finished_at

            if result.returncode == 0:
                task.status = TaskStatus.done
                save_task(task, cfg)
                breaker.record_success()
                return 0
            else:
                task.status = TaskStatus.failed
                final_exit_code = 0

        except subprocess.TimeoutExpired:
            elapsed_ms = (time.monotonic() - start) * 1000
            finished_at = datetime.now(tz=timezone.utc).isoformat()

            task.exit_code = None
            task.stdout_tail = ""
            task.stderr_tail = ""
            task.duration_ms = elapsed_ms
            task.finished_at = finished_at
            task.status = TaskStatus.timeout
            final_exit_code = 4

        save_task(task, cfg)

        # If there are retries left, sleep with exponential backoff and retry
        if attempt < retry_limit:
            retry_n = attempt + 1
            sleep_fn(backoff_base * (2 ** retry_n))
        else:
            # Final failure — notify breaker
            breaker.record_failure()

    return final_exit_code


def run_all(cfg: Config, cached: bool = False, sleep_fn: Optional[Callable[[float], None]] = None) -> None:
    """Execute all pending tasks concurrently via ThreadPoolExecutor.

    [FR-02] Uses ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS) to
    dispatch all pending tasks in parallel. Store writes are thread-safe
    via the shared Lock in taskq.store (NFR-03).

    [FR-03] Each worker respects the circuit breaker; injectable sleep_fn
    is forwarded to run_task for test isolation.
    """
    _ = validate_config(cfg)
    tasks = load_tasks(cfg)
    pending = [t for t in tasks.values() if t.status == TaskStatus.pending]

    with ThreadPoolExecutor(max_workers=cfg.max_workers) as executor:
        futures = [
            executor.submit(run_task, task.id, cfg, cached, False, sleep_fn)
            for task in pending
        ]
        for f in futures:
            f.result()
