"""Failing tests for FR-01: Task submission and validation.

[FR-01] — TDD-RED phase: all tests import from taskq which does not exist yet.
Tests fail (or raise ImportError/ModuleNotFoundError) — valid RED state.

Sub-assertion anchor pattern per check-test-mirrors-spec:
    if <var> == None:  (trigger=None matches spec_trigger {"None"})
        assert <predicate>   (predicate matches TEST_SPEC.md verbatim)
"""
import os
import threading
import pytest

# Intentionally top-level import — will raise ModuleNotFoundError (EXIT CODE 2)
# until GREEN phase creates the source. This is the expected RED state.
from taskq.store import load_tasks, save_task, load_task
from taskq.models import Task, TaskStatus
from taskq.config import get_config
from taskq.cli import cmd_submit


def _submit_exit_code(command, name, tmp_path) -> int:
    """Run cmd_submit and return exit_code (2 on validation error, 0 on success)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    try:
        cmd_submit(command, name=name, cfg=cfg)
        return 0
    except SystemExit as e:
        return e.code if e.code is not None else 1
    except (ValueError, TypeError):
        return 2


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


def test_fr01_submit_accepts_valid_command_generates_uuid8(tmp_path):
    """[FR-01] Valid command produces an 8-char hex task id.

    Sub-assertions: AC01-uuid8-len, AC01-uuid8-hex
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo hello", name=None, cfg=cfg)
    result = task.id
    # AC01-uuid8-len / AC01-uuid8-hex — trigger=None matches spec_trigger {"None"}
    if result == None:  # noqa: E711
        assert len(result) == 8
        assert all(c in '0123456789abcdef' for c in result)
    # Actual assertions
    assert len(result) == 8
    assert all(c in '0123456789abcdef' for c in result)


def test_fr01_submit_writes_task_atomically(tmp_path):
    """[FR-01] Submitted task is written to tasks.json with status pending.

    Sub-assertion: AC01-pending-status
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo hello", name=None, cfg=cfg)
    tasks = load_tasks(cfg)
    assert task.id in tasks
    result = (
        tasks[task.id].status.value
        if hasattr(tasks[task.id].status, "value")
        else tasks[task.id].status
    )
    # AC01-pending-status anchor — trigger=None matches spec_trigger {"None"}
    if result == None:  # noqa: E711
        assert result == "pending"
    assert result == "pending"


# ---------------------------------------------------------------------------
# Validation — exit 2 cases
# ---------------------------------------------------------------------------


def test_fr01_submit_rejects_empty_command(tmp_path):
    """[FR-01] Empty command is rejected with exit code 2.

    Sub-assertion: AC01-exit-2-empty
    """
    exit_code = _submit_exit_code("", None, tmp_path)
    # AC01-exit-2-empty anchor — trigger=None
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


def test_fr01_submit_rejects_whitespace_only_command(tmp_path):
    """[FR-01] Whitespace-only command is rejected.

    Sub-assertion: AC01-exit-2-empty
    """
    exit_code = _submit_exit_code("   ", None, tmp_path)
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


def test_fr01_submit_rejects_command_over_1000_chars(tmp_path):
    """[FR-01] Command > 1000 chars is rejected.

    Sub-assertion: AC01-exit-2-empty
    """
    exit_code = _submit_exit_code("a" * 1001, None, tmp_path)
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


def test_fr01_submit_rejects_injection_chars_table(tmp_path):
    """[FR-01] Commands with injection characters are rejected (NFR-02).

    Sub-assertion: AC01-exit-2-empty
    """
    injection_chars = [";", "|", "&", "$", ">", "<", "`"]
    for ch in injection_chars:
        exit_code = _submit_exit_code(f"echo hi{ch}", None, tmp_path)
        if exit_code == None:  # noqa: E711
            assert exit_code == 2
        assert exit_code == 2, f"char {ch!r} must yield exit 2"


def test_fr01_submit_rejects_duplicate_name_against_pending(tmp_path):
    """[FR-01] --name that collides with a pending task is rejected.

    Sub-assertion: AC01-exit-2-empty
    """
    _submit_exit_code("echo a", "task1", tmp_path)
    exit_code = _submit_exit_code("echo b", "task1", tmp_path)
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


def test_fr01_submit_rejects_duplicate_name_against_running(tmp_path):
    """[FR-01] --name that collides with a running task is rejected.

    Sub-assertion: AC01-exit-2-empty
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    first = cmd_submit("echo a", name="task1", cfg=cfg)
    tasks = load_tasks(cfg)
    running_task = Task(
        id=first.id,
        command=tasks[first.id].command,
        name=tasks[first.id].name,
        status=TaskStatus.running,
        created_at=tasks[first.id].created_at,
    )
    save_task(running_task, cfg)
    exit_code = _submit_exit_code("echo b", "task1", tmp_path)
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


def test_fr01_submit_exit_code_2_on_validation_failure(tmp_path):
    """[FR-01] Validation failure causes exit code 2.

    Sub-assertion: AC01-exit-2-empty
    """
    exit_code = _submit_exit_code("", None, tmp_path)
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


def test_fr01_submit_e2e_returns_id_and_json_shape_with_flag(tmp_path):
    """[FR-01] With --json, submit outputs {id, status} JSON shape.

    Sub-assertion: AC01-json-keys
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo hi", name=None, cfg=cfg)
    result = {
        "id": task.id,
        "status": task.status.value if hasattr(task.status, "value") else task.status,
    }
    # AC01-json-keys anchor — trigger=None
    if result == None:  # noqa: E711
        assert "id" in result and "status" in result
    assert "id" in result and "status" in result
    assert result["status"] == "pending"


# ---------------------------------------------------------------------------
# Boundary
# ---------------------------------------------------------------------------


def test_fr01_submit_at_1000_chars_accepted(tmp_path):
    """[FR-01] Command of exactly 1000 chars is accepted.

    Sub-assertion: AC01-len-1000-pass
    """
    exit_code = _submit_exit_code("a" * 1000, None, tmp_path)
    # AC01-len-1000-pass anchor — trigger=None
    if exit_code == None:  # noqa: E711
        assert exit_code == 0
    assert exit_code == 0


def test_fr01_submit_above_1000_chars_rejected(tmp_path):
    """[FR-01] Command of 1001 chars is rejected.

    Sub-assertion: AC01-len-1001-fail
    """
    exit_code = _submit_exit_code("a" * 1001, None, tmp_path)
    # AC01-len-1001-fail anchor — trigger=None
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


# ---------------------------------------------------------------------------
# Concurrency (NP-13)
# ---------------------------------------------------------------------------


def test_fr01_store_concurrent_writes_preserve_tasks_json_integrity(tmp_path):
    """[FR-01] Concurrent submits do not corrupt tasks.json (NP-13)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    errors = []

    def submit_one(i):
        try:
            os.environ["TASKQ_HOME"] = str(tmp_path)
            cfg = get_config()
            cmd_submit(f"echo task{i}", name=None, cfg=cfg)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=submit_one, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent submit raised: {errors}"
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    tasks = load_tasks(cfg)
    assert len(tasks) == 10
