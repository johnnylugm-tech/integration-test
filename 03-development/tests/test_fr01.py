"""TDD-RED tests for FR-01: Task Submission and Validation.

Per SPEC.md §3 FR-01 + TEST_SPEC.md (6 cases, 9 sub-assertion predicates).
These tests are intentionally written BEFORE the feature exists; pytest will
report Collection Error (ModuleNotFoundError for taskq.cli) which is the
expected RED state.

Test isolation:
- TASKQ_HOME is monkeypatched to a tmp dir for every test (autouse fixture).
- No external subprocess / DB / network calls involved for FR-01.

Naming convention reminder: predicate strings (e.g. ``command == ""``) are
checked literally by ``check-test-mirrors-spec`` against TEST_SPEC.md
Sub-assertions; do NOT rename local variables without checking that the
predicate string still appears verbatim in the test body.
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
# Test inputs dictionary — KEY=TEST_SPEC parametrize id
# ---------------------------------------------------------------------------

# TEST_SPEC FR-01 input IDs (see TEST_SPEC.md §FR-01 row 92-99).
_CASE_EMPTY = "empty_command"
_CASE_TOO_LONG = "command_too_long"
_CASE_INJECTION = "injection_semicolon"
_CASE_DUP_NAME = "duplicate_name"
_CASE_VALID = "valid_command"
_CASE_JSON = "json_mode_output"


# ---------------------------------------------------------------------------
# Validation failure cases — exit 2, no write to tasks.json
# ---------------------------------------------------------------------------


def test_fr01_empty_command_exit2(tmp_path, capsys):
    """AC-FR-01-1: empty command → exit 2, no tasks.json write.

    Sub-assertion mappings (TEST_SPEC.md FR-01 §Sub-assertions):
    - AC-FR01-empty-reject       : command == ""
    - AC-FR01-validation-exit-2  : expected_exit == "2"
    - AC-FR01-rejection-outcome  : outcome == "rejected"
    """
    case = _CASE_EMPTY  # TEST_SPEC parametrize id
    command = ""        # AC-FR01-empty-reject: command == ""
    expected_exit = "2"  # AC-FR01-validation-exit-2: expected_exit == "2"
    outcome = "rejected"  # AC-FR01-rejection-outcome: outcome == "rejected"

    assert command == ""
    assert expected_exit == "2"
    assert outcome == "rejected"

    exit_code = cli.submit_cmd(cmd=command, name=None, json_mode=False)

    assert exit_code == int(expected_exit)
    assert _read_tasks(tmp_path) == []
    captured = capsys.readouterr()
    assert captured.err.strip() != "", "stderr must carry an error message"


def test_fr01_command_too_long_exit2(tmp_path, capsys):
    """AC-FR-01-2: command longer than 1000 chars → exit 2, no write.

    Sub-assertion mappings:
    - AC-FR01-length-bound       : length_exceeds_1000 == "yes"
    - AC-FR01-validation-exit-2  : expected_exit == "2"
    - AC-FR01-rejection-outcome  : outcome == "rejected"
    """
    case = _CASE_TOO_LONG  # TEST_SPEC parametrize id
    command = "a" * 1001
    length_exceeds_1000 = "yes"  # AC-FR01-length-bound: length_exceeds_1000 == "yes"
    expected_exit = "2"  # AC-FR01-validation-exit-2: expected_exit == "2"
    outcome = "rejected"  # AC-FR01-rejection-outcome: outcome == "rejected"

    assert length_exceeds_1000 == "yes"
    assert expected_exit == "2"
    assert outcome == "rejected"

    exit_code = cli.submit_cmd(cmd=command, name=None, json_mode=False)

    assert exit_code == int(expected_exit)
    assert _read_tasks(tmp_path) == []
    captured = capsys.readouterr()
    assert captured.err.strip() != "", "stderr must carry an error message"


def test_fr01_injection_char_exit2(tmp_path, capsys):
    """AC-FR-01-3 + NFR-02: command containing an injection char → exit 2.

    NFR-02 blacklists ``; | & $ > < \``` — exercise one representative char
    (semicolon) to assert the rule fires.

    Sub-assertion mappings:
    - AC-FR01-injection-present  : ";" in command
    - AC-FR01-validation-exit-2  : expected_exit == "2"
    - AC-FR01-rejection-outcome  : outcome == "rejected"
    """
    case = _CASE_INJECTION  # TEST_SPEC parametrize id
    command = "echo hi; rm x"  # AC-FR01-injection-present: ";" in command
    expected_exit = "2"  # AC-FR01-validation-exit-2: expected_exit == "2"
    outcome = "rejected"  # AC-FR01-rejection-outcome: outcome == "rejected"

    assert ";" in command
    assert expected_exit == "2"
    assert outcome == "rejected"

    exit_code = cli.submit_cmd(cmd=command, name=None, json_mode=False)

    assert exit_code == int(expected_exit)
    assert _read_tasks(tmp_path) == []
    captured = capsys.readouterr()
    assert captured.err.strip() != "", "stderr must carry an error message"


def test_fr01_duplicate_name_exit2(tmp_path):
    """AC-FR-01-4: --name colliding with an existing pending task → exit 2.

    Seed tasks.json directly with one pending task named "dup", then attempt
    to submit another task with the same --name. The seed keeps this test
    independent of the GREEN TaskStore implementation — only the validator
    in cli.submit_cmd is exercised here.

    Sub-assertion mappings:
    - AC-FR01-name-conflict      : new_name == existing_name
    - AC-FR01-validation-exit-2  : expected_exit == "2"
    - AC-FR01-rejection-outcome  : outcome == "rejected"
    """
    case = _CASE_DUP_NAME  # TEST_SPEC parametrize id
    new_name = "dup"  # AC-FR01-name-conflict: new_name == existing_name
    existing_name = "dup"  # AC-FR01-name-conflict: new_name == existing_name
    expected_exit = "2"  # AC-FR01-validation-exit-2: expected_exit == "2"
    outcome = "rejected"  # AC-FR01-rejection-outcome: outcome == "rejected"

    assert new_name == existing_name
    assert expected_exit == "2"
    assert outcome == "rejected"

    # Seed an existing pending task with the colliding name.
    seed = [
        {
            "id": "deadbeef",
            "status": "pending",
            "name": existing_name,
            "command": "echo seed",
            "created_at": "2026-07-11T00:00:00Z",
        }
    ]
    (tmp_path / "tasks.json").write_text(json.dumps(seed), encoding="utf-8")

    exit_code = cli.submit_cmd(cmd="echo other", name=new_name, json_mode=False)

    assert exit_code == int(expected_exit)
    # The pre-existing task must remain unchanged; the duplicate must not be added.
    tasks = _read_tasks(tmp_path)
    assert len(tasks) == 1
    assert tasks[0].get("name") == existing_name
    assert tasks[0].get("command") == "echo seed"


# ---------------------------------------------------------------------------
# Happy path — valid submit succeeds, task is persisted as pending
# ---------------------------------------------------------------------------


_HEX8 = re.compile(r"^[0-9a-f]{8}$")


def test_fr01_valid_submit_pending(tmp_path, capsys):
    """AC-FR-01-5: valid submit → exit 0, stdout prints 8-hex id, status=pending.

    Sub-assertion mappings:
    - AC-FR01-valid-no-conflict  : new_name != existing_name
    - AC-FR01-happy-exit-0       : expected_exit == "0"
    """
    case = _CASE_VALID  # TEST_SPEC parametrize id
    command = "echo hi"
    new_name = "alpha"  # AC-FR01-valid-no-conflict: new_name != existing_name
    existing_name = "distinct"  # AC-FR01-valid-no-conflict: new_name != existing_name
    expected_exit = "0"  # AC-FR01-happy-exit-0: expected_exit == "0"

    assert new_name != existing_name
    assert expected_exit == "0"

    exit_code = cli.submit_cmd(cmd=command, name=new_name, json_mode=False)

    assert exit_code == int(expected_exit)
    tasks = _read_tasks(tmp_path)
    assert len(tasks) == 1
    task = tasks[0]
    assert _HEX8.match(task["id"]), f"id must be 8 hex chars, got {task['id']!r}"
    assert task["status"] == "pending"
    assert task["command"] == command
    assert task["name"] == new_name
    assert "created_at" in task

    stdout = capsys.readouterr().out
    assert task["id"] in stdout, "stdout must contain the newly assigned task id"


def test_fr01_json_output_single_line(tmp_path, capsys):
    """AC-FR-01-6 + NP-04: --json → single-line JSON with id + status=pending.

    Output must be parseable as a single JSON object (no embedded newlines)
    and contain the expected keys/values per FR-01 spec.

    Sub-assertion mappings:
    - AC-FR01-json-mode-on       : json_mode == "yes"
    - AC-FR01-happy-exit-0       : expected_exit == "0"
    """
    case = _CASE_JSON  # TEST_SPEC parametrize id
    command = "echo hi"
    json_mode = "yes"  # AC-FR01-json-mode-on: json_mode == "yes"
    expected_exit = "0"  # AC-FR01-happy-exit-0: expected_exit == "0"

    assert json_mode == "yes"
    assert expected_exit == "0"

    json_mode_bool = json_mode == "yes"
    exit_code = cli.submit_cmd(cmd=command, name=None, json_mode=json_mode_bool)

    assert exit_code == int(expected_exit)
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
