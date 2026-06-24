"""Integration tests for taskq — full module wiring (in-process).

These tests exercise the complete store → executor → breaker → cache pipeline
by calling the Python API directly (in-process), enabling coverage collection.

All test names follow the it('test_frNN_xxx') convention from SPEC.md.
"""
from __future__ import annotations

import os
import sys

# Ensure taskq is importable
sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "src")
))

from taskq.config import get_config
from taskq.cli import cmd_submit, cmd_clear
from taskq.executor import run_task, run_all
from taskq.store import load_task, load_tasks
from taskq.models import TaskStatus, BreakerState
from taskq.breaker import Breaker
from taskq import cache as task_cache


# ---------------------------------------------------------------------------
# FR-01 + FR-05: submit → store wiring
# ---------------------------------------------------------------------------


def test_fr01_submit_e2e_returns_id_and_pending_status(tmp_path, monkeypatch):
    """[FR-01][FR-05] submit returns Task with 8-char id and status=pending."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    cfg = get_config()
    task = cmd_submit("echo integration-test", name=None, cfg=cfg)
    assert len(task.id) == 8
    assert task.status == TaskStatus.pending


def test_fr05_e2e_full_submit_run_status_lifecycle(tmp_path, monkeypatch):
    """[FR-05] Full lifecycle: submit → run → status=done.

    Exercises CLI API → store → executor → breaker → cache wiring.
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    cfg = get_config()

    task = cmd_submit("echo hello-integration", name=None, cfg=cfg)
    assert task.status == TaskStatus.pending

    exit_code = run_task(task.id, cfg=cfg)
    assert exit_code == 0

    updated = load_task(task.id, cfg=cfg)
    assert updated.status == TaskStatus.done


def test_fr05_e2e_clear_removes_all_tasks(tmp_path, monkeypatch):
    """[FR-05] After clear, load_tasks returns empty list."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    cfg = get_config()

    cmd_submit("echo a", name=None, cfg=cfg)
    cmd_submit("echo b", name=None, cfg=cfg)
    assert len(load_tasks(cfg=cfg)) == 2

    cmd_clear(cfg=cfg)
    assert load_tasks(cfg=cfg) == {}


# ---------------------------------------------------------------------------
# FR-02: executor integration
# ---------------------------------------------------------------------------


def test_fr02_run_nonzero_command_sets_failed_status(tmp_path, monkeypatch):
    """[FR-02] A command that exits non-zero leaves task status=failed."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    cfg = get_config()

    task = cmd_submit("false", name=None, cfg=cfg)
    run_task(task.id, cfg=cfg)

    updated = load_task(task.id, cfg=cfg)
    assert updated.status == TaskStatus.failed


def test_fr02_run_all_executes_all_pending_tasks(tmp_path, monkeypatch):
    """[FR-02] run_all executes all pending tasks to terminal state."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_MAX_WORKERS", "2")
    cfg = get_config()

    t1 = cmd_submit("echo task-a", name=None, cfg=cfg)
    t2 = cmd_submit("echo task-b", name=None, cfg=cfg)

    run_all(cfg=cfg)

    s1 = load_task(t1.id, cfg=cfg)
    s2 = load_task(t2.id, cfg=cfg)
    assert s1.status == TaskStatus.done
    assert s2.status == TaskStatus.done


def test_fr02_executor_records_stdout_tail(tmp_path, monkeypatch):
    """[FR-02] Executor stores stdout_tail after successful run."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    cfg = get_config()

    task = cmd_submit("echo stdout-integration", name=None, cfg=cfg)
    run_task(task.id, cfg=cfg)

    updated = load_task(task.id, cfg=cfg)
    assert updated.stdout_tail is not None
    assert "stdout-integration" in updated.stdout_tail


# ---------------------------------------------------------------------------
# FR-03: circuit breaker integration
# ---------------------------------------------------------------------------


def test_fr03_e2e_three_failures_then_run_exits_3(tmp_path, monkeypatch):
    """[FR-03] After threshold consecutive failures, run returns 3 (breaker OPEN).

    Wires: executor → breaker FSM persistence across multiple run_task calls.
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "3")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "60")
    cfg = get_config()

    def no_sleep(_): pass

    for _ in range(3):
        t = cmd_submit("false", name=None, cfg=cfg)
        run_task(t.id, cfg=cfg, sleep_fn=no_sleep)

    t4 = cmd_submit("echo after-open", name=None, cfg=cfg)
    exit_code = run_task(t4.id, cfg=cfg, sleep_fn=no_sleep)
    assert exit_code == 3


def test_fr03_breaker_state_persists_across_calls(tmp_path, monkeypatch):
    """[FR-03] Breaker state survives across multiple Breaker instances (persistence)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "1")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "60")
    cfg = get_config()

    def no_sleep(_): pass

    t = cmd_submit("false", name=None, cfg=cfg)
    run_task(t.id, cfg=cfg, sleep_fn=no_sleep)

    # Load breaker state fresh — simulates a new process reading from disk
    breaker = Breaker(cfg)
    state = breaker.get_state()
    assert state == BreakerState.OPEN


# ---------------------------------------------------------------------------
# FR-04: cache integration
# ---------------------------------------------------------------------------


def test_fr04_e2e_repeated_command_replays_from_cache(tmp_path, monkeypatch):
    """[FR-04] A second run of the same command is served from cache.

    Wires: executor → cache write on first run, cache read on second run.
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_CACHE_TTL", "3600")
    cfg = get_config()

    def no_sleep(_): pass

    cmd = "echo cache-integration-test"

    # First run — executes subprocess, writes to cache
    t1 = cmd_submit(cmd, name=None, cfg=cfg)
    run_task(t1.id, cfg=cfg, sleep_fn=no_sleep)
    s1 = load_task(t1.id, cfg=cfg)
    assert s1.status == TaskStatus.done

    # Second run — same command with cached=True, should hit cache
    t2 = cmd_submit(cmd, name=None, cfg=cfg)
    run_task(t2.id, cfg=cfg, cached=True, sleep_fn=no_sleep)
    s2 = load_task(t2.id, cfg=cfg)
    assert s2.status == TaskStatus.done
    assert s2.cached is True


def test_fr04_cache_stores_result_for_done_task(tmp_path, monkeypatch):
    """[FR-04] Cache entry exists after a successful task run."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_CACHE_TTL", "3600")
    cfg = get_config()

    def no_sleep(_): pass

    cmd = "echo cache-write-test"
    t = cmd_submit(cmd, name=None, cfg=cfg)
    run_task(t.id, cfg=cfg, sleep_fn=no_sleep)

    entry = task_cache.lookup(cmd, cfg=cfg)
    assert entry is not None
    assert entry.exit_code == 0
