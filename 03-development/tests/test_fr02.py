import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "03-development" / "src"
EXECUTOR_SOURCE = SRC_DIR / "taskq" / "executor.py"


def _run_taskq(
    home: Path, *args: str, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    pythonpath = str(SRC_DIR)
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env.update({"TASKQ_HOME": str(home), "PYTHONPATH": pythonpath})
    if env_extra:
        env.update(env_extra)
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
    return json.loads(_tasks_path(home).read_text())


def _write_tasks(home: Path, tasks: dict[str, dict[str, object]]) -> None:
    home.mkdir(parents=True, exist_ok=True)
    _tasks_path(home).write_text(json.dumps(tasks))


def _python_command(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def _pending_task(task_id: str, command: str) -> dict[str, object]:
    return {
        "id": task_id,
        "command": command,
        "name": None,
        "status": "pending",
        "created_at": "2026-07-10T00:00:00Z",
    }


def test_fr02_no_shell_true() -> None:
    source_path = "src/taskq/executor.py"
    pattern = "shell=True"
    match_count = "0"

    if source_path == "src/taskq/executor.py":  # AC-FR02-no-shell-source
        assert EXECUTOR_SOURCE.exists(), f"missing {source_path}"
        source = EXECUTOR_SOURCE.read_text()
        assert source.count(pattern) == int(match_count)


def test_fr02_status_transitions(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    tasks = {
        "done0001": _pending_task("done0001", _python_command("print('ok')")),
        "fail0001": _pending_task("fail0001", _python_command("raise SystemExit(1)")),
        "time0001": _pending_task(
            "time0001", _python_command("import time; time.sleep(5)")
        ),
    }
    _write_tasks(home, tasks)

    cases = [
        ("done0001", "0", "done"),
        ("fail0001", "1", "failed"),
        ("time0001", "timeout", "timeout"),
    ]

    for task_id, exit_code_str, status in cases:
        _run_taskq(
            home,
            "run",
            task_id,
            env_extra={"TASKQ_TASK_TIMEOUT": "1"},
        )
        task = _load_tasks(home)[task_id]
        if exit_code_str == "0":  # AC-FR02-exit-zero + AC-FR02-done
            assert task["status"] == status == "done"
            assert task["exit_code"] == 0
        if exit_code_str == "1":  # AC-FR02-exit-nonzero + AC-FR02-failed
            assert task["status"] == status == "failed"
            assert task["exit_code"] == 1
        if exit_code_str == "timeout":  # AC-FR02-status-timeout
            assert task["status"] == status == "timeout"
            assert task["exit_code"] is None
        assert task["finished_at"]


def test_fr02_result_fields_present(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    field_names_csv = "exit_code,stdout_tail,stderr_tail,duration_ms,finished_at"
    field_count = "5"
    task_id = "fields01"
    _write_tasks(
        home,
        {
            task_id: _pending_task(
                task_id,
                _python_command(
                    "import sys; "
                    "sys.stdout.write('o' * 2100); "
                    "sys.stderr.write('e' * 2100)"
                ),
            )
        },
    )

    result = _run_taskq(home, "run", task_id)
    task = _load_tasks(home)[task_id]

    if field_count == "5":  # AC-FR02-fields-count-5
        assert result.returncode == 0
        for field in field_names_csv.split(","):
            assert field in task
    if len(field_names_csv.split(",")) == 5:  # AC-FR02-fields-csv-len
        assert task["exit_code"] == 0
        assert task["stdout_tail"] == "o" * 2000
        assert task["stderr_tail"] == "e" * 2000
        assert isinstance(task["duration_ms"], int | float)
        assert task["duration_ms"] >= 0
        assert task["finished_at"]


def test_fr02_run_all_concurrent_lock(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    worker_count = "4"
    writers = "8"
    locked_writes = "yes"
    tasks_valid_after = "yes"
    tasks = {
        f"bulk{i:04d}": _pending_task(
            f"bulk{i:04d}", _python_command("import time; time.sleep(0.35)")
        )
        for i in range(int(writers))
    }
    _write_tasks(home, tasks)

    started = time.perf_counter()
    result = _run_taskq(
        home,
        "run",
        "--all",
        env_extra={"TASKQ_MAX_WORKERS": worker_count, "TASKQ_TASK_TIMEOUT": "5"},
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

    if worker_count == "4":  # AC-FR02-worker-count
        assert result.returncode == 0
        assert elapsed_ms < 2200
    if locked_writes == "yes":  # AC-FR02-concurrent-locked
        loaded = _load_tasks(home)
        assert len(loaded) == int(writers)
        assert all(task["status"] == "done" for task in loaded.values())
    if tasks_valid_after == "yes":  # AC-FR02-concurrent-valid
        json.loads(_tasks_path(home).read_text())


def test_fr02_single_timeout_exit4(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    timeout_seconds = "1"
    sleep_command = "sleep 5"
    expected_exit = "4"
    status = "timeout"
    task_id = "slow0001"
    _write_tasks(
        home,
        {
            task_id: _pending_task(
                task_id, _python_command("import time; time.sleep(5)")
            )
        },
    )

    result = _run_taskq(
        home,
        "run",
        task_id,
        env_extra={"TASKQ_TASK_TIMEOUT": timeout_seconds},
    )
    task = _load_tasks(home)[task_id]

    if sleep_command == "sleep 5":  # AC-FR02-single-timeout-exit-4
        assert expected_exit == "4"
        assert result.returncode == int(expected_exit)
        assert task["status"] == status == "timeout"
        assert task["finished_at"]
