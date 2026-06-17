"""Targeted tests to kill surviving mutmut mutants.

These tests probe specific contracts that the default test surface does
not assert strongly enough on. Each test is designed to fail if a
particular mutation is applied to the production code.

Mutants being killed (selected from .mutmut-cache bad_survived):
  - cli.py:44       prog="taskq"  → verify help output mentions prog
  - cli.py:80       ensure_ascii=False in _emit  → unicode in --json output
  - cli.py:138      task.command[:50]  → exact 50-char truncation in list
  - cli.py:140      {"id": tid, **task.to_dict()}  → list --json has id field
  - persistence.py:60  json.dump(...ensure_ascii=False)  → unicode in tasks.json
  - persistence.py:106 for _ in range(16):  → retry counter
  - persistence.py:54  mkdir(parents=True, exist_ok=True)  → parent dir
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from taskq.cli import main as cli_main
from taskq.config import load_config
from taskq.store import persistence as persistence_mod
from taskq.store import submit_task


@pytest.fixture
def taskq_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect TASKQ_HOME to an isolated tmp directory for each test."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "10.0")
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "2")
    return tmp_path


# ---------------------------------------------------------------------------
# cli.py mutants
# ---------------------------------------------------------------------------


def test_kill_argparse_prog_is_taskq(taskq_home: Path, capsys) -> None:
    """cli.py:44  parser = argparse.ArgumentParser(prog="taskq")

    Mutation candidates: remove prog kwarg, change "taskq" → "" or other.
    Verify: when no args given, help/usage line begins with "usage: taskq".
    """
    rc = cli_main([])
    assert rc == 2  # no args → validation exit
    err = capsys.readouterr().err
    # argparse always emits "usage: PROG" line; prog default is "cli.py" without the kwarg.
    assert "usage: taskq" in err, f"prog should be 'taskq' in help, got: {err!r}"


def test_kill_emit_ensure_ascii_false_in_json_mode(taskq_home: Path, capsys) -> None:
    """cli.py:80  print(json.dumps(payload, ensure_ascii=False))

    Mutation: ensure_ascii=False → True would escape unicode to \\uXXXX.
    Submit a command containing a non-ASCII character, then --json list,
    and verify the output contains the LITERAL unicode character (not escaped).
    """
    # Use a CJK char — would definitely be escaped by ensure_ascii=True
    submit_task("echo 中文測試")
    rc = cli_main(["--json", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out.strip())
    # Find our task
    matching = [t for t in parsed if "中文測試" in t.get("command", "")]
    assert matching, f"task with 中文測試 not found in: {parsed!r}"
    # Literal unicode must appear in the raw output (not \\u escape)
    assert "中文測試" in out, f"unicode should be literal in output, got: {out!r}"
    assert "\\u" not in out, f"unicode should NOT be escaped in ensure_ascii=False mode: {out!r}"


def test_kill_list_truncation_exactly_50_chars(taskq_home: Path, capsys) -> None:
    """cli.py:138  task.command[:50]

    Mutation: [:50] → [:49] would produce 49-char truncation,
    [:51] would produce 51-char truncation. Verify EXACT 50 chars.
    """
    long_cmd = "x" * 200
    submit_task(long_cmd)
    rc = cli_main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    # Find the row containing our task
    for line in out.splitlines():
        if "x" * 50 in line and line.endswith("x" * 50):
            parts = line.split("\t")
            assert len(parts) >= 3
            command_col = parts[-1]
            assert len(command_col) == 50, (
                f"expected exact 50-char truncation, got {len(command_col)}: {command_col!r}"
            )
            return
    pytest.fail(f"no row found with 50-char 'x' prefix in: {out!r}")


def test_kill_list_json_id_field_merged_from_task(taskq_home: Path, capsys) -> None:
    """cli.py:140  {"id": tid, **task.to_dict()}

    Mutation: remove the "id" key, or change dict merge order.
    Verify: --json list output has 'id' key matching the actual task id.
    """
    submit_task("echo idmerge")
    rc = cli_main(["--json", "list"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    target = [t for t in parsed if t.get("command") == "echo idmerge"]
    assert len(target) == 1, f"expected exactly 1 task, got: {parsed!r}"
    record = target[0]
    # Must have 'id' field from merge
    assert "id" in record, f"record missing 'id' key: {record!r}"
    assert record["id"], f"id should be non-empty: {record!r}"
    assert re.fullmatch(r"[0-9a-f]{8}", record["id"]), (
        f"id should be 8-char hex, got: {record['id']!r}"
    )
    # Must also have task fields
    assert record.get("status") == "pending"


# ---------------------------------------------------------------------------
# persistence.py mutants
# ---------------------------------------------------------------------------


def test_kill_atomic_write_ensure_ascii_false(taskq_home: Path) -> None:
    """persistence.py:60  json.dump(data, f, ensure_ascii=False)

    Mutation: ensure_ascii=False → True would escape unicode in tasks.json.
    Submit unicode command, then read the raw tasks.json file and verify
    the unicode is stored as literal (not escaped).
    """
    submit_task("echo 保存中文")
    cfg = load_config()
    tasks_file = cfg.home / "tasks.json"
    raw = tasks_file.read_text(encoding="utf-8")
    # Literal unicode must appear in the file
    assert "保存中文" in raw, f"unicode should be stored literal in tasks.json, got: {raw!r}"
    assert "\\u" not in raw, f"unicode should NOT be escaped in tasks.json: {raw!r}"


def test_kill_submit_retry_loop_runs_16_times(taskq_home: Path, monkeypatch) -> None:
    """persistence.py:106  for _ in range(16):

    Mutation: range(16) → range(15) would retry 15 times.
    Strategy: mock generate_task_id to return 15 duplicates + 1 unique.
    range(15) → all 15 are dups → RuntimeError raised.
    range(16) → 16th is unique → success, returns the unique id.
    """
    collision_value = "deadbeef"
    unique_value = "cafef00d"
    # Pre-populate store with collision_value so the first generate_task_id()
    # call returns a duplicate (the for loop's `if tid not in raw: break`).
    cfg = load_config()
    cfg.home.mkdir(parents=True, exist_ok=True)
    persistence_mod._atomic_write({collision_value: {"command": "x", "status": "pending"}})

    call_count = {"n": 0}

    def fake_generate_id() -> str:
        call_count["n"] += 1
        if call_count["n"] <= 15:
            return collision_value  # collision → loop continues
        return unique_value  # 16th call → break

    monkeypatch.setattr(persistence_mod, "generate_task_id", fake_generate_id)

    # submit a new command
    new_id = submit_task("echo retrytest")
    assert new_id == unique_value, (
        f"loop should have iterated 16 times to find unique id, "
        f"got {new_id!r} (call count={call_count['n']})"
    )
    assert call_count["n"] == 16, f"expected 16 generate_task_id calls, got {call_count['n']}"


def test_kill_atomic_write_creates_parent_directory(taskq_home: Path) -> None:
    """persistence.py:54  path.parent.mkdir(parents=True, exist_ok=True)

    Mutation: parents=True → False, or exist_ok=True → False.
    Strategy: delete the .taskq home, submit_task, and verify it was
    recreated (proving parents=True or exist_ok=True path was taken).
    """
    cfg = load_config()
    # Make the home directory missing before submit
    import shutil
    if cfg.home.exists():
        shutil.rmtree(cfg.home)
    assert not cfg.home.exists()

    # submit must succeed by recreating parent dir
    new_id = submit_task("echo mkdirtest")
    assert new_id, "submit should return non-empty id"
    assert cfg.home.exists(), "home dir should be recreated by mkdir"
    assert (cfg.home / "tasks.json").exists(), "tasks.json should be created"


# ---------------------------------------------------------------------------
# Helper imports
# ---------------------------------------------------------------------------

import re  # noqa: E402
