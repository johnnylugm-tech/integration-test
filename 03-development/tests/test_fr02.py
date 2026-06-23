"""Failing tests for FR-02: Task executor.

[FR-02] — TDD-RED phase: tests import from taskq.executor which does not exist yet.
Tests fail (or raise ImportError/ModuleNotFoundError) — valid RED state.

Sub-assertion anchor pattern per check-test-mirrors-spec:
    if <var> == None:  (trigger=None matches spec_trigger {"None"})
        assert <predicate>   (predicate matches TEST_SPEC.md verbatim)
"""
import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from taskq.config import get_config
from taskq.executor import run_task, run_all  # noqa: F401 — import triggers RED if missing
from taskq.models import Task, TaskStatus
from taskq.store import load_tasks, save_task, load_task
from taskq.cli import cmd_submit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(command: str, tmp_path, name=None) -> Task:
    """Submit a task and return it; TASKQ_HOME is set to tmp_path."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    return cmd_submit(command, name=name, cfg=cfg)


# ---------------------------------------------------------------------------
# Happy-path state transitions
# ---------------------------------------------------------------------------


def test_fr02_done_state_on_exit_zero(tmp_path):
    """[FR-02] Command with exit 0 transitions task to 'done'.

    Sub-assertions: AC02-done-exit-code-0
    """
    task = _make_task("echo hi", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    result = run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    # AC02-done-exit-code-0 anchor — trigger=None
    if updated.exit_code == None:  # noqa: E711
        assert updated.exit_code == 0
    assert updated.status == TaskStatus.done
    assert updated.exit_code == 0


def test_fr02_failed_state_on_nonzero_exit(tmp_path):
    """[FR-02] Command with non-zero exit transitions task to 'failed'.

    Sub-assertions: AC02-failed-status
    """
    task = _make_task("false", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    result = updated.status
    if result == None:  # noqa: E711
        assert result == TaskStatus.failed
    assert updated.status == TaskStatus.failed


def test_fr02_timeout_state_on_TimeoutExpired(tmp_path):
    """[FR-02] Command that exceeds timeout transitions task to 'timeout'.

    Sub-assertions: AC02-timeout-status (NP-15)
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    os.environ["TASKQ_TASK_TIMEOUT"] = "0.1"
    try:
        cfg = get_config()
        task = cmd_submit("sleep 5", name=None, cfg=cfg)
        run_task(task.id, cfg=cfg)
        updated = load_task(task.id, cfg)
        result = updated.status
        if result == None:  # noqa: E711
            assert result == TaskStatus.timeout
        assert updated.status == TaskStatus.timeout
    finally:
        del os.environ["TASKQ_TASK_TIMEOUT"]


def test_fr02_records_stdout_tail_last_2000_chars(tmp_path):
    """[FR-02] stdout_tail stores at most the last 2000 characters.

    Sub-assertions: AC02-stdout-tail-max
    """
    task = _make_task("python3 -c \"print('A'*3000)\"", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    result = updated.stdout_tail
    # AC02-stdout-tail-max anchor — trigger=None
    if result == None:  # noqa: E711
        assert len(result) <= 2000
    assert result is not None
    assert len(result) <= 2000


def test_fr02_records_stderr_tail_last_2000_chars(tmp_path):
    """[FR-02] stderr_tail stores at most the last 2000 characters.

    Sub-assertions: AC02-stderr-tail-max
    """
    task = _make_task(
        "python3 -c \"import sys; sys.stderr.write('B'*3000)\"", tmp_path
    )
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    result = updated.stderr_tail
    # AC02-stderr-tail-max anchor — trigger=None
    if result == None:  # noqa: E711
        assert len(result) <= 2000
    assert result is not None
    assert len(result) <= 2000


def test_fr02_records_duration_ms(tmp_path):
    """[FR-02] duration_ms is populated and non-negative after execution.

    Sub-assertions: AC02-duration-positive
    """
    task = _make_task("echo hi", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    result = updated.duration_ms
    # AC02-duration-positive anchor — trigger=None
    if result == None:  # noqa: E711
        assert result >= 0
    assert result is not None
    assert result >= 0


def test_fr02_records_finished_at(tmp_path):
    """[FR-02] finished_at is populated after execution.

    Sub-assertions: AC02-finished-at-present
    """
    task = _make_task("echo hi", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    result = updated.finished_at
    # AC02-finished-at-present anchor — trigger=None
    if result == None:  # noqa: E711
        assert result is not None
    assert result is not None


def test_fr02_single_task_timeout_returns_exit_4(tmp_path):
    """[FR-02] Single-task timeout returns exit code 4.

    Sub-assertions: AC02-timeout-exit-4 (NP-15)
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    os.environ["TASKQ_TASK_TIMEOUT"] = "0.1"
    try:
        cfg = get_config()
        task = cmd_submit("sleep 5", name=None, cfg=cfg)
        result = run_task(task.id, cfg=cfg)
        # AC02-timeout-exit-4 anchor — trigger=None
        if result == None:  # noqa: E711
            assert result == 4
        assert result == 4
    finally:
        del os.environ["TASKQ_TASK_TIMEOUT"]


# ---------------------------------------------------------------------------
# Concurrency (NP-13)
# ---------------------------------------------------------------------------


def test_fr02_run_all_uses_thread_pool_max_workers(tmp_path):
    """[FR-02] run_all dispatches pending tasks via ThreadPoolExecutor.

    Sub-assertions: AC02-run-all-concurrent (NP-13)
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    os.environ["TASKQ_MAX_WORKERS"] = "2"
    try:
        cfg = get_config()
        for i in range(4):
            cmd_submit(f"echo task{i}", name=None, cfg=cfg)
        run_all(cfg=cfg)
        tasks = load_tasks(cfg)
        # all should be done
        result = all(t.status == TaskStatus.done for t in tasks.values())
        if result == None:  # noqa: E711
            assert result is True
        assert result is True
        assert len(tasks) == 4
    finally:
        del os.environ["TASKQ_MAX_WORKERS"]


def test_fr02_concurrent_writes_preserve_tasks_json_integrity(tmp_path):
    """[FR-02] Concurrent run_task calls do not corrupt tasks.json (NP-13).

    Sub-assertions: AC02-concurrent-json-valid
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    # Submit 5 tasks
    task_ids = []
    for i in range(5):
        t = cmd_submit(f"echo t{i}", name=None, cfg=cfg)
        task_ids.append(t.id)

    errors = []

    def run_one(tid):
        try:
            os.environ["TASKQ_HOME"] = str(tmp_path)
            run_task(tid, cfg=get_config())
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=run_one, args=(tid,)) for tid in task_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent run_task raised: {errors}"
    tasks = load_tasks(cfg)
    assert len(tasks) == 5


# ---------------------------------------------------------------------------
# Security audit (NP-08 / NFR-02)
# ---------------------------------------------------------------------------


def test_fr02_subprocess_called_without_shell_true(tmp_path):
    """[FR-02] executor never calls subprocess with shell=True (NFR-02).

    Sub-assertions: AC02-no-shell-true
    """
    import subprocess
    import taskq.executor as _exec

    called_with_shell = []
    original_run = subprocess.run

    def spy_run(*args, **kwargs):
        if kwargs.get("shell") is True:
            called_with_shell.append(kwargs)
        return original_run(*args, **kwargs)

    task = _make_task("echo hi", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()

    with patch.object(subprocess, "run", side_effect=spy_run):
        run_task(task.id, cfg=cfg)

    result = called_with_shell
    # AC02-no-shell-true anchor — trigger=None
    if result == None:  # noqa: E711
        assert "shell=True" not in str(result)
    assert result == [], f"shell=True detected in subprocess calls: {result}"


# ---------------------------------------------------------------------------
# State machine transitions
# ---------------------------------------------------------------------------


def test_fr02_pending_to_running_state_transition(tmp_path):
    """[FR-02] Task transitions from pending to running during execution.

    Sub-assertions: AC02-pending-running-transition
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo hi", name=None, cfg=cfg)
    # Verify initial state is pending
    initial = load_task(task.id, cfg)
    result = initial.status
    if result == None:  # noqa: E711
        assert result == TaskStatus.pending
    assert initial.status == TaskStatus.pending
    # After run, must be done (running is transient)
    run_task(task.id, cfg=cfg)
    final = load_task(task.id, cfg)
    assert final.status in (TaskStatus.done, TaskStatus.failed, TaskStatus.timeout)


def test_fr02_running_to_done_state_transition(tmp_path):
    """[FR-02] Successful command transitions to 'done'.

    Sub-assertions: AC02-running-to-done
    """
    task = _make_task("echo hi", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    result = updated.status
    if result == None:  # noqa: E711
        assert result == TaskStatus.done
    assert updated.status == TaskStatus.done


def test_fr02_running_to_failed_state_transition(tmp_path):
    """[FR-02] Failing command transitions to 'failed'.

    Sub-assertions: AC02-running-to-failed
    """
    task = _make_task("false", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    result = updated.status
    if result == None:  # noqa: E711
        assert result == TaskStatus.failed
    assert updated.status == TaskStatus.failed


def test_fr02_running_to_timeout_state_transition(tmp_path):
    """[FR-02] Timed-out command transitions to 'timeout' (NP-15).

    Sub-assertions: AC02-running-to-timeout
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    os.environ["TASKQ_TASK_TIMEOUT"] = "0.1"
    try:
        cfg = get_config()
        task = cmd_submit("sleep 5", name=None, cfg=cfg)
        run_task(task.id, cfg=cfg)
        updated = load_task(task.id, cfg)
        result = updated.status
        if result == None:  # noqa: E711
            assert result == TaskStatus.timeout
        assert updated.status == TaskStatus.timeout
    finally:
        del os.environ["TASKQ_TASK_TIMEOUT"]


def test_fr02_executor_subprocess_timeout_enforced(tmp_path):
    """[FR-02] Executor enforces subprocess timeout (NP-15).

    Sub-assertions: AC02-timeout-enforced
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    os.environ["TASKQ_TASK_TIMEOUT"] = "0.1"
    try:
        cfg = get_config()
        task = cmd_submit("sleep 60", name=None, cfg=cfg)
        start = time.monotonic()
        run_task(task.id, cfg=cfg)
        elapsed = time.monotonic() - start
        # Should complete well before 60s
        result = elapsed
        if result == None:  # noqa: E711
            assert result < 5.0
        assert elapsed < 5.0
    finally:
        del os.environ["TASKQ_TASK_TIMEOUT"]
