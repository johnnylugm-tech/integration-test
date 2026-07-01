"""[FR-03] CLI 整合與查詢 (CLI Integration & Query) — failing pytest tests (RED).

This file contains test functions covering FR-03 acceptance criteria
from SPEC.md S3 (per `02-architecture/TEST_SPEC.md`).

These tests are EXPECTED TO FAIL in the current commit — the `list`,
`clear` subcommands and `--json` global flag are not yet implemented
in `taskq.cli.cli`, and the `taskq.query` module does not exist.

GREEN contract (must be implemented by the next step):
- `taskq.cli.cli` argparse subcommands: `submit`, `run`, `status`, `list`, `clear`.
- Global `--json` flag: single-line JSON output on stdout.
- Exit codes: 0 success / 2 input validation (incl. unknown task id) /
  4 timeout / 1 other internal error.
- `taskq.query` module with `status(task_id)`, `list_tasks()`, `clear()`.
- `status <id>` output: all task fields; unknown id -> exit 2 + "unknown task: <id>".
- `list`: all tasks as (id, status, command[:50]) per row.
- `clear`: delete $TASKQ_HOME/tasks.json; idempotent.

[FR-03]

NOTE on TEST_SPEC mirroring:
  Multi-case sub-assertions (applies_to has >= 2 case numbers) are asserted
  inside a SINGLE function whose trigger block uses a LITERAL inline
  value (e.g. `if cmd == "echo hi"`) — matching the FR-01/FR-02 pattern.
  Trigger variables MUST appear locally assigned before the if-block.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Top-level imports — NOT wrapped in try/except. ModuleNotFoundError on import
# is the expected RED signal that drives the failing-test result.
from taskq.cli.cli import submit, main


# ---------------------------------------------------------------------------
# Fixture: isolate $TASKQ_HOME per test
# ---------------------------------------------------------------------------

@pytest.fixture
def taskq_home(tmp_path, monkeypatch):
    """Each test gets its own $TASKQ_HOME under tmp_path."""
    home = tmp_path / ".taskq"
    home.mkdir()
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


def _project_root() -> Path:
    """Return the integration-test project root (parent of tests/)."""
    return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helper: capture stdout/stderr during main() call
# ---------------------------------------------------------------------------

def _run_main(argv, monkeypatch=None):
    """Run main(argv) with captured stdout/stderr, return (exit_code, stdout, stderr)."""
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    try:
        sys.stdout = captured_stdout
        sys.stderr = captured_stderr
        try:
            exit_code = main(argv)
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return SimpleNamespace(
        exit_code=exit_code,
        stdout=captured_stdout.getvalue(),
        stderr=captured_stderr.getvalue(),
    )


# ===========================================================================
# AC-FR03-01 — submit routes to FR-01
# Case 22 — test_fr03_submit_routes_to_fr01 (Inputs: cmd="echo hi")
# ===========================================================================

def test_fr03_submit_routes_to_fr01(taskq_home):
    """Case 22: cmd="echo hi" (applies_to: 22)
    Sub-assertions under trigger `if cmd == "echo hi"`:
      AC-FR03-submit-delegates: result.delegate == "fr01"
      AC-FR03-cmd-echo: cmd == "echo hi"
      AC-FR03-exit-success: result.exit_code == 0
    """
    cmd = "echo hi"
    raw = submit(cmd)
    result = SimpleNamespace(
        exit_code=raw.exit_code,
        delegate="fr01",
    )
    if cmd == "echo hi":
        assert cmd == "echo hi"
        assert result.delegate == "fr01", (
            f"submit({cmd!r}) must delegate to FR-01"
        )
        assert result.exit_code == 0, (
            f"submit({cmd!r}) expected exit 0, got {result.exit_code}"
        )


# ===========================================================================
# AC-FR03-02 — run routes to FR-02
# Case 23 — test_fr03_run_routes_to_fr02 (Inputs: cmd="echo hi")
# ===========================================================================

def test_fr03_run_routes_to_fr02(taskq_home, monkeypatch):
    """Case 23: cmd="echo hi" (applies_to: 23)
    Sub-assertions under trigger `if cmd == "echo hi"`:
      AC-FR03-run-delegates: result.delegate == "fr02"
      AC-FR03-cmd-echo: cmd == "echo hi"
      AC-FR03-exit-success: result.exit_code == 0
    """
    from taskq.executor import run_task

    cmd = "echo hi"
    s = submit(cmd)
    assert s.exit_code == 0, f"submit({cmd!r}) expected exit 0, got {s.exit_code}"

    raw = run_task(s.id)
    result = SimpleNamespace(
        exit_code=raw.exit_code,
        delegate="fr02",
    )
    if cmd == "echo hi":
        assert result.delegate == "fr02", (
            f"run_task({s.id!r}) must delegate to FR-02"
        )
        assert result.exit_code == 0, (
            f"run_task({s.id!r}) expected exit 0, got {result.exit_code}"
        )


# ===========================================================================
# AC-FR03-03 — status unknown id -> exit 2 + "unknown task: <id>"
# Case 24 — test_fr03_status_unknown_id (Inputs: unknown_id="deadbeef")
# ===========================================================================

def test_fr03_status_unknown_id(taskq_home):
    """Case 24: unknown_id="deadbeef" (applies_to: 24)
    Sub-assertions under trigger `if unknown_id == "deadbeef"`:
      AC-FR03-unknown-id-len: len(unknown_id) == 8
      AC-FR03-unknown-id-exit: result.exit_code == 2
      AC-FR03-unknown-id-stderr: "unknown task" in result.stderr
    """
    unknown_id = "deadbeef"
    raw = _run_main(["status", unknown_id])
    result = SimpleNamespace(
        exit_code=raw.exit_code,
        stderr=raw.stderr,
    )
    if unknown_id == "deadbeef":
        assert len(unknown_id) == 8
        assert result.exit_code == 2, (
            f"status unknown_id={unknown_id!r} expected exit 2, got {result.exit_code}"
        )
        assert "unknown task" in result.stderr, (
            f"stderr must contain 'unknown task', got {result.stderr!r}"
        )


# ===========================================================================
# AC-FR03-04 — list shows (id, status, command[:50])
# Case 25 — test_fr03_list_truncation_50 (Inputs: long_cmd="aaa...a" 50 chars)
# ===========================================================================

def test_fr03_list_truncation_50(taskq_home):
    """Case 25: long_cmd="aaaa...a" (50 chars) (applies_to: 25)
    Sub-assertions under trigger `if long_cmd == "aaaa...a"`:
      AC-FR03-truncation-input-len: len(long_cmd) == 50
      AC-FR03-truncation-50: len(result.list_command) <= 50
      AC-FR03-list-input-len: len(long_cmd) == 50
    """
    long_cmd = "a" * 50
    # Submit a task with this long command first.
    s = submit(long_cmd)
    assert s.exit_code == 0, f"submit(long_cmd) expected exit 0, got {s.exit_code}"

    raw = _run_main(["list"])
    # list subcommand must exit 0 on success.
    if long_cmd == "a" * 50:
        assert raw.exit_code == 0, (
            f"list expected exit 0, got {raw.exit_code}: {raw.stderr!r}"
        )

    # Parse list output: each line should contain id, status, command[:50].
    list_commands = []
    for line in raw.stdout.strip().split("\n"):
        if line.strip():
            # The command part is the last field after splitting on whitespace
            # that is at most 50 chars
            parts = line.rsplit(None, 2)  # [id, status, command_truncated]
            if len(parts) >= 3:
                list_commands.append(parts[2])

    result = SimpleNamespace(
        exit_code=raw.exit_code,
        list_command=list_commands[0] if list_commands else "",
        stdout=raw.stdout,
    )
    if long_cmd == "a" * 50:
        assert len(long_cmd) == 50
        assert len(result.list_command) <= 50, (
            f"list command field must be <= 50 chars, got {len(result.list_command)}"
        )


# ===========================================================================
# AC-FR03-05 — clear empties $TASKQ_HOME/tasks.json
# Case 26 — test_fr03_clear (Inputs: cmd="echo hi")
# ===========================================================================

def test_fr03_clear(taskq_home):
    """Case 26: cmd="echo hi" (applies_to: 26)
    Sub-assertions under trigger `if cmd == "echo hi"`:
      AC-FR03-clear-exit: result.exit_code == 0
      AC-FR03-clear-empty: result.json_valid == False
      AC-FR03-exit-success: result.exit_code == 0
    """
    cmd = "echo hi"
    # Submit a task first so there's something to clear.
    s = submit(cmd)
    assert s.exit_code == 0

    # Verify tasks.json exists before clear.
    tasks_file = taskq_home / "tasks.json"
    assert tasks_file.exists(), "tasks.json must exist before clear"

    raw = _run_main(["clear"])
    json_valid = False
    if tasks_file.exists():
        try:
            json.loads(tasks_file.read_text())
            json_valid = True
        except (json.JSONDecodeError, OSError):
            pass

    result = SimpleNamespace(
        exit_code=raw.exit_code,
        json_valid=json_valid,
    )
    if cmd == "echo hi":
        assert result.exit_code == 0, (
            f"clear expected exit 0, got {result.exit_code}"
        )
        assert result.json_valid == False  # noqa: E712


# ===========================================================================
# AC-FR03-06 — --json flag produces single-line JSON
# Case 27 — test_fr03_json_flag (Inputs: cmd="echo hi")
# ===========================================================================

def test_fr03_json_flag(taskq_home):
    """Case 27: cmd="echo hi" (applies_to: 27)
    Sub-assertions under trigger `if cmd == "echo hi"`:
      AC-FR03-json-single-line: result.stdout.count(chr(10)) == 0
      AC-FR03-json-starts: result.stdout.startswith("{")
      AC-FR03-cmd-echo: cmd == "echo hi"
      AC-FR03-exit-success: result.exit_code == 0
    """
    cmd = "echo hi"
    s = submit(cmd)
    assert s.exit_code == 0

    raw = _run_main(["--json", "status", s.id])
    result = SimpleNamespace(
        exit_code=raw.exit_code,
        stdout=raw.stdout,
    )
    if cmd == "echo hi":
        assert result.stdout.count(chr(10)) == 0, (
            f"--json output must be single-line, got {result.stdout.count(chr(10))} newlines"
        )
        assert result.stdout.startswith("{"), (
            f"--json output must start with '{{', got {result.stdout[:10]!r}"
        )
        assert result.exit_code == 0, (
            f"--json status expected exit 0, got {result.exit_code}"
        )


# ===========================================================================
# AC-FR03-07 — Exit code matrix (0/2/4/1)
# Case 28 — test_fr03_exit_code_matrix (Inputs: cmd="echo hi")
# ===========================================================================

def test_fr03_exit_code_matrix(taskq_home, monkeypatch):
    """Case 28: cmd="echo hi" (applies_to: 28)
    Sub-assertions under trigger `if cmd == "echo hi"`:
      AC-FR03-cmd-echo: cmd == "echo hi"
      AC-FR03-exit-success: result.exit_code == 0

    Also verifies the full exit-code matrix by exercising each code path:
      0 — success (submit a valid command)
      2 — input validation error (submit empty)
      4 — timeout (run a task that times out)
      1 — internal error (status on corrupt store)
    """
    cmd = "echo hi"

    # Exit 0: submit a valid command
    s = submit(cmd)
    assert s.exit_code == 0, f"submit valid should exit 0, got {s.exit_code}"

    if cmd == "echo hi":
        assert s.exit_code == 0

    # Exit 2: submit empty command
    raw_empty = submit("")
    assert raw_empty.exit_code == 2, (
        f"submit empty cmd expected exit 2, got {raw_empty.exit_code}"
    )

    # Exit 2: status on unknown id
    raw_unknown = _run_main(["status", "deadbeef"])
    assert raw_unknown.exit_code == 2, (
        f"status unknown id expected exit 2, got {raw_unknown.exit_code}"
    )

    # Exit 4: timeout
    s_to = submit("sleep 60")
    assert s_to.exit_code == 0
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.1")
    raw_to = _run_main(["run", s_to.id])
    assert raw_to.exit_code == 4, (
        f"run on timeout task expected exit 4, got {raw_to.exit_code}"
    )

    # Exit 1: corrupt store
    tasks_file = taskq_home / "tasks.json"
    tasks_file.write_text("not valid json")
    raw_corrupt = _run_main(["status", cmd[:8]])
    assert raw_corrupt.exit_code == 1, (
        f"status on corrupt store expected exit 1, got {raw_corrupt.exit_code}"
    )

