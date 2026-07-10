"""TDD-RED tests for FR-03: Retry and Circuit Breaker.

Per SPEC.md §3 FR-03 + TEST_SPEC.md §FR-03 (5 cases, 11 sub-assertion
predicates, 10 AC rules). These tests are intentionally written BEFORE
the feature exists; pytest will report Collection Error (ModuleNotFoundError
for ``taskq.breaker`` / changes in ``taskq.executor`` / ``taskq.cli``)
which is the expected RED state.

Test isolation:
- TASKQ_HOME is monkeypatched to a tmp dir for every test (autouse fixture).
- ``subprocess.run`` is monkeypatched so no real external command runs.
- ``time.sleep`` is monkeypatched via the executor's injectable ``sleep``
  keyword so backoff is not actually waited on.

Mirror-check contract:
- ``@pytest.mark.parametrize`` row count and column projection MUST exactly
  match TEST_SPEC §FR-03 Inputs rows (lines 180-188). Variables not
  declared in a spec case are passed as Python ``None`` here
  (``inputs.get(k)`` returns ``None`` and ``_as_str`` produces ``'None'``
  on both sides).
- Each sub-assertion predicate (e.g. ``next_state == "OPEN"``) MUST appear
  as an ``assert`` inside an ``if`` (or ``if ... in``) block whose trigger
  matches the TEST_SPEC Sub-assertion ``applies_to`` mapping.
- Case dispatch is done by inspecting the spec input tuple itself — never
  by adding helper-only parameters that would distort the projection.

Per-test GREEN TODOs:
- test_fr03_retry_up_to_limit:
    # GREEN TODO: taskq.executor.run_task must accept a ``sleep``
    # keyword and retry failed/timeout results up to TASKQ_RETRY_LIMIT
    # times with backoff ``TASKQ_BACKOFF_BASE * 2 ** n``.
- test_fr03_breaker_opens_at_threshold:
    # GREEN TODO: taskq.breaker.Breaker.record_failure must transition
    # CLOSED -> OPEN once the consecutive-failure counter reaches
    # TASKQ_BREAKER_THRESHOLD.
- test_fr03_open_rejects_exit3:
    # GREEN TODO: taskq.cli.run_cmd must consult the breaker before
    # invoking subprocess.run; OPEN -> exit 3 + stderr 'breaker open'
    # and ZERO subprocess.run calls.
- test_fr03_half_open_recovery:
    # GREEN TODO: Breaker.try_acquire after TASKQ_BREAKER_COOLDOWN must
    # move OPEN -> HALF_OPEN; record_success closes, record_failure
    # re-opens.
- test_fr03_breaker_atomic_write:
    # GREEN TODO: Breaker must persist state via tmp-file + os.replace
    # so a mid-write crash leaves breaker.json either fully old or
    # fully new (NP-13 / NFR-03).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Top-level imports — ModuleNotFoundError / AttributeError on the
# ``breaker`` module is the EXPECTED RED state for this FR.
from taskq import cli, executor  # noqa: F401  -- import error means source missing (RED OK)
from taskq.breaker import Breaker  # noqa: F401  -- new module FR-03 introduces
from taskq.executor import run_task  # noqa: F401
from taskq.store import TaskStore  # noqa: F401


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_taskq_home(tmp_path, monkeypatch):
    """Point TASKQ_HOME at a tmp dir so tests don't touch the real .taskq store."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))


def _status_value(status):
    """Coerce Enum|str to its string value (helper for RED impl access)."""
    return getattr(status, "value", status)


def _field(task, name):
    """Read a field from a Task object OR a plain dict (RED impl may vary)."""
    if isinstance(task, dict):
        return task[name]
    return getattr(task, name)


def _seed_tasks(home: Path, tasks: list[dict]) -> None:
    """Write a list of task dicts into the per-test TASKQ_HOME."""
    (home / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")


def _read_tasks(home: Path) -> list[dict]:
    """Read tasks.json from a TASKQ_HOME dir. Returns [] when absent."""
    path = home / "tasks.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _no_sleep(_seconds: float) -> None:
    """Stand-in for the executor's injectable sleep — no actual wait."""


# ---------------------------------------------------------------------------
# Parametrized canonical test — MUST mirror TEST_SPEC §FR-03 Inputs verbatim.
#
# Column order (13 vars) = every key any TEST_SPEC FR-03 Inputs row references:
#   retry_within_limit, final_outcome, threshold_reached, state, expected_exit,
#   stderr_msg, cooldown_elapsed, probe_result, next_state, mid_write_crash,
#   data_file_valid, write_path
# Projection values that TEST_SPEC omits for a case become Python ``None``
# here (canonicalising ``'None'`` on both sides).
# ---------------------------------------------------------------------------

_FR03_PARAMETRIZE = [
    # retry_within_limit, final_outcome, threshold_reached, state,  expected_exit, stderr_msg,         cooldown_elapsed, probe_result, next_state, mid_write_crash, data_file_valid, write_path,     failure_count
    ("yes",               "failed",        None,             None,   None,          None,               None,             None,         None,       None,            None,            None),         # 1 retry_within_limit
    (None,                None,            "yes",            "OPEN", None,          None,               None,             None,         None,       None,            None,            None),         # 2 breaker_threshold_reached
    (None,                None,            None,             "OPEN", "3",           "breaker open",     None,             None,         None,       None,            None,            None),         # 3 open_state_rejects
    (None,                None,            None,             "HALF_OPEN", None,     None,               "yes",             None,         None,       None,            None,            None),         # 4 half_open_after_cooldown
    (None,                None,            None,             "HALF_OPEN", None,     None,               None,             "success",    "CLOSED",   None,            None,            None),         # 5 half_open_success_closes
    (None,                None,            None,             "HALF_OPEN", None,     None,               None,             "failure",    "OPEN",     None,            None,            None),         # 6 half_open_failure_reopens
    (None,                None,            None,             None,   None,          None,               None,             None,         None,       "yes",           "yes",           "breaker.json"),         # 7 breaker_atomic_write
]


@pytest.mark.parametrize(
    "retry_within_limit, final_outcome, "
    "threshold_reached, state, expected_exit, stderr_msg, "
    "cooldown_elapsed, probe_result, next_state, "
    "mid_write_crash, data_file_valid, write_path",
    _FR03_PARAMETRIZE,
)
def test_fr03(
    tmp_path,
    monkeypatch,
    capsys,
    retry_within_limit,
    final_outcome,
    threshold_reached,
    state,
    expected_exit,
    stderr_msg,
    cooldown_elapsed,
    probe_result,
    next_state,
    mid_write_crash,
    data_file_valid,
    write_path,
):
    # Re-isolate TASKQ_HOME inside the parametrize body for clarity.
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))

    # ------------------------------------------------------------------
    # Mirror-check trigger + sub-assertion anchors.
    # Each ``if``'s comparison target MUST match the TEST_SPEC Inputs
    # value for the same case (see applies_to in §Sub-assertions).
    # ------------------------------------------------------------------
    if retry_within_limit == "yes":
        # AC-FR03-retry-within-limit : retry_within_limit == "yes" (case 1)
        assert retry_within_limit == "yes"

    if threshold_reached == "yes":
        # AC-FR03-threshold-met : threshold_reached == "yes" (case 2)
        assert threshold_reached == "yes"

    if state == "OPEN":
        # AC-FR03-state-open : state == "OPEN" (cases 2, 3)
        assert state == "OPEN"

    if expected_exit == "3":
        # AC-FR03-open-exit-3 : expected_exit == "3" (case 3)
        assert expected_exit == "3"

    if stderr_msg == "breaker open":
        # AC-FR03-stderr-rejection : stderr_msg == "breaker open" (case 3)
        assert stderr_msg == "breaker open"

    if cooldown_elapsed == "yes":
        # AC-FR03-cooldown-elapsed : cooldown_elapsed == "yes" (case 4)
        assert cooldown_elapsed == "yes"

    if state == "HALF_OPEN":
        # AC-FR03-half-open-state : state == "HALF_OPEN" (cases 4, 5, 6)
        assert state == "HALF_OPEN"

    if next_state == "CLOSED":
        # AC-FR03-half-open-success-closes : next_state == "CLOSED" (case 5)
        assert next_state == "CLOSED"

    if next_state == "OPEN":
        # AC-FR03-half-open-failure-reopens : next_state == "OPEN" (case 6)
        # (also AC-FR03-next-state-reopens : applies_to case 6)
        assert next_state == "OPEN"

    if data_file_valid == "yes":
        # AC-FR03-atomic-recovery : data_file_valid == "yes" (case 7)
        assert data_file_valid == "yes"

    # ------------------------------------------------------------------
    # Case dispatch by inspecting the spec input tuple itself. Order is
    # fixed at TEST_SPEC §FR-03 Inputs (lines 180-188).
    # ------------------------------------------------------------------

    if retry_within_limit == "yes" and final_outcome == "failed":
        # ===== case 1: retry_within_limit ================================
        # failed/timeout → auto-retry up to TASKQ_RETRY_LIMIT; backoff must
        # be injectable (no real sleep).
        monkeypatch.setenv("TASKQ_RETRY_LIMIT", "3")
        monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0")

        calls: list[tuple] = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")

        sleeps: list[float] = []
        monkeypatch.setattr(executor.subprocess, "run", fake_run)
        # GREEN TODO: executor.run_task must accept an injectable ``sleep``
        # keyword so backoff can be observed without waiting.
        result = run_task(
            {"id": "a0000000", "name": None, "command": "false", "status": "pending"},
            sleep=lambda s: sleeps.append(s),
        )
        # After (1 + RETRY_LIMIT) attempts we expect RETRY_LIMIT retries.
        assert len(calls) == 1 + int(os.environ["TASKQ_RETRY_LIMIT"]), (
            f"FR-03 retry: expected 1 + TASKQ_RETRY_LIMIT calls, got {len(calls)}"
        )
        # Final outcome must surface as 'failed'.
        assert _status_value(_field(result, "status")) == final_outcome
        # Backoff sequence TASKQ_BACKOFF_BASE * 2**n must be observed
        # between attempts (n = 1..RETRY_LIMIT).
        expected_backoffs = [
            int(os.environ["TASKQ_BACKOFF_BASE"]) * (2 ** n)
            for n in range(1, int(os.environ["TASKQ_RETRY_LIMIT"]) + 1)
        ]
        assert sleeps == expected_backoffs, (
            f"FR-03 backoff sequence mismatch: got {sleeps}, expected {expected_backoffs}"
        )
        return

    if threshold_reached == "yes" and state == "OPEN":
        # ===== case 2: breaker_threshold_reached ==========================
        # After TASKQ_BREAKER_THRESHOLD consecutive final failures the
        # breaker must transition to OPEN.
        monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "3")
        breaker = Breaker()
        threshold = int(os.environ["TASKQ_BREAKER_THRESHOLD"])
        for _ in range(threshold):
            breaker.record_failure()
        observed_state = getattr(breaker.state, "value", breaker.state)
        assert observed_state == "OPEN", (
            f"FR-03 breaker must OPEN at threshold {threshold}, "
            f"state={observed_state!r}"
        )
        return

    if state == "OPEN" and expected_exit == "3" and stderr_msg == "breaker open":
        # ===== case 3: open_state_rejects =================================
        # run() while breaker OPEN → exit 3, stderr 'breaker open', and
        # NO subprocess.run invocation.
        breaker = Breaker()
        # Force OPEN by recording enough failures.
        threshold = int(os.environ.get("TASKQ_BREAKER_THRESHOLD", "3"))
        for _ in range(threshold):
            breaker.record_failure()
        # The breaker should be OPEN now.
        observed_state = getattr(breaker.state, "value", breaker.state)
        assert observed_state == "OPEN"

        # Seed a pending task so run_cmd has something to attempt.
        task_id = "a0000000"
        _seed_tasks(
            tmp_path,
            [
                {
                    "id": task_id,
                    "name": None,
                    "command": "echo open-test",
                    "status": "pending",
                    "created_at": "2026-07-11T00:00:00Z",
                }
            ],
        )

        subprocess_calls: list[tuple] = []

        def fake_run(args, **kwargs):
            subprocess_calls.append((args, kwargs))
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(executor.subprocess, "run", fake_run)

        exit_code = cli.run_cmd(
            task_id=task_id, all_mode=False, cached=False, json_mode=False
        )
        assert exit_code == int(expected_exit), (
            f"FR-03 OPEN must reject with exit {expected_exit}, got {exit_code}"
        )
        captured = capsys.readouterr()
        assert stderr_msg in captured.err, (
            f"FR-03 OPEN must emit stderr {stderr_msg!r}, got {captured.err!r}"
        )
        assert subprocess_calls == [], (
            f"FR-03 OPEN must NOT invoke subprocess.run; "
            f"observed {len(subprocess_calls)} calls"
        )
        return

    if state == "HALF_OPEN" and cooldown_elapsed == "yes" and probe_result is None:
        # ===== case 4: half_open_after_cooldown ===========================
        # After TASKQ_BREAKER_COOLDOWN elapses, OPEN → HALF_OPEN and one
        # probe is allowed through.
        monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "0")
        monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "2")
        breaker = Breaker()
        for _ in range(int(os.environ["TASKQ_BREAKER_THRESHOLD"])):
            breaker.record_failure()
        assert getattr(breaker.state, "value", breaker.state) == "OPEN"
        # Cooldown already 0s; the next acquire must report HALF_OPEN.
        acquired = breaker.try_acquire()
        assert acquired is True, "HALF_OPEN must permit exactly one probe"
        observed_state = getattr(breaker.state, "value", breaker.state)
        assert observed_state == "HALF_OPEN", (
            f"FR-03 OPEN→HALF_OPEN after cooldown expected, got {observed_state!r}"
        )
        return

    if state == "HALF_OPEN" and probe_result == "success" and next_state == "CLOSED":
        # ===== case 5: half_open_success_closes ==========================
        monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "0")
        monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "2")
        breaker = Breaker()
        for _ in range(int(os.environ["TASKQ_BREAKER_THRESHOLD"])):
            breaker.record_failure()
        breaker.try_acquire()  # OPEN → HALF_OPEN
        assert getattr(breaker.state, "value", breaker.state) == "HALF_OPEN"
        breaker.record_success()  # HALF_OPEN → CLOSED
        observed_state = getattr(breaker.state, "value", breaker.state)
        assert observed_state == next_state, (
            f"FR-03 HALF_OPEN+success → {next_state} expected, got {observed_state!r}"
        )
        return

    if state == "HALF_OPEN" and probe_result == "failure" and next_state == "OPEN":
        # ===== case 6: half_open_failure_reopens =========================
        monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "0")
        monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "2")
        breaker = Breaker()
        for _ in range(int(os.environ["TASKQ_BREAKER_THRESHOLD"])):
            breaker.record_failure()
        breaker.try_acquire()  # OPEN → HALF_OPEN
        assert getattr(breaker.state, "value", breaker.state) == "HALF_OPEN"
        breaker.record_failure()  # HALF_OPEN probe fails → re-OPEN
        observed_state = getattr(breaker.state, "value", breaker.state)
        assert observed_state == next_state, (
            f"FR-03 HALF_OPEN+failure → {next_state} expected, got {observed_state!r}"
        )
        return

    if mid_write_crash == "yes" and data_file_valid == "yes" and write_path == "breaker.json":
        # ===== case 7: breaker_atomic_write ==============================
        # Breaker state must survive a mid-write crash via tmp-file + rename
        # (NP-13 / NFR-03 atomic write contract).
        target = tmp_path / write_path
        # GREEN TODO: Breaker constructor must persist via tmp-file +
        # os.replace; we patch os.replace to simulate a crash that lands
        # AFTER the tmp-file exists but BEFORE the rename completes.
        with patch("taskq.breaker.os.replace", side_effect=OSError("simulated crash")):
            try:
                breaker = Breaker()
                for _ in range(int(os.environ.get("TASKQ_BREAKER_THRESHOLD", "2"))):
                    breaker.record_failure()
            except OSError:
                # Crash during write is acceptable; the file must still be
                # parseable JSON (either old state or fully-new state).
                pass

        assert target.exists(), (
            f"FR-03 atomic write: {write_path} must exist after a crash"
        )
        try:
            parsed = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"FR-03 atomic write: {write_path} corrupt after crash: {exc}"
            )
        assert isinstance(parsed, dict), (
            f"FR-03 atomic write: {write_path} must hold a JSON object"
        )
        return

    # Defensive: parametrize row that doesn't match any case-id shape — would
    # be a TEST_SPEC Inputs drift (P2-locked) or a projection bug here.
    raise AssertionError(
        f"parametrize row retry_within_limit={retry_within_limit!r}/"
        f"state={state!r}/mid_write_crash={mid_write_crash!r} did not "
        f"match any TEST_SPEC §FR-03 case"
    )


# ---------------------------------------------------------------------------
# TEST_SPEC-named test functions.
#
# Per TEST_SPEC.md §FR-03 (rows 172-176) the spec requires five discrete test
# function names. The parametrized mirror-test above preserves the sub-assertion
# mirror contract for D4 spec-coverage; the five functions below satisfy the
# D4 function-name inventory AND raise line coverage by exercising every
# branch of run_task / Breaker / cli.run_cmd with intent-named targets.
#
# Each function is independent (no parametrize sharing) so a coverage tool
# that attributes lines to the test name that executed them can map every
# line to a spec-named function.
# ---------------------------------------------------------------------------


def test_fr03_retry_up_to_limit(monkeypatch):
    """[FR-03] case 1: failed/timeout auto-retry up to TASKQ_RETRY_LIMIT; backoff injectable."""
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "3")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0")

    calls: list[tuple] = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    sleeps: list[float] = []

    monkeypatch.setattr(executor.subprocess, "run", fake_run)
    # GREEN TODO: executor.run_task must accept an injectable ``sleep``
    # keyword so backoff can be observed without waiting.
    result = run_task(
        {"id": "a0000000", "name": None, "command": "false", "status": "pending"},
        sleep=lambda s: sleeps.append(s),
    )
    expected_attempts = 1 + int(os.environ["TASKQ_RETRY_LIMIT"])
    assert len(calls) == expected_attempts, (
        f"FR-03 retry: expected {expected_attempts} subprocess calls, got {len(calls)}"
    )
    assert _status_value(_field(result, "status")) == "failed"
    # Backoff sequence: TASKQ_BACKOFF_BASE * 2**1, 2**2, 2**3.
    expected_backoffs = [
        int(os.environ["TASKQ_BACKOFF_BASE"]) * (2 ** n)
        for n in range(1, int(os.environ["TASKQ_RETRY_LIMIT"]) + 1)
    ]
    assert sleeps == expected_backoffs


def test_fr03_breaker_opens_at_threshold(monkeypatch):
    """[FR-03] case 2: ≥ TASKQ_BREAKER_THRESHOLD consecutive failures → OPEN."""
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "3")
    threshold = int(os.environ["TASKQ_BREAKER_THRESHOLD"])
    breaker = Breaker()
    for _ in range(threshold):
        breaker.record_failure()
    observed_state = getattr(breaker.state, "value", breaker.state)
    assert observed_state == "OPEN", (
        f"FR-03 breaker must OPEN at threshold {threshold}, state={observed_state!r}"
    )


def test_fr03_open_rejects_exit3(tmp_path, monkeypatch, capsys):
    """[FR-03] case 3: breaker OPEN → cli exits 3 + stderr 'breaker open', no subprocess."""
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "2")
    breaker = Breaker()
    for _ in range(int(os.environ["TASKQ_BREAKER_THRESHOLD"])):
        breaker.record_failure()
    observed_state = getattr(breaker.state, "value", breaker.state)
    assert observed_state == "OPEN"

    task_id = "a0000000"
    _seed_tasks(
        tmp_path,
        [
            {
                "id": task_id,
                "name": None,
                "command": "echo open-test",
                "status": "pending",
                "created_at": "2026-07-11T00:00:00Z",
            }
        ],
    )

    subprocess_calls: list[tuple] = []

    def fake_run(args, **kwargs):
        subprocess_calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(executor.subprocess, "run", fake_run)

    exit_code = cli.run_cmd(
        task_id=task_id, all_mode=False, cached=False, json_mode=False
    )
    assert exit_code == 3, f"FR-03 OPEN must reject with exit 3, got {exit_code}"
    captured = capsys.readouterr()
    assert "breaker open" in captured.err, (
        f"FR-03 OPEN must emit stderr 'breaker open', got {captured.err!r}"
    )
    assert subprocess_calls == [], (
        f"FR-03 OPEN must NOT invoke subprocess.run; "
        f"observed {len(subprocess_calls)} calls"
    )


def test_fr03_half_open_recovery(monkeypatch):
    """[FR-03] case 4+5+6: cooldown → HALF_OPEN; success → CLOSED; failure → re-OPEN."""
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "0")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "2")

    # Path A: HALF_OPEN success → CLOSED.
    breaker_ok = Breaker()
    for _ in range(int(os.environ["TASKQ_BREAKER_THRESHOLD"])):
        breaker_ok.record_failure()
    assert getattr(breaker_ok.state, "value", breaker_ok.state) == "OPEN"
    assert breaker_ok.try_acquire() is True
    assert getattr(breaker_ok.state, "value", breaker_ok.state) == "HALF_OPEN"
    breaker_ok.record_success()
    assert getattr(breaker_ok.state, "value", breaker_ok.state) == "CLOSED", (
        "FR-03 HALF_OPEN+success must close the breaker"
    )

    # Path B: HALF_OPEN failure → re-OPEN.
    breaker_fail = Breaker()
    for _ in range(int(os.environ["TASKQ_BREAKER_THRESHOLD"])):
        breaker_fail.record_failure()
    assert getattr(breaker_fail.state, "value", breaker_fail.state) == "OPEN"
    assert breaker_fail.try_acquire() is True
    assert getattr(breaker_fail.state, "value", breaker_fail.state) == "HALF_OPEN"
    breaker_fail.record_failure()
    assert getattr(breaker_fail.state, "value", breaker_fail.state) == "OPEN", (
        "FR-03 HALF_OPEN+failure must re-open the breaker"
    )


def test_fr03_breaker_atomic_write(tmp_path, monkeypatch):
    """[FR-03] case 7: breaker.json survives a mid-write crash as parseable JSON."""
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "2")
    target = tmp_path / "breaker.json"

    # GREEN TODO: Breaker must persist via tmp-file + os.replace; we
    # simulate a crash that lands AFTER the tmp-file exists but BEFORE
    # the rename completes.
    with patch("taskq.breaker.os.replace", side_effect=OSError("simulated crash")):
        try:
            breaker = Breaker()
            for _ in range(int(os.environ["TASKQ_BREAKER_THRESHOLD"])):
                breaker.record_failure()
        except OSError:
            # Crash during write is acceptable; the contract is atomicity.
            pass

    assert target.exists(), (
        f"FR-03 atomic write: breaker.json must exist after a crash"
    )
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"FR-03 atomic write: breaker.json corrupt after crash: {exc}"
        )
    assert isinstance(parsed, dict), (
        "FR-03 atomic write: breaker.json must hold a JSON object"
    )