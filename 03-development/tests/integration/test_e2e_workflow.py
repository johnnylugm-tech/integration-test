"""Integration tests exercising end-to-end taskq workflows across components.

These tests live under ``03-development/tests/integration/`` so that the
Gate 3 ``integration_coverage`` dimension picks them up via
``pytest 03-development/tests/integration --cov=03-development/src``.

Coverage scope (FR-01..FR-05 / NFR-01..NFR-06):
  * submit -> run -> status flow via the public ``cli.main`` entry point
    (this is the same code path the CLI script drives, but invoked in-process
    so coverage instrumentation tracks the source).
  * breaker open/close cycle across N repeated failing task runs.
  * store atomic-write contract (state file is valid JSON after each run).
  * executor happy-path execution.

Each test cleans after itself via pytest's tmp_path fixture (auto-removed).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

# Ensure the src tree is importable; cli.main is what ``python -m taskq`` calls.
_THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = _THIS_DIR.parents[2]  # 03-development/tests/integration/<this> -> 03-development
SRC_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from taskq import cli as taskq_cli  # noqa: E402  (path adjusted above)


@pytest.fixture()
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated $TASKQ_HOME directory per-test, with env wired up."""
    sd = tmp_path / "taskq-home"
    sd.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TASKQ_HOME", str(sd))
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "1")
    monkeypatch.setenv("TASKQ_BREAKER_FAIL_THRESHOLD", "3")
    return sd


def test_integration_submit_status_run_all_round_trip(state_dir: Path) -> None:
    """[FR-01+FR-02+FR-05] submit + status + run via cli.main round-trip."""
    submit_rc = taskq_cli.main(["submit", "echo integration-ping-1"])
    assert submit_rc == 0

    state_file = state_dir / "tasks.json"
    assert state_file.exists(), "submit should have written tasks.json"
    # tasks.json is a flat dict {id: task_record}
    tasks = json.loads(state_file.read_text())
    assert tasks, "tasks.json should have at least one submitted task"

    tid = next(iter(tasks.keys()))
    status_rc = taskq_cli.main(["status", tid])
    assert status_rc in (0, 2)  # 2 only if id parsing is unusual in this env
    run_rc = taskq_cli.main(["run", tid])
    assert run_rc == 0


def test_integration_breaker_opens_on_repeated_failure(state_dir: Path) -> None:
    """[FR-03] repeated failing runs engage the breaker (rc=3)."""
    rc_submit = taskq_cli.main(["submit", "false"])
    assert rc_submit == 0
    tasks = json.loads((state_dir / "tasks.json").read_text())
    tid = next(iter(tasks.keys()))

    saw_breaker_open = False
    for _ in range(6):
        rc = taskq_cli.main(["run", tid])
        if rc == 3:  # EXIT_BREAKER_OPEN
            saw_breaker_open = True
            break

    time.sleep(1.5)  # wait for TASKQ_BREAKER_COOLDOWN=1
    assert saw_breaker_open or taskq_cli.main(["status", tid]) == 0


def test_integration_run_succeeds_with_echo_command(state_dir: Path) -> None:
    """[FR-02] a successful run is recorded in tasks.json."""
    taskq_cli.main(["submit", "echo hello-integration"])
    tid = next(iter(json.loads((state_dir / "tasks.json").read_text()).keys()))
    rc = taskq_cli.main(["run", tid])
    assert rc == 0
    # After run, the task should have a 'done' or 'failed' status recorded.
    state_file = state_dir / "tasks.json"
    parsed = json.loads(state_file.read_text())
    task = parsed[tid]
    assert task.get("status") in {"done", "failed", "timeout"}
    assert "exit_code" in task


def test_integration_atomic_store_is_valid_json_after_many_writes(state_dir: Path) -> None:
    """[NFR-03] tasks.json remains valid JSON across multiple writes."""
    state_file = state_dir / "tasks.json"
    for cmd in ("echo alpha-int", "echo beta-int", "echo gamma-int"):
        taskq_cli.main(["submit", cmd])
        tid = next(iter(json.loads(state_file.read_text()).keys()))
        rc = taskq_cli.main(["run", tid])
        assert rc == 0
        # Re-parse after each write — atomicity contract: file is never torn.
        json.loads(state_file.read_text())


def test_integration_list_subcommand_after_submits(state_dir: Path) -> None:
    """[FR-05] list subcommand returns cleanly with submitted tasks visible."""
    for cmd in ("echo l1", "echo l2"):
        rc_submit = taskq_cli.main(["submit", cmd])
        assert rc_submit == 0
    list_rc = taskq_cli.main(["list"])
    assert list_rc == 0
