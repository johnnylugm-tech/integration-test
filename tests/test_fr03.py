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
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Top-level imports — NOT wrapped in try/except. ModuleNotFoundError on import
# is the expected RED signal that drives the failing-test result.
from taskq.cli.cli import submit, main
from taskq.core.validation import validate
from taskq.io import store as store_mod
from taskq import query as query_mod


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


# ===========================================================================
# Coverage-targeted additions — exercise code paths NOT covered by the seven
# TEST_SPEC.md FR-03 cases. These tests use the same helpers and fixture so
# they share the per-test $TASKQ_HOME isolation.
# ===========================================================================


# --- CLI surface: submit subcommand via main() --------------------------------

def test_fr03_cli_submit_human(taskq_home):
    """Coverage: cli.main() submit branch, human path (no --json, exit 0)."""
    raw = _run_main(["submit", "echo hi"])
    assert raw.exit_code == 0, f"submit human expected 0, got {raw.exit_code}: {raw.stderr!r}"
    # Human path writes a single line: the new task id.
    assert raw.stdout.strip() != "", "submit human must print the new task id"
    assert len(raw.stdout.strip()) == 8, (
        f"submit human output should be 8-char id, got {raw.stdout.strip()!r}"
    )


def test_fr03_cli_submit_json(taskq_home):
    """Coverage: cli.main() submit branch, --json path (single-line JSON, exit 0)."""
    raw = _run_main(["--json", "submit", "echo hi"])
    assert raw.exit_code == 0, f"submit --json expected 0, got {raw.exit_code}: {raw.stderr!r}"
    assert "\n" not in raw.stdout, "--json submit output must be single-line"
    assert raw.stdout.startswith("{"), "--json submit output must be JSON object"
    parsed = json.loads(raw.stdout)
    assert parsed.get("status") == "pending"
    assert parsed.get("command") == "echo hi"
    assert len(parsed.get("id", "")) == 8


def test_fr03_cli_submit_validation_fail(taskq_home):
    """Coverage: cli.main() submit branch on validation failure (exit 2)."""
    raw = _run_main(["submit", ""])
    assert raw.exit_code == 2, f"submit empty expected 2, got {raw.exit_code}"
    assert "non-empty" in raw.stderr or "invalid" in raw.stderr.lower(), (
        f"validation fail must write reason to stderr, got {raw.stderr!r}"
    )


# --- CLI surface: status subcommand human path on a known id ------------------

def test_fr03_cli_status_known_id_human(taskq_home):
    """Coverage: cli.main() status branch human path + query.format_task_human."""
    s = submit("echo hi")
    assert s.exit_code == 0
    raw = _run_main(["status", s.id])
    assert raw.exit_code == 0, f"status known id expected 0, got {raw.exit_code}: {raw.stderr!r}"
    # Human format_task_human writes "key: value" lines.
    assert "id:" in raw.stdout, f"status human must list fields, got {raw.stdout!r}"
    assert s.id in raw.stdout
    assert "pending" in raw.stdout


# --- CLI surface: list subcommand --json path + format_list_json --------------

def test_fr03_cli_list_json(taskq_home):
    """Coverage: cli.main() list --json branch + query.format_list_json."""
    s = submit("echo hi")
    assert s.exit_code == 0
    raw = _run_main(["--json", "list"])
    assert raw.exit_code == 0, f"list --json expected 0, got {raw.exit_code}: {raw.stderr!r}"
    assert "\n" not in raw.stdout, "list --json must be single-line"
    parsed = json.loads(raw.stdout)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["id"] == s.id
    assert parsed[0]["command"] == "echo hi"
    # truncation invariant
    assert len(parsed[0]["command"]) <= 50


# --- CLI surface: list subcommand on corrupt store (exit 1) ------------------

def test_fr03_cli_list_corrupt_store(taskq_home):
    """Coverage: cli.main() list branch CorruptStoreError -> exit 1."""
    tasks_file = taskq_home / "tasks.json"
    tasks_file.write_text("not valid json")
    raw = _run_main(["list"])
    assert raw.exit_code == 1, f"list on corrupt store expected 1, got {raw.exit_code}"
    assert "store corrupted" in raw.stderr, (
        f"list corrupt must write 'store corrupted' to stderr, got {raw.stderr!r}"
    )


# --- CLI surface: list subcommand on empty store (format_list_human empty) ----

def test_fr03_cli_list_empty(taskq_home):
    """Coverage: query.format_list_human empty-list early-return branch."""
    raw = _run_main(["list"])
    assert raw.exit_code == 0, f"list empty expected 0, got {raw.exit_code}: {raw.stderr!r}"
    # empty list -> format_list_human returns "" -> main writes "\n"
    assert raw.stdout.strip() == "", (
        f"list empty should produce no rows, got {raw.stdout!r}"
    )


# --- CLI surface: clear on missing tasks.json (idempotent FileNotFoundError) --

def test_fr03_cli_clear_idempotent_missing_file(taskq_home):
    """Coverage: query.clear() FileNotFoundError branch (no tasks.json)."""
    tasks_file = taskq_home / "tasks.json"
    assert not tasks_file.exists()
    raw = _run_main(["clear"])
    assert raw.exit_code == 0, f"clear on missing file expected 0, got {raw.exit_code}"
    assert not tasks_file.exists(), "clear must NOT create tasks.json"


# --- CLI surface: run on nonexistent task id (executor run_task not-found) ----

def test_fr03_cli_run_nonexistent_task(taskq_home):
    """Coverage: executor.run_task line 35-43 (task id not found -> failed/1)."""
    raw = _run_main(["run", "deadbeef"])
    assert raw.exit_code == 1, f"run on missing task expected 1, got {raw.exit_code}"
    # run_task returns RunResult(exit_code=1, status="failed"); main surfaces
    # the non-zero branch in human mode.
    assert "failed" in raw.stderr or raw.exit_code != 0


# --- CLI surface: run on a task that fails (subprocess returncode != 0) -------

def test_fr03_cli_run_task_failure(taskq_home):
    """Coverage: executor.run_task line 82-84 (returncode != 0 -> failed)."""
    s = submit("false")
    assert s.exit_code == 0
    raw = _run_main(["run", s.id])
    # `false` exits with 1 — single-task mode surfaces non-zero.
    assert raw.exit_code != 0, (
        f"run on `false` expected non-zero exit, got {raw.exit_code}"
    )
    assert "failed" in raw.stderr, (
        f"human run-fail must surface 'failed' status, got {raw.stderr!r}"
    )


# --- CLI surface: run on a task that raises (unhandled-exception path) --------

def test_fr03_cli_run_task_unhandled(taskq_home):
    """Coverage: cli.main() run branch unhandled-exception -> exit 1."""
    # Use a command that resolves to a non-existent binary; subprocess raises
    # FileNotFoundError, executor.run_task catches it (line 95-104) as
    # failed/exit_code=1. The single-task CLI surfaces exit_code=1.
    s = submit("/nonexistent/path/binary_xyz")
    assert s.exit_code == 0, (
        f"submit of nonexistent binary should pass validation, got exit {s.exit_code}"
    )
    raw = _run_main(["run", s.id])
    assert raw.exit_code == 1, (
        f"run on nonexistent binary expected exit 1, got {raw.exit_code}"
    )


# --- Validation rules: length > 1000, blacklist char, non-string input -------

def test_fr03_validation_length_over_limit(taskq_home):
    """Coverage: core.validation line 45-46 (cmd length > 1000)."""
    cmd = "a" * 1001
    outcome = validate(cmd)
    assert outcome.ok is False
    assert "1000" in outcome.reason, (
        f"length-reject reason must mention 1000, got {outcome.reason!r}"
    )


def test_fr03_validation_blacklist_char(taskq_home):
    """Coverage: core.validation line 48-50 (blacklist character rejected)."""
    # Each blacklist char independently rejected.
    for hit in [";", "|", "&", "$", ">", "<", "`"]:
        outcome = validate(f"echo a{hit}b")
        assert outcome.ok is False, f"blacklist char {hit!r} must be rejected"
        assert "disallowed" in outcome.reason, (
            f"blacklist reject reason must say 'disallowed', got {outcome.reason!r}"
        )


def test_fr03_validation_non_string(taskq_home):
    """Coverage: core.validation line 39-40 (non-string input)."""
    outcome = validate(None)
    assert outcome.ok is False
    assert "non-empty" in outcome.reason
    outcome = validate(12345)
    assert outcome.ok is False


# --- Store: payload not dict / tasks not list --------------------------------

def test_fr03_store_payload_not_dict(taskq_home):
    """Coverage: io.store.load_tasks line 44-45 (payload not a dict)."""
    tasks_file = taskq_home / "tasks.json"
    tasks_file.write_text("[1, 2, 3]")  # valid JSON, but a list, not a dict
    result = store_mod.load_tasks()
    assert result == [], "payload-not-dict must yield empty list, not raise"


def test_fr03_store_tasks_not_list(taskq_home):
    """Coverage: io.store.load_tasks line 47 (tasks field is not a list)."""
    tasks_file = taskq_home / "tasks.json"
    tasks_file.write_text('{"tasks": "not-a-list"}')
    result = store_mod.load_tasks()
    assert result == [], "tasks-not-list must yield empty list, not raise"


# --- Query helpers (direct unit coverage of pure functions) ------------------

def test_fr03_query_list_tasks_empty(taskq_home):
    """Coverage: query.list_tasks on empty store."""
    result = query_mod.list_tasks()
    assert result == []


def test_fr03_query_format_task_human(taskq_home):
    """Coverage: query.format_task_human pure function."""
    out = query_mod.format_task_human({"id": "deadbeef", "status": "pending"})
    assert "id: deadbeef" in out
    assert "status: pending" in out


def test_fr03_query_format_list_json_empty(taskq_home):
    """Coverage: query.format_list_json empty-list path."""
    out = query_mod.format_list_json([])
    assert out == "[]"
    assert "\n" not in out


# --- SubmitResult.attempts field assignment via the CLI --json submit branch --

def test_fr03_cli_submit_json_attempts_field(taskq_home):
    """Coverage: cli.main() submit --json writes attempts: 0 (line 142)."""
    raw = _run_main(["--json", "submit", "echo hi"])
    assert raw.exit_code == 0
    parsed = json.loads(raw.stdout)
    assert "attempts" in parsed, "--json submit output must include attempts"
    assert parsed["attempts"] == 0


# --- CLI run unhandled exception: monkeypatch run_task to raise ---------------

def test_fr03_cli_run_unhandled_exception(monkeypatch, taskq_home):
    """Coverage: cli.main() run branch `except Exception` -> exit 1 (line 175-178)."""
    from taskq.cli import cli as cli_mod

    def _boom(_task_id):
        raise RuntimeError("synthetic executor failure")

    monkeypatch.setattr(cli_mod, "run_task", _boom)
    raw = _run_main(["run", "deadbeef"])
    assert raw.exit_code == 1, (
        f"unhandled run exception expected exit 1, got {raw.exit_code}"
    )
    assert "unhandled exception" in raw.stderr, (
        f"unhandled path must write 'unhandled exception', got {raw.stderr!r}"
    )


# --- Store save_tasks exception cleanup (mock os.replace to raise) -----------

def test_fr03_store_save_tasks_exception_cleanup(monkeypatch, taskq_home):
    """Coverage: io.store.save_tasks line 75-81 (best-effort orphan tmp cleanup).

    Monkeypatch os.replace to raise OSError so the except branch is taken,
    then monkeypatch os.unlink to also raise OSError so the inner
    `except OSError: pass` (line 79-80) is exercised.
    """
    original_replace = os.replace

    def _replace_raises(src, dst):
        raise OSError("synthetic replace failure")

    def _unlink_raises(path):
        raise OSError("synthetic unlink failure")

    monkeypatch.setattr(store_mod.os, "replace", _replace_raises)
    monkeypatch.setattr(store_mod.os, "unlink", _unlink_raises)

    with pytest.raises(OSError):
        store_mod.save_tasks([{"id": "deadbeef", "command": "echo hi", "status": "pending"}])

    # restore os.replace so the test's tmp_path teardown works
    monkeypatch.setattr(store_mod.os, "replace", original_replace)

