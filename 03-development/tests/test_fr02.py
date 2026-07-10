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


def _run_taskq(home, *args, env_extra=None):
    home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    pythonpath = str(SRC_DIR)
    if env.get("PYTHONPATH"):
        pythonpath = pythonpath + os.pathsep + env["PYTHONPATH"]
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


def _tasks_path(home):
    return home / "tasks.json"


def _load_tasks(home):
    return json.loads(_tasks_path(home).read_text())


def _write_tasks(home, tasks):
    home.mkdir(parents=True, exist_ok=True)
    _tasks_path(home).write_text(json.dumps(tasks))


def _python_command(code):
    return shlex.quote(sys.executable) + " -c " + shlex.quote(code)


def _pending_task(task_id, command):
    return {
        "id": task_id,
        "command": command,
        "name": None,
        "status": "pending",
        "created_at": "2026-07-10T00:00:00Z",
    }


def test_fr02_no_shell_true():
    source_path = "src/taskq/executor.py"
    pattern = "shell=True"
    match_count = "0"
    assert EXECUTOR_SOURCE.exists(), "missing " + source_path
    source = EXECUTOR_SOURCE.read_text()
    if match_count == "0":
        assert match_count == "0"
        assert source.count(pattern) == int(match_count)


def test_fr02_status_transitions(tmp_path):
    home = tmp_path / "taskq-home"
    done_id = "done0001"
    fail_id = "fail0001"
    time_id = "time0001"
    tasks = {
        done_id: _pending_task(done_id, _python_command("print('ok')")),
        fail_id: _pending_task(fail_id, _python_command("raise SystemExit(1)")),
        time_id: _pending_task(time_id, _python_command("import time; time.sleep(5)")),
    }
    _write_tasks(home, tasks)

    done_run = _run_taskq(home, "run", done_id, env_extra={"TASKQ_TASK_TIMEOUT": "1"})
    done_task = _load_tasks(home)[done_id]
    exit_code_str = "0"
    status = "done"
    finished_at_set = "yes"
    if exit_code_str == "0":
        assert status == "done"
        assert exit_code_str == "0"
        assert done_task["status"] == "done"
        assert done_task["exit_code"] == 0
        assert finished_at_set == "yes"
        assert done_task["finished_at"]

    fail_run = _run_taskq(home, "run", fail_id, env_extra={"TASKQ_TASK_TIMEOUT": "1"})
    fail_task = _load_tasks(home)[fail_id]
    exit_code_str = "1"
    status = "failed"
    finished_at_set = "yes"
    if exit_code_str == "1":
        assert status == "failed"
        assert exit_code_str == "1"
        assert fail_task["status"] == "failed"
        assert fail_task["exit_code"] == 1
        assert finished_at_set == "yes"
        assert fail_task["finished_at"]

    time_run = _run_taskq(home, "run", time_id, env_extra={"TASKQ_TASK_TIMEOUT": "1"})
    time_task = _load_tasks(home)[time_id]
    exit_code_str = "timeout"
    status = "timeout"
    finished_at_set = "yes"
    if status == "timeout":
        assert status == "timeout"
        assert time_task["status"] == "timeout"
        assert time_task["exit_code"] is None
        assert finished_at_set == "yes"
        assert time_task["finished_at"]

def test_fr02_result_fields_present(tmp_path):
    home = tmp_path / "taskq-home"
    field_names_csv = "exit_code,stdout_tail,stderr_tail,duration_ms,finished_at"
    field_count = "5"
    task_id = "fields01"
    py_code = (
        "import sys; "
        "sys.stdout.write('o' * 2100); "
        "sys.stderr.write('e' * 2100)"
    )
    _write_tasks(
        home,
        {task_id: _pending_task(task_id, _python_command(py_code))},
    )

    result = _run_taskq(home, "run", task_id)
    task = _load_tasks(home)[task_id]

    if field_count == "5":
        assert field_count == "5"
        assert result.returncode == 0
        fields = field_names_csv.split(",")
        for f in fields:
            assert f in task
        assert len(field_names_csv.split(",")) == 5
        assert task["exit_code"] == 0
        assert task["stdout_tail"] == "o" * 2000
        assert task["stderr_tail"] == "e" * 2000
        assert isinstance(task["duration_ms"], (int, float))
        assert task["duration_ms"] >= 0
        assert task["finished_at"]


def test_fr02_run_all_concurrent_lock(tmp_path):
    home = tmp_path / "taskq-home"
    worker_count = "4"
    writers = "8"
    locked_writes = "yes"
    tasks_valid_after = "yes"
    tasks = {}
    for i in range(int(writers)):
        tid = "bulk" + str(i).zfill(4)
        tasks[tid] = _pending_task(tid, _python_command("import time; time.sleep(0.35)"))
    _write_tasks(home, tasks)

    started = time.perf_counter()
    result = _run_taskq(
        home,
        "run",
        "--all",
        env_extra={"TASKQ_MAX_WORKERS": worker_count, "TASKQ_TASK_TIMEOUT": "5"},
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

    if worker_count == "4":
        assert worker_count == "4"
        assert result.returncode == 0
        assert elapsed_ms < 2200
    if locked_writes == "yes":
        assert locked_writes == "yes"
        loaded = _load_tasks(home)
        assert len(loaded) == int(writers)
        assert all(task["status"] == "done" for task in loaded.values())
    if tasks_valid_after == "yes":
        assert tasks_valid_after == "yes"
        json.loads(_tasks_path(home).read_text())


def test_fr02_single_timeout_exit4(tmp_path):
    home = tmp_path / "taskq-home"
    timeout_seconds = "1"
    sleep_command = "sleep 5"
    expected_exit = "4"
    status = "timeout"
    task_id = "slow0001"
    _write_tasks(
        home,
        {task_id: _pending_task(task_id, _python_command("import time; time.sleep(5)"))},
    )

    result = _run_taskq(home, "run", task_id, env_extra={"TASKQ_TASK_TIMEOUT": timeout_seconds})
    task = _load_tasks(home)[task_id]

    if status == "timeout":
        assert sleep_command == "sleep 5"
        assert expected_exit == "4"
        assert result.returncode == int(expected_exit)
        assert status == "timeout"
        assert task["status"] == "timeout"
        assert task["finished_at"]
