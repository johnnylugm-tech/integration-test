"""[FR-01][FR-02][FR-03] End-to-end CLI lifecycle integration tests.

Exercises `python -m taskq` as a real subprocess against an isolated
$TASKQ_HOME so the full persistence + executor + query path is covered
beyond what the unit-level fr01/fr02/fr03 tests exercise.

This file verifies that the FR-01 (submit persistence), FR-02 (executor
retry + state machine) and FR-03 (CLI surface) requirements all hold
under realistic process boundaries (separate interpreter, separate
$TASKQ_HOME directory, real subprocess invocations).

Citations:
- SPEC.md S3 FR-01 (submit -> persisted -> status -> clear).
- SPEC.md S3 FR-02 (submit -> run subprocess -> state transitions).
- SPEC.md S3 FR-03 (--json, list, clear).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[3]
PYTHON = sys.executable
SRC = REPO / "03-development" / "src"


def _run_taskq(home: Path, *args: str, stdin_data: str | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["TASKQ_HOME"] = str(home)
    env["PYTHONPATH"] = str(SRC)
    env["TASKQ_TASK_TIMEOUT"] = "5"
    env["TASKQ_RETRY_LIMIT"] = "0"
    return subprocess.run(
        [PYTHON, "-m", "taskq", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        input=stdin_data,
    )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    d = tmp_path / "taskq_home"
    d.mkdir()
    return d


def test_integration_submit_status_clear_roundtrip(home: Path) -> None:
    """submit -> status -> clear lifecycle via real CLI subprocess."""
    p = _run_taskq(home, "submit", "echo integration_roundtrip")
    assert p.returncode == 0, f"submit failed: {p.stderr}"

    tasks_file = home / "tasks.json"
    assert tasks_file.exists(), "submit must persist tasks.json"
    payload = json.loads(tasks_file.read_text())
    assert "tasks" in payload and len(payload["tasks"]) == 1
    tid = payload["tasks"][0]["id"]
    assert len(tid) == 8

    p_status = _run_taskq(home, "status", tid)
    assert p_status.returncode == 0
    assert tid in p_status.stdout

    p_clear = _run_taskq(home, "clear")
    assert p_clear.returncode == 0
    assert not tasks_file.exists(), "clear must remove tasks.json"

    p_clear2 = _run_taskq(home, "clear")
    assert p_clear2.returncode == 0, "clear must be idempotent"


def _latest_task_id(home: Path) -> str:
    payload = json.loads((home / "tasks.json").read_text())
    return payload["tasks"][0]["id"]


def test_integration_run_subprocess_exit_code_0(home: Path) -> None:
    """submit + run for an exit-0 task lands in status 'done'."""
    p = _run_taskq(home, "submit", "true")
    assert p.returncode == 0
    tid = _latest_task_id(home)
    p_run = _run_taskq(home, "run", tid)
    assert p_run.returncode == 0
    payload = json.loads((home / "tasks.json").read_text())
    t = payload["tasks"][0]
    assert t["status"] == "done"


def test_integration_run_subprocess_failure(home: Path) -> None:
    """Failed command (exit 1) lands with status 'failed'."""
    p = _run_taskq(home, "submit", "false")
    assert p.returncode == 0
    tid = _latest_task_id(home)
    p_run = _run_taskq(home, "run", tid)
    assert p_run.returncode in (0, 1)
    payload = json.loads((home / "tasks.json").read_text())
    t = payload["tasks"][0]
    assert t["status"] == "failed"


def test_integration_json_flag_listing(home: Path) -> None:
    """--json must emit a single-line JSON document on submit and list."""
    p = _run_taskq(home, "--json", "submit", "echo hi")
    assert p.returncode == 0
    assert "\n" not in p.stdout.strip() or p.stdout.count("\n") <= 1
    parsed = json.loads(p.stdout)
    assert "id" in parsed and parsed["status"] == "pending"

    p_list = _run_taskq(home, "--json", "list")
    assert p_list.returncode == 0
    parsed_list = json.loads(p_list.stdout)
    assert isinstance(parsed_list, list)
    assert len(parsed_list) == 1


def test_integration_corrupt_store_yields_error(home: Path) -> None:
    """A malformed tasks.json triggers exit 1 + stderr 'store corrupted'."""
    tasks_file = home / "tasks.json"
    tasks_file.write_text("{ not valid json")
    p = _run_taskq(home, "list")
    assert p.returncode == 1, f"corrupt store expected exit 1, got {p.returncode}"
    assert "store corrupted" in p.stderr.lower()
