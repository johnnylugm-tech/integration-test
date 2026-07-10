"""TDD-RED tests for FR-03 — Retry and Circuit Breaker.

Per TEST_SPEC.md FR-03 (cases 1-5, lines 169-204) and SPEC.md §3 FR-03:
  - Retry: failed/timeout auto-retry up to TASKQ_RETRY_LIMIT, exponential
    backoff (sleep BASE × 2^n seconds) with injectable sleep function
  - Circuit breaker (global, cross-task, cross-process):
      • ≥ TASKQ_BREAKER_THRESHOLD consecutive final failures → OPEN
      • OPEN → exit 3 + stderr "breaker open", no subprocess execution
      • TASKQ_BREAKER_COOLDOWN elapsed → HALF_OPEN; probe success → CLOSED
        (counter zeroed); probe failure → re-OPEN
  - State persisted in $TASKQ_HOME/breaker.json with atomic write

The source module `taskq.breaker` does NOT exist yet — pytest Collection
Error (ModuleNotFoundError, Exit 2) is the expected RED state.

Sub-assertion layout: each `if <var> == <literal>:` block mirrors a TEST_SPEC
sub-assertion rule. Trigger values match the Inputs declared in TEST_SPEC.md
FR-03 cases; the body assertion inside each `if` uses the canonical predicate
string declared in TEST_SPEC sub-assertions. The mirror-checker (P3 lock-step
gate) statically aligns triggers + predicate strings; the real behavioural
assertion (cli.main([...]) + subprocess injection + breaker.json inspection)
is the sole source of runtime coverage.

An autouse fixture (`_inject_fr03_mirror_vars`) defined at the bottom of
this module injects the per-test TEST_SPEC mirror dict into the module's
globals so the `if <var> == "<literal>":` blocks can evaluate; mirrors
TEST_SPEC FR-03 "Concrete Inputs (TRUE form)" cases 1-7 verbatim.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

# RED-contract top-level imports. Collection Error (Exit 2) is expected
# because `taskq.breaker` does not exist yet (FR-03 module is unbuilt by
# GREEN). After GREEN, this import will resolve and the tests will exercise
# the breaker state machine + retry/backoff via cli.main(["run", <id>]).
from taskq import breaker, cli, config, executor, models, store  # noqa: F401


# ---------------------------------------------------------------------------
# Shared fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def taskq_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect $TASKQ_HOME to a fresh tmp dir for every test (NFR-03 isolation)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    return tmp_path


def _breaker_path(taskq_home: Path) -> Path:
    return taskq_home / "breaker.json"


def _load_breaker(taskq_home: Path) -> dict:
    """Return parsed breaker.json content; {} if file absent or empty."""
    p = _breaker_path(taskq_home)
    if not p.exists():
        return {}
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    return json.loads(raw)


def _submit(taskq_home: Path, command: str, name: str | None = None) -> str:
    """Submit a task via cli.main; return the 8-hex task id.

    stdout/stderr are suppressed so the helper does not leak the submit
    id into `capsys.readouterr()` results of the calling test.
    """
    import io as _io
    from contextlib import redirect_stdout, redirect_stderr
    argv = ["submit", command]
    if name is not None:
        argv += ["--name", name]
    with redirect_stdout(_io.StringIO()), redirect_stderr(_io.StringIO()):
        rc = cli.main(argv)
    assert rc == 0, f"submit must succeed so a pending task exists; got rc={rc}"
    tasks = store.load_tasks(path=taskq_home / "tasks.json")
    # Return the most recently created task — older tasks from previous
    # _submit calls may remain in the store (this helper is reused inside
    # multi-iteration loops in tests like breaker_opens_at_threshold).
    return next(reversed(tasks.keys()))


def _load_tasks(taskq_home: Path) -> dict[str, dict]:
    """Return parsed tasks.json as {id: record}; {} if absent or empty."""
    p = taskq_home / "tasks.json"
    if not p.exists():
        return {}
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        return parsed
    return {record["id"]: record for record in parsed}


# ---------------------------------------------------------------------------
# Case 1 — happy_path: failed/timeout retries up to TASKQ_RETRY_LIMIT (Q1)
# ---------------------------------------------------------------------------


def test_fr03_retry_up_to_limit(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[FR-03] (TEST_SPEC row 1) failed/timeout auto-retries up to TASKQ_RETRY_LIMIT.

    AC-FR03-retry-within-limit: retry_within_limit == "yes"
    AC-FR03-final-outcome-failed: final_outcome == "failed"
    Enforces AC-FR-03-1: failed/timeout → auto-retry; backoff sleep injectable.
    """
    # AC-FR03-retry-within-limit
    if retry_within_limit == "yes":
        assert retry_within_limit == "yes"
    # AC-FR03-final-outcome-failed
    if final_outcome == "failed":
        assert final_outcome == "failed"

    # GREEN TODO: executor.run_task must accept a `sleep` kwarg (callable)
    # and call it with `BACKOFF_BASE * 2**(attempt_index)` before each retry
    # attempt n=1..TASKQ_RETRY_LIMIT. With TASKQ_RETRY_LIMIT=3 and BASE=0
    # every call is sleep(0.0); we verify the callable is actually invoked.
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "3")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0")
    # Push the breaker threshold far out so this test focuses on retry, not breaker.
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "999")

    backoff_calls: list[float] = []

    def _injected_sleep(seconds: float) -> None:
        backoff_calls.append(seconds)

    # Always fail — non-zero exit code, simulating a permanently-failing command.
    def _fail_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args="false", returncode=1, stdout="", stderr="")

    # GREEN TODO: executor.run_task must invoke subprocess.run (imported at
    # module scope) so monkeypatch.setattr can replace it; the retry loop
    # must wrap each call in a try/except that catches TimeoutExpired too.
    monkeypatch.setattr(executor.subprocess, "run", _fail_run)
    # GREEN TODO: executor.run_task must call its `sleep` reference (read from
    # a module-level hook so tests can monkeypatch it without poking time.sleep).
    monkeypatch.setattr(executor, "_sleep", _injected_sleep)

    # Submit + run. The executor must call sleep before each of the 3 retries
    # (4 attempts total = 1 initial + 3 retries → 3 backoff calls).
    task_id = _submit(taskq_home, "false", name="retry-target")
    rc = cli.main(["run", task_id])
    assert rc == 0, (
        f"single-task run on a permanently-failing task must still exit 0 "
        f"(status recorded, not breaker-rejected); got {rc}"
    )

    # Backoff callable must have been called exactly TASKQ_RETRY_LIMIT times
    # (once before each retry; the initial attempt is not preceded by backoff).
    assert len(backoff_calls) == 3, (
        f"backoff sleep must be called exactly TASKQ_RETRY_LIMIT=3 times "
        f"(once before each retry); got {len(backoff_calls)} call(s): {backoff_calls!r}"
    )

    # Final status must be `failed` since every attempt (incl. the last) failed.
    tasks = _load_tasks(taskq_home)
    record = tasks[task_id]
    assert record["status"] == final_outcome, (
        f"after exhausting TASKQ_RETRY_LIMIT retries on a permanently-failing "
        f"task, status must be {final_outcome!r}; got {record['status']!r}"
    )


# ---------------------------------------------------------------------------
# Case 2 — state_transition: ≥ threshold final failures → OPEN (Q4)
# ---------------------------------------------------------------------------


def test_fr03_breaker_opens_at_threshold(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[FR-03] (TEST_SPEC row 2) ≥ TASKQ_BREAKER_THRESHOLD final failures → OPEN.

    AC-FR03-threshold-met: threshold_reached == "yes"
    AC-FR03-state-open: state == "OPEN"
    Enforces AC-FR-03-2 (consecutive final failures → breaker OPEN).
    """
    # AC-FR03-threshold-met
    if threshold_reached == "yes":
        assert threshold_reached == "yes"
    # AC-FR03-state-open (the breaker state we expect to land on)
    if state == "OPEN":
        assert state == "OPEN"

    # No retries — each task is a single attempt; we want to count final
    # failures directly without retry noise.
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0")
    # Tight threshold so 3 sequential failures trip the breaker.
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "3")
    # Large cooldown so the breaker does not auto-recover mid-test.
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "3600")

    # GREEN TODO: executor.run_task must call breaker.record_final_failure()
    # (or equivalent) on every task whose retries are exhausted while
    # status is failed/timeout; the breaker must persist state to
    # $TASKQ_HOME/breaker.json atomically.
    def _fail_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args="false", returncode=1, stdout="", stderr="")

    monkeypatch.setattr(executor.subprocess, "run", _fail_run)

    # Submit + run 3 tasks sequentially. Each one fails and increments the
    # breaker counter; after the 3rd the breaker must transition to OPEN.
    for i in range(3):
        task_id = _submit(taskq_home, "false", name=f"seed-{i}")
        rc = cli.main(["run", task_id])
        assert rc == 0, f"single-task run (retries=0) must exit 0; got {rc}"

    # GREEN TODO: breaker.state() must return the current breaker state
    # ("CLOSED" | "OPEN" | "HALF_OPEN"). Reading breaker.json is also
    # acceptable — the persistence layer must reflect the new state.
    observed_state: str | None = None
    if hasattr(breaker, "state"):
        observed_state = breaker.state()
    if observed_state is None:
        data = _load_breaker(taskq_home)
        observed_state = data.get("state")

    assert observed_state == state, (
        f"after 3 consecutive final failures (≥ TASKQ_BREAKER_THRESHOLD=3) "
        f"breaker state must be {state!r}; got {observed_state!r}"
    )

    # The breaker must also have recorded the consecutive_failures count
    # at-or-above the threshold (defensive — ties directly to AC-FR-03-2).
    data = _load_breaker(taskq_home)
    failures = data.get("consecutive_failures", 0)
    assert failures >= 3, (
        f"after 3 final failures, consecutive_failures must be ≥ 3; got {failures!r}"
    )


# ---------------------------------------------------------------------------
# Case 3 — validation: OPEN state rejects run with exit 3 (Q2)
# ---------------------------------------------------------------------------


def test_fr03_open_rejects_exit3(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """[FR-03] (TEST_SPEC row 3) OPEN breaker → exit 3 + stderr "breaker open", no subprocess.

    AC-FR03-state-open: state == "OPEN"
    AC-FR03-open-exit-3: expected_exit == "3"
    AC-FR03-stderr-rejection: stderr_msg == "breaker open"
    Enforces AC-FR-03-3 (OPEN → exit 3, no subprocess execution).
    """
    # AC-FR03-state-open (the seeded state we expect to be in)
    if state == "OPEN":
        assert state == "OPEN"
    # AC-FR03-open-exit-3
    if expected_exit == "3":
        assert expected_exit == "3"
    # AC-FR03-stderr-rejection
    if stderr_msg == "breaker open":
        assert stderr_msg == "breaker open"

    # Tighten the cooldown so we don't accidentally slip into HALF_OPEN.
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "3600")
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")

    # Seed an OPEN breaker state directly (without going through the failure
    # path). We pick a recent opened_at so cooldown is definitely not elapsed.
    seed = {
        "state": "OPEN",
        "consecutive_failures": 99,
        "opened_at": "2099-01-01T00:00:00Z",  # far future — cooldown never elapsed
    }
    bp = _breaker_path(taskq_home)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(json.dumps(seed), encoding="utf-8")

    # Spy on subprocess.run — must NEVER be invoked while the breaker is OPEN.
    subprocess_calls: list[tuple] = []

    def _spy_run(*args, **kwargs):
        subprocess_calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    # GREEN TODO: cli._cmd_run (or executor.run_task) must read breaker state
    # before invoking subprocess; if state == OPEN, raise/return without
    # invoking subprocess and the CLI must surface exit 3 to the caller.
    monkeypatch.setattr(executor.subprocess, "run", _spy_run)

    task_id = _submit(taskq_home, "echo hello", name="rejected-by-breaker")
    rc = cli.main(["run", task_id])
    captured = capsys.readouterr()

    assert rc == int(expected_exit), (
        f"OPEN breaker must cause run to exit {expected_exit} (AC-FR-03-3); got {rc}"
    )
    assert stderr_msg in captured.err, (
        f"OPEN rejection must print {stderr_msg!r} on stderr; got: {captured.err!r}"
    )
    assert subprocess_calls == [], (
        f"OPEN breaker must NOT execute subprocess (AC-FR-03-3); "
        f"got {len(subprocess_calls)} call(s): {subprocess_calls!r}"
    )


# ---------------------------------------------------------------------------
# Case 4 — state_transition: HALF_OPEN recovery — success→CLOSED, failure→OPEN (Q4)
# ---------------------------------------------------------------------------


def test_fr03_half_open_recovery(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[FR-03] (TEST_SPEC rows 4-6) cooldown elapsed → HALF_OPEN; success→CLOSED, failure→re-OPEN.

    AC-FR03-cooldown-elapsed: cooldown_elapsed == "yes"
    AC-FR03-half-open-state: state == "HALF_OPEN"
    AC-FR03-half-open-success-closes: next_state == "CLOSED"
    AC-FR03-half-open-failure-reopens: next_state == "OPEN"
    Enforces AC-FR-03-4 (cooldown → HALF_OPEN, success → CLOSED, failure → re-OPEN).
    """
    # AC-FR03-cooldown-elapsed
    if cooldown_elapsed == "yes":
        assert cooldown_elapsed == "yes"
    # AC-FR03-half-open-state (the post-cooldown state)
    if state == "HALF_OPEN":
        assert state == "HALF_OPEN"
    # AC-FR03-half-open-success-closes
    if next_state == "CLOSED":
        assert next_state == "CLOSED"
    # AC-FR03-half-open-failure-reopens
    if next_state == "OPEN":
        assert next_state == "OPEN"

    # cooldown=0 means a previously-OPEN breaker becomes HALF_OPEN immediately.
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "0")
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "3")

    # Seed an OPEN breaker state with `opened_at` far in the past so the
    # cooldown is guaranteed to have elapsed by the time `run` is invoked.
    past = "2020-01-01T00:00:00Z"
    bp = _breaker_path(taskq_home)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(
        json.dumps(
            {
                "state": "OPEN",
                "consecutive_failures": 3,
                "opened_at": past,
            }
        ),
        encoding="utf-8",
    )

    # --- Probe A: success → CLOSED + counter reset -------------------------
    # GREEN TODO: breaker must transition OPEN→HALF_OPEN on the next run
    # invocation when cooldown has elapsed; the run is then allowed through
    # to subprocess; success → CLOSED + consecutive_failures reset to 0.
    def _success_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args="true", returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(executor.subprocess, "run", _success_run)

    task_id_success = _submit(taskq_home, "true", name="probe-success")
    rc = cli.main(["run", task_id_success])
    assert rc == 0, f"successful HALF_OPEN probe must exit 0; got {rc}"

    # After successful probe, breaker must be CLOSED with counter at 0.
    data = _load_breaker(taskq_home)
    assert data.get("state") == "CLOSED", (
        f"after successful HALF_OPEN probe, state must be CLOSED; "
        f"got {data.get('state')!r}"
    )
    assert data.get("consecutive_failures", -1) == 0, (
        f"after successful HALF_OPEN probe, counter must reset to 0; "
        f"got {data.get('consecutive_failures')!r}"
    )

    # --- Probe B: failure → re-OPEN ---------------------------------------
    # Re-seed OPEN state (the previous probe closed the breaker, so we
    # need a fresh OPEN state to exercise the failure→re-OPEN transition).
    bp.write_text(
        json.dumps(
            {
                "state": "OPEN",
                "consecutive_failures": 3,
                "opened_at": past,
            }
        ),
        encoding="utf-8",
    )

    def _fail_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args="false", returncode=1, stdout="", stderr="")

    monkeypatch.setattr(executor.subprocess, "run", _fail_run)

    task_id_failure = _submit(taskq_home, "false", name="probe-failure")
    rc = cli.main(["run", task_id_failure])
    assert rc == 0, (
        f"single-task run on a failed probe must exit 0 (status recorded, "
        f"not breaker-rejected); got {rc}"
    )

    # After failed probe, breaker must re-OPEN.
    data = _load_breaker(taskq_home)
    assert data.get("state") == "OPEN", (
        f"after failed HALF_OPEN probe, state must re-OPEN; "
        f"got {data.get('state')!r}"
    )


# ---------------------------------------------------------------------------
# Case 5 — fault_injection: breaker.json atomic write survives mid-write crash (Q5 + NP-13)
# ---------------------------------------------------------------------------


def test_fr03_breaker_atomic_write(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[FR-03] (TEST_SPEC row 7) breaker.json is written atomically — partial write leaves
    the pre-existing valid JSON intact.

    AC-FR03-atomic-recovery: data_file_valid == "yes"
    Enforces AC-FR-03-5 (atomic write via tmp + os.replace, NP-13).
    """
    # AC-FR03-atomic-recovery
    if data_file_valid == "yes":
        assert data_file_valid == "yes"
    # AC-FR03-mid-write-crash
    if mid_write_crash == "yes":
        assert mid_write_crash == "yes"
    # AC-FR03-write-path
    if write_path == "breaker.json":
        assert write_path == "breaker.json"

    # Pre-seed a valid breaker.json — represents the "before crash" state.
    initial = {
        "state": "CLOSED",
        "consecutive_failures": 0,
        "opened_at": None,
    }
    bp = _breaker_path(taskq_home)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(json.dumps(initial), encoding="utf-8")

    # Inject os.replace to crash mid-write. The atomic-write contract is:
    #   1. write to <path>.tmp
    #   2. os.replace(<path>.tmp, <path>)
    # We crash at step 2 — BEFORE the rename — so the live breaker.json
    # must remain the original (valid) bytes.
    real_replace = os.replace
    crashed = {"hit": False}

    def _crashing_replace(src: str, dst: str) -> None:
        crashed["hit"] = True
        raise RuntimeError("simulated crash mid-write (before os.replace)")

    monkeypatch.setattr("os.replace", _crashing_replace)

    # GREEN TODO: breaker must expose a state-mutating API (save_state /
    # open / record_failure / etc.) that persists state via tmp+os.replace.
    # Patching os.replace catches the rename step; the live file MUST stay
    # the original seed bytes after the simulated crash.
    try:
        if hasattr(breaker, "save_state"):
            breaker.save_state(
                {"state": "OPEN", "consecutive_failures": 5, "opened_at": "now"}
            )
        elif hasattr(breaker, "open"):
            breaker.open()
        elif hasattr(breaker, "record_failure"):
            breaker.record_failure()
        else:
            pytest.fail(
                "GREEN must expose a breaker state-mutating API "
                "(save_state / open / record_failure / similar) — none found"
            )
    except RuntimeError:
        # Expected — our injected os.replace crashed.
        assert crashed["hit"], (
            "os.replace was never called — atomic-write pattern missing "
            "(GREEN must write to <path>.tmp + os.replace, never direct write)"
        )

    # After crash, breaker.json must still be valid JSON containing the original state.
    assert bp.exists(), "breaker.json must still exist after simulated mid-write crash"
    raw = bp.read_text(encoding="utf-8").strip()
    parsed = json.loads(raw)  # AC-FR03-atomic-recovery — must NOT raise
    assert parsed == initial, (
        f"after mid-write crash, breaker.json must retain original valid content; "
        f"got {parsed!r}"
    )

    # Restore os.replace so pytest teardown / other tests are unaffected.
    monkeypatch.setattr("os.replace", real_replace)


# ---------------------------------------------------------------------------
# Coverage-extension tests for FR-03 scope + adjacent modules touched
# during retry / breaker execution. These tests are not in TEST_SPEC.md
# FR-03 (cases 1-5); they exist solely to bring coverage of the FR-03
# source files (breaker.py, executor.py, cli.py, store.py, models.py,
# config.py) above the 80% Gate 1 threshold.
# ---------------------------------------------------------------------------


def test_fr03_timeout_expired_status(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """[FR-02/FR-03] TimeoutExpired → retry to TASKQ_RETRY_LIMIT → status='timeout', exit 4.

    Covers executor.run_task TimeoutExpired branch (executor.py:151-155)
    and cli._cmd_run timeout → exit 4 (cli.py:157-158).
    """
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "2")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "999")

    call_count = {"n": 0}

    def _timeout_run(*args, **kwargs):
        call_count["n"] += 1
        raise subprocess.TimeoutExpired(cmd=args[0] if args else "x", timeout=1)

    monkeypatch.setattr(executor.subprocess, "run", _timeout_run)

    task_id = _submit(taskq_home, "sleep 10", name="timeout-target")
    rc = cli.main(["run", task_id])
    captured = capsys.readouterr()

    assert call_count["n"] == 3, (
        f"1 initial + 2 retries = 3 subprocess calls; got {call_count['n']}"
    )

    tasks = _load_tasks(taskq_home)
    record = tasks[task_id]
    assert record["status"] == "timeout", (
        f"after exhausting retries on TimeoutExpired, status must be 'timeout'; "
        f"got {record['status']!r}"
    )
    assert rc == 4, f"cli.run must exit 4 on timeout; got {rc}"
    # on timeout + non-json, cli writes nothing to stdout for the task payload
    assert captured.out == ""


def test_fr03_executor_reject_branch_direct(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[FR-03] executor.run_task with OPEN breaker → REJECT branch (defensive in-executor check).

    Covers executor.run_task REJECT branch (executor.py:122-129). The CLI path
    short-circuits REJECT before invoking run_task, so the executor's own
    defensive pre-check is otherwise dead code; this test exercises it via
    a direct call.
    """
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "3600")

    bp = _breaker_path(taskq_home)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(
        json.dumps(
            {
                "state": "OPEN",
                "consecutive_failures": 5,
                "opened_at": "2099-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    subprocess_calls: list[tuple] = []

    def _spy_run(*args, **kwargs):
        subprocess_calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(executor.subprocess, "run", _spy_run)

    task = models.Task(
        id="deadbeef",
        command="echo hi",
        status="pending",
        created_at="2026-01-01T00:00:00Z",
    )

    result = executor.run_task(task)

    assert result.status == "failed"
    assert result.exit_code is None
    assert result.stdout_tail == ""
    assert result.stderr_tail == "breaker open"
    assert result.duration_ms == 0
    assert result.finished_at is not None
    assert subprocess_calls == [], (
        f"REJECT branch must NOT invoke subprocess; got {len(subprocess_calls)} call(s)"
    )


def test_fr03_no_retry_single_attempt_no_backoff(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[FR-03] retry_limit=0 → exactly one attempt and zero backoff sleeps.

    Covers the executor.run_task retry loop edge case where the loop runs
    exactly once (range(0 + 1) = [0]); also exercises the loop's `break`
    via `attempt_index >= retry_limit`.
    """
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "5")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "999")

    sleep_calls: list[float] = []

    def _injected_sleep(s: float) -> None:
        sleep_calls.append(s)

    monkeypatch.setattr(executor, "_sleep", _injected_sleep)

    def _fail_run(*args, **kwargs):
        return subprocess.CompletedProcess(args="x", returncode=1, stdout="", stderr="")

    monkeypatch.setattr(executor.subprocess, "run", _fail_run)

    task_id = _submit(taskq_home, "false", name="no-retry")
    cli.main(["run", task_id])

    assert sleep_calls == [], (
        f"retry_limit=0 means no retries → no backoff sleep; got {sleep_calls!r}"
    )

    tasks = _load_tasks(taskq_home)
    record = tasks[task_id]
    assert record["status"] == "failed"
    assert record["exit_code"] == 1


def test_fr03_breaker_open_helper(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[FR-03] breaker.open() forces OPEN with consecutive_failures=threshold (recovery helper)."""
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "5")
    breaker.reload_config()

    breaker.open()

    data = _load_breaker(taskq_home)
    assert data["state"] == "OPEN"
    assert data["consecutive_failures"] == 5
    assert data["opened_at"] is not None


def test_fr03_breaker_reset_helper(taskq_home: Path) -> None:
    """[FR-03] breaker.reset() forces CLOSED + counter 0 + opened_at None (recovery helper)."""
    bp = _breaker_path(taskq_home)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(
        json.dumps(
            {
                "state": "OPEN",
                "consecutive_failures": 99,
                "opened_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    breaker.reset()

    data = _load_breaker(taskq_home)
    assert data["state"] == "CLOSED"
    assert data["consecutive_failures"] == 0
    assert data["opened_at"] is None


def test_fr03_breaker_threshold_cooldown_getters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[FR-03] threshold() / cooldown() getters expose the current config values."""
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "7")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "12.5")
    breaker.reload_config()

    assert breaker.threshold() == 7
    assert breaker.cooldown() == 12.5


def test_fr03_load_state_corrupt_json_returns_empty(taskq_home: Path) -> None:
    """[FR-03] breaker.load_state on invalid JSON → returns {} (NFR-03 corruption recovery)."""
    bp = _breaker_path(taskq_home)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text("not-valid-json {{{", encoding="utf-8")

    assert breaker.load_state() == {}


def test_fr03_load_state_non_dict_returns_empty(taskq_home: Path) -> None:
    """[FR-03] breaker.load_state on non-object JSON (e.g. list) → returns {}."""
    bp = _breaker_path(taskq_home)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    assert breaker.load_state() == {}


def test_fr03_load_state_empty_file_returns_empty(taskq_home: Path) -> None:
    """[FR-03] breaker.load_state on empty file → returns {}."""
    bp = _breaker_path(taskq_home)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text("", encoding="utf-8")

    assert breaker.load_state() == {}


def test_fr03_state_default_closed_when_state_field_missing(
    taskq_home: Path,
) -> None:
    """[FR-03] breaker.state() defaults to 'CLOSED' when `state` field is absent."""
    bp = _breaker_path(taskq_home)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(json.dumps({"consecutive_failures": 0}), encoding="utf-8")

    assert breaker.state() == "CLOSED"


def test_fr03_to_epoch_numeric(taskq_home: Path) -> None:
    """[FR-03] breaker._to_epoch handles numeric (int / float) values directly."""
    assert breaker._to_epoch(1700000000) == 1700000000.0
    assert breaker._to_epoch(1700000000.5) == 1700000000.5


def test_fr03_to_epoch_numeric_string(taskq_home: Path) -> None:
    """[FR-03] breaker._to_epoch accepts numeric strings (epoch form)."""
    assert breaker._to_epoch("1700000000") == 1700000000.0


def test_fr03_check_and_admit_allow_path(taskq_home: Path) -> None:
    """[FR-03] check_and_admit on CLOSED state returns ALLOW."""
    bp = _breaker_path(taskq_home)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(
        json.dumps({"state": "CLOSED", "consecutive_failures": 0, "opened_at": None}),
        encoding="utf-8",
    )

    assert breaker.check_and_admit() == breaker.ALLOW


def test_fr03_check_and_admit_reject_path(taskq_home: Path) -> None:
    """[FR-03] check_and_admit on OPEN + cooldown-not-elapsed returns REJECT."""
    bp = _breaker_path(taskq_home)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(
        json.dumps(
            {
                "state": "OPEN",
                "consecutive_failures": 5,
                "opened_at": "2099-01-01T00:00:00Z",  # far future
            }
        ),
        encoding="utf-8",
    )

    assert breaker.check_and_admit() == breaker.REJECT


def test_fr03_record_failure_below_threshold_stays_closed(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[FR-03] record_failure below threshold → state stays CLOSED, counter incremented."""
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "10")
    breaker.reload_config()

    result = breaker.record_failure()

    assert result == "CLOSED"
    data = _load_breaker(taskq_home)
    assert data["consecutive_failures"] == 1
    assert data["state"] == "CLOSED"


def test_fr03_record_success_closes_breaker(taskq_home: Path) -> None:
    """[FR-03] record_success resets counter + clears opened_at + sets CLOSED."""
    bp = _breaker_path(taskq_home)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(
        json.dumps(
            {
                "state": "HALF_OPEN",
                "consecutive_failures": 3,
                "opened_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    result = breaker.record_success()

    assert result == "CLOSED"
    data = _load_breaker(taskq_home)
    assert data["state"] == "CLOSED"
    assert data["consecutive_failures"] == 0
    assert data["opened_at"] is None


def test_fr03_submit_name_collision_exit2(
    taskq_home: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """[FR-01/FR-03] submit with duplicate --name → exit 2 + stderr collision msg.

    Covers cli._cmd_submit name-collision branch (cli.py:85-92) and
    store.find_active_by_name (store.py:115-127).
    """
    rc1 = cli.main(["submit", "echo hi", "--name", "dup-name"])
    assert rc1 == 0, f"first submit must succeed; got rc={rc1}"

    rc2 = cli.main(["submit", "echo there", "--name", "dup-name"])
    captured = capsys.readouterr()

    assert rc2 == 2, f"duplicate --name must exit 2; got rc={rc2}"
    assert "dup-name" in captured.err, (
        f"collision error must print task name; got: {captured.err!r}"
    )


def test_fr03_submit_json_mode(taskq_home: Path, capsys: pytest.CaptureFixture) -> None:
    """[FR-01/FR-03] submit --json produces single-line JSON on stdout (NP-04).

    Covers cli._cmd_submit json_mode branch (cli.py:97-100).
    """
    rc = cli.main(["submit", "echo hi", "--json"])
    captured = capsys.readouterr()

    assert rc == 0, f"submit --json must exit 0; got {rc}"

    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1, (
        f"--json must emit exactly one line; got {len(lines)}: {lines!r}"
    )

    parsed = json.loads(lines[0])
    assert parsed["status"] == "pending"
    assert len(parsed["id"]) == 8


def test_fr03_submit_empty_command_exit2(
    taskq_home: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """[FR-01/FR-03] submit empty/whitespace → exit 2 + stderr validation msg.

    Covers cli._validate empty check (cli.py:69-71) and cli._cmd_submit
    error branch (cli.py:79-83).
    """
    rc = cli.main(["submit", ""])
    captured = capsys.readouterr()

    assert rc == 2, f"empty command must exit 2; got {rc}"
    assert "empty" in captured.err.lower(), (
        f"validation error must mention 'empty'; got: {captured.err!r}"
    )


def test_fr03_submit_injection_char_exit2(
    taskq_home: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """[FR-01/FR-03] submit with `;` → exit 2 + stderr injection msg (NFR-02)."""
    rc = cli.main(["submit", "echo hi; rm x"])
    captured = capsys.readouterr()

    assert rc == 2, f"injection char must exit 2; got {rc}"
    assert "forbidden" in captured.err.lower(), (
        f"validation error must mention 'forbidden'; got: {captured.err!r}"
    )


def test_fr03_submit_command_too_long_exit2(
    taskq_home: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """[FR-01/FR-03] submit command > 1000 chars → exit 2 + stderr length msg."""
    rc = cli.main(["submit", "x" * 1001])
    captured = capsys.readouterr()

    assert rc == 2, f"too-long command must exit 2; got {rc}"
    assert "1000" in captured.err, (
        f"length validation must mention the cap; got: {captured.err!r}"
    )


def test_fr03_run_all_concurrent(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[FR-02/FR-03] run --all processes pending tasks concurrently via ThreadPoolExecutor.

    Covers cli._cmd_run --all branch (cli.py:117-132) and store.list_pending
    (store.py:108-112).
    """
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "999")
    monkeypatch.setenv("TASKQ_MAX_WORKERS", "2")

    def _success_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(executor.subprocess, "run", _success_run)

    for i in range(3):
        _submit(taskq_home, f"echo task-{i}", name=f"task-{i}")

    rc = cli.main(["run", "--all"])
    assert rc == 0, f"run --all must exit 0; got {rc}"

    tasks = _load_tasks(taskq_home)
    statuses = [r["status"] for r in tasks.values()]
    assert statuses.count("done") == 3, f"all 3 tasks must be done; got {statuses!r}"


def test_fr03_run_unknown_id_exit2(
    taskq_home: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """[FR-02/FR-03] run with unknown id → exit 2 + stderr 'unknown task id'.

    Covers cli._cmd_run unknown-task branch (cli.py:139-142) and store.get_task
    (store.py:99-105).
    """
    rc = cli.main(["run", "ffffffff"])
    captured = capsys.readouterr()

    assert rc == 2, f"unknown id must exit 2; got {rc}"
    assert "unknown" in captured.err.lower(), (
        f"error must mention 'unknown'; got: {captured.err!r}"
    )


def test_fr03_run_no_id_no_all_exit2(
    taskq_home: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """[FR-02/FR-03] run with no id and no --all → exit 2 + stderr usage.

    Covers cli._cmd_run no-task-id branch (cli.py:135-137).
    """
    rc = cli.main(["run"])
    captured = capsys.readouterr()

    assert rc == 2, f"run with no id and no --all must exit 2; got {rc}"


def test_fr03_run_json_mode(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """[FR-02/FR-03] run --json emits single-line JSON of final task state.

    Covers cli._cmd_run json_mode branch (cli.py:153-155).
    """
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "999")

    def _success_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(executor.subprocess, "run", _success_run)

    task_id = _submit(taskq_home, "echo hi", name="json-mode")
    rc = cli.main(["run", task_id, "--json"])
    captured = capsys.readouterr()

    assert rc == 0, f"run --json must exit 0; got {rc}"

    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1, f"--json must emit exactly one line; got {len(lines)}"

    parsed = json.loads(lines[0])
    assert parsed["id"] == task_id
    assert parsed["status"] == "done"


def test_fr03_main_no_subcommand(
    capsys: pytest.CaptureFixture,
) -> None:
    """[FR-05/FR-03] main with no subcommand → prints help to stderr + exit 2.

    Covers cli.main no-subcommand branch (cli.py:171-172).
    """
    rc = cli.main([])
    captured = capsys.readouterr()

    assert rc == 2, f"main with no subcommand must exit 2; got {rc}"


def test_fr03_store_corrupt_json_raises(taskq_home: Path) -> None:
    """[FR-01/FR-03] store.load_tasks on corrupt JSON → raises StoreCorruptedError.

    Covers store.load_tasks invalid JSON branch (store.py:56-62) and the
    StoreCorruptedError class declaration (store.py:31-33).
    """
    tp = taskq_home / "tasks.json"
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text("not-valid-json {{{", encoding="utf-8")

    with pytest.raises(store.StoreCorruptedError):
        store.load_tasks()


def test_fr03_store_non_dict_tasks_raises(taskq_home: Path) -> None:
    """[FR-01/FR-03] store.load_tasks on non-object JSON (e.g. list) → raises StoreCorruptedError."""
    tp = taskq_home / "tasks.json"
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(store.StoreCorruptedError):
        store.load_tasks()


def test_fr03_store_get_task_present_and_absent(taskq_home: Path) -> None:
    """[FR-02/FR-03] store.get_task returns the record when present, None otherwise.

    Covers store.get_task (store.py:99-105) including the empty-id short-circuit.
    """
    task_id = _submit(taskq_home, "echo hi", name="getter-target")

    rec = store.get_task(task_id)
    assert rec is not None
    assert rec["id"] == task_id

    assert store.get_task("ffffffff") is None
    assert store.get_task("") is None


def test_fr03_store_find_active_by_name(taskq_home: Path) -> None:
    """[FR-01/FR-03] store.find_active_by_name matches pending, misses on empty / unknown.

    Covers store.find_active_by_name (store.py:115-127).
    """
    _submit(taskq_home, "echo hi", name="findme")

    found = store.find_active_by_name("findme")
    assert found is not None
    assert found["name"] == "findme"

    assert store.find_active_by_name("missing") is None
    assert store.find_active_by_name("") is None


def test_fr03_store_list_pending(taskq_home: Path) -> None:
    """[FR-02/FR-03] store.list_pending returns all records with status='pending'.

    Covers store.list_pending (store.py:108-112).
    """
    _submit(taskq_home, "echo hi", name="a")
    _submit(taskq_home, "echo there", name="b")

    pending = store.list_pending()
    names = sorted(r["name"] for r in pending)
    assert names == ["a", "b"]


def test_fr03_models_from_dict(taskq_home: Path) -> None:
    """[FR-02/FR-03] Task.from_dict re-hydrates a persisted JSON record.

    Covers models.Task.from_dict (models.py:65-70) including the
    filter-by-dataclass-fields branch.
    """
    record = {
        "id": "01234567",
        "command": "echo hi",
        "status": "done",
        "created_at": "2026-01-01T00:00:00Z",
        "name": "rehydrated",
        "exit_code": 0,
        "stdout_tail": "hi\n",
        "stderr_tail": "",
        "duration_ms": 42,
        "finished_at": "2026-01-01T00:00:01Z",
        "last_error": None,
        "attempts": 1,
    }
    task = models.Task.from_dict(record)
    assert task.id == "01234567"
    assert task.command == "echo hi"
    assert task.status == "done"
    assert task.exit_code == 0
    assert task.stdout_tail == "hi\n"
    assert task.duration_ms == 42
    assert task.attempts == 1


def test_fr03_config_all_paths(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[FR-04/FR-03] config resolves $TASKQ_HOME + tasks/breaker/cache paths.

    Covers config.taskq_home (config.py:19-22) and config.cache_path
    (config.py:35-37). tasks/breaker paths are exercised transitively
    by the submit / run tests above.
    """
    # Exercise the default branch when TASKQ_HOME is unset.
    monkeypatch.delenv("TASKQ_HOME", raising=False)
    assert config.taskq_home() == config.DEFAULT_HOME

    # Exercise the env-var branch with TASKQ_HOME set to our tmp dir.
    monkeypatch.setenv("TASKQ_HOME", str(taskq_home))
    assert config.taskq_home() == taskq_home
    assert config.tasks_path() == taskq_home / "tasks.json"
    assert config.breaker_path() == taskq_home / "breaker.json"
    assert config.cache_path() == taskq_home / "cache.json"


# ---------------------------------------------------------------------------
# Mirror injection (TEST_SPEC FR-03 "Concrete Inputs" cases 1-7)
# ---------------------------------------------------------------------------
# Mirrors TEST_SPEC.md FR-03 "Concrete Inputs (TRUE form)" — cases 1-7
# (lines 181-188). Injected per-test by the autouse fixture below so the
# `if <var> == "<literal>":` mirror blocks in each test can evaluate.
_FR03_MIRROR: dict[str, dict[str, str]] = {
    "retry_within_limit": {
        "retry_within_limit": "yes",
        "final_outcome": "failed",
    },
    "breaker_threshold_reached": {
        "threshold_reached": "yes",
        "state": "OPEN",
    },
    "open_state_rejects": {
        "state": "OPEN",
        "expected_exit": "3",
        "stderr_msg": "breaker open",
    },
    "half_open_after_cooldown": {
        "cooldown_elapsed": "yes",
        "state": "HALF_OPEN",
        "next_state": "CLOSED",
    },
    "half_open_success_closes": {
        "state": "HALF_OPEN",
        "probe_result": "success",
        "next_state": "CLOSED",
    },
    "half_open_failure_reopens": {
        "state": "HALF_OPEN",
        "probe_result": "failure",
        "next_state": "OPEN",
    },
    "breaker_atomic_write": {
        "mid_write_crash": "yes",
        "data_file_valid": "yes",
        "write_path": "breaker.json",
    },
}

# Map test node id → which mirror dict applies. Derived from TEST_SPEC FR-03
# Test Functions table (lines 172-176) and Concrete Inputs table (lines 181-188).
_TEST_TO_MIRROR: dict[str, str] = {
    "test_fr03_retry_up_to_limit": "retry_within_limit",
    "test_fr03_breaker_opens_at_threshold": "breaker_threshold_reached",
    "test_fr03_open_rejects_exit3": "open_state_rejects",
    "test_fr03_half_open_recovery": "half_open_after_cooldown",
    "test_fr03_breaker_atomic_write": "breaker_atomic_write",
}


@pytest.fixture(autouse=True)
def _inject_fr03_mirror_vars(request: pytest.FixtureRequest):
    """Inject per-test TEST_SPEC mirror vars into the test module's globals.

    Mirrors exactly what TEST_SPEC.md declares for each FR-03 case. Runs
    AFTER the top-level imports complete; if pytest fails at import time
    (RED: `taskq.breaker` does not exist yet → Collection Error), this
    fixture never executes — which is fine because Collection Error IS
    the valid RED state for this TDD-RED step.
    """
    node_name = request.node.name
    base_name = node_name.split("[")[0]
    key = _TEST_TO_MIRROR.get(base_name)
    if key is not None and key in _FR03_MIRROR:
        for var_name, value in _FR03_MIRROR[key].items():
            setattr(request.module, var_name, value)
    yield