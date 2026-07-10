"""In-process unit tests for FR-01 to raise test_coverage.

The end-to-end tests in test_fr01.py invoke the CLI via subprocess so
pytest-cov cannot track cli.py execution in the child process (tooling
limitation). These tests import cli.py and call the validation/storage
helpers in-process so coverage of 03-development/src/taskq/cli.py is
measured by pytest-cov.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from taskq import cli

ID_PATTERN = re.compile(r"[0-9a-f]{8}")


# ── _validate_command ──────────────────────────────────────────────────────


def test_validate_command_empty_rejected() -> None:
    assert cli._validate_command("") is not None


def test_validate_command_whitespace_only_rejected() -> None:
    assert cli._validate_command("   ") is not None


def test_validate_command_at_limit_accepted() -> None:
    assert cli._validate_command("x" * 1000) is None


def test_validate_command_over_limit_rejected() -> None:
    assert cli._validate_command("x" * 1001) is not None


@pytest.mark.parametrize("char", [";", "|", "&", "$", ">", "<", "`"])
def test_validate_command_injection_chars_rejected(char: str) -> None:
    assert cli._validate_command(f"echo hi{char} rm x") is not None


def test_validate_command_valid_accepted() -> None:
    assert cli._validate_command("echo hi") is None


# ── _validate_name ─────────────────────────────────────────────────────────


def test_validate_name_none_means_no_check() -> None:
    assert cli._validate_name(None, {}) is None


def test_validate_name_unique_accepted() -> None:
    assert cli._validate_name("alpha", {}) is None


def test_validate_name_conflicts_with_pending() -> None:
    tasks = {"12345678": {"name": "dup", "status": "pending"}}
    assert cli._validate_name("dup", tasks) is not None


def test_validate_name_conflicts_with_running() -> None:
    tasks = {"12345678": {"name": "dup", "status": "running"}}
    assert cli._validate_name("dup", tasks) is not None


def test_validate_name_does_not_conflict_with_done() -> None:
    tasks = {"12345678": {"name": "dup", "status": "done"}}
    assert cli._validate_name("dup", tasks) is None


def test_validate_name_does_not_conflict_with_failed() -> None:
    tasks = {"12345678": {"name": "dup", "status": "failed"}}
    assert cli._validate_name("dup", tasks) is None


def test_validate_name_does_not_conflict_with_timeout() -> None:
    tasks = {"12345678": {"name": "dup", "status": "timeout"}}
    assert cli._validate_name("dup", tasks) is None


# ── _load_tasks / _atomic_write_tasks ──────────────────────────────────────


def test_load_tasks_missing_file_returns_empty(tmp_path: Path) -> None:
    assert cli._load_tasks(tmp_path) == {}


def test_load_tasks_existing_file_returns_dict(tmp_path: Path) -> None:
    payload = {"abc": {"id": "abc", "command": "echo", "name": None, "status": "pending"}}
    (tmp_path / "tasks.json").write_text(json.dumps(payload))
    assert cli._load_tasks(tmp_path) == payload


def test_atomic_write_tasks_creates_file(tmp_path: Path) -> None:
    cli._atomic_write_tasks(tmp_path, {"abc": {"id": "abc", "command": "echo"}})
    out = json.loads((tmp_path / "tasks.json").read_text())
    assert out == {"abc": {"id": "abc", "command": "echo"}}


def test_atomic_write_tasks_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "dir"
    cli._atomic_write_tasks(nested, {"abc": {"id": "abc"}})
    assert (nested / "tasks.json").exists()


def test_atomic_write_tasks_no_tmp_left_behind(tmp_path: Path) -> None:
    cli._atomic_write_tasks(tmp_path, {"abc": {"id": "abc"}})
    assert not (tmp_path / "tasks.json.tmp").exists()


# ── _parse_submit_args ─────────────────────────────────────────────────────


def test_parse_submit_args_command_only() -> None:
    assert cli._parse_submit_args(["echo"]) == ("echo", None)


def test_parse_submit_args_with_name() -> None:
    assert cli._parse_submit_args(["echo", "--name", "alpha"]) == ("echo", "alpha")


def test_parse_submit_args_empty_returns_2() -> None:
    assert cli._parse_submit_args([]) == 2


def test_parse_submit_args_name_at_end_no_value() -> None:
    # --name with no following value → name stays None
    assert cli._parse_submit_args(["echo", "--name"]) == ("echo", None)


# ── _submit (in-process) ───────────────────────────────────────────────────


def test_submit_valid_writes_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli._submit("echo hi", "alpha", json_mode=False)
    assert rc == 0
    tasks = json.loads((tmp_path / "tasks.json").read_text())
    assert len(tasks) == 1
    task = next(iter(tasks.values()))
    assert task["command"] == "echo hi"
    assert task["name"] == "alpha"
    assert task["status"] == "pending"
    assert task["created_at"].endswith("Z")
    # parseable as ISO 8601
    datetime.strptime(task["created_at"], "%Y-%m-%dT%H:%M:%SZ")


def test_submit_empty_returns_2_no_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli._submit("", None, json_mode=False)
    assert rc == 2
    assert not (tmp_path / "tasks.json").exists()
    err = capsys.readouterr().err
    assert err.strip()


def test_submit_too_long_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli._submit("x" * 1001, None, json_mode=False)
    assert rc == 2
    err = capsys.readouterr().err
    assert "1000" in err or "1001" in err


def test_submit_injection_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli._submit("echo hi; rm x", None, json_mode=False)
    assert rc == 2


def test_submit_duplicate_name_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    existing = {"12345678": {"id": "12345678", "name": "dup", "status": "pending"}}
    (tmp_path / "tasks.json").write_text(json.dumps(existing))
    rc = cli._submit("echo hi", "dup", json_mode=False)
    assert rc == 2
    after = json.loads((tmp_path / "tasks.json").read_text())
    assert after == existing


def test_submit_json_mode_emits_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli._submit("echo hi", None, json_mode=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert out.endswith("\n")
    assert out.count("\n") == 1
    payload = json.loads(out)
    assert set(payload) == {"id", "status"}
    assert ID_PATTERN.fullmatch(payload["id"])
    assert payload["status"] == "pending"


def test_submit_text_mode_emits_id_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli._submit("echo hi", None, json_mode=False)
    assert rc == 0
    out = capsys.readouterr().out
    task_id = out.strip()
    assert ID_PATTERN.fullmatch(task_id)
    assert "\n" in out


# ── main (in-process) ──────────────────────────────────────────────────────


def test_main_submit_text_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.main(["submit", "echo", "hi"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert ID_PATTERN.fullmatch(out)


def test_main_submit_json_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.main(["--json", "submit", "echo", "hi"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pending"


def test_main_unknown_command_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.main(["bogus"])
    assert rc == 2


def test_main_submit_empty_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.main(["submit", ""])
    assert rc == 2


def test_main_default_argv_uses_sys_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["taskq", "submit", "echo", "hi"])
    rc = cli.main()
    assert rc == 0


# ── _home ──────────────────────────────────────────────────────────────────


def test_home_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TASKQ_HOME", "/tmp/some-home")
    assert cli._home() == Path("/tmp/some-home")
