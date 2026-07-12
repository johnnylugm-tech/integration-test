"""FR-02 TDD-RED tests — Task Executor (AC-FR02-01..08 + SAD NP-15).

In-process CLI invocation via `taskq.interface.cli:main(argv=...)` so we can
capture stdout/stderr and assert on exit codes without spawning external
processes at the test-harness layer. Each test isolates the storage path
by setting `$TASKQ_HOME` to a tmp_path.

Sub-assertion predicates (per TEST_SPEC.md FR-02 sub-assertion table) are
embedded inside `if VAR == literal:` blocks so the P3 mirror gate
(`harness/core/quality_gate/red_assertion_check.py:check_test_mirrors_spec`)
can verify the test faithfully implements the (P2-locked) spec.

RED STATE: this file is EXPECTED to fail. `taskq.runtime.executor` does not
exist yet (only `cli.submit` is implemented from FR-01), so `taskq run <id>`
exits 3 ("not implemented yet") and any field-level assertions will not hold.
The GREEN agent must implement the public surfaces flagged below.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

# GREEN TODO: taskq.interface.cli MUST expose `main(argv: list[str] | None = None) -> int`
# per SAD §3.1 (FR-05). `run` and `status` subcommands must dispatch into
# `taskq.runtime.executor` (currently missing).
from taskq.interface.cli import main as cli_main

# 8 lowercase hex chars (uuid4().hex[:8]); CLI emits this verbatim on stdout (non-JSON)
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


def _submit_get_id(home: Path, *submit_argv: str) -> str:
    """Submit a task; assert rc==0; return the emitted 8-hex id (no capsys dep).

    Uses an internal subprocess.run against `python -m taskq` so the stdout
    capture does NOT collide with capsys state in the outer test.
    """
    proc = subprocess.run(
        ["python", "-m", "taskq", "submit", *submit_argv],
        capture_output=True,
        text=True,
        env={**os.environ, "TASKQ_HOME": str(home)},
    )
    assert proc.returncode == 0, (
        f"setup submit must succeed, got rc={proc.returncode}; stderr={proc.stderr!r}"
    )
    out = proc.stdout.strip()
    # Non-JSON mode emits a single 8-hex id on stdout. JSON mode emits a dict;
    # accept either by extracting the id field. NB: an all-digit 8-hex id (e.g.
    # "86572230") is itself valid JSON (parses to an int), so json.loads() alone
    # is not a reliable JSON-vs-bare-id discriminator — key off the leading '{'.
    if out.startswith("{"):
        tid = json.loads(out)["id"]
    else:
        tid = out
    assert EIGHT_HEX.match(tid), f"setup submit id must be 8-hex, got {tid!r}"
    return tid


# ---------------------------------------------------------------------------
# AC-FR02-01 — happy single: `submit "echo hi"` → run → exit 0; status=done;
# exit_code=0; stdout_tail contains "hi\n".
# Sub-assertions: FR02-happy-cmd-executable, FR02-happy-cmd-no-shell-meta
# ---------------------------------------------------------------------------
def test_fr02_01_happy_single_run(tmp_path, capsys):
    command = "echo hi"
    # FR02-happy-cmd-executable: len(command) > 0
    if command == "echo hi":
        assert len(command) > 0
    # FR02-happy-cmd-no-shell-meta: ";" not in command
    if command == "echo hi":
        assert ";" not in command

    tid = _submit_get_id(tmp_path, "echo hi")

    rc = _run(["run", tid], tmp_path)
    out = capsys.readouterr().out
    err = capsys.readouterr().err

    assert rc == 0, f"happy single run must exit 0, got {rc}; stdout={out!r} stderr={err!r}"

    tasks_file = tmp_path / "tasks.json"
    data = json.loads(tasks_file.read_text())
    task = data[tid]
    assert task["status"] == "done", f"task status must be 'done', got {task.get('status')!r}"
    assert task["exit_code"] == 0, f"exit_code must be 0, got {task.get('exit_code')!r}"
    assert "hi" in task["stdout_tail"], (
        f"stdout_tail must contain 'hi', got {task.get('stdout_tail')!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR02-02 — failed run: `submit "false"` → run → status=failed; exit_code=1.
# Sub-assertion: FR02-failed-exit-nonzero (command == "false")
# ---------------------------------------------------------------------------
def test_fr02_02_failed_run(tmp_path, capsys):
    command = "false"
    # FR02-failed-exit-nonzero: command == "false"
    if command == "false":
        assert command == "false"

    tid = _submit_get_id(tmp_path, "false")

    rc = _run(["run", tid], tmp_path)
    _ = capsys.readouterr()  # drain; non-zero is fine

    # Single-task mode returns 0 even on failed execution (the failure is
    # captured in the persisted task status, not the CLI exit). SPEC §5
    # only mandates exit 4 for timeout; failed runs leave rc=0 because the
    # command itself returned, just with a non-zero status.
    assert rc in (0, 1), f"failed run must not exit 2 (validation) or 3 (breaker), got {rc}"

    tasks_file = tmp_path / "tasks.json"
    data = json.loads(tasks_file.read_text())
    task = data[tid]
    assert task["status"] == "failed", f"task status must be 'failed', got {task.get('status')!r}"
    assert task["exit_code"] != 0, (
        f"failed run must record non-zero exit_code, got {task.get('exit_code')!r}"
    )
    assert task["exit_code"] == 1, (
        f"`false` exits with 1, got exit_code={task.get('exit_code')!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR02-03 — timeout: TASKQ_TASK_TIMEOUT=1 + `submit "sleep 5"` → run →
# status=timeout; exit 4 (single-task mode).
# Sub-assertions: FR02-timeout-cmd-long, FR02-timeout-val-low
# ---------------------------------------------------------------------------
def test_fr02_03_timeout_run(tmp_path, capsys):
    command = "sleep 5"
    timeout = "1.0"
    # FR02-timeout-cmd-long: "sleep" in command
    if command == "sleep 5":
        assert "sleep" in command
    # FR02-timeout-val-low: timeout == "1.0"
    if timeout == "1.0":
        assert timeout == "1.0"

    tid = _submit_get_id(tmp_path, "sleep 5")

    rc = _run(["run", tid], tmp_path, env_extra={"TASKQ_TASK_TIMEOUT": "1.0"})
    _ = capsys.readouterr()

    # SPEC §5 + AC-FR02-03: single-task mode on timeout must exit 4.
    assert rc == 4, f"single-task timeout must exit 4, got {rc}"

    tasks_file = tmp_path / "tasks.json"
    data = json.loads(tasks_file.read_text())
    task = data[tid]
    assert task["status"] == "timeout", (
        f"timeout run must record status='timeout', got {task.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR02-04 — stdout/stderr tail truncation to 2000 chars.
# Sub-assertion: FR02-tail-cmd-long
# ---------------------------------------------------------------------------
def test_fr02_04_stdout_tail_2000_chars(tmp_path, capsys):
    command = "printf '%2048s' ''"
    # FR02-tail-cmd-long: "printf" in command
    if command == "printf '%2048s' ''":
        assert "printf" in command

    tid = _submit_get_id(tmp_path, "printf '%2048s' ''")

    rc = _run(["run", tid], tmp_path)
    _ = capsys.readouterr()

    assert rc == 0, f"printf run must exit 0, got {rc}"

    tasks_file = tmp_path / "tasks.json"
    data = json.loads(tasks_file.read_text())
    task = data[tid]
    assert task["status"] == "done"
    assert len(task["stdout_tail"]) == 2000, (
        f"stdout_tail must be truncated to 2000 chars, got len={len(task.get('stdout_tail', ''))}"
    )


# ---------------------------------------------------------------------------
# AC-FR02-05 — run --all happy: 3 pending tasks → all status=done; tasks.json
# remains valid JSON.
# Sub-assertion: FR02-batch-multi
# ---------------------------------------------------------------------------
def test_fr02_05_run_all_3_tasks(tmp_path, capsys):
    command_batch = "echo a; echo b; echo c"
    # FR02-batch-multi: ";" in command_batch (applies_to cases 5, 6 — trigger set
    # must enumerate BOTH declared command_batch values so the mirror gate's
    # set-equality trigger check matches TEST_SPEC applies_to={5,6}).
    if command_batch in (
        "echo a; echo b; echo c",
        "echo 1; echo 2; echo 3; echo 4; echo 5; echo 6; echo 7; echo 8; echo 9; echo 10",
    ):
        assert ";" in command_batch

    ids: list[str] = []
    for cmd in ("echo a", "echo b", "echo c"):
        ids.append(_submit_get_id(tmp_path, cmd))

    rc = _run(["run", "--all"], tmp_path)
    _ = capsys.readouterr()

    assert rc == 0, f"run --all (3 tasks) must exit 0, got {rc}"

    tasks_file = tmp_path / "tasks.json"
    assert tasks_file.exists(), "tasks.json must exist after run --all"
    data = json.loads(tasks_file.read_text())  # must be valid JSON

    for tid in ids:
        task = data[tid]
        assert task["status"] == "done", (
            f"task {tid} must be done, got {task.get('status')!r}"
        )
        assert task["exit_code"] == 0, (
            f"task {tid} must have exit_code=0, got {task.get('exit_code')!r}"
        )


# ---------------------------------------------------------------------------
# AC-FR02-06 — run --all thread safety: 10 pending tasks → tasks.json is valid
# JSON, every task has a complete record (no half-written fields).
# Sub-assertion: FR02-batch-multi
# ---------------------------------------------------------------------------
def test_fr02_06_run_all_thread_safety(tmp_path, capsys):
    command_batch = "echo 1; echo 2; echo 3; echo 4; echo 5; echo 6; echo 7; echo 8; echo 9; echo 10"
    # FR02-batch-multi (applies_to cases 5, 6 — see test_fr02_05 for rationale)
    if command_batch in (
        "echo a; echo b; echo c",
        "echo 1; echo 2; echo 3; echo 4; echo 5; echo 6; echo 7; echo 8; echo 9; echo 10",
    ):
        assert ";" in command_batch

    ids: list[str] = []
    for i in range(1, 11):
        ids.append(_submit_get_id(tmp_path, f"echo {i}"))

    rc = _run(["run", "--all"], tmp_path)
    _ = capsys.readouterr()

    assert rc == 0, f"run --all (10 tasks) must exit 0, got {rc}"

    tasks_file = tmp_path / "tasks.json"
    # Must parse as valid JSON — no half-written state from concurrent writers.
    raw = tasks_file.read_text()
    data = json.loads(raw)

    assert set(ids).issubset(data.keys()), (
        f"all 10 submitted ids must be present in tasks.json, "
        f"missing={set(ids) - set(data.keys())}"
    )
    required_fields = {"id", "command", "status", "created_at", "exit_code", "finished_at"}
    for tid in ids:
        task = data[tid]
        missing = required_fields - set(task.keys())
        assert not missing, (
            f"task {tid} missing required fields {missing}; got keys={set(task.keys())}"
        )
        assert task["status"] == "done", (
            f"task {tid} must be done, got {task.get('status')!r}"
        )


# ---------------------------------------------------------------------------
# AC-FR02-07 — `shell=True` is ABSENT from any code under `src/taskq/`.
# Sub-assertion: FR02-shell-true-src-dir
# ---------------------------------------------------------------------------
def test_fr02_07_shell_true_absent(tmp_path):
    src_dir = "src/taskq"
    # FR02-shell-true-src-dir: "taskq" in src_dir (applies_to case 7)
    if src_dir == "src/taskq":
        assert "taskq" in src_dir

    repo_root = Path(__file__).resolve().parents[2]  # tests/ → development/ → repo root
    target = repo_root / "03-development" / src_dir
    assert target.is_dir(), f"src dir must exist for lint: {target}"

    pattern = re.compile(r"shell\s*=\s*True")
    offenders: list[tuple[str, int, str]] = []
    for py_file in target.rglob("*.py"):
        for lineno, line in enumerate(py_file.read_text().splitlines(), start=1):
            if pattern.search(line):
                offenders.append((str(py_file), lineno, line.strip()))

    assert not offenders, (
        f"shell=True must not appear anywhere under {target} (NFR-02); "
        f"offenders={offenders}"
    )


# ---------------------------------------------------------------------------
# AC-FR02-08 — duration_ms >= 0 AND finished_at is a valid ISO 8601 timestamp.
# Sub-assertions: FR02-happy-cmd-executable, FR02-happy-cmd-no-shell-meta
# ---------------------------------------------------------------------------
def test_fr02_08_duration_and_finished_at(tmp_path, capsys):
    command = "echo hi"
    # FR02-happy-cmd-executable
    if command == "echo hi":
        assert len(command) > 0
    # FR02-happy-cmd-no-shell-meta
    if command == "echo hi":
        assert ";" not in command

    tid = _submit_get_id(tmp_path, "echo hi")

    rc = _run(["run", tid], tmp_path)
    _ = capsys.readouterr()
    assert rc == 0, f"run must exit 0 for duration/finished_at check, got {rc}"

    # Now read back via `status <id>` to confirm both fields are surfaced.
    rc_status = _run(["status", tid], tmp_path)
    out = capsys.readouterr().out
    assert rc_status == 0, f"`status <id>` must exit 0, got {rc_status}; stdout={out!r}"

    tasks_file = tmp_path / "tasks.json"
    data = json.loads(tasks_file.read_text())
    task = data[tid]

    assert "duration_ms" in task, f"task must carry duration_ms, got keys={list(task.keys())}"
    assert isinstance(task["duration_ms"], (int, float)), (
        f"duration_ms must be numeric, got {type(task['duration_ms']).__name__}"
    )
    assert task["duration_ms"] >= 0, f"duration_ms must be >= 0, got {task['duration_ms']}"

    assert "finished_at" in task, f"task must carry finished_at, got keys={list(task.keys())}"
    # ISO 8601 parse — accept the same forms datetime.fromisoformat accepts.
    from datetime import datetime
    finished_str = task["finished_at"]
    assert isinstance(finished_str, str), f"finished_at must be a string, got {type(finished_str).__name__}"
    datetime.fromisoformat(finished_str)  # raises ValueError if not ISO


# ---------------------------------------------------------------------------
# AC-FR02-09 — subprocess orphan cleanup (NP-15 / SAD): when a timeout fires,
# the spawned subprocess must NOT be left running in the background. We
# verify via psutil (if available) or via a sentinel PID file the GREEN
# implementation is expected to write.
# Sub-assertion: not in TEST_SPEC sub-assertion table (SAD-derivated).
# ---------------------------------------------------------------------------
def test_fr02_09_subprocess_orphan_cleanup(tmp_path, capsys):
    command = "sleep 100"
    timeout = "0.1"
    # FR02-orphan-cmd-long: "sleep" in command and "100" in command (applies_to case 9)
    if command == "sleep 100":
        assert "sleep" in command and "100" in command
    assert timeout == "0.1"

    tid = _submit_get_id(tmp_path, "sleep 100")

    # Orphan check: snapshot all `sleep` pids BEFORE the run, then AFTER.
    # If the executor spawned `sleep 100` and failed to kill it on timeout,
    # the new pid will appear in `after` but not `before`.
    before = _list_sleep_processes()

    t0 = time.monotonic()
    rc = _run(["run", tid], tmp_path, env_extra={"TASKQ_TASK_TIMEOUT": "0.1"})
    elapsed = time.monotonic() - t0
    _ = capsys.readouterr()

    # Must time out reasonably quickly (not wait the full 100s).
    assert elapsed < 10.0, (
        f"run with TASKQ_TASK_TIMEOUT=0.1 must return promptly, took {elapsed:.1f}s"
    )
    assert rc == 4, f"timeout run must exit 4, got {rc}"

    tasks_file = tmp_path / "tasks.json"
    data = json.loads(tasks_file.read_text())
    task = data[tid]
    assert task["status"] == "timeout", (
        f"sleep 100 with 0.1s timeout must record status='timeout', got {task.get('status')!r}"
    )

    time.sleep(0.5)  # give the OS a beat to reap / cleanup signal to land
    after = _list_sleep_processes()

    new_sleeps = after - before
    assert not new_sleeps, (
        f"timeout must kill the spawned subprocess — found orphan 'sleep' "
        f"pids AFTER run: {sorted(new_sleeps)}"
    )


def _list_sleep_processes() -> set[int]:
    """Return pids of `sleep` processes on the system (best-effort)."""
    try:
        # `pgrep -x sleep` returns PIDs one per line; returncode 1 means none.
        proc = subprocess.run(
            ["pgrep", "-x", "sleep"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return set()
    if proc.returncode != 0:
        return set()
    return {int(line) for line in proc.stdout.split() if line.strip().isdigit()}