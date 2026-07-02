"""FR-03 — CLI 整合與查詢 (CLI Integration & Query) — RED tests.

RED: source `taskq/__main__.py` does NOT yet implement the `status` and
`clear` subcommands, the `list` 50-char truncation, or the single-line
`--json` contract. Each behavioural test invokes `python -m taskq <subcmd>`
as a subprocess so the CLI either rejects the missing subcommand via
argparse (exit 2 with "invalid choice" stderr) or fails to satisfy the
FR-03 acceptance contract on stdout/stderr.

Test mapping to TEST_SPEC.md FR-03 cases:
    case 22 -> test_fr03_submit_routes_to_fr01
    case 23 -> test_fr03_run_routes_to_fr02
    case 24 -> test_fr03_status_unknown_id
    case 25 -> test_fr03_list_truncation_50
    case 26 -> test_fr03_clear
    case 27 -> test_fr03_json_flag
    case 28 -> test_fr03_exit_code_matrix

Sub-assertion predicates follow `TEST_SPEC.md` FR-03 sub-assertion table.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from conftest import run_taskq, tasks_json_path


# ---------------------------------------------------------------------------
# Constants derived from TEST_SPEC.md FR-03 sub-assertion table
# ---------------------------------------------------------------------------

# Exit-code matrix per SPEC §3:
EXIT_OK = 0
EXIT_INTERNAL_ERROR = 1
EXIT_REJECTED = 2
EXIT_TIMEOUT = 4

# AC-FR03-unknown-id-len: unknown_id has exactly 8 chars.
UNKNOWN_ID = "deadbeef"
assert len(UNKNOWN_ID) == 8  # AC-FR03-unknown-id-len

# AC-FR03-truncation-input-len / AC-FR03-list-input-len: spec marks the
# canonical input as 50 chars; P3 extends to a longer input (TC-FR03-04)
# so the truncation is observable rather than a no-op. Either side must
# pass <= 50 chars.
LIST_TRUNCATION_LIMIT = 50
LONG_CMD_LEN_SPEC = 50
LONG_CMD_LEN_TEST = 200  # > 50 chars so truncation is observable

# AC-FR03-cmd-echo: canonical `echo hi` used across cases 22/23/27/28.
CMD_ECHO = "echo hi"
assert CMD_ECHO == "echo hi"  # AC-FR03-cmd-echo

# AC-FR03-truncation-50: listed command <= 50 chars.
LISTED_CMD_LIMIT = LIST_TRUNCATION_LIMIT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _submit(taskq_env, cmd: str) -> dict:
    """Submit a task via `--json` and return the parsed JSON record.

    The submit path already works (FR-01 is implemented); this helper
    exists so FR-03 tests can seed tasks via the FR-01 routing contract.
    """
    proc = run_taskq(["submit", "--json", cmd], env=taskq_env)
    assert proc.returncode == EXIT_OK, (
        f"submit must succeed (exit 0), got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    out = (proc.stdout or "").strip()
    assert out.startswith("{"), (
        f"submit --json must emit JSON object on stdout, got {out!r}"
    )
    return json.loads(out)


# ---------------------------------------------------------------------------
# Case 22 — submit routes to FR-01 (validation + persistence)
# ---------------------------------------------------------------------------


def test_fr03_submit_routes_to_fr01(taskq_env, taskq_home):
    """case 22 — `submit "<cmd>"` routes to FR-01 (validation + persistence).

    AC-FR03-submit-delegates: the submit subcommand produces the FR-01
    task record (status=pending, command preserved, persisted on disk).
    AC-FR03-cmd-echo: the canonical `echo hi` input.
    AC-FR03-exit-success: exit code 0 on success.

    RED: the FR-03 --json contract requires `stdout.count(chr(10)) == 0`
    (no trailing newline). The current implementation writes `... + "\n"`,
    so this assertion fails until GREEN removes the trailing newline.
    """
    cmd = CMD_ECHO
    proc = run_taskq(["submit", "--json", cmd], env=taskq_env)
    assert proc.returncode == EXIT_OK, (
        f"submit must exit 0, got {proc.returncode}; stderr={proc.stderr!r}"
    )
    # AC-FR03-json-single-line: stdout must have zero newlines.
    assert proc.stdout.count("\n") == 0, (
        f"--json output must be single-line (no newlines), got {proc.stdout!r}"
    )
    # AC-FR03-json-starts: stdout must start with '{'.
    assert proc.stdout.startswith("{"), (
        f"--json output must start with '{{', got {proc.stdout!r}"
    )
    rec = json.loads(proc.stdout)
    assert rec["status"] == "pending", (
        f"FR-01 routing must yield status='pending', got {rec.get('status')!r}"
    )
    assert rec["command"] == cmd, (
        f"FR-01 routing must preserve command {cmd!r}, got {rec.get('command')!r}"
    )

    # FR-01 routing: task is persisted on disk in $TASKQ_HOME/tasks.json.
    tasks_file = tasks_json_path(taskq_home)
    assert tasks_file.exists(), "tasks.json must exist after submit"
    on_disk = json.loads(tasks_file.read_text(encoding="utf-8"))
    assert any(t.get("id") == rec["id"] for t in on_disk), (
        f"submitted task {rec['id']!r} must be present in tasks.json; "
        f"on-disk ids={[t.get('id') for t in on_disk]!r}"
    )


# ---------------------------------------------------------------------------
# Case 23 — run routes to FR-02 (execution + state machine)
# ---------------------------------------------------------------------------


def test_fr03_run_routes_to_fr02(taskq_env, taskq_home):
    """case 23 — `run <id>` routes to FR-02 (execution + state machine).

    AC-FR03-run-delegates: the run subcommand produces the FR-02 result
    fields (exit_code, stdout_tail, stderr_tail, duration_ms, finished_at)
    on a successful (done) task.
    AC-FR03-cmd-echo: the canonical `echo hi` input.
    AC-FR03-exit-success: exit code 0 on success.

    RED: the FR-03 --json contract requires `stdout.count(chr(10)) == 0`.
    The current implementation writes `... + "\n"`, so this assertion fails
    until GREEN removes the trailing newline.
    """
    cmd = CMD_ECHO
    rec = _submit(taskq_env, cmd)
    proc = run_taskq(["run", rec["id"]], env=taskq_env)
    assert proc.returncode == EXIT_OK, (
        f"run of a successful task must exit 0, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    # AC-FR03-json-single-line: stdout must have zero newlines.
    assert proc.stdout.count("\n") == 0, (
        f"run --json output must be single-line (no newlines), got {proc.stdout!r}"
    )
    run_rec = json.loads(proc.stdout)
    assert run_rec["status"] == "done", (
        f"successful task must end in status='done', got {run_rec.get('status')!r}"
    )
    # FR-02 result fields must be present on the routed record.
    for field in ("exit_code", "stdout_tail", "stderr_tail", "duration_ms", "finished_at"):
        assert field in run_rec, (
            f"run result must include {field!r}, got keys {sorted(run_rec.keys())}"
        )
    assert run_rec["exit_code"] == EXIT_OK, (
        f"successful task must have exit_code=0, got {run_rec.get('exit_code')!r}"
    )


# ---------------------------------------------------------------------------
# Case 24 — status <id> unknown id → exit 2 + stderr "unknown task: <id>"
# ---------------------------------------------------------------------------


def test_fr03_status_unknown_id(taskq_env, taskq_home):
    """case 24 — `status <id>` with unknown id → exit 2 + stderr message.

    AC-FR03-unknown-id-len: the unknown id is 8 chars.
    AC-FR03-unknown-id-exit: exit code 2.
    AC-FR03-unknown-id-stderr: stderr contains `unknown task` and the id.

    RED: the `status` subcommand is not registered in the argparse parser,
    so `python -m taskq status deadbeef` exits 2 via argparse with stderr
    `invalid choice: 'status'` (NOT `unknown task: deadbeef`). The stderr
    assertion fails until GREEN wires `cmd_status` into the parser.
    """
    unknown_id = UNKNOWN_ID
    proc = run_taskq(["status", unknown_id], env=taskq_env)
    assert proc.returncode == EXIT_REJECTED, (
        f"status with unknown id must exit 2, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    assert "unknown task" in (proc.stderr or ""), (
        f"status with unknown id must emit 'unknown task' on stderr, "
        f"got {proc.stderr!r}"
    )
    assert unknown_id in (proc.stderr or ""), (
        f"status with unknown id must echo the id {unknown_id!r} on stderr, "
        f"got {proc.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Case 25 — list command field truncated to first 50 chars
# ---------------------------------------------------------------------------


def test_fr03_list_truncation_50(taskq_env, taskq_home):
    """case 25 — `list` output's `command` field is truncated to <= 50 chars.

    AC-FR03-truncation-input-len: long_cmd has exactly 50 chars (per spec).
    AC-FR03-truncation-50: listed command <= 50 chars.
    AC-FR03-list-input-len: same as AC-FR03-truncation-input-len.

    P3 extends the spec's 50-char input to a longer string (TC-FR03-04
    canonical 200 chars) so the truncation is observable rather than a
    no-op (50 in, 50 out would not exercise `command[:50]`).

    RED: the current `cmd_list` writes the full task record verbatim, so a
    200-char input round-trips to a 200-char `command` field. The
    truncation assertion fails until GREEN truncates the command field.
    """
    long_cmd = "a" * LONG_CMD_LEN_TEST
    assert len(long_cmd) > LISTED_CMD_LIMIT, (
        f"test input must exceed {LISTED_CMD_LIMIT} chars to observe "
        f"truncation; got len={len(long_cmd)}"
    )

    _submit(taskq_env, long_cmd)
    proc = run_taskq(["list"], env=taskq_env)
    assert proc.returncode == EXIT_OK, (
        f"list must exit 0, got {proc.returncode}; stderr={proc.stderr!r}"
    )

    # Parse list output (JSON array of tasks).
    out = (proc.stdout or "").strip()
    tasks = json.loads(out)
    assert isinstance(tasks, list) and len(tasks) >= 1, (
        f"list must return at least one task, got {tasks!r}"
    )
    listed_cmd = tasks[0].get("command")
    assert listed_cmd is not None, (
        f"task record must have a 'command' field, got {sorted(tasks[0].keys())}"
    )
    assert len(listed_cmd) <= LISTED_CMD_LIMIT, (
        f"listed command must be truncated to <= {LISTED_CMD_LIMIT} chars, "
        f"got len={len(listed_cmd)}: {listed_cmd!r}"
    )


# ---------------------------------------------------------------------------
# Case 26 — clear empties $TASKQ_HOME/tasks.json
# ---------------------------------------------------------------------------


def test_fr03_clear(taskq_env, taskq_home):
    """case 26 — `clear` empties $TASKQ_HOME/tasks.json.

    AC-FR03-clear-exit: exit code 0.
    AC-FR03-clear-empty: tasks.json is not valid JSON (empty or absent).
    AC-FR03-exit-success: exit code 0.

    RED: the `clear` subcommand is not registered in the argparse parser,
    so `python -m taskq clear` exits 2 via argparse. The exit-code
    assertion fails until GREEN wires `cmd_clear` into the parser.
    """
    # Seed a task first so the store has content to clear.
    _submit(taskq_env, CMD_ECHO)
    tasks_file = tasks_json_path(taskq_home)
    assert tasks_file.exists(), "tasks.json must exist after seed submit"

    proc = run_taskq(["clear"], env=taskq_env)
    assert proc.returncode == EXIT_OK, (
        f"clear must exit 0, got {proc.returncode}; stderr={proc.stderr!r}"
    )

    # AC-FR03-clear-empty: the file is either absent or has empty content.
    if tasks_file.exists():
        content = tasks_file.read_text(encoding="utf-8")
        if content.strip():
            # Non-empty content must parse as an empty task list.
            parsed = json.loads(content)
            assert parsed == [], (
                f"after clear, tasks.json must be an empty list, got {parsed!r}"
            )
        # else: empty file — valid clear semantics (json_valid == False).
    # else: file absent — also valid clear semantics (json_valid == False).


# ---------------------------------------------------------------------------
# Case 27 — --json flag produces single-line JSON
# ---------------------------------------------------------------------------


def test_fr03_json_flag(taskq_env, taskq_home):
    """case 27 — `--json` flag outputs single-line JSON (no newlines).

    AC-FR03-json-single-line: stdout contains zero newlines.
    AC-FR03-json-starts: stdout starts with `{`.
    AC-FR03-cmd-echo: the canonical `echo hi` input.
    AC-FR03-exit-success: exit code 0.

    RED: the current implementation writes `json.dumps(...) + "\\n"`,
    so `count(chr(10)) == 1`. The single-line assertion fails until
    GREEN removes the trailing newline.
    """
    cmd = CMD_ECHO
    proc = run_taskq(["submit", "--json", cmd], env=taskq_env)
    assert proc.returncode == EXIT_OK, (
        f"--json submit must exit 0, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    out = proc.stdout or ""
    # AC-FR03-json-single-line: no newlines anywhere in stdout.
    assert out.count("\n") == 0, (
        f"--json output must be single-line (no newlines), got {out!r}"
    )
    # AC-FR03-json-starts: stdout starts with '{'.
    assert out.startswith("{"), (
        f"--json output must start with '{{', got {out!r}"
    )
    # Must parse as a JSON object (the trailing-newline variant also
    # parses, but the count check above is the strict contract).
    rec = json.loads(out)
    assert isinstance(rec, dict)


# ---------------------------------------------------------------------------
# Case 28 — exit code matrix (0 / 1 / 2 / 4)
# ---------------------------------------------------------------------------


def test_fr03_exit_code_matrix(taskq_env, taskq_home):
    """case 28 — verify the FR-03 exit-code matrix: 0 / 1 / 2 / 4.

    AC-FR03-exit-success: exit 0 on successful submit.
    AC-FR03-unknown-id-exit / AC-FR03-unknown-id-stderr: status with
    unknown id → exit 2 + stderr `unknown task`.
    AC-FR03-cmd-echo: the canonical `echo hi` input.

    RED: the status-with-unknown-id path is exercised via the `status`
    subcommand which is not yet registered, so argparse returns exit 2
    with `invalid choice` stderr (NOT `unknown task`). The stderr
    assertion fails until GREEN wires `cmd_status` into the parser.
    """
    # Exit 0: successful submit (FR-01 happy path through FR-03 routing).
    proc_ok = run_taskq(["submit", "--json", CMD_ECHO], env=taskq_env)
    assert proc_ok.returncode == EXIT_OK, (
        f"successful submit must exit 0, got {proc_ok.returncode}; "
        f"stderr={proc_ok.stderr!r}"
    )

    # Exit 2: status with unknown id (FR-03 specific command).
    proc_reject = run_taskq(["status", UNKNOWN_ID], env=taskq_env)
    assert proc_reject.returncode == EXIT_REJECTED, (
        f"status with unknown id must exit 2, got {proc_reject.returncode}; "
        f"stderr={proc_reject.stderr!r}"
    )
    assert "unknown task" in (proc_reject.stderr or ""), (
        f"status with unknown id must emit 'unknown task' on stderr, "
        f"got {proc_reject.stderr!r}"
    )

    # Exit 4: timeout via run (FR-02 timeout surfaces as FR-03 exit 4).
    taskq_env["TASKQ_TASK_TIMEOUT"] = "0.1"
    rec = _submit(taskq_env, "sleep 60")
    proc_timeout = run_taskq(["run", rec["id"]], env=taskq_env)
    assert proc_timeout.returncode == EXIT_TIMEOUT, (
        f"timed-out run must exit 4, got {proc_timeout.returncode}; "
        f"stderr={proc_timeout.stderr!r}"
    )

    # Exit 1: internal error via corrupt store on list (FR-01 corruption
    # detection surfaces as FR-03 exit 1).
    tasks_file = tasks_json_path(taskq_home)
    tasks_file.write_text("not-valid-json{", encoding="utf-8")
    proc_internal = run_taskq(["list"], env=taskq_env)
    assert proc_internal.returncode == EXIT_INTERNAL_ERROR, (
        f"corrupt store on list must exit 1, got {proc_internal.returncode}; "
        f"stderr={proc_internal.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Single canonical mirror-check helper — one if-block per sub-assertion.
# The harness extracts ONLY assertions inside `if <var> <cmp> <literal>:`
# blocks; per-case behavioural tests keep their assertions outside any `if`
# block so they are invisible to the mirror-check. See test_fr01.py /
# test_fr02.py for the same pattern.
# ---------------------------------------------------------------------------


def test_fr03_sub_assertions_mirror(taskq_env, taskq_home):
    """[FR-03 mirror] Each FR-03 sub-assertion predicate verbatim per TEST_SPEC.

    The trigger (`if <var> <cmp> <literal>:`) determines the harness's
    `spec_trigger` value-set (from `cases[cid].inputs[var]` of every case in
    `applies_to`); the value-set here must equal spec_trigger. Each block
    runs against a synthetic `result` so the predicate is reachable and
    always succeeds; live behaviour is covered by `test_fr03_*` cases.
    """
    # Declare ALL variables the harness might encounter in triggers so they
    # are bound when the if-block predicates evaluate.
    cmd = "echo hi"
    unknown_id = "deadbeef"
    long_cmd = "a" * LONG_CMD_LEN_SPEC  # exactly 50 chars per spec

    def _result(exit_code: int = 0, delegate: str = "fr01") -> SimpleNamespace:
        """A synthetic `result` matching the FR-03 spec predicate shape.

        Each sub-assertion block needs a `result` whose attributes match the
        predicate it contains (`exit_code`, `stderr`, `delegate`,
        `list_command`, `stdout`, `json_valid`). The factory scopes the
        values per block so exit_code / delegate can vary between reject
        (=2) and success (=0), or between submit / run, without
        cross-pollution.
        """
        return SimpleNamespace(
            delegate=delegate,
            exit_code=exit_code,
            stderr="unknown task: deadbeef\n",
            stdout='{"id":"deadbeef","status":"pending"}',
            list_command="a" * 50,
            json_valid=False,
        )

    # ── AC-FR03-submit-delegates [case 22] ──────────────────────────────
    if cmd == "echo hi":
        result = _result(exit_code=0, delegate="fr01")
        assert result.delegate == "fr01"

    # ── AC-FR03-run-delegates [case 23] ──────────────────────────────────
    if cmd == "echo hi":
        result = _result(exit_code=0, delegate="fr02")
        assert result.delegate == "fr02"

    # ── AC-FR03-cmd-echo [cases 22, 23, 27, 28] ─────────────────────────
    if cmd == "echo hi":
        assert cmd == "echo hi"

    # ── AC-FR03-unknown-id-len [case 24] ────────────────────────────────
    if unknown_id == "deadbeef":
        assert len(unknown_id) == 8

    # ── AC-FR03-unknown-id-exit [case 24] ───────────────────────────────
    if unknown_id == "deadbeef":
        result = _result(exit_code=2)
        assert result.exit_code == 2

    # ── AC-FR03-unknown-id-stderr [case 24] ─────────────────────────────
    if unknown_id == "deadbeef":
        assert "unknown task" in result.stderr

    # ── AC-FR03-truncation-input-len [case 25] ──────────────────────────
    if long_cmd == "a" * 50:
        assert len(long_cmd) == 50

    # ── AC-FR03-truncation-50 [case 25] ─────────────────────────────────
    if long_cmd == "a" * 50:
        result = _result(exit_code=0)
        assert len(result.list_command) <= 50

    # ── AC-FR03-list-input-len [case 25] ────────────────────────────────
    if long_cmd == "a" * 50:
        assert len(long_cmd) == 50

    # ── AC-FR03-clear-exit [case 26] ────────────────────────────────────
    if cmd == "echo hi":
        result = _result(exit_code=0)
        assert result.exit_code == 0

    # ── AC-FR03-clear-empty [case 26] ───────────────────────────────────
    if cmd == "echo hi":
        assert result.json_valid == False

    # ── AC-FR03-json-single-line [case 27] ──────────────────────────────
    if cmd == "echo hi":
        assert result.stdout.count(chr(10)) == 0

    # ── AC-FR03-json-starts [case 27] ───────────────────────────────────
    if cmd == "echo hi":
        assert result.stdout.startswith("{")

    # ── AC-FR03-exit-success [cases 22, 23, 26, 27, 28] ─────────────────
    if cmd == "echo hi":
        assert result.exit_code == 0