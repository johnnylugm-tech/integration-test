"""TDD-RED tests for FR-02: Task Executor.

Per SPEC.md §3 FR-02 + TEST_SPEC.md §FR-02 (5 required function
names). These tests are intentionally written before the FR-02 source modules
exist. A pytest Collection Error from the standard top-level imports below is a
valid RED state.

Test isolation:
- TASKQ_HOME points at tmp_path for every test.
- subprocess.run is monkeypatched in execution tests, so no real external
  command is launched.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

# Top-level imports — ModuleNotFoundError is the EXPECTED RED state for FR-02.
from taskq import cli, executor
from taskq.executor import run_task
from taskq.models import Status, Task
from taskq.store import TaskStore


@pytest.fixture(autouse=True)
def isolate_taskq_home(tmp_path, monkeypatch):
    """Point TASKQ_HOME at a tmp dir so tests never touch a real task store."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))


def _status_value(status):
    return getattr(status, "value", status)


def _field(task, name):
    if isinstance(task, dict):
        return task[name]
    return getattr(task, name)


def _make_task(task_id="a0000000", command="echo hi", status=None):
    if status is None:
        status = Status.PENDING
    return Task(
        id=task_id,
        name=None,
        command=command,
        status=status,
        created_at="2026-07-11T00:00:00Z",
        exit_code=None,
        stdout_tail=None,
        stderr_tail=None,
        duration_ms=None,
        finished_at=None,
        cached=False,
    )


def _seed_tasks(home: Path, tasks: list[dict]) -> None:
    (home / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")


def _read_tasks(home: Path) -> list[dict]:
    return json.loads((home / "tasks.json").read_text(encoding="utf-8"))


def test_fr02_no_shell_true(tmp_path, monkeypatch):
    """FR-02 executes via shlex-split argv and never enables shell execution."""
    source_path = Path(__file__).parents[1] / "src" / "taskq" / "executor.py"
    assert source_path.read_text(encoding="utf-8").count("shell=True") == 0

    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "7.5")
    monkeypatch.setattr(executor.subprocess, "run", fake_run)

    result = run_task(_make_task(command='python -c "print(1)"'))

    assert calls, "run_task must call subprocess.run"
    args, kwargs = calls[0]
    assert args == ["python", "-c", "print(1)"]
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["timeout"] == pytest.approx(7.5)
    assert kwargs.get("shell") is not True
    assert _status_value(_field(result, "status")) == "done"


@pytest.mark.parametrize(
    "returncode, expected_status, expected_exit_code",
    [
        (0, "done", 0),
        (1, "failed", 1),
    ],
)
def test_fr02_status_transitions(monkeypatch, returncode, expected_status, expected_exit_code):
    """FR-02 maps exit 0/non-zero/TimeoutExpired to final task statuses."""

    def fake_run(args, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout="out", stderr="err")

    monkeypatch.setattr(executor.subprocess, "run", fake_run)

    result = run_task(_make_task(command="python -V"))

    assert _status_value(_field(result, "status")) == expected_status
    assert _field(result, "exit_code") == expected_exit_code
    assert _field(result, "finished_at")

    def fake_timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs["timeout"])

    monkeypatch.setattr(executor.subprocess, "run", fake_timeout)

    timeout_result = run_task(_make_task(task_id="b0000000", command="sleep 5"))

    assert _status_value(_field(timeout_result, "status")) == "timeout"
    assert _field(timeout_result, "finished_at")


def test_fr02_result_fields_present(monkeypatch):
    """FR-02 records exit_code/stdout_tail/stderr_tail/duration_ms/finished_at."""
    stdout = "O" * 2105 + "STDOUT_END"
    stderr = "E" * 2105 + "STDERR_END"

    def fake_run(args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(executor.subprocess, "run", fake_run)

    result = run_task(_make_task(command="python -V"))

    assert _field(result, "exit_code") == 0
    assert _field(result, "stdout_tail") == stdout[-2000:]
    assert _field(result, "stderr_tail") == stderr[-2000:]
    assert len(_field(result, "stdout_tail")) == 2000
    assert len(_field(result, "stderr_tail")) == 2000
    assert isinstance(_field(result, "duration_ms"), (int, float))
    assert _field(result, "duration_ms") >= 0
    assert _field(result, "finished_at")


def test_fr02_run_all_concurrent_lock(tmp_path, monkeypatch):
    """FR-02 run --all uses 4 workers and leaves tasks.json valid after writes."""
    monkeypatch.setenv("TASKQ_MAX_WORKERS", "4")
    tasks = [
        {
            "id": f"a000000{i}",
            "name": None,
            "command": "python -V",
            "status": "pending",
            "created_at": "2026-07-11T00:00:00Z",
        }
        for i in range(8)
    ]
    _seed_tasks(tmp_path, tasks)

    active = 0
    max_active = 0
    counter_lock = threading.Lock()

    def fake_run(args, **kwargs):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.03)
        with counter_lock:
            active -= 1
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(executor.subprocess, "run", fake_run)

    exit_code = cli.run_cmd(task_id=None, all_mode=True, cached=False, json_mode=False)

    assert exit_code == 0
    assert max_active > 1, "run --all must execute pending tasks concurrently"
    stored = _read_tasks(tmp_path)
    assert len(stored) == 8
    assert {task["id"] for task in stored} == {task["id"] for task in tasks}
    assert all(task["status"] == "done" for task in stored)
    assert all(task.get("finished_at") for task in stored)
    store = TaskStore()
    assert isinstance(getattr(store, "_lock", None), type(threading.Lock()))


def test_fr02_single_timeout_exit4(tmp_path, monkeypatch):
    """FR-02 single-task timeout stores timeout status and returns exit 4."""
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "1")
    task_id = "a0000000"
    _seed_tasks(
        tmp_path,
        [
            {
                "id": task_id,
                "name": None,
                "command": "sleep 5",
                "status": "pending",
                "created_at": "2026-07-11T00:00:00Z",
            }
        ],
    )

    def fake_timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs["timeout"])

    monkeypatch.setattr(executor.subprocess, "run", fake_timeout)

    exit_code = cli.run_cmd(task_id=task_id, all_mode=False, cached=False, json_mode=False)

    assert exit_code == 4
    stored = _read_tasks(tmp_path)
    assert len(stored) == 1
    assert stored[0]["id"] == task_id
    assert stored[0]["status"] == "timeout"
    assert stored[0].get("finished_at")
