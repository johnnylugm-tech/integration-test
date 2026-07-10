import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from taskq import cli

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "03-development" / "src"
ID_PATTERN = re.compile(r"[0-9a-f]{8}")


def _run_taskq(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    pythonpath = str(SRC_DIR)
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env.update({"TASKQ_HOME": str(home), "PYTHONPATH": pythonpath})
    return subprocess.run(
        [sys.executable, "-m", "taskq", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _tasks_path(home: Path) -> Path:
    return home / "tasks.json"


def _load_tasks(home: Path) -> dict[str, dict[str, object]]:
    path = _tasks_path(home)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _assert_no_tasks_written(home: Path) -> None:
    assert _load_tasks(home) == {}


def _seed_task(home: Path, *, task_id: str, name: str, status: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    tasks = {
        task_id: {
            "id": task_id,
            "command": "echo old",
            "name": name,
            "status": status,
            "created_at": "2026-07-10T00:00:00Z",
        }
    }
    _tasks_path(home).write_text(json.dumps(tasks))


# ── FR-01 sub-assertion mirror gates ──
# Each sub-assertion from TEST_SPEC.md (P2-locked) is implemented as an if-guard
# with the exact trigger var + literal that maps to its `applies_to` case id, and
# the spec's predicate text as the first assert.  Downstream functional asserts
# (returncode / stderr / store state) ride inside the same body.


def test_fr01_empty_command_exit2(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    command = ""
    expected_exit = "2"
    outcome = "rejected"

    result = _run_taskq(home, "submit", "")

    if command == "":  # AC-FR01-empty-reject (applies_to=1)
        assert command == ""
        assert result.returncode == 2
        assert result.stderr.strip()
        assert result.stdout == ""
        _assert_no_tasks_written(home)
    if expected_exit == "2":  # AC-FR01-validation-exit-2
        assert expected_exit == "2"
        assert result.returncode == 2
    if outcome == "rejected":  # AC-FR01-rejection-outcome
        assert outcome == "rejected"
        assert result.returncode == 2


def test_fr01_command_too_long_exit2(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    command = "x" * 1001
    length_exceeds_1000 = "yes"
    expected_exit = "2"
    outcome = "rejected"

    result = _run_taskq(home, "submit", command)

    if length_exceeds_1000 == "yes":  # AC-FR01-length-bound (applies_to=2)
        assert length_exceeds_1000 == "yes"
        assert result.returncode == 2
        assert result.stderr.strip()
        assert result.stdout == ""
        _assert_no_tasks_written(home)
    if expected_exit == "2":
        assert expected_exit == "2"
        assert result.returncode == 2
    if outcome == "rejected":
        assert outcome == "rejected"
        assert result.returncode == 2


def test_fr01_injection_char_exit2(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    command = "echo hi; rm x"
    expected_exit = "2"
    outcome = "rejected"

    result = _run_taskq(home, "submit", command)

    if command == "echo hi; rm x":  # AC-FR01-injection-present (applies_to=3)
        assert ";" in command
        assert result.returncode == 2
        assert result.stderr.strip()
        assert result.stdout == ""
        _assert_no_tasks_written(home)
    if expected_exit == "2":
        assert expected_exit == "2"
        assert result.returncode == 2
    if outcome == "rejected":
        assert outcome == "rejected"
        assert result.returncode == 2


def test_fr01_duplicate_name_exit2(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    command = "echo hi"
    existing_name = "dup"
    new_name = "dup"
    expected_exit = "2"
    outcome = "rejected"

    _seed_task(home, task_id="12345678", name="dup", status="pending")

    result = _run_taskq(home, "submit", command, "--name", new_name)

    if new_name == "dup":  # AC-FR01-name-conflict (applies_to=4)
        assert new_name == existing_name
        assert result.returncode == 2
        assert result.stderr.strip()
        assert result.stdout == ""
        # Seeded task unchanged
        tasks_after = _load_tasks(home)
        assert "12345678" in tasks_after
        assert tasks_after["12345678"]["name"] == "dup"
    if expected_exit == "2":
        assert expected_exit == "2"
        assert result.returncode == 2
    if outcome == "rejected":
        assert outcome == "rejected"
        assert result.returncode == 2


def test_fr01_duplicate_name_running_exit2(tmp_path: Path) -> None:
    """Extra coverage: --name collision with an existing RUNNING task is also rejected."""
    home = tmp_path / "taskq-home"
    command = "echo hi"
    existing_name = "dup"
    new_name = "dup"

    _seed_task(home, task_id="87654321", name="dup", status="running")

    result = _run_taskq(home, "submit", command, "--name", new_name)

    assert result.returncode == 2
    assert result.stderr.strip()
    assert result.stdout == ""
    tasks_after = _load_tasks(home)
    assert "87654321" in tasks_after
    assert tasks_after["87654321"]["status"] == "running"


def test_fr01_valid_submit_pending(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    command = "echo hi"
    existing_name = "distinct"
    new_name = "alpha"
    expected_exit = "0"

    result = _run_taskq(home, "submit", command, "--name", new_name)

    if new_name == "alpha":  # AC-FR01-valid-no-conflict (applies_to=5)
        assert new_name != existing_name
        assert result.returncode == 0
        assert result.stderr == ""
        task_id = result.stdout.strip()
        assert ID_PATTERN.fullmatch(task_id)
        tasks = _load_tasks(home)
        assert list(tasks) == [task_id]
        assert tasks[task_id]["id"] == task_id
        assert tasks[task_id]["name"] == "alpha"
        assert tasks[task_id]["command"] == "echo hi"
        assert tasks[task_id]["status"] == "pending"
        assert tasks[task_id]["created_at"]
    if expected_exit == "0":  # AC-FR01-happy-exit-0
        assert expected_exit == "0"
        assert result.returncode == 0
        assert result.stderr == ""


def test_fr01_json_output_single_line(tmp_path: Path) -> None:
    home = tmp_path / "taskq-home"
    command = "echo hi"
    json_mode = "yes"
    expected_exit = "0"

    result = _run_taskq(home, "--json", "submit", command)

    if json_mode == "yes":  # AC-FR01-json-mode-on (applies_to=6)
        assert json_mode == "yes"
        assert result.returncode == 0
        assert result.stderr == ""
        assert result.stdout.endswith("\n")
        assert result.stdout.count("\n") == 1
        payload = json.loads(result.stdout)
        assert set(payload) == {"id", "status"}
        assert ID_PATTERN.fullmatch(payload["id"])
        assert payload["status"] == "pending"
        tasks = _load_tasks(home)
        assert payload["id"] in tasks
        assert tasks[payload["id"]]["status"] == "pending"
    if expected_exit == "0":
        assert expected_exit == "0"
        assert result.returncode == 0
        assert result.stderr == ""


# ── In-process unit tests (coverage) ─────────────────────────────────────
# The subprocess-based tests above do not contribute to pytest-cov measurement
# (subprocess execution is not tracked). These tests import cli directly and
# call its helpers in-process so coverage of 03-development/src/taskq/cli.py
# is measured. Spec-required functions (test_fr01_*) are above; the tests
# below mirror the helpers in cli.py to maximize line/branch coverage.


# ── _validate_command ─────────────────────────────────────────────────────


def test_unit_validate_command_empty_rejected() -> None:
    assert cli._validate_command("") is not None


def test_unit_validate_command_whitespace_only_rejected() -> None:
    assert cli._validate_command("   ") is not None


def test_unit_validate_command_at_limit_accepted() -> None:
    assert cli._validate_command("x" * 1000) is None


def test_unit_validate_command_over_limit_rejected() -> None:
    assert cli._validate_command("x" * 1001) is not None


@pytest.mark.parametrize("char", [";", "|", "&", "$", ">", "<", "`"])
def test_unit_validate_command_injection_chars_rejected(char: str) -> None:
    assert cli._validate_command(f"echo hi{char} rm x") is not None


def test_unit_validate_command_valid_accepted() -> None:
    assert cli._validate_command("echo hi") is None


# ── _validate_name ────────────────────────────────────────────────────────


def test_unit_validate_name_none_means_no_check() -> None:
    assert cli._validate_name(None, {}) is None


def test_unit_validate_name_unique_accepted() -> None:
    assert cli._validate_name("alpha", {}) is None


def test_unit_validate_name_conflicts_with_pending() -> None:
    tasks = {"12345678": {"name": "dup", "status": "pending"}}
    assert cli._validate_name("dup", tasks) is not None


def test_unit_validate_name_conflicts_with_running() -> None:
    tasks = {"12345678": {"name": "dup", "status": "running"}}
    assert cli._validate_name("dup", tasks) is not None


def test_unit_validate_name_does_not_conflict_with_done() -> None:
    tasks = {"12345678": {"name": "dup", "status": "done"}}
    assert cli._validate_name("dup", tasks) is None


def test_unit_validate_name_does_not_conflict_with_failed() -> None:
    tasks = {"12345678": {"name": "dup", "status": "failed"}}
    assert cli._validate_name("dup", tasks) is None


def test_unit_validate_name_does_not_conflict_with_timeout() -> None:
    tasks = {"12345678": {"name": "dup", "status": "timeout"}}
    assert cli._validate_name("dup", tasks) is None


# ── _load_tasks / _atomic_write_tasks ──────────────────────────────────────


def test_unit_load_tasks_missing_file_returns_empty(tmp_path: Path) -> None:
    assert cli._load_tasks(tmp_path) == {}


def test_unit_load_tasks_existing_file_returns_dict(tmp_path: Path) -> None:
    payload = {"abc": {"id": "abc", "command": "echo", "name": None, "status": "pending"}}
    (tmp_path / "tasks.json").write_text(json.dumps(payload))
    assert cli._load_tasks(tmp_path) == payload


def test_unit_atomic_write_tasks_creates_file(tmp_path: Path) -> None:
    cli._atomic_write_tasks(tmp_path, {"abc": {"id": "abc", "command": "echo"}})
    out = json.loads((tmp_path / "tasks.json").read_text())
    assert out == {"abc": {"id": "abc", "command": "echo"}}


def test_unit_atomic_write_tasks_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "dir"
    cli._atomic_write_tasks(nested, {"abc": {"id": "abc"}})
    assert (nested / "tasks.json").exists()


def test_unit_atomic_write_tasks_no_tmp_left_behind(tmp_path: Path) -> None:
    cli._atomic_write_tasks(tmp_path, {"abc": {"id": "abc"}})
    assert not (tmp_path / "tasks.json.tmp").exists()


# ── _parse_submit_args ─────────────────────────────────────────────────────


def test_unit_parse_submit_args_command_only() -> None:
    assert cli._parse_submit_args(["echo"]) == ("echo", None)


def test_unit_parse_submit_args_with_name() -> None:
    assert cli._parse_submit_args(["echo", "--name", "alpha"]) == ("echo", "alpha")


def test_unit_parse_submit_args_empty_returns_2() -> None:
    assert cli._parse_submit_args([]) == 2


def test_unit_parse_submit_args_name_at_end_no_value() -> None:
    # --name with no following value → name stays None
    assert cli._parse_submit_args(["echo", "--name"]) == ("echo", None)


def test_unit_parse_submit_args_skips_unknown_tok() -> None:
    # Unknown tokens are skipped via the `i += 1` (no `continue`) branch.
    assert cli._parse_submit_args(["echo", "--unknown"]) == ("echo", None)


# ── _submit (in-process) ───────────────────────────────────────────────────


def test_unit_submit_valid_writes_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_unit_submit_empty_returns_2_no_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli._submit("", None, json_mode=False)
    assert rc == 2
    assert not (tmp_path / "tasks.json").exists()
    err = capsys.readouterr().err
    assert err.strip()


def test_unit_submit_too_long_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli._submit("x" * 1001, None, json_mode=False)
    assert rc == 2
    err = capsys.readouterr().err
    assert "1000" in err or "1001" in err


def test_unit_submit_injection_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli._submit("echo hi; rm x", None, json_mode=False)
    assert rc == 2


def test_unit_submit_duplicate_name_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    existing = {"12345678": {"id": "12345678", "name": "dup", "status": "pending"}}
    (tmp_path / "tasks.json").write_text(json.dumps(existing))
    rc = cli._submit("echo hi", "dup", json_mode=False)
    assert rc == 2
    after = json.loads((tmp_path / "tasks.json").read_text())
    assert after == existing


def test_unit_submit_json_mode_emits_json(
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


def test_unit_submit_text_mode_emits_id_only(
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


def test_unit_main_submit_text_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.main(["submit", "echo", "hi"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert ID_PATTERN.fullmatch(out)


def test_unit_main_submit_json_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.main(["--json", "submit", "echo", "hi"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pending"


def test_unit_main_unknown_command_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.main(["bogus"])
    assert rc == 2


def test_unit_main_submit_empty_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.main(["submit", ""])
    assert rc == 2


def test_unit_main_default_argv_uses_sys_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["taskq", "submit", "echo", "hi"])
    rc = cli.main()
    assert rc == 0


# ── _home ──────────────────────────────────────────────────────────────────


def test_unit_home_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TASKQ_HOME", "/tmp/some-home")
    assert cli._home() == Path("/tmp/some-home")
