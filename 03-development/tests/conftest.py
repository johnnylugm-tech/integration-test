"""Shared pytest fixtures for FR-01 tests.

The `taskq` CLI is invoked as a subprocess to exercise the real CLI entry
(`python -m taskq`), so each test gets an isolated `$TASKQ_HOME` directory
under pytest's `tmp_path`. This isolates filesystem state across tests
without mocking the CLI's own internal filesystem calls.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def taskq_home(tmp_path: Path) -> Path:
    """Return an isolated TASKQ_HOME directory for a single test."""
    home = tmp_path / ".taskq"
    home.mkdir(parents=True, exist_ok=True)
    return home


@pytest.fixture
def taskq_env(taskq_home: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Environment dict with TASKQ_HOME pointed at the per-test directory.

    The returned dict is suitable for `subprocess.run(env=...)`. We do NOT
    rely on `monkeypatch.setenv` here because the subprocess needs the
    value visible inside its own process — passing `env=` is the explicit,
    reliable way to do that.
    """
    env = os.environ.copy()
    env["TASKQ_HOME"] = str(taskq_home)
    # Force unbuffered output so we can read what the CLI writes.
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run_taskq(
    args: list[str],
    env: dict[str, str],
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `python -m taskq <args>` as a subprocess and capture output.

    The `taskq` module lives at `03-development/src/taskq/` and is importable
    because `setup.cfg` sets `pythonpath = 03-development/src`. The subprocess
    inherits the same Python and the same sys.path configuration as pytest
    (we copy PATH / PYTHONPATH through `env`).

    Caller-supplied env is merged over `os.environ` so call sites only need
    to override the variables they care about (e.g. TASKQ_HOME). Without
    this merge, a caller passing only `{"TASKQ_HOME": ...}` strips
    PYTHONPATH and the subprocess fails with `No module named taskq`.
    """
    merged_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, "-m", "taskq", *args],
        capture_output=True,
        text=True,
        env=merged_env,
        cwd=str(cwd) if cwd else None,
        timeout=30,
    )


def tasks_json_path(taskq_home: Path) -> Path:
    """Return the path to `$TASKQ_HOME/tasks.json`."""
    return taskq_home / "tasks.json"


def write_corrupt_tasks_json(taskq_home: Path) -> Path:
    """Write invalid JSON to tasks.json so startup-detection can be exercised."""
    p = tasks_json_path(taskq_home)
    p.write_text("not-valid-json{", encoding="utf-8")
    return p


def load_tasks(taskq_home: Path) -> list[dict[str, Any]]:
    """Read and parse `$TASKQ_HOME/tasks.json`. Raises on invalid JSON."""
    p = tasks_json_path(taskq_home)
    import json as _json

    return _json.loads(p.read_text(encoding="utf-8"))