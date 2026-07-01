"""FR-01: 任務模型與持久化 (Task Model & Persistence) — failing pytest tests (RED).

This file contains 16 test functions covering FR-01 acceptance criteria
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
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
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
    """Each test gets its own $TASKQ_HOME under tmp_path.

    The GREEN implementation must read $TASKQ_HOME from env (or default to
    ~/.taskq) and place tasks.json inside it. This fixture is purely test-side
    isolation — it does not stub any production code.
    """
    home = tmp_path / ".taskq"
    home.mkdir()
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


# ---------------------------------------------------------------------------
# AC-FR01-01 — Non-empty rejection (exit 2, no write)
# ---------------------------------------------------------------------------

def test_fr01_submit_empty(taskq_home):
    """AC-FR01-01 (non-empty): empty cmd → reject, exit 2, no write to tasks.json."""
    cmd = ""
    assert len(cmd) == 0
    result = submit(cmd)
    assert result.exit_code == 2
    assert not (taskq_home / "tasks.json").exists()


def test_fr01_submit_whitespace(taskq_home):
    """AC-FR01-01 (non-empty): all-whitespace cmd → reject, exit 2, no write."""
    cmd = "   "
    assert cmd.strip() == ""
    result = submit(cmd)
    assert result.exit_code == 2
    assert not (taskq_home / "tasks.json").exists()


# ---------------------------------------------------------------------------
# AC-FR01-02 — Length boundary (1000 chars inclusive accepted, >1000 rejected)
# ---------------------------------------------------------------------------

def test_fr01_submit_length_boundary(taskq_home):
    """AC-FR01-02: cmd of 1000 chars accepted (exit 0), cmd of 1001 chars rejected (exit 2)."""
    cmd_at_limit = "a" * 1000
    cmd_over_limit = "a" * 1001
    # Sub-assertion: the strings are the lengths the boundary demands.
    assert len(cmd_at_limit) == 1000
    assert len(cmd_over_limit) == 1001

    accepted = submit(cmd_at_limit)
    assert accepted.exit_code == 0

    rejected = submit(cmd_over_limit)
    assert rejected.exit_code == 2


# ---------------------------------------------------------------------------
# AC-FR01-03 — Injection character blacklist (one test per blacklisted char)
# ---------------------------------------------------------------------------

def test_fr01_submit_injection_semicolon(taskq_home):
    """AC-FR01-03: ';' in cmd → reject, exit 2."""
    cmd = "echo a;b"
    assert cmd.find(";") != -1
    result = submit(cmd)
    assert result.exit_code == 2


def test_fr01_submit_injection_pipe(taskq_home):
    """AC-FR01-03: '|' in cmd → reject, exit 2."""
    cmd = "echo a|b"
    pipe_char = "|"
    assert cmd.find(pipe_char) != -1
    result = submit(cmd)
    assert result.exit_code == 2


def test_fr01_submit_injection_amp(taskq_home):
    """AC-FR01-03: '&' in cmd → reject, exit 2."""
    cmd = "echo a&b"
    assert cmd.find("&") != -1
    result = submit(cmd)
    assert result.exit_code == 2


def test_fr01_submit_injection_dollar(taskq_home):
    """AC-FR01-03: '$' in cmd → reject, exit 2."""
    cmd = "echo $HOME"
    assert cmd.find("$") != -1
    result = submit(cmd)
    assert result.exit_code == 2


def test_fr01_submit_injection_gt(taskq_home):
    """AC-FR01-03: '>' in cmd → reject, exit 2."""
    cmd = "echo a>b"
    assert cmd.find(">") != -1
    result = submit(cmd)
    assert result.exit_code == 2


def test_fr01_submit_injection_lt(taskq_home):
    """AC-FR01-03: '<' in cmd → reject, exit 2."""
    cmd = "echo a<b"
    assert cmd.find("<") != -1
    result = submit(cmd)
    assert result.exit_code == 2


def test_fr01_submit_injection_backtick(taskq_home):
    """AC-FR01-03: '`' in cmd → reject, exit 2."""
    cmd = "echo `id`"
    assert cmd.find("`") != -1
    result = submit(cmd)
    assert result.exit_code == 2


def test_fr01_blacklist_chars_present(taskq_home):
    """AC-FR01-03 (blacklist shape): the 7-char blacklist is ; | & $ > < ` .

    Sub-assertion locks in the canonical 7-char set; every char must be
    rejected by submit (exit 2) when present in a submitted cmd.
    """
    semicolon = ";"
    pipe_chr = "|"
    amp = "&"
    dollar = "$"
    gt = ">"
    lt = "<"
    btick = "`"
    blacklist = semicolon + pipe_chr + amp + dollar + gt + lt + btick
    assert len(blacklist) == 7
    for ch in blacklist:
        result = submit(f"echo safe{ch}trigger")
        assert result.exit_code == 2, f"blacklist char {ch!r} was NOT rejected"


# ---------------------------------------------------------------------------
# AC-FR01-04 + AC-FR01-05 — Id format, pending state, command preserved
# ---------------------------------------------------------------------------

def test_fr01_submit_valid(taskq_home):
    """AC-FR01-04/05: valid cmd → exit 0, id is 8 lowercase hex chars, status='pending'."""
    cmd = "echo hi"
    assert len(cmd) > 0 and cmd.strip() != ""
    result = submit(cmd)
    assert result.exit_code == 0
    assert len(result.id) == 8
    assert all(c in "0123456789abcdef" for c in result.id), (
        f"id {result.id!r} is not 8 lowercase hex chars"
    )
    assert result.status == "pending"
    assert result.command == cmd
    assert result.attempts == 0


def test_fr01_pending_state_record(taskq_home):
    """AC-FR01-05: submitted task is persisted with status=pending + command + created_at."""
    cmd = "sleep 0"
    assert len(cmd) > 0 and cmd.strip() != ""
    result = submit(cmd)
    assert result.status == "pending"
    assert result.command == cmd
    assert result.attempts == 0
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
# ---------------------------------------------------------------------------

def test_fr01_atomic_write(taskq_home):
    """AC-FR01-06: tasks.json is written atomically; content is valid JSON.

    Crash-safety is the cross-cut exercised by NFR-03 case 32. Here we verify
    the happy-path write is well-formed (no partial-write garbage) and that
    the persisted payload round-trips through the file.
    """
    cmd = "echo hi"
    result = submit(cmd)
    tasks_file = taskq_home / "tasks.json"
    assert tasks_file.exists(), "tasks.json must exist after a successful submit"
    payload = json.loads(tasks_file.read_text())
    assert "tasks" in payload
    assert len(payload["tasks"]) == 1
    assert payload["tasks"][0]["id"] == result.id


# ---------------------------------------------------------------------------
# AC-FR01-07 — Corruption detection (exit 1 + stderr "store corrupted")
# ---------------------------------------------------------------------------

def test_fr01_corrupt_store_exit1(taskq_home):
    """AC-FR01-07: tasks.json containing invalid JSON → startup detection → exit 1, stderr 'store corrupted'.

    Exercised via subprocess so the real exit-code + stderr contract is
    observed end-to-end (CLI must NOT silently rebuild the store).
    """
    tasks_file = taskq_home / "tasks.json"
    tasks_file.write_text("not-valid-json")

    # Subprocess needs the taskq package on PYTHONPATH (configured in
    # setup.cfg as pythonpath = 03-development/src).
    project_root = Path(__file__).resolve().parent.parent
    src_path = project_root / "03-development" / "src"
    env = os.environ.copy()
    env["TASKQ_HOME"] = str(taskq_home)
    env["PYTHONPATH"] = str(src_path) + os.pathsep + env.get("PYTHONPATH", "")

    # A read-only subcommand (status) triggers startup-time load and surfaces
    # the corruption detection before any business logic runs.
    proc = subprocess.run(
        [sys.executable, "-m", "taskq", "status", "deadbeef"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "store corrupted" in proc.stderr, (
        f"expected 'store corrupted' in stderr, got: {proc.stderr!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR01-08 — Validation violation writes nothing to storage
# ---------------------------------------------------------------------------

def test_fr01_no_write_on_reject(taskq_home):
    """AC-FR01-08: any validation rule violation writes NOTHING to tasks.json."""
    cmd = "bad;cmd"  # contains ';' → rejected by AC-FR01-03
    result = submit(cmd)
    assert result.exit_code == 2
    tasks_file = taskq_home / "tasks.json"
    assert not tasks_file.exists(), (
        "tasks.json must not be created when submit is rejected"
    )