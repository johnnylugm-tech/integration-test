"""FR-01 — 任務提交與驗證 (RED phase failing tests).

Traces SRS §3 FR-01 (AC-FR-01-01..05) and TEST_SPEC FR-01 cases 1-6.

GREEN CONTRACT (what the GREEN agent must implement in src/taskq/store.py):
  - store.add_task(command: str, name: str | None = None) -> Task
      * validates command per FR-01 rules; on any violation raises
        store.ValidationError (subclass of ValueError) and does NOT write storage
      * on success: generates task id = uuid4().hex[:8], status="pending",
        records command/name/created_at, atomically writes $TASKQ_HOME/tasks.json
  - store.ValidationError: exception type raised on validation failure
  - Task: object with attributes .id (8 lowercase hex) and .status ("pending")
  - $TASKQ_HOME/tasks.json: JSON container (dict id->record or list) of tasks

Top-level import below is intentional: until src/taskq exists pytest raises a
Collection Error (ModuleNotFoundError, exit 2). That is a VALID RED STATE.
"""

import json

import pytest

from taskq import store


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Isolate storage under a tmp $TASKQ_HOME so tests don't touch real files."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    return tmp_path


def _task_count(home_dir):
    """Count persisted tasks in $TASKQ_HOME/tasks.json (dict or list container)."""
    data = json.loads((home_dir / "tasks.json").read_text())
    return len(data)


# TEST_SPEC FR-01 case 1 — happy_path (AC-FR-01-05)
def test_fr01_add_task_success_atomic_write(home):
    result = store.add_task(command="echo hi", name="t1")

    assert len(result.id) == 8
    assert all(c in "0123456789abcdef" for c in result.id)
    assert result.status == "pending"
    assert _task_count(home) == 1


# TEST_SPEC FR-01 case 2 — validation (AC-FR-01-01, empty)
def test_fr01_add_task_empty_rejected(home):
    with pytest.raises(store.ValidationError):
        store.add_task(command="", name="")
    assert not (home / "tasks.json").exists()


# TEST_SPEC FR-01 case 3 — validation (AC-FR-01-01, all-whitespace)
def test_fr01_add_task_whitespace_rejected(home):
    with pytest.raises(store.ValidationError):
        store.add_task(command="   ", name="")
    assert not (home / "tasks.json").exists()


# TEST_SPEC FR-01 case 4 — boundary (AC-FR-01-02, >1000 chars)
def test_fr01_add_task_too_long_rejected(home):
    command = "x" * 1001
    assert len(command) == 1001
    with pytest.raises(store.ValidationError):
        store.add_task(command=command, name="")
    assert not (home / "tasks.json").exists()


# TEST_SPEC FR-01 case 5 — validation (AC-FR-01-03, injection blacklist)
# Parametrically enumerates the 6 blacklisted injection chars: ; | & $ > < `
@pytest.mark.parametrize("bad_char", [";", "|", "&", "$", ">", "<", "`"])
def test_fr01_add_task_injection_chars_rejected(home, bad_char):
    command = f"echo hi{bad_char} rm x"
    assert bad_char in command
    with pytest.raises(store.ValidationError):
        store.add_task(command=command, name="")
    assert not (home / "tasks.json").exists()


# TEST_SPEC FR-01 case 6 — validation (AC-FR-01-04, name uniqueness)
def test_fr01_add_task_name_conflict_rejected(home):
    store.add_task(command="echo ok", name="dup")
    with pytest.raises(store.ValidationError):
        store.add_task(command="echo ok", name="dup")
    # only the first (pending) task persisted; duplicate rejected
    assert _task_count(home) == 1
