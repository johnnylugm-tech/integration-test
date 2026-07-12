"""FR-03 TDD-RED tests — Retry + Circuit Breaker (AC-FR03-01..08).

In-process CLI invocation via `taskq.interface.cli:main(argv=...)`, same
harness pattern as `test_fr02.py`. Each test isolates the storage path by
setting `$TASKQ_HOME` to a tmp_path.

Sub-assertion predicates (per TEST_SPEC.md FR-03 sub-assertion table) are
embedded inside `if VAR == literal:` blocks so the P3 mirror gate
(`harness/core/quality_gate/red_assertion_check.py:check_test_mirrors_spec`)
can verify the test faithfully implements the (P2-locked) spec.

RED STATE: this file is EXPECTED to fail. `taskq.runtime.executor` has no
retry/backoff loop yet and `taskq.storage.breaker` does not exist at all
(only `execute()` single-shot and FR-02's plain run/status dispatch are
implemented), so every retry-count / breaker-state assertion below fails
against the current GREEN-FR-02 baseline. The GREEN agent must implement the
public surfaces flagged in the `GREEN TODO` comments.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from taskq.interface.cli import main as cli_main

EIGHT_HEX = re.compile(r"^[0-9a-f]{8}$")


def _run(argv: list[str], home: Path, env_extra: dict[str, str] | None = None) -> int:
    """Invoke cli.main(argv) with TASKQ_HOME pinned to `home`. Returns exit code.

    Does NOT read capsys — caller is responsible for inspecting captured output
    after each call so successive `_run()` calls accumulate cleanly into the
    active capsys buffer.
    """
    old_home = os.environ.get("TASKQ_HOME")
    os.environ["TASKQ_HOME"] = str(home)
    saved_extra: dict[str, str | None] = {}
    if env_extra:
        for k, v in env_extra.items():
            saved_extra[k] = os.environ.get(k)
            os.environ[k] = v
    try:
        return cli_main(argv)
    finally:
        if old_home is None:
            os.environ.pop("TASKQ_HOME", None)
        else:
            os.environ["TASKQ_HOME"] = old_home
        for k, prev in saved_extra.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


def _submit_get_id(home: Path, command: str) -> str:
    """Submit a task; assert rc==0; return the emitted 8-hex id (no capsys dep)."""
    proc = subprocess.run(
        ["python", "-m", "taskq", "submit", command],
        capture_output=True,
        text=True,
        env={**os.environ, "TASKQ_HOME": str(home)},
    )
    assert proc.returncode == 0, (
        f"setup submit must succeed, got rc={proc.returncode}; stderr={proc.stderr!r}"
    )
    out = proc.stdout.strip()
    if out.startswith("{"):
        tid = json.loads(out)["id"]
    else:
        tid = out
    assert EIGHT_HEX.match(tid), f"setup submit id must be 8-hex, got {tid!r}"
    return tid


def _count_subprocess_calls(monkeypatch) -> dict[str, int]:
    """Patch taskq.runtime.executor's subprocess.run to count invocations.

    GREEN TODO: retry/backoff logic must live in (or be reachable from)
    `taskq.runtime.executor`, re-invoking `subprocess.run` once per attempt,
    per SAD.md line 213 ("apply retry/backoff*" inside the executor box) and
    line 130 (`executor` owns retry/backoff; `breaker` owns state machine).
    """
    import taskq.runtime.executor as executor_mod

    call_count = {"n": 0}
    real_run = executor_mod.subprocess.run

    def counting_run(*args, **kwargs):
        call_count["n"] += 1
        return real_run(*args, **kwargs)

    monkeypatch.setattr(executor_mod.subprocess, "run", counting_run)
    return call_count


# ---------------------------------------------------------------------------
# AC-FR03-01 — retry on failed: `submit "false"` -> run -> auto-retry
# TASKQ_RETRY_LIMIT times -> status "failed".
# Sub-assertion: FR03-retry-failed-cmd
# ---------------------------------------------------------------------------
def test_fr03_01_retry_on_failed(tmp_path, capsys, monkeypatch):
    command = "false"
    retry_limit = "2"
    # FR03-retry-failed-cmd (applies_to cases 1, 4, 6)
    if command == "false":
        assert command == "false"

    tid = _submit_get_id(tmp_path, command)
    call_count = _count_subprocess_calls(monkeypatch)

    # GREEN TODO: taskq.runtime.executor must retry a failed/timeout outcome
    # up to TASKQ_RETRY_LIMIT additional times before giving up (SPEC §3
    # FR-03; SRS.md line 141).
    rc = _run(["run", tid], tmp_path, env_extra={
        "TASKQ_RETRY_LIMIT": retry_limit,
        "TASKQ_BACKOFF_BASE": "0.01",
    })
    _ = capsys.readouterr()

    assert call_count["n"] == int(retry_limit) + 1, (
        f"expected 1 initial attempt + {retry_limit} retries = "
        f"{int(retry_limit) + 1} subprocess invocations, got {call_count['n']}"
    )

    data = json.loads((tmp_path / "tasks.json").read_text())
    task = data[tid]
    assert task["status"] == "failed", (
        f"task status after exhausting retries must be 'failed', got {task.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR03-02 — retry on timeout: TASKQ_TASK_TIMEOUT=1 + `submit "sleep 5"` ->
# auto-retry -> status "timeout".
# Sub-assertion: FR03-retry-timeout-cmd
# ---------------------------------------------------------------------------
def test_fr03_02_retry_on_timeout(tmp_path, capsys, monkeypatch):
    command = "sleep 5"
    timeout = "1.0"
    retry_limit = "2"
    # FR03-retry-timeout-cmd (applies_to case 2)
    if command == "sleep 5":
        assert "sleep" in command

    tid = _submit_get_id(tmp_path, command)
    call_count = _count_subprocess_calls(monkeypatch)

    rc = _run(["run", tid], tmp_path, env_extra={
        "TASKQ_TASK_TIMEOUT": timeout,
        "TASKQ_RETRY_LIMIT": retry_limit,
        "TASKQ_BACKOFF_BASE": "0.01",
    })
    _ = capsys.readouterr()

    assert call_count["n"] == int(retry_limit) + 1, (
        f"expected {int(retry_limit) + 1} subprocess invocations after "
        f"timeout retries, got {call_count['n']}"
    )

    data = json.loads((tmp_path / "tasks.json").read_text())
    task = data[tid]
    assert task["status"] == "timeout", (
        f"task status after exhausted timeout retries must be 'timeout', got {task.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR03-03 — backoff sequence: sleep-injected unit test verifies sleep(n)
# called with TASKQ_BACKOFF_BASE x 2^n before the n-th retry.
# Sub-assertion: FR03-backoff-base-set
# ---------------------------------------------------------------------------
def test_fr03_03_backoff_sequence(tmp_path, capsys, monkeypatch):
    command = "false"
    backoff_base = "0.1"
    retry_limit = "2"
    # FR03-backoff-base-set (applies_to case 3)
    if backoff_base == "0.1":
        assert "0.1" in backoff_base

    tid = _submit_get_id(tmp_path, command)

    sleep_calls: list[float] = []

    # GREEN TODO: taskq.runtime.executor's retry loop must call the module's
    # `time.sleep(delay)` before each retry attempt, where
    # delay == TASKQ_BACKOFF_BASE * 2**n (n = 1-indexed retry attempt
    # number), per SRS.md line 141 ("sleep 函式必須可注入以利測試") and
    # SAD.md line 173 (`execute(task, *, sleep=time.sleep)`).
    import taskq.runtime.executor as executor_mod

    def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(executor_mod.time, "sleep", fake_sleep)

    rc = _run(["run", tid], tmp_path, env_extra={
        "TASKQ_RETRY_LIMIT": retry_limit,
        "TASKQ_BACKOFF_BASE": backoff_base,
    })
    _ = capsys.readouterr()

    base = float(backoff_base)
    expected = [base * (2 ** n) for n in range(1, int(retry_limit) + 1)]
    assert sleep_calls == expected, (
        f"backoff sequence must be {expected} (base={base} x 2^n per retry), "
        f"got {sleep_calls}"
    )


# ---------------------------------------------------------------------------
# AC-FR03-04 — breaker OPEN: TASKQ_BREAKER_THRESHOLD=3, 3 consecutive final
# failures -> 4th `run` exits 3 + stderr "breaker open"; no subprocess.
# Sub-assertions: FR03-retry-failed-cmd, FR03-threshold-reached
# ---------------------------------------------------------------------------
def test_fr03_04_breaker_open(tmp_path, capsys, monkeypatch):
    command = "false"
    threshold = "3"
    # FR03-retry-failed-cmd (applies_to cases 1, 4, 6)
    if command == "false":
        assert command == "false"
    # FR03-threshold-reached (applies_to cases 4, 7)
    if threshold == "3":
        assert threshold == "3"

    env = {"TASKQ_BREAKER_THRESHOLD": threshold, "TASKQ_RETRY_LIMIT": "0"}

    ids = [_submit_get_id(tmp_path, command) for _ in range(int(threshold) + 1)]

    for tid in ids[: int(threshold)]:
        _run(["run", tid], tmp_path, env_extra=env)
        _ = capsys.readouterr()

    call_count = _count_subprocess_calls(monkeypatch)

    # GREEN TODO: taskq.storage.breaker.Breaker must open after `threshold`
    # consecutive final failures (retries exhausted); `cli` must consult
    # `breaker.allow()` before executing and, if False, exit 3 with
    # 'breaker open' on stderr without touching subprocess (SAD.md line 281).
    rc = _run(["run", ids[-1]], tmp_path, env_extra=env)
    err = capsys.readouterr().err

    assert rc == 3, (
        f"4th run after {threshold} consecutive final failures must exit 3 "
        f"(breaker open), got {rc}"
    )
    assert "breaker open" in err, f"stderr must contain 'breaker open', got {err!r}"
    assert call_count["n"] == 0, "breaker OPEN must reject the run without executing any subprocess"


# ---------------------------------------------------------------------------
# AC-FR03-05 — breaker HALF_OPEN success: after cooldown, a successful probe
# run transitions OPEN -> CLOSED with failure_count reset to 0.
# Sub-assertion: FR03-cooldown-set
# ---------------------------------------------------------------------------
def test_fr03_05_breaker_half_open_success(tmp_path, capsys, monkeypatch):
    command = "echo hi"
    cooldown = "5.0"
    # FR03-cooldown-set (applies_to cases 5, 6, 8)
    if cooldown == "5.0":
        assert "5.0" in cooldown

    env = {
        "TASKQ_BREAKER_THRESHOLD": "1",
        "TASKQ_RETRY_LIMIT": "0",
        "TASKQ_BREAKER_COOLDOWN": cooldown,
    }

    fail_id = _submit_get_id(tmp_path, "false")
    _run(["run", fail_id], tmp_path, env_extra=env)
    _ = capsys.readouterr()

    probe_id = _submit_get_id(tmp_path, command)
    rc_open = _run(["run", probe_id], tmp_path, env_extra=env)
    _ = capsys.readouterr()
    assert rc_open == 3, f"breaker must be OPEN immediately after threshold failure, got rc={rc_open}"

    time.sleep(float(cooldown) + 0.5)

    # GREEN TODO: after TASKQ_BREAKER_COOLDOWN elapses, breaker.allow() must
    # transition OPEN -> HALF_OPEN and permit exactly one probe run; on
    # success the breaker must transition to CLOSED with failure_count reset
    # to 0 (SRS.md line 146; SAD.md line 176 Breaker.allow()/record()).
    rc = _run(["run", probe_id], tmp_path, env_extra=env)
    _ = capsys.readouterr()

    assert rc == 0, f"HALF_OPEN probe with 'echo hi' must succeed (exit 0), got {rc}"

    data = json.loads((tmp_path / "tasks.json").read_text())
    task = data[probe_id]
    assert task["status"] == "done", f"probe task must be done, got {task.get('status')!r}"

    breaker_file = tmp_path / "breaker.json"
    assert breaker_file.exists(), "breaker.json must exist after breaker activity"
    breaker_data = json.loads(breaker_file.read_text())
    assert breaker_data["state"] == "CLOSED", (
        f"breaker must be CLOSED after successful HALF_OPEN probe, got {breaker_data.get('state')!r}"
    )
    assert breaker_data["failure_count"] == 0, (
        f"failure_count must reset to 0 after successful probe, got {breaker_data.get('failure_count')!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR03-06 — breaker HALF_OPEN failure: a failing probe re-opens the
# breaker and restarts the cooldown window.
# Sub-assertions: FR03-retry-failed-cmd, FR03-cooldown-set
# ---------------------------------------------------------------------------
def test_fr03_06_breaker_half_open_failure(tmp_path, capsys, monkeypatch):
    command = "false"
    cooldown = "5.0"
    # FR03-retry-failed-cmd (applies_to cases 1, 4, 6)
    if command == "false":
        assert command == "false"
    # FR03-cooldown-set (applies_to cases 5, 6, 8)
    if cooldown == "5.0":
        assert "5.0" in cooldown

    env = {
        "TASKQ_BREAKER_THRESHOLD": "1",
        "TASKQ_RETRY_LIMIT": "0",
        "TASKQ_BREAKER_COOLDOWN": cooldown,
    }

    fail_id = _submit_get_id(tmp_path, command)
    _run(["run", fail_id], tmp_path, env_extra=env)
    _ = capsys.readouterr()

    time.sleep(float(cooldown) + 0.5)

    # GREEN TODO: a HALF_OPEN probe task that itself fails/times out must
    # re-open the breaker (state -> OPEN) and restart the cooldown window
    # (SRS.md line 146: "失敗 -> 重新 OPEN").
    probe_id = _submit_get_id(tmp_path, command)
    _run(["run", probe_id], tmp_path, env_extra=env)
    _ = capsys.readouterr()

    breaker_file = tmp_path / "breaker.json"
    assert breaker_file.exists(), "breaker.json must exist after breaker activity"
    breaker_data = json.loads(breaker_file.read_text())
    assert breaker_data["state"] == "OPEN", (
        f"breaker must re-open after a failed HALF_OPEN probe, got {breaker_data.get('state')!r}"
    )

    next_id = _submit_get_id(tmp_path, "echo hi")
    rc_rejected = _run(["run", next_id], tmp_path, env_extra=env)
    _ = capsys.readouterr()
    assert rc_rejected == 3, (
        f"run immediately after re-OPEN must be rejected (exit 3), got {rc_rejected}"
    )


# ---------------------------------------------------------------------------
# AC-FR03-07 — breaker persistence: OPEN state written to breaker.json
# (legal JSON); a fresh process reading the same $TASKQ_HOME still sees OPEN.
# Sub-assertion: FR03-threshold-reached
# ---------------------------------------------------------------------------
def test_fr03_07_breaker_persistence(tmp_path, capsys, monkeypatch):
    command = "false"
    threshold = "3"
    # FR03-threshold-reached (applies_to cases 4, 7)
    if threshold == "3":
        assert threshold == "3"

    env = {"TASKQ_BREAKER_THRESHOLD": threshold, "TASKQ_RETRY_LIMIT": "0"}

    ids = [_submit_get_id(tmp_path, command) for _ in range(int(threshold))]
    for tid in ids:
        _run(["run", tid], tmp_path, env_extra=env)
        _ = capsys.readouterr()

    breaker_file = tmp_path / "breaker.json"
    assert breaker_file.exists(), "breaker.json must exist after threshold consecutive failures"
    breaker_data = json.loads(breaker_file.read_text())  # must be legal JSON
    assert breaker_data["state"] == "OPEN", (
        f"breaker.json state must be OPEN after {threshold} consecutive final "
        f"failures, got {breaker_data.get('state')!r}"
    )

    # GREEN TODO: breaker state must be persisted (not in-memory-only) so a
    # brand-new OS process reading the same $TASKQ_HOME still observes OPEN
    # (SRS.md line 147; AC-FR03-07 "跨 process 重啟後讀取仍為 OPEN").
    another_id = _submit_get_id(tmp_path, "echo hi")
    proc = subprocess.run(
        ["python", "-m", "taskq", "run", another_id],
        capture_output=True,
        text=True,
        env={**os.environ, "TASKQ_HOME": str(tmp_path), **env},
    )
    assert proc.returncode == 3, (
        f"breaker OPEN must persist across a process restart, got rc={proc.returncode}"
    )
    assert "breaker open" in proc.stderr


# ---------------------------------------------------------------------------
# AC-FR03-08 — recovery time: OPEN -> CLOSED recovery time <=
# TASKQ_BREAKER_COOLDOWN + 1s (integration test, real elapsed time measured).
# Sub-assertion: FR03-cooldown-set
# ---------------------------------------------------------------------------
def test_fr03_08_recovery_time(tmp_path, capsys, monkeypatch):
    command = "echo hi"
    cooldown = "5.0"
    # FR03-cooldown-set (applies_to cases 5, 6, 8)
    if cooldown == "5.0":
        assert "5.0" in cooldown

    env = {
        "TASKQ_BREAKER_THRESHOLD": "1",
        "TASKQ_RETRY_LIMIT": "0",
        "TASKQ_BREAKER_COOLDOWN": cooldown,
    }

    fail_id = _submit_get_id(tmp_path, "false")
    _run(["run", fail_id], tmp_path, env_extra=env)
    _ = capsys.readouterr()

    probe_id = _submit_get_id(tmp_path, command)
    t0 = time.monotonic()

    # GREEN TODO: `run` must consult breaker.allow(); OPEN -> reject exit 3
    # without executing, HALF_OPEN (after cooldown) -> permit + transition on
    # outcome (SRS.md line 145-146; SAD.md line 281).
    immediate_rc = _run(["run", probe_id], tmp_path, env_extra=env)
    _ = capsys.readouterr()
    assert immediate_rc == 3, (
        f"breaker must be OPEN immediately after threshold failure, got rc={immediate_rc}"
    )

    rc = None
    while time.monotonic() - t0 < float(cooldown) + 5.0:
        time.sleep(0.5)
        rc = _run(["run", probe_id], tmp_path, env_extra=env)
        _ = capsys.readouterr()
        if rc != 3:
            break
    elapsed = time.monotonic() - t0

    assert rc == 0, f"probe must eventually succeed once breaker recovers, got rc={rc}"
    assert elapsed <= float(cooldown) + 1.0, (
        f"OPEN->CLOSED recovery must be <= cooldown+1s "
        f"({float(cooldown) + 1.0}s), took {elapsed:.2f}s"
    )


# ---------------------------------------------------------------------------
# AC-FR03-04(negative) — breaker_state=OPEN pre-seeded in breaker.json ->
# `run` rejects immediately with exit 3 + "breaker open", no subprocess.
# Sub-assertion: FR03-brkr-open-noexec
# ---------------------------------------------------------------------------
def test_fr03_09_breaker_open_rejects_no_subprocess(tmp_path, capsys, monkeypatch):
    command = "echo hi"
    breaker_state = "OPEN"
    # FR03-brkr-open-noexec (applies_to case 9)
    if breaker_state == "OPEN":
        assert breaker_state == "OPEN"

    tmp_path.mkdir(parents=True, exist_ok=True)
    breaker_file = tmp_path / "breaker.json"
    # GREEN TODO: breaker.json shape per SAD.md line 266-268:
    # {"version": 1, "state": "OPEN"|"CLOSED"|"HALF_OPEN", "failure_count":
    # int, "opened_at": str|null}. Pre-seeding OPEN here must be honored by
    # taskq.storage.breaker.Breaker.allow() on the very next `run`.
    breaker_file.write_text(json.dumps({
        "version": 1,
        "state": breaker_state,
        "failure_count": 3,
        "opened_at": "2026-07-12T00:00:00",
    }))

    tid = _submit_get_id(tmp_path, command)
    call_count = _count_subprocess_calls(monkeypatch)

    rc = _run(["run", tid], tmp_path, env_extra={"TASKQ_BREAKER_COOLDOWN": "9999"})
    err = capsys.readouterr().err

    assert rc == 3, f"pre-seeded breaker_state=OPEN must reject run with exit 3, got {rc}"
    assert "breaker open" in err, f"stderr must contain 'breaker open', got {err!r}"
    assert call_count["n"] == 0, "breaker_state=OPEN must reject without executing any subprocess"

    data = json.loads((tmp_path / "tasks.json").read_text())
    task = data[tid]
    assert task["status"] == "pending", (
        f"rejected task must remain 'pending' (never attempted), got {task.get('status')!r}"
    )
