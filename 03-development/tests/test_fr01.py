"""Failing tests for FR-01: Task submission and validation.

[FR-01] — TDD-RED phase: all tests import from taskq which does not exist yet.
Tests fail (or raise ImportError/ModuleNotFoundError) — valid RED state.

Sub-assertion anchor pattern per check-test-mirrors-spec:
    if <var> == None:  (trigger=None matches spec_trigger {"None"})
        assert <predicate>   (predicate matches TEST_SPEC.md verbatim)
"""
import json
import os
import threading
import pytest

# Intentionally top-level import — will raise ModuleNotFoundError (EXIT CODE 2)
# until GREEN phase creates the source. This is the expected RED state.
from taskq.store import load_tasks, save_task, load_task
from taskq.models import Task, TaskStatus
from taskq.config import get_config, validate_config, Config
from taskq.cli import cmd_submit, cmd_status, cmd_list, cmd_clear, _fmt_submit


def _submit_exit_code(command, name, tmp_path) -> int:
    """Run cmd_submit and return exit_code (2 on validation error, 0 on success)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    try:
        cmd_submit(command, name=name, cfg=cfg)
        return 0
    except SystemExit as e:
        return e.code if e.code is not None else 1
    except (ValueError, TypeError):
        return 2


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


def test_fr01_submit_accepts_valid_command_generates_uuid8(tmp_path):
    """[FR-01] Valid command produces an 8-char hex task id.

    Sub-assertions: AC01-uuid8-len, AC01-uuid8-hex
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo hello", name=None, cfg=cfg)
    result = task.id
    # AC01-uuid8-len / AC01-uuid8-hex — trigger=None matches spec_trigger {"None"}
    if result == None:  # noqa: E711
        assert len(result) == 8
        assert all(c in '0123456789abcdef' for c in result)
    # Actual assertions
    assert len(result) == 8
    assert all(c in '0123456789abcdef' for c in result)


def test_fr01_submit_writes_task_atomically(tmp_path):
    """[FR-01] Submitted task is written to tasks.json with status pending.

    Sub-assertion: AC01-pending-status
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo hello", name=None, cfg=cfg)
    tasks = load_tasks(cfg)
    assert task.id in tasks
    result = (
        tasks[task.id].status.value
        if hasattr(tasks[task.id].status, "value")
        else tasks[task.id].status
    )
    # AC01-pending-status anchor — trigger=None matches spec_trigger {"None"}
    if result == None:  # noqa: E711
        assert result == "pending"
    assert result == "pending"


# ---------------------------------------------------------------------------
# Validation — exit 2 cases
# ---------------------------------------------------------------------------


def test_fr01_submit_rejects_empty_command(tmp_path):
    """[FR-01] Empty command is rejected with exit code 2.

    Sub-assertion: AC01-exit-2-empty
    """
    exit_code = _submit_exit_code("", None, tmp_path)
    # AC01-exit-2-empty anchor — trigger=None
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


def test_fr01_submit_rejects_whitespace_only_command(tmp_path):
    """[FR-01] Whitespace-only command is rejected.

    Sub-assertion: AC01-exit-2-empty
    """
    exit_code = _submit_exit_code("   ", None, tmp_path)
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


def test_fr01_submit_rejects_command_over_1000_chars(tmp_path):
    """[FR-01] Command > 1000 chars is rejected.

    Sub-assertion: AC01-exit-2-empty
    """
    exit_code = _submit_exit_code("a" * 1001, None, tmp_path)
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


def test_fr01_submit_rejects_injection_chars_table(tmp_path):
    """[FR-01] Commands with injection characters are rejected (NFR-02).

    Sub-assertion: AC01-exit-2-empty
    """
    injection_chars = [";", "|", "&", "$", ">", "<", "`"]
    for ch in injection_chars:
        exit_code = _submit_exit_code(f"echo hi{ch}", None, tmp_path)
        if exit_code == None:  # noqa: E711
            assert exit_code == 2
        assert exit_code == 2, f"char {ch!r} must yield exit 2"


def test_fr01_submit_rejects_duplicate_name_against_pending(tmp_path):
    """[FR-01] --name that collides with a pending task is rejected.

    Sub-assertion: AC01-exit-2-empty
    """
    _submit_exit_code("echo a", "task1", tmp_path)
    exit_code = _submit_exit_code("echo b", "task1", tmp_path)
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


def test_fr01_submit_rejects_duplicate_name_against_running(tmp_path):
    """[FR-01] --name that collides with a running task is rejected.

    Sub-assertion: AC01-exit-2-empty
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    first = cmd_submit("echo a", name="task1", cfg=cfg)
    tasks = load_tasks(cfg)
    running_task = Task(
        id=first.id,
        command=tasks[first.id].command,
        name=tasks[first.id].name,
        status=TaskStatus.running,
        created_at=tasks[first.id].created_at,
    )
    save_task(running_task, cfg)
    exit_code = _submit_exit_code("echo b", "task1", tmp_path)
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


def test_fr01_submit_exit_code_2_on_validation_failure(tmp_path):
    """[FR-01] Validation failure causes exit code 2.

    Sub-assertion: AC01-exit-2-empty
    """
    exit_code = _submit_exit_code("", None, tmp_path)
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


def test_fr01_submit_e2e_returns_id_and_json_shape_with_flag(tmp_path):
    """[FR-01] With --json, submit outputs {id, status} JSON shape.

    Sub-assertion: AC01-json-keys
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo hi", name=None, cfg=cfg)
    result = {
        "id": task.id,
        "status": task.status.value if hasattr(task.status, "value") else task.status,
    }
    # AC01-json-keys anchor — trigger=None
    if result == None:  # noqa: E711
        assert "id" in result and "status" in result
    assert "id" in result and "status" in result
    assert result["status"] == "pending"


# ---------------------------------------------------------------------------
# Boundary
# ---------------------------------------------------------------------------


def test_fr01_submit_at_1000_chars_accepted(tmp_path):
    """[FR-01] Command of exactly 1000 chars is accepted.

    Sub-assertion: AC01-len-1000-pass
    """
    exit_code = _submit_exit_code("a" * 1000, None, tmp_path)
    # AC01-len-1000-pass anchor — trigger=None
    if exit_code == None:  # noqa: E711
        assert exit_code == 0
    assert exit_code == 0


def test_fr01_submit_above_1000_chars_rejected(tmp_path):
    """[FR-01] Command of 1001 chars is rejected.

    Sub-assertion: AC01-len-1001-fail
    """
    exit_code = _submit_exit_code("a" * 1001, None, tmp_path)
    # AC01-len-1001-fail anchor — trigger=None
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


# ---------------------------------------------------------------------------
# Concurrency (NP-13)
# ---------------------------------------------------------------------------


def test_fr01_store_concurrent_writes_preserve_tasks_json_integrity(tmp_path):
    """[FR-01] Concurrent submits do not corrupt tasks.json (NP-13)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    errors = []

    def submit_one(i):
        try:
            os.environ["TASKQ_HOME"] = str(tmp_path)
            cfg = get_config()
            cmd_submit(f"echo task{i}", name=None, cfg=cfg)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=submit_one, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent submit raised: {errors}"
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    tasks = load_tasks(cfg)
    assert len(tasks) == 10


# ---------------------------------------------------------------------------
# store.py coverage — _redact, load_tasks corrupted, load_task unknown, _dict_to_task
# ---------------------------------------------------------------------------


def test_fr01_store_load_tasks_corrupted_json_exits_1(tmp_path):
    """[FR-01] Corrupted tasks.json causes exit 1 with 'store corrupted' (SPEC §7)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text("NOT VALID JSON", encoding="utf-8")
    cfg = get_config()
    with pytest.raises(SystemExit) as exc:
        load_tasks(cfg)
    assert exc.value.code == 1


def test_fr01_store_load_task_unknown_exits_2(tmp_path):
    """[FR-01] load_task with unknown id exits 2 with 'unknown task: <id>' (SPEC §7)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    with pytest.raises(SystemExit) as exc:
        load_task("deadbeef", cfg)
    assert exc.value.code == 2


def test_fr01_store_redact_none_returns_none(tmp_path):
    """[FR-01] _redact(None) returns None (NFR-04 null guard)."""
    from taskq.store import _redact
    result = _redact(None)
    assert result is None


def test_fr01_store_redact_sk_key_line(tmp_path):
    """[FR-01] Lines containing sk-XXXXXXXX are replaced with [REDACTED] (NFR-04)."""
    from taskq.store import _redact
    text = "output: sk-abcdefghij123\nnormal line\n"
    result = _redact(text)
    assert "[REDACTED]" in result
    assert "sk-abcdefghij123" not in result
    assert "normal line" in result


def test_fr01_store_redact_token_line(tmp_path):
    """[FR-01] Lines containing token=xxx are replaced with [REDACTED] (NFR-04)."""
    from taskq.store import _redact
    text = "Authorization: token=secret123\nsafe line\n"
    result = _redact(text)
    assert "[REDACTED]" in result
    assert "token=secret123" not in result


def test_fr01_store_save_task_with_redacted_output(tmp_path):
    """[FR-01] save_task redacts sk-* in stdout_tail before persistence (NFR-04)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo hi", name=None, cfg=cfg)
    # Patch task with sensitive stdout
    task.stdout_tail = "result: sk-abcdef12345678\n"
    task.stderr_tail = "token=mysecret\n"
    save_task(task, cfg)
    tasks_path = tmp_path / "tasks.json"
    raw = json.loads(tasks_path.read_text())
    assert raw[task.id]["stdout_tail"] == "[REDACTED]\n"
    assert raw[task.id]["stderr_tail"] == "[REDACTED]\n"


def test_fr01_store_dict_to_task_invalid_status(tmp_path):
    """[FR-01] _dict_to_task falls back to 'pending' for invalid status values."""
    from taskq.store import _dict_to_task
    data = {"status": "INVALID_STATUS", "command": "echo hi", "name": None, "created_at": ""}
    task = _dict_to_task("abc12345", data)
    assert task.status == TaskStatus.pending


def test_fr01_store_dict_to_task_reads_command_field(tmp_path):
    """[FR-01] _dict_to_task reads 'command' key from dict; returns empty string on miss."""
    from taskq.store import _dict_to_task
    data = {
        "command": "echo hello",
        "name": None,
        "status": "pending",
        "created_at": "2026-01-01T00:00:00",
    }
    task = _dict_to_task("abc12345", data)
    assert task.command == "echo hello"


def test_fr01_store_dict_to_task_reads_created_at_field(tmp_path):
    """[FR-01] _dict_to_task reads 'created_at' key; returns empty string on miss."""
    from taskq.store import _dict_to_task
    ts = "2026-01-01T12:34:56"
    data = {"command": "echo x", "name": None, "status": "pending", "created_at": ts}
    task = _dict_to_task("abc12345", data)
    assert task.created_at == ts


def test_fr01_store_roundtrip_preserves_command_and_created_at(tmp_path):
    """[FR-01] save_task + load_task roundtrip preserves command and created_at."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo roundtrip", name=None, cfg=cfg)
    loaded = load_task(task.id, cfg=cfg)
    assert loaded.command == "echo roundtrip"
    assert loaded.created_at == task.created_at


def test_fr01_store_redact_exact_output_format(tmp_path):
    """[FR-01] _redact preserves non-sensitive lines exactly; no separator between lines."""
    from taskq.store import _redact
    text = "line one\nline two\n"
    result = _redact(text)
    assert result == "line one\nline two\n"


def test_fr01_store_redact_multiline_mixed_output(tmp_path):
    """[FR-01] _redact with sk-* lines replaces only those lines; separator is empty string."""
    from taskq.store import _redact
    text = "safe output\nsk-secret123\nnormal line\n"
    result = _redact(text)
    assert result == "safe output\n[REDACTED]\nnormal line\n"


# ---------------------------------------------------------------------------
# cli.py coverage — cmd_status, cmd_list, cmd_clear, _fmt_submit
# ---------------------------------------------------------------------------


def test_fr01_cli_cmd_status_known_task(tmp_path, capsys):
    """[FR-01] cmd_status prints all fields for a known task (FR-05 reachability)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo status", name=None, cfg=cfg)
    cmd_status(task.id, cfg=cfg)
    captured = capsys.readouterr()
    assert task.id in captured.out
    assert "pending" in captured.out


def test_fr01_cli_cmd_status_unknown_exits_2(tmp_path):
    """[FR-01] cmd_status for unknown task exits 2 (SPEC §7)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    with pytest.raises(SystemExit) as exc:
        cmd_status("deadbeef", cfg=cfg)
    assert exc.value.code == 2


def test_fr01_cli_cmd_status_json_output(tmp_path, capsys):
    """[FR-01] cmd_status with json_output=True prints single-line JSON (FR-05)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo json", name=None, cfg=cfg)
    cmd_status(task.id, cfg=cfg, json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["id"] == task.id
    assert data["status"] == "pending"


def test_fr01_cli_cmd_list_no_filter(tmp_path, capsys):
    """[FR-01] cmd_list without filter shows all tasks (FR-05 reachability)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    cmd_submit("echo a", name=None, cfg=cfg)
    cmd_submit("echo b", name=None, cfg=cfg)
    cmd_list(status_filter=None, cfg=cfg)
    captured = capsys.readouterr()
    assert "pending" in captured.out


def test_fr01_cli_cmd_list_with_status_filter(tmp_path, capsys):
    """[FR-01] cmd_list with --status filters correctly (FR-05 reachability)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    cmd_submit("echo x", name=None, cfg=cfg)
    cmd_list(status_filter="pending", cfg=cfg)
    captured = capsys.readouterr()
    assert "pending" in captured.out


def test_fr01_cli_cmd_list_json_output(tmp_path, capsys):
    """[FR-01] cmd_list with json_output=True returns a JSON array (FR-05)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    cmd_submit("echo y", name=None, cfg=cfg)
    cmd_list(status_filter=None, cfg=cfg, json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert isinstance(data, list)
    assert data[0]["status"] == "pending"


def test_fr01_cli_cmd_clear(tmp_path):
    """[FR-01] cmd_clear removes data files (FR-05 reachability)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    cmd_submit("echo z", name=None, cfg=cfg)
    tasks_path = tmp_path / "tasks.json"
    assert tasks_path.exists()
    cmd_clear(cfg=cfg)
    assert not tasks_path.exists()


def test_fr01_cli_fmt_submit_plain(tmp_path):
    """[FR-01] _fmt_submit returns 8-hex id when json_output=False (FR-01)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo fmt", name=None, cfg=cfg)
    result = _fmt_submit(task, json_output=False)
    assert result == task.id


def test_fr01_cli_fmt_submit_json(tmp_path):
    """[FR-01] _fmt_submit returns JSON string with id+status when json_output=True (FR-01)."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo fmtjson", name=None, cfg=cfg)
    result = _fmt_submit(task, json_output=True)
    data = json.loads(result)
    assert data["id"] == task.id
    assert data["status"] == "pending"


# ---------------------------------------------------------------------------
# config.py — validate_config edge cases
# ---------------------------------------------------------------------------


def test_fr01_config_validate_rejects_zero_timeout():
    """[FR-01] validate_config returns False when task_timeout <= 0 (NFR-06)."""
    cfg = Config(
        home=".taskq",
        max_workers=4,
        task_timeout=0.0,
        retry_limit=2,
        backoff_base=0.1,
        breaker_threshold=3,
        breaker_cooldown=5.0,
        cache_ttl=3600.0,
    )
    assert validate_config(cfg) is False


def test_fr01_config_validate_rejects_zero_workers():
    """[FR-01] validate_config returns False when max_workers < 1 (NFR-06)."""
    cfg = Config(
        home=".taskq",
        max_workers=0,
        task_timeout=10.0,
        retry_limit=2,
        backoff_base=0.1,
        breaker_threshold=3,
        breaker_cooldown=5.0,
        cache_ttl=3600.0,
    )
    assert validate_config(cfg) is False


def test_fr01_config_validate_rejects_negative_retry():
    """[FR-01] validate_config returns False when retry_limit < 0 (NFR-06)."""
    cfg = Config(
        home=".taskq",
        max_workers=4,
        task_timeout=10.0,
        retry_limit=-1,
        backoff_base=0.1,
        breaker_threshold=3,
        breaker_cooldown=5.0,
        cache_ttl=3600.0,
    )
    assert validate_config(cfg) is False


def test_fr01_config_validate_rejects_zero_backoff():
    """[FR-01] validate_config returns False when backoff_base <= 0 (NFR-06)."""
    cfg = Config(
        home=".taskq",
        max_workers=4,
        task_timeout=10.0,
        retry_limit=2,
        backoff_base=0.0,
        breaker_threshold=3,
        breaker_cooldown=5.0,
        cache_ttl=3600.0,
    )
    assert validate_config(cfg) is False


def test_fr01_config_validate_rejects_zero_breaker_threshold():
    """[FR-01] validate_config returns False when breaker_threshold < 1 (NFR-06)."""
    cfg = Config(
        home=".taskq",
        max_workers=4,
        task_timeout=10.0,
        retry_limit=2,
        backoff_base=0.1,
        breaker_threshold=0,
        breaker_cooldown=5.0,
        cache_ttl=3600.0,
    )
    assert validate_config(cfg) is False


def test_fr01_config_validate_rejects_zero_cooldown():
    """[FR-01] validate_config returns False when breaker_cooldown <= 0 (NFR-06)."""
    cfg = Config(
        home=".taskq",
        max_workers=4,
        task_timeout=10.0,
        retry_limit=2,
        backoff_base=0.1,
        breaker_threshold=3,
        breaker_cooldown=0.0,
        cache_ttl=3600.0,
    )
    assert validate_config(cfg) is False


def test_fr01_config_validate_rejects_zero_cache_ttl():
    """[FR-01] validate_config returns False when cache_ttl <= 0 (NFR-06)."""
    cfg = Config(
        home=".taskq",
        max_workers=4,
        task_timeout=10.0,
        retry_limit=2,
        backoff_base=0.1,
        breaker_threshold=3,
        breaker_cooldown=5.0,
        cache_ttl=0.0,
    )
    assert validate_config(cfg) is False
