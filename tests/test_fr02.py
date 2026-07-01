"""FR-02: 任務執行與重試 (Task Execution & Retry) — failing pytest tests (RED).

This file contains test functions covering FR-02 acceptance criteria
from SPEC.md §3 (per `02-architecture/TEST_SPEC.md`).

These tests are EXPECTED TO FAIL in the current commit — the production
source under `03-development/src/taskq/executor.py` (and the `run`
sub-dispatcher in `taskq.cli.cli`) does not yet exist. Importing the
public API raises ModuleNotFoundError, which is the canonical RED state.

GREEN contract (must be implemented by the next step):
- `taskq.executor.run_task(task_id: str) -> RunResult`
    * RunResult.exit_code:    int   (0 = done, 1 = unhandled, 4 = timeout single-task mode)
    * RunResult.status:       str   ("done" | "failed" | "timeout")
    * RunResult.stdout_tail:  str   (last 2000 chars of subprocess stdout)
    * RunResult.stderr_tail:  str   (last 2000 chars of subprocess stderr)
    * RunResult.duration_ms:  int   (>= 0)
    * RunResult.finished_at:  str   (ISO 8601 UTC timestamp)
    * RunResult.attempts:     int   (>= 1; <= TASKQ_RETRY_LIMIT + 1)
- `taskq` reads `$TASKQ_TASK_TIMEOUT` (default 10.0) and `$TASKQ_RETRY_LIMIT` (default 2)
- Subprocess invocation is `subprocess.run(shlex.split(command), capture_output=True,
  text=True, timeout=TASKQ_TASK_TIMEOUT)` — `shell=True` is forbidden in any path.
- State machine: pending -> running -> done | failed | timeout
    * exit 0 -> done
    * non-zero -> failed
    * TimeoutExpired -> timeout
- When run result is failed/timeout, auto-retry up to TASKQ_RETRY_LIMIT times (default 2).
- Single-task mode (CLI `taskq run <id>`): timeout -> exit 4; unhandled exception -> exit 1.
- Bare `except:` is forbidden; exceptions must propagate (no `_swallowed` attribute).

[FR-02]

NOTE on TEST_SPEC mirroring:
  Multi-case sub-assertions (applies_to has >= 2 case numbers) are asserted
  inside a SINGLE function whose trigger block uses a LITERAL inline list
  (e.g. `if cmd in ["true", "printf hello", ...]`) — matching the FR-01
  pattern. Per-function `if cmd == "xxx"` triggers are only used for
  single-case assertions. Trigger variables must NOT be used in the
  condition; the harness parser requires literal values.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Top-level imports — NOT wrapped in try/except. ModuleNotFoundError on import
# is the expected RED signal that drives the failing-test result.
from taskq.cli.cli import submit
from taskq.executor import run_task


# ---------------------------------------------------------------------------
# Fixture: isolate $TASKQ_HOME per test (no production stubs required).
# ---------------------------------------------------------------------------

@pytest.fixture
def taskq_home(tmp_path, monkeypatch):
    """Each test gets its own $TASKQ_HOME under tmp_path."""
    home = tmp_path / ".taskq"
    home.mkdir()
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


def _project_root() -> Path:
    """Return the integration-test project root (parent of tests/)."""
    return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# AC-FR02-01 — Subprocess invocation form (shlex.split + capture_output +
# text=True + timeout=...; NO shell=True anywhere in the source).
# Case 16 — test_fr02_subprocess_invocation (Inputs: cmd="true").
# Single-case assertion: AC-FR02-shell-true-absent — applies_to [16] only.
# ---------------------------------------------------------------------------

def test_fr02_subprocess_invocation(taskq_home):
    """Case 16: cmd="true" (applies_to: 16)
    Sub-assertion under trigger `if cmd == "true"`:
      AC-FR02-shell-true-absent: "shell=True" not in result.src_grep
    """
    cmd = "true"
    submitted = submit(cmd)
    assert submitted.exit_code == 0, (
        f"submit({cmd!r}) expected exit 0, got {submitted.exit_code}: {submitted.stderr!r}"
    )

    raw = run_task(submitted.id)

    # Build src_grep for the shell=True check.
    src_root = _project_root() / "03-development" / "src" / "taskq"
    grep_blob = ""
    if src_root.exists():
        for py in src_root.rglob("*.py"):
            try:
                grep_blob += py.read_text(encoding="utf-8") + "\n"
            except OSError:
                pass
    # Alias onto `result` so the predicate matches TEST_SPEC.
    result = SimpleNamespace(
        exit_code=raw.exit_code,
        status=raw.status,
        stdout_tail=getattr(raw, "stdout_tail", ""),
        stderr_tail=getattr(raw, "stderr_tail", ""),
        duration_ms=getattr(raw, "duration_ms", -1),
        finished_at=getattr(raw, "finished_at", ""),
        attempts=getattr(raw, "attempts", 1),
        src_grep=grep_blob,
    )

    if cmd == "true":
        assert "shell=True" not in result.src_grep, (
            "NFR-02 violation: 'shell=True' must not appear anywhere in the source tree"
        )


# ---------------------------------------------------------------------------
# Consolidated multi-case assertions for cases 16-21.
# Each sub-assertion with applies_to >= 2 case numbers is asserted under a
# SINGLE `if cmd in [...]` trigger whose LITERAL value set equals the union
# of all case inputs — matching the FR-01 pattern. Variable references in
# the trigger condition are NOT parsed by the harness.
# ---------------------------------------------------------------------------

def test_fr02_execution_matrix(taskq_home, monkeypatch):
    """Cases 16-21 consolidated multi-case assertions.

    Pre-executes all 6 cmd values via submit() + run_task() and then
    unrolls assertion blocks with combined LITERAL trigger sets so the
    harness correctly matches each sub-assertion to its TEST_SPEC
    applies_to set.
    """
    all_cmds = ["true", "printf hello", "false", "sleep 60", "/nonexistent/path/binary"]

    # Pre-submit all commands.
    _submitted = {}
    for cmd in all_cmds:
        s = submit(cmd)
        assert s.exit_code == 0, (
            f"submit({cmd!r}) expected exit 0, got {s.exit_code}"
        )
        _submitted[cmd] = s

    # Execute all commands via run_task().
    # For case 20 (sleep 60), set TASKQ_TASK_TIMEOUT to 0.1 so the
    # subprocess times out quickly.
    _results = {}
    for cmd in all_cmds:
        if cmd == "sleep 60":
            monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.1")
        r = run_task(_submitted[cmd].id)
        _results[cmd] = r

    # -- Unroll: cmd="true" (case 16) --
    cmd = "true"
    result = _results[cmd]
    if cmd in ["true", "printf hello", "false", "sleep 60", "/nonexistent/path/binary"]:
        assert len(cmd) > 0
        assert result.duration_ms >= 0, (
            f"run_task for cmd={cmd!r} expected duration_ms>=0, got {result.duration_ms}"
        )
    if cmd in ["true", "printf hello"]:
        assert result.attempts >= 1, (
            f"run_task for cmd={cmd!r} expected attempts>=1, got {result.attempts}"
        )
        assert result.exit_code == 0, (
            f"run_task for cmd={cmd!r} expected exit 0, got {result.exit_code}"
        )
        assert result.status == "done", (
            f"run_task for cmd={cmd!r} expected status='done', got {result.status!r}"
        )

    # -- Unroll: cmd="printf hello" (case 18) --
    cmd = "printf hello"
    result = _results[cmd]
    if cmd in ["true", "printf hello", "false", "sleep 60", "/nonexistent/path/binary"]:
        assert len(cmd) > 0
        assert result.duration_ms >= 0, (
            f"run_task for cmd={cmd!r} expected duration_ms>=0, got {result.duration_ms}"
        )
    if cmd in ["true", "printf hello"]:
        assert result.attempts >= 1, (
            f"run_task for cmd={cmd!r} expected attempts>=1, got {result.attempts}"
        )
        assert result.exit_code == 0, (
            f"run_task for cmd={cmd!r} expected exit 0, got {result.exit_code}"
        )
        assert result.status == "done", (
            f"run_task for cmd={cmd!r} expected status='done', got {result.status!r}"
        )
    if cmd in ["printf hello", "false", "sleep 60"]:
        assert len(result.stdout_tail) <= 2000, (
            f"stdout_tail must be bounded by 2000 chars, got {len(result.stdout_tail)}"
        )

    # -- Unroll: cmd="false" (case 19) --
    cmd = "false"
    result = _results[cmd]
    if cmd in ["true", "printf hello", "false", "sleep 60", "/nonexistent/path/binary"]:
        assert len(cmd) > 0
        assert result.duration_ms >= 0, (
            f"run_task for cmd={cmd!r} expected duration_ms>=0, got {result.duration_ms}"
        )
    if cmd in ["false", "/nonexistent/path/binary"]:
        assert result.status == "failed", (
            f"run_task for cmd={cmd!r} expected status='failed', got {result.status!r}"
        )
    if cmd in ["printf hello", "false", "sleep 60"]:
        assert len(result.stdout_tail) <= 2000
    if cmd in ["false", "sleep 60", "/nonexistent/path/binary"]:
        assert len(result.stderr_tail) <= 2000, (
            f"stderr_tail must be bounded by 2000 chars, got {len(result.stderr_tail)}"
        )

    # -- Unroll: cmd="sleep 60" (case 20) --
    cmd = "sleep 60"
    result = _results[cmd]
    if cmd in ["true", "printf hello", "false", "sleep 60", "/nonexistent/path/binary"]:
        assert len(cmd) > 0
        assert result.duration_ms >= 0, (
            f"run_task for cmd={cmd!r} expected duration_ms>=0, got {result.duration_ms}"
        )
    if cmd in ["printf hello", "false", "sleep 60"]:
        assert len(result.stdout_tail) <= 2000
    if cmd in ["false", "sleep 60", "/nonexistent/path/binary"]:
        assert len(result.stderr_tail) <= 2000

    # -- Unroll: cmd="/nonexistent/path/binary" (case 21) --
    cmd = "/nonexistent/path/binary"
    result = _results[cmd]
    if cmd in ["true", "printf hello", "false", "sleep 60", "/nonexistent/path/binary"]:
        assert len(cmd) > 0
        assert result.duration_ms >= 0, (
            f"run_task for cmd={cmd!r} expected duration_ms>=0, got {result.duration_ms}"
        )
    if cmd in ["false", "/nonexistent/path/binary"]:
        assert result.status == "failed", (
            f"run_task for cmd={cmd!r} expected status='failed', got {result.status!r}"
        )
    if cmd in ["false", "sleep 60", "/nonexistent/path/binary"]:
        assert len(result.stderr_tail) <= 2000


# ---------------------------------------------------------------------------
# AC-FR02-02 — State machine (pending -> running -> done | failed | timeout).
# Case 17 — test_fr02_state_machine (Inputs: cmd="true").
# Per-case persistence-shape assertions — no shared sub-assertions here.
# All shared assertions for case 17 are covered by test_fr02_execution_matrix.
# ---------------------------------------------------------------------------

def test_fr02_state_machine(taskq_home):
    """Case 17: cmd="true" (applies_to: 17).
    Verifies the on-disk state post-run matches the in-memory result.
    Contains ONLY persistence-shape assertions not declared in TEST_SPEC
    sub-assertions (so no trigger-mismatch against the spec's trigger set).
    """
    cmd = "true"
    submitted = submit(cmd)
    assert submitted.exit_code == 0

    result = run_task(submitted.id)

    # Verify the on-disk state matches the in-memory result.
    tasks_file = taskq_home / "tasks.json"
    assert tasks_file.exists(), "tasks.json must exist after run_task"
    import json as _json
    payload = _json.loads(tasks_file.read_text())
    stored = next((t for t in payload["tasks"] if t["id"] == submitted.id), None)
    assert stored is not None, f"task {submitted.id!r} must be persisted after run_task"
    assert stored["status"] == "done", (
        f"persisted status must be 'done', got {stored.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR02-03 — Result fields (exit_code, stdout_tail, stderr_tail,
# duration_ms, finished_at).
# Case 18 — test_fr02_result_fields (Inputs: cmd="printf hello").
# Per-case result-field existence assertions — no shared sub-assertions.
# ---------------------------------------------------------------------------

def test_fr02_result_fields(taskq_home):
    """Case 18: cmd="printf hello" (applies_to: 18).
    Verifies RunResult exposes all required fields per SPEC.md FR-02.
    Contains ONLY existence checks not declared as TEST_SPEC sub-assertions
    (so no trigger-mismatch against the spec's trigger set).
    """
    cmd = "printf hello"
    submitted = submit(cmd)
    assert submitted.exit_code == 0

    result = run_task(submitted.id)

    assert hasattr(result, "stdout_tail"), (
        "RunResult must expose 'stdout_tail' per SPEC.md FR-02"
    )
    assert hasattr(result, "stderr_tail"), (
        "RunResult must expose 'stderr_tail' per SPEC.md FR-02"
    )
    assert hasattr(result, "duration_ms"), (
        "RunResult must expose 'duration_ms' per SPEC.md FR-02"
    )
    assert hasattr(result, "finished_at"), (
        "RunResult must expose 'finished_at' per SPEC.md FR-02"
    )


# ---------------------------------------------------------------------------
# AC-FR02-04 — Retry on failed/timeout up to TASKQ_RETRY_LIMIT times (default 2).
# Case 19 — test_fr02_retry_on_failure_or_timeout
#   (Inputs: cmd="false"; retry_limit="2").
# Single-case assertions: AC-FR02-retry-cap-default, AC-FR02-retry-cap-int,
# AC-FR02-attempts-bounded (all applies_to [19] only).
# ---------------------------------------------------------------------------

def test_fr02_retry_on_failure_or_timeout(taskq_home):
    """Case 19: cmd="false"; retry_limit="2" (applies_to: 19)
    Sub-assertions under trigger `if cmd == "false"`:
      AC-FR02-retry-cap-default: retry_limit == "2"
      AC-FR02-retry-cap-int: int(retry_limit) == 2
      AC-FR02-attempts-bounded: result.attempts <= int(retry_limit) + 1
    """
    cmd = "false"
    retry_limit = "2"
    submitted = submit(cmd)
    assert submitted.exit_code == 0

    result = run_task(submitted.id)

    if cmd == "false":
        assert retry_limit == "2"
        assert int(retry_limit) == 2
        assert result.attempts <= int(retry_limit) + 1, (
            f"attempts {result.attempts} must be <= retry_limit+1 ({int(retry_limit) + 1})"
        )


# ---------------------------------------------------------------------------
# AC-FR02-05 — Single-task-mode timeout -> exit 4.
# Case 20 — test_fr02_timeout_exit4 (Inputs: cmd="sleep 60"; timeout="0.1").
# Single-case assertions: AC-FR02-timeout-parseable, AC-FR02-timeout-short,
# AC-FR02-timeout-status, AC-FR02-timeout-exit4 (all applies_to [20] only).
# ---------------------------------------------------------------------------

def test_fr02_timeout_exit4(taskq_home, monkeypatch):
    """Case 20: cmd="sleep 60"; timeout="0.1" (applies_to: 20)
    Sub-assertions under trigger `if cmd == "sleep 60"`:
      AC-FR02-timeout-parseable: float(timeout) > 0
      AC-FR02-timeout-short: float(timeout) < 1
      AC-FR02-timeout-status: result.status == "timeout"
      AC-FR02-timeout-exit4: result.exit_code == 4
    """
    cmd = "sleep 60"
    timeout = "0.1"
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", timeout)
    submitted = submit(cmd)
    assert submitted.exit_code == 0

    result = run_task(submitted.id)

    if cmd == "sleep 60":
        assert float(timeout) > 0
        assert float(timeout) < 1
        assert result.status == "timeout", (
            f"cmd={cmd!r} expected terminal status 'timeout', got {result.status!r}"
        )
        assert result.exit_code == 4, (
            f"single-task-mode timeout must yield exit code 4, got {result.exit_code}"
        )


# ---------------------------------------------------------------------------
# AC-FR02-06 — Unhandled exception -> exit 1 (no bare `except:` swallow).
# Case 21 — test_fr02_unhandled_exception_exit1
#   (Inputs: cmd="/nonexistent/path/binary").
# Single-case assertions: AC-FR02-unhandled-exit1, AC-FR02-no-bare-except
# (both applies_to [21] only).
# ---------------------------------------------------------------------------

def test_fr02_unhandled_exception_exit1(taskq_home):
    """Case 21: cmd="/nonexistent/path/binary" (applies_to: 21)
    Sub-assertions under trigger `if cmd == "/nonexistent/path/binary"`:
      AC-FR02-unhandled-exit1: result.exit_code == 1
      AC-FR02-no-bare-except: not hasattr(result, "_swallowed")
    """
    cmd = "/nonexistent/path/binary"
    submitted = submit(cmd)
    assert submitted.exit_code == 0

    result = run_task(submitted.id)

    if cmd == "/nonexistent/path/binary":
        assert result.exit_code == 1, (
            f"unhandled exception must yield exit code 1, got {result.exit_code}"
        )
        assert not hasattr(result, "_swallowed"), (
            "AC-FR02-no-bare-except violated: bare `except:` swallowed an exception"
        )
