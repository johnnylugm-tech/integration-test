"""TDD-RED tests for FR-01: Task Submission and Validation.

Per SPEC.md §3 FR-01 + TEST_SPEC.md (6 cases). These tests are intentionally
written BEFORE the feature exists; pytest will report Collection Error
(ModuleNotFoundError for taskq.cli) which is the expected RED state.

Test isolation:
- TASKQ_HOME is monkeypatched to a tmp dir for every test (autouse fixture).
- No external subprocess / DB / network calls involved for FR-01.
"""

from __future__ import annotations

import json
import re

import pytest

# Top-level imports — ModuleNotFoundError is the EXPECTED RED state.
from taskq import cli  # noqa: F401  -- import error means source missing (RED OK)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_taskq_home(tmp_path, monkeypatch):
    """Point TASKQ_HOME at a tmp dir so tests don't touch the real .taskq store."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))


def _read_tasks(home) -> list[dict]:
    """Read tasks.json from a TASKQ_HOME dir. Returns [] when the file is absent."""
    path = home / "tasks.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Validation failure cases — all must exit 2 and NOT write to tasks.json
# ---------------------------------------------------------------------------


def test_fr01_empty_command_exit2(tmp_path, capsys):
    """AC-FR-01-1: empty command → exit 2, no tasks.json write."""
    exit_code = cli.submit_cmd(cmd="", name=None, json_mode=False)

    assert exit_code == 2
    assert _read_tasks(tmp_path) == []
    captured = capsys.readouterr()
    assert captured.err.strip() != "", "stderr must carry an error message"


def test_fr01_command_too_long_exit2(tmp_path, capsys):
    """AC-FR-01-2: command longer than 1000 chars → exit 2, no write."""
    long_cmd = "a" * 1001

    exit_code = cli.submit_cmd(cmd=long_cmd, name=None, json_mode=False)

    assert exit_code == 2
    assert _read_tasks(tmp_path) == []
    captured = capsys.readouterr()
    assert captured.err.strip() != "", "stderr must carry an error message"


def test_fr01_injection_char_exit2(tmp_path, capsys):
    """AC-FR-01-3 + NFR-02: command containing an injection char → exit 2.

    NFR-02 blacklists `; | & $ > < \\`` — exercise one representative char
    (semicolon) which is enough to assert the rule fires.
    """
    exit_code = cli.submit_cmd(cmd="echo hi; rm x", name=None, json_mode=False)

    assert exit_code == 2
    assert _read_tasks(tmp_path) == []
    captured = capsys.readouterr()
    assert captured.err.strip() != "", "stderr must carry an error message"


def test_fr01_duplicate_name_exit2(tmp_path):
    """AC-FR-01-4: --name colliding with an existing pending task → exit 2.

    Seed tasks.json directly with one pending task named "dup", then attempt
    to submit another task with the same --name. The seed keeps this test
    independent of the GREEN TaskStore implementation — only the validator
    in cli.submit_cmd is exercised here.
    """
    # Seed an existing pending task with the colliding name.
    seed = [
        {
            "id": "deadbeef",
            "status": "pending",
            "name": "dup",
            "command": "echo seed",
            "created_at": "2026-07-11T00:00:00Z",
        }
    ]
    (tmp_path / "tasks.json").write_text(json.dumps(seed), encoding="utf-8")

    exit_code = cli.submit_cmd(cmd="echo other", name="dup", json_mode=False)

    assert exit_code == 2
    # The pre-existing task must remain unchanged; the duplicate must not be added.
    tasks = _read_tasks(tmp_path)
    assert len(tasks) == 1
    assert tasks[0].get("name") == "dup"
    assert tasks[0].get("command") == "echo seed"


# ---------------------------------------------------------------------------
# Happy path — valid submit succeeds, task is persisted as pending
# ---------------------------------------------------------------------------


_HEX8 = re.compile(r"^[0-9a-f]{8}$")


def test_fr01_valid_submit_pending(tmp_path, capsys):
    """AC-FR-01-5: valid submit → exit 0, stdout prints 8-hex id, status=pending."""
    exit_code = cli.submit_cmd(cmd="echo hi", name="alpha", json_mode=False)

    assert exit_code == 0
    tasks = _read_tasks(tmp_path)
    assert len(tasks) == 1
    task = tasks[0]
    assert _HEX8.match(task["id"]), f"id must be 8 hex chars, got {task['id']!r}"
    assert task["status"] == "pending"
    assert task["command"] == "echo hi"
    assert task["name"] == "alpha"
    assert "created_at" in task

    stdout = capsys.readouterr().out
    assert task["id"] in stdout, "stdout must contain the newly assigned task id"


def test_fr01_json_output_single_line(tmp_path, capsys):
    """AC-FR-01-6 + NP-04: --json → single-line JSON with id + status=pending.

    Output must be parseable as a single JSON object (no embedded newlines)
    and contain the expected keys/values per FR-01 spec.
    """
    exit_code = cli.submit_cmd(cmd="echo hi", name=None, json_mode=True)

    assert exit_code == 0
    out = capsys.readouterr().out
    # Single-line JSON: no literal newline between tokens (strip trailing newline).
    assert "\n" not in out.rstrip("\n"), f"json output must be single-line, got {out!r}"

    payload = json.loads(out)
    assert set(payload.keys()) >= {"id", "status"}
    assert payload["status"] == "pending"
    assert _HEX8.match(payload["id"]), f"id must be 8 hex chars, got {payload['id']!r}"

    # Cross-check: the same id was persisted in tasks.json.
    tasks = _read_tasks(tmp_path)
    assert len(tasks) == 1
    assert tasks[0]["id"] == payload["id"]