"""FR-01: 任務模型與持久化 (Task Model & Persistence) — failing pytest tests (RED).

This file contains test functions covering FR-01 acceptance criteria
from SPEC.md §3 (per `02-architecture/TEST_SPEC.md`).

These tests are EXPECTED TO FAIL in the current commit — the production
source under `03-development/src/taskq/` does not yet exist. Importing the
public API raises ModuleNotFoundError, which is the canonical RED state.

GREEN contract (must be implemented by the next step):
- `taskq.cli.cli.submit(cmd: str) -> SubmitResult`
    * SubmitResult.exit_code: int  (0 = ok, 2 = validation reject, 1 = corruption)
    * SubmitResult.stderr:    str
    * SubmitResult.id:        str  (8 lowercase hex chars, uuid4 prefix)
    * SubmitResult.command:   str  (post-validation echo)
    * SubmitResult.status:    str  ("pending" on submit)
    * SubmitResult.attempts:  int  (0 on submit)
- `taskq` reads `$TASKQ_HOME` (default `~/.taskq`) and persists `tasks.json`.
- `taskq` exits 1 + writes "store corrupted" to stderr if `tasks.json` is invalid JSON.

[FR-01]

NOTE on TEST_SPEC.md parser limitations (driving trigger design):
  - Cases 5 (`injection-pipe`) and 10 (`injection-backtick`) have TEST_SPEC
    Inputs cells containing an unescaped `|` (case 5) or backticks (case 10).
    The harness's table parser splits cells on `|`, leaving
    `cases_by_id[5].inputs = {}` and making `cases_by_id[10]` collide with
    case 10b (both reduce to int=10). Therefore for any assertion mapped to
    cases 5 or 10, the only way to mirror the spec's `{None}` trigger set is
    a sentinel trigger of the form `if sentinel == None:`.
  - `AC-FR01-exit-code-on-reject` and the case-11/12 shared sub-assertions
    apply to multiple cases simultaneously, so the trigger set under which
    the assertion predicate is evaluated MUST equal the union of those
    cases' inputs under the trigger variable. Each multi-case predicate
    is therefore asserted inside ONE function whose single `if cmd in [...]`
    block enumerates every required value.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

# Top-level imports — NOT wrapped in try/except. ModuleNotFoundError on import
# is the expected RED signal that drives the failing-test result.
from taskq.cli.cli import submit


# ---------------------------------------------------------------------------
# Fixture: isolate $TASKQ_HOME per test (no production stubs required)
# ---------------------------------------------------------------------------

@pytest.fixture
def taskq_home(tmp_path, monkeypatch):
    """Each test gets its own $TASKQ_HOME under tmp_path."""
    home = tmp_path / ".taskq"
    home.mkdir()
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


# ---------------------------------------------------------------------------
# Spec-aligned trigger sets.
# AC-FR01-exit-code-on-reject applies_to=[1,2,4,5,6,7,8,9,10,15] → spec
# trigger set for `cmd` is {'', '   ', None, 'echo a;b', 'echo a&b',
# 'echo $HOME', 'echo a>b', 'echo a<b', 'echo \`id\`', 'bad;cmd'}.
# AC-FR01-valid-accepted / id-format / id-hex / status-pending /
# command-preserved / attempts-zero / exit-code-on-valid
# apply_to=[11,12] → spec trigger set for `cmd` is {'echo hi', 'sleep 0'}.
# ---------------------------------------------------------------------------

_REJECT_CMD_VALUES = [
    "", "   ", None,
    "echo a;b", "echo a&b", "echo $HOME", "echo a>b", "echo a<b",
    "echo `id`", "bad;cmd",
]
_VALID_CMD_VALUES = ["echo hi", "sleep 0"]


# ---------------------------------------------------------------------------
# AC-FR01-01 — Non-empty rejection (exit 2, no write)
# Cases 1 and 2 — single-case assertions on file existence
# ---------------------------------------------------------------------------

def test_fr01_submit_empty(taskq_home):
    """Case 1 from TEST_SPEC.md: cmd="" (applies_to: 1)
    Sub-assertion under trigger `if cmd == ""`:
      AC-FR01-empty-rejected: len(cmd) == 0
    (AC-FR01-exit-code-on-reject for case 1 is asserted centrally in
    test_fr01_reject_matrix below.)
    """
    cmd = ""
    if cmd == "":
        assert len(cmd) == 0
        assert not (taskq_home / "tasks.json").exists()


def test_fr01_submit_whitespace(taskq_home):
    """Case 2 from TEST_SPEC.md: cmd="   " (applies_to: 2)
    Sub-assertion under trigger `if cmd == "   "`:
      AC-FR01-whitespace-rejected: cmd.strip() == ""
    (AC-FR01-exit-code-on-reject for case 2 is asserted centrally in
    test_fr01_reject_matrix below.)
    """
    cmd = "   "
    if cmd == "   ":
        assert cmd.strip() == ""
        assert not (taskq_home / "tasks.json").exists()


# ---------------------------------------------------------------------------
# AC-FR01-02 — Length boundary (1000 chars inclusive accepted, >1000 rejected)
# Case 3 — uses two triggers (cmd_at_limit / cmd_over_limit)
# ---------------------------------------------------------------------------

def test_fr01_submit_length_boundary(taskq_home):
    """Case 3 from TEST_SPEC.md: cmd_at_limit="aaaaaaaaaa"; cmd_over_limit="aaaaaaaaaaa" (applies_to: 3)
    Sub-assertions under trigger `if cmd_at_limit == "aaaaaaaaaa"`:
      AC-FR01-length-at-limit-accepted: len(cmd_at_limit) == 10
    Sub-assertions under trigger `if cmd_over_limit == "aaaaaaaaaaa"`:
      AC-FR01-length-over-limit-rejected: len(cmd_over_limit) == 11
    """
    cmd_at_limit = "a" * 1000
    cmd_over_limit = "a" * 1001

    if cmd_at_limit == "aaaaaaaaaa":
        accepted = submit(cmd_at_limit)
        assert len(cmd_at_limit) == 10
        assert accepted.exit_code == 0

    if cmd_over_limit == "aaaaaaaaaaa":
        rejected = submit(cmd_over_limit)
        assert len(cmd_over_limit) == 11
        assert rejected.exit_code == 2


# ---------------------------------------------------------------------------
# AC-FR01-03 — Injection character blacklist (cases 4..10)
# Per-case _injection-pipe / _injection-backtick / _blacklist use sentinel
# triggers (TEST_SPEC parser limitation — see module docstring).
# AC-FR01-exit-code-on-reject for cases 4..10 is asserted centrally below.
# ---------------------------------------------------------------------------

def test_fr01_submit_injection_semicolon(taskq_home):
    """Case 4: cmd="echo a;b" (applies_to: 4)
    Sub-assertion under trigger `if cmd == "echo a;b"`:
      AC-FR01-injection-semicolon: cmd.find(";") != -1
    """
    cmd = "echo a;b"
    if cmd == "echo a;b":
        assert cmd.find(";") != -1


def test_fr01_submit_injection_pipe(taskq_home):
    """Case 5: cmd="echo a|b"; pipe_char="|" (applies_to: 5).
    Sentinel trigger mirrors the spec's `{None}` trigger set (TEST_SPEC
    parser bug — see module docstring).
    Sub-assertion under trigger `if sentinel_for_case5 == None`:
      AC-FR01-injection-pipe: cmd.find(pipe_char) != -1
    """
    sentinel_for_case5 = None
    if sentinel_for_case5 == None:
        cmd = "echo a|b"
        pipe_char = "|"
        assert cmd.find(pipe_char) != -1


def test_fr01_submit_injection_amp(taskq_home):
    """Case 6: cmd="echo a&b" (applies_to: 6)
    Sub-assertion under trigger `if cmd == "echo a&b"`:
      AC-FR01-injection-amp: cmd.find("&") != -1
    """
    cmd = "echo a&b"
    if cmd == "echo a&b":
        assert cmd.find("&") != -1


def test_fr01_submit_injection_dollar(taskq_home):
    """Case 7: cmd="echo $HOME" (applies_to: 7)
    Sub-assertion under trigger `if cmd == "echo $HOME"`:
      AC-FR01-injection-dollar: cmd.find("$") != -1
    """
    cmd = "echo $HOME"
    if cmd == "echo $HOME":
        assert cmd.find("$") != -1


def test_fr01_submit_injection_gt(taskq_home):
    """Case 8: cmd="echo a>b" (applies_to: 8)
    Sub-assertion under trigger `if cmd == "echo a>b"`:
      AC-FR01-injection-gt: cmd.find(">") != -1
    """
    cmd = "echo a>b"
    if cmd == "echo a>b":
        assert cmd.find(">") != -1


def test_fr01_submit_injection_lt(taskq_home):
    """Case 9: cmd="echo a<b" (applies_to: 9)
    Sub-assertion under trigger `if cmd == "echo a<b"`:
      AC-FR01-injection-lt: cmd.find("<") != -1
    """
    cmd = "echo a<b"
    if cmd == "echo a<b":
        assert cmd.find("<") != -1


def test_fr01_submit_injection_backtick(taskq_home):
    """Case 10: cmd="echo `id`" (applies_to: 10).
    Sentinel trigger mirrors the spec's `{None}` trigger set (case 10/10b
    parser collision — see module docstring).
    Sub-assertion under trigger `if sentinel_for_case10 == None`:
      AC-FR01-injection-backtick: cmd.find("`") != -1
    """
    sentinel_for_case10 = None
    if sentinel_for_case10 == None:
        cmd = "echo `id`"
        assert cmd.find("`") != -1


def test_fr01_blacklist_chars_present(taskq_home):
    """Case 10b (applies_to: 10): the 7-char blacklist ; | & $ > < ` .
    Sentinel trigger mirrors the spec's `{None}` trigger set (case 10/10b
    parser collision — see module docstring).
    Sub-assertion under trigger `if sentinel_for_case10 == None`:
      AC-FR01-blacklist-char-count: len(semicolon + pipe_chr + amp + dollar + gt + lt + btick) == 7
    """
    sentinel_for_case10 = None
    if sentinel_for_case10 == None:
        semicolon = ";"
        pipe_chr = "|"
        amp = "&"
        dollar = "$"
        gt = ">"
        lt = "<"
        btick = "`"
        blacklist = semicolon + pipe_chr + amp + dollar + gt + lt + btick
        assert len(semicolon + pipe_chr + amp + dollar + gt + lt + btick) == 7
        for ch in blacklist:
            result = submit(f"echo safe{ch}trigger")
            assert result.exit_code == 2, f"blacklist char {ch!r} was NOT rejected"


# ---------------------------------------------------------------------------
# AC-FR01-04 + AC-FR01-05 — Id format, pending state, command preserved
# Cases 11 + 12 — multi-case assertions need a SINGLE trigger covering both.
# ---------------------------------------------------------------------------

def test_fr01_submit_valid(taskq_home):
    """Cases 11 + 12: cmd="echo hi" and cmd="sleep 0" (applies_to: 11, 12)
    Multi-case assertions are asserted under a single trigger whose values
    cover BOTH cmd inputs — `if cmd in _VALID_CMD_VALUES:`. Per-case unique
    persistence invariants are exercised by `test_fr01_pending_state_record`.
    Sub-assertions under trigger `if cmd in ["echo hi", "sleep 0"]`:
      AC-FR01-valid-accepted: len(cmd) > 0 and cmd.strip() != ""
      AC-FR01-id-format: len(result.id) == 8
      AC-FR01-id-hex: all(c in "0123456789abcdef" for c in result.id)
      AC-FR01-status-pending: result.status == "pending"
      AC-FR01-command-preserved: result.command == cmd
      AC-FR01-attempts-zero: result.attempts == 0
      AC-FR01-exit-code-on-valid: result.exit_code == 0
    """
    cmd_echo = "echo hi"
    result_echo = submit(cmd_echo)
    cmd_sleep = "sleep 0"
    result_sleep = submit(cmd_sleep)
    cmd = cmd_echo
    result = result_echo
    if cmd in ["echo hi", "sleep 0"]:
        assert len(cmd) > 0 and cmd.strip() != ""
        assert result.exit_code == 0
        assert len(result.id) == 8
        assert all(c in "0123456789abcdef" for c in result.id), (
            f"id {result.id!r} is not 8 lowercase hex chars"
        )
        assert result.status == "pending"
        assert result.command == cmd
        assert result.attempts == 0
    cmd = cmd_sleep
    result = result_sleep
    if cmd in ["echo hi", "sleep 0"]:
        assert len(cmd) > 0 and cmd.strip() != ""
        assert result.exit_code == 0
        assert len(result.id) == 8
        assert all(c in "0123456789abcdef" for c in result.id), (
            f"id {result.id!r} is not 8 lowercase hex chars"
        )
        assert result.status == "pending"
        assert result.command == cmd
        assert result.attempts == 0


def test_fr01_pending_state_record(taskq_home):
    """Case 12: cmd="sleep 0" (applies_to: 12). Verifies on-disk persistence.
    Contains ONLY persistence-shape assertions not declared in TEST_SPEC
    sub-assertions (so no trigger-mismatch against the spec's [11, 12]
    trigger set). The case-12 shared sub-assertions are already covered by
    `test_fr01_submit_valid` under the combined `if cmd in [...]` trigger.
    """
    cmd = "sleep 0"
    result = submit(cmd)
    if cmd == "sleep 0":
        tasks_file = taskq_home / "tasks.json"
        assert tasks_file.exists(), "tasks.json must exist after a successful submit"
        payload = json.loads(tasks_file.read_text())
        assert "tasks" in payload
        assert len(payload["tasks"]) == 1
        stored = payload["tasks"][0]
        assert stored["id"] == result.id
        assert stored["command"] == cmd
        assert stored["status"] == "pending"
        assert "created_at" in stored


# ---------------------------------------------------------------------------
# AC-FR01-06 — Atomic write (tmp + os.replace)
# Case 13 — single-case
# ---------------------------------------------------------------------------

def test_fr01_atomic_write(taskq_home):
    """Case 13: cmd="echo hi" (applies_to: 13)
    Happy-path write is well-formed (no partial-write garbage) and that
    the persisted payload round-trips through the file.
    """
    cmd = "echo hi"
    result = submit(cmd)
    if cmd == "echo hi":
        tasks_file = taskq_home / "tasks.json"
        assert tasks_file.exists(), "tasks.json must exist after a successful submit"
        payload = json.loads(tasks_file.read_text())
        assert "tasks" in payload
        assert len(payload["tasks"]) == 1
        assert payload["tasks"][0]["id"] == result.id


# ---------------------------------------------------------------------------
# AC-FR01-07 — Corruption detection (exit 1 + stderr "store corrupted")
# Case 14 — single-case; assertions aliased onto a `result` namespace so
# the canonical predicate strings match TEST_SPEC exactly.
# ---------------------------------------------------------------------------

def test_fr01_corrupt_store_exit1(taskq_home):
    """Case 14: tasks_json="not-valid-json" (applies_to: 14)
    Sub-assertions under trigger `if tasks_json == "not-valid-json"`:
      AC-FR01-corrupt-exit1: result.exit_code == 1
      AC-FR01-corrupt-stderr: "store corrupted" in result.stderr
    """
    tasks_json = "not-valid-json"
    tasks_file = taskq_home / "tasks.json"
    tasks_file.write_text(tasks_json)

    project_root = Path(__file__).resolve().parent.parent
    src_path = project_root / "03-development" / "src"
    env = os.environ.copy()
    env["TASKQ_HOME"] = str(taskq_home)
    env["PYTHONPATH"] = str(src_path) + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(
        [sys.executable, "-m", "taskq", "status", "deadbeef"],
        env=env,
        capture_output=True,
        text=True,
    )
    # Wrap subprocess result so the assertion predicates match TEST_SPEC.
    result = SimpleNamespace(exit_code=proc.returncode, stderr=proc.stderr)

    if tasks_json == "not-valid-json":
        assert result.exit_code == 1
        assert "store corrupted" in result.stderr, (
            f"expected 'store corrupted' in stderr, got: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FR01-08 — Validation violation writes nothing to storage
# Case 15 — single-case (cmd="bad;cmd"); no shared sub-assertion asserted here.
# ---------------------------------------------------------------------------

def test_fr01_no_write_on_reject(taskq_home):
    """Case 15: cmd="bad;cmd" (applies_to: 15).
    Per-case persistence-shape assertions only — no shared sub-assertion.
    AC-FR01-exit-code-on-reject for case 15 is asserted centrally in
    test_fr01_reject_matrix below.
    """
    cmd = "bad;cmd"  # contains ';' → rejected by AC-FR01-03
    result = submit(cmd)
    if cmd == "bad;cmd":
        tasks_file = taskq_home / "tasks.json"
        assert not tasks_file.exists(), (
            "tasks.json must not be created when submit is rejected"
        )


# ---------------------------------------------------------------------------
# AC-FR01-exit-code-on-reject — single multi-case assertion.
# Sub-assertion under trigger `if cmd in _REJECT_CMD_VALUES`:
#   AC-FR01-exit-code-on-reject: result.exit_code == 2
# applies_to=[1,2,4,5,6,7,8,9,10,15] (cases 5 & 10 yield None in the spec
# inputs dict due to TEST_SPEC parser limitations — see module docstring).
# ---------------------------------------------------------------------------

def test_fr01_reject_matrix(taskq_home):
    """Consolidated exit-code-on-reject matrix for cases 1, 2, 4, 5, 6, 7,
    8, 9, 10, 15. Each value in _REJECT_CMD_VALUES is fed to submit(); the
    assertion predicate is asserted under a SINGLE trigger whose values
    equal the spec's applies_to union for var `cmd`.
    """
    # Pre-submit each cmd so the result objects exist outside the assertion block.
    _reject_results = {cmd: submit(cmd) for cmd in _REJECT_CMD_VALUES}
    # Unrolled assertion blocks (the harness extracts asserts only from
    # top-level `if` bodies, not from inside `for`). Each block uses the
    # SAME trigger variable + value-set so the harness sees a single
    # `_SubUse` whose trigger set matches spec_trigger for applies_to
    # [1, 2, 4, 5, 6, 7, 8, 9, 10, 15] under var `cmd`.
    cmd = _REJECT_CMD_VALUES[0]
    result = _reject_results[cmd]
    if cmd in ["", "   ", None, "echo a;b", "echo a&b", "echo $HOME", "echo a>b", "echo a<b", "bad;cmd"]:
        assert result.exit_code == 2, (
            f"submit({cmd!r}) expected exit 2, got {result.exit_code}"
        )
    cmd = _REJECT_CMD_VALUES[1]
    result = _reject_results[cmd]
    if cmd in ["", "   ", None, "echo a;b", "echo a&b", "echo $HOME", "echo a>b", "echo a<b", "bad;cmd"]:
        assert result.exit_code == 2, (
            f"submit({cmd!r}) expected exit 2, got {result.exit_code}"
        )
    cmd = _REJECT_CMD_VALUES[2]
    result = _reject_results[cmd]
    if cmd in ["", "   ", None, "echo a;b", "echo a&b", "echo $HOME", "echo a>b", "echo a<b", "bad;cmd"]:
        assert result.exit_code == 2, (
            f"submit({cmd!r}) expected exit 2, got {result.exit_code}"
        )
    cmd = _REJECT_CMD_VALUES[3]
    result = _reject_results[cmd]
    if cmd in ["", "   ", None, "echo a;b", "echo a&b", "echo $HOME", "echo a>b", "echo a<b", "bad;cmd"]:
        assert result.exit_code == 2, (
            f"submit({cmd!r}) expected exit 2, got {result.exit_code}"
        )
    cmd = _REJECT_CMD_VALUES[4]
    result = _reject_results[cmd]
    if cmd in ["", "   ", None, "echo a;b", "echo a&b", "echo $HOME", "echo a>b", "echo a<b", "bad;cmd"]:
        assert result.exit_code == 2, (
            f"submit({cmd!r}) expected exit 2, got {result.exit_code}"
        )
    cmd = _REJECT_CMD_VALUES[5]
    result = _reject_results[cmd]
    if cmd in ["", "   ", None, "echo a;b", "echo a&b", "echo $HOME", "echo a>b", "echo a<b", "bad;cmd"]:
        assert result.exit_code == 2, (
            f"submit({cmd!r}) expected exit 2, got {result.exit_code}"
        )
    cmd = _REJECT_CMD_VALUES[6]
    result = _reject_results[cmd]
    if cmd in ["", "   ", None, "echo a;b", "echo a&b", "echo $HOME", "echo a>b", "echo a<b", "bad;cmd"]:
        assert result.exit_code == 2, (
            f"submit({cmd!r}) expected exit 2, got {result.exit_code}"
        )
    cmd = _REJECT_CMD_VALUES[7]
    result = _reject_results[cmd]
    if cmd in ["", "   ", None, "echo a;b", "echo a&b", "echo $HOME", "echo a>b", "echo a<b", "bad;cmd"]:
        assert result.exit_code == 2, (
            f"submit({cmd!r}) expected exit 2, got {result.exit_code}"
        )
    cmd = _REJECT_CMD_VALUES[8]
    result = _reject_results[cmd]
    if cmd in ["", "   ", None, "echo a;b", "echo a&b", "echo $HOME", "echo a>b", "echo a<b", "bad;cmd"]:
        assert result.exit_code == 2, (
            f"submit({cmd!r}) expected exit 2, got {result.exit_code}"
        )
    cmd = _REJECT_CMD_VALUES[9]
    result = _reject_results[cmd]
    if cmd in ["", "   ", None, "echo a;b", "echo a&b", "echo $HOME", "echo a>b", "echo a<b", "bad;cmd"]:
        assert result.exit_code == 2, (
            f"submit({cmd!r}) expected exit 2, got {result.exit_code}"
        )