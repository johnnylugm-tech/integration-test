import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

from taskq import executor, store

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

    _run_taskq(home, "run", done_id, env_extra={"TASKQ_TASK_TIMEOUT": "1"})  # noqa: F841  side-effecting: transitions task to done
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

    _run_taskq(home, "run", fail_id, env_extra={"TASKQ_TASK_TIMEOUT": "1"})  # noqa: F841  side-effecting: transitions task to failed
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

    _run_taskq(home, "run", time_id, env_extra={"TASKQ_TASK_TIMEOUT": "1"})  # noqa: F841  side-effecting: transitions task to timeout
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


# ── In-process unit tests (coverage) ─────────────────────────────────────
# The subprocess-based tests above do not contribute to pytest-cov measurement
# (subprocess execution is not tracked). These tests import executor and store
# directly and call their helpers in-process so coverage of
# 03-development/src/taskq/{executor,store}.py is measured.


# ── executor._now_iso ─────────────────────────────────────────────────────


def test_unit_now_iso_format() -> None:
    ts = executor._now_iso()
    # parseable as ISO 8601 with trailing Z
    assert ts.endswith("Z")
    datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


# ── executor._run_subprocess ──────────────────────────────────────────────


def test_unit_run_subprocess_done() -> None:
    exit_code, stdout_tail, stderr_tail, duration_ms, status = executor._run_subprocess(
        "echo done", 5.0
    )
    assert status == "done"
    assert exit_code == 0
    assert stdout_tail.strip() == "done"
    assert stderr_tail == ""
    assert duration_ms >= 0


def test_unit_run_subprocess_failed() -> None:
    exit_code, stdout_tail, stderr_tail, duration_ms, status = executor._run_subprocess(
        f"{sys.executable} -c \"import sys; sys.stderr.write('oops'); sys.exit(2)\"",
        5.0,
    )
    assert status == "failed"
    assert exit_code == 2
    assert "oops" in stderr_tail
    assert duration_ms >= 0


def test_unit_run_subprocess_timeout() -> None:
    exit_code, stdout_tail, stderr_tail, duration_ms, status = executor._run_subprocess(
        f"{sys.executable} -c \"import time; time.sleep(5)\"",
        0.5,
    )
    assert status == "timeout"
    assert exit_code is None
    assert duration_ms >= 0


def test_unit_run_subprocess_stdout_tail_truncation() -> None:
    # produce more than 2000 chars of stdout; expect tail to keep last 2000
    code = (
        "import sys; "
        "sys.stdout.write('a' * 2500)"
    )
    exit_code, stdout_tail, stderr_tail, _duration_ms, status = executor._run_subprocess(
        f"{sys.executable} -c {shlex.quote(code)}", 5.0
    )
    assert status == "done"
    assert exit_code == 0
    assert len(stdout_tail) == 2000
    assert stdout_tail == "a" * 2000


# ── executor.execute_task ────────────────────────────────────────────────


def _write_pending_task(home: Path, task_id: str, command: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    payload = {
        task_id: {
            "id": task_id,
            "command": command,
            "name": None,
            "status": "pending",
            "created_at": "2026-07-10T00:00:00Z",
        }
    }
    (home / "tasks.json").write_text(json.dumps(payload))


def test_unit_execute_task_done_writes_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    # Reset memoised home
    store._HOME = None
    _write_pending_task(tmp_path, "t1", "echo hello")
    status = executor.execute_task("t1", "echo hello", 5.0)
    assert status == "done"
    saved = json.loads((tmp_path / "tasks.json").read_text())
    assert saved["t1"]["status"] == "done"
    assert saved["t1"]["exit_code"] == 0
    assert saved["t1"]["finished_at"]
    assert "hello" in saved["t1"]["stdout_tail"]


def test_unit_execute_task_failed_writes_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    store._HOME = None
    code = "import sys; sys.exit(3)"
    cmd = f"{sys.executable} -c {shlex.quote(code)}"
    _write_pending_task(tmp_path, "t2", cmd)
    status = executor.execute_task("t2", cmd, 5.0)
    assert status == "failed"
    saved = json.loads((tmp_path / "tasks.json").read_text())
    assert saved["t2"]["status"] == "failed"
    assert saved["t2"]["exit_code"] == 3
    assert saved["t2"]["finished_at"]


def test_unit_execute_task_timeout_writes_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    store._HOME = None
    code = "import time; time.sleep(5)"
    cmd = f"{sys.executable} -c {shlex.quote(code)}"
    _write_pending_task(tmp_path, "t3", cmd)
    status = executor.execute_task("t3", cmd, 0.5)
    assert status == "timeout"
    saved = json.loads((tmp_path / "tasks.json").read_text())
    assert saved["t3"]["status"] == "timeout"
    assert saved["t3"]["exit_code"] is None
    assert saved["t3"]["finished_at"]


# ── executor.run_all ─────────────────────────────────────────────────────


def test_unit_run_all_no_pending_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    store._HOME = None
    # Write a tasks file with no pending entries
    (tmp_path / "tasks.json").write_text(
        json.dumps(
            {
                "x1": {
                    "id": "x1",
                    "command": "echo",
                    "name": None,
                    "status": "done",
                    "created_at": "2026-07-10T00:00:00Z",
                }
            }
        )
    )
    results = executor.run_all(timeout=5.0, max_workers=2)
    assert results == {}


def test_unit_run_all_executes_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    store._HOME = None
    tasks = {}
    for i in range(3):
        tid = f"p{i}"
        tasks[tid] = {
            "id": tid,
            "command": f"echo {tid}",
            "name": None,
            "status": "pending",
            "created_at": "2026-07-10T00:00:00Z",
        }
    (tmp_path / "tasks.json").write_text(json.dumps(tasks))

    results = executor.run_all(timeout=5.0, max_workers=2)
    assert set(results) == {"p0", "p1", "p2"}
    assert all(s == "done" for s in results.values())

    saved = json.loads((tmp_path / "tasks.json").read_text())
    for tid in ("p0", "p1", "p2"):
        assert saved[tid]["status"] == "done"
        assert saved[tid]["exit_code"] == 0
        assert saved[tid]["finished_at"]


def test_unit_run_all_skips_non_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    store._HOME = None
    # Only one pending; others are already done
    tasks = {
        "p0": {
            "id": "p0",
            "command": "echo hi",
            "name": None,
            "status": "pending",
            "created_at": "2026-07-10T00:00:00Z",
        },
        "x1": {
            "id": "x1",
            "command": "echo x",
            "name": None,
            "status": "done",
            "created_at": "2026-07-10T00:00:00Z",
        },
    }
    (tmp_path / "tasks.json").write_text(json.dumps(tasks))
    results = executor.run_all(timeout=5.0, max_workers=2)
    assert set(results) == {"p0"}


# ── store.update_task ────────────────────────────────────────────────────


def test_unit_update_task_existing_entry(tmp_path: Path) -> None:
    # Set HOME directly (avoids env-var race with other tests)
    store._HOME = tmp_path
    payload = {
        "ab": {
            "id": "ab",
            "command": "echo",
            "name": None,
            "status": "pending",
            "created_at": "2026-07-10T00:00:00Z",
        }
    }
    (tmp_path / "tasks.json").write_text(json.dumps(payload))
    store.update_task("ab", status="running")
    after = json.loads((tmp_path / "tasks.json").read_text())
    assert after["ab"]["status"] == "running"
    assert after["ab"]["command"] == "echo"


def test_unit_update_task_missing_file_no_write(tmp_path: Path) -> None:
    store._HOME = tmp_path
    # No tasks.json file exists; update_task should be a no-op
    store.update_task("missing", status="running")
    assert not (tmp_path / "tasks.json").exists()


# ── store.save_tasks / load_tasks ────────────────────────────────────────


def test_unit_save_tasks_creates_file(tmp_path: Path) -> None:
    store._HOME = tmp_path
    store.save_tasks({"k": {"id": "k", "command": "echo"}})
    assert (tmp_path / "tasks.json").exists()
    assert not (tmp_path / "tasks.json.tmp").exists()
    payload = json.loads((tmp_path / "tasks.json").read_text())
    assert payload == {"k": {"id": "k", "command": "echo"}}


def test_unit_save_tasks_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "dir"
    store._HOME = nested
    store.save_tasks({"k": {"id": "k"}})
    assert (nested / "tasks.json").exists()


def test_unit_load_tasks_missing_returns_empty(tmp_path: Path) -> None:
    store._HOME = tmp_path
    assert store.load_tasks() == {}


def test_unit_load_tasks_existing_returns_dict(tmp_path: Path) -> None:
    store._HOME = tmp_path
    payload = {"k": {"id": "k", "command": "echo"}}
    (tmp_path / "tasks.json").write_text(json.dumps(payload))
    assert store.load_tasks() == payload

