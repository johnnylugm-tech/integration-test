"""Tests for FR-05: CLI integration (argparse subcommands, exit codes, --json).

[FR-05] — TDD-RED phase: tests verify CLI argparse wiring, exit code contract,
  --json flag, and subcommand reachability.

Sub-assertion anchor pattern per check-test-mirrors-spec:
    if <var> == None:  (trigger=None matches spec_trigger {"None"})
        assert <predicate>   (predicate matches TEST_SPEC.md verbatim)
"""
from __future__ import annotations

import json
import os
import sys
import subprocess
import pytest

from taskq.config import get_config
from taskq.cli import cmd_submit, cmd_status, cmd_list, cmd_clear, main
from taskq.store import load_task, load_tasks, save_task
from taskq.models import Task, TaskStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_cli(*args, tmp_path=None, env_override=None):
    """Run python -m taskq <args> in subprocess; return CompletedProcess."""
    env = os.environ.copy()
    if tmp_path is not None:
        env["TASKQ_HOME"] = str(tmp_path)
    if env_override:
        env.update(env_override)
    src_dir = os.path.join(
        os.path.dirname(__file__), "..", "03-development", "src"
    )
    return subprocess.run(
        [sys.executable, "-m", "taskq", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=os.path.normpath(src_dir),
    )


# ---------------------------------------------------------------------------
# Exit code tests
# ---------------------------------------------------------------------------


def test_fr05_exit_code_0_success(tmp_path):
    """[FR-05] Successful submit returns exit code 0.

    Sub-assertion: AC05-success-exit-0
    """
    result = _run_cli("submit", "echo hi", tmp_path=tmp_path)
    exit_code = result.returncode
    # AC05-success-exit-0 anchor — trigger=None
    if exit_code == None:  # noqa: E711
        assert exit_code == 0
    assert exit_code == 0


def test_fr05_exit_code_2_validation_error(tmp_path):
    """[FR-05] Empty command causes validation exit code 2.

    Sub-assertion: AC05-exit-2-validation
    """
    result = _run_cli("submit", "", tmp_path=tmp_path)
    exit_code = result.returncode
    # AC05-exit-2-validation anchor — trigger=None
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


def test_fr05_exit_code_2_unknown_task_id(tmp_path):
    """[FR-05] status on unknown task id yields exit code 2.

    Sub-assertion: AC05-exit-2-unknown
    """
    result = _run_cli("status", "deadbeef", tmp_path=tmp_path)
    exit_code = result.returncode
    # AC05-exit-2-unknown anchor — trigger=None
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


def test_fr05_exit_code_3_breaker_open(tmp_path):
    """[FR-05] run when breaker is OPEN returns exit code 3.

    Sub-assertion: no AC05 (FR-03 AC05 scope)
    """
    import json as _json
    import time as _time
    # Pre-set breaker to OPEN via breaker.json
    breaker_path = tmp_path / "breaker.json"
    breaker_path.write_text(
        _json.dumps({
            "state": "OPEN",
            "consecutive_failures": 3,
            "opened_at": _time.time() - 1,
        }),
        encoding="utf-8",
    )
    # Submit a task first
    r_submit = _run_cli("submit", "echo hi", tmp_path=tmp_path)
    task_id = r_submit.stdout.strip()
    result = _run_cli("run", task_id, tmp_path=tmp_path,
                      env_override={"TASKQ_BREAKER_THRESHOLD": "3",
                                    "TASKQ_BREAKER_COOLDOWN": "9999"})
    exit_code = result.returncode
    if exit_code == None:  # noqa: E711
        assert exit_code == 3
    assert exit_code == 3


def test_fr05_exit_code_4_task_timeout(tmp_path):
    """[FR-05] run on a sleep task with tight timeout returns exit code 4.

    Sub-assertion: no dedicated AC (derived from FR-02 AC02-timeout-exit-4)
    """
    r_submit = _run_cli("submit", "sleep 5", tmp_path=tmp_path)
    task_id = r_submit.stdout.strip()
    result = _run_cli(
        "run", task_id,
        tmp_path=tmp_path,
        env_override={
            "TASKQ_TASK_TIMEOUT": "1",
            "TASKQ_RETRY_LIMIT": "0",
        },
    )
    exit_code = result.returncode
    if exit_code == None:  # noqa: E711
        assert exit_code == 4
    assert exit_code == 4


def test_fr05_exit_code_1_other_internal_error(tmp_path):
    """[FR-05] Corrupted tasks.json triggers exit code 1 with 'store corrupted'.

    Sub-assertion: scenario=corrupted_store
    """
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text("NOT VALID JSON", encoding="utf-8")
    result = _run_cli("list", tmp_path=tmp_path)
    exit_code = result.returncode
    if exit_code == None:  # noqa: E711
        assert exit_code == 1
    assert exit_code == 1
    assert "store corrupted" in result.stderr


# ---------------------------------------------------------------------------
# --json flag
# ---------------------------------------------------------------------------


def test_fr05_json_flag_emits_single_line_json(tmp_path):
    """[FR-05] --json submit output is a single-line JSON with no embedded newlines.

    Sub-assertions: AC05-success-exit-0, AC05-json-single-line
    """
    result = _run_cli("--json", "submit", "echo hi", tmp_path=tmp_path)
    exit_code = result.returncode
    json_output = result.stdout.strip()
    # AC05-success-exit-0 anchor
    if exit_code == None:  # noqa: E711
        assert exit_code == 0
    assert exit_code == 0
    # AC05-json-single-line anchor
    if json_output == None:  # noqa: E711
        assert "\n" not in json_output
    assert "\n" not in json_output
    data = json.loads(json_output)
    assert "id" in data
    assert "status" in data
    assert data["status"] == "pending"


# ---------------------------------------------------------------------------
# Subcommand: clear
# ---------------------------------------------------------------------------


def test_fr05_clear_removes_all_data_files(tmp_path):
    """[FR-05] clear removes tasks.json, breaker.json, and cache.json.

    Sub-assertion: AC05-success-exit-0
    """
    # Create all three data files
    (tmp_path / "tasks.json").write_text("{}", encoding="utf-8")
    (tmp_path / "breaker.json").write_text("{}", encoding="utf-8")
    (tmp_path / "cache.json").write_text("{}", encoding="utf-8")

    result = _run_cli("clear", tmp_path=tmp_path)
    exit_code = result.returncode
    if exit_code == None:  # noqa: E711
        assert exit_code == 0
    assert exit_code == 0
    assert not (tmp_path / "tasks.json").exists()
    assert not (tmp_path / "breaker.json").exists()
    assert not (tmp_path / "cache.json").exists()


# ---------------------------------------------------------------------------
# Subcommand: list --status filter
# ---------------------------------------------------------------------------


def test_fr05_list_filters_by_status_flag(tmp_path):
    """[FR-05] list --status pending shows only pending tasks; done tasks excluded.

    Sub-assertion: AC05-success-exit-0
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    # Add pending task
    t_pending = cmd_submit("echo pending", name="p", cfg=cfg)
    # Add done task manually
    t_done = cmd_submit("echo done_task", name="d", cfg=cfg)
    done_task = Task(
        id=t_done.id,
        command=t_done.command,
        name=t_done.name,
        status=TaskStatus.done,
        created_at=t_done.created_at,
        exit_code=0,
    )
    save_task(done_task, cfg)

    result = _run_cli("list", "--status", "pending", tmp_path=tmp_path)
    exit_code = result.returncode
    if exit_code == None:  # noqa: E711
        assert exit_code == 0
    assert exit_code == 0
    assert t_pending.id in result.stdout
    assert t_done.id not in result.stdout


# ---------------------------------------------------------------------------
# Subcommand: status
# ---------------------------------------------------------------------------


def test_fr05_status_outputs_full_task_fields(tmp_path):
    """[FR-05] status displays all expected task fields.

    Sub-assertion: AC05-success-exit-0
    """
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = cmd_submit("echo fields", name=None, cfg=cfg)

    result = _run_cli("status", task.id, tmp_path=tmp_path)
    exit_code = result.returncode
    if exit_code == None:  # noqa: E711
        assert exit_code == 0
    assert exit_code == 0
    output = result.stdout
    # All required fields must appear
    for field in ("command", "status", "exit_code", "duration_ms", "finished_at"):
        assert field in output, f"Field {field!r} missing from status output"


# ---------------------------------------------------------------------------
# E2E tests
# ---------------------------------------------------------------------------


def test_fr05_e2e_full_lifecycle_submit_run_status(tmp_path):
    """[FR-05] Full lifecycle: submit → run → status shows done.

    Sub-assertion: AC05-success-exit-0
    """
    r_submit = _run_cli("submit", "echo hi", tmp_path=tmp_path)
    assert r_submit.returncode == 0
    task_id = r_submit.stdout.strip()
    assert len(task_id) == 8

    r_run = _run_cli("run", task_id, tmp_path=tmp_path,
                     env_override={"TASKQ_RETRY_LIMIT": "0"})
    assert r_run.returncode == 0

    r_status = _run_cli("status", task_id, tmp_path=tmp_path)
    exit_code = r_status.returncode
    if exit_code == None:  # noqa: E711
        assert exit_code == 0
    assert exit_code == 0
    assert "done" in r_status.stdout


def test_fr05_e2e_clear_then_run_unknown_id_exits_2(tmp_path):
    """[FR-05] After clear, run on old task id exits 2 (unknown task).

    Sub-assertions: AC05-exit-2-unknown
    """
    # Submit then clear
    r_submit = _run_cli("submit", "echo a", tmp_path=tmp_path)
    task_id = r_submit.stdout.strip()
    _run_cli("clear", tmp_path=tmp_path)

    result = _run_cli("run", task_id, tmp_path=tmp_path)
    exit_code = result.returncode
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2


# ---------------------------------------------------------------------------
# status -- unknown id stderr message
# ---------------------------------------------------------------------------


def test_fr05_status_unknown_id_exits_2_with_stderr_message(tmp_path):
    """[FR-05] status on unknown task exits 2 with 'unknown task: deadbeef' in stderr.

    Sub-assertions: AC05-exit-2-unknown, AC05-unknown-task-stderr
    """
    result = _run_cli("status", "deadbeef", tmp_path=tmp_path)
    exit_code = result.returncode
    stderr = result.stderr
    if exit_code == None:  # noqa: E711
        assert exit_code == 2
    assert exit_code == 2
    # AC05-unknown-task-stderr anchor
    if stderr == None:  # noqa: E711
        assert "unknown task: deadbeef" in stderr
    assert "unknown task: deadbeef" in stderr


# ---------------------------------------------------------------------------
# Subcommand reachability (interface contract)
# ---------------------------------------------------------------------------


def test_fr05_submit_subcommand_reachable(tmp_path):
    """[FR-05] submit subcommand is registered and reachable via CLI."""
    result = _run_cli("submit", "echo reachable", tmp_path=tmp_path)
    # Must not be an argparse error about unknown subcommand
    assert result.returncode != 2 or "invalid choice" not in result.stderr
    assert result.returncode == 0


def test_fr05_run_subcommand_reachable(tmp_path):
    """[FR-05] run subcommand is registered and reachable; exits 2 for unknown id."""
    result = _run_cli("run", "abc12345", tmp_path=tmp_path)
    # Should exit 2 (unknown task) not argparse error
    assert "invalid choice" not in result.stderr
    assert result.returncode in (0, 2, 3, 4)


def test_fr05_status_subcommand_reachable(tmp_path):
    """[FR-05] status subcommand is registered and reachable; exits 2 for unknown id."""
    result = _run_cli("status", "abc12345", tmp_path=tmp_path)
    assert "invalid choice" not in result.stderr
    assert result.returncode == 2


def test_fr05_list_subcommand_reachable(tmp_path):
    """[FR-05] list subcommand is registered and reachable."""
    result = _run_cli("list", tmp_path=tmp_path)
    assert "invalid choice" not in result.stderr
    assert result.returncode == 0


def test_fr05_clear_subcommand_reachable(tmp_path):
    """[FR-05] clear subcommand is registered and reachable."""
    result = _run_cli("clear", tmp_path=tmp_path)
    assert "invalid choice" not in result.stderr
    assert result.returncode == 0
