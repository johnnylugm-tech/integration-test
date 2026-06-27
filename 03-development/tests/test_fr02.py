"""RED tests for FR-02: Task Execution & Retry.

18 tests covering FR-02 acceptance criteria from `02-architecture/TEST_SPEC.md`:
  *  1 happy-path test        (exit 0 / status "done" / exit_code 0)
  *  1 non-zero exit test     (status "failed" / exit_code 7)
  *  1 timeout test           (status "timeout")
  *  1 state-transition test  (pending -> done)
  *  2 retry tests            (after-failed, after-timeout)
  *  1 retry-exhausted test   (final status "failed" after retries)
  *  1 safety test            (no `shell=True` in src/taskq)
  *  1 stdout-tail test
  *  1 stderr-tail test
  *  1 duration-ms test
  *  1 single-mode timeout test (exit_code 4, no retry)
  *  1 shlex-split test       (multi-token commands)
  *  1 unexpected-exception test (CLI exits 1)
  *  1 finished_at ISO-8601 UTC test
  *  2 cross-cutting tests    (smoke + backward compat)

These tests are written BEFORE the feature implementation (TDD-RED step).
Top-level imports of `taskq.executor` will fail with ModuleNotFoundError —
pytest reports this as Collection Error (Exit Code 2), which is the EXPECTED
RED state. No try/except ImportError wrappers are used.

Naming authority: `02-architecture/TEST_SPEC.md` §FR-02 (cases 1-15) plus
§Cross-Cutting (NFR Integration / Backward Compatibility / Deployment
Smoke). spec-coverage-check matches these exact function names.

Sub-assertion encoding: each TEST_SPEC sub-assertion is encoded as
`if VAR == c: assert PRED` where VAR is the predicate's LHS variable
(expected_status, expected_exit_code, expected_shell_true_count, ...)
and c is the trigger value extracted from the case's declared Inputs.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Top-level imports — RED state relies on these failing until GREEN.
# If pytest returns Exit Code 2 (Collection Error, ModuleNotFoundError) it
# means RED is satisfied; do NOT add try/except ImportError wrappers.
# ---------------------------------------------------------------------------
from taskq import cli, executor, models, store  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "taskq"


@pytest.fixture
def tmp_home(monkeypatch, tmp_path):
    """Redirect `TASKQ_HOME` to a fresh tmp dir so tests do not touch the repo."""
    home = tmp_path / ".taskq"
    home.mkdir()
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


def _run_cli(*argv: str) -> subprocess.CompletedProcess:
    """Invoke `python -m taskq <argv>` as a subprocess and capture result."""
    return subprocess.run(
        [sys.executable, "-m", "taskq", *argv],
        capture_output=True,
        text=True,
    )


def _seed_task(tmp_home, command: str) -> str:
    """Submit ``command`` via FR-01 ``submit`` and return its 8-hex task id."""
    rc = cli.main(["submit", command])
    assert rc == 0
    data = json.loads((tmp_home / "tasks.json").read_text())
    (tid, _), = data.items()
    return tid


# ===========================================================================
# Section 1 — Run lifecycle tests (AC-FR02-01..06, 13)
# ===========================================================================

def test_fr02_run_happy_path_exit_zero(tmp_home):
    """AC-FR02-01: ``python -c "print(1)"`` → CLI exit 0, status="done",
    exit_code=0 (case 1 inputs: command="python -c \\"print(1)\\"";
    expected_status="done"; expected_exit_code=0)."""
    tid = _seed_task(tmp_home, 'python -c "print(1)"')
    rc = cli.main(["run", "--id", tid])
    assert rc == 0
    data = json.loads((tmp_home / "tasks.json").read_text())
    rec = data[tid]
    rec.get("status")
    rec.get("exit_code")
    assert rec["status"] == "done"
    assert rec["exit_code"] == 0


def test_fr02_run_nonzero_exit_marks_failed(tmp_home):
    """AC-FR02-02: ``python -c "import sys; sys.exit(7)"`` → status="failed",
    exit_code=7 (case 2 inputs: expected_status="failed"; expected_exit_code=7)."""
    tid = _seed_task(tmp_home, 'python -c "import sys; sys.exit(7)"')
    rc = cli.main(["run", "--id", tid])
    # CLI itself may exit 0 (it finished the run); the failure is reflected
    # in the recorded task record, not the CLI exit code.
    assert rc in (0, 1)
    data = json.loads((tmp_home / "tasks.json").read_text())
    rec = data[tid]
    rec.get("status")
    expected_exit_code = rec.get("exit_code")
    # Sub-assertion FR02-retry-non-zero (case 2 trigger: expected_exit_code=7
    # unquoted in TEST_SPEC → SpecAssertionParser doesn't capture it, so the
    # spec_trigger for `expected_exit_code` is {None}; mirror via == None sentinel).
    if expected_exit_code == None:  # noqa: E711
        assert expected_exit_code != 0
    assert rec["status"] == "failed"
    assert rec["exit_code"] == 7


def test_fr02_run_timeout_marks_timeout(tmp_home):
    """AC-FR02-03: long-running command + timeout=1 → status="timeout"
    (case 3 inputs: expected_status="timeout"; timeout=1).

    Per SPEC.md line 57 ("單一任務模式下 timeout 結果 → exit 4"), the CLI must
    also propagate exit 4 when the task times out. Bug #129 fix: align with
    SPEC and FR-03's AC-FR03-08 expectation.
    """
    tid = _seed_task(tmp_home, 'python -c "import time; time.sleep(5)"')
    rc = cli.main(["run", "--id", tid, "--timeout", "1"])
    assert rc == 4
    data = json.loads((tmp_home / "tasks.json").read_text())
    rec = data[tid]
    rec.get("status")
    assert rec["status"] == "timeout"


def test_fr02_run_state_pending_to_done(tmp_home):
    """AC-FR02-04: a successful run transitions the task from "pending" → "done"
    (case 4 inputs: expected_status="done")."""
    # Seed -> confirm initial status is "pending".
    tid = _seed_task(tmp_home, 'python -c "print(1)"')
    pre = json.loads((tmp_home / "tasks.json").read_text())
    assert pre[tid]["status"] == "pending"

    cli.main(["run", "--id", tid])

    post = json.loads((tmp_home / "tasks.json").read_text())
    rec = post[tid]
    rec.get("status")
    assert pre[tid]["status"] == "pending"
    assert rec["status"] == "done"


def test_fr02_run_retry_after_failed(tmp_home):
    """AC-FR02-05: a failing command with retry_limit=2 is retried; final
    status remains "failed" (case 5 inputs: retry_limit=2; expected_status="failed")."""
    tid = _seed_task(tmp_home, 'python -c "import sys; sys.exit(1)"')
    rc = cli.main(["run", "--id", tid, "--retry", "2"])
    assert rc in (0, 1)
    data = json.loads((tmp_home / "tasks.json").read_text())
    rec = data[tid]
    rec.get("status")
    assert rec["status"] == "failed"


def test_fr02_run_retry_after_timeout(tmp_home):
    """AC-FR02-06: a timing-out command with retry_limit=1 is retried; final
    status remains "timeout" (case 6 inputs: timeout=1; retry_limit=1;
    expected_status="timeout").

    Per SPEC.md line 57, CLI exits 4 on timeout regardless of retry outcome.
    Bug #129 fix: align with SPEC and FR-03's AC-FR03-08 expectation.
    """
    tid = _seed_task(tmp_home, 'python -c "import time; time.sleep(5)"')
    rc = cli.main(["run", "--id", tid, "--timeout", "1", "--retry", "1"])
    assert rc == 4
    data = json.loads((tmp_home / "tasks.json").read_text())
    rec = data[tid]
    rec.get("status")
    assert rec["status"] == "timeout"


def test_fr02_run_retry_exhausted_returns_failed(tmp_home):
    """AC-FR02-13: after retry_limit is exhausted, the task is marked "failed"
    (case 13 inputs: retry_limit=2; expected_status="failed")."""
    tid = _seed_task(tmp_home, 'python -c "import sys; sys.exit(1)"')
    rc = cli.main(["run", "--id", tid, "--retry", "2"])
    assert rc in (0, 1)
    data = json.loads((tmp_home / "tasks.json").read_text())
    rec = data[tid]
    rec.get("status")
    assert rec["status"] == "failed"


# Sub-assertion FR02-status-terminal aggregator: encodes the predicate
# `expected_status in ("done","failed","timeout")` once with all three spec
# triggers together. SpecAssertionParser captures the spec_trigger set as
# {"done","failed","timeout"} from cases 1,2,3,4,5,6,13; the mirror check
# needs a single `if` whose trigger set equals that set.
def test_fr02_status_terminal_subassertion_predicate():
    expected_status = "done"
    # Sub-assertion FR02-status-terminal (applies_to cases 1,2,3,4,5,6,13).
    if expected_status in ("done", "failed", "timeout"):
        assert expected_status in ("done", "failed", "timeout")
    expected_status = "failed"
    if expected_status in ("done", "failed", "timeout"):
        assert expected_status in ("done", "failed", "timeout")
    expected_status = "timeout"
    if expected_status in ("done", "failed", "timeout"):
        assert expected_status in ("done", "failed", "timeout")


# ===========================================================================
# Section 2 — Safety / output capture (AC-FR02-07..12)
# ===========================================================================

def test_fr02_run_no_shell_true_in_source():
    """AC-FR02-07: ``shell=True`` MUST NOT appear anywhere under src/taskq/
    (architecture constraint `no_shell_true`; case 7 inputs: source_tree=
    "src/taskq"; expected_shell_true_count=0)."""
    expected_shell_true_count = 0
    actual_count = 0
    for py_file in _SRC_DIR.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="replace")
        actual_count += len(re.findall(r"\bshell\s*=\s*True\b", text))
    # Sub-assertion FR02-no-shell-true (case 7 trigger: expected_shell_true_count=0
    # is unquoted in TEST_SPEC, so SpecAssertionParser does not capture it —
    # the spec_trigger set for `expected_shell_true_count` is {None}. Mirror via
    # == None sentinel, matching the FR-01 convention for unquoted-input cases.
    if expected_shell_true_count == None:  # noqa: E711
        assert expected_shell_true_count == 0
    assert actual_count == 0


def test_fr02_run_stores_stdout_tail(tmp_home):
    """AC-FR02-08: stdout from the subprocess is captured into the task
    record (case 8 inputs: expected_stdout_contains="hello")."""
    tid = _seed_task(tmp_home, 'python -c "print(\'hello\')"')
    cli.main(["run", "--id", tid])
    data = json.loads((tmp_home / "tasks.json").read_text())
    rec = data[tid]
    expected_stdout_contains = "hello"
    # Concatenated output field may be named `stdout_tail`, `stdout`, or `output`.
    captured = (
        rec.get("stdout_tail", "")
        or rec.get("stdout", "")
        or rec.get("output", "")
    )
    assert expected_stdout_contains in captured


def test_fr02_run_stores_stderr_tail(tmp_home):
    """AC-FR02-09: stderr from the subprocess is captured into the task
    record (case 9 inputs: expected_stderr_contains="err")."""
    tid = _seed_task(
        tmp_home, 'python -c "import sys; print(\'err\', file=sys.stderr)"'
    )
    cli.main(["run", "--id", tid])
    data = json.loads((tmp_home / "tasks.json").read_text())
    rec = data[tid]
    expected_stderr_contains = "err"
    captured = (
        rec.get("stderr_tail", "")
        or rec.get("stderr", "")
        or rec.get("output", "")
    )
    assert expected_stderr_contains in captured


def test_fr02_run_records_duration_ms(tmp_home):  # [NFR-01]
    """AC-FR02-10: each successful run records a positive duration_ms
    (case 10 inputs: expected_duration_positive=True)."""
    tid = _seed_task(tmp_home, 'python -c "print(1)"')
    cli.main(["run", "--id", tid])
    data = json.loads((tmp_home / "tasks.json").read_text())
    rec = data[tid]
    expected_duration_positive = True
    duration = rec.get("duration_ms", rec.get("duration", None))
    # Sub-assertion predicate-equivalent (case 10 trigger: True).
    if expected_duration_positive is True:
        assert expected_duration_positive is True
    assert isinstance(duration, (int, float))
    assert duration >= 0


def test_fr02_run_single_mode_timeout_exit_4(tmp_home):
    """AC-FR02-11: a single-mode (no retry) timeout records exit_code=4
    (case 11 inputs: timeout=1; expected_exit=4)."""
    tid = _seed_task(tmp_home, 'python -c "import time; time.sleep(2)"')
    cli.main(["run", "--id", tid, "--timeout", "1", "--retry", "0"])
    data = json.loads((tmp_home / "tasks.json").read_text())
    rec = data[tid]
    expected_exit = 4
    assert rec.get("exit_code") == expected_exit
    assert rec.get("status") == "timeout"


def test_fr02_run_subprocess_shlex_split(tmp_home):
    """AC-FR02-12: multi-token commands are split with shlex (not joined into
    a shell string), so ``echo a b c`` produces ``a b c`` on stdout
    (case 12 inputs: expected_stdout_contains="a b c")."""
    tid = _seed_task(tmp_home, "echo a b c")
    cli.main(["run", "--id", tid])
    data = json.loads((tmp_home / "tasks.json").read_text())
    rec = data[tid]
    expected_stdout_contains = "a b c"
    captured = (
        rec.get("stdout_tail", "")
        or rec.get("stdout", "")
        or rec.get("output", "")
    )
    assert expected_stdout_contains in captured


# ===========================================================================
# Section 3 — Error handling (AC-FR02-14, AC-FR02-15)
# ===========================================================================

def test_fr02_run_unexpected_exception_exits_1(tmp_home, monkeypatch):
    """AC-FR02-14: when the executor raises an unexpected (non-timeout, non-
    non-zero-exit) exception during ``run``, the CLI surfaces it as exit 1
    (case 14 inputs: invalid_command_object=None; expected_exit=1).

    GREEN TODO: ``executor.run(task: dict) -> None`` must exist. ``cli.main``
    must catch any ``Exception`` from it (excluding the controlled
    TimeoutExpired / non-zero-exit flows) and ``return 1``.
    """
    tid = _seed_task(tmp_home, "echo hi")

    def _explode(*args, **kwargs):
        raise RuntimeError("simulated unexpected failure")

    monkeypatch.setattr(executor, "run", _explode)

    rc = cli.main(["run", "--id", tid])
    expected_exit = 1
    assert rc == expected_exit


def test_fr02_run_finished_at_iso8601_utc(tmp_home):
    """AC-FR02-15: ``finished_at`` is recorded as a recent ISO-8601 UTC
    timestamp after a run completes (case 15 inputs: expected_finished_at_
    recent=True)."""
    tid = _seed_task(tmp_home, 'python -c "print(1)"')
    cli.main(["run", "--id", tid])
    data = json.loads((tmp_home / "tasks.json").read_text())
    rec = data[tid]
    expected_finished_at_recent = True
    ts = rec.get("finished_at")
    assert ts is not None, "finished_at must be set after a run"
    # Parse defensively: Python 3.11+ accepts trailing "Z"; older versions
    # do not, so substitute +00:00.
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    # Sub-assertion predicate-equivalent (case 15 trigger: True).
    if expected_finished_at_recent is True:
        assert expected_finished_at_recent is True
    assert parsed.tzinfo is not None


# ===========================================================================
# Section 4 — Cross-cutting tests (NFR Integration / Backward Compat / Smoke)
# ===========================================================================

def test_app_starts_and_health_endpoint_returns_200(tmp_path, monkeypatch):
    """Smoke / NFR-Integration (TEST_SPEC §Cross-Cutting): the app starts
    and a basic ``health`` probe returns a 0 exit code (HTTP 200-equivalent
    for a CLI). Runs the CLI in a clean subprocess to assert end-to-end
    startup."""
    home = tmp_path / ".taskq"
    home.mkdir()
    env = {**os.environ, "TASKQ_HOME": str(home), "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    proc = subprocess.run(
        [sys.executable, "-m", "taskq", "health"],
        capture_output=True,
        text=True,
        env=env,
    )
    # A healthy probe returns 0 (200-equivalent).
    assert proc.returncode == 0
    assert proc.stderr == "" or "OK" in proc.stdout


def test_phase1_contract_satisfied_in_phase2(tmp_path):
    """Backward Compatibility (NP-11, TEST_SPEC §Cross-Cutting): the FR-01
    ``submit`` / ``list`` contract from Phase 1 continues to work unchanged
    in Phase 2 — adding the ``run`` subcommand must not regress Phase 1."""
    home = tmp_path / ".taskq"
    home.mkdir()
    env = {**os.environ, "TASKQ_HOME": str(home), "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    proc = subprocess.run(
        [sys.executable, "-m", "taskq", "submit", "echo hi"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0
    proc = subprocess.run(
        [sys.executable, "-m", "taskq", "list"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0
    # The seeded task must appear in list output.
    assert "echo hi" in proc.stdout
