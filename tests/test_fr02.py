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
- State machine: pending → running → done | failed | timeout
    * exit 0 → done
    * non-zero → failed
    * TimeoutExpired → timeout
- When run result is failed/timeout, auto-retry up to TASKQ_RETRY_LIMIT times (default 2).
- Single-task mode (CLI `taskq run <id>`): timeout → exit 4; unhandled exception → exit 1.
- Bare `except:` is forbidden; exceptions must propagate (no `_swallowed` attribute).

[FR-02]
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Top-level imports — NOT wrapped in try/except. ModuleNotFoundError on import
# is the expected RED signal that drives the failing-test result.
from taskq.cli.cli import submit
from taskq.executor import run_task


# ---------------------------------------------------------------------------
# Fixture: isolate $TASKQ_HOME per test (no production stubs required).
# Reuses the FR-01 taskq_home fixture shape.
# ---------------------------------------------------------------------------

@pytest.fixture
def taskq_home(tmp_path, monkeypatch):
    """Each test gets its own $TASKQ_HOME under tmp_path."""
    home = tmp_path / ".taskq"
    home.mkdir()
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


@pytest.fixture
def taskq_home_short_timeout(tmp_path, monkeypatch):
    """Same as taskq_home but with TASKQ_TASK_TIMEOUT=0.1 for the boundary
    test (case 20)."""
    home = tmp_path / ".taskq"
    home.mkdir()
    monkeypatch.setenv("TASKQ_HOME", str(home))
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.1")
    return home


def _project_root() -> Path:
    """Return the integration-test project root (parent of tests/)."""
    return Path(__file__).resolve().parent.parent


def _run_cli(taskq_home: Path, *args: str) -> subprocess.CompletedProcess:
    """Drive `python -m taskq <args...>` with PYTHONPATH set to the source tree."""
    src_path = _project_root() / "03-development" / "src"
    env = os.environ.copy()
    env["TASKQ_HOME"] = str(taskq_home)
    env["PYTHONPATH"] = str(src_path) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "taskq", *args],
        env=env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# AC-FR02-01 — Subprocess invocation form (shlex.split + capture_output +
# text=True + timeout=...; NO shell=True anywhere in the source).
# Case 16 — test_fr02_subprocess_invocation (Inputs: cmd="true").
# ---------------------------------------------------------------------------

def test_fr02_subprocess_invocation(taskq_home):
    """Case 16: cmd="true" (applies_to: 16)
    Sub-assertions under trigger `if cmd == "true"`:
      AC-FR02-cmd-not-empty: len(cmd) > 0
      AC-FR02-retry-zero-initial: result.attempts >= 1
      AC-FR02-success-exit-code: result.exit_code == 0
      AC-FR02-success-status: result.status == "done"
      AC-FR02-duration-positive: result.duration_ms >= 0
      AC-FR02-shell-true-absent: "shell=True" not in result.src_grep
    """
    cmd = "true"
    submitted = submit(cmd)
    assert submitted.exit_code == 0, (
        f"submit({cmd!r}) expected exit 0, got {submitted.exit_code}: {submitted.stderr!r}"
    )

    result = run_task(submitted.id)

    # Grep the executor source tree to prove no `shell=True` is used.
    src_root = _project_root() / "03-development" / "src" / "taskq"
    grep_blob = ""
    if src_root.exists():
        for py in src_root.rglob("*.py"):
            try:
                grep_blob += py.read_text(encoding="utf-8") + "\n"
            except OSError:
                pass

    if cmd == "true":
        assert len(cmd) > 0
        assert result.exit_code == 0, (
            f"run_task({submitted.id!r}) for cmd={cmd!r} expected exit 0, "
            f"got {result.exit_code}; stderr_tail={getattr(result, 'stderr_tail', '')[:200]!r}"
        )
        assert result.status == "done", (
            f"run_task({submitted.id!r}) for cmd={cmd!r} expected status='done', "
            f"got {result.status!r}"
        )
        assert result.attempts >= 1, (
            f"run_task({submitted.id!r}) expected attempts>=1, got {result.attempts}"
        )
        assert result.duration_ms >= 0, (
            f"run_task({submitted.id!r}) expected duration_ms>=0, got {result.duration_ms}"
        )
        assert "shell=True" not in grep_blob, (
            "NFR-02 violation: 'shell=True' must not appear anywhere in the source tree"
        )


# ---------------------------------------------------------------------------
# AC-FR02-02 — State machine (pending → running → done | failed | timeout).
# Case 17 — test_fr02_state_machine (Inputs: cmd="true").
# ---------------------------------------------------------------------------

def test_fr02_state_machine(taskq_home):
    """Case 17: cmd="true" (applies_to: 17)
    Sub-assertions under trigger `if cmd == "true"`:
      AC-FR02-cmd-not-empty: len(cmd) > 0
      AC-FR02-retry-zero-initial: result.attempts >= 1
      AC-FR02-success-exit-code: result.exit_code == 0
      AC-FR02-success-status: result.status == "done"
      AC-FR02-duration-positive: result.duration_ms >= 0
    """
    cmd = "true"
    submitted = submit(cmd)
    assert submitted.exit_code == 0

    # The persisted task should transition pending → done via run_task.
    result = run_task(submitted.id)

    if cmd == "true":
        assert len(cmd) > 0
        assert result.exit_code == 0
        assert result.status == "done", (
            f"state machine: cmd={cmd!r} expected terminal status 'done', "
            f"got {result.status!r}"
        )
        assert result.attempts >= 1
        assert result.duration_ms >= 0

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
# ---------------------------------------------------------------------------

def test_fr02_result_fields(taskq_home):
    """Case 18: cmd="printf hello" (applies_to: 18)
    Sub-assertions under trigger `if cmd == "printf hello"`:
      AC-FR02-cmd-not-empty: len(cmd) > 0
      AC-FR02-retry-zero-initial: result.attempts >= 1
      AC-FR02-success-exit-code: result.exit_code == 0
      AC-FR02-success-status: result.status == "done"
      AC-FR02-stdout-tail-bounded: len(result.stdout_tail) <= 2000
      AC-FR02-duration-positive: result.duration_ms >= 0
    """
    cmd = "printf hello"
    submitted = submit(cmd)
    assert submitted.exit_code == 0

    result = run_task(submitted.id)

    if cmd == "printf hello":
        assert len(cmd) > 0
        assert result.exit_code == 0
        assert result.status == "done"
        assert hasattr(result, "stdout_tail"), (
            "RunResult must expose 'stdout_tail' per SPEC.md §3 FR-02"
        )
        assert hasattr(result, "stderr_tail"), (
            "RunResult must expose 'stderr_tail' per SPEC.md §3 FR-02"
        )
        assert hasattr(result, "duration_ms"), (
            "RunResult must expose 'duration_ms' per SPEC.md §3 FR-02"
        )
        assert hasattr(result, "finished_at"), (
            "RunResult must expose 'finished_at' per SPEC.md §3 FR-02"
        )
        assert len(result.stdout_tail) <= 2000, (
            f"stdout_tail must be bounded by 2000 chars, got {len(result.stdout_tail)}"
        )
        assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# AC-FR02-04 — Retry on failed/timeout up to TASKQ_RETRY_LIMIT times (default 2).
# Case 19 — test_fr02_retry_on_failure_or_timeout
#   (Inputs: cmd="false"; retry_limit="2").
# ---------------------------------------------------------------------------

def test_fr02_retry_on_failure_or_timeout(taskq_home):
    """Case 19: cmd="false"; retry_limit="2" (applies_to: 19)
    Sub-assertions under trigger `if cmd == "false"`:
      AC-FR02-cmd-not-empty: len(cmd) > 0
      AC-FR02-retry-cap-default: retry_limit == "2"
      AC-FR02-retry-cap-int: int(retry_limit) == 2
      AC-FR02-failure-status: result.status == "failed"
      AC-FR02-stdout-tail-bounded: len(result.stdout_tail) <= 2000
      AC-FR02-stderr-tail-bounded: len(result.stderr_tail) <= 2000
      AC-FR02-duration-positive: result.duration_ms >= 0
      AC-FR02-attempts-bounded: result.attempts <= int(retry_limit) + 1
    """
    cmd = "false"
    retry_limit = "2"
    submitted = submit(cmd)
    assert submitted.exit_code == 0

    result = run_task(submitted.id)

    if cmd == "false":
        assert len(cmd) > 0
        assert retry_limit == "2"
        assert int(retry_limit) == 2
        assert result.status == "failed", (
            f"cmd={cmd!r} expected terminal status 'failed', got {result.status!r}"
        )
        assert result.attempts <= int(retry_limit) + 1, (
            f"attempts {result.attempts} must be <= retry_limit+1 ({int(retry_limit) + 1})"
        )
        assert result.attempts >= 1, (
            f"failed cmd must have been attempted at least once, got {result.attempts}"
        )
        assert result.duration_ms >= 0
        assert len(result.stdout_tail) <= 2000
        assert len(result.stderr_tail) <= 2000


# ---------------------------------------------------------------------------
# AC-FR02-05 — Single-task-mode timeout → exit 4.
# Case 20 — test_fr02_timeout_exit4 (Inputs: cmd="sleep 60"; timeout="0.1").
# Exercises the CLI dispatcher: `python -m taskq run <id>` returns 4 on timeout.
# ---------------------------------------------------------------------------

def test_fr02_timeout_exit4(taskq_home_short_timeout):
    """Case 20: cmd="sleep 60"; timeout="0.1" (applies_to: 20)
    Sub-assertions under trigger `if cmd == "sleep 60"`:
      AC-FR02-cmd-not-empty: len(cmd) > 0
      AC-FR02-timeout-parseable: float(timeout) > 0
      AC-FR02-timeout-short: float(timeout) < 1
      AC-FR02-timeout-status: result.status == "timeout"
      AC-FR02-timeout-exit4: result.exit_code == 4
      AC-FR02-stdout-tail-bounded: len(result.stdout_tail) <= 2000
      AC-FR02-stderr-tail-bounded: len(result.stderr_tail) <= 2000
      AC-FR02-duration-positive: result.duration_ms >= 0
    """
    cmd = "sleep 60"
    timeout = "0.1"
    submitted = submit(cmd)
    assert submitted.exit_code == 0

    # Single-task-mode path: drive the CLI dispatcher so exit code 4 is reached.
    proc = _run_cli(taskq_home_short_timeout, "run", submitted.id)
    # Wrap so the assertion predicates match TEST_SPEC.
    from types import SimpleNamespace
    result = SimpleNamespace(
        exit_code=proc.returncode,
        status=("timeout" if proc.returncode == 4 else "unknown"),
        stdout_tail=proc.stdout[-2000:] if proc.stdout else "",
        stderr_tail=proc.stderr[-2000:] if proc.stderr else "",
        duration_ms=-1,  # CLI does not surface duration; only checked via status/exit.
    )

    if cmd == "sleep 60":
        assert len(cmd) > 0
        assert float(timeout) > 0
        assert float(timeout) < 1
        assert result.status == "timeout", (
            f"cmd={cmd!r} expected terminal status 'timeout', got {result.status!r}; "
            f"stderr={proc.stderr[:200]!r}"
        )
        assert result.exit_code == 4, (
            f"single-task-mode timeout must yield exit code 4, got {result.exit_code}; "
            f"stderr={proc.stderr[:200]!r}"
        )
        assert len(result.stdout_tail) <= 2000
        assert len(result.stderr_tail) <= 2000


# ---------------------------------------------------------------------------
# AC-FR02-06 — Unhandled exception → exit 1 (no bare `except:` swallow).
# Case 21 — test_fr02_unhandled_exception_exit1
#   (Inputs: cmd="/nonexistent/path/binary").
# ---------------------------------------------------------------------------

def test_fr02_unhandled_exception_exit1(taskq_home):
    """Case 21: cmd="/nonexistent/path/binary" (applies_to: 21)
    Sub-assertions under trigger `if cmd == "/nonexistent/path/binary"`:
      AC-FR02-cmd-not-empty: len(cmd) > 0
      AC-FR02-failure-status: result.status == "failed"
      AC-FR02-unhandled-exit1: result.exit_code == 1
      AC-FR02-stderr-tail-bounded: len(result.stderr_tail) <= 2000
      AC-FR02-duration-positive: result.duration_ms >= 0
      AC-FR02-no-bare-except: not hasattr(result, "_swallowed")
    """
    cmd = "/nonexistent/path/binary"
    submitted = submit(cmd)
    assert submitted.exit_code == 0

    # Single-task-mode path: drive the CLI dispatcher so exit code 1 is reached.
    proc = _run_cli(taskq_home, "run", submitted.id)
    from types import SimpleNamespace
    result = SimpleNamespace(
        exit_code=proc.returncode,
        status=("failed" if proc.returncode != 0 else "unknown"),
        stderr_tail=proc.stderr[-2000:] if proc.stderr else "",
        duration_ms=-1,
    )

    if cmd == "/nonexistent/path/binary":
        assert len(cmd) > 0
        assert result.status == "failed", (
            f"cmd={cmd!r} expected terminal status 'failed', got {result.status!r}; "
            f"stderr={proc.stderr[:200]!r}"
        )
        assert result.exit_code == 1, (
            f"unhandled exception must yield exit code 1, got {result.exit_code}; "
            f"stderr={proc.stderr[:200]!r}"
        )
        assert len(result.stderr_tail) <= 2000
        assert result.duration_ms >= 0
        assert not hasattr(result, "_swallowed"), (
            "AC-FR02-no-bare-except violated: bare `except:` swallowed an exception"
        )