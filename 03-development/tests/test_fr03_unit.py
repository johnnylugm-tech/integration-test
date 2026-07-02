"""FR-03 — direct unit tests for FR-03 specific code paths in `taskq/__main__.py`.

These tests import the production modules directly (no subprocess) so
coverage can measure lines per module. They complement the integration
tests in `test_fr03.py` (which exercise the CLI end-to-end via
`python -m taskq <subcommand>` and so don't contribute to pytest-cov for
the FR-03 branches: `cmd_status`, `cmd_clear`, list-truncation branch).

Coverage goal: lift `03-development/src/taskq/__main__.py` above 80% for
the FR-scoped Gate 1 evaluation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from taskq.__main__ import (
    LIST_COMMAND_PREVIEW_LEN,
    _generate_task_id,
    build_parser,
    cmd_clear,
    cmd_list,
    cmd_status,
    cmd_submit,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point TASKQ_HOME at `tmp_path/.taskq` (auto-mkdir) and return it."""
    home = tmp_path / ".taskq"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


def _seed_task(
    home: Path,
    task_id: str,
    command: str = "echo hi",
    **overrides,
) -> dict:
    """Write a single-task tasks.json under `home` and return the record."""
    record = {
        "id": task_id,
        "command": command,
        "status": "pending",
        "attempts": 0,
        "created_at": "2026-01-01T00:00:00+00:00",
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "duration_ms": None,
        "finished_at": None,
    }
    record.update(overrides)
    (home / "tasks.json").write_text(json.dumps([record]), encoding="utf-8")
    return record


# ---------------------------------------------------------------------------
# cmd_status — FR-03 status <id> (covers lines 243-262)
# ---------------------------------------------------------------------------


def test_unit_cmd_status_unknown_id(monkeypatch, tmp_path, capsys):
    """[FR-03] status with unknown id → exit 2 + stderr 'unknown task: <id>'."""
    _seed_home(monkeypatch, tmp_path)
    ns = build_parser().parse_args(["status", "deadbeef"])
    rc = cmd_status(ns)
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown task: deadbeef" in err


def test_unit_cmd_status_corrupt_store(monkeypatch, tmp_path, capsys):
    """[FR-03] status with corrupt store → exit 1 + stderr 'store corrupted'."""
    home = _seed_home(monkeypatch, tmp_path)
    (home / "tasks.json").write_text("not-valid-json{", encoding="utf-8")
    ns = build_parser().parse_args(["status", "deadbeef"])
    rc = cmd_status(ns)
    assert rc == 1
    assert "store corrupted" in capsys.readouterr().err


def test_unit_cmd_status_emits_single_line_json(monkeypatch, tmp_path, capsys):
    """[FR-03] status with a known id emits single-line JSON, no trailing newline."""
    home = _seed_home(monkeypatch, tmp_path)
    _seed_task(home, "abcd1234", "echo hi", status="done")
    ns = build_parser().parse_args(["status", "abcd1234"])
    rc = cmd_status(ns)
    assert rc == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 0, f"status --json must be single-line, got {out!r}"
    rec = json.loads(out)
    assert rec["id"] == "abcd1234"
    assert rec["status"] == "done"
    assert rec["command"] == "echo hi"


# ---------------------------------------------------------------------------
# cmd_clear — FR-03 clear (covers lines 265-276)
# ---------------------------------------------------------------------------


def test_unit_cmd_clear_writes_empty_list(monkeypatch, tmp_path, capsys):
    """[FR-03] clear writes an empty list to tasks.json atomically."""
    home = _seed_home(monkeypatch, tmp_path)
    _seed_task(home, "abcd1234")
    ns = build_parser().parse_args(["clear"])
    rc = cmd_clear(ns)
    assert rc == 0
    # tasks.json now exists and is an empty list.
    on_disk = json.loads((home / "tasks.json").read_text(encoding="utf-8"))
    assert on_disk == []


def test_unit_cmd_clear_when_store_missing(monkeypatch, tmp_path):
    """[FR-03] clear on a missing store creates an empty tasks.json."""
    home = _seed_home(monkeypatch, tmp_path)
    ns = build_parser().parse_args(["clear"])
    rc = cmd_clear(ns)
    assert rc == 0
    assert (home / "tasks.json").exists()
    on_disk = json.loads((home / "tasks.json").read_text(encoding="utf-8"))
    assert on_disk == []


# ---------------------------------------------------------------------------
# cmd_list — FR-03 list 50-char truncation (covers line 149-150 too)
# ---------------------------------------------------------------------------


def test_unit_cmd_list_truncates_command_to_50(monkeypatch, tmp_path, capsys):
    """[FR-03] list truncates each record's command field to first 50 chars."""
    home = _seed_home(monkeypatch, tmp_path)
    long_cmd = "a" * 200
    _seed_task(home, "abcd1234", command=long_cmd)
    ns = build_parser().parse_args(["list"])
    rc = cmd_list(ns)
    assert rc == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 0, f"list output must be single-line JSON, got {out!r}"
    tasks = json.loads(out)
    assert isinstance(tasks, list) and len(tasks) == 1
    assert len(tasks[0]["command"]) == LIST_COMMAND_PREVIEW_LEN
    assert tasks[0]["command"] == "a" * LIST_COMMAND_PREVIEW_LEN


def test_unit_cmd_list_short_command_unchanged(monkeypatch, tmp_path, capsys):
    """[FR-03] list leaves commands <= 50 chars unchanged."""
    home = _seed_home(monkeypatch, tmp_path)
    _seed_task(home, "abcd1234", command="echo hi")
    ns = build_parser().parse_args(["list"])
    rc = cmd_list(ns)
    assert rc == 0
    out = capsys.readouterr().out
    tasks = json.loads(out)
    assert tasks[0]["command"] == "echo hi"


def test_unit_cmd_list_corrupt_store(monkeypatch, tmp_path, capsys):
    """[FR-03] list against a corrupt store → exit 1 + stderr 'store corrupted'."""
    home = _seed_home(monkeypatch, tmp_path)
    (home / "tasks.json").write_text("not-valid-json{", encoding="utf-8")
    ns = build_parser().parse_args(["list"])
    rc = cmd_list(ns)
    assert rc == 1
    assert "store corrupted" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# cmd_submit — FR-03 single-line --json output (covers lines 113-116)
# ---------------------------------------------------------------------------


def test_unit_cmd_submit_corrupt_store(monkeypatch, tmp_path, capsys):
    """[FR-03] submit against corrupt store → exit 1 + stderr 'store corrupted'."""
    home = _seed_home(monkeypatch, tmp_path)
    (home / "tasks.json").write_text("not-valid-json{", encoding="utf-8")
    ns = build_parser().parse_args(["submit", "echo hi"])
    rc = cmd_submit(ns)
    assert rc == 1
    assert "store corrupted" in capsys.readouterr().err
    # Original bytes survive — no silent rebuild.
    assert "not-valid-json" in (home / "tasks.json").read_text(encoding="utf-8")


def test_unit_cmd_submit_json_single_line(monkeypatch, tmp_path, capsys):
    """[FR-03] --json submit emits single-line JSON, no trailing newline."""
    home = _seed_home(monkeypatch, tmp_path)
    ns = build_parser().parse_args(["submit", "--json", "echo hi"])
    rc = cmd_submit(ns)
    assert rc == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 0, f"submit --json must be single-line, got {out!r}"
    rec = json.loads(out)
    assert rec["command"] == "echo hi"
    assert rec["status"] == "pending"


# ---------------------------------------------------------------------------
# main() dispatch — FR-03 routes to status / list / clear (covers lines 320-324)
# ---------------------------------------------------------------------------


def test_unit_main_routes_status(monkeypatch, tmp_path, capsys):
    """[FR-03] main() dispatches `status <id>` to cmd_status."""
    _seed_home(monkeypatch, tmp_path)
    rc = main(["status", "deadbeef"])
    assert rc == 2
    assert "unknown task: deadbeef" in capsys.readouterr().err


def test_unit_main_routes_list(monkeypatch, tmp_path, capsys):
    """[FR-03] main() dispatches `list` to cmd_list."""
    _seed_home(monkeypatch, tmp_path)
    rc = main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert json.loads(out) == []


def test_unit_main_routes_clear(monkeypatch, tmp_path):
    """[FR-03] main() dispatches `clear` to cmd_clear."""
    home = _seed_home(monkeypatch, tmp_path)
    rc = main(["clear"])
    assert rc == 0
    assert (home / "tasks.json").exists()
    assert json.loads((home / "tasks.json").read_text(encoding="utf-8")) == []


# ---------------------------------------------------------------------------
# build_parser — FR-03 subcommands registered (covers status / clear args)
# ---------------------------------------------------------------------------


def test_unit_build_parser_status():
    """[FR-03] build_parser registers `status` subcommand with task_id positional."""
    parser = build_parser()
    ns = parser.parse_args(["status", "deadbeef"])
    assert ns.command_name == "status"
    assert ns.task_id == "deadbeef"


def test_unit_build_parser_list():
    """[FR-03] build_parser registers `list` subcommand."""
    parser = build_parser()
    ns = parser.parse_args(["list"])
    assert ns.command_name == "list"


def test_unit_build_parser_clear():
    """[FR-03] build_parser registers `clear` subcommand."""
    parser = build_parser()
    ns = parser.parse_args(["clear"])
    assert ns.command_name == "clear"


# ---------------------------------------------------------------------------
# Sanity: LIST_COMMAND_PREVIEW_LEN is 50 per SPEC
# ---------------------------------------------------------------------------


def test_unit_list_preview_len_is_50():
    """[FR-03] LIST_COMMAND_PREVIEW_LEN matches SPEC §3 FR-03 line 69 (前 50 字元)."""
    assert LIST_COMMAND_PREVIEW_LEN == 50


def test_unit_generate_task_id_is_8_hex():
    """[FR-01] _generate_task_id returns 8 lowercase hex chars (sanity, shared)."""
    for _ in range(20):
        tid = _generate_task_id()
        assert len(tid) == 8
        assert all(c in "0123456789abcdef" for c in tid)