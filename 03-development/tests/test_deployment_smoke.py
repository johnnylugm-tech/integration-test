"""Deployment smoke tests.

Reference:
  TEST_SPEC.md §Deployment Smoke — ``test_cli_help_prints_subcommands``,
  ``test_python_dash_m_taskq_runs``.

These tests verify the SAD §1.1 deployment entry contract:
``python -m taskq`` works as an installed entry point and ``--help``
prints the subcommand table.
"""

from __future__ import annotations

import json as json_lib
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def taskq_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test ``$TASKQ_HOME`` directory."""
    home = tmp_path / "taskq_home"
    home.mkdir()
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


def test_cli_help_prints_subcommands(taskq_home: Path) -> None:
    """Smoke: ``python -m taskq --help`` prints the subcommand table.

    AC: invoking the package's ``__main__`` entrypoint with ``--help``
    (or ``-h``) prints a usage string listing every public subcommand
    (submit, run, status, list, clear) and exits 0.
    """
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src")}

    # ``--help`` must succeed.
    rc = subprocess.run(
        [sys.executable, "-m", "taskq", "--help"],
        capture_output=True, text=True, env=env, timeout=10,
    )
    assert rc.returncode == 0, f"--help exited {rc.returncode}: stderr={rc.stderr!r}"

    # The output must enumerate every subcommand.
    out = rc.stdout
    for sub in ("submit", "run", "status", "list", "clear"):
        assert sub in out, f"subcommand {sub!r} missing from --help output: {out!r}"


def test_python_dash_m_taskq_runs(taskq_home: Path) -> None:
    """Smoke: ``python -m taskq <subcommand>`` runs as installed entry.

    AC: invoking the package's ``__main__`` entrypoint with a valid
    subcommand (``status <id>`` after seeding a record) succeeds end-to-end
    and the in-process CLI dispatcher maps to the right handler.
    """
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src")}

    # Seed a task via the entrypoint.
    rc_submit = subprocess.run(
        [sys.executable, "-m", "taskq", "submit", "echo smoke"],
        capture_output=True, text=True, env=env, timeout=10,
    )
    assert rc_submit.returncode == 0, (
        f"submit failed: stderr={rc_submit.stderr!r}"
    )

    # Read back the seeded record's id from tasks.json.
    data = json_lib.loads((taskq_home / "tasks.json").read_text())
    assert isinstance(data, dict)
    assert len(data) == 1, f"expected 1 record, got {len(data)}"
    tid = next(iter(data))

    # ``status <id>`` via the entrypoint returns 0 and prints the record.
    rc_status = subprocess.run(
        [sys.executable, "-m", "taskq", "status", tid],
        capture_output=True, text=True, env=env, timeout=10,
    )
    assert rc_status.returncode == 0, (
        f"status failed: stderr={rc_status.stderr!r}"
    )
    assert tid in rc_status.stdout
    assert "echo smoke" in rc_status.stdout