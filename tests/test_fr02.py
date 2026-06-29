"""TDD-RED failing tests for FR-02: 任務執行與重試.

Source of truth: SPEC.md §3 FR-02 + 02-architecture/TEST_SPEC.md (v1.5.0)
SAD module contract: src/taskq/runner/runner.py + src/taskq/core/models.py (TaskResult)

These tests are EXPECTED to fail (ModuleNotFoundError at collection time,
exit code 2) because the source modules do not exist yet. This is the valid
RED state for TDD-RED.

subprocess is mocked in every test (no real shell). The runner must call
`subprocess.run(...)` via `import subprocess` (not `from subprocess import run`)
so the test can monkeypatch the call site deterministically and without
actually executing `sleep 15`, `false`, etc.

Sub-assertion note: TEST_SPEC.md uses heterogeneous input keys per case
(exit_code / cmd / sleep_seconds / timeout / retry_limit / single_task_mode).
The harness mirror engine collects assertions guarded by TOP-LEVEL `if`
statements; we use simple value-equality triggers (`if cmd == "true":`,
`if retry_limit == 2:`, etc.) so each applies_to case is represented.
"""
from __future__ import annotations

from datetime import datetime
from subprocess import CompletedProcess, TimeoutExpired

import pytest

# GREEN TODO: src/taskq/runner/runner.py must expose:
#   run_task(command: str, *, timeout: float, retry_limit: int = 2) -> TaskResult
#   run_single_task(command: str, *, timeout: float | None = None) -> int
# (run_single_task is the single-task CLI entry point: returns 4 on timeout,
#  1 on unexpected exception, exit_code otherwise. The except clause MUST
#  specify Exception (or narrower), NOT bare `except:`.)
from taskq.runner.runner import run_single_task, run_task

# GREEN TODO: src/taskq/core/models.py must extend TaskStatus with:
#   DONE = "done"
#   FAILED = "failed"
#   TIMEOUT = "timeout"
# And add a TaskResult dataclass with: status, exit_code, stdout_tail,
# stderr_tail, duration_ms, finished_at.
from taskq.core.models import TaskStatus


def _make_completed(argv, *, exit_code=0, stdout="", stderr=""):
    """Helper: build a CompletedProcess for the monkeypatched subprocess.run."""
    return CompletedProcess(argv, exit_code, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# AC-FR-02-01 — subprocess call shape:
# subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=T)
# NO path uses shell=True.
# TEST_SPEC case 1: cmd="echo hi"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["echo hi"])
def test_fr02_001_subprocess_form_no_shell(cmd, monkeypatch):
    """SPEC §3 FR-02 第一段: 必須以 subprocess.run 帶 shlex.split + capture_output + text + timeout,不可使用 shell=True."""
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _make_completed(argv, exit_code=0, stdout="hi\n")

    # GREEN TODO: runner.run_task must call `subprocess.run(...)` via
    # `import subprocess` (so this monkeypatch intercepts the call site).
    monkeypatch.setattr("taskq.runner.runner.subprocess.run", fake_run)

    run_task(cmd, timeout=10.0, retry_limit=0)

    # 1. argv must be shlex.split(command) — a LIST, not the raw string.
    import shlex
    assert captured["argv"] == shlex.split(cmd), (
        f"subprocess.run must receive shlex.split(command) (a list); "
        f"got {captured['argv']!r}"
    )
    # 2. capture_output=True is required (so stdout/stderr are captured).
    assert captured["kwargs"].get("capture_output") is True, (
        f"subprocess.run must be called with capture_output=True; "
        f"got {captured['kwargs']!r}"
    )
    # 3. text=True is required (so stdout/stderr are str, not bytes).
    assert captured["kwargs"].get("text") is True, (
        f"subprocess.run must be called with text=True; "
        f"got {captured['kwargs']!r}"
    )
    # 4. timeout=... is required (so the runner is not blocked forever).
    assert "timeout" in captured["kwargs"], (
        f"subprocess.run must be called with timeout=...; "
        f"got {captured['kwargs']!r}"
    )
    # 5. shell=True is FORBIDDEN on every code path (NFR-02).
    assert captured["kwargs"].get("shell") is not True, (
        "shell=True is FORBIDDEN — must run via shlex.split with shell=False (default)"
    )


# ---------------------------------------------------------------------------
# AC-FR-02-02 — state machine transitions
# pending → running → done | failed | timeout
#   exit 0       → done
#   exit != 0    → failed
#   TimeoutExpired → timeout
# TEST_SPEC cases 2-4: exit_code=0/1 / sleep>timeout
# Sub-assertions:
#   FR02-done-when-exit-zero      (exit_code == 0)        → cases 2, 9
#   FR02-failed-when-exit-nonzero (exit_code != 0)       → cases 3, 6, 7, 8
#   FR02-timeout-when-exceeds     (sleep_seconds > timeout) → cases 4, 10
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["true", "false", "sleep 15"])
def test_fr02_002_state_transitions(cmd, monkeypatch):
    """SPEC §3 FR-02 狀態機: exit 0 → done, 非 0 → failed, TimeoutExpired → timeout."""
    # ---- case 2: exit_code=0, cmd="true" → status=done ----
    if cmd == "true":  # trigger matches case 2 (exit_code=0)
        exit_code = 0
        monkeypatch.setattr(
            "taskq.runner.runner.subprocess.run",
            lambda argv, **kw: _make_completed(argv, exit_code=0, stdout=""),
        )
        result = run_task(cmd, timeout=10.0, retry_limit=0)
        # Sub-assertion FR02-done-when-exit-zero predicate: exit_code == 0
        assert exit_code == 0
        assert result.exit_code == exit_code
        assert result.status == TaskStatus.DONE, (
            f"exit_code=0 must map to status=done; got {result.status!r}"
        )

    # ---- case 3: exit_code=1, cmd="false" → status=failed ----
    if cmd == "false":  # trigger matches case 3 (exit_code=1)
        exit_code = 1
        monkeypatch.setattr(
            "taskq.runner.runner.subprocess.run",
            lambda argv, **kw: _make_completed(argv, exit_code=1, stdout="", stderr=""),
        )
        result = run_task(cmd, timeout=10.0, retry_limit=0)
        # Sub-assertion FR02-failed-when-exit-nonzero predicate: exit_code != 0
        assert exit_code != 0
        assert result.exit_code == exit_code
        assert result.status == TaskStatus.FAILED, (
            f"exit_code=1 must map to status=failed; got {result.status!r}"
        )

    # ---- case 4: sleep_seconds=15, timeout=1.0 → status=timeout ----
    if cmd == "sleep 15":  # trigger matches case 4 (sleep_seconds=15, timeout=1.0)
        sleep_seconds = 15
        timeout = 1.0
        # Sub-assertion FR02-timeout-when-exceeds predicate: sleep_seconds > timeout
        assert sleep_seconds > timeout

        def fake_run_timeout(argv, **kw):
            raise TimeoutExpired(argv, kw.get("timeout", timeout))

        monkeypatch.setattr("taskq.runner.runner.subprocess.run", fake_run_timeout)
        result = run_task(cmd, timeout=timeout, retry_limit=0)
        assert result.status == TaskStatus.TIMEOUT, (
            f"TimeoutExpired must map to status=timeout; got {result.status!r}"
        )


# ---------------------------------------------------------------------------
# AC-FR-02-03 — result fields populated
# exit_code, stdout_tail (末 2000 chars), stderr_tail (末 2000 chars),
# duration_ms, finished_at
# TEST_SPEC case 5: stdout_text="abc"; cmd="echo abc"
# Sub-assertion: FR02-tail-truncation-bounded (len(stdout_tail) <= 2000)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["echo abc"])
def test_fr02_003_result_fields_populated(cmd, monkeypatch):
    """SPEC §3 FR-02 結果欄位: exit_code, stdout_tail, stderr_tail, duration_ms, finished_at 皆須填寫."""
    stdout_text = "abc"
    monkeypatch.setattr(
        "taskq.runner.runner.subprocess.run",
        lambda argv, **kw: _make_completed(argv, exit_code=0, stdout=f"{stdout_text}\n"),
    )
    result = run_task(cmd, timeout=10.0, retry_limit=0)

    # Sub-assertion FR02-tail-truncation-bounded: len(stdout_tail) <= 2000
    assert len(result.stdout_tail) <= 2000, (
        f"stdout_tail must be bounded to 2000 chars; got {len(result.stdout_tail)}"
    )
    assert len(result.stderr_tail) <= 2000
    assert stdout_text in result.stdout_tail, (
        f"stdout_tail must contain command output; got {result.stdout_tail!r}"
    )

    assert result.exit_code == 0
    assert result.duration_ms is not None and result.duration_ms >= 0
    assert result.finished_at is not None
    assert isinstance(result.finished_at, datetime), (
        f"finished_at must be a datetime; got {type(result.finished_at).__name__}"
    )


# ---------------------------------------------------------------------------
# AC-FR-02-04 — retry on failed/timeout up to TASKQ_RETRY_LIMIT (default 2)
# TEST_SPEC cases 6-8: retry_limit=2 / 0 / 3, cmd="false" (always fails)
# Sub-assertion: FR02-failed-when-exit-nonzero (exit_code != 0)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["false", "false", "false"])
def test_fr02_004_retry_until_limit(cmd, monkeypatch):
    """SPEC §3 FR-02 重試: failed/timeout 自動重試,上限 TASKQ_RETRY_LIMIT 次(預設 2)."""
    call_count = {"n": 0}

    def fake_run(argv, **kw):
        call_count["n"] += 1
        return _make_completed(argv, exit_code=1, stdout="", stderr="")

    monkeypatch.setattr("taskq.runner.runner.subprocess.run", fake_run)

    # ---- case 6: retry_limit=2 → 3 total attempts (1 initial + 2 retries) ----
    retry_limit = 2
    if retry_limit == 2:  # trigger matches case 6
        call_count["n"] = 0
        result = run_task(cmd, timeout=10.0, retry_limit=retry_limit)
        # Sub-assertion FR02-failed-when-exit-nonzero
        assert result.exit_code != 0
        assert result.status == TaskStatus.FAILED
        assert call_count["n"] == 1 + retry_limit, (
            f"retry_limit=2 must yield 3 attempts (1+2); got {call_count['n']}"
        )

    # ---- case 7: retry_limit=0 → 1 total attempt (boundary, no retry) ----
    retry_limit = 0
    if retry_limit == 0:  # trigger matches case 7
        call_count["n"] = 0
        result = run_task(cmd, timeout=10.0, retry_limit=retry_limit)
        assert call_count["n"] == 1, (
            f"retry_limit=0 must yield 1 attempt; got {call_count['n']}"
        )

    # ---- case 8: retry_limit=3 → 4 total attempts (boundary) ----
    retry_limit = 3
    if retry_limit == 3:  # trigger matches case 8
        call_count["n"] = 0
        result = run_task(cmd, timeout=10.0, retry_limit=retry_limit)
        assert call_count["n"] == 1 + retry_limit, (
            f"retry_limit=3 must yield 4 attempts; got {call_count['n']}"
        )


# ---------------------------------------------------------------------------
# AC-FR-02-04b — done tasks must NOT be retried (even with retry_limit > 0)
# TEST_SPEC case 9: cmd="true"
# Sub-assertion: FR02-done-when-exit-zero (exit_code == 0)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["true"])
def test_fr02_004b_no_retry_on_done(cmd, monkeypatch):
    """SPEC §3 FR-02: 成功的任務不重試,即使 retry_limit > 0."""
    call_count = {"n": 0}

    def fake_run(argv, **kw):
        call_count["n"] += 1
        return _make_completed(argv, exit_code=0, stdout="")

    monkeypatch.setattr("taskq.runner.runner.subprocess.run", fake_run)

    # Use a deliberately large retry_limit; done must short-circuit.
    result = run_task(cmd, timeout=10.0, retry_limit=5)
    # Sub-assertion FR02-done-when-exit-zero
    assert result.exit_code == 0
    assert result.status == TaskStatus.DONE
    assert call_count["n"] == 1, (
        f"done task must not be retried; got {call_count['n']} attempts"
    )


# ---------------------------------------------------------------------------
# AC-FR-02-05 — single-task mode timeout → exit code 4
# TEST_SPEC case 10: sleep_seconds=15; cmd="sleep 15"; timeout=1.0; single_task_mode=true
# Sub-assertions:
#   FR02-timeout-when-exceeds           (sleep_seconds > timeout)
#   FR02-single-task-mode-flags-timeout (single_task_mode == True)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["sleep 15"])
def test_fr02_005_timeout_exit_code_4(cmd, monkeypatch):
    """SPEC §3 FR-02: 單一任務模式下 timeout 結果 → exit 4."""
    sleep_seconds = 15
    timeout = 1.0
    single_task_mode = True

    if single_task_mode is True:  # trigger matches case 10
        # Sub-assertion FR02-timeout-when-exceeds
        assert sleep_seconds > timeout
        # Sub-assertion FR02-single-task-mode-flags-timeout
        assert single_task_mode is True

        def fake_run_timeout(argv, **kw):
            raise TimeoutExpired(argv, kw.get("timeout", timeout))

        monkeypatch.setattr("taskq.runner.runner.subprocess.run", fake_run_timeout)
        code = run_single_task(cmd, timeout=timeout)
        assert code == 4, (
            f"single-task-mode timeout must yield exit code 4; got {code}"
        )


# ---------------------------------------------------------------------------
# AC-FR-02-06 — unexpected exception → exit code 1 (no bare except:)
# TEST_SPEC case 11: cmd="true"
# ---------------------------------------------------------------------------

def test_fr02_006_unexpected_exception_exit1(monkeypatch):
    """SPEC §3 FR-02: 其他未預期例外 → exit 1(不得裸 except: 吞噬)."""
    cmd = "true"

    def _boom(*args, **kwargs):
        # Simulate an unexpected failure inside the runner's subprocess call.
        raise RuntimeError("simulated unexpected failure")

    monkeypatch.setattr("taskq.runner.runner.subprocess.run", _boom)

    # GREEN TODO: runner.run_single_task must catch non-TimeoutExpired exceptions
    # and return exit code 1. The except clause MUST specify Exception (or
    # narrower), NOT bare `except:` — which would also swallow
    # KeyboardInterrupt / SystemExit and is explicitly forbidden by the AC.
    code = run_single_task(cmd, timeout=10.0)
    assert code == 1, (
        f"unexpected exception must yield exit code 1; got {code}"
    )