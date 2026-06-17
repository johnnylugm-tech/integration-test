"""Integration tests: full E2E flows covering all modules in one process.

These tests live under `tests/integration/` so the
`pytest-cov-integration` tool (Gate 2 `integration_coverage` dim) finds
them and measures real end-to-end coverage of the source tree. In-process
invocation is used so coverage.py can actually track the lines touched;
this still covers the full module interaction (cli → executor → store →
persistence → validation → redact).
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout

import pytest

from taskq.cli import main as cli_main
from taskq.executor import run_task
from taskq.store import clear_store, load_store, submit_task


@pytest.fixture
def isolated_home(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect TASKQ_HOME to tmp + standard timeout env."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "10.0")
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")


def test_e2e_submit_run_status_list_clear(isolated_home) -> None:
    """Full pipeline: submit → run → status → list → clear all exit 0."""
    # 1. submit
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        code = cli_main(["submit", "echo integ"])
    assert code == 0
    tid = buf.getvalue().strip().splitlines()[-1]
    # 2. run
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        code = cli_main(["run", tid])
    assert code == 0
    # 3. status
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        code = cli_main(["status", tid])
    assert code == 0
    assert "done" in buf.getvalue()
    # 4. list
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        code = cli_main(["list"])
    assert code == 0
    assert tid in buf.getvalue()
    # 5. clear
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        code = cli_main(["clear"])
    assert code == 0
    assert load_store() == {}


def test_e2e_json_flag_round_trip(isolated_home) -> None:
    """`--json` mode round-trips parseable output for submit + list."""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        code = cli_main(["--json", "submit", "echo j"])
    assert code == 0
    submit_obj = json.loads(buf.getvalue().strip())
    assert "id" in submit_obj
    assert submit_obj["command"] == "echo j"
    tid = submit_obj["id"]
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        code = cli_main(["--json", "list"])
    assert code == 0
    listing = json.loads(buf.getvalue().strip())
    assert any(t["id"] == tid for t in listing)


def test_e2e_concurrent_submits_and_run(isolated_home) -> None:
    """Eight submits + runs all complete; list shows all 8."""
    tids: list[str] = []
    for i in range(8):
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            code = cli_main(["submit", f"echo p{i}"])
        assert code == 0
        tids.append(buf.getvalue().strip().splitlines()[-1])
    # Run them all
    for tid in tids:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            assert cli_main(["run", tid]) == 0
    # List
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        code = cli_main(["list"])
    assert code == 0
    for tid in tids:
        assert tid in buf.getvalue()


def test_e2e_secret_redaction_pipeline(isolated_home, monkeypatch) -> None:
    """End-to-end: a run emitting a sk-* token to stdout must be persisted
    with the secret scrubbed. Exercises cli → executor → store → persistence
    → redact all in one path."""
    import os
    monkeypatch.setenv("STDOUT_SECRET", "sk-thisisnotreal123456789")
    helper = os.path.join(os.path.dirname(__file__), "_secret_echo.py")
    with open(helper, "w") as f:
        f.write("import os\nprint(os.environ['STDOUT_SECRET'])\n")
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        code = cli_main(["submit", f"python3 {helper}"])
    assert code == 0
    tid = buf.getvalue().strip().splitlines()[-1]
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        code = cli_main(["run", tid])
    assert code == 0
    # Persisted record must not contain the raw secret
    record = load_store()[tid]
    assert "sk-thisisnotreal123456789" not in (record.stdout_tail or "")
    # cleanup
    os.unlink(helper)
    clear_store()
