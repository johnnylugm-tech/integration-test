"""[bug-hunt 2026-07-07 round-2] Repro test for FR-03 breaker double-counting.

Bug: ``taskq.executor.execute`` records each failed retry attempt on the
breaker via ``_breaker.check_and_record(success=False)`` (executor.py:268),
AND ``taskq.cli._finalize_run`` records the SAME final outcome via
``breaker.check_and_record(success=(result.status == "done"))`` (cli.py:130).

SPEC.md §3 FR-03 contract: "連續最終失敗(重試耗盡仍 failed/timeout)計數
≥ ``TASKQ_BREAKER_THRESHOLD`` → OPEN". Each TASK's terminal outcome is ONE
"consecutive final failure" event, regardless of how many retry attempts
happened inside the executor. Counting EACH retry attempt separately is a
double-count that violates the spec.

Production impact with default TASKQ_BREAKER_THRESHOLD=3 and
TASKQ_RETRY_LIMIT=2:

  * Task fails once, exhausts retries (3 attempts).
  * executor.execute calls ``check_and_record(success=False)`` 3x during
    its retry loop (once per attempt).
  * cli._finalize_run then calls ``check_and_record(success=False)`` once
    more for the same terminal "failed" outcome.
  * Net: a single failing task increments ``failure_count`` by 4 — the
    breaker opens after ONE failing task instead of three.

This test pins the spec: ``cli._finalize_run`` MUST NOT record again on
"failed"/"timeout" status, because executor.execute is already the SOLE
recorder for failure-side outcomes (per executor.py:263-265 "breaker is
wired ONLY for failure-driven state transitions").

REGRESSION assertions:

  1. After one failing task via cli.run, ``breaker.json.failure_count == 1``
     (NOT 2 as today).
  2. After three failing tasks via cli.run, breaker state MUST be
     ``CLOSED`` (NOT ``OPEN`` — only final-failures count, threshold is 3).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from taskq import cli


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Isolate storage under a tmp $TASKQ_HOME."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")  # no retries → 1 record attempt per task
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "3")
    return tmp_path


def _read_breaker_json(home_dir: Path) -> dict:
    return json.loads((home_dir / "breaker.json").read_text(encoding="utf-8"))


def _submit_one(home, command: str) -> str:
    """Submit one task via cli.main and return its id."""
    rc = cli.main(["submit", command])
    assert rc == 0, f"submit failed with rc={rc}"
    data = json.loads((home / "tasks.json").read_text(encoding="utf-8"))
    # Pick the latest task by created_at to handle test fixtures that
    # don't fully isolate between tests.
    return max(data.items(), key=lambda kv: kv[1].get("created_at", ""))[0] if data else None


def _run_one(home, task_id: str) -> int:
    """Run a task via cli.main and return rc."""
    return cli.main(["run", task_id])


def test_double_count_one_task(home):
    """REGRESSION: one failing task → failure_count == 1 (not 2)."""
    task_id = _submit_one(home, command="false")  # `false` exits 1

    rc = _run_one(home, task_id)
    assert rc == 1  # FR-02 exit code: subprocess returned 1

    data = _read_breaker_json(home)
    assert data.get("failure_count") == 1, (
        f"Expected failure_count == 1 after ONE failing task, got "
        f"failure_count={data.get('failure_count')} (double-counting bug)."
    )


def test_double_count_threshold(home):
    """REGRESSION: 3 failing tasks via cli → 3rd task actually executes.

    With TASKQ_BREAKER_THRESHOLD=3 the breaker should OPEN ON the 3rd
    final failure (SPEC.md §3 FR-03 "連續最終失敗計數 ≥ threshold →
    OPEN"). Double-counting inside execute()+cli._finalize_run() makes
    the breaker OPEN prematurely after the 2nd task, blocking the 3rd
    task from even running. This test asserts that all 3 task runs
    were attempted (rc=1 for each, NOT rc=3 "breaker open" for any).
    """
    rcs = []
    for _ in range(3):
        task_id = _submit_one(home, command="false")
        rcs.append(_run_one(home, task_id))

    # All 3 task runs should have actually executed (rc=1 for "false"
    # command). The 3rd one should NOT be rejected by an OPEN breaker
    # (rc=3) — that would be the double-counting bug.
    assert rcs == [1, 1, 1], (
        f"Expected all 3 failing tasks to actually execute (rc=1 each). "
        f"Got rcs={rcs}. If the last one is 3, the breaker OPEN'd "
        f"prematurely due to double-counting bug."
    )
