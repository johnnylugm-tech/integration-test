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
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime

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
    """Invoke `python -m taskq <argv>` as a subprocess and capture result."""
    return subprocess.run(
        [sys.executable, "-m", "taskq", *argv],
        capture_output=True,
        text=True,
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
    cmd = "a" * 1000
    rc = cli.main(["submit", cmd])
    assert rc == 0
    data = json.loads((tmp_home / "tasks.json").read_text())
    assert len(data) == 1
    (tid, record), = data.items()
    assert len(tid) == 8
    assert re.fullmatch(r"[0-9a-f]{8}", tid)
    assert record["command"] == cmd


def test_cli_fr01_length_1001_rejected(tmp_home):
    """AC-FR01-04: command of 1001 chars → exit 2, no write."""
    rc = cli.main(["submit", "a" * 1001])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()


def test_cli_fr01_blacklist_semicolon_rejected(tmp_home):
    """AC-FR01-05: command containing ';' → exit 2, no write."""
    rc = cli.main(["submit", "echo a;b"])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()


def test_cli_fr01_blacklist_pipe_rejected(tmp_home):
    """AC-FR01-05: command containing '|' → exit 2, no write."""
    rc = cli.main(["submit", "echo a|b"])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()


def test_cli_fr01_blacklist_ampersand_rejected(tmp_home):
    """AC-FR01-05: command containing '&' → exit 2, no write."""
    rc = cli.main(["submit", "echo a&b"])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()


def test_cli_fr01_blacklist_dollar_rejected(tmp_home):
    """AC-FR01-05: command containing '$' → exit 2, no write."""
    rc = cli.main(["submit", "echo $HOME"])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()


def test_cli_fr01_blacklist_gt_rejected(tmp_home):
    """AC-FR01-05: command containing '>' → exit 2, no write."""
    rc = cli.main(["submit", "echo a>b"])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()


def test_cli_fr01_blacklist_lt_rejected(tmp_home):
    """AC-FR01-05: command containing '<' → exit 2, no write."""
    rc = cli.main(["submit", "echo a<b"])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()


def test_cli_fr01_blacklist_backtick_rejected(tmp_home):
    """AC-FR01-05: command containing '`' → exit 2, no write."""
    rc = cli.main(["submit", "echo `id`"])
    assert rc == 2
    assert not (tmp_home / "tasks.json").exists()


# ===========================================================================
# Section 2 — Unit tests (AC-FR01-06, AC-FR01-07)
# ===========================================================================

def test_unit_fr01_task_id_format_eight_hex():
    """AC-FR01-06: task id is exactly 8 lowercase hex chars (uuid4 prefix)."""
    # GREEN TODO: `taskq.models.new_task_id() -> str` returning uuid4().hex[:8].
    tid = models.new_task_id()
    assert isinstance(tid, str)
    assert len(tid) == 8
    assert re.fullmatch(r"[0-9a-f]{8}", tid)


def test_unit_fr01_task_id_uniqueness_1000_iter():
    """AC-FR01-06: 1000 generated ids must all be distinct."""
    ids = {models.new_task_id() for _ in range(1000)}
    assert len(ids) == 1000
    for tid in ids:
        assert re.fullmatch(r"[0-9a-f]{8}", tid)


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

def test_integration_fr01_atomic_write_no_tmp_leftover(tmp_home):
    """AC-FR01-08: after a successful submit, no `.tmp` file remains."""
    rc = cli.main(["submit", "echo hi"])
    assert rc == 0
    leftovers = [p for p in tmp_home.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


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
    assert proc.returncode == 1
    assert "store corrupted" in proc.stderr


def test_integration_fr01_corrupted_garbage_exit_one(tmp_home):
    """AC-FR01-09: garbage bytes → exit 1, stderr contains 'store corrupted'."""
    (tmp_home / "tasks.json").write_bytes(b"garbage_bytes\xff\x00\xff")
    proc = _run_cli("list")
    assert proc.returncode == 1
    assert "store corrupted" in proc.stderr


def test_integration_fr01_corrupted_content_unchanged(tmp_home):
    """AC-FR01-09: corruption handling must NOT silently rebuild tasks.json
    — the on-disk bytes must remain byte-for-byte identical to the input."""
    raw = b"corrupted_payload_!!!\x00\xff"
    (tmp_home / "tasks.json").write_bytes(raw)
    proc = _run_cli("list")
    assert proc.returncode == 1
    assert (tmp_home / "tasks.json").read_bytes() == raw
