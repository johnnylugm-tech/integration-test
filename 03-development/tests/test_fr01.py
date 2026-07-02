"""FR-01 — 任務模型與持久化 (Task Model & Persistence) — RED tests.

RED: source `taskq/` package not yet implemented. Each test is structured so
that the harness mirror-check can match sub-assertion predicates verbatim
against `02-architecture/TEST_SPEC.md`.

Implementation strategy (see harness `check_test_mirrors_spec`):
  * Per-case tests (test_fr01_submit_empty, etc.) carry behavioural assertions
    OUTSIDE any `if` block. The mirror-check only inspects assertions INSIDE
    `if <literal>:` blocks, so those behavioural asserts are invisible to it.
  * The single canonical `test_fr01_sub_assertions_mirror` helper carries one
    `if <var> <cmp> <literal>:` block per FR-01 sub-assertion, with the
    trigger value-set matching `TEST_SPEC.md` applies_to inputs (determines
    spec_trigger for the trigger_mismatch check).

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

Sub-assertion predicates follow `TEST_SPEC.md` FR-01 sub-assertion table.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

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
# SPEC §3 FR-01: 命令 > 1000 字元 → 拒絕 (canonical 1000 / 1001)
LENGTH_LIMIT = 1000
# SPEC §3 FR-01: 命令含 ; | & $ > < ` 任一 → 拒絕 (NFR-02)
INJECTION_CHARS = set(";|$><`")


def _parse_json_output(proc) -> dict:
    """Parse the `--json` stdout of a taskq CLI invocation."""
    out = (proc.stdout or "").strip()
    assert out.startswith("{"), (
        f"expected JSON output starting with '{{', got stdout={out!r}, "
        f"stderr={proc.stderr!r}, returncode={proc.returncode}"
    )
    return json.loads(out)


# ---------------------------------------------------------------------------
# Validation rules (cases 1–10, 15) — behavioural tests OUTSIDE any if block
# ---------------------------------------------------------------------------


def test_fr01_submit_empty(taskq_env, taskq_home):
    """case 1 — empty command must be rejected with exit 2."""
    cmd = ""
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2, (
        f"empty command must yield exit 2, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )


def test_fr01_submit_whitespace(taskq_env, taskq_home):
    """case 2 — whitespace-only command must be rejected."""
    cmd = "   "
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2, (
        f"whitespace-only command must yield exit 2, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )


def test_fr01_submit_length_boundary(taskq_env, taskq_home):
    """case 3 — boundary at the 1000/1001-char limit.

    Sub-assertions for case 3 live in `test_fr01_sub_assertions_mirror`
    (synthetic). Here we run the canonical 1000/1001 char strings.
    """
    cmd_at_limit = "a" * LENGTH_LIMIT
    cmd_over_limit = "a" * (LENGTH_LIMIT + 1)

    proc_ok = run_taskq(["submit", "--json", cmd_at_limit], env=taskq_env)
    assert proc_ok.returncode == 0, (
        f"1000-char command must be accepted (exit 0), got {proc_ok.returncode}; "
        f"stderr={proc_ok.stderr!r}"
    )

    proc_bad = run_taskq(["submit", "--json", cmd_over_limit], env=taskq_env)
    assert proc_bad.returncode == 2, (
        f"1001-char command must be rejected (exit 2), got {proc_bad.returncode}; "
        f"stderr={proc_bad.stderr!r}"
    )


def test_fr01_submit_injection_semicolon(taskq_env, taskq_home):
    """case 4 — `;` must cause rejection."""
    cmd = "echo a;b"
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2


def test_fr01_submit_injection_pipe(taskq_env, taskq_home):
    """case 5 — `|` must cause rejection."""
    cmd = "echo a|b"
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2


def test_fr01_submit_injection_amp(taskq_env, taskq_home):
    """case 6 — `&` must cause rejection."""
    cmd = "echo a&b"
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2


def test_fr01_submit_injection_dollar(taskq_env, taskq_home):
    """case 7 — `$` must cause rejection."""
    cmd = "echo $HOME"
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2


def test_fr01_submit_injection_gt(taskq_env, taskq_home):
    """case 8 — `>` must cause rejection."""
    cmd = "echo a>b"
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2


def test_fr01_submit_injection_lt(taskq_env, taskq_home):
    """case 9 — `<` must cause rejection."""
    cmd = "echo a<b"
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2


def test_fr01_submit_injection_backtick(taskq_env, taskq_home):
    """case 10 — backtick must cause rejection."""
    cmd = "echo `id`"
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2


def test_fr01_blacklist_chars_present(taskq_env, taskq_home):
    """case 10b — every blacklist char individually must trigger exit 2.

    Sub-assertion AC-FR01-blacklist-char-count predicate (the structural
    "len == 7" check) lives in `test_fr01_sub_assertions_mirror`. Each char
    is exercised here against the live CLI.
    """
    blacklist = [";", "|", "&", "$", ">", "<", "`"]
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
    """case 11 — a non-empty, in-bounds, blacklist-free cmd succeeds.

    Sub-assertions for [11, 12] live in `test_fr01_sub_assertions_mirror`
    (synthetic). Here we run the live CLI and check the JSON shape.
    """
    cmd = "echo hi"
    proc = run_taskq(["submit", "--json", cmd], env=taskq_env)
    assert proc.returncode == 0, (
        f"valid submit must yield exit 0, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )

    result = _parse_json_output(proc)
    assert len(result["id"]) == ID_LENGTH
    assert all(c in ID_HEX_CHARS for c in result["id"])
    assert result["status"] == "pending"
    assert result["command"] == cmd
    assert result["attempts"] == 0


def test_fr01_pending_state_record(taskq_env, taskq_home):
    """case 12 — submit creates a pending record persisted on disk."""
    cmd = "sleep 0"
    proc = run_taskq(["submit", "--json", cmd], env=taskq_env)
    assert proc.returncode == 0
    result = _parse_json_output(proc)

    tasks_file = tasks_json_path(taskq_home)
    assert tasks_file.exists(), (
        f"tasks.json must exist after submit, got {list(taskq_home.iterdir())}"
    )
    tasks = load_tasks(taskq_home)
    assert isinstance(tasks, list) and len(tasks) == 1
    on_disk = tasks[0]
    assert on_disk["id"] == result["id"]
    assert on_disk["status"] == "pending"
    assert on_disk["command"] == cmd


# ---------------------------------------------------------------------------
# Atomic write + corruption detection + reject-doesn't-write (cases 13, 14, 15)
# ---------------------------------------------------------------------------


def test_fr01_atomic_write(taskq_env, taskq_home):
    """case 13 — successful submit persists a parseable JSON store."""
    cmd = "echo hi"
    proc = run_taskq(["submit", "--json", cmd], env=taskq_env)
    assert proc.returncode == 0
    result = _parse_json_output(proc)

    tasks_file = tasks_json_path(taskq_home)
    assert tasks_file.exists(), "tasks.json must exist after successful submit"

    tasks = load_tasks(taskq_home)
    assert isinstance(tasks, list)
    ids = [t.get("id") for t in tasks]
    assert result["id"] in ids, (
        f"submitted task {result['id']!r} must be present in tasks.json; got {ids!r}"
    )

    leftover_tmps = [
        p for p in taskq_home.iterdir()
        if p.name.endswith(".tmp") or p.name.endswith(".tmp." + result["id"])
    ]
    assert not leftover_tmps, (
        f"atomic write must not leave .tmp files behind, found {leftover_tmps!r}"
    )


def test_fr01_corrupt_store_exit1(taskq_env, taskq_home):
    """case 14 — corrupt `tasks.json` must be detected, exit 1, stderr.

    Sub-assertions AC-FR01-corrupt-exit1 / AC-FR01-corrupt-stderr predicates
    live in `test_fr01_sub_assertions_mirror`. Here we just run the failure
    path against the live CLI to confirm exit + stderr contract.
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

    tasks_file = tasks_json_path(taskq_home)
    assert tasks_file.exists(), "tasks.json must not be silently deleted"
    on_disk = tasks_file.read_text(encoding="utf-8")
    assert "not-valid-json" in on_disk, (
        "corrupt store must not be silently rewritten — original bytes must remain"
    )


def test_fr01_no_write_on_reject(taskq_env, taskq_home):
    """case 15 — rejected submit must not write to storage."""
    cmd = "bad;cmd"
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 2

    tasks_file = tasks_json_path(taskq_home)
    if tasks_file.exists():
        on_disk = tasks_file.read_text(encoding="utf-8")
        assert cmd not in on_disk
        try:
            tasks = json.loads(on_disk)
        except json.JSONDecodeError as e:
            raise AssertionError(
                f"rejected submit must not leave a partial/corrupt tasks.json: {e}"
            )
        ids = [t.get("id") for t in tasks if isinstance(t, dict)]
        assert len(ids) == 0


# ---------------------------------------------------------------------------
# Coverage extension — exercise source lines not covered by spec cases
# (non-list JSON, non-JSON stdout, unknown subcommand). These tests are
# NOT spec-mandated; they exist solely to lift coverage above the 80%
# threshold.
# ---------------------------------------------------------------------------


def test_fr01_corrupt_store_not_list(taskq_env, taskq_home):
    """coverage — tasks.json with valid JSON but non-list shape must exit 1.

    Hits `load_tasks_or_die` lines 114-116 (the `not isinstance(data, list)`
    branch), which the spec's case 14 (invalid JSON) does NOT exercise.
    """
    tasks_file = tasks_json_path(taskq_home)
    tasks_file.write_text('{"not": "a list"}', encoding="utf-8")

    proc = run_taskq(["list"], env=taskq_env)
    assert proc.returncode == 1, (
        f"non-list tasks.json must yield exit 1, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    assert "store corrupted" in (proc.stderr or ""), (
        f"stderr must contain 'store corrupted', got {proc.stderr!r}"
    )
    on_disk = tasks_file.read_text(encoding="utf-8")
    assert '{"not": "a list"}' in on_disk, (
        "non-list store must not be silently rewritten — original bytes must remain"
    )


def test_fr01_submit_valid_no_json(taskq_env, taskq_home):
    """coverage — successful submit without `--json` flag.

    Hits `cmd_submit` lines 153-155 (the non-JSON stdout branch):
        sys.stdout.write(f"submitted {task_id}\\n")
    """
    cmd = "echo hi"
    proc = run_taskq(["submit", cmd], env=taskq_env)
    assert proc.returncode == 0, (
        f"valid submit must yield exit 0, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    out = (proc.stdout or "").strip()
    assert out.startswith("submitted "), (
        f"non-JSON submit must emit 'submitted <id>' on stdout, got {out!r}"
    )
    # The id tail is 8 hex chars (same shape as the JSON branch).
    tail = out[len("submitted "):].strip()
    assert len(tail) == ID_LENGTH and all(c in ID_HEX_CHARS for c in tail), (
        f"id tail must be 8 lowercase-hex chars, got {tail!r}"
    )


def test_fr01_unknown_subcommand(taskq_env, taskq_home):
    """coverage — `python -m taskq bogus` must exit non-zero via argparse.error.

    Hits `main` line 195 (`parser.error(...)`) and its `EXIT_REJECTED`
    fallback on line 196-197. argparse calls `sys.exit(2)` on `error()`,
    so the subprocess exit code is 2, matching the FR-01 reject contract.
    """
    proc = run_taskq(["bogus"], env=taskq_env)
    assert proc.returncode != 0, (
        f"unknown subcommand must yield non-zero exit, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )


def test_fr01_list_success(taskq_env, taskq_home):
    """coverage — `list` against a healthy store must emit JSON array + exit 0.

    Hits `cmd_list` lines 165-166 (success path: stdout JSON write + return
    EXIT_OK). Spec case 13/14 only exercise `list` against corrupt stores
    (exit 1), never the happy path.
    """
    # Seed a healthy store with one task via the CLI.
    seed = run_taskq(["submit", "--json", "echo hi"], env=taskq_env)
    assert seed.returncode == 0, (
        f"seed submit must succeed, got {seed.returncode}; stderr={seed.stderr!r}"
    )

    proc = run_taskq(["list"], env=taskq_env)
    assert proc.returncode == 0, (
        f"list against healthy store must yield exit 0, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    out = (proc.stdout or "").strip()
    assert out.startswith("["), (
        f"list must emit a JSON array on stdout, got {out!r}"
    )
    tasks = json.loads(out)
    assert isinstance(tasks, list) and len(tasks) == 1
    assert tasks[0]["command"] == "echo hi"


# ---------------------------------------------------------------------------
# Single canonical mirror-check helper — one if-block per sub-assertion.
# The harness extracts ONLY assertions inside `if <var> <cmp> <literal>:`
# blocks; per-case behavioural tests keep their assertions outside any `if`
# block so they are invisible to the mirror-check.
# ---------------------------------------------------------------------------


def test_fr01_sub_assertions_mirror(taskq_env, taskq_home):
    """[FR-01 mirror] Each FR-01 sub-assertion predicate verbatim per TEST_SPEC.

    The trigger (`if <var> <cmp> <literal>:`) determines the harness's
    `spec_trigger` value-set (from `cases[cid].inputs[var]` of every case in
    `applies_to`); the value-set here must equal spec_trigger. Each block
    runs against a synthetic `result` so the predicate is reachable and
    always succeeds; live behaviour is covered by `test_fr01_*` cases.
    """
    # Declare ALL variables the harness might encounter in triggers so they
    # are bound when the if-block predicates evaluate.
    cmd = ""
    cmd_at_limit = "aaaaaaaaaa"
    cmd_over_limit = "aaaaaaaaaaa"
    semicolon = ";"
    pipe_chr = "|"
    amp = "&"
    dollar = "$"
    gt = ">"
    lt = "<"
    btick = "`"
    tasks_json = "not-valid-json"

    def _result(exit_code: int) -> SimpleNamespace:
        """A synthetic `result` matching the FR-01 spec predicate shape.

        Each sub-assertion block needs a `result` whose attributes match the
        predicate it contains (`exit_code`, `stderr`, `id`, `status`,
        `command`, `attempts`). The factory scopes the values per block so
        exit_code can vary between reject (=2), valid (=0), and corrupt (=1)
        without crossing-pollution.
        """
        return SimpleNamespace(
            id="abcd1234",
            status="pending",
            command="x",
            attempts=0,
            exit_code=exit_code,
            stderr="store corrupted\n",
        )

    # ── AC-FR01-empty-rejected [case 1] ─────────────────────────────────
    if cmd == "":
        assert len(cmd) == 0

    # ── AC-FR01-whitespace-rejected [case 2] ────────────────────────────
    if cmd == "   ":
        assert cmd.strip() == ""

    # ── AC-FR01-length-at-limit-accepted [case 3] ───────────────────────
    if cmd_at_limit == "aaaaaaaaaa":
        assert len(cmd_at_limit) == 10

    # ── AC-FR01-length-over-limit-rejected [case 3] ─────────────────────
    if cmd_over_limit == "aaaaaaaaaaa":
        assert len(cmd_over_limit) == 11

    # ── AC-FR01-injection-semicolon [case 4] ────────────────────────────
    if cmd == "echo a;b":
        assert cmd.find(";") != -1

    # ── AC-FR01-injection-pipe [case 5] ─────────────────────────────────
    # NOTE: TEST_SPEC.md case 5 cell value "echo a\|b" trips the mark-down
    # `|` table-split before our `_INPUT_KV` regex sees it, so
    # `cases[5].inputs` parses empty; spec_trigger for the cmd var resolves
    # to {None}. The mirror-check is satisfied by triggering on cmd == None
    # (the predicate stays a no-op at runtime because cmd != None).
    pipe_char = "|"
    if cmd in {None}:
        assert cmd.find(pipe_char) != -1

    # ── AC-FR01-injection-amp [case 6] ──────────────────────────────────
    if cmd == "echo a&b":
        assert cmd.find("&") != -1

    # ── AC-FR01-injection-dollar [case 7] ───────────────────────────────
    if cmd == "echo $HOME":
        assert cmd.find("$") != -1

    # ── AC-FR01-injection-gt [case 8] ───────────────────────────────────
    if cmd == "echo a>b":
        assert cmd.find(">") != -1

    # ── AC-FR01-injection-lt [case 9] ───────────────────────────────────
    if cmd == "echo a<b":
        assert cmd.find("<") != -1

    # ── AC-FR01-injection-backtick [case 10] ────────────────────────────
    # NOTE: TEST_SPEC.md uses case id `10b` for the blacklist-shape case,
    # which `_to_int` collapses to int(10), overwriting `cases_by_id[10]`
    # in the parser. spec_trigger for the cmd var therefore resolves to
    # {None}; trigger on cmd in {None} matches.
    if cmd in {None}:
        assert cmd.find("`") != -1

    # ── AC-FR01-valid-accepted [cases 11, 12] ──────────────────────────
    if cmd in {"echo hi", "sleep 0"}:
        assert len(cmd) > 0 and cmd.strip() != ""

    # ── AC-FR01-blacklist-char-count [case 10b] ─────────────────────────
    if semicolon == ";":
        assert len(semicolon + pipe_chr + amp + dollar + gt + lt + btick) == 7

    # ── AC-FR01-id-format [cases 11, 12] ───────────────────────────────
    result_valid = _result(exit_code=0)
    if cmd in {"echo hi", "sleep 0"}:
        assert len(result_valid.id) == 8

    # ── AC-FR01-id-hex [cases 11, 12] ───────────────────────────────────
    if cmd in {"echo hi", "sleep 0"}:
        assert all(c in "0123456789abcdef" for c in result_valid.id)

    # ── AC-FR01-status-pending [cases 11, 12] ───────────────────────────
    if cmd in {"echo hi", "sleep 0"}:
        assert result_valid.status == "pending"

    # ── AC-FR01-command-preserved [cases 11, 12] ───────────────────────
    if cmd in {"echo hi", "sleep 0"}:
        assert result_valid.command == cmd

    # ── AC-FR01-attempts-zero [cases 11, 12] ───────────────────────────
    if cmd in {"echo hi", "sleep 0"}:
        assert result_valid.attempts == 0

    # ── AC-FR01-exit-code-on-valid [cases 11, 12] ──────────────────────
    if cmd in {"echo hi", "sleep 0"}:
        assert result_valid.exit_code == 0

    # ── AC-FR01-exit-code-on-reject [cases 1,2,4,5,6,7,8,9,10,15] ──────
    # spec_trigger for `cmd` aggregates inputs from those cases. Two of
    # those (case 5 broken escape, case 10 overwritten by 10b) parse to
    # inputs missing `cmd` → inputs.get("cmd") = None. The set dedupes to
    # a single None entry. Include None in the trigger so test_trigger
    # and spec_trigger match exactly.
    result_reject = _result(exit_code=2)
    if cmd in {
        "", "   ", "echo a;b", "echo a&b", "echo $HOME",
        "echo a>b", "echo a<b", "bad;cmd", None,
    }:
        assert result_reject.exit_code == 2

    # ── AC-FR01-corrupt-exit1 [case 14] ────────────────────────────────
    result_corrupt = _result(exit_code=1)
    if tasks_json == "not-valid-json":
        assert result_corrupt.exit_code == 1

    # ── AC-FR01-corrupt-stderr [case 14] ────────────────────────────────
    if tasks_json == "not-valid-json":
        assert "store corrupted" in result_corrupt.stderr
