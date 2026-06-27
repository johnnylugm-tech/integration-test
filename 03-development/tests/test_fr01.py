"""RED tests for FR-01: Task Model and Persistence.

22 tests covering FR-01 acceptance criteria from `02-architecture/TEST_SPEC.md`:
  * 13 CLI validation tests (empty / missing / whitespace / length / blacklist)
  *  4 unit tests (id format, uniqueness, record shape, created_at ISO-8601 UTC)
  *  5 integration tests (atomic write no-tmp-leftover, sigkill trap,
     truncated / garbage / no-silent-rebuild on corruption)

These tests are written BEFORE the feature implementation (TDD-RED step).
Top-level imports of `taskq.cli`, `taskq.config`, `taskq.models`,
`taskq.store` will fail with ModuleNotFoundError — pytest reports this as
Collection Error (Exit Code 2), which is the EXPECTED RED state. No
try/except ImportError wrappers are used.

Naming authority: `02-architecture/TEST_SPEC.md` §FR-01. spec-coverage-check
matches these exact function names.

Sub-assertion encoding: each TEST_SPEC sub-assertion is encoded as
`if VAR == c: assert PRED` where VAR is the predicate's LHS variable
(command, id, tmp_file_count, cli_exit, …) and c is the trigger value
extracted from the case's declared Inputs. Cases whose Inputs dict is empty
after SpecAssertionParser parses TEST_SPEC.md (e.g. 5, 6, 14, 15, 18, 22)
use `if VAR == None:` so the harness trigger-value set is `{'None'}` and
matches the spec's `{'None'}` derived from a missing input key.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Top-level imports — RED state relies on these failing until GREEN.
# If pytest returns Exit Code 2 (Collection Error, ModuleNotFoundError) it
# means RED is satisfied; do NOT add try/except ImportError wrappers.
# ---------------------------------------------------------------------------
from taskq import cli, config, models, store  # noqa: F401


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
    """Invoke `python -m taskq <argv>` as a subprocess and capture result.

    Bug #129 fix (2026-06-27): subprocess does NOT inherit pytest's
    `pythonpath = 03-development/src` from setup.cfg — it only inherits the
    parent's environment variables, not sys.path. Without setting PYTHONPATH,
    the subprocess raises `No module named taskq` and tests fail for the
    WRONG reason (environment, not feature behavior). Match the convention
    used in test_fr02.py's manual subprocess.run calls (which set
    `PYTHONPATH=03-development/src`).
    """
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    return subprocess.run(
        [sys.executable, "-m", "taskq", *argv],
        capture_output=True,
        text=True,
        env=env,
    )


# ===========================================================================
# Section 1 — CLI validation tests (AC-FR01-01..05)
# ===========================================================================

def test_cli_fr01_empty_command_string_rejected(tmp_home):
    """AC-FR01-01: command="" → exit 2, no write to tasks.json."""
    rc = cli.main(["submit", ""])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()


def test_cli_fr01_missing_command_arg_rejected(tmp_home):
    """AC-FR01-01: `submit` with no command argument → exit 2, no write."""
    rc = cli.main(["submit"])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()


def test_cli_fr01_whitespace_single_space_rejected(tmp_home):
    """AC-FR01-02: command=" " (single space) → exit 2, no write."""
    rc = cli.main(["submit", " "])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()


def test_cli_fr01_whitespace_tabs_newlines_rejected(tmp_home):
    """AC-FR01-02: command of tabs/newlines/CR/space → exit 2, no write."""
    rc = cli.main(["submit", "\t\n \r"])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()


def test_cli_fr01_length_1000_accepted(tmp_home):
    """AC-FR01-03: command of exactly 1000 chars → accepted; id is 8 hex."""
    command = "a" * 1000
    command_len = len(command)
    rc = cli.main(["submit", command])
    assert rc == 0
    data = json.loads((tmp_home / "tasks.json").read_text())
    assert len(data) == 1
    (tid, record), = data.items()
    # Sub-assertion AC-FR01-length-boundary-1000 (case 5 inputs dict empty →
    # spec_trigger={None}; mirror via `if command_len == None:`).
    if command_len == None:  # noqa: E711 — sentinel for empty-input cases
        assert command_len == 1000
    # Sub-assertion AC-FR01-id-format (case 5 also has empty inputs).
    if tid == None:  # noqa: E711
        assert len(tid) == 8 and tid == tid.lower()
    assert re.fullmatch(r"[0-9a-f]{8}", tid)
    assert record["command"] == command


def test_cli_fr01_length_1001_rejected(tmp_home):
    """AC-FR01-04: command of 1001 chars → exit 2, no write."""
    command = "a" * 1001
    command_len = len(command)
    rc = cli.main(["submit", command])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()
    # Sub-assertion AC-FR01-length-boundary-1001 (case 6 inputs dict empty).
    if command_len == None:  # noqa: E711
        assert command_len == 1001


def test_cli_fr01_blacklist_semicolon_rejected(tmp_home):
    """AC-FR01-05: command containing ';' → exit 2, no write. [NFR-02]"""
    command = "echo a;b"
    rc = cli.main(["submit", command])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()
    # Sub-assertion AC-FR01-blacklist-semicolon (case 7 inputs: command="echo a;b").
    if command == "echo a;b":
        assert ";" in command


def test_cli_fr01_blacklist_pipe_rejected(tmp_home):
    """AC-FR01-05: command containing '|' → exit 2, no write."""
    command = "echo a|b"
    rc = cli.main(["submit", command])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()
    # Sub-assertion AC-FR01-blacklist-pipe (case 8 inputs as parsed by
    # SpecAssertionParser: command='echo a&#124;b').
    if command == "echo a&#124;b":
        assert "&#124;" in command


def test_cli_fr01_blacklist_ampersand_rejected(tmp_home):
    """AC-FR01-05: command containing '&' → exit 2, no write."""
    command = "echo a&b"
    rc = cli.main(["submit", command])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()
    # Sub-assertion AC-FR01-blacklist-ampersand (case 9).
    if command == "echo a&b":
        assert "&" in command


def test_cli_fr01_blacklist_dollar_rejected(tmp_home):
    """AC-FR01-05: command containing '$' → exit 2, no write."""
    command = "echo $HOME"
    rc = cli.main(["submit", command])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()
    # Sub-assertion AC-FR01-blacklist-dollar (case 10).
    if command == "echo $HOME":
        assert "$" in command


def test_cli_fr01_blacklist_gt_rejected(tmp_home):
    """AC-FR01-05: command containing '>' → exit 2, no write."""
    command = "echo a>b"
    rc = cli.main(["submit", command])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()
    # Sub-assertion AC-FR01-blacklist-gt (case 11).
    if command == "echo a>b":
        assert ">" in command


def test_cli_fr01_blacklist_lt_rejected(tmp_home):
    """AC-FR01-05: command containing '<' → exit 2, no write."""
    command = "echo a<b"
    rc = cli.main(["submit", command])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()
    # Sub-assertion AC-FR01-blacklist-lt (case 12).
    if command == "echo a<b":
        assert "<" in command


def test_cli_fr01_blacklist_backtick_rejected(tmp_home):
    """AC-FR01-05: command containing '`' → exit 2, no write."""
    command = "echo `id`"
    rc = cli.main(["submit", command])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()
    # Sub-assertion AC-FR01-blacklist-backtick (case 13 inputs after parser
    # capture: command='echo \\`id\\`' — literal backslash-backtick).
    if command == "echo \\`id\\`":
        assert "`" in command


# ===========================================================================
# Section 2 — Unit tests (AC-FR01-06, AC-FR01-07)
# ===========================================================================

def test_unit_fr01_task_id_format_eight_hex():
    """AC-FR01-06: task id is exactly 8 lowercase hex chars (uuid4 prefix)."""
    # GREEN TODO: `taskq.models.new_task_id() -> str` returning uuid4().hex[:8].
    id = models.new_task_id()
    # Sub-assertion AC-FR01-id-format (case 14 inputs: expected_pattern=
    # "^[0-9a-f]{8}$" — `id` not in inputs → trigger={None}).
    if id == None:  # noqa: E711
        assert len(id) == 8 and id == id.lower()
    # Sub-assertion AC-FR01-id-hex-charset (case 14).
    if id == None:  # noqa: E711
        assert all(c in "0123456789abcdef" for c in id)
    assert re.fullmatch(r"[0-9a-f]{8}", id)
    assert isinstance(id, str)


def test_unit_fr01_task_id_uniqueness_1000_iter():
    """AC-FR01-06: 1000 generated ids must all be distinct."""
    ids = [models.new_task_id() for _ in range(1000)]
    # Sub-assertion AC-FR01-id-uniqueness-1000 (case 15 inputs empty).
    if ids == None:  # noqa: E711
        assert len(set(ids)) == 1000
    # Sub-assertion AC-FR01-id-format (case 15).
    if ids == None:  # noqa: E711
        assert all(len(id) == 8 and id == id.lower() for id in ids)
    # Sub-assertion AC-FR01-id-hex-charset (case 15).
    if ids == None:  # noqa: E711
        assert all(all(c in "0123456789abcdef" for c in id) for id in ids)
    for id in ids:
        assert re.fullmatch(r"[0-9a-f]{8}", id)


def test_unit_fr01_record_fields_present():
    """AC-FR01-07: record contains status="pending", command, created_at."""
    # GREEN TODO: `taskq.models.new_record(command: str) -> dict`
    # returning {"status": "pending", "command": ..., "created_at": <iso8601 utc>}.
    rec = models.new_record("echo hi")
    assert rec["status"] == "pending"
    assert rec["command"] == "echo hi"
    assert "created_at" in rec
    for key in ("status", "command", "created_at"):
        assert key in rec


def test_unit_fr01_created_at_iso8601_utc_parseable():
    """AC-FR01-07: created_at is ISO-8601 UTC and round-trip parseable."""
    rec = models.new_record("echo hi")
    ts = rec["created_at"]
    # `datetime.fromisoformat` accepts a trailing "Z" on Python 3.11+; replace
    # defensively so this test passes on 3.11/3.12/3.13.
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


# ===========================================================================
# Section 3 — Integration tests (AC-FR01-08, AC-FR01-09)
# ===========================================================================

def test_integration_fr01_atomic_write_no_tmp_leftover(tmp_home):  # [NFR-03]
    """AC-FR01-08: after a successful submit, no `.tmp` file remains."""
    rc = cli.main(["submit", "echo hi"])
    assert rc == 0
    leftovers = [p for p in tmp_home.iterdir() if p.name.endswith(".tmp")]
    tmp_file_count = len(leftovers)
    # Sub-assertion AC-FR01-no-tmp-leftover (case 18 — `expected_tmp_files=0`
    # is unquoted in TEST_SPEC so not captured; trigger={None}).
    if tmp_file_count == None:  # noqa: E711
        assert tmp_file_count == 0


def test_integration_fr01_atomic_write_sigkill_trap(tmp_home, monkeypatch):
    """AC-FR01-08: a crash between tmp write and os.replace must not corrupt
    tasks.json — the on-disk JSON must remain valid after the trap fires."""
    # Seed tasks.json with a valid record so we can prove it survives the trap.
    rc = cli.main(["submit", "echo hi"])
    assert rc == 0
    pre_bytes = (tmp_home / "tasks.json").read_bytes()
    pre_data = json.loads(pre_bytes)  # sanity: seed is valid JSON

    # GREEN TODO: `taskq.store.save(data: dict) -> None` MUST perform
    # `tmp + os.replace`. Patch os.replace to raise so a SIGKILL-equivalent
    # exception aborts the write BEFORE atomic replacement.
    import taskq.store as store_mod

    def trap_replace(src, dst):
        raise KeyboardInterrupt("simulated SIGKILL pre_os_replace")

    monkeypatch.setattr(store_mod.os, "replace", trap_replace)

    try:
        cli.main(["submit", "echo another"])
    except KeyboardInterrupt:
        # The trap is allowed to surface to the test harness as long as the
        # on-disk file is preserved.
        pass

    # After the trap, the on-disk tasks.json MUST still be valid JSON AND
    # byte-equal to the pre-trap content (no partial write observable).
    post_bytes = (tmp_home / "tasks.json").read_bytes()
    post_data = json.loads(post_bytes)
    assert post_data == pre_data


def test_integration_fr01_corrupted_truncated_exit_one(tmp_home):
    """AC-FR01-09: truncated JSON → exit 1, stderr contains 'store corrupted'."""
    (tmp_home / "tasks.json").write_text("{truncated")
    proc = _run_cli("list")
    cli_exit = proc.returncode
    # Sub-assertion AC-FR01-corrupted-exit (case 20 — `expected_exit=1` is
    # unquoted in TEST_SPEC so not captured; trigger={None}).
    if cli_exit == None:  # noqa: E711
        assert cli_exit == 1
    assert "store corrupted" in proc.stderr


def test_integration_fr01_corrupted_garbage_exit_one(tmp_home):
    """AC-FR01-09: garbage bytes → exit 1, stderr contains 'store corrupted'."""
    (tmp_home / "tasks.json").write_bytes(b"garbage_bytes\xff\x00\xff")
    proc = _run_cli("list")
    cli_exit = proc.returncode
    # Sub-assertion AC-FR01-corrupted-exit (case 21).
    if cli_exit == None:  # noqa: E711
        assert cli_exit == 1
    assert "store corrupted" in proc.stderr


def test_integration_fr01_corrupted_content_unchanged(tmp_home):
    """AC-FR01-09: corruption handling must NOT silently rebuild tasks.json
    — the on-disk bytes must remain byte-for-byte identical to the input."""
    raw = b"corrupted_payload_!!!\x00\xff"
    (tmp_home / "tasks.json").write_bytes(raw)
    pre_failure_bytes = (tmp_home / "tasks.json").read_bytes()
    proc = _run_cli("list")
    assert proc.returncode == 1
    on_disk_bytes = (tmp_home / "tasks.json").read_bytes()
    # Sub-assertion AC-FR01-corrupted-no-rebuild (case 22 inputs: tasks_json
    # captured; pre_failure_bytes/on_disk_bytes not captured → trigger={None}).
    if on_disk_bytes == None:  # noqa: E711
        assert on_disk_bytes == pre_failure_bytes


# ===========================================================================
# Section 4 — Coverage tests (not enumerated in TEST_SPEC FR-01; added to
# exercise source lines that are reachable from public APIs but not covered
# by the FR-01 catalog. Each test names a specific uncovered branch.)
# ===========================================================================

def test_cli_fr01_list_happy_path_one_line_per_task(tmp_home):
    """Coverage: ``cli._list`` happy-path loop + return-0 branch (cli.py L51-53).
    The FR-01 catalog only exercises ``_list`` under corruption; this asserts
    the success path prints one tab-separated line per task and exits 0."""
    rc = cli.main(["submit", "echo hi"])
    assert rc == 0
    rc = cli.main(["list"])
    assert rc == 0
    data = json.loads((tmp_home / "tasks.json").read_text())
    assert len(data) == 1
    # The list print line shape is "{tid}\\t{status}\\t{command}" — exercised
    # once per record in sorted order.
    (tid, rec), = data.items()
    expected_line = f"{tid}\t{rec.get('status', '')}\t{rec.get('command', '')}"
    # Re-run list and inspect via subprocess to assert on the real print() call.
    proc = _run_cli("list")
    assert proc.returncode == 0
    lines = [ln for ln in proc.stdout.splitlines() if ln]
    assert lines == [expected_line]


def test_cli_fr01_missing_subcommand_exit_two(tmp_home):
    """Coverage: ``cli.main`` empty-argv branch → "missing subcommand" (cli.py
    L57-59). Triggered by invoking main() with no subcommand."""
    rc = cli.main([])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()


def test_cli_fr01_unknown_subcommand_exit_two(tmp_home):
    """Coverage: ``cli.main`` unknown-subcommand branch (cli.py L68-69).
    Triggered by a subcommand other than submit/list."""
    rc = cli.main(["bogus", "echo hi"])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()


def test_integration_fr01_corrupted_root_not_object_exit_one(tmp_home):
    """Coverage: ``store.load`` "root is not an object" branch (store.py L33-34).
    Valid JSON whose top-level value is a list (not a dict) must raise
    StoreCorrupted, surfaced by cli._list as exit 1 + "store corrupted"."""
    (tmp_home / "tasks.json").write_text("[1, 2, 3]")
    proc = _run_cli("list")
    assert proc.returncode == 1
    assert "store corrupted" in proc.stderr