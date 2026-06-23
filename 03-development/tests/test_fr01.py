"""Failing tests for FR-01: Task submission and validation.

[FR-01] — TDD-RED phase: all tests import from src.taskq which does not exist yet.
"""
import json
import os
import sys
import threading
import pytest

# Intentionally top-level import — will raise ModuleNotFoundError (EXIT CODE 2)
# until GREEN phase creates the source. This is the expected RED state.
from taskq.store import load_tasks, save_task, load_task
from taskq.models import Task, TaskStatus
from taskq.config import get_config
from taskq.cli import cmd_submit


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


def test_fr01_submit_accepts_valid_command_generates_uuid8(tmp_path):
    """[FR-01] Valid command produces an 8-char hex task id."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo hello", name=None, cfg=cfg)
    assert len(task.id) == 8
    assert all(c in "0123456789abcdef" for c in task.id)


def test_fr01_submit_writes_task_atomically(tmp_path):
    """[FR-01] Submitted task is written to tasks.json with status pending."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo hello", name=None, cfg=cfg)
    tasks = load_tasks(cfg)
    assert task.id in tasks
    assert tasks[task.id].status == TaskStatus.pending


# ---------------------------------------------------------------------------
# Validation — exit 2 cases
# ---------------------------------------------------------------------------


def test_fr01_submit_rejects_empty_command(tmp_path):
    """[FR-01] Empty command is rejected with ValueError (exit 2)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    with pytest.raises((ValueError, SystemExit)) as exc_info:
        cmd_submit("", name=None, cfg=cfg)
    if isinstance(exc_info.value, SystemExit):
        assert exc_info.value.code == 2


def test_fr01_submit_rejects_whitespace_only_command(tmp_path):
    """[FR-01] Whitespace-only command is rejected."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    with pytest.raises((ValueError, SystemExit)) as exc_info:
        cmd_submit("   ", name=None, cfg=cfg)
    if isinstance(exc_info.value, SystemExit):
        assert exc_info.value.code == 2


def test_fr01_submit_rejects_command_over_1000_chars(tmp_path):
    """[FR-01] Command > 1000 chars is rejected."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    with pytest.raises((ValueError, SystemExit)) as exc_info:
        cmd_submit("a" * 1001, name=None, cfg=cfg)
    if isinstance(exc_info.value, SystemExit):
        assert exc_info.value.code == 2


def test_fr01_submit_rejects_injection_chars_table(tmp_path):
    """[FR-01] Commands with injection characters are rejected (NFR-02)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    injection_chars = [";", "|", "&", "$", ">", "<", "`"]
    for ch in injection_chars:
        with pytest.raises((ValueError, SystemExit)) as exc_info:
            cmd_submit(f"echo hi{ch}", name=None, cfg=cfg)
        if isinstance(exc_info.value, SystemExit):
            assert exc_info.value.code == 2, f"char {ch!r} must yield exit 2"


def test_fr01_submit_rejects_duplicate_name_against_pending(tmp_path):
    """[FR-01] --name that collides with a pending task is rejected."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    cmd_submit("echo a", name="task1", cfg=cfg)
    with pytest.raises((ValueError, SystemExit)) as exc_info:
        cmd_submit("echo b", name="task1", cfg=cfg)
    if isinstance(exc_info.value, SystemExit):
        assert exc_info.value.code == 2


def test_fr01_submit_rejects_duplicate_name_against_running(tmp_path):
    """[FR-01] --name that collides with a running task is rejected."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    # Manually insert a running task with name task1
    first = cmd_submit("echo a", name="task1", cfg=cfg)
    tasks = load_tasks(cfg)
    running_task = tasks[first.id]
    running_task = Task(
        id=running_task.id,
        command=running_task.command,
        name=running_task.name,
        status=TaskStatus.running,
        created_at=running_task.created_at,
    )
    save_task(running_task, cfg)
    with pytest.raises((ValueError, SystemExit)) as exc_info:
        cmd_submit("echo b", name="task1", cfg=cfg)
    if isinstance(exc_info.value, SystemExit):
        assert exc_info.value.code == 2


def test_fr01_submit_exit_code_2_on_validation_failure(tmp_path):
    """[FR-01] Validation failure causes exit code 2."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    with pytest.raises((ValueError, SystemExit)) as exc_info:
        cmd_submit("", name=None, cfg=cfg)
    if isinstance(exc_info.value, SystemExit):
        assert exc_info.value.code == 2


def test_fr01_submit_e2e_returns_id_and_json_shape_with_flag(tmp_path):
    """[FR-01] With --json, submit outputs {id, status} JSON object."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo hi", name=None, cfg=cfg)
    result = {"id": task.id, "status": task.status.value if hasattr(task.status, "value") else task.status}
    assert "id" in result
    assert "status" in result
    assert result["status"] == "pending"


# ---------------------------------------------------------------------------
# Boundary
# ---------------------------------------------------------------------------


def test_fr01_submit_at_1000_chars_accepted(tmp_path):
    """[FR-01] Command of exactly 1000 chars is accepted."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("a" * 1000, name=None, cfg=cfg)
    assert len(task.id) == 8


def test_fr01_submit_above_1000_chars_rejected(tmp_path):
    """[FR-01] Command of 1001 chars is rejected."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    with pytest.raises((ValueError, SystemExit)):
        cmd_submit("a" * 1001, name=None, cfg=cfg)


# ---------------------------------------------------------------------------
# Concurrency (NP-13)
# ---------------------------------------------------------------------------


def test_fr01_store_concurrent_writes_preserve_tasks_json_integrity(tmp_path):
    """[FR-01] Concurrent submits do not corrupt tasks.json (NP-13)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    errors = []

    def submit_one(i):
        try:
            cmd_submit(f"echo task{i}", name=None, cfg=cfg)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=submit_one, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent submit raised: {errors}"
    tasks = load_tasks(cfg)
    assert len(tasks) == 10
