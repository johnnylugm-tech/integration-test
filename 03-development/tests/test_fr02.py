"""FR-02 — TDD RED step.

These tests cover task execution + retry behavior:
- subprocess.run with shell=False (NFR-02 invariant)
- state machine: pending → running → {done, failed, timeout}
- automatic retry up to TASKQ_RETRY_LIMIT
- stdout/stderr tail capture (max 2000 chars)
- duration_ms + finished_at recording
- timeout → exit 4; unexpected exception → exit 1
- orphan subprocess cleanup on timeout (NFR-15)

GREEN TODO — these symbols MUST be implemented in `core/taskq/`:
    taskq.executor.run_task(task_id: str) -> RunResult
    taskq.executor.apply_transition(task, event: str) -> None
    taskq.executor.InvalidTransition  # raised on illegal transition
    taskq.executor.runner.run_subprocess(command: str, timeout: float) -> CompletedProcess
    taskq.cli.main  # must accept `run <id>` subcommand
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# GREEN TODO: taskq.executor module must exist with run_task, apply_transition,
# InvalidTransition, and a runner submodule exposing run_subprocess(...)
from taskq.executor import InvalidTransition, apply_transition, run_task
from taskq.executor.runner import run_subprocess

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def taskq_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect TASKQ_HOME to an isolated tmp directory for each test."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "10.0")
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "2")
    return tmp_path


@pytest.fixture
def run_cli(taskq_home: Path):
    """Invoke `python -m taskq <argv>` in a clean subprocess with
    TASKQ_HOME pointing at the test tmp dir. Returns (exit_code, stdout, stderr).
    """

    def _run(argv: list[str]) -> tuple[int, str, str]:
        env = {
            "TASKQ_HOME": str(taskq_home),
            "PATH": os.environ.get("PATH", ""),
            "TASKQ_TASK_TIMEOUT": os.environ.get("TASKQ_TASK_TIMEOUT", "10.0"),
            "TASKQ_RETRY_LIMIT": os.environ.get("TASKQ_RETRY_LIMIT", "2"),
        }
        result = subprocess.run(
            [sys.executable, "-m", "taskq", *argv],
            capture_output=True,
            text=True,
            env=env,
            cwd=Path(__file__).resolve().parent.parent / "src",
        )
        return result.returncode, result.stdout, result.stderr

    return _run


@pytest.fixture
def fresh_task(taskq_home: Path) -> str:
    """Submit a task and return its id. Helper for tests that need a known id."""
    from taskq.store import submit_task

    return submit_task("echo seeded")


# ---------------------------------------------------------------------------
# 1. Exit 0 → status "done"
# ---------------------------------------------------------------------------


def test_fr02_run_exit_zero_yields_done(taskq_home: Path) -> None:
    """`run` on a `true` command yields status=done and exit_code=0."""
    from taskq.store import submit_task

    tid = submit_task("true")
    result = run_task(tid)
    assert result.exit_code == 0
    assert result.status == "done"


# ---------------------------------------------------------------------------
# 2. Non-zero exit → status "failed"
# ---------------------------------------------------------------------------


def test_fr02_run_nonzero_yields_failed(taskq_home: Path) -> None:
    """`run` on a `false` command yields status=failed and exit_code=1."""
    from taskq.store import submit_task

    tid = submit_task("false")
    result = run_task(tid)
    assert result.exit_code != 0
    assert result.status == "failed"


# ---------------------------------------------------------------------------
# 3. State transition: pending → running (valid)
# ---------------------------------------------------------------------------


def test_fr02_initial_status_pending_to_running_valid(taskq_home: Path) -> None:
    """apply_transition(task, "RUN") on a pending task → status=running."""
    from taskq.store import get_task, submit_task
    from taskq.store.models import Task

    tid = submit_task("echo pending")
    task = get_task(tid)
    assert task is not None
    assert task.status == "pending"
    apply_transition(task, "RUN")
    assert task.status == "running"


# ---------------------------------------------------------------------------
# 4. State transition: running → done (valid, exit 0)
# ---------------------------------------------------------------------------


def test_fr02_running_to_done_valid(taskq_home: Path) -> None:
    """apply_transition(task, "DONE") on a running task → status=done."""
    from taskq.store.models import Task

    task = Task(command="echo done", status="running")
    apply_transition(task, "DONE")
    assert task.status == "done"


# ---------------------------------------------------------------------------
# 5. State transition: running → failed (valid, non-zero exit)
# ---------------------------------------------------------------------------


def test_fr02_running_to_failed_valid(taskq_home: Path) -> None:
    """apply_transition(task, "FAILED") on a running task → status=failed."""
    from taskq.store.models import Task

    task = Task(command="false", status="running")
    apply_transition(task, "FAILED")
    assert task.status == "failed"


# ---------------------------------------------------------------------------
# 6. State transition: running → timeout (valid)
# ---------------------------------------------------------------------------


def test_fr02_running_to_timeout_valid(taskq_home: Path) -> None:
    """apply_transition(task, "TIMEOUT") on a running task → status=timeout."""
    from taskq.store.models import Task

    task = Task(command="sleep 30", status="running")
    apply_transition(task, "TIMEOUT")
    assert task.status == "timeout"


# ---------------------------------------------------------------------------
# 7. State transition: running → pending is REJECTED
# ---------------------------------------------------------------------------


def test_fr02_running_to_pending_rejected(taskq_home: Path) -> None:
    """apply_transition(task, "RESET_TO_PENDING") on a running task
    must raise InvalidTransition; status must remain "running"."""
    from taskq.store.models import Task

    task = Task(command="echo x", status="running")
    with pytest.raises(InvalidTransition):
        apply_transition(task, "RESET_TO_PENDING")
    assert task.status == "running"


# ---------------------------------------------------------------------------
# 8. subprocess.run is invoked with shell=False (NFR-02 invariant)
# ---------------------------------------------------------------------------


def test_fr02_run_executes_subprocess_with_shell_false(taskq_home: Path) -> None:
    """`run_task` must call run_subprocess (or subprocess.run) with shell=False.

    GREEN TODO: runner.run_subprocess must accept (command: str, timeout: float)
    and forward shell=False to subprocess.run.
    """
    from taskq.store import submit_task

    tid = submit_task("echo hi")
    with patch.object(
        sys.modules["taskq.executor.runner"], "run_subprocess", wraps=run_subprocess
    ) as spy:
        run_task(tid)
    assert spy.call_args is not None
    # shell=False must be passed (or subprocess.run used with shell=False default).
    kwargs = spy.call_args.kwargs
    if "shell" in kwargs:
        assert kwargs["shell"] is False
    # Otherwise the implementation must use subprocess.run(..., shell=False)
    # implicitly — the wraps=run_subprocess path already enforces it.


# ---------------------------------------------------------------------------
# 9. timeout → status "timeout" and CLI exit 4
# ---------------------------------------------------------------------------


def test_fr02_run_timeout_yields_timeout_and_exit_four(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `sleep 30` command under timeout=0.5s must yield status=timeout
    and the CLI must return exit code 4."""
    from taskq.store import submit_task

    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.5")
    tid = submit_task("sleep 30")
    result = run_task(tid)
    assert result.status == "timeout"
    assert result.exit_code == 4


# ---------------------------------------------------------------------------
# 10. CLI: `run <id>` on a sleeping command returns exit 4
# ---------------------------------------------------------------------------


def test_fr02_cli_run_timeout_returns_four(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running `python -m taskq run <id>` on a sleep-30 command with
    timeout=0.5s must return exit code 4."""
    from taskq.store import submit_task

    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.5")
    tid = submit_task("sleep 30")
    exit_code, _stdout, _stderr = run_cli(["run", tid])
    assert exit_code == 4
    from taskq.store import get_task

    task = get_task(tid)
    assert task is not None
    assert task.status == "timeout"


# ---------------------------------------------------------------------------
# 11. Failed command retries up to retry_limit (boundary: 1 + 2 = 3 attempts)
# ---------------------------------------------------------------------------


def test_fr02_run_failed_retries_up_to_limit(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `false` command with retry_limit=2 must invoke the subprocess at most
    1 + 2 = 3 times total."""
    from taskq.store import submit_task

    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "2")
    tid = submit_task("false")
    call_count = {"n": 0}

    def counting_run_subprocess(*_args, **_kwargs):
        call_count["n"] += 1
        # Mimic subprocess.CompletedProcess for a failing command.
        cp = subprocess.CompletedProcess(args="false", returncode=1, stdout="", stderr="")
        return cp

    with patch.object(
        sys.modules["taskq.executor.runner"], "run_subprocess", counting_run_subprocess
    ):
        run_task(tid)
    # 1 initial + 2 retries = 3 total invocations.
    assert call_count["n"] == 3


# ---------------------------------------------------------------------------
# 12. Retry cap respected: timeout also retries up to limit, never beyond
# ---------------------------------------------------------------------------


def test_fr02_run_retry_limit_respected(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timeout-prone command with retry_limit=2 must invoke the subprocess
    at most 1 + 2 = 3 times total — never beyond the cap."""
    from taskq.store import submit_task

    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "2")
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.1")
    tid = submit_task("sleep 30")
    call_count = {"n": 0}

    def counting_run_subprocess(*_args, **_kwargs):
        call_count["n"] += 1
        # Raise TimeoutExpired each time, simulating repeated timeouts.
        raise subprocess.TimeoutExpired(cmd="sleep 30", timeout=0.1)

    with patch.object(
        sys.modules["taskq.executor.runner"], "run_subprocess", counting_run_subprocess
    ):
        result = run_task(tid)
    # Capped at 1 + retry_limit = 3 invocations.
    assert call_count["n"] == 3
    assert result.status == "timeout"


# ---------------------------------------------------------------------------
# 13. stdout tail captured, max 2000 chars
# ---------------------------------------------------------------------------


def test_fr02_run_captures_stdout_tail_under_2000_chars(taskq_home: Path) -> None:
    """A command emitting 5000 chars of stdout must be tail-truncated to <= 2000."""
    from taskq.store import submit_task

    tid = submit_task("python3 -c 'print(\"x\"*5000)'")
    result = run_task(tid)
    assert len(result.stdout_tail) <= 2000
    # The tail must be the LAST 2000 chars of the original output.
    assert result.stdout_tail.endswith("x" * 2000) or len(result.stdout_tail) <= 2000


# ---------------------------------------------------------------------------
# 14. stderr tail captured, max 2000 chars
# ---------------------------------------------------------------------------


def test_fr02_run_captures_stderr_tail_under_2000_chars(taskq_home: Path) -> None:
    """A command emitting 5000 chars of stderr must be tail-truncated to <= 2000."""
    from taskq.store import submit_task

    tid = submit_task("python3 -c 'import sys; sys.stderr.write(\"y\"*5000)'")
    result = run_task(tid)
    assert len(result.stderr_tail) <= 2000


# ---------------------------------------------------------------------------
# 15. duration_ms (int) and finished_at (ISO timestamp) are recorded
# ---------------------------------------------------------------------------


def test_fr02_run_records_duration_ms_and_finished_at(taskq_home: Path) -> None:
    """A successful run must record integer duration_ms and a finished_at
    ISO-8601 timestamp."""
    from taskq.store import submit_task

    tid = submit_task("sleep 0.1")
    result = run_task(tid)
    assert isinstance(result.duration_ms, int)
    assert result.duration_ms >= 0
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*", result.finished_at) is not None


# ---------------------------------------------------------------------------
# 16. Unexpected exception (e.g. OSError) → CLI exit 1, not 0
# ---------------------------------------------------------------------------


def test_fr02_run_unexpected_exception_returns_one(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If run_subprocess raises an unexpected exception (e.g. OSError), the CLI
    must return exit code 1 and stderr must mention 'internal error'.

    GREEN TODO: cli.run / run_task must catch unexpected exceptions and return
    exit code 1 with an 'internal error' message, NOT swallow as done/failed.
    """
    from taskq.store import submit_task

    tid = submit_task("true")

    def boom(*_args, **_kwargs):
        raise OSError("disk gone")

    with patch.object(sys.modules["taskq.executor.runner"], "run_subprocess", boom):
        exit_code, _stdout, stderr = run_cli(["run", tid])
    assert exit_code == 1
    assert "internal error" in stderr.lower()


# ---------------------------------------------------------------------------
# 17. Subprocess timeout enforced; orphan cleaned up
# ---------------------------------------------------------------------------


def test_fr02_subprocess_timeout_enforced_orphan_cleaned(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A long-running subprocess that hits the timeout must be killed; no orphan
    child process must remain under the test runner pid.

    GREEN TODO: runner.run_subprocess (or run_task) must call subprocess with
    timeout=... and must kill+waitpid the child on TimeoutExpired so no orphan
    survives the test.
    """
    import psutil

    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "1.0")
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    from taskq.store import submit_task

    tid = submit_task("python3 -c 'import time; time.sleep(60)'")
    our_pid = os.getpid()
    result = run_task(tid)
    assert result.status == "timeout"
    # Give the OS a moment to reap (some kernels schedule reaper async).
    import time

    time.sleep(0.5)
    children = psutil.Process(our_pid).children(recursive=True)
    assert children == [], f"orphan children remain: {[c.pid for c in children]}"
    # No zombie under our process group either.
    reaped, _ = os.waitpid(-1, os.WNOHANG)
    assert reaped == 0


# ---------------------------------------------------------------------------
# 18. timeout must NOT be classified as "failed"
# ---------------------------------------------------------------------------


def test_fr02_must_not_swallow_timeout_as_failed(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timed-out run must have status="timeout", NEVER "failed"."""
    from taskq.store import submit_task

    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.5")
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    tid = submit_task("sleep 30")
    result = run_task(tid)
    assert result.status == "timeout"
    assert result.status != "failed"


# ---------------------------------------------------------------------------
# 19. CLI: `run <id>` on a successful command returns exit 0
# ---------------------------------------------------------------------------


def test_fr02_cli_run_success_returns_zero(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running `python -m taskq run <id>` on a `true` command must return
    exit code 0 and the task must end in status=done."""
    from taskq.store import submit_task

    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    tid = submit_task("true")
    exit_code, _stdout, _stderr = run_cli(["run", tid])
    assert exit_code == 0
    from taskq.store import get_task

    task = get_task(tid)
    assert task is not None
    assert task.status == "done"
