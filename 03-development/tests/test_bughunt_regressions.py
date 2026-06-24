"""Regression tests for confirmed Gate-3 adversarial bug-hunt findings.

These tests reproduce the two CONFIRMED high-severity findings recorded in
.methodology/bug_hunt_report.json and guard their fixes (RED before the fix,
GREEN after). Test names follow the it('test_frNN_xxx') convention so the
D4 spec-coverage check associates them with their FR.

Findings:
  * executor#1 [FR-02, resilience] — a command that cannot be spawned
    (nonexistent / not executable / empty argv) raised an UNCAUGHT OSError
    (FileNotFoundError / PermissionError) from subprocess.run. The executor
    only caught subprocess.TimeoutExpired, so:
      - single run left the task stuck in 'running' and crashed the caller;
      - run_all aborted the whole batch via future.result(), losing tasks;
      - the CLI dumped a Python traceback instead of a defined exit code.
    Fix: treat a spawn failure as a terminal 'failed' result (exit_code 127).

  * executor#2 [FR-03, concurrency] — in HALF_OPEN the breaker must admit
    exactly ONE trial task (SPEC FR-03 "放行一個任務"). run_all dispatched
    ALL pending tasks in parallel; each saw is_open()==False and stampeded
    through the single trial slot. Fix: run_all runs one trial synchronously
    in HALF_OPEN and lets the breaker's verdict gate the remainder.
"""
from __future__ import annotations

import json
import os
import time

from taskq.config import get_config
from taskq.cli import cmd_submit
from taskq.executor import run_task, run_all
from taskq.store import load_task, load_tasks
from taskq.models import TaskStatus, BreakerState
from taskq.breaker import Breaker


# ---------------------------------------------------------------------------
# executor#1 — spawn failure is a 'failed' terminal state, not a crash
# ---------------------------------------------------------------------------


def test_fr02_nonexistent_command_marks_failed_without_crashing(tmp_path, monkeypatch):
    """[FR-02] A command that cannot be spawned ends 'failed', not an uncaught crash.

    RED before fix: run_task raised FileNotFoundError and left status='running'.
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "99")
    cfg = get_config()

    t = cmd_submit("nonexistent_program_xyz", name=None, cfg=cfg)
    # Must NOT raise.
    rc = run_task(t.id, cfg=cfg, sleep_fn=lambda _s: None)
    updated = load_task(t.id, cfg=cfg)

    assert updated.status == TaskStatus.failed
    assert updated.status != TaskStatus.running  # not stuck mid-execution
    assert updated.finished_at is not None
    assert rc == 0  # SPEC defines no dedicated 'failed' exit code (else 0)


def test_fr02_run_all_continues_when_one_task_cannot_spawn(tmp_path, monkeypatch):
    """[FR-02] One un-spawnable task must not abort the whole run_all batch.

    RED before fix: future.result() re-raised the OSError, aborting the batch
    and leaving sibling tasks stuck in 'running'.
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_MAX_WORKERS", "2")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "99")
    cfg = get_config()

    cmd_submit("echo good1", name="g1", cfg=cfg)
    cmd_submit("nonexistent_program_xyz", name="bad", cfg=cfg)
    cmd_submit("echo good2", name="g2", cfg=cfg)

    # Must NOT raise.
    run_all(cfg=cfg, sleep_fn=lambda _s: None)

    statuses = sorted(t.status for t in load_tasks(cfg=cfg).values())
    assert statuses == [TaskStatus.done, TaskStatus.done, TaskStatus.failed]
    # No task left stranded in a non-terminal state.
    assert all(
        t.status in (TaskStatus.done, TaskStatus.failed, TaskStatus.timeout)
        for t in load_tasks(cfg=cfg).values()
    )


def test_fr03_spawn_failure_notifies_breaker(tmp_path, monkeypatch):
    """[FR-03] A spawn-failed task counts as a final failure toward the breaker.

    RED before fix: the OSError escaped before record_failure ran, so the
    breaker never observed the failure.
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "1")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "9999")
    cfg = get_config()

    t = cmd_submit("nonexistent_program_xyz", name=None, cfg=cfg)
    run_task(t.id, cfg=cfg, sleep_fn=lambda _s: None)

    assert Breaker(cfg).get_state() == BreakerState.OPEN


# ---------------------------------------------------------------------------
# executor#2 — HALF_OPEN admits exactly one trial under run_all
# ---------------------------------------------------------------------------


def _force_half_open(cfg) -> None:
    """Persist a breaker.json that resolves to HALF_OPEN (cooled-down OPEN)."""
    bp = os.path.join(cfg.home, "breaker.json")
    with open(bp, "w", encoding="utf-8") as f:
        json.dump(
            {"state": "OPEN", "consecutive_failures": 1, "opened_at": time.time() - 1.0},
            f,
        )


def test_fr03_run_all_admits_single_trial_when_half_open_trial_fails(tmp_path, monkeypatch):
    """[FR-03] In HALF_OPEN, run_all admits exactly ONE trial; if it fails the rest are rejected.

    RED before fix: all pending tasks stampeded the single HALF_OPEN slot
    (5 subprocess executions instead of 1).
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "1")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "0.1")
    monkeypatch.setenv("TASKQ_MAX_WORKERS", "5")
    cfg = get_config()

    # Open the breaker, then force the effective state to HALF_OPEN.
    t = cmd_submit("false", name=None, cfg=cfg)
    run_task(t.id, cfg=cfg, sleep_fn=lambda _s: None)
    _force_half_open(cfg)
    assert Breaker(cfg).get_current_state() == BreakerState.HALF_OPEN

    # Five failing pending tasks; only the single trial should ever spawn.
    for _ in range(5):
        cmd_submit("false", name=None, cfg=cfg)

    import subprocess as _sp

    calls = [0]
    orig = _sp.run

    def counting_run(*a, **k):
        calls[0] += 1
        return orig(*a, **k)

    monkeypatch.setattr(_sp, "run", counting_run)
    run_all(cfg=cfg, sleep_fn=lambda _s: None)

    # Exactly one trial executed; the breaker re-OPENed and rejected the rest.
    assert calls[0] == 1
    assert Breaker(cfg).get_state() == BreakerState.OPEN


def test_fr03_run_all_half_open_trial_success_then_resumes(tmp_path, monkeypatch):
    """[FR-03] A successful HALF_OPEN trial closes the breaker and lets the rest run.

    Confirms the single-trial gate does not deadlock recovery: once the trial
    succeeds (→CLOSED) the remaining tasks proceed normally.
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "1")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "0.1")
    monkeypatch.setenv("TASKQ_MAX_WORKERS", "5")
    cfg = get_config()

    t = cmd_submit("false", name=None, cfg=cfg)
    run_task(t.id, cfg=cfg, sleep_fn=lambda _s: None)
    _force_half_open(cfg)
    assert Breaker(cfg).get_current_state() == BreakerState.HALF_OPEN

    ids = [cmd_submit("echo hi", name=None, cfg=cfg).id for _ in range(5)]
    run_all(cfg=cfg, sleep_fn=lambda _s: None)

    # Trial succeeded → breaker CLOSED → all five complete as done.
    assert Breaker(cfg).get_state() == BreakerState.CLOSED
    tasks = load_tasks(cfg=cfg)
    assert all(tasks[i].status == TaskStatus.done for i in ids)
