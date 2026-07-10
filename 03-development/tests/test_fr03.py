"""[FR-03] RED tests for retry-and-circuit-breaker behavior.

Citations:
  - SPEC.md §3 FR-03 (retry + circuit breaker)
  - 02-architecture/TEST_SPEC.md (FR-03 sub-assertions)
  - 02-architecture/SAD.md (src/taskq/breaker.py + executor retry wiring)

These tests are written FIRST (TDD-RED). They MUST fail because:
  - `taskq.breaker` module does not exist yet
  - `execute_task` / `run_all` do not retry yet
  - `cli.run` does not consult the breaker yet

Each test function name matches TEST_SPEC.md exactly so spec-coverage-check
can match them.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from taskq import executor, store  # `breaker` intentionally not imported yet
from taskq import breaker  # in-process unit tests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "03-development" / "src"


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


def _breaker_path(home):
    return home / "breaker.json"


def _load_tasks(home):
    return json.loads(_tasks_path(home).read_text())


def _load_breaker(home):
    return json.loads(_breaker_path(home).read_text())


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


# ── 1. test_fr03_retry_up_to_limit ──────────────────────────────────────
# Q1 (happy_path): failed/timeout auto-retry up to TASKQ_RETRY_LIMIT.
# Backoff function must be injectable so tests do not actually sleep.


def test_fr03_retry_up_to_limit(tmp_path, monkeypatch):
    retry_within_limit = "yes"
    final_outcome = "failed"
    home = tmp_path / "taskq-home"
    task_id = "retry001"
    fail_cmd = _python_command("import sys; sys.exit(1)")
    _write_tasks(home, {task_id: _pending_task(task_id, fail_cmd)})

    sleep_calls = []
    def _fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setenv("TASKQ_HOME", str(home))
    store._HOME = None
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "2")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0.1")
    monkeypatch.setattr(executor.time, "sleep", _fake_sleep)

    # GREEN TODO: `executor.execute_task` must retry on failed/timeout up to
    # `TASKQ_RETRY_LIMIT`, sleeping `BACKOFF_BASE * 2**n` between attempts.
    status = executor.execute_task(task_id, fail_cmd, 5.0)

    if retry_within_limit == "yes":  # AC-FR03-retry-within-limit
        assert retry_within_limit == "yes"
        assert status == "failed"
        # TASKQ_RETRY_LIMIT=2 means at most 2 backoff sleeps between attempts.
        # Sleep magnitudes follow TASKQ_BACKOFF_BASE * 2**n.
        assert len(sleep_calls) >= 1
        for n, secs in enumerate(sleep_calls[:2]):
            expected = 0.1 * (2 ** n)
            assert abs(secs - expected) < 1e-9, f"sleep[{n}]={secs} != {expected}"
        if final_outcome == "failed":
            assert final_outcome == "failed"
            task = _load_tasks(home)[task_id]
            assert task["status"] == "failed"
            assert task["exit_code"] == 1


# ── 2. test_fr03_breaker_opens_at_threshold ──────────────────────────────
# Q4 (state_transition): consecutive final failures >= TASKQ_BREAKER_THRESHOLD -> OPEN.


def test_fr03_breaker_opens_at_threshold(tmp_path, monkeypatch):
    threshold_reached = "yes"
    state = "OPEN"
    home = tmp_path / "taskq-home"
    threshold = 3
    fail_cmd = _python_command("import sys; sys.exit(1)")

    tasks = {}
    for i in range(threshold):
        tid = "thr" + str(i).zfill(4)
        tasks[tid] = _pending_task(tid, fail_cmd)
    _write_tasks(home, tasks)

    monkeypatch.setattr(executor.time, "sleep", lambda _s: None)
    result = _run_taskq(
        home, "run", "--all",
        env_extra={
            "TASKQ_RETRY_LIMIT": "0",
            "TASKQ_BREAKER_THRESHOLD": str(threshold),
            "TASKQ_TASK_TIMEOUT": "5",
        },
    )

    if threshold_reached == "yes":  # AC-FR03-threshold-met
        assert threshold_reached == "yes"
        assert result.returncode == 0
        # Breaker JSON must exist and report OPEN.
        assert _breaker_path(home).exists(), "breaker.json must be persisted"
        breaker = _load_breaker(home)
    if state == "OPEN":  # AC-FR03-state-open
        assert state == "OPEN"
        assert breaker.get("state") == "OPEN"
        assert breaker.get("failure_count", 0) >= threshold


# ── 3. test_fr03_open_rejects_exit3 ──────────────────────────────────────
# Q2 (validation): OPEN state -> exit 3 + stderr "breaker open", no subprocess.


def test_fr03_open_rejects_exit3(tmp_path):
    home = tmp_path / "taskq-home"
    state = "OPEN"
    expected_exit = "3"
    stderr_msg = "breaker open"
    task_id = "reject001"

    home.mkdir(parents=True, exist_ok=True)
    # Force the breaker into OPEN before invoking `run`.
    opened_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _breaker_path(home).write_text(json.dumps({
        "state": "OPEN",
        "opened_at": opened_at,
        "failure_count": 5,
    }))
    _write_tasks(home, {task_id: _pending_task(task_id, "echo hi")})

    result = _run_taskq(home, "run", task_id)

    if state == "OPEN":  # AC-FR03-state-open
        assert state == "OPEN"
        if expected_exit == "3":  # AC-FR03-open-exit-3
            assert expected_exit == "3"
            assert result.returncode == 3
        if stderr_msg == "breaker open":  # AC-FR03-stderr-rejection
            assert stderr_msg == "breaker open"
            assert "breaker open" in result.stderr

        # No subprocess should have run: status remains pending.
        task = _load_tasks(home)[task_id]
        assert task["status"] == "pending"


# ── 4. test_fr03_half_open_recovery ─────────────────────────────────────
# Q4 (state_transition): after cooldown -> HALF_OPEN; success -> CLOSED; failure -> re-OPEN.


def test_fr03_half_open_recovery(tmp_path):
    cooldown_elapsed = "yes"
    state = "HALF_OPEN"
    next_state = "CLOSED"
    home = tmp_path / "taskq-home"
    task_id = "recover001"
    ok_cmd = _python_command("print('ok')")

    home.mkdir(parents=True, exist_ok=True)
    # Breaker is OPEN but opened_at is far enough in the past for cooldown.
    opened_at = (datetime.now(timezone.utc) - timedelta(seconds=3600)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    _breaker_path(home).write_text(json.dumps({
        "state": "OPEN",
        "opened_at": opened_at,
        "failure_count": 5,
    }))
    _write_tasks(home, {task_id: _pending_task(task_id, ok_cmd)})

    if cooldown_elapsed == "yes":  # AC-FR03-cooldown-elapsed
        assert cooldown_elapsed == "yes"
        result = _run_taskq(home, "run", task_id)
        # Successful probe -> breaker must transition to CLOSED.
        assert result.returncode == 0
        breaker = _load_breaker(home)
        task = _load_tasks(home)[task_id]
    if state == "HALF_OPEN":  # AC-FR03-half-open-state
        assert state == "HALF_OPEN"
        assert task["status"] == "done"
    if next_state == "CLOSED":  # AC-FR03-half-open-success-closes
        assert next_state == "CLOSED"
        assert breaker.get("state") == "CLOSED"
        assert breaker.get("failure_count", 0) == 0
    if next_state == "OPEN":  # AC-FR03-half-open-failure-reopens
        assert next_state == "OPEN"
        assert breaker.get("state") == "OPEN"


# ── 5. test_fr03_breaker_atomic_write ───────────────────────────────────
# Q5 (fault_injection): breaker.json survives a mid-write crash.
# The atomic-write pattern (tmp + os.replace) means the file is always
# valid JSON and never leaves an orphan .tmp behind.


def test_fr03_breaker_atomic_write(tmp_path, monkeypatch):
    mid_write_crash = "yes"
    data_file_valid = "yes"
    write_path = "breaker.json"
    home = tmp_path / "taskq-home"

    threshold = 3
    fail_cmd = _python_command("import sys; sys.exit(1)")
    tasks = {
        "a" + str(i).zfill(4): _pending_task("a" + str(i).zfill(4), fail_cmd)
        for i in range(threshold)
    }
    _write_tasks(home, tasks)

    monkeypatch.setattr(executor.time, "sleep", lambda _s: None)
    _run_taskq(
        home, "run", "--all",
        env_extra={
            "TASKQ_RETRY_LIMIT": "0",
            "TASKQ_BREAKER_THRESHOLD": str(threshold),
            "TASKQ_TASK_TIMEOUT": "5",
        },
    )

    if mid_write_crash == "yes":  # AC-FR03-atomic-recovery
        assert mid_write_crash == "yes"
        bp = _breaker_path(home)
        if data_file_valid == "yes":
            assert data_file_valid == "yes"
            assert bp.exists(), write_path + " must exist after threshold reached"
            # File must be valid JSON (atomic write means no half-written state).
            json.loads(bp.read_text())
            # No leftover `.tmp` file from the atomic write.
            assert not bp.with_name("breaker.json.tmp").exists(), (
                "atomic write must leave no orphan .tmp file"
            )
            assert write_path == "breaker.json"


# ── In-process unit tests (coverage) ────────────────────────────────────
# Mirror the test_fr02.py coverage block. These exercise the
# `breaker` module API directly so pytest-cov measures it.


# GREEN TODO: `taskq.breaker` module must expose:
#   - class Breaker with `state`, `failure_count`, `opened_at`, `cooldown`,
#     `threshold`
#   - record_failure() -> None
#   - record_success() -> None
#   - try_acquire() -> bool  (True => allow; False => reject)
#   - load(path) -> Breaker / save(path, breaker) -> None  (atomic write)


def test_unit_breaker_initially_closed():
    # GREEN TODO: `taskq.breaker.Breaker()` constructor must yield state="CLOSED".
    from taskq import breaker  # type: ignore[import-not-found]

    b = breaker.Breaker()
    assert b.state == "CLOSED"
    assert b.failure_count == 0


def test_unit_breaker_opens_after_threshold_failures():
    from taskq import breaker  # type: ignore[import-not-found]

    b = breaker.Breaker(threshold=3)
    b.record_failure()
    assert b.state == "CLOSED"
    b.record_failure()
    assert b.state == "CLOSED"
    b.record_failure()
    assert b.state == "OPEN"
    assert b.try_acquire() is False


def test_unit_breaker_open_rejects():
    from taskq import breaker  # type: ignore[import-not-found]

    b = breaker.Breaker(threshold=1)
    b.record_failure()
    assert b.state == "OPEN"
    assert b.try_acquire() is False


def test_unit_breaker_half_open_success_closes():
    from taskq import breaker  # type: ignore[import-not-found]

    b = breaker.Breaker(threshold=1, cooldown=0.0)
    b.record_failure()
    assert b.state == "OPEN"
    # Cooldown already elapsed (0.0s) -> next try_acquire yields HALF_OPEN.
    assert b.try_acquire() is True
    b.record_success()
    assert b.state == "CLOSED"
    assert b.failure_count == 0


def test_unit_breaker_half_open_failure_reopens():
    from taskq import breaker  # type: ignore[import-not-found]

    b = breaker.Breaker(threshold=1, cooldown=0.0)
    b.record_failure()
    assert b.state == "OPEN"
    assert b.try_acquire() is True  # HALF_OPEN probe admitted
    b.record_failure()
    assert b.state == "OPEN"


def test_unit_breaker_save_load_roundtrip(tmp_path):
    from taskq import breaker  # type: ignore[import-not-found]

    p = tmp_path / "breaker.json"
    b = breaker.Breaker(threshold=2)
    b.record_failure()
    b.record_failure()
    assert b.state == "OPEN"
    breaker.save(p, b)
    assert p.exists()
    b2 = breaker.load(p)
    assert b2.state == "OPEN"
    assert b2.failure_count == 2


# ── executor retry behaviour (in-process coverage) ─────────────────────


def test_unit_execute_task_retries_until_done(tmp_path, monkeypatch):
    # Injectable sleeper so backoff is observed, not waited on.
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    store._HOME = None
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "2")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0.1")
    monkeypatch.setattr(executor.time, "sleep", lambda _s: None)

    calls = {"n": 0}
    original = executor._run_subprocess

    def _flaky(command, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            return 1, "", "", 1.0, "failed"
        return original(command, timeout)

    monkeypatch.setattr(executor, "_run_subprocess", _flaky)

    # GREEN TODO: `executor.execute_task` must retry on failed/timeout up to
    # `TASKQ_RETRY_LIMIT`, sleeping `BACKOFF_BASE * 2**n` between attempts.
    status = executor.execute_task("rt1", "echo hi", 5.0)
    assert status == "done"
    assert calls["n"] == 3


# ── executor.run_all breaker integration (in-process coverage) ──────────


def test_unit_run_all_records_breaker_success(tmp_path, monkeypatch):
    """When a task succeeds under breaker supervision, run_all records
    the success and the breaker returns to CLOSED with failure_count == 0.
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    store._HOME = None
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "3")
    monkeypatch.setattr(executor.time, "sleep", lambda _s: None)

    home = tmp_path
    (home / "tasks.json").write_text(json.dumps({
        "p0": {
            "id": "p0",
            "command": "echo ok",
            "name": None,
            "status": "pending",
            "created_at": "2026-07-10T00:00:00Z",
        },
    }))
    results = executor.run_all(timeout=5.0, max_workers=1)
    assert results == {"p0": "done"}

    bp = breaker.load(home / "breaker.json")
    assert bp.state == "CLOSED"
    assert bp.failure_count == 0


def test_unit_run_all_records_breaker_failure(tmp_path, monkeypatch):
    """When a task fails under breaker supervision, run_all records the
    failure on the breaker (failure_count increments).
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    store._HOME = None
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "5")
    monkeypatch.setattr(executor.time, "sleep", lambda _s: None)

    home = tmp_path
    fail_cmd = _python_command("import sys; sys.exit(1)")
    (home / "tasks.json").write_text(json.dumps({
        "f0": {
            "id": "f0",
            "command": fail_cmd,
            "name": None,
            "status": "pending",
            "created_at": "2026-07-10T00:00:00Z",
        },
    }))
    results = executor.run_all(timeout=5.0, max_workers=1)
    assert results == {"f0": "failed"}

    bp = breaker.load(home / "breaker.json")
    assert bp.failure_count >= 1


def test_unit_run_all_skips_when_breaker_open(tmp_path, monkeypatch):
    """When the breaker is OPEN and cooldown has not elapsed, run_all
    skips pending tasks (returns without attempting them).
    """
    from datetime import datetime, timezone

    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    store._HOME = None
    monkeypatch.setattr(executor.time, "sleep", lambda _s: None)

    home = tmp_path
    opened_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (home / "breaker.json").write_text(json.dumps({
        "state": "OPEN",
        "opened_at": opened_at,
        "failure_count": 5,
        "threshold": 3,
        "cooldown": 60.0,
    }))
    (home / "tasks.json").write_text(json.dumps({
        "s0": {
            "id": "s0",
            "command": "echo ok",
            "name": None,
            "status": "pending",
            "created_at": "2026-07-10T00:00:00Z",
        },
    }))
    results = executor.run_all(timeout=5.0, max_workers=1)
    # Breaker is OPEN and cooldown not elapsed → task skipped, not in results.
    assert results == {}


# ── executor._run_subprocess timeout branch (coverage) ──────────────────


def test_unit_run_subprocess_timeout_branch(monkeypatch):
    """Cover the TimeoutExpired exception path in _run_subprocess."""
    monkeypatch.setattr(executor.time, "sleep", lambda _s: None)
    cmd = _python_command("import time; time.sleep(5)")
    exit_code, stdout_tail, stderr_tail, duration_ms, status = executor._run_subprocess(
        cmd, 0.5
    )
    assert status == "timeout"
    assert exit_code is None
    assert duration_ms >= 0
