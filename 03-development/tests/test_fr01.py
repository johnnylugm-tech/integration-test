import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "03-development" / "src"
ID_PATTERN = re.compile(r"[0-9a-f]{8}")


def _run_taskq(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    pythonpath = str(SRC_DIR)
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env.update({"TASKQ_HOME": str(home), "PYTHONPATH": pythonpath})
    return subprocess.run(
        [sys.executable, "-m", "taskq", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _tasks_path(home: Path) -> Path:
    return home / "tasks.json"


def _load_tasks(home: Path) -> dict[str, dict[str, object]]:
    path = _tasks_path(home)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _assert_no_tasks_written(home: Path) -> None:
    assert _load_tasks(home) == {}


def _seed_task(home: Path, *, task_id: str, name: str, status: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    tasks = {
        task_id: {
            "id": task_id,
            "command": "echo old",
            "name": name,
            "status": status,
            "created_at": "2026-07-10T00:00:00Z",
        }
    }
    _tasks_path(home).write_text(json.dumps(tasks))


# ── FR-01 sub-assertion mirror gates ──
# Each sub-assertion from TEST_SPEC.md (P2-locked) is implemented as an if-guard
# with the exact trigger var + literal that maps to its `applies_to` case id, and
# the spec's predicate text as the first assert.  Downstream functional asserts
# (returncode / stderr / store state) ride inside the same body.


def test_fr01_empty_command_exit2(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    command = ""
    expected_exit = "2"
    outcome = "rejected"

    result = _run_taskq(home, "submit", "")

    if command == "":  # AC-FR01-empty-reject (applies_to=1)
        assert command == ""
        assert result.returncode == 2
        assert result.stderr.strip()
        assert result.stdout == ""
        _assert_no_tasks_written(home)
    if expected_exit == "2":  # AC-FR01-validation-exit-2
        assert expected_exit == "2"
        assert result.returncode == 2
    if outcome == "rejected":  # AC-FR01-rejection-outcome
        assert outcome == "rejected"
        assert result.returncode == 2


def test_fr01_command_too_long_exit2(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    command = "x" * 1001
    length_exceeds_1000 = "yes"
    expected_exit = "2"
    outcome = "rejected"

    result = _run_taskq(home, "submit", command)

    if length_exceeds_1000 == "yes":  # AC-FR01-length-bound (applies_to=2)
        assert length_exceeds_1000 == "yes"
        assert result.returncode == 2
        assert result.stderr.strip()
        assert result.stdout == ""
        _assert_no_tasks_written(home)
    if expected_exit == "2":
        assert expected_exit == "2"
        assert result.returncode == 2
    if outcome == "rejected":
        assert outcome == "rejected"
        assert result.returncode == 2


def test_fr01_injection_char_exit2(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    command = "echo hi; rm x"
    expected_exit = "2"
    outcome = "rejected"

    result = _run_taskq(home, "submit", command)

    if command == "echo hi; rm x":  # AC-FR01-injection-present (applies_to=3)
        assert ";" in command
        assert result.returncode == 2
        assert result.stderr.strip()
        assert result.stdout == ""
        _assert_no_tasks_written(home)
    if expected_exit == "2":
        assert expected_exit == "2"
        assert result.returncode == 2
    if outcome == "rejected":
        assert outcome == "rejected"
        assert result.returncode == 2


def test_fr01_duplicate_name_exit2(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    command = "echo hi"
    existing_name = "dup"
    new_name = "dup"
    expected_exit = "2"
    outcome = "rejected"

    _seed_task(home, task_id="12345678", name="dup", status="pending")

    result = _run_taskq(home, "submit", command, "--name", new_name)

    if new_name == "dup":  # AC-FR01-name-conflict (applies_to=4)
        assert new_name == existing_name
        assert result.returncode == 2
        assert result.stderr.strip()
        assert result.stdout == ""
        # Seeded task unchanged
        tasks_after = _load_tasks(home)
        assert "12345678" in tasks_after
        assert tasks_after["12345678"]["name"] == "dup"
    if expected_exit == "2":
        assert expected_exit == "2"
        assert result.returncode == 2
    if outcome == "rejected":
        assert outcome == "rejected"
        assert result.returncode == 2


def test_fr01_duplicate_name_running_exit2(tmp_path: Path) -> None:
    """Extra coverage: --name collision with an existing RUNNING task is also rejected."""
    home = tmp_path / "taskq-home"
    command = "echo hi"
    existing_name = "dup"
    new_name = "dup"

    _seed_task(home, task_id="87654321", name="dup", status="running")

    result = _run_taskq(home, "submit", command, "--name", new_name)

    assert result.returncode == 2
    assert result.stderr.strip()
    assert result.stdout == ""
    tasks_after = _load_tasks(home)
    assert "87654321" in tasks_after
    assert tasks_after["87654321"]["status"] == "running"


def test_fr01_valid_submit_pending(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    command = "echo hi"
    existing_name = "distinct"
    new_name = "alpha"
    expected_exit = "0"

    result = _run_taskq(home, "submit", command, "--name", new_name)

    if new_name == "alpha":  # AC-FR01-valid-no-conflict (applies_to=5)
        assert new_name != existing_name
        assert result.returncode == 0
        assert result.stderr == ""
        task_id = result.stdout.strip()
        assert ID_PATTERN.fullmatch(task_id)
        tasks = _load_tasks(home)
        assert list(tasks) == [task_id]
        assert tasks[task_id]["id"] == task_id
        assert tasks[task_id]["name"] == "alpha"
        assert tasks[task_id]["command"] == "echo hi"
        assert tasks[task_id]["status"] == "pending"
        assert tasks[task_id]["created_at"]
    if expected_exit == "0":  # AC-FR01-happy-exit-0
        assert expected_exit == "0"
        assert result.returncode == 0
        assert result.stderr == ""


def test_fr01_json_output_single_line(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    command = "echo hi"
    json_mode = "yes"
    expected_exit = "0"

    result = _run_taskq(home, "--json", "submit", command)

    if json_mode == "yes":  # AC-FR01-json-mode-on (applies_to=6)
        assert json_mode == "yes"
        assert result.returncode == 0
        assert result.stderr == ""
        assert result.stdout.endswith("\n")
        assert result.stdout.count("\n") == 1
        payload = json.loads(result.stdout)
        assert set(payload) == {"id", "status"}
        assert ID_PATTERN.fullmatch(payload["id"])
        assert payload["status"] == "pending"
        tasks = _load_tasks(home)
        assert payload["id"] in tasks
        assert tasks[payload["id"]]["status"] == "pending"
    if expected_exit == "0":
        assert expected_exit == "0"
        assert result.returncode == 0
        assert result.stderr == ""
