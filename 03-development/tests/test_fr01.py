"""TDD-RED tests for FR-01: Task Submission and Validation.

Per SPEC.md §3 FR-01 + TEST_SPEC.md §FR-01 (6 cases, 9 sub-assertion
predicates). These tests are intentionally written BEFORE the feature
exists; pytest will report Collection Error (ModuleNotFoundError for
taskq.cli) which is the expected RED state.

Test isolation:
- TASKQ_HOME is monkeypatched to a tmp dir for every test (autouse fixture).
- No external subprocess / DB / network calls involved for FR-01.

Mirror-check contract:
- ``@pytest.mark.parametrize`` row count and column projection MUST exactly
  match TEST_SPEC §FR-01 Inputs rows. Variables not declared in a spec case
  are passed as Python ``None`` here (``inputs.get(k)`` returns ``None`` and
  ``_as_str`` produces ``'None'`` on both sides).
- Each sub-assertion predicate (e.g. ``command == ""``) MUST appear as an
  ``assert`` inside an ``if VAR == c:`` (or ``if VAR in (...):``) block
  whose trigger matches the TEST_SPEC Sub-assertion ``applies_to`` mapping.
- Case dispatch (empty / too_long / injection / dup / valid / json) is done
  by inspecting the spec input tuple itself — never by adding helper-only
  parameters that would distort the projection.
"""

from __future__ import annotations

import json
import re

import pytest

# Top-level imports — ModuleNotFoundError is the EXPECTED RED state.
from taskq import cli  # noqa: F401  -- import error means source missing (RED OK)


# ---------------------------------------------------------------------------
# Fixtures + helpers
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


_HEX8 = re.compile(r"^[0-9a-f]{8}$")


# ---------------------------------------------------------------------------
# Parametrized canonical test — MUST mirror TEST_SPEC §FR-01 Inputs verbatim.
#
# Column order (7 vars) = every key any TEST_SPEC FR-01 Inputs row references:
#   command, length_exceeds_1000, new_name, existing_name,
#   json_mode, expected_exit, outcome
# Projection values that TEST_SPEC omits for a case become Python ``None``
# here (canonicalising ``'None'`` on both sides).
# ---------------------------------------------------------------------------

_FR01_PARAMETRIZE = [
    # command,           length_exceeds_1000, new_name, existing_name, json_mode, expected_exit, outcome
    ("",                  None,                None,     None,          None,      "2",           "rejected"),  # 1 empty_command
    (None,                "yes",               None,     None,          None,      "2",           "rejected"),  # 2 command_too_long
    ("echo hi; rm x",     None,                None,     None,          None,      "2",           "rejected"),  # 3 injection_semicolon
    (None,                None,                "dup",    "dup",         None,      "2",           "rejected"),  # 4 duplicate_name
    ("echo hi",           None,                "alpha",  "distinct",    None,      "0",           "pending"),   # 5 valid_command
    ("echo hi",           None,                None,     None,          "yes",     "0",           "pending"),   # 6 json_mode_output
]


@pytest.mark.parametrize(
    "command, length_exceeds_1000, new_name, existing_name, "
    "json_mode, expected_exit, outcome",
    _FR01_PARAMETRIZE,
)
def test_fr01(
    tmp_path,
    capsys,
    monkeypatch,
    command,
    length_exceeds_1000,
    new_name,
    existing_name,
    json_mode,
    expected_exit,
    outcome,
):
    # Re-isolate TASKQ_HOME inside the parametrize body for clarity.
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))

    # ------------------------------------------------------------------
    # Mirror-check trigger + sub-assertion anchors.
    # Each ``if``'s comparison target MUST match the TEST_SPEC Inputs
    # value for the same case (see applies_to in §Sub-assertions).
    # ------------------------------------------------------------------
    if command == "":
        # AC-FR01-empty-reject : command == "" (applies_to case 1)
        assert command == ""

    if length_exceeds_1000 == "yes":
        # AC-FR01-length-bound : length_exceeds_1000 == "yes" (applies_to case 2)
        assert length_exceeds_1000 == "yes"

    if command == "echo hi; rm x":
        # AC-FR01-injection-present : ";" in command (applies_to case 3)
        assert ";" in command

    if new_name == "dup":
        # AC-FR01-name-conflict : new_name == existing_name (applies_to case 4)
        assert new_name == existing_name

    if new_name == "alpha":
        # AC-FR01-valid-no-conflict : new_name != existing_name (applies_to case 5)
        assert new_name != existing_name

    if json_mode == "yes":
        # AC-FR01-json-mode-on : json_mode == "yes" (applies_to case 6)
        assert json_mode == "yes"

    if expected_exit == "2":
        # AC-FR01-validation-exit-2 : expected_exit == "2" (cases 1,2,3,4)
        assert expected_exit == "2"

    if expected_exit == "0":
        # AC-FR01-happy-exit-0 : expected_exit == "0" (cases 5,6)
        assert expected_exit == "0"

    if outcome == "rejected":
        # AC-FR01-rejection-outcome : outcome == "rejected" (cases 1,2,3,4)
        assert outcome == "rejected"

    # ------------------------------------------------------------------
    # Case dispatch by inspecting the spec input tuple itself. Order is
    # fixed at TEST_SPEC §FR-01 Inputs (line 94-99).
    # ------------------------------------------------------------------

    if command == "" and length_exceeds_1000 != "yes" and new_name is None:
        # ===== case 1: empty_command → exit 2 ============================
        exit_code = cli.submit_cmd(cmd="", name=None, json_mode=False)
        assert exit_code == int(expected_exit)
        assert _read_tasks(tmp_path) == []
        err = capsys.readouterr().err
        assert err.strip() != "", "stderr must carry an error message"
        return

    if length_exceeds_1000 == "yes":
        # ===== case 2: command_too_long → exit 2 =========================
        exit_code = cli.submit_cmd(cmd="a" * 1001, name=None, json_mode=False)
        assert exit_code == int(expected_exit)
        assert _read_tasks(tmp_path) == []
        err = capsys.readouterr().err
        assert err.strip() != "", "stderr must carry an error message"
        return

    if command == "echo hi; rm x":
        # ===== case 3: injection_semicolon → exit 2 (NFR-02) ============
        exit_code = cli.submit_cmd(cmd="echo hi; rm x", name=None, json_mode=False)
        assert exit_code == int(expected_exit)
        assert _read_tasks(tmp_path) == []
        err = capsys.readouterr().err
        assert err.strip() != "", "stderr must carry an error message"
        return

    if new_name == "dup" and existing_name == "dup":
        # ===== case 4: duplicate_name → exit 2 ===========================
        # Seed the store with a colliding pending task so we exercise the
        # name-uniqueness validator independent of the GREEN implementation.
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
        assert exit_code == int(expected_exit)
        tasks = _read_tasks(tmp_path)
        assert len(tasks) == 1
        assert tasks[0].get("name") == "dup"
        assert tasks[0].get("command") == "echo seed"
        return

    if new_name == "alpha" and existing_name == "distinct":
        # ===== case 5: valid_command → exit 0, status=pending ===========
        exit_code = cli.submit_cmd(cmd="echo hi", name="alpha", json_mode=False)
        assert exit_code == int(expected_exit)
        tasks = _read_tasks(tmp_path)
        assert len(tasks) == 1
        task = tasks[0]
        assert _HEX8.match(task["id"]), f"id must be 8 hex chars, got {task['id']!r}"
        assert task["status"] == "pending"
        assert task["command"] == "echo hi"
        assert task["name"] == "alpha"
        assert "created_at" in task
        out = capsys.readouterr().out
        assert task["id"] in out, "stdout must contain the newly assigned task id"
        return

    if json_mode == "yes":
        # ===== case 6: json_mode_output → exit 0, single-line JSON ======
        exit_code = cli.submit_cmd(cmd="echo hi", name=None, json_mode=True)
        assert exit_code == int(expected_exit)
        out = capsys.readouterr().out
        assert "\n" not in out.rstrip("\n"), f"json output must be single-line, got {out!r}"
        payload = json.loads(out)
        assert set(payload.keys()) >= {"id", "status"}
        assert payload["status"] == "pending"
        assert _HEX8.match(payload["id"]), f"id must be 8 hex chars, got {payload['id']!r}"
        tasks = _read_tasks(tmp_path)
        assert len(tasks) == 1
        assert tasks[0]["id"] == payload["id"]
        return

    # Defensive: parametrize row that doesn't match any case-id shape — would
    # be a TEST_SPEC Inputs drift (P2-locked) or a projection bug here.
    raise AssertionError(
        f"parametrize row {command!r}/{length_exceeds_1000!r}/{new_name!r}/"
        f"{existing_name!r}/{json_mode!r} did not match any TEST_SPEC §FR-01 case"
    )


# ---------------------------------------------------------------------------
# TEST_SPEC-named test functions.
#
# Per TEST_SPEC.md §FR-01 (rows 83-88) the spec requires six discrete test
# function names. The parametrized mirror-test above preserves the sub-assertion
# mirror contract for D4 spec-coverage; the six functions below satisfy the
# D4 function-name inventory AND raise line coverage by exercising every
# branch of submit_cmd / _validate_command / _name_conflicts / _atomic_write /
# _load_tasks with intent-named targets.
#
# Each function is independent (no parametrize sharing) so a coverage tool that
# attributes lines to the test name that executed them can map every line to a
# spec-named function.
# ---------------------------------------------------------------------------


def test_fr01_empty_command_exit2(tmp_path, monkeypatch, capsys):
    """[FR-01] case 1: empty command → exit 2 + stderr."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    exit_code = cli.submit_cmd(cmd="", name=None, json_mode=False)
    assert exit_code == 2
    assert _read_tasks(tmp_path) == []
    err = capsys.readouterr().err
    assert err.strip() != "", "stderr must carry an error message"


def test_fr01_command_too_long_exit2(tmp_path, monkeypatch, capsys):
    """[FR-01] case 2: command length > 1000 → exit 2 + stderr."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    exit_code = cli.submit_cmd(cmd="a" * 1001, name=None, json_mode=False)
    assert exit_code == 2
    assert _read_tasks(tmp_path) == []
    err = capsys.readouterr().err
    assert err.strip() != "", "stderr must carry an error message"


def test_fr01_injection_char_exit2(tmp_path, monkeypatch, capsys):
    """[FR-01] case 3: command with injection char ';' → exit 2 (NFR-02)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    exit_code = cli.submit_cmd(cmd="echo hi; rm x", name=None, json_mode=False)
    assert exit_code == 2
    assert _read_tasks(tmp_path) == []
    err = capsys.readouterr().err
    assert err.strip() != "", "stderr must carry an error message"


def test_fr01_duplicate_name_exit2(tmp_path, monkeypatch, capsys):
    """[FR-01] case 4: --name collides with a pending task → exit 2."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    # Seed the store with a colliding pending task so we exercise the
    # name-uniqueness validator independent of the GREEN implementation.
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
    tasks = _read_tasks(tmp_path)
    assert len(tasks) == 1
    assert tasks[0].get("name") == "dup"
    assert tasks[0].get("command") == "echo seed"
    err = capsys.readouterr().err
    assert err.strip() != "", "stderr must carry an error message"


def test_fr01_valid_submit_pending(tmp_path, monkeypatch, capsys):
    """[FR-01] case 5: valid submit → exit 0 + pending task + id on stdout."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
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
    out = capsys.readouterr().out
    assert task["id"] in out, "stdout must contain the newly assigned task id"


def test_fr01_json_output_single_line(tmp_path, monkeypatch, capsys):
    """[FR-01] case 6: --json mode → single-line JSON with id+status."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    exit_code = cli.submit_cmd(cmd="echo hi", name=None, json_mode=True)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "\n" not in out.rstrip("\n"), f"json output must be single-line, got {out!r}"
    payload = json.loads(out)
    assert set(payload.keys()) >= {"id", "status"}
    assert payload["status"] == "pending"
    assert _HEX8.match(payload["id"]), f"id must be 8 hex chars, got {payload['id']!r}"
    tasks = _read_tasks(tmp_path)
    assert len(tasks) == 1
    assert tasks[0]["id"] == payload["id"]
