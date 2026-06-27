"""End-to-end integration tests for the ``taskq`` CLI.

These tests exercise the complete submit -> run -> status -> list -> clear
lifecycle. They are coarser-grained than the per-FR unit suites under
``tests/test_fr*.py`` and serve as the Gate-2 integration_coverage
dimension: real CLI invocation (via ``cli.main`` in-process), real
subprocess execution, real on-disk store. Coverage is measured against
``src/taskq``.

Strategy: call ``cli.main([...])`` in-process for assertions (so coverage
tracks the src/ tree) and spawn ``python -m taskq`` subprocesses to verify
the entry-point wiring is intact end-to-end. Both paths count toward
integration coverage because the subprocesses re-exercise ``__main__`` and
``cli`` through the interpreter.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from taskq import cli

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"


def _run_subprocess(args: list[str], home: Path) -> subprocess.CompletedProcess:
    """Invoke ``python -m taskq <args>`` with TASKQ_HOME pointed at ``home``.

    Used only for the end-to-end smoke assertions (entry-point wiring);
    coverage tracking is provided by the in-process cli.main calls.
    """
    env = {
        **os.environ,
        "TASKQ_HOME": str(home),
        "PYTHONPATH": str(_SRC),
    }
    return subprocess.run(
        [sys.executable, "-m", "taskq", *args],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def fresh_home(tmp_path, monkeypatch) -> Path:
    """Fresh TASKQ_HOME for each test; monkeypatched into the in-process env."""
    home = tmp_path / ".taskq"
    home.mkdir()
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


def _load(home: Path) -> dict:
    return json.loads((home / "tasks.json").read_text())


def test_int_submit_creates_record(fresh_home):
    """submit writes an 8-hex task record into tasks.json."""
    rc = cli.main(["submit", "echo hi"])
    assert rc == 0
    data = _load(fresh_home)
    assert len(data) == 1
    tid, rec = next(iter(data.items()))
    assert len(tid) == 8
    assert rec["command"] == "echo hi"
    assert rec["status"] == "pending"
    assert rec["created_at"].endswith("Z")


def test_int_submit_then_list_shows_task(fresh_home):
    """list surfaces the submitted task."""
    cli.main(["submit", "echo hi"])
    import io

    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["list"])
    assert rc == 0
    assert "echo hi" in buf.getvalue()


def test_int_submit_then_run_then_status(fresh_home):
    """Full happy path: submit -> run -> status returns done, exit_code 0."""
    cli.main(["submit", 'python -c "print(1)"'])
    tid = next(iter(_load(fresh_home)))
    rc = cli.main(["run", "--id", tid])
    assert rc == 0
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["status", tid])
    assert rc == 0
    out = buf.getvalue()
    assert "done" in out
    assert "exit_code: 0" in out


def test_int_run_nonzero_marks_failed(fresh_home):
    """A failing command (sys.exit(7)) produces status=failed, exit_code=7."""
    cli.main(["submit", 'python -c "import sys; sys.exit(7)"'])
    tid = next(iter(_load(fresh_home)))
    cli.main(["run", "--id", tid])
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.main(["status", tid])
    out = buf.getvalue()
    assert "failed" in out
    assert "exit_code: 7" in out


def test_int_run_timeout_exits_4(fresh_home):
    """A timing-out command propagates CLI exit 4 and status=timeout."""
    cli.main(["submit", 'python -c "import time; time.sleep(5)"'])
    tid = next(iter(_load(fresh_home)))
    rc = cli.main(["run", "--id", tid, "--timeout", "1"])
    assert rc == 4


def test_int_list_json_emits_array(fresh_home):
    """list --json emits a single-line JSON array of records."""
    cli.main(["submit", "echo hi"])
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["list", "--json"])
    assert rc == 0
    payload = json.loads(buf.getvalue().strip())
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["command"] == "echo hi"


def test_int_status_unknown_id_exits_2(fresh_home, capsys):
    """status <unknown> exits 2 and emits stderr."""
    rc = cli.main(["status", "deadbeef"])
    assert rc == 2
    assert "unknown task" in capsys.readouterr().err


def test_int_health_probe_ok(fresh_home, capsys):
    """health probe returns 0 with OK on stdout."""
    rc = cli.main(["health"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "OK"


def test_int_clear_empties_store(fresh_home, capsys):
    """clear removes tasks.json so a subsequent list shows no entries."""
    cli.main(["submit", "echo hi"])
    rc = cli.main(["clear"])
    assert rc == 0
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["list"])
    assert rc == 0
    assert buf.getvalue().strip() == ""


def test_int_submit_rejects_blacklist_char(fresh_home, capsys):
    """A shell-metacharacter command is rejected at submit (exit 2, no record)."""
    rc = cli.main(["submit", "echo hi; rm"])
    assert rc == 2
    assert not (fresh_home / "tasks.json").exists()


def test_int_subprocess_entry_point_wires(fresh_home):
    """End-to-end smoke: subprocess invocation via python -m taskq works."""
    rc = _run_subprocess(["submit", "echo hi"], fresh_home)
    assert rc.returncode == 0
    rc = _run_subprocess(["list"], fresh_home)
    assert rc.returncode == 0
    assert "echo hi" in rc.stdout
    rc = _run_subprocess(["health"], fresh_home)
    assert rc.returncode == 0
    assert rc.stdout.strip() == "OK"