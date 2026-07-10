import json
import os
import re
import subprocess
import sys
from pathlib import Path

import taskq.cli  # noqa: F401


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


def _seed_task(home: Path, *, task_id: str, name: str, status: str) -> dict[str, dict[str, object]]:
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
    return tasks


def test_fr01_empty_command_exit2(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"

    result = _run_taskq(home, "submit", "")

    assert result.returncode == 2
    assert result.stderr.strip()
    assert result.stdout == ""
    _assert_no_tasks_written(home)


def test_fr01_command_too_long_exit2(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    command = "x" * 1001

    result = _run_taskq(home, "submit", command)

    assert result.returncode == 2
    assert result.stderr.strip()
    assert result.stdout == ""
    _assert_no_tasks_written(home)


def test_fr01_injection_char_exit2(tmp_path: Path) -> None:
    for char in [";", "|", "&", "$", ">", "<", "`"]:
        home = tmp_path / f"taskq-home-{ord(char)}"

        result = _run_taskq(home, "submit", f"echo hi{char} rm x")

        assert result.returncode == 2
        assert result.stderr.strip()
        assert result.stdout == ""
        _assert_no_tasks_written(home)


def test_fr01_duplicate_name_exit2(tmp_path: Path) -> None:
    for status in ["pending", "running"]:
        home = tmp_path / f"taskq-home-{status}"
        task_id = "12345678" if status == "pending" else "87654321"
        existing = _seed_task(home, task_id=task_id, name="dup", status=status)

        result = _run_taskq(home, "submit", "echo hi", "--name", "dup")

        assert result.returncode == 2
        assert result.stderr.strip()
        assert result.stdout == ""
        assert _load_tasks(home) == existing


def test_fr01_valid_submit_pending(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"

    result = _run_taskq(home, "submit", "echo hi", "--name", "alpha")

    assert result.returncode == 0
    task_id = result.stdout.strip()
    assert ID_PATTERN.fullmatch(task_id)
    assert result.stderr == ""

    tasks = _load_tasks(home)
    assert list(tasks) == [task_id]
    task = tasks[task_id]
    assert task["id"] == task_id
    assert task["command"] == "echo hi"
    assert task["name"] == "alpha"
    assert task["status"] == "pending"
    assert task["created_at"]


def test_fr01_json_output_single_line(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"

    result = _run_taskq(home, "--json", "submit", "echo hi")

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
