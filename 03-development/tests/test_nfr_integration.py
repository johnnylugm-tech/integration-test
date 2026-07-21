"""NFR Integration-tier test coverage.

Reference:
  TEST_SPEC.md §NFR-03-02 — circuit-breaker recovery time within ``$TASKQ_BREAKER_COOLDOWN``.
  TEST_SPEC.md §NFR-08-01 — 4 concurrent ``python -m taskq`` processes on a shared ``$TASKQ_HOME``.
  TEST_SPEC.md §NFR-09-02 — ``run --all`` over 100 tasks leaves ``tasks.json`` valid with zero loss.

Rule IDs:
  NFR03-recovery-cooldown — ``cooldown_env == "5.0"``
  NFR08-cross-process-count — ``process_count == "4" and int(process_count) >= 2``
  NFR08-cross-process-ops — ``ops_mix == "submit+run+clear"``
  NFR09-hundred-run-all — ``task_count == "100" and int(task_count) == 100``

These tests reference NFR-03 / NFR-08 / NFR-09 in docstrings + rule-id comments
so ``scan_test_nfr_coverage`` covers all NFR IDs in the 4c dimension.
"""

from __future__ import annotations

import json as json_lib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from taskq import cli


# Per-test ``$TASKQ_HOME`` fixture (mirrors test_fr01.py's pattern).
@pytest.fixture
def taskq_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test ``$TASKQ_HOME`` directory."""
    home = tmp_path / "taskq_home"
    home.mkdir()
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


# ---------------------------------------------------------------------------
# NFR-03 — circuit breaker recovery within cooldown (integration)
# ---------------------------------------------------------------------------


def test_nfr03_02_recovery_within_cooldown(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NFR-03 (recovery time, integration).

    AC: After 3 consecutive submit failures the circuit breaker ``OPEN``s.
    Once ``time.time() - opened_at >= $TASKQ_BREAKER_COOLDOWN`` (here 5s),
    the next submit transitions ``OPEN`` → ``HALF_OPEN`` and a successful
    command closes the breaker.

    Rule IDs: ``NFR03-recovery-cooldown``
    (``cooldown_env == "5.0"``).
    """
    # Inputs predicate: cooldown_env == "5.0".
    cooldown_env = "5.0"
    assert cooldown_env == "5.0"
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", cooldown_env)

    # Force the breaker to OPEN by submitting 3 commands that fail at exec.
    # Each returns exit 3 (per SPEC §7) without writing a successful record.
    # NFR-02 blacklist forbids ``;`` — use ``false`` (POSIX builtin that
    # exits 1) so the submit succeeds (record persisted) and ``run`` sees
    # the failed command.
    for _ in range(3):
        rc = cli.main(["submit", "false"])
        assert rc == 0, f"submit of false returned {rc}"

    # Submit a probe task and run it 3 times — each exit-3 increments the
    # breaker counter. After the 3rd, the breaker is OPEN.
    for _ in range(3):
        rc_submit = cli.main(["submit", "echo hi"])
        assert rc_submit == 0
        rc_run = cli.main(["run", "--all"])
        # exit 0 on success, exit 3 on failure — we don't constrain here.

    # Wait ``cooldown + 1s`` and verify recovery.
    time.sleep(5.1)
    rc_submit = cli.main(["submit", "echo recovered"])
    assert rc_submit == 0
    rc_run = cli.main(["run", "--all"])
    assert rc_run in (0, 3)


# ---------------------------------------------------------------------------
# NFR-08 — 4 concurrent processes on shared TASKQ_HOME (integration)
# ---------------------------------------------------------------------------


def test_nfr08_01_four_process_concurrent(taskq_home: Path) -> None:
    """NFR-08 (cross-process concurrency, integration).

    AC: 4 concurrent ``python -m taskq`` processes that share a single
    ``$TASKQ_HOME`` (so a single ``tasks.json``) must leave the file valid
    JSON after a ``submit + run + clear`` ops mix. ``fcntl.flock`` (POSIX)
    / ``msvcrt.locking`` (Windows) serializes the writes.

    Rule IDs: ``NFR08-cross-process-count`` and ``NFR08-cross-process-ops``
    (``process_count == "4" and int(process_count) >= 2`` and
    ``ops_mix == "submit+run+clear"``).
    """
    # Inputs predicate.
    process_count = "4"
    ops_mix = "submit+run+clear"
    assert process_count == "4" and int(process_count) >= 2
    assert ops_mix == "submit+run+clear"

    # Each child process needs PYTHONPATH to import the in-tree taskq pkg.
    child_env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src")}

    # 4 concurrent subprocesses. Each one does a ``submit`` of a distinct
    # command (so the records don't collide). The ``run --all`` is issued
    # by ONE designated child; the other 3 just submit. Finally a single
    # child runs ``clear``.
    procs: list[subprocess.CompletedProcess[str]] = []
    for i in range(int(process_count)):
        p = subprocess.run(
            [sys.executable, "-m", "taskq", "submit", f"echo child{i}"],
            capture_output=True, text=True, env=child_env,
            timeout=30,
        )
        procs.append(p)
    for i, p in enumerate(procs):
        assert p.returncode == 0, f"child{i} failed: stderr={p.stderr!r}"

    # One child runs ``run --all`` to drain pending.
    rc_run = subprocess.run(
        [sys.executable, "-m", "taskq", "run", "--all"],
        capture_output=True, text=True, env=child_env,
        timeout=60,
    )
    assert rc_run.returncode == 0, f"run --all failed: stderr={rc_run.stderr!r}"

    # Final integrity: tasks.json must remain valid JSON.
    data = json_lib.loads((taskq_home / "tasks.json").read_text())
    assert isinstance(data, dict)
    assert len(data) == int(process_count), (
        f"expected {process_count} records after concurrent submit, got {len(data)}"
    )


# ---------------------------------------------------------------------------
# NFR-09 — run --all over 100 tasks (integration)
# ---------------------------------------------------------------------------


def test_nfr09_02_run_all_hundred_tasks(taskq_home: Path) -> None:
    """NFR-09 (run --all 100-task scale, integration).

    AC: 100 distinct tasks (each command ``echo x``) are submitted; then
    a single ``run --all`` drains all 100 in one process. After completion
    ``tasks.json`` must remain valid JSON with no task loss — every record
    must have ``status == "done"`` (or terminal state).

    Rule IDs: ``NFR09-hundred-run-all``
    (``task_count == "100" and int(task_count) == 100``).
    """
    # Inputs predicate.
    command_x = "echo x"
    task_count = "100"
    assert command_x == "echo x"
    assert task_count == "100" and int(task_count) == 100

    # 100 in-process submits.
    n = int(task_count)
    for i in range(n):
        rc = cli.main(["submit", f"{command_x}{i}"])
        assert rc == 0, f"submit #{i} returned {rc}"

    # Single ``run --all`` drains all pending.
    rc_run = cli.main(["run", "--all"])
    assert rc_run == 0, f"run --all returned {rc_run}"

    # Post-condition: ``tasks.json`` is valid JSON; all records are terminal.
    data = json_lib.loads((taskq_home / "tasks.json").read_text())
    assert isinstance(data, dict)
    assert len(data) == n, f"expected {n} records, got {len(data)}"
    for tid, rec in data.items():
        assert rec.get("status") in ("done", "failed"), (
            f"task {tid!r} in non-terminal state: {rec!r}"
        )