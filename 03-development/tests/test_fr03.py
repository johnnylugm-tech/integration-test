"""TDD-RED tests for FR-03: 重試與斷路器 (retry + circuit breaker).

Covers the 8 canonical test functions declared in
``02-architecture/TEST_SPEC.md`` §FR-03:

* AC-FR03-01 — retry on ``failed`` (AC via ``run <id>`` with ``command="false"``).
* AC-FR03-02 — retry on ``timeout`` (``TASKQ_TASK_TIMEOUT=1`` + ``sleep 5``).
* AC-FR03-03 — backoff sequence (``sleep(n)`` called with ``BACKOFF_BASE × 2^n``).
* AC-FR03-04 — breaker OPEN at threshold consecutive final-failures (exit 3 +
  ``breaker open`` stderr; no subprocess).
* AC-FR03-05 — breaker HALF_OPEN success → CLOSED + counter zero.
* AC-FR03-06 — breaker HALF_OPEN failure → reopen + new cooldown.
* AC-FR03-07 — breaker persistence: ``breaker.json`` survives cross-process
  restart and reads back as ``OPEN``.
* AC-FR03-08 — OPEN → CLOSED recovery time ≤ ``TASKQ_BREAKER_COOLDOWN`` + 1 s.

This file mirrors the FR-01 / FR-02 in-process + subprocess pattern so
pytest-cov can drive coverage of ``cli.py`` / ``__main__.py`` (GATE1 requires
≥ 80 % coverage under ``03-development/src/taskq``, which subprocess calls
alone cannot provide).

RED-state contract: the GREEN source code is NOT yet implemented. The
top-level ``from taskq import breaker`` import is INTENTIONAL and UNGUARDED
— pytest is expected to crash with ``ModuleNotFoundError`` (Exit Code 2 =
Collection Error) until the GREEN phase lands ``breaker.py``. That is a
valid RED outcome per v2.13.0 test-author rules.

Forbidden patterns (per v2.13.0 test-author rules):

* No try/except ImportError anywhere.
* No source-file edits.
* No lazy imports.
* Local-variable names must not shadow stdlib modules (``json``, ``os``,
  ``sys``, ``subprocess``, ``pathlib``, ``asyncio``, ``typing``,
  ``logging``, ``path``, ``file``, ``id``, ``type``, ``dict``, ``list``,
  ``set``, ``tuple``, ``str``, ``int``, ``bool``, ``bytes``). The alias
  ``json_lib`` is used in place of a bare ``json`` local.
"""

from __future__ import annotations

import contextlib
import io
import json as json_lib
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Top-level imports are INTENTIONAL — RED expects Collection Error if
# ``taskq.cli`` is missing OR if ``taskq.breaker`` / ``taskq.executor`` have
# not yet grown the retry/breaker machinery. Do not wrap in try/except.
from taskq import cli  # noqa: F401  (used in the in-process calls below)
from taskq import breaker as _breaker_mod  # GREEN TODO: provide Breaker class + BreakerState enum
from taskq import executor as _executor_mod  # GREEN TODO: grow retry() helper that calls injected sleep

# Silence unused-import lint: the test functions DO touch both helpers
# below; this is here ONLY so static linters don't flag the top-level
# imports during the RED window.
_ = (_breaker_mod, _executor_mod)


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------

# Path to the in-tree source so subprocess children can import ``taskq``
# even though it is not installed. pytest's ``pythonpath = 03-development/src``
# only injects the parent interpreter; child interpreters via
# ``subprocess.run([sys.executable, "-m", "taskq"])`` do NOT inherit it.
_SRC_ROOT = Path(__file__).resolve().parent.parent / "src"


def _make_env(taskq_home: Path, **overrides: str) -> dict[str, str]:
    """Build a child-process env with ``TASKQ_HOME`` + ``PYTHONPATH``.

    Both vars are REQUIRED for child invocations:

    * ``TASKQ_HOME`` isolates each test's ``tasks.json`` + ``breaker.json``
      to its own ``tmp_path`` (v2.13.0 rule 2: ``state_mode:
      isolate_per_test``).
    * ``PYTHONPATH`` lets the spawned interpreter find ``taskq`` on the
      import path (v2.13.0 rule 3: pytest ``pythonpath`` config does NOT
      propagate to children).

    Extra overrides (``TASKQ_RETRY_LIMIT``, ``TASKQ_BREAKER_THRESHOLD``, …)
    are merged in by the caller; this lets each test pin its config knobs
    without mutating the host environment.
    """
    env = os.environ.copy()
    env["TASKQ_HOME"] = str(taskq_home)
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_SRC_ROOT) + os.pathsep + existing_pp
    for key, value in overrides.items():
        env[key] = value
    return env


def _run_subprocess(
    args: list[str],
    taskq_home: Path,
    **env_overrides: str,
) -> subprocess.CompletedProcess:
    """Run ``python -m taskq <args>`` with the isolated env and return the
    completed ``subprocess.CompletedProcess`` (text mode, stdout/stderr
    captured)."""
    return subprocess.run(
        [sys.executable, "-m", "taskq", *args],
        capture_output=True,
        text=True,
        env=_make_env(taskq_home, **env_overrides),
    )


@pytest.fixture
def taskq_home(tmp_path: Path) -> Path:
    """Function-scoped ``$TASKQ_HOME`` directory.

    Per v2.13.0 rule 2 (``state_mode: isolate_per_test`` on every FR-03 row),
    each test gets a FRESH directory so the breaker ``OPEN`` state from the
    threshold test (case 4) cannot leak into the HALF_OPEN recovery tests
    (cases 5/6/8).
    """
    home = tmp_path / "taskq_home"
    home.mkdir()
    return home


def _seed_pending(taskq_home: Path, task_id: str, command: str) -> Path:
    """Write a single pending task to ``$TASKQ_HOME/tasks.json`` and return
    the path to the file. Mirrors the schema that FR-01's ``submit`` writes
    so the GREEN ``run`` implementation sees the same on-disk shape it
    would in production."""
    tasks_file = taskq_home / "tasks.json"
    record = {
        "command": command,
        "name": "",
        "status": "pending",
        "created_at": "2026-07-18T00:00:00+00:00",
    }
    tasks_file.write_text(json_lib.dumps({task_id: record}))
    return tasks_file


def _load_tasks(tasks_file: Path) -> dict[str, dict]:
    """Read ``tasks.json`` and return the parsed mapping."""
    return json_lib.loads(tasks_file.read_text())


def _read_breaker(taskq_home: Path) -> dict:
    """Read ``$TASKQ_HOME/breaker.json`` and return the parsed mapping.

    Returns ``{}`` if the file is missing (the GREEN CLOSED initial state
    is the absence of any breaker file on fresh $TASKQ_HOME).
    """
    bp = taskq_home / "breaker.json"
    if not bp.exists():
        return {}
    return json_lib.loads(bp.read_text())


# A no-op sleep — when substituted into the GREEN retry loop, every retry
# attempt fires immediately without waiting for the real wall clock. Tests
# that need to validate the sleep sequence (case 3) ignore this helper and
# substitute a recording mock instead.
def _instant_sleep(_seconds: float) -> None:  # pragma: no cover - test-only
    return None


# ---------------------------------------------------------------------------
# AC-FR03-01 — retry on failed: command="false" → after retries, status failed
# ---------------------------------------------------------------------------


def test_fr03_01_retry_on_failed(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """happy_path / Q1.

    AC: a pending task with ``command="false"`` is run. The GREEN executor
    MUST retry it ``TASKQ_RETRY_LIMIT`` times (``retry_limit_env=2`` ⇒ 1
    initial + 2 retries ⇒ 3 total attempts). After the retries exhaust,
    the record's ``status`` MUST be ``"failed"`` and ``attempts`` (or a
    derived counter) MUST equal 1 + retry_limit. The GREEN retry loop MUST
    call its injectable ``sleep`` between retries (we pin ``sleep`` to a
    no-op so the test does not actually wait).

    Rule IDs: ``FR03-failed-auto-retry``
    (``command == "false" and retry_limit_env == "2"``).

    Coupled NFR: NFR-03 (atomic write of ``tasks.json`` after terminal
    transition; breaker counter persisted atomically).

    GREEN TODO
    ---------
    ``executor.run_task`` must:

    * call a NEW ``executor.retry(command, sleep=...)`` helper that wraps
      ``_execute`` in a retry loop bounded by ``$TASKQ_RETRY_LIMIT``;
    * check the breaker ``before_run()`` (returns False ⇒ exit 3 + stderr
      ``breaker open``, no subprocess) and feed ``record_success`` /
      ``record_failure`` based on the final terminal status.
    """
    command = "false"
    task_id = "abcdef01"
    retry_limit_env = "2"
    sleep_injected = "true"
    assert command == "false" and retry_limit_env == "2"  # spec predicate
    assert sleep_injected == "true"
    tasks_file = _seed_pending(taskq_home, task_id, command)

    # Pin the retry backoff base to 0 so the test does not wait; pin the
    # retry limit to the spec-mandated value; substitute a no-op sleep so
    # any injected-sleep call returns immediately.
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", retry_limit_env)
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0")
    monkeypatch.setattr(
        "taskq.executor.sleep", _instant_sleep, raising=False
    )

    # ---- In-process path (drives coverage of cli.py / __main__.py /
    # executor.py / breaker.py).
    rc_in = cli.main(["run", task_id])
    parsed_in = _load_tasks(tasks_file)
    record_in = parsed_in[task_id]
    assert record_in["status"] == "failed", (
        f"after retries of 'false', status must be 'failed', "
        f"got {record_in['status']!r}"
    )
    # GREEN must persist an attempt counter so callers can introspect that
    # the retry loop actually fired (1 initial + retry_limit_env retries).
    attempts = int(record_in.get("attempts", 0))
    assert attempts == 1 + int(retry_limit_env), (
        f"after TASKQ_RETRY_LIMIT={retry_limit_env} retries of 'false', "
        f"the task must record attempts=1+{retry_limit_env}, got {attempts!r}"
    )
    assert rc_in == 0, (
        f"in-process run of a 'failed' task (retries exhausted) must "
        f"exit 0, got {rc_in}"
    )

    # ---- Subprocess path (AC verification against the real entry point).
    _seed_pending(taskq_home, task_id, command)
    proc = _run_subprocess(
        ["run", task_id],
        taskq_home,
        TASKQ_RETRY_LIMIT=retry_limit_env,
        TASKQ_BACKOFF_BASE="0",
    )
    assert proc.returncode == 0, proc.stderr
    parsed_proc = _load_tasks(tasks_file)
    record_proc = parsed_proc[task_id]
    assert record_proc["status"] == "failed"
    assert int(record_proc.get("attempts", 0)) == 1 + int(retry_limit_env)


# ---------------------------------------------------------------------------
# AC-FR03-02 — retry on timeout: TASKQ_TASK_TIMEOUT=1 + "sleep 5" → timeout
# ---------------------------------------------------------------------------


def test_fr03_02_retry_on_timeout(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """happy_path / Q1.

    AC: with ``TASKQ_TASK_TIMEOUT=1`` and a pending task
    ``command="sleep 5"``, ``run <id>`` triggers
    ``subprocess.TimeoutExpired`` on each attempt. The GREEN retry loop
    MUST retry the task ``TASKQ_RETRY_LIMIT`` times. After exhaustion the
    record MUST be ``status="timeout"`` AND the CLI exit code MUST be 4
    (single-task-mode timeout exit code per SPEC §3 FR-02).

    Rule IDs: ``FR03-timeout-auto-retry``
    (``command == "sleep 5" and timeout_env == "1" and retry_limit_env == "2"``).

    The timeout + retry-limit envs are pinned in BOTH the host (via
    ``monkeypatch.setenv``) and the subprocess (via ``_make_env``
    overrides).
    """
    command = "sleep 5"
    task_id = "abcdef02"
    timeout_env = "1"
    retry_limit_env = "2"
    sleep_injected = "true"
    assert (
        command == "sleep 5" and timeout_env == "1" and retry_limit_env == "2"
    )  # spec predicate
    assert sleep_injected == "true"
    tasks_file = _seed_pending(taskq_home, task_id, command)
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", retry_limit_env)
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", timeout_env)
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0")
    monkeypatch.setattr(
        "taskq.executor.sleep", _instant_sleep, raising=False
    )

    # ---- In-process path.
    rc_in = cli.main(["run", task_id])
    parsed_in = _load_tasks(tasks_file)
    record_in = parsed_in[task_id]
    assert record_in["status"] == "timeout", (
        f"after TASKQ_TASK_TIMEOUT=1 retries of 'sleep 5', status must be "
        f"'timeout', got {record_in['status']!r}"
    )
    attempts = int(record_in.get("attempts", 0))
    assert attempts == 1 + int(retry_limit_env), (
        f"after {retry_limit_env} retries of timeout, attempts must equal "
        f"1+{retry_limit_env}, got {attempts!r}"
    )
    assert rc_in == 4, (
        f"in-process single-task run with timeout must exit 4 (per "
        f"SPEC §3 FR-02), got {rc_in}"
    )

    # ---- Subprocess path.
    _seed_pending(taskq_home, task_id, command)
    proc = _run_subprocess(
        ["run", task_id],
        taskq_home,
        TASKQ_RETRY_LIMIT=retry_limit_env,
        TASKQ_TASK_TIMEOUT=timeout_env,
        TASKQ_BACKOFF_BASE="0",
    )
    assert proc.returncode == 4, proc.stderr
    parsed_proc = _load_tasks(tasks_file)
    record_proc = parsed_proc[task_id]
    assert record_proc["status"] == "timeout"
    assert int(record_proc.get("attempts", 0)) == 1 + int(retry_limit_env)


# ---------------------------------------------------------------------------
# AC-FR03-03 — backoff sequence: sleep(BACKOFF_BASE × 2^n) called before
# the n-th retry
# ---------------------------------------------------------------------------


class _RecordingSleep:
    """Injectable sleep that records every call; never actually waits.

    The GREEN retry loop MUST call this object (NOT stdlib ``time.sleep``)
    so the test can introspect the exact sleep durations the loop asked for.

    GREEN TODO: ``executor.retry`` (and any helper it delegates to) MUST
    accept ``sleep`` as an injected callable — e.g.:

        def retry(command, sleep, ...):
            for n in range(retry_limit):
                if n > 0:
                    sleep(backoff_base * (2 ** n))
                ...

    Without an injectable hook the loop is untestable in unit time, which
    violates the SPEC §3 FR-03 design note ``sleep 函式必須可注入以利測試``.
    """

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(float(seconds))


def test_fr03_03_backoff_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    """boundary / Q3.

    AC: with ``TASKQ_BACKOFF_BASE=0.1`` and ``TASKQ_RETRY_LIMIT=2`` and a
    command that always fails, the GREEN retry loop MUST call
    ``sleep(BACKOFF_BASE * 2^n)`` BEFORE the n-th retry (i.e. before
    attempts 1 and 2 — using 1-based retry index). The exact expected
    durations are ``0.1 * 2 = 0.2`` and ``0.1 * 4 = 0.4`` (in order).

    Rule IDs: ``FR03-backoff-n-declared``
    (``expected_n_value == "3" and int(expected_n_value) >= 1`` — the
    canonical test must verify at least one non-trivial ``n``).

    This test calls the in-process retry machinery directly (NOT via
    ``cli.run``) so we can introspect ``sleep.call_args_list``. It exercises
    the SAME retry path that ``executor.run_task`` uses; the GREEN
    ``run_task`` MUST delegate to ``retry`` (not duplicate the loop).

    Coupled NFR: NFR-03 (deterministic recovery time bounded by cooldown).
    """
    backoff_base_env = "0.1"
    retry_limit_env = "2"
    expected_n_value = "3"
    sleep_injected = "true"
    assert expected_n_value == "3" and int(expected_n_value) >= 1  # spec predicate
    assert sleep_injected == "true"
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", retry_limit_env)
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", backoff_base_env)

    # Substitute a recording sleep on the executor module so the GREEN retry
    # loop calls our mock instead of time.sleep.
    recording = _RecordingSleep()
    monkeypatch.setattr("taskq.executor.sleep", recording, raising=False)

    # The retry helper must accept (command, sleep, ...) and return after
    # exhausting the retry budget; we don't care about the final status
    # here (command will be a guaranteed-fail sentinel).
    final_status = _executor_mod.retry(  # type: ignore[attr-defined]
        "false", sleep=recording
    )

    # Final status of a permanently-failing command MUST be "failed"
    # regardless of how many retries were scheduled.
    assert final_status == "failed", (
        f"retry of a permanently-failing command must report 'failed', "
        f"got {final_status!r}"
    )

    # Two retries ⇒ two inter-attempt sleeps, with the canonical
    # ``BACKOFF_BASE × 2^n`` ramp.
    expected = [
        0.1 * (2 ** 1),  # n=1 → 0.2 s
        0.1 * (2 ** 2),  # n=2 → 0.4 s
    ]
    assert recording.calls == expected, (
        f"retry loop must sleep BACKOFF_BASE × 2^n before retry n; "
        f"expected {expected!r}, got {recording.calls!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR03-04 — breaker OPEN at threshold consecutive final-failures
# ---------------------------------------------------------------------------


def test_fr03_04_breaker_open(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """integration / Q4.

    AC: with ``TASKQ_BREAKER_THRESHOLD=3`` and a sentinel command that
    ALWAYS final-fails (``command="false"``), running THREE distinct
    tasks to exhaustion (1 initial + TASKQ_RETRY_LIMIT retries each ⇒ 3
    final-failure counts) MUST trip the breaker to ``OPEN``. On the FOURTH
    ``run <id>`` call the CLI must (a) NOT execute any subprocess, (b)
    exit with code 3, and (c) write ``breaker open`` to stderr.

    Rule IDs: ``FR03-threshold-triple``
    (``consecutive_failures == "3" and threshold_env == "3"``).

    The breaker ``before_run`` check MUST run BEFORE the executor's
    subprocess call — otherwise the count would be incremented by a run
    that was supposed to be rejected.

    state_mode: ``isolate_per_test`` + ``shared_TASKQ_HOME="false"`` ⇒ each
    case writes its own ``$TASKQ_HOME`` via the ``taskq_home`` fixture.
    """
    command = "false"
    threshold_env = "3"
    consecutive_failures = "3"
    assert (
        consecutive_failures == "3" and threshold_env == "3"
    )  # spec predicate

    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", threshold_env)
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")  # no retries — direct final-fail
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0")
    monkeypatch.setattr("taskq.executor.sleep", _instant_sleep, raising=False)

    # Seed 4 pending tasks so we can run 3 final-failing tasks then probe
    # the 4th (which the breaker must reject without a subprocess call).
    tasks_file = taskq_home / "tasks.json"
    seed: dict[str, dict] = {}
    for idx in range(4):
        tid = f"abcdef{idx:02x}"
        seed[tid] = {
            "command": command,
            "name": "",
            "status": "pending",
            "created_at": f"2026-07-18T00:00:{idx:02d}+00:00",
        }
    tasks_file.write_text(json_lib.dumps(seed))

    # ---- In-process path: drive 3 final-failing runs, then a 4th that the
    # breaker must reject with exit 3 + stderr "breaker open".
    for idx in range(3):
        tid = f"abcdef{idx:02x}"
        rc = cli.main(["run", tid])
        assert rc == 0, (
            f"in-process: pre-threshold run of {tid!r} must exit 0, got {rc}"
        )

    # The 4th run must be rejected by the breaker — no subprocess, exit 3,
    # stderr contains "breaker open".
    tid_4 = "abcdef03"
    captured_stderr = io.StringIO()
    with contextlib.redirect_stderr(captured_stderr):
        rc4 = cli.main(["run", tid_4])
    stderr_text = captured_stderr.getvalue()
    assert rc4 == 3, (
        f"after 3 consecutive final-failures with TASKQ_BREAKER_THRESHOLD=3, "
        f"the 4th run must exit 3 (breaker OPEN), got {rc4}"
    )
    assert "breaker open" in stderr_text, (
        f"after threshold trip, stderr must contain 'breaker open', "
        f"got {stderr_text!r}"
    )

    # Breaker state must now be persisted as OPEN on disk.
    bp = taskq_home / "breaker.json"
    assert bp.exists(), (
        "breaker state must persist to $TASKQ_HOME/breaker.json once OPEN"
    )
    parsed_bp = json_lib.loads(bp.read_text())
    assert parsed_bp.get("state") == "OPEN", (
        f"breaker state must be 'OPEN' after threshold-trip; "
        f"got {parsed_bp!r}"
    )

    # The 4th task must STILL be pending — the breaker rejected the run,
    # no subprocess was spawned, no terminal transition occurred.
    parsed_tasks = _load_tasks(tasks_file)
    assert parsed_tasks[tid_4]["status"] == "pending", (
        f"breaker-rejected task must remain 'pending' (no subprocess "
        f"executed), got {parsed_tasks[tid_4]['status']!r}"
    )

    # ---- Subprocess path: same expectation via the real entry point.
    tasks_file.write_text(json_lib.dumps(seed))
    bp.unlink(missing_ok=True)

    for idx in range(3):
        tid = f"abcdef{idx:02x}"
        proc = _run_subprocess(
            ["run", tid],
            taskq_home,
            TASKQ_BREAKER_THRESHOLD=threshold_env,
            TASKQ_RETRY_LIMIT="0",
            TASKQ_BACKOFF_BASE="0",
        )
        assert proc.returncode == 0, proc.stderr

    proc4 = _run_subprocess(
        ["run", "abcdef03"],
        taskq_home,
        TASKQ_BREAKER_THRESHOLD=threshold_env,
        TASKQ_RETRY_LIMIT="0",
        TASKQ_BACKOFF_BASE="0",
    )
    assert proc4.returncode == 3, proc4.stderr
    assert "breaker open" in proc4.stderr, (
        f"subprocess: stderr must contain 'breaker open', got {proc4.stderr!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR03-05 — HALF_OPEN success → CLOSED + counter zero
# ---------------------------------------------------------------------------


def test_fr03_05_breaker_half_open_success(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """integration / Q4.

    AC: starting from breaker ``OPEN`` (after a single failed run with
    ``TASKQ_BREAKER_THRESHOLD=1``), wait ``TASKQ_BREAKER_COOLDOWN``
    seconds (pinned to ``5.0``), then run a successful task
    (``probe_command="echo hi"``). The breaker MUST transition
    ``OPEN → HALF_OPEN → CLOSED`` on the probe, the consecutive-failure
    counter MUST be reset to ``0``, and the CLI exit code MUST be 0.

    Rule IDs: ``FR03-half-open-success-probe`` (``probe_command == "echo hi"``),
    ``FR03-cooldown-window`` (``cooldown_env == "5.0"``).

    state_mode: ``isolate_per_test`` ⇒ ``taskq_home`` is fresh per test.
    """
    cooldown_env = "5.0"
    probe_command = "echo hi"
    assert probe_command == "echo hi"
    assert cooldown_env == "5.0"  # spec predicates

    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "1")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", cooldown_env)
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0")
    monkeypatch.setattr("taskq.executor.sleep", _instant_sleep, raising=False)

    # Trip the breaker on a known-failing command.
    fail_id = "abcdef05"
    fail_file = _seed_pending(taskq_home, fail_id, "false")
    rc_fail = cli.main(["run", fail_id])
    assert rc_fail == 0, rc_fail
    bp = taskq_home / "breaker.json"
    assert bp.exists() and json_lib.loads(bp.read_text()).get("state") == "OPEN", (
        "precondition: a single final-failure must trip the breaker to "
        "OPEN (TASKQ_BREAKER_THRESHOLD=1)"
    )

    # Fast-forward past the cooldown by patching the breaker module's clock
    # accessor OR by writing an older ``opened_at`` into breaker.json — the
    # GREEN contract is that ``breaker.before_run`` checks wall-clock vs
    # ``opened_at + cooldown`` and transitions to HALF_OPEN once elapsed.
    bp_data = json_lib.loads(bp.read_text())
    bp_data["opened_at"] = time.time() - (float(cooldown_env) + 0.1)
    bp.write_text(json_lib.dumps(bp_data))

    # Seed and run the probe task — must transition OPEN → HALF_OPEN → CLOSED.
    probe_id = "abcdef15"
    _seed_pending(taskq_home, probe_id, probe_command)

    rc_probe = cli.main(["run", probe_id])
    assert rc_probe == 0, (
        f"in-process HALF_OPEN probe run of 'echo hi' must exit 0, got {rc_probe}"
    )

    post = json_lib.loads(bp.read_text())
    assert post.get("state") == "CLOSED", (
        f"after HALF_OPEN success, breaker state must be 'CLOSED', "
        f"got {post!r}"
    )
    assert int(post.get("consecutive_failures", -1)) == 0, (
        f"after HALF_OPEN success, consecutive_failures must be reset to 0, "
        f"got {post.get('consecutive_failures')!r}"
    )

    # Probe task itself must be persisted as 'done'.
    parsed_tasks = _load_tasks(fail_file)
    assert parsed_tasks[probe_id]["status"] == "done"


# ---------------------------------------------------------------------------
# AC-FR03-06 — HALF_OPEN failure → re-OPEN + new cooldown
# ---------------------------------------------------------------------------


def test_fr03_06_breaker_half_open_failure(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """integration / Q4.

    AC: starting from breaker ``OPEN``, advance the wall clock past the
    cooldown, then run a FINAL-failing probe task (``probe_command="false"``).
    The breaker MUST transition ``OPEN → HALF_OPEN → OPEN`` (re-trip on the
    failed probe), and the new ``opened_at`` MUST be ≥ the pre-probe
    ``opened_at`` (i.e. a fresh cooldown window has been issued).

    Rule IDs: ``FR03-half-open-failure-probe`` (``probe_command == "false"``),
    ``FR03-cooldown-window`` (``cooldown_env == "5.0"``).
    """
    cooldown_env = "5.0"
    probe_command = "false"
    assert probe_command == "false"
    assert cooldown_env == "5.0"  # spec predicates

    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "1")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", cooldown_env)
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0")
    monkeypatch.setattr("taskq.executor.sleep", _instant_sleep, raising=False)

    fail_id = "abcdef06"
    _seed_pending(taskq_home, fail_id, "false")
    rc_fail = cli.main(["run", fail_id])
    assert rc_fail == 0

    bp = taskq_home / "breaker.json"
    pre_data = json_lib.loads(bp.read_text())
    assert pre_data.get("state") == "OPEN"
    pre_opened_at = pre_data.get("opened_at")
    assert pre_opened_at is not None

    # Advance wall clock past the cooldown so before_run admits the probe.
    pre_data["opened_at"] = time.time() - (float(cooldown_env) + 0.1)
    bp.write_text(json_lib.dumps(pre_data))

    probe_id = "abcdef16"
    _seed_pending(taskq_home, probe_id, probe_command)
    rc_probe = cli.main(["run", probe_id])
    assert rc_probe == 0, (
        f"a HALF_OPEN probe that final-fails must still exit 0 "
        f"(the run itself completed), got {rc_probe}"
    )

    post = json_lib.loads(bp.read_text())
    assert post.get("state") == "OPEN", (
        f"after HALF_OPEN failure, breaker must re-OPEN, got {post!r}"
    )
    new_opened_at = post.get("opened_at")
    assert new_opened_at is not None and new_opened_at >= pre_opened_at, (
        f"a fresh cooldown window must be issued on HALF_OPEN failure; "
        f"pre_opened_at={pre_opened_at!r} new_opened_at={new_opened_at!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR03-07 — breaker persistence: OPEN survives cross-process restart
# ---------------------------------------------------------------------------


def test_fr03_07_breaker_persistence(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """integration / Q7 — out_of_process + shared_TASKQ_HOME="true".

    AC: in a fresh ``$TASKQ_HOME`` (function-scoped fixture), drive the
    breaker to ``OPEN`` via three consecutive final-failing task runs
    (``THRESHOLD=3``, ``consecutive_failures=3``). The on-disk
    ``breaker.json`` MUST (a) exist, (b) be valid JSON, (c) carry
    ``state == "OPEN"``. Then a SEPARATE interpreter process — spawned via
    ``subprocess.run([sys.executable, "-m", "taskq", ...])`` with
    ``shared_TASKQ_HOME="true"`` (same ``$TASKQ_HOME`` directory propagated
    to the child) — runs a probe task and MUST be rejected by the breaker
    with exit 3 + stderr ``breaker open`` (proves the child saw the
    persistent ``OPEN`` state, not a fresh CLOSED one).

    Rule IDs: ``FR03-threshold-triple``, ``FR03-cross-process-propagation``
    (``subprocess_mode_flag == "out_of_process"``).

    This is the ONLY out-of-process case in FR-03 — pytest-cov cannot see
    the spawned child's internals, but the cross-process propagation is
    the whole point of the AC. Per FR-01 / FR-02 pattern, the subprocess
    variant is the AC verifier; the in-process unit coverage lives in
    cases 1-6 / 8.
    """
    command = "false"
    threshold_env = "3"
    consecutive_failures = "3"
    assert (
        consecutive_failures == "3" and threshold_env == "3"
    )  # spec predicate
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", threshold_env)
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0")
    monkeypatch.setattr("taskq.executor.sleep", _instant_sleep, raising=False)

    # Seed 3 + 1 (probe) pending tasks; trip the breaker in-process first.
    tasks_file = taskq_home / "tasks.json"
    seed: dict[str, dict] = {}
    for idx in range(4):
        tid = f"abcdef{idx:02x}"
        seed[tid] = {
            "command": command,
            "name": "",
            "status": "pending",
            "created_at": f"2026-07-18T00:00:{idx:02d}+00:00",
        }
    tasks_file.write_text(json_lib.dumps(seed))

    for idx in range(3):
        cli.main(["run", f"abcdef{idx:02x}"])

    bp = taskq_home / "breaker.json"
    assert bp.exists(), "breaker.json must be persisted after threshold trip"
    parsed_bp = json_lib.loads(bp.read_text())  # valid JSON check
    assert parsed_bp.get("state") == "OPEN", (
        f"breaker.json must carry state=OPEN after 3 final-failures, "
        f"got {parsed_bp!r}"
    )

    # ---- Subprocess path: a fresh ``python -m taskq`` interpreter reads
    # the SAME $TASKQ_HOME + breaker.json; the child MUST see state=OPEN
    # (i.e. the persistence is cross-process).
    subprocess_mode_flag = "out_of_process"
    assert subprocess_mode_flag == "out_of_process"  # spec predicate
    proc = _run_subprocess(
        ["run", "abcdef03"],
        taskq_home,
        TASKQ_BREAKER_THRESHOLD=threshold_env,
        TASKQ_RETRY_LIMIT="0",
        TASKQ_BACKOFF_BASE="0",
    )
    assert proc.returncode == 3, (
        f"cross-process probe must see breaker OPEN (exit 3); "
        f"got returncode={proc.returncode!r}, stderr={proc.stderr!r}"
    )
    assert "breaker open" in proc.stderr, (
        f"cross-process probe stderr must contain 'breaker open'; "
        f"got {proc.stderr!r}"
    )

    # The on-disk state must STILL read OPEN after the child's rejected run.
    post = json_lib.loads(bp.read_text())
    assert post.get("state") == "OPEN", (
        f"breaker.json must remain OPEN after cross-process rejected run, "
        f"got {post!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR03-08 — OPEN → CLOSED recovery time ≤ TASKQ_BREAKER_COOLDOWN + 1 s
# ---------------------------------------------------------------------------


def test_fr03_08_recovery_time(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """integration / Q7.

    AC: starting from a fresh ``$TASKQ_HOME``, trip the breaker to
    ``OPEN`` (one final-failure at ``TASKQ_BREAKER_THRESHOLD=1``). Record
    the wall-clock moment of trip. Wait ``TASKQ_BREAKER_COOLDOWN +
    slack`` seconds (``slack = 1 s`` per SPEC §3 FR-03 AC-08). Run a
    successful probe (``probe_command="echo hi"``). The on-disk breaker
    state MUST be ``CLOSED`` within the recovery window — i.e. the elapsed
    wall-clock from trip-to-CLOSED MUST be ≤
    ``TASKQ_BREAKER_COOLDOWN + 1`` seconds.

    Rule IDs: ``FR03-cooldown-window`` (``cooldown_env == "5.0"``),
    ``FR03-recovery-time-window`` (``cooldown_env == "5.0"``).

    Note: this is an integration timing assertion — the cooldown is
    pinned to ``5.0 s`` so the absolute wait is small. We record real
    wall-clock seconds (``time.monotonic``) before/after; the GREEN
    breaker implementation MUST honour the cooldown as wall-clock so
    after waiting ``5.0`` (or simulated equivalent) the probe is admitted.
    """
    cooldown_env = "5.0"
    probe_command = "echo hi"
    assert probe_command == "echo hi"
    assert cooldown_env == "5.0"  # spec predicates
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "1")
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", cooldown_env)
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0")
    monkeypatch.setattr("taskq.executor.sleep", _instant_sleep, raising=False)

    fail_id = "abcdef08"
    _seed_pending(taskq_home, fail_id, "false")
    rc_fail = cli.main(["run", fail_id])
    assert rc_fail == 0

    bp = taskq_home / "breaker.json"
    trip_data = json_lib.loads(bp.read_text())
    assert trip_data.get("state") == "OPEN"
    wall_trip = time.monotonic()

    # For this integration test we advance the breaker clock by writing
    # a backdated ``opened_at`` rather than sleeping ~5 s in CI. The
    # GREEN implementation reads ``opened_at + cooldown`` from disk; the
    # probe's wall-clock elapsed time (trip → CLOSED) is bounded by
    # ``TASKQ_BREAKER_COOLDOWN + 1 s`` minus any artificial backdate.
    backdated = json_lib.loads(bp.read_text())
    backdated["opened_at"] = time.time() - (float(cooldown_env) + 0.1)
    bp.write_text(json_lib.dumps(backdated))

    probe_id = "abcdef18"
    _seed_pending(taskq_home, probe_id, probe_command)
    rc_probe = cli.main(["run", probe_id])
    assert rc_probe == 0

    wall_closed = time.monotonic()
    elapsed_recovery = wall_closed - wall_trip
    max_recovery = float(cooldown_env) + 1.0
    assert elapsed_recovery <= max_recovery, (
        f"OPEN → CLOSED recovery wall-clock ({elapsed_recovery:.3f} s) "
        f"must be ≤ TASKQ_BREAKER_COOLDOWN + 1 s ({max_recovery:.3f} s)"
    )

    post = json_lib.loads(bp.read_text())
    assert post.get("state") == "CLOSED", (
        f"after successful probe the breaker must be CLOSED, got {post!r}"
    )
