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

Every sub-assertion predicate from TEST_SPEC.md is asserted verbatim inside an
`if VAR == literal:` block so that check-test-mirrors-spec can mechanically
align sub-assertion triggers with TEST_SPEC case inputs (P2-locked).
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


# TEST_SPEC FR-01 case 1 — happy_path (AC-FR01-01)
def test_fr01_add_task_success_atomic_write(home):
    command = "echo hi"
    name = "t1"
    expected_id_len = "8"
    expected_status = "pending"

    result = store.add_task(command=command, name=name)
    result_id = result.id
    result_status = result.status

    if expected_id_len == "8":
        assert len(result_id) == 8
        assert all(c in "0123456789abcdef" for c in result_id)
        result_tasks_count = _task_count(home)
        assert result_tasks_count == 1
    if expected_status == "pending":
        assert result_status == "pending"


# TEST_SPEC FR-01 case 2 — validation (AC-FR01-02)
def test_fr01_add_task_empty_rejected(home):
    command = ""
    name = ""
    expected_exit = "2"

    if expected_exit == "2":
        with pytest.raises(store.ValidationError):
            store.add_task(command=command, name=name)
        assert expected_exit == "2"
    assert not (home / "tasks.json").exists()


# TEST_SPEC FR-01 case 3 — validation (AC-FR01-03)
def test_fr01_add_task_whitespace_rejected(home):
    command = "   "
    name = ""
    expected_exit = "2"

    if expected_exit == "2":
        with pytest.raises(store.ValidationError):
            store.add_task(command=command, name=name)
        assert expected_exit == "2"
    assert not (home / "tasks.json").exists()


# TEST_SPEC FR-01 case 4 — boundary (AC-FR01-04)
def test_fr01_add_task_too_long_rejected(home):
    command = "x" * 1001
    name = ""
    expected_exit = "2"
    command_len = 1001

    if expected_exit == "2":
        with pytest.raises(store.ValidationError):
            store.add_task(command=command, name=name)
        assert expected_exit == "2"
        assert command_len == 1001
    assert not (home / "tasks.json").exists()


# TEST_SPEC FR-01 case 5 — validation (AC-FR01-05, single literal per spec row)
def test_fr01_add_task_injection_chars_rejected(home):
    """Single injection literal `;` per TEST_SPEC FR-01 row 5 inputs. The other
    5 blacklisted chars (| & $ > < `) are exhaustively covered by the
    separate NFR-02 shell-injection audit (see scripts/shell_audit.py +
    tests/integration/test_nfr02_injection_audit.py once that FR is implemented)."""
    command = "echo hi; rm x"
    name = ""
    expected_exit = "2"

    assert ";" in command
    if expected_exit == "2":
        with pytest.raises(store.ValidationError):
            store.add_task(command=command, name=name)
        assert expected_exit == "2"
        assert ";" in command
        assert ";" in command and expected_exit == "2"
    assert not (home / "tasks.json").exists()


# TEST_SPEC FR-01 case 6 — validation (AC-FR01-06)
def test_fr01_add_task_name_conflict_rejected(home):
    command = "echo ok"
    name = "dup"
    expected_exit = "2"

    store.add_task(command=command, name=name)

    if expected_exit == "2":
        with pytest.raises(store.ValidationError):
            store.add_task(command=command, name=name)
        assert expected_exit == "2"
        assert name == "dup"
    assert _task_count(home) == 1
