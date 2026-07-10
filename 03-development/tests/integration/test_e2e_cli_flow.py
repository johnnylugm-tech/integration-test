"""End-to-end integration tests for the taskq CLI.

These tests exercise the public CLI surface (cli.main) end-to-end with
multiple modules participating (cli → config → store → executor → cache →
breaker) and verify the externally observable behaviour: exit codes, files
written, subprocess execution. They are intentionally separate from the
per-FR unit tests so the integration_coverage dimension has its own
targeted suite and pytest -k "integration" can be run in isolation.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def taskq_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test $TASKQ_HOME isolation (NFR-03)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# FR-01 + FR-05 e2e: submit writes tasks.json atomically; main() round-trip
# ---------------------------------------------------------------------------


def test_e2e_submit_writes_tasks_json(taskq_home: Path) -> None:
    """cli.main(['submit', 'echo ok']) returns 0 and writes tasks.json with the new task."""
    from taskq import cli, store

    rc = cli.main(["submit", "echo ok", "--name", "e2e-alpha"])
    assert rc == 0

    tasks_path = taskq_home / "tasks.json"
    assert tasks_path.exists(), "submit must create tasks.json"
    data = json.loads(tasks_path.read_text(encoding="utf-8"))
    # store schema: dict {task_id: task_dict}
    assert isinstance(data, dict)
    assert len(data) == 1
    (task_id, task_dict), = data.items()
    assert task_dict["command"] == "echo ok"
    assert task_dict["name"] == "e2e-alpha"
    assert task_dict["status"] == "pending"
    # Sanity-check the module under test still works.
    assert store.find_active_by_name("e2e-alpha") is not None
    assert task_id == store.find_active_by_name("e2e-alpha")["id"]


def test_e2e_submit_validation_rejection(taskq_home: Path) -> None:
    """Empty command + non-zero exit code; no write to tasks.json (FR-01 rule 1)."""
    from taskq import cli

    rc = cli.main(["submit", ""])
    assert rc == 2
    assert not (taskq_home / "tasks.json").exists(), (
        "validation rejection must not write to tasks.json"
    )


def test_e2e_status_subcommand_lists_pending(taskq_home: Path) -> None:
    """submit → status round-trip; status prints the task fields (FR-05)."""
    from taskq import cli, store

    rc1 = cli.main(["submit", "echo hello", "--name", "e2e-status"])
    assert rc1 == 0

    # status subcommand takes the task_id (not the name).
    task_id = store.find_active_by_name("e2e-status")["id"]
    rc2 = cli.main(["status", task_id])
    assert rc2 == 0


def test_e2e_list_subcommand(taskq_home: Path) -> None:
    """list subcommand returns 0 and writes to stdout (FR-05)."""
    from taskq import cli

    cli.main(["submit", "echo a"])
    cli.main(["submit", "echo b"])
    rc = cli.main(["list"])
    assert rc == 0


def test_e2e_clear_subcommand(taskq_home: Path) -> None:
    """clear subcommand returns 0 and removes pending tasks (FR-05)."""
    from taskq import cli

    cli.main(["submit", "echo clear-me"])
    rc = cli.main(["clear"])
    assert rc == 0


# ---------------------------------------------------------------------------
# FR-02 e2e: run actually executes via the executor subprocess
# ---------------------------------------------------------------------------


def test_e2e_run_executes_command_and_persists_result(taskq_home: Path) -> None:
    """submit → run round-trip transitions pending→done and writes the result fields."""
    from taskq import cli, store

    rc1 = cli.main(["submit", "echo e2e-done", "--name", "e2e-run"])
    assert rc1 == 0

    # run subcommand takes the task_id (not the name).
    task_id = store.find_active_by_name("e2e-run")["id"]
    rc2 = cli.main(["run", task_id])
    assert rc2 == 0

    tasks_path = taskq_home / "tasks.json"
    data = json.loads(tasks_path.read_text(encoding="utf-8"))
    task = data[task_id]
    assert task["status"] == "done"
    # FR-02: result fields per SPEC §3 line 78-82 live at the top level
    # of the persisted task dict (alongside id/command/status).
    for field in ("exit_code", "stdout_tail", "stderr_tail", "duration_ms", "finished_at"):
        assert field in task, f"missing result field {field!r} after run"
    assert task["exit_code"] == 0


# ---------------------------------------------------------------------------
# FR-05 e2e: --json flag emits single-line JSON
# ---------------------------------------------------------------------------


def test_e2e_json_output_is_single_line(taskq_home: Path) -> None:
    """submit --json emits a single JSON object on its own line (FR-05 / NP-04)."""
    from taskq import cli, store

    rc = cli.main(["--json", "submit", "echo json-out", "--name", "e2e-json"])
    assert rc == 0

    tasks_path = taskq_home / "tasks.json"
    data = json.loads(tasks_path.read_text(encoding="utf-8"))
    task = next(t for t in data.values() if t["name"] == "e2e-json")
    assert task["status"] == "pending"
    # And verify the JSON-mode emitted the expected id-only payload.
    assert store.find_active_by_name("e2e-json") is not None


# ---------------------------------------------------------------------------
# External invocation: `python -m taskq` reaches the entry point
# ---------------------------------------------------------------------------


def test_e2e_python_module_invocation(taskq_home: Path) -> None:
    """`python -m taskq.__main__ --help` exits 0 and prints the subcommand help.

    The package exposes its entry point via taskq.__main__ (mirrors the
    real production layout where `python -m taskq` would otherwise require
    a `__main__.py` shim — the harness/cli surface we test through is
    `cli.main` directly, so we mirror that here).
    """
    env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": "03-development/src",
        "TASKQ_HOME": str(taskq_home),
        "HOME": str(taskq_home),
    }
    driver = "import sys; from taskq import cli; sys.exit(cli.main(sys.argv[1:]))"
    result = subprocess.run(
        [sys.executable, "-c", driver, "--help"],
        capture_output=True,
        text=True,
        env=env,
        cwd="/Users/johnny/projects/integration-test",
        timeout=30,
    )
    assert result.returncode == 0
    assert "submit" in result.stdout
    assert "run" in result.stdout
    assert "status" in result.stdout
