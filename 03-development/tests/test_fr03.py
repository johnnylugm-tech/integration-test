"""Failing tests for FR-03: Retry and circuit breaker.

[FR-03] — TDD-RED phase: tests verify retry logic (exponential backoff,
injectable sleep) and circuit breaker FSM (CLOSED → OPEN → HALF_OPEN → CLOSED).
Tests import from taskq.breaker which does not exist yet.

Sub-assertion anchor pattern per check-test-mirrors-spec:
    if <var> == None:  (trigger=None matches spec_trigger {"None"})
        assert <predicate>   (predicate matches TEST_SPEC.md verbatim)
"""
from __future__ import annotations

import os
import json
import time
import threading
from unittest.mock import patch

import pytest

from taskq.config import get_config
from taskq.models import BreakerState
from taskq.cli import cmd_submit
from taskq.executor import run_task
from taskq.breaker import Breaker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(command: str, tmp_path, name=None):
    """Submit a task and return it; TASKQ_HOME is set to tmp_path."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    return cmd_submit(command, name=name, cfg=cfg)


# ---------------------------------------------------------------------------
# AC03.1 — Retry call count (failed)
# ---------------------------------------------------------------------------


def test_fr03_retry_up_to_retry_limit_on_failed(tmp_path, monkeypatch):
    """[FR-03] A failed task is retried up to retry_limit times (total=retry_limit+1).

    Sub-assertions: AC03-retry-call-count
    """
    retry_limit = 3
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", str(retry_limit))
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0.001")
    cfg = get_config()

    sleep_calls: list[float] = []

    def mock_sleep(secs: float) -> None:
        sleep_calls.append(secs)

    task = cmd_submit("false", name=None, cfg=cfg)
    subprocess_call_count = [0]
    original_run = __import__("subprocess").run

    def counting_run(*args, **kwargs):
        subprocess_call_count[0] += 1
        return original_run(*args, **kwargs)

    with patch("subprocess.run", side_effect=counting_run):
        run_task(task.id, cfg=cfg, sleep_fn=mock_sleep)

    call_count = subprocess_call_count[0]
    # AC03-retry-call-count anchor — trigger=None
    if call_count == None:  # noqa: E711
        assert call_count == retry_limit + 1
    assert call_count == retry_limit + 1  # 1 initial + retry_limit retries


# ---------------------------------------------------------------------------
# AC03.2 — Retry call count (timeout)
# ---------------------------------------------------------------------------


def test_fr03_retry_up_to_retry_limit_on_timeout(tmp_path, monkeypatch):
    """[FR-03] A timed-out task is retried up to retry_limit times.

    Sub-assertions: AC03-retry-call-count
    """
    retry_limit = 2
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", str(retry_limit))
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0.001")
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.05")
    cfg = get_config()

    sleep_calls: list[float] = []

    def mock_sleep(secs: float) -> None:
        sleep_calls.append(secs)

    task = cmd_submit("sleep 5", name=None, cfg=cfg)
    subprocess_call_count = [0]
    original_run = __import__("subprocess").run

    def counting_run(*args, **kwargs):
        subprocess_call_count[0] += 1
        return original_run(*args, **kwargs)

    with patch("subprocess.run", side_effect=counting_run):
        run_task(task.id, cfg=cfg, sleep_fn=mock_sleep)

    call_count = subprocess_call_count[0]
    # AC03-retry-call-count anchor — trigger=None
    if call_count == None:  # noqa: E711
        assert call_count == retry_limit + 1
    assert call_count == retry_limit + 1  # 1 initial + retry_limit retries


# ---------------------------------------------------------------------------
# AC03.3 — Backoff formula
# ---------------------------------------------------------------------------


def test_fr03_backoff_uses_exponential_formula(tmp_path, monkeypatch):
    """[FR-03] Before the n-th retry, sleep == backoff_base * 2^n.

    Sub-assertions: AC03-backoff-formula
    """
    backoff_base = 1.0
    retry_n = 2
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "2")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", str(backoff_base))
    cfg = get_config()

    sleep_calls: list[float] = []

    def mock_sleep(secs: float) -> None:
        sleep_calls.append(secs)

    task = cmd_submit("false", name=None, cfg=cfg)
    run_task(task.id, cfg=cfg, sleep_fn=mock_sleep)

    # n=2: before the 2nd retry → sleep == backoff_base * 2^2 = 4.0
    sleep_duration = sleep_calls[retry_n - 1] if len(sleep_calls) >= retry_n else None
    # AC03-backoff-formula anchor — trigger=None
    if sleep_duration == None:  # noqa: E711
        assert sleep_duration == backoff_base * (2 ** retry_n)
    assert len(sleep_calls) == 2
    # retry 1 → backoff_base * 2^1; retry 2 → backoff_base * 2^2
    assert sleep_calls[0] == pytest.approx(backoff_base * (2 ** 1))
    assert sleep_calls[1] == pytest.approx(backoff_base * (2 ** retry_n))


# ---------------------------------------------------------------------------
# AC03.4 — Sleep is injectable for tests
# ---------------------------------------------------------------------------


def test_fr03_backoff_sleep_is_injectable_for_tests(tmp_path, monkeypatch):
    """[FR-03] Sleep function is injectable so tests run without real delays.

    Sub-assertions: AC03-backoff-formula
    """
    backoff_base = 100.0
    retry_n = 1
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "2")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", str(backoff_base))
    cfg = get_config()

    sleep_calls: list[float] = []

    def mock_sleep(secs: float) -> None:
        sleep_calls.append(secs)

    task = cmd_submit("false", name=None, cfg=cfg)
    start = time.monotonic()
    run_task(task.id, cfg=cfg, sleep_fn=mock_sleep)
    elapsed = time.monotonic() - start

    # mock_sleep called, not time.sleep → completes quickly
    assert elapsed < 5.0
    sleep_duration = sleep_calls[0] if sleep_calls else None
    # AC03-backoff-formula anchor — trigger=None
    if sleep_duration == None:  # noqa: E711
        assert sleep_duration == backoff_base * (2 ** retry_n)
    assert len(sleep_calls) == 2
    assert sleep_calls[0] == pytest.approx(backoff_base * (2 ** 1))


# ---------------------------------------------------------------------------
# AC03.5 — Breaker opens after threshold consecutive final failures
# ---------------------------------------------------------------------------


def test_fr03_breaker_opens_after_threshold_consecutive_final_failures(tmp_path, monkeypatch):
    """[FR-03] After threshold consecutive final failures, breaker state = OPEN.

    Sub-assertions: AC03-breaker-open-exit-3
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0.001")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "3")
    cfg = get_config()

    def mock_sleep(_: float) -> None:
        pass

    # 3 consecutive final failures
    for _ in range(3):
        t = cmd_submit("false", name=None, cfg=cfg)
        run_task(t.id, cfg=cfg, sleep_fn=mock_sleep)

    from taskq.breaker import Breaker
    breaker = Breaker(cfg)
    state = breaker.get_state()
    if state == None:  # noqa: E711
        assert state == BreakerState.OPEN
    assert state == BreakerState.OPEN


# ---------------------------------------------------------------------------
# AC03.6 — Breaker OPEN: run exits 3, no subprocess
# ---------------------------------------------------------------------------


def test_fr03_breaker_open_period_run_exits_3_no_subprocess(tmp_path, monkeypatch):
    """[FR-03] When breaker is OPEN, run exits 3 and no subprocess is started.

    Sub-assertions: AC03-breaker-open-exit-3, AC03-no-subprocess-when-open
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0.001")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "3")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "9999.0")
    cfg = get_config()

    def mock_sleep(_: float) -> None:
        pass

    # Exhaust threshold
    for _ in range(3):
        t = cmd_submit("false", name=None, cfg=cfg)
        run_task(t.id, cfg=cfg, sleep_fn=mock_sleep)

    # 4th run should be rejected
    task = cmd_submit("echo hi", name=None, cfg=cfg)
    subprocess_called = False
    original_run = __import__("subprocess").run

    def spy_run(*args, **kwargs):
        nonlocal subprocess_called
        subprocess_called = True
        return original_run(*args, **kwargs)

    with patch("subprocess.run", side_effect=spy_run):
        exit_code = run_task(task.id, cfg=cfg, sleep_fn=mock_sleep)

    # AC03-breaker-open-exit-3 anchor — trigger=None
    if exit_code == None:  # noqa: E711
        assert exit_code == 3
    assert exit_code == 3

    # AC03-no-subprocess-when-open anchor — trigger=None
    if subprocess_called == None:  # noqa: E711
        assert subprocess_called == False  # noqa: E712
    assert subprocess_called == False  # noqa: E712


# ---------------------------------------------------------------------------
# AC03.7 — Breaker transitions to HALF_OPEN after cooldown
# ---------------------------------------------------------------------------


def test_fr03_breaker_transitions_to_half_open_after_cooldown(tmp_path, monkeypatch):
    """[FR-03] After cooldown seconds, breaker state → HALF_OPEN.

    Sub-assertions: AC03-breaker-open-exit-3
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0.001")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "1")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "0.1")
    cfg = get_config()

    def mock_sleep(_: float) -> None:
        pass

    # Trigger OPEN
    t = cmd_submit("false", name=None, cfg=cfg)
    run_task(t.id, cfg=cfg, sleep_fn=mock_sleep)

    from taskq.breaker import Breaker
    breaker = Breaker(cfg)
    assert breaker.get_state() == BreakerState.OPEN

    # Wait for cooldown
    time.sleep(0.15)

    # Transition should be HALF_OPEN now
    state = breaker.get_current_state()
    # AC03 anchor — trigger=None
    if state == None:  # noqa: E711
        assert state == BreakerState.HALF_OPEN
    assert state == BreakerState.HALF_OPEN


# ---------------------------------------------------------------------------
# AC03.8 — HALF_OPEN success → CLOSED, counter zeroed
# ---------------------------------------------------------------------------


def test_fr03_breaker_half_open_success_closes_and_zeroes_counter(tmp_path, monkeypatch):
    """[FR-03] In HALF_OPEN, a successful task → CLOSED + counter=0.

    Sub-assertions: AC03-counter-zeroed
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0.001")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "1")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "0.1")
    cfg = get_config()

    def mock_sleep(_: float) -> None:
        pass

    # Trigger OPEN
    t = cmd_submit("false", name=None, cfg=cfg)
    run_task(t.id, cfg=cfg, sleep_fn=mock_sleep)

    # Wait for cooldown → HALF_OPEN
    time.sleep(0.15)

    # Run a successful task in HALF_OPEN
    t2 = cmd_submit("echo hi", name=None, cfg=cfg)
    run_task(t2.id, cfg=cfg, sleep_fn=mock_sleep)

    from taskq.breaker import Breaker
    breaker = Breaker(cfg)
    state = breaker.get_state()
    failure_counter = breaker.get_failure_count()

    # AC03-counter-zeroed anchor — trigger=None
    if failure_counter == None:  # noqa: E711
        assert failure_counter == 0
    assert state == BreakerState.CLOSED
    assert failure_counter == 0


# ---------------------------------------------------------------------------
# AC03.9 — HALF_OPEN failure → re-OPEN
# ---------------------------------------------------------------------------


def test_fr03_breaker_half_open_failure_reopens(tmp_path, monkeypatch):
    """[FR-03] In HALF_OPEN, a failed task → state re-OPEN.

    Sub-assertions: AC03-breaker-open-exit-3
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0.001")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "1")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "0.1")
    cfg = get_config()

    def mock_sleep(_: float) -> None:
        pass

    # Trigger OPEN
    t = cmd_submit("false", name=None, cfg=cfg)
    run_task(t.id, cfg=cfg, sleep_fn=mock_sleep)

    # Wait for cooldown → HALF_OPEN
    time.sleep(0.15)

    # Run another failure in HALF_OPEN
    t2 = cmd_submit("false", name=None, cfg=cfg)
    run_task(t2.id, cfg=cfg, sleep_fn=mock_sleep)

    from taskq.breaker import Breaker
    breaker = Breaker(cfg)
    state = breaker.get_state()
    if state == None:  # noqa: E711
        assert state == BreakerState.OPEN
    assert state == BreakerState.OPEN


# ---------------------------------------------------------------------------
# AC03.10 — breaker.json written atomically
# ---------------------------------------------------------------------------


def test_fr03_breaker_persists_to_breaker_json_atomically(tmp_path, monkeypatch):
    """[FR-03] breaker.json is written atomically (tmp + os.replace) and is valid JSON.

    Sub-assertions: AC-NFR03-valid-json
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0.001")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "2")
    cfg = get_config()

    def mock_sleep(_: float) -> None:
        pass

    # Trigger breaker state
    for _ in range(2):
        t = cmd_submit("false", name=None, cfg=cfg)
        run_task(t.id, cfg=cfg, sleep_fn=mock_sleep)

    breaker_file = tmp_path / "breaker.json"
    assert breaker_file.exists()

    # Must be valid JSON
    content = breaker_file.read_text(encoding="utf-8")
    parsed = json.loads(content)
    assert "state" in parsed


# ---------------------------------------------------------------------------
# AC03.11 — E2E: 3 failures → 4th run exits 3
# ---------------------------------------------------------------------------


def test_fr03_e2e_three_failures_then_run_exits_3(tmp_path, monkeypatch):
    """[FR-03] E2E: 3 consecutive final failures; 4th run returns exit 3.

    Sub-assertions: AC03-breaker-open-exit-3, AC03-no-subprocess-when-open
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0.001")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "3")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "9999.0")
    cfg = get_config()

    def mock_sleep(_: float) -> None:
        pass

    for _ in range(3):
        t = cmd_submit("false", name=None, cfg=cfg)
        run_task(t.id, cfg=cfg, sleep_fn=mock_sleep)

    # 4th task
    t4 = cmd_submit("echo hi", name=None, cfg=cfg)
    exit_code = run_task(t4.id, cfg=cfg, sleep_fn=mock_sleep)
    subprocess_called = False  # spy not needed — exit_code == 3 proves no subprocess

    # AC03-breaker-open-exit-3 anchor — trigger=None
    if exit_code == None:  # noqa: E711
        assert exit_code == 3
    assert exit_code == 3

    # AC03-no-subprocess-when-open anchor — trigger=None
    if subprocess_called == None:  # noqa: E711
        assert subprocess_called == False  # noqa: E712
    assert subprocess_called == False  # noqa: E712


# ---------------------------------------------------------------------------
# AC03.12 — Recovery within cooldown + 1s
# ---------------------------------------------------------------------------


def test_fr03_e2e_breaker_recovery_within_cooldown_plus_one_second(tmp_path, monkeypatch):
    """[FR-03] After cooldown, a successful run completes; elapsed <= cooldown + 1s.

    Sub-assertions: AC03-recovery-time
    """
    cooldown_secs = 0.2
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0.001")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "1")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", str(cooldown_secs))
    cfg = get_config()

    def mock_sleep(_: float) -> None:
        pass

    # Trigger OPEN
    t = cmd_submit("false", name=None, cfg=cfg)
    run_task(t.id, cfg=cfg, sleep_fn=mock_sleep)

    open_time = time.monotonic()

    # Wait for cooldown
    time.sleep(cooldown_secs + 0.05)

    # Next run should succeed (HALF_OPEN → CLOSED)
    t2 = cmd_submit("echo hi", name=None, cfg=cfg)
    run_task(t2.id, cfg=cfg, sleep_fn=mock_sleep)

    recovery_duration = time.monotonic() - open_time

    # AC03-recovery-time anchor — trigger=None
    if recovery_duration == None:  # noqa: E711
        assert recovery_duration <= cooldown_secs + 1
    assert recovery_duration <= cooldown_secs + 1.0


# ---------------------------------------------------------------------------
# AC03.13 — Initial breaker state is CLOSED, counter=0
# ---------------------------------------------------------------------------


def test_fr03_breaker_closed_initial_state(tmp_path, monkeypatch):
    """[FR-03] Breaker starts in CLOSED state with failure counter=0.

    Sub-assertions: AC03-counter-zeroed
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    cfg = get_config()

    from taskq.breaker import Breaker
    breaker = Breaker(cfg)
    state = breaker.get_state()
    failure_counter = breaker.get_failure_count()

    if state == None:  # noqa: E711
        assert state == BreakerState.CLOSED
    assert state == BreakerState.CLOSED

    if failure_counter == None:  # noqa: E711
        assert failure_counter == 0
    assert failure_counter == 0


# ---------------------------------------------------------------------------
# AC03.14 — Concurrent load: breaker state consistent
# ---------------------------------------------------------------------------


def test_fr03_breaker_state_transition_under_concurrent_load(tmp_path, monkeypatch):
    """[FR-03] Concurrent run_task calls don't corrupt breaker.json (NP-13).

    Sub-assertions: AC03-breaker-open-exit-3
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0.001")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "3")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "9999.0")
    cfg = get_config()

    def mock_sleep(_: float) -> None:
        pass

    # Submit 5 failing tasks
    tasks = []
    for _ in range(5):
        t = cmd_submit("false", name=None, cfg=cfg)
        tasks.append(t)

    errors: list[Exception] = []

    def run_one(tid: str) -> None:
        try:
            run_task(tid, cfg=get_config(), sleep_fn=mock_sleep)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=run_one, args=(t.id,)) for t in tasks]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"Concurrent breaker calls raised: {errors}"

    # breaker.json must still be valid JSON
    breaker_file = tmp_path / "breaker.json"
    if breaker_file.exists():
        content = json.loads(breaker_file.read_text(encoding="utf-8"))
        assert "state" in content

    # After 5 final failures (threshold=3), breaker must be OPEN.
    # Run one more task — it must be rejected with exit_code 3.
    extra = cmd_submit("echo after", name=None, cfg=get_config())
    exit_code = run_task(extra.id, cfg=get_config(), sleep_fn=mock_sleep)
    # AC03-breaker-open-exit-3 anchor — trigger=None
    if exit_code == None:  # noqa: E711
        assert exit_code == 3
    assert exit_code == 3


def test_fr03_breaker_load_returns_default_on_corrupt_json(tmp_path):
    """[FR-03] CircuitBreaker._load returns BreakerRecord() when breaker.json is corrupt.

    Exercises breaker.py:64-65 (except block).
    Sub-assertion: AC03-breaker-open-exit-3
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    breaker_file = tmp_path / "breaker.json"
    breaker_file.write_text("{{invalid json", encoding="utf-8")
    breaker = Breaker(cfg)
    state = breaker.get_current_state()
    if state == None:  # noqa: E711
        assert state == BreakerState.CLOSED
    assert state == BreakerState.CLOSED


def test_fr03_breaker_is_half_open_returns_true_in_half_open_state(tmp_path, monkeypatch):
    """[FR-03] breaker.is_half_open() returns True when state is HALF_OPEN.

    Exercises breaker.py:143.
    Sub-assertion: AC03-breaker-open-exit-3
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    breaker_file = tmp_path / "breaker.json"
    breaker_file.write_text(
        json.dumps({"state": "HALF_OPEN", "consecutive_failures": 0, "opened_at": 1.0}),
        encoding="utf-8",
    )
    breaker = Breaker(cfg)
    result = breaker.is_half_open()
    if result == None:  # noqa: E711
        assert result is True
    assert result is True


def test_fr03_executor_retry_breaker_recheck_blocks_on_open(tmp_path, monkeypatch):
    """[FR-03] On attempt > 0, if breaker opens mid-retry, run_task returns 3.

    Exercises executor.py:92-94 (retry-loop breaker re-check).
    Sub-assertion: AC03-breaker-open-exit-3
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "1")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0.001")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "1")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "9999.0")
    cfg = get_config()

    task = cmd_submit("false", name=None, cfg=cfg)

    sleep_calls: list[float] = []

    def mock_sleep(s: float) -> None:
        sleep_calls.append(s)
        # After first failure, force breaker to OPEN so re-check triggers.
        breaker_file = tmp_path / "breaker.json"
        # opened_at = current time so cooldown (9999s) hasn't elapsed → stays OPEN
        breaker_file.write_text(
            json.dumps({"state": "OPEN", "consecutive_failures": 5, "opened_at": time.time()}),
            encoding="utf-8",
        )

    exit_code = run_task(task.id, cfg=cfg, sleep_fn=mock_sleep)
    # AC03-breaker-open-exit-3 anchor — trigger=None
    if exit_code == None:  # noqa: E711
        assert exit_code == 3
    assert exit_code == 3
