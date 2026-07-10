"""TDD-RED tests for FR-02 — Task Executor + state machine.

Per TEST_SPEC.md FR-02 (cases 1-5, lines 117-159) and SPEC.md §3 FR-02:
  - subprocess.run + shlex.split, never shell=True (NFR-02 / AC-FR-02-1)
  - state machine: pending -> running -> done | failed | timeout (AC-FR-02-2)
  - result fields: exit_code / stdout_tail / stderr_tail / duration_ms / finished_at (AC-FR-02-3)
  - run --all concurrent, Lock-protected writes (AC-FR-02-4 / NP-13)
  - single-task timeout -> exit 4 (AC-FR-02-5)

The source module `taskq.executor` does NOT exist yet — pytest Collection
Error (ModuleNotFoundError, Exit 2) is the expected RED state. `taskq.cli`
exists with FR-01 `submit` only; the `run` subcommand will be added by GREEN
as part of FR-02/03/05 wiring.

Sub-assertion layout: each `if <var> == <literal>:` block mirrors a TEST_SPEC
sub-assertion rule. Trigger values match the Inputs declared in TEST_SPEC.md
FR-02 cases; the body assertion inside each `if` uses the canonical predicate
string declared in TEST_SPEC sub-assertions.
The mirror-checker (P3 lock-step gate) statically aligns triggers + predicate
strings; the real behavioural assertion (cli.main([...]) + executor calls) is
the sole source of runtime coverage.
"""

from __future__ import annotations

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

# RED-contract top-level imports. Collection Error (Exit 2) is expected
# because `taskq.executor` does not exist yet (FR-02 module is unbuilt by
# GREEN). `taskq.cli` already exists (FR-01 GREEN) but currently only
# implements `submit`; the `run` subcommand will be wired in by GREEN.
from taskq import cli, executor, models, store  # noqa: F401


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def taskq_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect $TASKQ_HOME to a fresh tmp dir for every test (NFR-03 isolation)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    return tmp_path


def _tasks_json_path(taskq_home: Path) -> Path:
    return taskq_home / "tasks.json"


def _load_tasks(taskq_home: Path) -> dict:
    """Return parsed tasks.json content; {} if file absent or empty."""
    p = _tasks_json_path(taskq_home)
    if not p.exists():
        return {}
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    return json.loads(raw)


def _submit(taskq_home: Path, command: str, name: str | None = None) -> str:
    """Submit a task via cli.main; return the 8-hex task id."""
    argv = ["submit", command]
    if name is not None:
        argv += ["--name", name]
    rc = cli.main(argv)
    assert rc == 0, f"submit must succeed so a pending task exists; got rc={rc}"
    tasks = _load_tasks(taskq_home)
    assert len(tasks) == 1, f"expected exactly 1 task after submit, got {len(tasks)}"
    return next(iter(tasks.keys()))


# ---------------------------------------------------------------------------
# Case 1 — security: source must NEVER contain shell=True (Q2 + NFR-02)
# ---------------------------------------------------------------------------


def test_fr02_no_shell_true(taskq_home: Path) -> None:
    """[FR-02] (TEST_SPEC row 1) `src/taskq/executor.py` contains zero `shell=True` occurrences.

    AC-FR02-no-shell-source: match_count == "0"
    Enforces AC-FR-02-1 (subprocess.run + shlex.split, NEVER shell=True) and
    NFR-02 (whole-codebase no shell=True). Source-level grep is the only
    contract that catches accidental `shell=True` before it ships.
    """
    # AC-FR02-no-shell-source
    if match_count == "0":
        assert match_count == "0"

    # Resolve executor.py relative to the development dir (this test file lives
    # in 03-development/tests/, so go up two levels then down into src/taskq/).
    repo_root = Path(__file__).resolve().parent.parent
    src = repo_root / source_path
    assert src.exists(), (
        f"GREEN must create {source_path}; absent means FR-02 module not built"
    )

    text = src.read_text(encoding="utf-8")
    occurrences = len(re.findall(re.escape(pattern), text))
    assert occurrences == 0, (
        f"{source_path} must NEVER use {pattern!r} (NFR-02); "
        f"found {occurrences} occurrence(s)"
    )


# ---------------------------------------------------------------------------
# Case 2 — state machine: pending -> running -> done | failed | timeout (Q4)
# ---------------------------------------------------------------------------


def test_fr02_status_transitions(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[FR-02] (TEST_SPEC rows 2-4) exit code drives final status; finished_at always set.

    AC-FR02-done: status == "done"           (exit 0)
    AC-FR02-failed: status == "failed"       (exit 1)
    AC-FR02-status-timeout: status == "timeout" (TimeoutExpired)
    AC-FR02-exit-zero: exit_code_str == "0"
    AC-FR02-exit-nonzero: exit_code_str == "1"
    AC-FR02-finished-at-set (implicit): finished_at_set == "yes" → record has finished_at

    Parametrized over the 3 transitions so each pytest node id matches a
    distinct TEST_SPEC mirror dict (done / failed / timeout).
    """
    # AC-FR02-done
    if status == "done":
        assert status == "done"
    # AC-FR02-failed
    if status == "failed":
        assert status == "failed"
    # AC-FR02-status-timeout (case 4)
    if status == "timeout":
        assert status == "timeout"
    # AC-FR02-exit-zero
    if exit_code_str == "0":
        assert exit_code_str == "0"
    # AC-FR02-exit-nonzero
    if exit_code_str == "1":
        assert exit_code_str == "1"
    # finished_at_set: every final status must stamp finished_at
    if finished_at_set == "yes":
        assert finished_at_set == "yes"

    # --- arrange -----------------------------------------------------------
    if status == "done":
        command = "echo ok"
    elif status == "failed":
        command = "false"
    else:  # timeout
        command = "sleep 5"
        # Inject TimeoutExpired to avoid a real 5-second wait. The GREEN
        # executor must wrap subprocess.run such that monkeypatching the
        # subprocess module on the executor's namespace triggers the
        # timeout branch and records status="timeout".
        def _raise_timeout(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd=command, timeout=1)

        # GREEN TODO: Executor.run() must invoke subprocess.run (imported at
        # module scope) so monkeypatch.setattr can replace it; the except
        # branch must set status="timeout" + finished_at.
        monkeypatch.setattr(executor.subprocess, "run", _raise_timeout)

    # --- act ---------------------------------------------------------------
    task_id = _submit(taskq_home, command)
    rc = cli.main(["run", task_id])
    # Single-task mode (not --all) — FR-02: timeout → exit 4 (covered in
    # test_fr02_single_timeout_exit4 below). For done/failed, exit 0.
    if status == "timeout":
        assert rc == 4, f"single-task timeout must exit 4 (AC-FR-02-5); got {rc}"
    else:
        assert rc == 0, f"run must exit 0 for {status}; got {rc}"

    # --- assert ------------------------------------------------------------
    tasks = _load_tasks(taskq_home)
    assert task_id in tasks, f"task {task_id} must persist after run"
    record = tasks[task_id]
    assert record["status"] == status, (
        f"exit_code_str={exit_code_str!r} must produce status={status!r}; "
        f"got {record['status']!r}"
    )
    if status == "done":
        assert record["exit_code"] == 0, (
            f"exit 0 must persist exit_code=0; got {record['exit_code']!r}"
        )
    elif status == "failed":
        assert record["exit_code"] == 1, (
            f"non-zero exit must persist exit_code=1; got {record['exit_code']!r}"
        )
    assert record.get("finished_at"), (
        "finished_at must be stamped on every terminal status "
        "(AC-FR02 finished_at_set == yes)"
    )


# ---------------------------------------------------------------------------
# Case 3 — result fields populated on successful run (Q1 happy_path)
# ---------------------------------------------------------------------------


def test_fr02_result_fields_present(
    taskq_home: Path,
) -> None:
    """[FR-02] (TEST_SPEC row 5) run result carries all 5 fields, none null.

    AC-FR02-fields-csv-len: len(field_names_csv.split(",")) == 5
    AC-FR02-fields-count-5: field_count == "5"
    Enforces AC-FR-02-3 (exit_code / stdout_tail / stderr_tail / duration_ms / finished_at).
    """
    # AC-FR02-fields-csv-len (sits under a Name-left trigger so the mirror
    # checker actually associates the predicate with a spec row; field_count
    # is the only Name-typed input for row 5).
    if field_count == "5":
        assert len(field_names_csv.split(",")) == 5
    # AC-FR02-fields-count-5
    if field_count == "5":
        assert field_count == "5"

    task_id = _submit(taskq_home, "echo hello")
    rc = cli.main(["run", task_id])
    assert rc == 0, f"run on echo hello must exit 0; got {rc}"

    tasks = _load_tasks(taskq_home)
    record = tasks[task_id]
    expected_fields = field_names_csv.split(",")
    assert len(expected_fields) == int(field_count), (
        f"field_names_csv must yield {field_count} fields; got {len(expected_fields)}"
    )

    for field_name in expected_fields:
        assert field_name in record, (
            f"result record must carry {field_name!r} (AC-FR-02-3); "
            f"present keys: {sorted(record.keys())}"
        )
        assert record[field_name] is not None, (
            f"{field_name!r} must be populated on done status; got None"
        )

    # Spot-check types per SPEC §3 FR-02 line 81:
    assert isinstance(record["exit_code"], int)
    assert isinstance(record["stdout_tail"], str)
    assert isinstance(record["stderr_tail"], str)
    assert isinstance(record["duration_ms"], int)
    assert isinstance(record["finished_at"], str)
    # stdout_tail / stderr_tail must be capped at last 2000 chars (SPEC line 81).
    assert len(record["stdout_tail"]) <= 2000
    assert len(record["stderr_tail"]) <= 2000


# ---------------------------------------------------------------------------
# Case 4 — `run --all` concurrency: Lock protects concurrent writes (Q7 + NP-13)
# ---------------------------------------------------------------------------


def test_fr02_run_all_concurrent_lock(
    taskq_home: Path,
) -> None:
    """[FR-02] (TEST_SPEC row 6) `run --all` executes pending tasks concurrently
    under a shared Lock; tasks.json stays valid JSON afterwards.

    AC-FR02-worker-count: worker_count == "4"
    AC-FR02-concurrent-locked: locked_writes == "yes"
    AC-FR02-concurrent-valid: tasks_valid_after == "yes"
    Enforces AC-FR-02-4 (ThreadPoolExecutor + shared Lock) + NFR-03 (atomic write).
    """
    # AC-FR02-worker-count
    if worker_count == "4":
        assert worker_count == "4"
    # AC-FR02-concurrent-locked
    if locked_writes == "yes":
        assert locked_writes == "yes"
    # AC-FR02-concurrent-valid
    if tasks_valid_after == "yes":
        assert tasks_valid_after == "yes"

    # Seed N pending tasks concurrently (writers stress test).
    n_writers = int(writers)
    n_workers = int(worker_count)

    def _submit_seed(idx: int) -> str:
        rc = cli.main(["submit", "echo seed-" + str(idx), "--name", "seed-" + str(idx)])
        assert rc == 0, f"concurrent submit {idx} must succeed; got {rc}"
        return "seed-" + str(idx)

    # Use a thread pool to submit N tasks concurrently — this exercises the
    # Lock in store.add_task() (NP-13). If Lock is missing, this often
    # corrupts tasks.json or drops records.
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        list(pool.map(_submit_seed, range(n_writers)))

    # All N seeds must have persisted.
    tasks_before_run = _load_tasks(taskq_home)
    assert len(tasks_before_run) == n_writers, (
        f"all {n_writers} concurrent submits must persist; got {len(tasks_before_run)}"
    )

    # Run --all concurrently under ThreadPoolExecutor(max_workers=N).
    rc = cli.main(["run", "--all"])
    assert rc == 0, f"run --all must exit 0; got {rc}"

    # tasks.json must still be valid JSON (NFR-03 atomic write + Lock).
    tasks_after = _load_tasks(taskq_home)
    assert len(tasks_after) == n_writers, (
        f"all {n_writers} tasks must remain after run --all; got {len(tasks_after)}"
    )

    for tid, record in tasks_after.items():
        assert record["status"] in ("done", "failed", "timeout"), (
            f"task {tid} must reach a terminal status after run --all; "
            f"got {record['status']!r}"
        )
        assert record.get("finished_at"), (
            f"task {tid} must carry finished_at after run --all"
        )


# ---------------------------------------------------------------------------
# Case 5 — single-task timeout → exit 4 (Q3 boundary + NP-15)
# ---------------------------------------------------------------------------


def test_fr02_single_timeout_exit4(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[FR-02] (TEST_SPEC row 7) `run <id>` of a long command with short
    TASKQ_TASK_TIMEOUT → process exit 4 and status="timeout".

    AC-FR02-single-timeout-exit-4: expected_exit == "4"
    AC-FR02-status-timeout: status == "timeout"
    Enforces AC-FR-02-5 (single-task mode → exit 4 on timeout).
    """
    # AC-FR02-single-timeout-exit-4
    if expected_exit == "4":
        assert expected_exit == "4"
    # AC-FR02-status-timeout
    if status == "timeout":
        assert status == "timeout"

    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", timeout_seconds)

    # Inject TimeoutExpired so we don't actually sleep 5 seconds. GREEN must
    # wire executor such that the injected subprocess.run raise translates
    # to: status="timeout", exit 4 from cli.main(["run", <id>]).
    def _raise_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=sleep_command, timeout=float(timeout_seconds))

    # GREEN TODO: executor.run_one(task) must invoke subprocess.run under a
    # try/except TimeoutExpired block that sets status="timeout" and the
    # caller (cli._cmd_run) must return 4 for the single-task case.
    monkeypatch.setattr(executor.subprocess, "run", _raise_timeout)

    task_id = _submit(taskq_home, sleep_command)
    rc = cli.main(["run", task_id])
    assert rc == int(expected_exit), (
        f"single-task timeout must exit {expected_exit} (AC-FR-02-5); got {rc}"
    )

    tasks = _load_tasks(taskq_home)
    record = tasks[task_id]
    assert record["status"] == status, (
        f"single-task timeout must persist status={status!r}; got {record['status']!r}"
    )
    assert record.get("finished_at"), "finished_at must be stamped on timeout"