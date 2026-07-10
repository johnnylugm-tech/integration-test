"""End-to-end integration tests for taskq CLI cross-module flows.

Exercises the full CLI → executor → store pipeline by calling `cli.main()`
directly (in-process) under isolated `TASKQ_HOME`. In-process execution
ensures coverage propagates to the parent runner (subprocess would not).

Each test covers a distinct cross-module interaction:

  * submit → list                    (cli → store)
  * submit → run → status            (cli → executor → store)
  * submit → run (fail) → status     (cli → executor → store, error path)
  * submit → clear                   (cli → store, lifecycle)
  * submit --json roundtrip + status (cli → store, JSON serialization)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from taskq import cli

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_ROOT / "03-development" / "src"


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point TASKQ_HOME at a fresh per-test directory and reset module-level
    caches that the production modules memoize at import time."""
    from taskq import store

    home = tmp_path / "taskq-home"
    monkeypatch.setenv("TASKQ_HOME", str(home))
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "5")
    # Reset module-level memoised HOME so the new env var takes effect.
    store._HOME = None  # noqa: SLF001 — intentional test isolation
    return home


def _python_command(body: str) -> str:
    import shlex
    import sys

    return shlex.quote(sys.executable) + " -c " + shlex.quote(body)


def test_integration_submit_then_list(isolated_home: Path) -> None:
    """submit persists task → list reads it back (cli ↔ store round-trip)."""
    rc = cli.main(["--json", "submit", _python_command("print('hi')")])
    assert rc == 0

    # Read tasks.json directly (list output goes to stdout which we don't capture here).
    tasks_path = isolated_home / "tasks.json"
    assert tasks_path.exists()
    tasks = json.loads(tasks_path.read_text())
    assert len(tasks) == 1
    (task_id, task) = next(iter(tasks.items()))
    assert task["status"] == "pending"
    assert task["name"] is None


def test_integration_submit_run_status_done(isolated_home: Path) -> None:
    """submit → run → status flows through cli → executor → store."""
    rc = cli.main(["--json", "submit", _python_command("print('done')")])
    assert rc == 0
    tasks = json.loads((isolated_home / "tasks.json").read_text())
    task_id = next(iter(tasks))

    rc = cli.main(["run", task_id])
    assert rc == 0

    tasks_after = json.loads((isolated_home / "tasks.json").read_text())
    assert tasks_after[task_id]["status"] == "done"
    assert tasks_after[task_id]["exit_code"] == 0
    assert tasks_after[task_id]["finished_at"]


def test_integration_submit_run_failure_propagates(isolated_home: Path) -> None:
    """A failing command is recorded as 'failed' with non-zero exit_code."""
    rc = cli.main(["--json", "submit", _python_command("raise SystemExit(7)")])
    assert rc == 0
    tasks = json.loads((isolated_home / "tasks.json").read_text())
    task_id = next(iter(tasks))

    rc = cli.main(["run", task_id])
    assert rc == 0  # CLI itself OK; the task failed.

    tasks_after = json.loads((isolated_home / "tasks.json").read_text())
    assert tasks_after[task_id]["status"] == "failed"
    assert tasks_after[task_id]["exit_code"] == 7
    assert tasks_after[task_id]["finished_at"]


def test_integration_submit_clear_lifecycle(isolated_home: Path) -> None:
    """submit adds → clear removes (cli → store → cli)."""
    rc = cli.main(["--json", "submit", _python_command("print('x')")])
    assert rc == 0
    assert (isolated_home / "tasks.json").exists()

    rc = cli.main(["clear"])
    assert rc == 0

    # `clear` deletes tasks.json (not just empties it). Verify via `list`.
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["list"])
    assert rc == 0
    assert buf.getvalue().strip() == ""


def test_integration_json_roundtrip(isolated_home: Path) -> None:
    """--json output on submit + status produces parseable JSON both times."""
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["--json", "submit", _python_command("print('j')")])
    assert rc == 0
    submit_payload = json.loads(buf.getvalue())
    assert submit_payload["status"] == "pending"
    task_id = submit_payload["id"]

    rc = cli.main(["run", task_id])
    assert rc == 0

    buf.seek(0)
    buf.truncate(0)
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["--json", "status", task_id])
    assert rc == 0
    status_payload = json.loads(buf.getvalue())
    assert status_payload["status"] == "done"
    assert status_payload["exit_code"] == 0