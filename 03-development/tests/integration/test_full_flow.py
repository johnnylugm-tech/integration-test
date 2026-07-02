"""End-to-end integration tests for the ``taskq`` CLI.

Coarser-grained than the per-FR unit suites under ``tests/test_fr*.py``.
Serves the Gate-2 integration_coverage dimension: real CLI invocation
(``cli.main`` in-process for source coverage), real subprocess execution
for entry-point wiring.

Strategy: call ``taskq_cli.main([...])`` in-process so coverage tracks ``src/``;
spawn ``python -m taskq`` once at end-of-suite to confirm the entry-point
wiring remains intact.

Citations:
- SPEC.md S3 FR-01..FR-03 (CLI submit/list/run/status/clear lifecycle).
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from taskq.cli import cli as taskq_cli

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"


def _run_subprocess(args: list[str], home: Path) -> subprocess.CompletedProcess:
    """Invoke ``python -m taskq <args>`` end-to-end (entry-point smoke only).

    The sitecustomize.py adjacent to `tests/` is added to PYTHONPATH so the
    subprocess records its own source-tree coverage when
    COVERAGE_PROCESS_START is set.
    """
    env = {
        **os.environ,
        "TASKQ_HOME": str(home),
        "PYTHONPATH": str(_ROOT),
        "COVERAGE_PROCESS_START": str(_ROOT / ".coveragerc"),
        "COVERAGE_FILE": str(_ROOT / ".coverage.subproc"),
    }
    return subprocess.run(
        [sys.executable, "-m", "taskq", *args],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def fresh_home(tmp_path, monkeypatch) -> Path:
    """Fresh TASKQ_HOME per test; monkeypatched into the env."""
    home = tmp_path / ".taskq"
    home.mkdir()
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


def _load(home: Path) -> list:
    """Load the tasks list from on-disk store (FR-01 dict-or-list payload)."""
    payload = json.loads((home / "tasks.json").read_text())
    # store schema is {"tasks": [...]}; callers use this list directly
    if isinstance(payload, dict) and "tasks" in payload:
        return payload["tasks"]
    return payload if isinstance(payload, list) else []


def _first_task_id(home: Path) -> str:
    """Return the first submitted task id from the on-disk list."""
    for rec in _load(home):
        if "id" in rec:
            return rec["id"]
    raise AssertionError(f"no task id found in {home}/tasks.json")


def test_int_submit_creates_record(fresh_home):
    """submit writes an 8-hex task record into tasks.json (FR-01)."""
    rc = taskq_cli.main(["submit", "echo hi"])
    assert rc == 0
    recs = _load(fresh_home)
    assert len(recs) == 1
    rec = recs[0]
    tid = rec["id"]
    assert len(tid) == 8
    assert rec["command"] == "echo hi"
    assert rec["status"] == "pending"
    assert rec["created_at"].endswith("Z")


def test_int_submit_then_list_shows_task(fresh_home):
    """list surfaces the just-submitted task (FR-03)."""
    taskq_cli.main(["submit", "echo hi"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = taskq_cli.main(["list"])
    assert rc == 0
    assert "echo hi" in buf.getvalue()


def test_int_submit_run_status_happy(fresh_home):
    """Submit + run + status: returns 0 and status=done."""
    taskq_cli.main(["submit", 'python -c "print(1)"'])
    tid = _first_task_id(fresh_home)
    rc = taskq_cli.main(["run", tid])
    assert rc == 0
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = taskq_cli.main(["status", tid])
    assert rc == 0
    out = buf.getvalue()
    assert "status: done" in out


def test_int_run_nonzero_marks_failed(fresh_home):
    """Failing command produces status=failed (FR-02)."""
    taskq_cli.main(["submit", 'python -c "import sys\nsys.exit(7)"'])
    tid = _first_task_id(fresh_home)
    taskq_cli.main(["run", tid])
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskq_cli.main(["status", tid])
    out = buf.getvalue()
    assert "status: failed" in out


def test_int_run_timeout_exits_4(fresh_home, monkeypatch):
    """A timing-out command propagates CLI exit 4 (FR-02 timeout semantics)."""
    # Force a 1s timeout via TASKQ_TASK_TIMEOUT env override (only knob).
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "1")
    taskq_cli.main(["submit", 'python -c "import time\ntime.sleep(5)"'])
    tid = _first_task_id(fresh_home)
    rc = taskq_cli.main(["run", tid])
    assert rc == 4


def test_int_list_json_emits_array(fresh_home):
    """list --json emits a single-line JSON array (FR-03)."""
    taskq_cli.main(["submit", "echo hi"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = taskq_cli.main(["--json", "list"])
    assert rc == 0
    payload = json.loads(buf.getvalue().strip())
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["command"] == "echo hi"


def test_int_status_unknown_id_exits_2(fresh_home, capsys):
    """status <unknown> exits 2 and emits stderr (FR-03)."""
    rc = taskq_cli.main(["status", "deadbeef"])
    assert rc == 2
    assert "unknown task" in capsys.readouterr().err


def test_int_clear_empties_store(fresh_home, capsys):
    """clear removes tasks.json (FR-03)."""
    taskq_cli.main(["submit", "echo hi"])
    rc = taskq_cli.main(["clear"])
    assert rc == 0
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = taskq_cli.main(["list"])
    assert rc == 0
    assert buf.getvalue().strip() == ""


def test_int_submit_rejects_blacklist_char(fresh_home, capsys):
    """A shell-metacharacter command is rejected at submit (NFR-02, FR-01)."""
    rc = taskq_cli.main(["submit", "echo hi; rm"])
    assert rc == 2
    assert not (fresh_home / "tasks.json").exists()


def test_int_subprocess_entry_point_wires(fresh_home):
    """End-to-end smoke: subprocess invocation via `python -m taskq` works."""
    rc = _run_subprocess(["submit", "echo hi"], fresh_home)
    assert rc.returncode == 0
    rc = _run_subprocess(["list"], fresh_home)
    assert rc.returncode == 0
    assert "echo hi" in rc.stdout
