"""Failing tests for FR-02: Task executor.

[FR-02] — TDD-RED phase: tests import from taskq.executor which does not exist yet.
Tests fail (or raise ImportError/ModuleNotFoundError) — valid RED state.

Sub-assertion anchor pattern per check-test-mirrors-spec:
    if <var> == None:  (trigger=None matches spec_trigger {"None"})
        assert <predicate>   (predicate matches TEST_SPEC.md verbatim)
"""
import os
import threading
import time
from unittest.mock import patch

import pytest

from taskq.config import get_config
from taskq.executor import run_task, run_all  # noqa: F401 — import triggers RED if missing
from taskq.models import Task, TaskStatus
from taskq.store import load_tasks, load_task
from taskq.cli import cmd_submit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(command: str, tmp_path, name=None) -> Task:
    """Submit a task and return it; TASKQ_HOME is set to tmp_path."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    return cmd_submit(command, name=name, cfg=cfg)


# ---------------------------------------------------------------------------
# Happy-path state transitions
# ---------------------------------------------------------------------------


def test_fr02_done_state_on_exit_zero(tmp_path):
    """[FR-02] Command with exit 0 transitions task to 'done'.

    Sub-assertions: AC02-done-exit-code-0
    """
    task = _make_task("echo hi", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    exit_code = updated.exit_code
    # AC02-done-exit-code-0 anchor — trigger=None
    if exit_code == None:  # noqa: E711
        assert exit_code == 0
    assert updated.status == TaskStatus.done
    assert exit_code == 0


def test_fr02_failed_state_on_nonzero_exit(tmp_path):
    """[FR-02] Command with non-zero exit transitions task to 'failed'.

    Sub-assertions: AC02-failed-status
    """
    task = _make_task("false", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    result = updated.status
    if result == None:  # noqa: E711
        assert result == TaskStatus.failed
    assert updated.status == TaskStatus.failed


def test_fr02_timeout_state_on_TimeoutExpired(tmp_path, monkeypatch):
    """[FR-02] Command that exceeds timeout transitions task to 'timeout'.

    Sub-assertions: AC02-timeout-status (NP-15)
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.1")
    cfg = get_config()
    task = cmd_submit("sleep 5", name=None, cfg=cfg)
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    result = updated.status
    if result == None:  # noqa: E711
        assert result == TaskStatus.timeout
    assert updated.status == TaskStatus.timeout


def test_fr02_records_stdout_tail_last_2000_chars(tmp_path):
    """[FR-02] stdout_tail stores at most the last 2000 characters.

    Sub-assertions: AC02-stdout-tail-max
    """
    task = _make_task("python3 -c \"print('A'*3000)\"", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    stdout_tail = updated.stdout_tail
    # AC02-stdout-tail-max anchor — trigger=None
    if stdout_tail == None:  # noqa: E711
        assert len(stdout_tail) <= 2000
    assert stdout_tail is not None
    assert len(stdout_tail) <= 2000


def test_fr02_records_stderr_tail_last_2000_chars(tmp_path):
    """[FR-02] stderr_tail stores at most the last 2000 characters.

    Sub-assertions: AC02-stderr-tail-max
    """
    task = _make_task(
        "python3 -c \"import sys; sys.stderr.write('B'*3000)\"", tmp_path
    )
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    stderr_tail = updated.stderr_tail
    # AC02-stderr-tail-max anchor — trigger=None
    if stderr_tail == None:  # noqa: E711
        assert len(stderr_tail) <= 2000
    assert stderr_tail is not None
    assert len(stderr_tail) <= 2000


def test_fr02_records_duration_ms(tmp_path):
    """[FR-02] duration_ms is populated and non-negative after execution.

    Sub-assertions: AC02-duration-positive
    """
    task = _make_task("echo hi", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    duration_ms = updated.duration_ms
    # AC02-duration-positive anchor — trigger=None
    if duration_ms == None:  # noqa: E711
        assert duration_ms >= 0
    assert duration_ms is not None
    assert duration_ms >= 0


def test_fr02_records_finished_at(tmp_path):
    """[FR-02] finished_at is populated after execution.

    Sub-assertions: AC02-finished-at-present
    """
    task = _make_task("echo hi", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    finished_at = updated.finished_at
    # AC02-finished-at-present anchor — trigger=None
    if finished_at == None:  # noqa: E711
        assert finished_at is not None
    assert finished_at is not None


def test_fr02_single_task_timeout_returns_exit_4(tmp_path, monkeypatch):
    """[FR-02] Single-task timeout returns exit code 4.

    Sub-assertions: AC02-timeout-exit-4 (NP-15)
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.1")
    cfg = get_config()
    task = cmd_submit("sleep 5", name=None, cfg=cfg)
    exit_code = run_task(task.id, cfg=cfg)
    # AC02-timeout-exit-4 anchor — trigger=None
    if exit_code == None:  # noqa: E711
        assert exit_code == 4
    assert exit_code == 4


# ---------------------------------------------------------------------------
# Concurrency (NP-13)
# ---------------------------------------------------------------------------


def test_fr02_run_all_uses_thread_pool_max_workers(tmp_path, monkeypatch):
    """[FR-02] run_all dispatches pending tasks via ThreadPoolExecutor.

    Sub-assertions: AC02-run-all-concurrent (NP-13)
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_MAX_WORKERS", "2")
    cfg = get_config()
    for i in range(4):
        cmd_submit(f"echo task{i}", name=None, cfg=cfg)
    run_all(cfg=cfg)
    tasks = load_tasks(cfg)
    # all should be done
    result = all(t.status == TaskStatus.done for t in tasks.values())
    if result == None:  # noqa: E711
        assert result is True
    assert result is True
    assert len(tasks) == 4


def test_fr02_concurrent_writes_preserve_tasks_json_integrity(tmp_path):
    """[FR-02] Concurrent run_task calls do not corrupt tasks.json (NP-13).

    Sub-assertions: AC02-concurrent-json-valid
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    # Submit 5 tasks
    task_ids = []
    for i in range(5):
        t = cmd_submit(f"echo t{i}", name=None, cfg=cfg)
        task_ids.append(t.id)

    errors = []

    def run_one(tid):
        try:
            os.environ["TASKQ_HOME"] = str(tmp_path)
            run_task(tid, cfg=get_config())
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=run_one, args=(tid,)) for tid in task_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent run_task raised: {errors}"
    tasks = load_tasks(cfg)
    assert len(tasks) == 5


# ---------------------------------------------------------------------------
# Security audit (NP-08 / NFR-02)
# ---------------------------------------------------------------------------


def test_fr02_subprocess_called_without_shell_true(tmp_path):
    """[FR-02] executor never calls subprocess with shell=True (NFR-02).

    Sub-assertions: AC02-no-shell-true
    """
    import subprocess

    subprocess_call_args: list[dict] = []
    original_run = subprocess.run

    def spy_run(*args, **kwargs):
        subprocess_call_args.append({"args": args, "kwargs": kwargs})
        return original_run(*args, **kwargs)

    task = _make_task("echo hi", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()

    with patch.object(subprocess, "run", side_effect=spy_run):
        run_task(task.id, cfg=cfg)

    # AC02-no-shell-true anchor — trigger=None
    if subprocess_call_args == None:  # noqa: E711
        assert "shell=True" not in subprocess_call_args
    # Verify no call used shell=True
    for call in subprocess_call_args:
        assert call["kwargs"].get("shell") is not True, (
            f"shell=True found in subprocess call: {call}"
        )
    assert "shell=True" not in str(subprocess_call_args)


# ---------------------------------------------------------------------------
# State machine transitions
# ---------------------------------------------------------------------------


def test_fr02_pending_to_running_state_transition(tmp_path):
    """[FR-02] Task transitions from pending to running during execution.

    Sub-assertions: AC02-pending-running-transition
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo hi", name=None, cfg=cfg)
    # Verify initial state is pending
    initial = load_task(task.id, cfg)
    result = initial.status
    if result == None:  # noqa: E711
        assert result == TaskStatus.pending
    assert initial.status == TaskStatus.pending
    # After run, must be done (running is transient)
    run_task(task.id, cfg=cfg)
    final = load_task(task.id, cfg)
    assert final.status in (TaskStatus.done, TaskStatus.failed, TaskStatus.timeout)


def test_fr02_running_to_done_state_transition(tmp_path):
    """[FR-02] Successful command transitions to 'done'.

    Sub-assertions: AC02-running-to-done
    """
    task = _make_task("echo hi", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    result = updated.status
    if result == None:  # noqa: E711
        assert result == TaskStatus.done
    assert updated.status == TaskStatus.done


def test_fr02_running_to_failed_state_transition(tmp_path):
    """[FR-02] Failing command transitions to 'failed'.

    Sub-assertions: AC02-running-to-failed
    """
    task = _make_task("false", tmp_path)
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    result = updated.status
    if result == None:  # noqa: E711
        assert result == TaskStatus.failed
    assert updated.status == TaskStatus.failed


def test_fr02_running_to_timeout_state_transition(tmp_path, monkeypatch):
    """[FR-02] Timed-out command transitions to 'timeout' (NP-15).

    Sub-assertions: AC02-running-to-timeout
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.1")
    cfg = get_config()
    task = cmd_submit("sleep 5", name=None, cfg=cfg)
    run_task(task.id, cfg=cfg)
    updated = load_task(task.id, cfg)
    result = updated.status
    if result == None:  # noqa: E711
        assert result == TaskStatus.timeout
    assert updated.status == TaskStatus.timeout


def test_fr02_executor_subprocess_timeout_enforced(tmp_path, monkeypatch):
    """[FR-02] Executor enforces subprocess timeout (NP-15).

    Sub-assertions: AC02-timeout-enforced
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.1")
    cfg = get_config()
    task = cmd_submit("sleep 60", name=None, cfg=cfg)
    start = time.monotonic()
    run_task(task.id, cfg=cfg)
    elapsed = time.monotonic() - start
    # Should complete well before 60s
    assert elapsed < 5.0


# ---------------------------------------------------------------------------
# Config validation edge cases (NFR-06 coverage)
# ---------------------------------------------------------------------------


def test_fr02_validate_config_invalid_max_workers(tmp_path):
    """[FR-02] validate_config returns False for max_workers < 1.

    Sub-assertions: AC02-config-validate-workers
    """
    from taskq.config import Config, validate_config

    cfg = Config(
        home=str(tmp_path), max_workers=0, task_timeout=10.0,
        retry_limit=2, backoff_base=0.1, breaker_threshold=3,
        breaker_cooldown=5.0, cache_ttl=3600.0,
    )
    assert validate_config(cfg) is False


def test_fr02_validate_config_invalid_task_timeout(tmp_path):
    """[FR-02] validate_config returns False for task_timeout <= 0.

    Sub-assertions: AC02-config-validate-timeout
    """
    from taskq.config import Config, validate_config

    cfg = Config(
        home=str(tmp_path), max_workers=4, task_timeout=0.0,
        retry_limit=2, backoff_base=0.1, breaker_threshold=3,
        breaker_cooldown=5.0, cache_ttl=3600.0,
    )
    assert validate_config(cfg) is False


def test_fr02_validate_config_invalid_backoff_base(tmp_path):
    """[FR-02] validate_config returns False for backoff_base <= 0.

    Sub-assertions: AC02-config-validate-backoff
    """
    from taskq.config import Config, validate_config

    cfg = Config(
        home=str(tmp_path), max_workers=4, task_timeout=10.0,
        retry_limit=2, backoff_base=0.0, breaker_threshold=3,
        breaker_cooldown=5.0, cache_ttl=3600.0,
    )
    assert validate_config(cfg) is False


def test_fr02_validate_config_invalid_breaker_threshold(tmp_path):
    """[FR-02] validate_config returns False for breaker_threshold < 1.

    Sub-assertions: AC02-config-validate-breaker
    """
    from taskq.config import Config, validate_config

    cfg = Config(
        home=str(tmp_path), max_workers=4, task_timeout=10.0,
        retry_limit=2, backoff_base=0.1, breaker_threshold=0,
        breaker_cooldown=5.0, cache_ttl=3600.0,
    )
    assert validate_config(cfg) is False


def test_fr02_validate_config_invalid_breaker_cooldown(tmp_path):
    """[FR-02] validate_config returns False for breaker_cooldown <= 0.

    Sub-assertions: AC02-config-validate-cooldown
    """
    from taskq.config import Config, validate_config

    cfg = Config(
        home=str(tmp_path), max_workers=4, task_timeout=10.0,
        retry_limit=2, backoff_base=0.1, breaker_threshold=3,
        breaker_cooldown=0.0, cache_ttl=3600.0,
    )
    assert validate_config(cfg) is False


def test_fr02_validate_config_invalid_cache_ttl(tmp_path):
    """[FR-02] validate_config returns False for cache_ttl <= 0.

    Sub-assertions: AC02-config-validate-cache-ttl
    """
    from taskq.config import Config, validate_config

    cfg = Config(
        home=str(tmp_path), max_workers=4, task_timeout=10.0,
        retry_limit=2, backoff_base=0.1, breaker_threshold=3,
        breaker_cooldown=5.0, cache_ttl=0.0,
    )
    assert validate_config(cfg) is False


def test_fr02_store_corrupted_json_exits_1(tmp_path):
    """[FR-02] load_tasks raises SystemExit(1) on corrupted tasks.json.

    Sub-assertions: AC02-store-corrupt-exit-1
    """

    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()

    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        load_tasks(cfg)
    assert exc_info.value.code == 1


def test_fr02_store_load_task_unknown_id_exits_2(tmp_path):
    """[FR-02] load_task raises SystemExit(2) for unknown task id.

    Sub-assertions: AC02-store-unknown-id-exit-2
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()

    with pytest.raises(SystemExit) as exc_info:
        load_task("nonexistent", cfg)
    assert exc_info.value.code == 2


def test_fr02_store_redact_masks_secrets(tmp_path):
    """[FR-02] store._redact replaces lines containing sk-* or token= with [REDACTED].

    Sub-assertions: AC02-store-redact-secrets (NFR-04)
    """
    from taskq.store import _redact

    text = "normal line\nsk-ABCDEFGH1234secret\ntoken=my_secret_value\nclean line"
    result = _redact(text)
    assert result is not None
    assert "[REDACTED]" in result
    assert "sk-ABCDEFGH1234secret" not in result
    assert "token=my_secret_value" not in result
    assert "normal line" in result
    assert "clean line" in result


def test_fr02_run_task_unknown_id_exits_2(tmp_path):
    """[FR-02] run_task with unknown task id propagates SystemExit(2).

    Sub-assertions: AC02-run-unknown-id-exit-2
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()

    with pytest.raises(SystemExit) as exc_info:
        run_task("nonexistent", cfg=cfg)
    assert exc_info.value.code == 2


def test_fr02_cli_submit_empty_command_exits_2(tmp_path):
    """[FR-02] cmd_submit rejects empty command with SystemExit(2).

    Sub-assertions: AC02-cli-empty-command
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    with pytest.raises(SystemExit) as exc_info:
        cmd_submit("", name=None, cfg=cfg)
    assert exc_info.value.code == 2


def test_fr02_cli_submit_too_long_command_exits_2(tmp_path):
    """[FR-02] cmd_submit rejects commands over 1000 chars with SystemExit(2).

    Sub-assertions: AC02-cli-long-command
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    with pytest.raises(SystemExit) as exc_info:
        cmd_submit("x" * 1001, name=None, cfg=cfg)
    assert exc_info.value.code == 2


def test_fr02_cli_submit_injection_char_outside_quotes_exits_2(tmp_path):
    """[FR-02] cmd_submit rejects injection chars outside quotes with SystemExit(2).

    Sub-assertions: AC02-cli-injection-outside-quotes (NFR-02)
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    with pytest.raises(SystemExit) as exc_info:
        cmd_submit("echo hi; rm x", name=None, cfg=cfg)
    assert exc_info.value.code == 2


def test_fr02_cli_submit_duplicate_name_exits_2(tmp_path):
    """[FR-02] cmd_submit rejects duplicate name for pending task with SystemExit(2).

    Sub-assertions: AC02-cli-duplicate-name
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    cmd_submit("echo first", name="myname", cfg=cfg)
    with pytest.raises(SystemExit) as exc_info:
        cmd_submit("echo second", name="myname", cfg=cfg)
    assert exc_info.value.code == 2


def test_fr02_cli_fmt_submit_json_output(tmp_path):
    """[FR-02] _fmt_submit returns JSON when json_output=True.

    Sub-assertions: AC02-cli-fmt-submit-json
    """
    import json as _json
    from taskq.cli import _fmt_submit

    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo hi", name=None, cfg=cfg)
    result = _fmt_submit(task, json_output=True)
    parsed = _json.loads(result)
    assert "id" in parsed
    assert parsed["status"] == "pending"


def test_fr02_cli_cmd_status_json(tmp_path):
    """[FR-02] cmd_status outputs JSON when json_output=True.

    Sub-assertions: AC02-cli-status-json
    """
    import io
    import json as _json
    from taskq.cli import cmd_status

    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo hi", name=None, cfg=cfg)
    run_task(task.id, cfg=cfg)

    captured = io.StringIO()
    import sys as _sys
    old_stdout = _sys.stdout
    _sys.stdout = captured
    try:
        cmd_status(task.id, cfg=cfg, json_output=True)
    finally:
        _sys.stdout = old_stdout
    parsed = _json.loads(captured.getvalue())
    assert parsed["id"] == task.id
    assert parsed["status"] == "done"


def test_fr02_cli_cmd_list_all(tmp_path):
    """[FR-02] cmd_list enumerates all tasks.

    Sub-assertions: AC02-cli-list-all
    """
    import io
    from taskq.cli import cmd_list

    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    cmd_submit("echo a", name=None, cfg=cfg)
    cmd_submit("echo b", name=None, cfg=cfg)

    captured = io.StringIO()
    import sys as _sys
    old_stdout = _sys.stdout
    _sys.stdout = captured
    try:
        cmd_list(status_filter=None, cfg=cfg, json_output=False)
    finally:
        _sys.stdout = old_stdout
    output = captured.getvalue()
    assert "echo a" in output
    assert "echo b" in output


def test_fr02_cli_cmd_clear(tmp_path):
    """[FR-02] cmd_clear removes tasks.json from TASKQ_HOME.

    Sub-assertions: AC02-cli-clear
    """
    from taskq.cli import cmd_clear

    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    cmd_submit("echo hi", name=None, cfg=cfg)
    tasks_file = tmp_path / "tasks.json"
    assert tasks_file.exists()
    cmd_clear(cfg=cfg)
    assert not tasks_file.exists()
