"""taskq task executor — subprocess execution with ThreadPoolExecutor for --all.

[FR-02] Implements single-task and batch execution with proper state machine:
    pending → running → done | failed | timeout

Uses subprocess.run with shlex.split; shell=True is never used (NFR-02).
Concurrent writes to tasks.json are protected by the store module's Lock.
"""
from __future__ import annotations

import shlex
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from taskq.config import Config, validate_config
from taskq.models import TaskStatus
from taskq.store import load_task, load_tasks, save_task


def run_task(
    task_id: str,
    cfg: Config,
    cached: bool = False,
    json_output: bool = False,
) -> int:
    """Execute a single task by id, updating its state machine in tasks.json.

    [FR-02] State machine: pending → running → done | failed | timeout
    - exit 0 → done; non-zero → failed; TimeoutExpired → timeout
    - Result fields populated: exit_code, stdout_tail, stderr_tail,
      duration_ms, finished_at.
    - subprocess.run is called with shlex.split(command); shell=True is
      never used (NFR-02).
    - In single-task mode, returns 4 if task ends as timeout, else 0.

    Returns:
        0 on success (done/failed), 4 on timeout.
    """
    _ = validate_config(cfg)
    task = load_task(task_id, cfg)

    # Mark running
    task.status = TaskStatus.running
    save_task(task, cfg)

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
        task.status = TaskStatus.done if result.returncode == 0 else TaskStatus.failed
        save_task(task, cfg)
        return 0

    except subprocess.TimeoutExpired:
        elapsed_ms = (time.monotonic() - start) * 1000
        finished_at = datetime.now(tz=timezone.utc).isoformat()

        task.exit_code = None
        task.stdout_tail = ""
        task.stderr_tail = ""
        task.duration_ms = elapsed_ms
        task.finished_at = finished_at
        task.status = TaskStatus.timeout
        save_task(task, cfg)
        return 4


def run_all(cfg: Config, cached: bool = False) -> None:
    """Execute all pending tasks concurrently via ThreadPoolExecutor.

    [FR-02] Uses ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS) to
    dispatch all pending tasks in parallel. Store writes are thread-safe
    via the shared Lock in taskq.store (NFR-03).
    """
    _ = validate_config(cfg)
    tasks = load_tasks(cfg)
    pending = [t for t in tasks.values() if t.status == TaskStatus.pending]

    with ThreadPoolExecutor(max_workers=cfg.max_workers) as executor:
        futures = [
            executor.submit(run_task, task.id, cfg, cached)
            for task in pending
        ]
        for f in futures:
            f.result()
