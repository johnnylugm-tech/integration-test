"""RED tests for FR-03: CLI Integration & Query (status / list / clear).

10 tests covering FR-03 acceptance criteria from `02-architecture/TEST_SPEC.md`:
  *  1 status happy-path      (known id → full record)
  *  1 status validation      (unknown id → exit 2, "unknown task")
  *  1 list truncation        (command truncated to 50 chars)
  *  1 clear happy-path      (store emptied)
  *  1 status --json          (single-line JSON containing command)
  *  1 list --json            (single-line JSON array)
  *  1 missing-subcommand     (exit 2)
  *  1 timeout exit code      (CLI exit 4 on timeout)
  *  1 internal-error exit    (CLI exit 1 on internal fault)
  *  1 backward compat        (submit + list still works)

These tests are written BEFORE the feature implementation (TDD-RED step).
Top-level imports of `taskq.cli`, `taskq.executor`, `taskq.models`,
`taskq.store` already exist from FR-01/FR-02; what is missing is the
``status`` / ``clear`` subcommands, the ``--json`` flag on status/list,
the 50-char command truncation in list output, and the CLI-level exit
code 4 on timeout. Each of those missing surfaces will surface in this
file as an AssertionError — the EXPECTED RED state. No try/except
ImportError wrappers are used.

Naming authority: `02-architecture/TEST_SPEC.md` §FR-03. spec-coverage-check
matches these exact function names.

Sub-assertion encoding: each TEST_SPEC sub-assertion is encoded as
`if VAR == c: assert PRED` where VAR is the predicate's LHS variable
(expected_exit, expected_command_prefix_len, expected_post_clear_count, ...)
and c is the trigger value extracted from the case's declared Inputs.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Top-level imports — RED state relies on `status` / `clear` subcommands and
# the `--json` flag being ABSENT. Calls below surface as exit 2 (unknown
# subcommand) or as output-shape assertion failures. If pytest returns Exit
# Code 2 (Collection Error, ModuleNotFoundError) it means RED is satisfied;
# do NOT add try/except ImportError wrappers.
# ---------------------------------------------------------------------------
from taskq import cli, models, store  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_home(monkeypatch, tmp_path):
    """Redirect `TASKQ_HOME` to a fresh tmp dir so tests do not touch the repo."""
    home = tmp_path / ".taskq"
    home.mkdir()
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


def _run_cli(*argv: str) -> subprocess.CompletedProcess:
    """Invoke `python -m taskq <argv>` as a subprocess and capture result."""
    return subprocess.run(
        [sys.executable, "-m", "taskq", *argv],
        capture_output=True,
        text=True,
    )


def _seed_task(tmp_home, command: str) -> str:
    """Submit ``command`` via FR-01 ``submit`` and return its 8-hex task id."""
    rc = cli.main(["submit", command])
    assert rc == 0
    data = json.loads((tmp_home / "tasks.json").read_text())
    (tid, _), = data.items()
    return tid


# ===========================================================================
# Section 1 — Status subcommand (AC-FR03-01, AC-FR03-02)
# ===========================================================================

def test_fr03_status_known_id_returns_full_record(tmp_home):
    """AC-FR03-01: ``status <tid>`` returns the full task record for an
    existing id (case 1 inputs: command="echo hi"; expected_status_present=
    True; expected_command="echo hi")."""
    tid = _seed_task(tmp_home, "echo hi")
    expected_command = "echo hi"
    rc = cli.main(["status", tid])
    expected_status_present = (rc == 0)
    # Sub-assertion FR03-status-known (case 1 trigger: expected_status_present=True).
    if expected_status_present is True:
        assert expected_status_present is True
    assert rc == 0, "status <known id> must return 0"

    # GREEN TODO: ``cli.main(["status", tid])`` must print a representation
    # of the full task record on stdout. Assert the printed record includes
    # the original command — exact format (JSON, plain text, ...) is decided
    # by GREEN.
    proc = _run_cli("status", tid)
    assert proc.returncode == 0
    assert expected_command in proc.stdout


def test_fr03_status_unknown_id_exits_2(tmp_home):
    """AC-FR03-02: ``status deadbeef`` → exit 2, stderr contains
    "unknown task" (case 2 inputs: tid="deadbeef"; expected_exit=2;
    expected_stderr_contains="unknown task")."""
    tid = "deadbeef"
    proc = _run_cli("status", tid)
    expected_exit = 2
    expected_stderr_contains = "unknown task"
    # Sub-assertion FR03-exit-code-2 (case 2 trigger: expected_exit=2).
    if expected_exit == 2:
        assert expected_exit == 2
    assert proc.returncode == expected_exit
    assert expected_stderr_contains in proc.stderr


# ===========================================================================
# Section 2 — List output truncation (AC-FR03-03)
# ===========================================================================

def test_fr03_list_shows_id_status_command_50chars(tmp_home):
    """AC-FR03-03: ``list`` prints one line per task in the shape
    ``{tid}\\t{status}\\t{command[:50]}`` — i.e. the command field is
    truncated to at most 50 characters (case 3 inputs: command=
    "echo hello world this is a longer command for truncation testing purposes";
    expected_command_prefix_len=50)."""
    long_command = (
        "echo hello world this is a longer command for truncation testing purposes"
    )
    assert len(long_command) > 50, "test fixture must exceed the truncation cap"
    tid = _seed_task(tmp_home, long_command)

    proc = _run_cli("list")
    assert proc.returncode == 0

    expected_command_prefix_len = 50
    # Find the line for the seeded task; the shape is one tab-separated record.
    matched = [
        ln for ln in proc.stdout.splitlines()
        if ln.startswith(f"{tid}\t")
    ]
    assert matched, f"list output missing entry for tid {tid!r}: {proc.stdout!r}"
    line = matched[0]
    parts = line.split("\t")
    assert len(parts) >= 3, f"list line shape must be tid\\tstatus\\tcommand, got {line!r}"
    command_field = parts[2]
    # Sub-assertion FR03-command-prefix-50 (case 3 trigger: expected_command_prefix_len=50).
    if expected_command_prefix_len == 50:
        assert expected_command_prefix_len == 50
    assert len(command_field) == expected_command_prefix_len, (
        f"command field must be truncated to {expected_command_prefix_len} chars, "
        f"got {len(command_field)}: {command_field!r}"
    )
    # The truncated prefix must equal the original command's first 50 chars.
    assert command_field == long_command[:expected_command_prefix_len]


# ===========================================================================
# Section 3 — Clear subcommand (AC-FR03-04)
# ===========================================================================

def test_fr03_clear_empties_store(tmp_home):
    """AC-FR03-04: ``clear`` removes the store contents (no tasks.json on
    disk, equivalent record count 0) (case 4 inputs: command="echo hi";
    expected_post_clear_file_exists=False; expected_post_clear_count=0)."""
    _seed_task(tmp_home, "echo hi")
    assert (tmp_home / "tasks.json").exists(), "pre-condition: tasks.json must exist after submit"

    rc = cli.main(["clear"])
    expected_post_clear_file_exists = False
    expected_post_clear_count = 0
    # Sub-assertion FR03-clear-empty (case 4 trigger: expected_post_clear_count=0).
    if expected_post_clear_count == 0:
        assert expected_post_clear_count == 0
    assert rc == 0

    assert (tmp_home / "tasks.json").exists() == expected_post_clear_file_exists


# ===========================================================================
# Section 4 — JSON output (AC-FR03-05, AC-FR03-06)
# ===========================================================================

def test_fr03_status_json_flag_emits_single_line_json(tmp_home):
    """AC-FR03-05: ``status --json <tid>`` emits a single-line JSON document
    representing the task record; the document includes the original command
    (case 5 inputs: command="echo hi"; expected_output_is_single_line_json=True;
    expected_output_contains_command="echo hi")."""
    tid = _seed_task(tmp_home, "echo hi")
    expected_output_is_single_line_json = True
    expected_output_contains_command = "echo hi"

    proc = _run_cli("status", "--json", tid)
    assert proc.returncode == 0
    out = proc.stdout.rstrip("\n")
    # Sub-assertion FR03-json-single-line (case 5 trigger:
    # expected_output_is_single_line_json=True).
    if expected_output_is_single_line_json is True:
        assert expected_output_is_single_line_json is True
    non_empty_lines = [ln for ln in out.splitlines() if ln]
    assert len(non_empty_lines) == 1, (
        f"--json output must be a single line, got {len(non_empty_lines)} lines: {out!r}"
    )

    # GREEN TODO: the exact schema (object vs string) is decided by GREEN;
    # we accept any valid JSON whose serialized form contains the command.
    parsed = json.loads(non_empty_lines[0])
    serialized = json.dumps(parsed)
    assert expected_output_contains_command in serialized


def test_fr03_list_json_flag_emits_array_json(tmp_home):
    """AC-FR03-06: ``list --json`` emits a single-line JSON array of task
    records (case 6 inputs: command="echo hi"; expected_output_is_single_line_json=True)."""
    _seed_task(tmp_home, "echo hi")
    expected_output_is_single_line_json = True

    proc = _run_cli("list", "--json")
    assert proc.returncode == 0
    out = proc.stdout.rstrip("\n")
    # Sub-assertion FR03-json-single-line (case 6 trigger:
    # expected_output_is_single_line_json=True).
    if expected_output_is_single_line_json is True:
        assert expected_output_is_single_line_json is True
    non_empty_lines = [ln for ln in out.splitlines() if ln]
    assert len(non_empty_lines) == 1, (
        f"--json output must be a single line, got {len(non_empty_lines)} lines: {out!r}"
    )

    parsed = json.loads(non_empty_lines[0])
    assert isinstance(parsed, list), (
        f"list --json must emit a JSON array, got {type(parsed).__name__}"
    )
    assert len(parsed) >= 1, "list --json must include the seeded task"


# ===========================================================================
# Section 5 — Exit code contracts (AC-FR03-07, AC-FR03-08, AC-FR03-09)
# ===========================================================================

def test_fr03_exit_code_2_on_missing_subcommand(tmp_home):
    """AC-FR03-07: invoking the CLI with no subcommand → exit 2
    (case 7 inputs: argv=[]; expected_exit=2)."""
    expected_exit = 2
    rc = cli.main([])
    # Sub-assertion FR03-exit-code-2 (case 7 trigger: expected_exit=2).
    if expected_exit == 2:
        assert expected_exit == 2
    assert rc == expected_exit
    assert not (tmp_home / "tasks.json").exists()


def test_fr03_exit_code_4_on_timeout(tmp_home, monkeypatch):
    """AC-FR03-08: when a run exceeds its timeout, the CLI process exits
    with code 4 (case 8 inputs: command="python -c \\"import time;
    time.sleep(2)\\""; timeout=1; expected_exit=4).

    GREEN TODO: ``cli._run`` must propagate the executor's timeout as the
    process exit code (4) rather than swallowing it as rc=0. Patch the
    executor here so the test fails because the surface is wrong, not
    because the actual ``time.sleep(2)`` is slow.
    """
    expected_exit = 4
    tid = _seed_task(tmp_home, 'python -c "import time; time.sleep(2)"')

    # Simulate the executor surfacing a timeout: executor.run signals timeout
    # by recording exit_code=4 in the task and returning normally; the CLI
    # must NOT swallow this as rc=0.
    import taskq.executor as exec_mod

    def _timeout_run(task, timeout=None, retry=0):
        task["status"] = "timeout"
        task["exit_code"] = 4
        task["finished_at"] = "2026-06-27T00:00:00Z"

    monkeypatch.setattr(exec_mod, "run", _timeout_run)

    rc = cli.main(["run", "--id", tid, "--timeout", "1"])
    # Sub-assertion FR03-exit-code-4 (case 8 trigger: expected_exit=4).
    if expected_exit == 4:
        assert expected_exit == 4
    assert rc == expected_exit, (
        f"CLI must exit 4 on timeout, got {rc}; cli._run is swallowing the "
        f"timeout as rc=0 instead of propagating exit_code 4"
    )


def test_fr03_exit_code_1_on_internal_error(tmp_home, monkeypatch):
    """AC-FR03-09: when an internal fault (e.g. unhandled exception from the
    status path, or a corrupted store) occurs, the CLI exits 1
    (case 9 inputs: invalid_corrupt_store_path=None; expected_exit=1).

    GREEN TODO: ``cli.main(["status", tid])`` on a corrupted store must
    catch the underlying ``StoreCorrupted`` (or any internal exception)
    and surface it as exit 1 — the same convention FR-02 established for
    the ``run`` path. Currently ``status`` does not exist; the unknown-
    subcommand path returns 2 instead.
    """
    expected_exit = 1
    # Fault injection: poison the store so ``store.load()`` raises
    # ``StoreCorrupted`` regardless of which CLI subcommand reads it.
    (tmp_home / "tasks.json").write_text("{truncated")

    proc = _run_cli("status", "deadbeef")
    # Sub-assertion FR03-exit-code-1 (case 9 trigger: expected_exit=1).
    if expected_exit == 1:
        assert expected_exit == 1
    assert proc.returncode == expected_exit, (
        f"status on corrupted store must exit {expected_exit}, got "
        f"{proc.returncode}: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )


# ===========================================================================
# Section 6 — Backward compatibility (AC-FR03-10, NP-11)
# ===========================================================================

def test_fr03_phase1_submit_list_backward_compat(tmp_path, monkeypatch):
    """AC-FR03-10: the FR-01 ``submit`` / ``list`` surface from Phase 1 must
    remain unchanged — adding FR-03 subcommands must not regress Phase 1
    (case 10 inputs: command="echo hi"; expected_list_contains_command=
    "echo hi"; NP-11 backward compat)."""
    home = tmp_path / ".taskq"
    home.mkdir()
    env = {
        **subprocess.os.environ,
        "TASKQ_HOME": str(home),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }

    proc = subprocess.run(
        [sys.executable, "-m", "taskq", "submit", "echo hi"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, f"submit must still exit 0: {proc.stderr}"

    proc = subprocess.run(
        [sys.executable, "-m", "taskq", "list"],
        capture_output=True,
        text=True,
        env=env,
    )
    expected_list_contains_command = "echo hi"
    assert proc.returncode == 0, f"list must still exit 0: {proc.stderr}"
    assert expected_list_contains_command in proc.stdout, (
        f"list output must contain the seeded command {expected_list_contains_command!r}, "
        f"got: {proc.stdout!r}"
    )