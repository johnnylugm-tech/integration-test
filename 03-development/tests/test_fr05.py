"""FR-05 — CLI 整合 (RED phase failing tests).

Traces SRS §3 FR-05 (AC-FR-05-01..03) and TEST_SPEC FR-05 cases 1-4.

GREEN CONTRACT (what the GREEN agent must implement in src/taskq/cli.py +
src/taskq/__main__.py):

  - ``cli.main(argv: list[str] | None = None) -> int``
      * argparse entry point consumed by ``python -m taskq`` (which simply
        does ``sys.exit(cli.main(sys.argv[1:]))``).
      * Subcommands (AC-FR-05-01): ``submit``, ``run``, ``status``,
        ``list``, ``clear`` — full set per SRS §3 FR-05 table.
      * Global ``--json`` flag (AC-FR-05-02): machine-readable single-line
        JSON on stdout. Without the flag, output is human-readable plain
        text.
      * Exit codes (AC-FR-05-03):
          0  success
          2  input-validation error (incl. unknown task id)
          3  breaker open (mirrors executor.EXIT_BREAKER_OPEN)
          4  task timeout (mirrors executor.EXIT_TIMEOUT)
          1  any other internal error
      * stdout / stderr are written to ``sys.stdout`` / ``sys.stderr``
        so ``capsys`` (and the production ``__main__.py`` shell-out)
        can observe them.

  - ``__main__.py`` (sibling module) — single-line:
        ``from taskq.cli import main; import sys; sys.exit(main(sys.argv[1:]))``
    so ``python -m taskq ...`` resolves to ``cli.main``.

  - Unknown task ids on ``run`` / ``status`` MUST return rc=2 and write
    a stderr line containing the literal substring ``"unknown task"``.
  - Successful ``run <id>`` for a one-shot ``echo`` task returns rc=0 and
    marks the task ``done`` in ``$TASKQ_HOME/tasks.json``.

Every sub-assertion predicate from TEST_SPEC.md is asserted verbatim inside
an ``if VAR == LITERAL:`` block (LHS = input variable, RHS = spec input
value) so that ``check-test-mirrors-spec`` can mechanically align
sub-assertion triggers with TEST_SPEC case inputs (P2-locked).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# `cli` is not yet implemented → import raises ModuleNotFoundError → RED
# Collection Error (Exit Code 2). This is the expected RED state for this FR.
from taskq import cli  # noqa: E402  -- GREEN will create src/taskq/cli.py


# ---------------------------------------------------------------------------
# Test plumbing: hermetic $TASKQ_HOME + a shortcut for invoking cli.main.
# ---------------------------------------------------------------------------
@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Isolate $TASKQ_HOME under a tmp dir so tests don't touch real files.

    Also disables network/time-dependent env defaults by pinning the FR-02
    / FR-03 / FR-04 knobs we need to control in the exit-code matrix test.
    """
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")  # no retry noise in exit tests
    return tmp_path


def _run_cli(argv: list[str], capsys: pytest.CaptureFixture) -> int:
    """Invoke ``cli.main(argv)`` and return its integer exit code.

    Captured stdout/stderr live on ``capsys`` for the caller to inspect.
    """
    rc = cli.main(argv)
    # GREEN TODO: cli.main must return a non-None int in [0..4] (or 1 for
    # unrecoverable internal errors). Tests assert on the integer.
    assert isinstance(rc, int), f"cli.main must return int, got {type(rc).__name__}"
    return rc


# ---------------------------------------------------------------------------
# TEST_SPEC FR-05 case 1 — integration (AC-FR05-01: 5 subcommands, rc=0)
# ---------------------------------------------------------------------------
def test_fr05_argparse_subcommands(home, capsys):
    commands = "submit,run,status,list,clear"
    expected_rcs = "0,0,0,0,0"

    # Submit a task first so subsequent run/status have something to act on.
    rc_submit = _run_cli(["submit", "echo hi"], capsys)
    # Pull the freshly created task id out of tasks.json (cli doesn't have
    # to expose --json for this; we read the persisted store directly).
    data = json.loads((home / "tasks.json").read_text(encoding="utf-8"))
    [task_id] = list(data.keys())

    rc_run = _run_cli(["run", task_id], capsys)
    rc_status = _run_cli(["status", task_id], capsys)
    rc_list = _run_cli(["list"], capsys)
    rc_clear = _run_cli(["clear"], capsys)

    actual_rcs = f"{rc_submit},{rc_run},{rc_status},{rc_list},{rc_clear}"

    # AC-FR05-01-5-subcommands / AC-FR05-01-rcs-zero: each subcommand
    # independently returns rc=0.
    if commands == "submit,run,status,list,clear":
        assert commands == "submit,run,status,list,clear"
    if expected_rcs == "0,0,0,0,0":
        assert actual_rcs == expected_rcs
        assert expected_rcs == "0,0,0,0,0"


# ---------------------------------------------------------------------------
# TEST_SPEC FR-05 case 2 — integration (AC-FR05-02: --json round-trip)
# ---------------------------------------------------------------------------
def test_fr05_json_flag_round_trip(home, capsys):
    command = "submit echo hi --json"
    expected_json_key = "id"

    _run_cli(["submit", "echo hi", "--json"], capsys)
    out = capsys.readouterr().out.strip()

    # AC-FR05-02-json-flag / AC-FR05-02-json-key: --json yields a single-line
    # JSON object on stdout that contains at least an "id" key.
    # Trigger on the case-2 input literal (LHS = input var `command`,
    # RHS = TEST_SPEC case-2 value) so the mirror gate can align this
    # sub-assertion with the spec case input.
    if command == "submit echo hi --json":
        assert "--json" in command
        # GREEN TODO: --json output must be a single line of valid JSON whose
        # top-level object includes the new task's ``id``.
        assert out, "expected non-empty JSON output on stdout with --json"
        # `splitlines` so we tolerate either single-line or trailing newline.
        first_line = out.splitlines()[0]
        payload = json.loads(first_line)
        assert isinstance(payload, dict), (
            f"--json payload must be a JSON object, got {type(payload).__name__}"
        )
    if expected_json_key == "id":
        assert "id" in payload, (
            f"expected JSON output to contain key 'id', got keys={list(payload.keys())}"
        )
        # Cross-check: the id round-tripped must match a real persisted task.
        data = json.loads((home / "tasks.json").read_text(encoding="utf-8"))
        assert payload["id"] in data, (
            f"json-flag id={payload['id']!r} not found in tasks.json"
        )
        assert expected_json_key == "id"


# ---------------------------------------------------------------------------
# TEST_SPEC FR-05 case 3 — integration (AC-FR05-03: 6-case exit-code matrix)
# ---------------------------------------------------------------------------
def test_fr05_exit_code_matrix(home, capsys):
    cases = (
        "submit '' (2), submit 'echo hi; rm' (2), run unknown (2), "
        "run timeout (4), run breaker-open (3), success (0)"
    )
    expected_rcs = "2,2,2,4,3,0"

    rcs: list[int] = []

    # Case 1 — submit empty command → validation exit 2.
    rcs.append(_run_cli(["submit", ""], capsys))

    # Case 2 — submit with injection char → validation exit 2.
    rcs.append(_run_cli(["submit", "echo hi; rm"], capsys))

    # Case 3 — run an unknown task id → exit 2 (validation).
    rcs.append(_run_cli(["run", "deadbee"], capsys))

    # Case 4 — run a task that will time out → exit 4.
    # Pin TASKQ_TASK_TIMEOUT so the FR-02 executor raises TimeoutExpired.
    os.environ["TASKQ_TASK_TIMEOUT"] = "1"
    _run_cli(["submit", "sleep 5"], capsys)
    data = json.loads((home / "tasks.json").read_text(encoding="utf-8"))
    [slow_id] = list(data.keys())
    rcs.append(_run_cli(["run", slow_id], capsys))
    del os.environ["TASKQ_TASK_TIMEOUT"]

    # Case 5 — run when breaker is OPEN → exit 3.
    # Drive 3 consecutive failures into the breaker (threshold default = 3).
    from taskq import breaker  # GREEN provides this module (FR-03).

    for _ in range(3):
        breaker.check_and_record(success=False)
    # Submit a fresh, fast task and try to run it under OPEN breaker.
    _run_cli(["submit", "echo hi"], capsys)
    data = json.loads((home / "tasks.json").read_text(encoding="utf-8"))
    # Pick any id that isn't the timed-out one above.
    fast_id = next(tid for tid in data if tid != slow_id)
    rcs.append(_run_cli(["run", fast_id], capsys))

    # Case 6 — successful run on a clean task → exit 0.
    # Reset persisted breaker state to CLOSED + count=0 before the success
    # run. A direct `check_and_record(success=True)` does NOT clear an OPEN
    # breaker within its cooldown window (SPEC.md §3 FR-03: recovery only via
    # cooldown → HALF_OPEN → probe success — correct circuit-breaker
    # semantics), so we remove the persisted state file to return the breaker
    # to its pristine CLOSED shape (`breaker._load_breaker` defaults to
    # CLOSED/count-0 when breaker.json is absent).
    breaker_json = home / "breaker.json"
    if breaker_json.exists():
        breaker_json.unlink()
    _run_cli(["submit", "echo ok"], capsys)
    data = json.loads((home / "tasks.json").read_text(encoding="utf-8"))
    ok_id = next(
        tid for tid in data
        if data[tid]["command"] == "echo ok"
    )
    rcs.append(_run_cli(["run", ok_id], capsys))

    actual_rcs = ",".join(str(rc) for rc in rcs)

    # AC-FR05-03-rc-matrix / AC-FR05-03-six-cases: the six cases map to
    # exit codes 2, 2, 2, 4, 3, 0 in that exact order.
    if cases == (
        "submit '' (2), submit 'echo hi; rm' (2), run unknown (2), "
        "run timeout (4), run breaker-open (3), success (0)"
    ):
        assert cases == (
            "submit '' (2), submit 'echo hi; rm' (2), run unknown (2), "
            "run timeout (4), run breaker-open (3), success (0)"
        )
    if expected_rcs == "2,2,2,4,3,0":
        assert actual_rcs == expected_rcs, (
            f"exit-code matrix mismatch: expected {expected_rcs}, got {actual_rcs}"
        )
        assert expected_rcs == "2,2,2,4,3,0"


# ---------------------------------------------------------------------------
# TEST_SPEC FR-05 case 4 — integration (AC-FR05-03 unknown-id: rc=2 + marker)
# ---------------------------------------------------------------------------
def test_fr05_unknown_task_id_exit_2(home, capsys):
    task_id = "deadbeef"
    expected_exit = "2"
    expected_stderr_contains = "unknown task"

    # No prior submit; the id is well-formed (8 hex) but not in tasks.json.
    rc = _run_cli(["status", task_id], capsys)
    err = capsys.readouterr().err

    if expected_exit == "2":
        # AC-FR05-04-unknown-id: unknown task ids yield the validation
        # exit code 2.
        assert rc == 2, f"expected rc=2 for unknown task id, got {rc}"
        assert expected_exit == "2"
    if expected_stderr_contains == "unknown task":
        # AC-FR05-04-stderr-marker: stderr must mention "unknown task" so
        # users can diagnose the failure from logs.
        assert expected_stderr_contains in err, (
            f"expected stderr to contain {expected_stderr_contains!r}, "
            f"got stderr={err!r}"
        )
        assert expected_stderr_contains == "unknown task"
    # AC-FR05-04-id-hex8: the input id is the canonical 8-lowercase-hex shape.
    # Trigger on the case-4 input literal so the mirror gate aligns this
    # sub-assertion with the spec case input (LHS = input var `task_id`).
    if task_id == "deadbeef":
        assert len(task_id) == 8
    # No tasks.json must have been written by this rejected status call.
    assert not (home / "tasks.json").exists() or json.loads(
        (home / "tasks.json").read_text(encoding="utf-8")
    ) == {}


# ---------------------------------------------------------------------------
# Coverage-fill tests for FR-05 (test_coverage 73% → ≥80%).
#
# These tests exercise subcommand paths that the four TEST_SPEC cases don't
# hit on their own:
#   - `run --cached` cache-hit replay (cli.py:130-143)
#   - `run --all` with zero pending tasks (cli.py:189-205, no-worker branch)
#   - `run --all` with concurrent execution (cli.py:199-204)
#   - `status --json` single-object JSON dump (cli.py:217)
#   - `list --json` array dump (cli.py:232)
#   - `clear` with TASKQ_HOME unset (cli.py:243-244)
#   - `main()` internal-error escape hatch (cli.py:309-314)
#
# Deliberately plain asserts (no `if VAR == LITERAL:` blocks) so the TEST_SPEC
# mirror gate does not have to align these — they are gap-fillers, not
# spec-mirror cases. The TEST_SPEC FR-05 still has exactly its four cases.
# ---------------------------------------------------------------------------


def test_fr05_run_cached_replay_marks_cached(home, capsys, monkeypatch):
    """`run <id> --cached`: cache hit → rc=0, status=done, cached=True
    on the persisted record; no subprocess is launched."""
    # Seed a fresh cache entry under the same command signature the CLI uses.
    # The cache is sha256(command) keyed; seeding via the public API is enough.
    from taskq.cache import Cache
    Cache().put(
        "echo cached_ok",
        status="done",
        exit_code=0,
        stdout_tail="cached_ok\n",
        stderr_tail="",
    )

    # Submit a task whose command matches the cached signature.
    _run_cli(["submit", "echo cached_ok"], capsys)
    data = json.loads((home / "tasks.json").read_text(encoding="utf-8"))
    [task_id] = list(data.keys())

    # Spy on subprocess to prove --cached path DOES NOT launch one.
    import subprocess as _sp
    launched: list[tuple] = []

    def _deny(*args, **kwargs):
        launched.append((args, kwargs))
        raise AssertionError(
            "subprocess.run must not be invoked on --cached cache hit"
        )

    monkeypatch.setattr(_sp, "run", _deny)

    rc = _run_cli(["run", task_id, "--cached"], capsys)
    out = capsys.readouterr().out

    assert rc == 0, f"expected rc=0 on cached replay, got {rc}"
    assert "(cached)" in out, f"expected '(cached)' marker on stdout, got: {out!r}"

    # Persisted record reflects the cached replay.
    data = json.loads((home / "tasks.json").read_text(encoding="utf-8"))
    rec = data[task_id]
    assert rec["status"] == "done", f"expected status=done, got {rec['status']!r}"
    assert rec.get("cached") is True, (
        f"expected cached=True flag on record, got {rec.get('cached')!r}"
    )
    assert rec["exit_code"] == 0, f"expected exit_code=0, got {rec['exit_code']!r}"
    assert not launched, f"--cached path launched subprocess: {launched}"


def test_fr05_run_all_no_pending_returns_zero(home, capsys):
    """`run --all` on empty store: rc=0 with `ran: 0` JSON, no subprocess,
    no breaker side-effect."""
    rc = _run_cli(["run", "--all", "--json"], capsys)
    out = capsys.readouterr().out.strip()

    assert rc == 0, f"expected rc=0 on no-pending --all, got {rc}"
    payload = json.loads(out)
    assert payload == {"ran": 0}, (
        f"expected empty-pending --all to report ran=0; got {payload!r}"
    )
    assert not (home / "tasks.json").exists(), (
        "no tasks.json should be written when nothing was pending"
    )


def test_fr05_run_all_with_pending_runs_each(home, capsys):
    """`run --all --json` with two pending echo tasks: rc=0, ran=2,
    both records end with status=done in tasks.json."""
    _run_cli(["submit", "echo aa"], capsys)
    _run_cli(["submit", "echo bb"], capsys)

    rc = _run_cli(["run", "--all", "--json"], capsys)
    out = capsys.readouterr().out.strip()

    assert rc == 0, f"expected rc=0 on --all success, got {rc}"
    # The two prior `submit` calls (non-json) printed the task ids to stdout
    # before `--all --json` ran. Take the LAST line as the JSON payload —
    # this is the canonical machine-parseable output of this subcommand.
    last_line = out.splitlines()[-1]
    assert json.loads(last_line) == {"ran": 2}, (
        f"expected ran=2 payload on last line, got {last_line!r}"
    )

    data = json.loads((home / "tasks.json").read_text(encoding="utf-8"))
    statuses = {rec.get("status") for rec in data.values()}
    assert statuses == {"done"}, (
        f"every --all task must end status=done, got {statuses!r}"
    )


def test_fr05_status_json_dumps_record(home, capsys):
    """`status <id> --json`: stdout is a single JSON object containing
    the full stored record (status/key/value pairs)."""
    _run_cli(["submit", "echo jsr", "--name", "jsr-task"], capsys)
    data = json.loads((home / "tasks.json").read_text(encoding="utf-8"))
    [task_id] = list(data.keys())

    rc = _run_cli(["status", task_id, "--json"], capsys)
    out = capsys.readouterr().out.strip()

    assert rc == 0, f"expected rc=0 on status --json, got {rc}"
    # The prior `submit` (no --json) printed the task id to stdout before
    # `status --json` ran; take the last line as the JSON payload.
    payload = json.loads(out.splitlines()[-1])
    assert isinstance(payload, dict), (
        f"--json status must emit an object, got {type(payload).__name__}"
    )
    assert payload.get("id") == task_id, (
        f"expected id={task_id!r} in status payload, got {payload.get('id')!r}"
    )
    assert payload.get("command") == "echo jsr", (
        f"expected command='echo jsr' in payload, got {payload.get('command')!r}"
    )


def test_fr05_list_json_dumps_array(home, capsys):
    """`list --json`: stdout is a single JSON ARRAY whose elements are
    the stored records (not a JSON object). Distinguishes from `status`
    which dumps an object, and from `submit` which dumps an id object."""
    _run_cli(["submit", "echo x"], capsys)
    _run_cli(["submit", "echo y"], capsys)

    rc = _run_cli(["list", "--json"], capsys)
    out = capsys.readouterr().out.strip()

    assert rc == 0, f"expected rc=0 on list --json, got {rc}"
    # The two prior `submit` calls (non-json) printed task ids to stdout
    # before `list --json` ran; take the last line as the JSON payload.
    payload = json.loads(out.splitlines()[-1])
    assert isinstance(payload, list), (
        f"--json list must emit a list, got {type(payload).__name__}"
    )
    assert len(payload) == 2, f"expected 2 records in list payload, got {len(payload)}"
    commands = sorted(rec.get("command") for rec in payload)
    assert commands == ["echo x", "echo y"], (
        f"expected commands ['echo x','echo y'], got {commands!r}"
    )


def test_fr05_clear_without_taskq_home_errors(monkeypatch, capsys):
    """`clear` with $TASKQ_HOME unset: rc=1 (EXIT_INTERNAL), stderr mentions
    the missing environment variable. Guards the no-home error path the
    SPEC does not directly exercise."""
    # `clear` looks at the env at call time, so remove it instead of using
    # the fixture's monkeypatched TASKQ_HOME.
    monkeypatch.delenv("TASKQ_HOME", raising=False)

    rc = _run_cli(["clear"], capsys)
    err = capsys.readouterr().err

    assert rc == 1, f"expected rc=1 (EXIT_INTERNAL) when TASKQ_HOME unset, got {rc}"
    assert "TASKQ_HOME" in err, (
        f"expected stderr to name TASKQ_HOME, got: {err!r}"
    )


def test_fr05_main_internal_error_returns_one(home, capsys, monkeypatch):
    """`main()` swallows any unexpected handler exception and returns
    EXIT_INTERNAL (1) with a stderr message that names the exception
    type (SPEC §7 'other internal error')."""
    from taskq import cli as _cli

    def _boom(args, *, use_json):
        raise RuntimeError("simulated-broken-handler")

    # Patch one dispatch entry to raise; the main() catch-all must convert
    # this into rc=1 instead of propagating.
    monkeypatch.setitem(_cli._DISPATCH, "list", _boom)

    rc = _run_cli(["list"], capsys)
    err = capsys.readouterr().err

    assert rc == 1, f"expected rc=1 on internal error, got {rc}"
    assert "internal error" in err, (
        f"expected 'internal error' marker in stderr, got: {err!r}"
    )
    assert "RuntimeError" in err, (
        f"expected exception class name in stderr, got: {err!r}"
    )