"""FR-01 — 任務模型與持久化 (Task Model & Persistence) — failing TDD tests.

These tests are the RED step of the FR-01 TDD cycle. They are intentionally
failing because `taskq/` (the source package) does not exist yet. Each test
function name matches `02-architecture/TEST_SPEC.md` exactly so the
spec-coverage-check tool (D4) can verify 1:1 traceability.

Test mapping to TEST_SPEC.md FR-01 cases:

    case  1  -> test_fr01_submit_empty
    case  2  -> test_fr01_submit_whitespace
    case  3  -> test_fr01_submit_length_boundary
    case  4  -> test_fr01_submit_injection_semicolon
    case  5  -> test_fr01_submit_injection_pipe
    case  6  -> test_fr01_submit_injection_amp
    case  7  -> test_fr01_submit_injection_dollar
    case  8  -> test_fr01_submit_injection_gt
    case  9  -> test_fr01_submit_injection_lt
    case 10  -> test_fr01_submit_injection_backtick
    case 10b -> test_fr01_blacklist_chars_present
    case 11  -> test_fr01_submit_valid
    case 12  -> test_fr01_pending_state_record
    case 13  -> test_fr01_atomic_write
    case 14  -> test_fr01_corrupt_store_exit1
    case 15  -> test_fr01_no_write_on_reject

Sub-assertions follow `TEST_SPEC.md` FR-01 sub-assertion table verbatim.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

from conftest import (
    load_tasks,
    run_taskq,
    tasks_json_path,
    write_corrupt_tasks_json,
)


# ---------------------------------------------------------------------------
# Constants derived from TEST_SPEC.md FR-01 sub-assertion table
# ---------------------------------------------------------------------------

# AC-FR01-id-format: len(result.id) == 8
ID_LENGTH = 8
# AC-FR01-id-hex: all(c in "0123456789abcdef" for c in result.id)
ID_HEX_CHARS = set("0123456789abcdef")
# SPEC §3 FR-01: 命令 > 1000 字元 → 拒絕
LENGTH_LIMIT = 1000
# SPEC §3 FR-01: 命令含 ; | & $ > < ` 任一 → 拒絕 (NFR-02)
INJECTION_CHARS = set(";|$><`")


def _parse_json_output(proc) -> dict:
    """Parse the `--json` stdout of a taskq CLI invocation.

    Returns the parsed dict, or asserts with a helpful message on parse failure.
    """
    out = (proc.stdout or "").strip()
    assert out.startswith("{"), (
        f"expected JSON output starting with '{{', got stdout={out!r}, "
        f"stderr={proc.stderr!r}, returncode={proc.returncode}"
    )
    return json.loads(out)


# ---------------------------------------------------------------------------
# Validation rules (cases 1–10, 15)
# ---------------------------------------------------------------------------


def test_fr01_submit_empty(taskq_env, taskq_home):
    """case 1 — AC-FR01-empty-rejected: empty command must be rejected with exit 2."""
    proc = run_taskq(["submit", ""], env=taskq_env)
    assert proc.returncode == 2, (
        f"empty command must yield exit 2, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )


def test_fr01_submit_whitespace(taskq_env, taskq_home):
    """case 2 — AC-FR01-whitespace-rejected: whitespace-only command must be rejected."""
    proc = run_taskq(["submit", "   "], env=taskq_env)
    assert proc.returncode == 2, (
        f"whitespace-only command must yield exit 2, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )


def test_fr01_submit_length_boundary(taskq_env, taskq_home):
    """case 3 — boundary at the 1000/1001-char limit.

    AC-FR01-length-at-limit-accepted: 1000-char command is accepted.
    AC-FR01-length-over-limit-rejected: 1001-char command is rejected with exit 2.
    """
    cmd_at_limit = "a" * LENGTH_LIMIT
    cmd_over_limit = "a" * (LENGTH_LIMIT + 1)

    # Sub-assertion: lengths match the spec boundary
    assert len(cmd_at_limit) == LENGTH_LIMIT
    assert len(cmd_over_limit) == LENGTH_LIMIT + 1

    # 1000 chars — must be accepted (exit 0)
    proc_ok = run_taskq(["submit", "--json", cmd_at_limit], env=taskq_env)
    assert proc_ok.returncode == 0, (
        f"1000-char command must be accepted (exit 0), got {proc_ok.returncode}; "
        f"stderr={proc_ok.stderr!r}"
    )

    # 1001 chars — must be rejected (exit 2)
    proc_bad = run_taskq(["submit", "--json", cmd_over_limit], env=taskq_env)
    assert proc_bad.returncode == 2, (
        f"1001-char command must be rejected (exit 2), got {proc_bad.returncode}; "
        f"stderr={proc_bad.stderr!r}"
    )


def test_fr01_submit_injection_semicolon(taskq_env, taskq_home):
    """case 4 — AC-FR01-injection-semicolon: `;` must cause rejection."""
    cmd = "echo a;b"
    assert cmd.find(";") != -1  # sub-assertion: input truly contains the char
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2


def test_fr01_submit_injection_pipe(taskq_env, taskq_home):
    """case 5 — AC-FR01-injection-pipe: `|` must cause rejection."""
    pipe_char = "|"
    cmd = f"echo a{pipe_char}b"
    assert cmd.find(pipe_char) != -1
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2


def test_fr01_submit_injection_amp(taskq_env, taskq_home):
    """case 6 — AC-FR01-injection-amp: `&` must cause rejection."""
    cmd = "echo a&b"
    assert cmd.find("&") != -1
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2


def test_fr01_submit_injection_dollar(taskq_env, taskq_home):
    """case 7 — AC-FR01-injection-dollar: `$` must cause rejection."""
    cmd = "echo $HOME"
    assert cmd.find("$") != -1
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2


def test_fr01_submit_injection_gt(taskq_env, taskq_home):
    """case 8 — AC-FR01-injection-gt: `>` must cause rejection."""
    cmd = "echo a>b"
    assert cmd.find(">") != -1
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2


def test_fr01_submit_injection_lt(taskq_env, taskq_home):
    """case 9 — AC-FR01-injection-lt: `<` must cause rejection."""
    cmd = "echo a<b"
    assert cmd.find("<") != -1
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2


def test_fr01_submit_injection_backtick(taskq_env, taskq_home):
    """case 10 — AC-FR01-injection-backtick: backtick must cause rejection."""
    cmd = "echo `id`"
    assert cmd.find("`") != -1
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2


def test_fr01_blacklist_chars_present(taskq_env, taskq_home):
    """case 10b — AC-FR01-blacklist-char-count: the blacklist contains exactly 7 chars.

    The NFR-02 injection blacklist is `; | & $ > < `` ` `` (7 distinct chars).
    Verifying coverage: every one of the 7 chars, when used in `submit`,
    causes exit 2. Structural sub-assertion on the count itself is also
    included so the test fails fast if the constant drifts.
    """
    semicolon = ";"
    pipe_chr = "|"
    amp = "&"
    dollar = "$"
    gt = ">"
    lt = "<"
    btick = "`"
    blacklist = semicolon + pipe_chr + amp + dollar + gt + lt + btick

    # AC-FR01-blacklist-char-count: structural shape of the blacklist
    assert len(blacklist) == 7, (
        f"FR-01 blacklist must contain exactly 7 chars, got {len(blacklist)}"
    )
    # Verify the 7-char set matches the canonical SPEC §3 FR-01 row.
    assert set(blacklist) == INJECTION_CHARS, (
        f"FR-01 blacklist drift: got {sorted(blacklist)!r}, "
        f"expected {sorted(INJECTION_CHARS)!r}"
    )

    # AC-FR01-exit-code-on-reject: each char individually causes exit 2.
    for ch in blacklist:
        proc = run_taskq(["submit", f"echo a{ch}b"], env=taskq_env)
        assert proc.returncode == 2, (
            f"blacklist char {ch!r} must cause exit 2, "
            f"got {proc.returncode}; stderr={proc.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Happy-path / state-record (cases 11, 12)
# ---------------------------------------------------------------------------


def test_fr01_submit_valid(taskq_env, taskq_home):
    """case 11 — AC-FR01-valid-accepted: a non-empty, in-bounds, blacklist-free cmd succeeds.

    On success: exit 0; result.id is 8 lowercase-hex chars; result.status == "pending";
    result.command == cmd; result.attempts == 0.
    """
    cmd = "echo hi"
    proc = run_taskq(["submit", "--json", cmd], env=taskq_env)
    assert proc.returncode == 0, (
        f"valid submit must yield exit 0, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )

    result = _parse_json_output(proc)

    # AC-FR01-id-format
    assert len(result["id"]) == ID_LENGTH, (
        f"task id must be 8 hex chars, got {result['id']!r}"
    )
    # AC-FR01-id-hex
    assert all(c in ID_HEX_CHARS for c in result["id"]), (
        f"task id must be lowercase hex, got {result['id']!r}"
    )
    # AC-FR01-status-pending
    assert result["status"] == "pending", (
        f"newly-submitted task must be pending, got {result['status']!r}"
    )
    # AC-FR01-command-preserved
    assert result["command"] == cmd, (
        f"command must round-trip, got {result['command']!r} != {cmd!r}"
    )
    # AC-FR01-attempts-zero
    assert result["attempts"] == 0, (
        f"newly-submitted task must have attempts=0, got {result['attempts']!r}"
    )


def test_fr01_pending_state_record(taskq_env, taskq_home):
    """case 12 — submit creates a pending record persisted on disk.

    After a successful `submit`, `$TASKQ_HOME/tasks.json` exists and contains
    exactly one task with the expected fields. This is the integration
    counterpart to test_fr01_submit_valid: the in-memory object is also on disk.
    """
    cmd = "sleep 0"
    proc = run_taskq(["submit", "--json", cmd], env=taskq_env)
    assert proc.returncode == 0
    result = _parse_json_output(proc)

    # Sub-assertion: AC-FR01-valid-accepted for sleep 0 (a non-blocking command).
    assert result["status"] == "pending"
    assert result["command"] == cmd
    assert result["attempts"] == 0
    assert len(result["id"]) == ID_LENGTH
    assert all(c in ID_HEX_CHARS for c in result["id"])

    # The task must also be persisted to $TASKQ_HOME/tasks.json.
    tasks_file = tasks_json_path(taskq_home)
    assert tasks_file.exists(), (
        f"tasks.json must exist after submit, got {list(taskq_home.iterdir())}"
    )
    tasks = load_tasks(taskq_home)
    assert isinstance(tasks, list) and len(tasks) == 1, (
        f"tasks.json must contain exactly one record, got {tasks!r}"
    )
    on_disk = tasks[0]
    assert on_disk["id"] == result["id"], (
        f"on-disk id must match CLI-reported id: {on_disk.get('id')!r} != {result['id']!r}"
    )
    assert on_disk["status"] == "pending"
    assert on_disk["command"] == cmd


# ---------------------------------------------------------------------------
# Atomic write + corruption detection + reject-doesn't-write (cases 13, 14, 15)
# ---------------------------------------------------------------------------


def test_fr01_atomic_write(taskq_env, taskq_home):
    """case 13 — AC-FR01-atomic-write: successful submit persists a parseable JSON store.

    AC-FR01-06: 原子寫入 $TASKQ_HOME/tasks.json (tmp + os.replace).
    The user-observable guarantee is that after submit, tasks.json is a
    valid JSON file containing the new task — i.e. no partial-write state
    is ever visible to a reader (the executor / list subcommand).
    """
    cmd = "echo hi"
    proc = run_taskq(["submit", "--json", cmd], env=taskq_env)
    assert proc.returncode == 0
    result = _parse_json_output(proc)

    tasks_file = tasks_json_path(taskq_home)
    assert tasks_file.exists(), "tasks.json must exist after successful submit"

    # Atomic-write observability: the file is parseable as a whole —
    # a half-written tmp file would raise JSONDecodeError here.
    tasks = load_tasks(taskq_home)
    assert isinstance(tasks, list)
    ids = [t.get("id") for t in tasks]
    assert result["id"] in ids, (
        f"submitted task {result['id']!r} must be present in tasks.json; got {ids!r}"
    )

    # No leftover .tmp file should remain after a successful write
    # (production code writes to .tmp then os.replace's it over tasks.json).
    leftover_tmps = [
        p for p in taskq_home.iterdir()
        if p.name.endswith(".tmp") or p.name.endswith(".tmp." + result["id"])
    ]
    assert not leftover_tmps, (
        f"atomic write must not leave .tmp files behind, found {leftover_tmps!r}"
    )


def test_fr01_corrupt_store_exit1(taskq_env, taskq_home):
    """case 14 — AC-FR01-corrupt-exit1 + AC-FR01-corrupt-stderr.

    If `$TASKQ_HOME/tasks.json` contains invalid JSON, the next taskq
    invocation must detect the corruption, exit 1, and print
    `store corrupted` to stderr — without silently rebuilding.
    """
    write_corrupt_tasks_json(taskq_home)
    proc = run_taskq(["list"], env=taskq_env)
    assert proc.returncode == 1, (
        f"corrupt tasks.json must yield exit 1, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    assert "store corrupted" in (proc.stderr or ""), (
        f"stderr must contain 'store corrupted', got {proc.stderr!r}"
    )

    # "no silent rebuild" — the corrupt file must NOT have been overwritten
    # with a fresh empty list by the detection path.
    tasks_file = tasks_json_path(taskq_home)
    assert tasks_file.exists(), "tasks.json must not be silently deleted"
    on_disk = tasks_file.read_text(encoding="utf-8")
    assert "not-valid-json" in on_disk, (
        "corrupt store must not be silently rewritten — original bytes must remain"
    )


def test_fr01_no_write_on_reject(taskq_env, taskq_home):
    """case 15 — AC-FR01-reject-writes-nothing: rejected submit must not write to storage.

    After a rejected submit (`bad;cmd` — contains `;`), tasks.json must NOT
    exist (or be unchanged from its prior state). This is verbatim from
    SPEC.md FR-01 preamble: "任一違反 → exit 2 + stderr 錯誤訊息,不寫入存儲".
    """
    cmd = "bad;cmd"
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2, (
        f"rejected submit must yield exit 2, got {proc.returncode}"
    )

    tasks_file = tasks_json_path(taskq_home)
    if tasks_file.exists():
        # If something exists, it must not contain the rejected cmd.
        on_disk = tasks_file.read_text(encoding="utf-8")
        assert cmd not in on_disk, (
            f"rejected cmd {cmd!r} must not appear in tasks.json; got {on_disk!r}"
        )
        # And it must be valid JSON (no half-written partial record).
        try:
            tasks = json.loads(on_disk)
        except json.JSONDecodeError as e:
            raise AssertionError(
                f"rejected submit must not leave a partial/corrupt tasks.json: {e}"
                )
        ids = [t.get("id") for t in tasks if isinstance(t, dict)]
        assert len(ids) == 0, (
            f"rejected submit must not produce any task records; got {ids!r}"
        )
    # else: tasks.json doesn't exist — also satisfies "no write on reject".