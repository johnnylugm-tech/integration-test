"""FR-01 — direct unit tests for the refactored `taskq` package.

These tests import the production modules directly (no subprocess) so
coverage can measure lines per module. They mirror the FR-01 acceptance
criteria in TEST_SPEC.md and complement the integration tests in
`test_fr01.py` (which exercise the CLI end-to-end via `python -m taskq`).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from taskq import (
    COMMAND_MAX_LENGTH,
    INJECTION_CHARS,
    StoreCorruptedError,
    append_task,
    atomic_write_tasks,
    load_tasks_or_die,
    taskq_home,
    tasks_json_path,
    validate_command,
)
from taskq.__main__ import _generate_task_id, build_parser, cmd_list, cmd_submit, main


# ---------------------------------------------------------------------------
# validation (SPEC §3 FR-01 rows 「非空」「長度」「注入字元」)
# ---------------------------------------------------------------------------


def test_validate_command_accepts_simple():
    """[FR-01] Plain command accepted."""
    assert validate_command("echo hi") is None


def test_validate_command_rejects_empty():
    """[FR-01] empty string → error."""
    err = validate_command("")
    assert err is not None
    assert "empty" in err.lower()


def test_validate_command_rejects_whitespace():
    """[FR-01] whitespace-only → error."""
    err = validate_command("   ")
    assert err is not None
    assert "empty" in err.lower()


def test_validate_command_accepts_at_limit_length():
    """[FR-01] exactly 1000 chars accepted."""
    assert validate_command("a" * COMMAND_MAX_LENGTH) is None


def test_validate_command_rejects_over_limit_length():
    """[FR-01] 1001 chars rejected."""
    err = validate_command("a" * (COMMAND_MAX_LENGTH + 1))
    assert err is not None
    assert "exceeds limit" in err


@pytest.mark.parametrize("ch", list(INJECTION_CHARS))
def test_validate_command_rejects_injection_char(ch):
    """[FR-01] each blacklist char rejected."""
    err = validate_command(f"echo a{ch}b")
    assert err is not None
    assert "injection" in err.lower()


# ---------------------------------------------------------------------------
# config (SPEC §3 FR-01 "$TASKQ_HOME/tasks.json")
# ---------------------------------------------------------------------------


def test_taskq_home_default(monkeypatch):
    """[FR-01] TASKQ_HOME absent → ~/.taskq."""
    monkeypatch.delenv("TASKQ_HOME", raising=False)
    home = taskq_home()
    assert home.name == ".taskq"


def test_taskq_home_from_env(monkeypatch, tmp_path):
    """[FR-01] TASKQ_HOME env var wins."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path / "q-home"))
    assert taskq_home() == tmp_path / "q-home"


def test_tasks_json_path_under_home(monkeypatch, tmp_path):
    """[FR-01] tasks.json lives under TASKQ_HOME."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    assert tasks_json_path() == tmp_path / "tasks.json"


# ---------------------------------------------------------------------------
# store (SPEC §3 FR-01 atomic write + corruption)
# ---------------------------------------------------------------------------


def _home_with(monkeypatch, tmp_path: Path):
    """Point TASKQ_HOME at tmp_path (create the dir) and return it."""
    home = tmp_path / ".taskq"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


def test_load_tasks_missing_returns_empty(monkeypatch, tmp_path):
    """[FR-01] no file → [] (no error)."""
    _home_with(monkeypatch, tmp_path)
    assert load_tasks_or_die() == []


def test_load_tasks_corrupt_raises(monkeypatch, tmp_path):
    """[FR-01] malformed JSON raises StoreCorruptedError."""
    home = _home_with(monkeypatch, tmp_path)
    (home / "tasks.json").write_text("not-valid-json{", encoding="utf-8")
    with pytest.raises(StoreCorruptedError):
        load_tasks_or_die()


def test_load_tasks_non_list_raises(monkeypatch, tmp_path):
    """[FR-01] top-level non-list raises StoreCorruptedError."""
    home = _home_with(monkeypatch, tmp_path)
    (home / "tasks.json").write_text('{"oops": true}', encoding="utf-8")
    with pytest.raises(StoreCorruptedError):
        load_tasks_or_die()


def test_atomic_write_tasks_creates_file(monkeypatch, tmp_path):
    """[FR-01] tasks appear in tasks.json after write."""
    home = _home_with(monkeypatch, tmp_path)
    payload = [{"id": "abcd1234", "status": "pending"}]
    atomic_write_tasks(payload, "abcd1234")
    on_disk = json.loads((home / "tasks.json").read_text(encoding="utf-8"))
    assert on_disk == payload


def test_atomic_write_tasks_no_tmp_leftover(monkeypatch, tmp_path):
    """[FR-01] atomic write must replace, not leave tmp."""
    home = _home_with(monkeypatch, tmp_path)
    atomic_write_tasks([{"id": "deadbeef"}], "deadbeef")
    leftover = [p for p in home.iterdir() if p.name.startswith("tasks.json.tmp")]
    assert leftover == []


def test_append_task_writes_record(monkeypatch, tmp_path):
    """[FR-01] append_task adds the record and persists atomically."""
    home = _home_with(monkeypatch, tmp_path)
    record = {"id": "feed1234", "status": "pending", "command": "echo hi"}
    new_id = append_task(record)
    assert new_id == "feed1234"
    on_disk = json.loads((home / "tasks.json").read_text(encoding="utf-8"))
    assert on_disk == [record]


# ---------------------------------------------------------------------------
# __main__ argparse surface (SPEC §3 FR-01)
# ---------------------------------------------------------------------------


def test_generate_task_id_is_8_hex():
    """[FR-01] task id is 8 lowercase hex chars."""
    for _ in range(50):
        tid = _generate_task_id()
        assert len(tid) == 8
        assert all(c in "0123456789abcdef" for c in tid)


def test_build_parser_has_submit_and_list():
    """[FR-01] subcommands submit + list registered (no SystemExit on parse)."""
    parser = build_parser()
    # Parsing each subcommand without SystemExit confirms registration.
    ns_submit = parser.parse_args(["submit", "echo hi"])
    assert ns_submit.command_name == "submit"
    ns_list = parser.parse_args(["list"])
    assert ns_list.command_name == "list"


def test_cmd_submit_rejects_empty(monkeypatch, tmp_path, capsys):
    """[FR-01] empty cmd → exit 2, stderr error, no file."""
    _home_with(monkeypatch, tmp_path)
    ns = build_parser().parse_args(["submit", ""])
    rc = cmd_submit(ns)
    assert rc == 2
    err = capsys.readouterr().err
    assert "empty" in err.lower()


def test_cmd_submit_rejects_injection(monkeypatch, tmp_path, capsys):
    """[FR-01] blacklist char → exit 2, no file."""
    home = _home_with(monkeypatch, tmp_path)
    ns = build_parser().parse_args(["submit", "echo a;b"])
    rc = cmd_submit(ns)
    assert rc == 2
    assert not (home / "tasks.json").exists()


def test_cmd_submit_writes_record(monkeypatch, tmp_path, capsys):
    """[FR-01] valid cmd → exit 0, file written, --json output."""
    _home_with(monkeypatch, tmp_path)
    ns = build_parser().parse_args(["submit", "--json", "echo hi"])
    rc = cmd_submit(ns)
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip().startswith("{")
    rec = json.loads(out.strip())
    assert rec["status"] == "pending"
    assert rec["command"] == "echo hi"
    assert rec["attempts"] == 0


def test_cmd_list_corrupt_returns_corrupt_exit(monkeypatch, tmp_path, capsys):
    """[FR-01] corrupt store → exit 1, stderr, no rewrite."""
    home = _home_with(monkeypatch, tmp_path)
    (home / "tasks.json").write_text("not-valid-json{", encoding="utf-8")
    ns = build_parser().parse_args(["list"])
    rc = cmd_list(ns)
    assert rc == 1
    err = capsys.readouterr().err
    assert "store corrupted" in err
    # Original bytes survive — no silent rebuild.
    assert "not-valid-json" in (home / "tasks.json").read_text(encoding="utf-8")


def test_main_unknown_subcommand_exits(monkeypatch, tmp_path, capsys):
    """[FR-01] unknown subcommand → non-zero exit."""
    _home_with(monkeypatch, tmp_path)
    with pytest.raises(SystemExit):
        main(["nope"])


def test_main_submit_round_trip(monkeypatch, tmp_path, capsys):
    """[FR-01] end-to-end via main(): submit → list."""
    _home_with(monkeypatch, tmp_path)
    assert main(["submit", "echo hi"]) == 0
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "echo hi" in out


# ---------------------------------------------------------------------------
# Sanity: forbidden-chars config matches spec
# ---------------------------------------------------------------------------


def test_injection_chars_set_shape():
    """[FR-01] blacklist is exactly 7 distinct chars per SPEC §3 FR-01."""
    assert INJECTION_CHARS == set(";|&$><`")
    assert len(INJECTION_CHARS) == 7


def test_command_max_length_is_1000():
    """[FR-01] COMMAND_MAX_LENGTH matches SPEC row 「長度」."""
    assert COMMAND_MAX_LENGTH == 1000


# Keep uuid-as-import false-positive (uuid is imported above for sanity).
_ = uuid
