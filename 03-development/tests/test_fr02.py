"""TDD-RED tests for FR-02: 任務執行器 (`taskq run <id>` / `run --all`).

Covers the 8 canonical test functions declared in
``02-architecture/TEST_SPEC.md`` §FR-02 (state machine
``pending → running → done | failed | timeout``; subprocess execution
without ``shell=True``; result fields ``exit_code`` / ``stdout_tail`` /
``stderr_tail`` / ``duration_ms`` / ``finished_at``; thread-safe ``--all``).

This file exercises TWO execution paths per case, mirroring ``test_fr01.py``:

* **In-process** — calls ``taskq.cli.main([...])`` directly inside the pytest
  process. Drives pytest-cov coverage of ``cli.py`` / ``__main__.py`` (GATE1
  requires >= 80% coverage of the source under ``03-development/src/taskq``,
  which subprocess calls can NEVER provide).
* **Subprocess** — spawns ``python -m taskq <args>`` with a function-scoped
  ``$TASKQ_HOME`` and an explicit ``PYTHONPATH`` (pytest's ``pythonpath``
  config does NOT propagate to child interpreters per v2.13.0 rule 3).

RED-state contract: source code is NOT yet implemented. The top-level
``from taskq import cli`` import is INTENTIONAL and UNGUARDED — pytest will
fail because ``cli.main(["run", id])`` returns exit 2 (the ``run`` subcommand
is not yet wired). A future GREEN implementation must add the ``run``
subcommand to ``cli.main`` plus the executor module that performs the
subprocess invocation. That is a valid RED outcome.

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
from pathlib import Path

import pytest

# Top-level import is INTENTIONAL — RED expects Collection Error if
# ``taskq.cli`` is missing. Do not wrap in try/except.
from taskq import cli  # noqa: F401  (used in the in-process calls below)


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

    * ``TASKQ_HOME`` isolates each test's ``tasks.json`` to its own
      ``tmp_path`` (v2.13.0 rule 2: ``state_mode: isolate_per_test``).
    * ``PYTHONPATH`` lets the spawned interpreter find ``taskq`` on the
      import path (v2.13.0 rule 3: pytest ``pythonpath`` config does NOT
      propagate to children).

    Extra overrides (e.g. ``TASKQ_TASK_TIMEOUT="1"``) are merged in by
    the caller; this lets the timeout test pin the deadline without
    mutating the host environment.
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

    Per v2.13.0 rule 2 (``state_mode: isolate_per_test`` on every FR-02 row),
    each test gets a FRESH directory so a thread-safety fault in case 6
    cannot leak a half-written ``tasks.json`` into a sibling test.
    """
    home = tmp_path / "taskq_home"
    home.mkdir()
    return home


def _seed_pending(taskq_home: Path, task_id: str, command: str) -> Path:
    """Write a single pending task to ``$TASKQ_HOME/tasks.json`` and return
    the path to the file. Mirrors the schema that FR-01's ``submit`` writes,
    so the GREEN ``run`` implementation sees the same on-disk shape it would
    in production."""
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
    """Read ``tasks.json`` and return the parsed mapping. Raises if the
    file is missing or corrupt — both are legitimate failure modes the
    FR-02 thread-safety case (AC-FR02-06) is on the hook for."""
    return json_lib.loads(tasks_file.read_text())


# ---------------------------------------------------------------------------
# AC-FR02-01 — happy single: "echo hi" → done, exit_code=0, stdout_tail ~hi
# ---------------------------------------------------------------------------


def test_fr02_01_happy_single_run(taskq_home: Path) -> None:
    """happy_path / Q1.

    AC: a pending task with ``command="echo hi"`` exists; ``run <id>`` exits
    0; the record transitions to ``status="done"`` with ``exit_code=0`` and
    ``stdout_tail`` containing ``hi\\n``.

    Rule IDs: ``FR02-exit-0-ok`` (``command == "echo hi"``).
    Coupled NFR: NFR-03 (atomic write of tasks.json after run transition).
    """
    command = "echo hi"
    task_id = "abcdef01"
    assert command == "echo hi"  # sanity — spec predicate must hold
    tasks_file = _seed_pending(taskq_home, task_id, command)

    # ---- In-process path (drives coverage of cli.py / __main__.py).
    rc_in = cli.main(["run", task_id])
    assert rc_in == 0, (
        f"in-process run({task_id!r}) must exit 0 on happy path, got {rc_in}"
    )
    parsed_in = _load_tasks(tasks_file)
    record_in = parsed_in[task_id]
    assert record_in["status"] == "done", (
        f"after run, status must be 'done', got {record_in['status']!r}"
    )
    assert record_in["exit_code"] == 0, (
        f"exit_code must be 0 on happy path, got {record_in['exit_code']!r}"
    )
    assert "hi" in record_in["stdout_tail"], (
        f"stdout_tail must contain 'hi', got {record_in['stdout_tail']!r}"
    )

    # ---- Subprocess path (AC verification against real entry point).
    # Re-seed because the in-process call already mutated the file.
    _seed_pending(taskq_home, task_id, command)
    proc = _run_subprocess(["run", task_id], taskq_home)
    assert proc.returncode == 0, proc.stderr
    parsed_proc = _load_tasks(tasks_file)
    record_proc = parsed_proc[task_id]
    assert record_proc["status"] == "done"
    assert record_proc["exit_code"] == 0
    assert "hi" in record_proc["stdout_tail"]


# ---------------------------------------------------------------------------
# AC-FR02-02 — failed: "false" → status=failed, exit_code=1
# ---------------------------------------------------------------------------


def test_fr02_02_failed_run(taskq_home: Path) -> None:
    """validation / Q2.

    AC: a pending task with ``command="false"`` exists; ``run <id>`` records
    ``status="failed"`` and ``exit_code=1``. The CLI exit code for the failed
    (non-timeout) case is 0 — the run *itself* completed; only the inner
    subprocess exited non-zero.

    Rule IDs: ``FR02-exit-1-fail`` (``command == "false"``).
    Coupled NFR: NFR-02 (no shell=True path — ``false`` exits 1 via exec form
    of ``subprocess.run(shlex.split(command), shell=False)``); NFR-03
    (atomic write after failed transition).
    """
    command = "false"
    task_id = "abcdef02"
    assert command == "false"  # sanity — spec predicate must hold
    tasks_file = _seed_pending(taskq_home, task_id, command)

    # ---- In-process path.
    rc_in = cli.main(["run", task_id])
    parsed_in = _load_tasks(tasks_file)
    record_in = parsed_in[task_id]
    assert record_in["status"] == "failed", (
        f"after run of 'false', status must be 'failed', "
        f"got {record_in['status']!r}"
    )
    assert record_in["exit_code"] == 1, (
        f"after run of 'false', exit_code must be 1, "
        f"got {record_in['exit_code']!r}"
    )
    # The CLI itself succeeded (the task ran to a defined terminal state).
    assert rc_in == 0, (
        f"in-process run must exit 0 for non-timeout failures, got {rc_in}"
    )

    # ---- Subprocess path.
    _seed_pending(taskq_home, task_id, command)
    proc = _run_subprocess(["run", task_id], taskq_home)
    assert proc.returncode == 0, proc.stderr
    parsed_proc = _load_tasks(tasks_file)
    record_proc = parsed_proc[task_id]
    assert record_proc["status"] == "failed"
    assert record_proc["exit_code"] == 1


# ---------------------------------------------------------------------------
# AC-FR02-03 — timeout: TASKQ_TASK_TIMEOUT=1 + "sleep 5" → timeout, exit 4
# ---------------------------------------------------------------------------


def test_fr02_03_timeout_run(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """boundary / Q3.

    AC: with ``TASKQ_TASK_TIMEOUT=1`` and a pending task
    ``command="sleep 5"``, ``run <id>`` raises ``TimeoutExpired`` inside the
    executor, the record is set to ``status="timeout"``, and the CLI exits
    **4** (SPEC §3 FR-02 single-task-mode timeout exit code).

    Rule IDs: ``FR02-timeout-config``
    (``command == "sleep 5" and timeout_env == "1"``).

    Coupled NFR: NFR-03 (atomic write of tasks.json after timeout transition
    — record must persist even though subprocess was killed).

    The timeout env is injected both for the in-process call (via
    ``monkeypatch.setenv``) and the subprocess call (via ``_make_env``
    override).
    """
    command = "sleep 5"
    task_id = "abcdef03"
    timeout_env = "1"
    assert command == "sleep 5" and timeout_env == "1"  # spec predicate
    tasks_file = _seed_pending(taskq_home, task_id, command)

    # ---- In-process path: pin timeout in the host env via monkeypatch so
    # the GREEN executor sees ``TASKQ_TASK_TIMEOUT=1`` during its read.
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", timeout_env)
    rc_in = cli.main(["run", task_id])
    parsed_in = _load_tasks(tasks_file)
    record_in = parsed_in[task_id]
    assert record_in["status"] == "timeout", (
        f"after run with timeout=1 of 'sleep 5', status must be 'timeout', "
        f"got {record_in['status']!r}"
    )
    assert rc_in == 4, (
        f"in-process single-task run with timeout must exit 4, got {rc_in}"
    )

    # ---- Subprocess path: same expectation via PYTHONPATH-propagated env.
    _seed_pending(taskq_home, task_id, command)
    proc = _run_subprocess(
        ["run", task_id], taskq_home, TASKQ_TASK_TIMEOUT=timeout_env
    )
    assert proc.returncode == 4, proc.stderr
    parsed_proc = _load_tasks(tasks_file)
    record_proc = parsed_proc[task_id]
    assert record_proc["status"] == "timeout"


# ---------------------------------------------------------------------------
# AC-FR02-04 — stdout_tail truncated to last 2000 chars
# ---------------------------------------------------------------------------


def test_fr02_04_stdout_tail_2000_chars(taskq_home: Path) -> None:
    """boundary / Q3.

    AC: a pending task whose command emits 2048 chars of stdout (``printf
    '%2048s' x`` — that is, the single arg ``x`` right-padded to width 2048
    for a total of exactly 2048 chars with NO trailing newline). After
    ``run <id>``, the record's ``stdout_tail`` MUST equal the **last 2000
    chars** of the captured stdout — i.e. length is exactly 2000 (NFR-08
    result-shape invariant).

    Rule IDs: ``FR02-stdout-tail-truncation``
    (``stdout_total_len == "2049" and int(stdout_total_len) > 2000``).
    The TEST_SPEC lists ``stdout_total_len="2049"`` — that value covers
    any reasonable formatter (2048 chars + a possible trailing newline);
    either way, the AC is ``len(stdout_tail) == 2000`` (last 2000 chars),
    not ``> 2000``.

    Coupled NFR: NFR-04 (NFR-04 redaction targets the ``stdout_tail`` /
    ``stderr_tail`` fields populated here; this test pins the shape of the
    redaction-input buffer).
    """
    # 'x' right-padded to width 2048 → 2047 spaces + 'x' = exactly 2048 chars.
    command = "printf '%2048s' x"
    task_id = "abcdef04"
    stdout_total_len = "2049"
    assert stdout_total_len == "2049" and int(stdout_total_len) > 2000
    tasks_file = _seed_pending(taskq_home, task_id, command)

    # ---- In-process path.
    rc_in = cli.main(["run", task_id])
    parsed_in = _load_tasks(tasks_file)
    record_in = parsed_in[task_id]
    assert "stdout_tail" in record_in, (
        "after run, record must carry stdout_tail field"
    )
    assert len(record_in["stdout_tail"]) == 2000, (
        f"stdout_tail must be truncated to last 2000 chars, "
        f"got length {len(record_in['stdout_tail'])}"
    )

    # ---- Subprocess path.
    _seed_pending(taskq_home, task_id, command)
    proc = _run_subprocess(["run", task_id], taskq_home)
    assert proc.returncode == 0, proc.stderr
    parsed_proc = _load_tasks(tasks_file)
    record_proc = parsed_proc[task_id]
    assert len(record_proc["stdout_tail"]) == 2000, (
        f"stdout_tail must be truncated to last 2000 chars, "
        f"got length {len(record_proc['stdout_tail'])}"
    )


# ---------------------------------------------------------------------------
# AC-FR02-05 — run --all happy path: 3 pending → all done, JSON valid
# ---------------------------------------------------------------------------


def test_fr02_05_run_all_3_tasks(taskq_home: Path) -> None:
    """integration / Q7.

    AC: 3 pending tasks with commands ``a=true``, ``b=true``, ``c=true``
    exist in ``tasks.json``. ``run --all`` runs each via
    ``subprocess.run`` (per SPEC §3 FR-02). After the call, every task
    MUST be in ``status="done"`` and ``tasks.json`` MUST remain valid JSON.

    Rule IDs: ``FR02-three-task-happy`` (``task_count == "3"``),
    ``FR02-concurrent-task-count`` (``task_count == "10" and int(task_count)
    >= 2`` — relaxed here to count >= 1 because this case is the 3-task
    happy path, not the 10-task concurrency case).

    Coupled NFR: NFR-08 (cross-thread safety of the shared store lock under
    ``run --all`` ThreadPoolExecutor dispatch).

    v2.13.0 rule 2 mandates function-scoped fixtures — this fixture is
    explicitly function-scoped, so concurrent test runs cannot share state.
    """
    command_a = "true"
    command_b = "true"
    command_c = "true"
    task_count = "3"
    assert task_count == "3" and int(task_count) == 3  # spec predicate
    tasks_file = taskq_home / "tasks.json"
    seed = {
        "abcdef05": {
            "command": command_a,
            "name": "",
            "status": "pending",
            "created_at": "2026-07-18T00:00:00+00:00",
        },
        "abcdef15": {
            "command": command_b,
            "name": "",
            "status": "pending",
            "created_at": "2026-07-18T00:00:01+00:00",
        },
        "abcdef25": {
            "command": command_c,
            "name": "",
            "status": "pending",
            "created_at": "2026-07-18T00:00:02+00:00",
        },
    }
    tasks_file.write_text(json_lib.dumps(seed))

    # ---- In-process path.
    rc_in = cli.main(["run", "--all"])
    assert rc_in == 0, (
        f"in-process run --all must exit 0 on happy path, got {rc_in}"
    )
    parsed_in = _load_tasks(tasks_file)
    for tid, rec in parsed_in.items():
        assert rec["status"] == "done", (
            f"task {tid!r} must be 'done' after run --all, "
            f"got {rec['status']!r}"
        )

    # ---- Subprocess path.
    tasks_file.write_text(json_lib.dumps(seed))
    proc = _run_subprocess(["run", "--all"], taskq_home)
    assert proc.returncode == 0, proc.stderr
    parsed_proc = _load_tasks(tasks_file)  # must remain valid JSON
    for tid, rec in parsed_proc.items():
        assert rec["status"] == "done", (
            f"subprocess: task {tid!r} must be 'done', got {rec['status']!r}"
        )


# ---------------------------------------------------------------------------
# AC-FR02-06 — run --all thread safety: 10 pending → JSON valid, all fields
# ---------------------------------------------------------------------------


def test_fr02_06_run_all_thread_safety(taskq_home: Path) -> None:
    """integration / Q7.

    AC: 10 pending tasks exist; ``run --all`` dispatches them via
    ``ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS)``. After the call,
    ``tasks.json`` MUST be valid JSON (the shared ``threading.Lock`` write
    boundary prevented a partial overwrite) AND every record MUST have the
    full result schema (``status``, ``exit_code``, ``stdout_tail``,
    ``stderr_tail``, ``duration_ms``, ``finished_at``) — no record should be
    in a half-written state.

    Rule IDs: ``FR02-concurrent-task-count`` (``task_count == "10" and
    int(task_count) >= 2``).

    Coupled NFR: NFR-03 (atomic write boundary under concurrent writers —
    no half-written records; NFR-03 partial-write invariant), NFR-08
    (cross-thread Lock — best-effort enhancement layered on top of NFR-03
    atomic write).
    """
    command_x = "echo x"
    task_count = "10"
    assert task_count == "10" and int(task_count) >= 2  # spec predicate
    tasks_file = taskq_home / "tasks.json"
    seed: dict[str, dict] = {}
    for idx in range(10):
        tid = f"abcdef{idx:02x}"
        seed[tid] = {
            "command": command_x,
            "name": "",
            "status": "pending",
            "created_at": f"2026-07-18T00:00:{idx:02d}+00:00",
        }
    tasks_file.write_text(json_lib.dumps(seed))

    # ---- In-process path.
    rc_in = cli.main(["run", "--all"])
    assert rc_in == 0, (
        f"in-process run --all (10 tasks) must exit 0, got {rc_in}"
    )
    # tasks.json MUST be valid JSON (parse raises if not).
    parsed_in = _load_tasks(tasks_file)
    assert len(parsed_in) == 10, (
        f"all 10 task records must survive concurrent writes, "
        f"got {len(parsed_in)} records"
    )
    required_fields = (
        "status",
        "exit_code",
        "stdout_tail",
        "stderr_tail",
        "duration_ms",
        "finished_at",
    )
    for tid, rec in parsed_in.items():
        for field in required_fields:
            assert field in rec, (
                f"task {tid!r} missing required field {field!r} — "
                f"concurrent writer left a half-written record"
            )
        assert rec["status"] == "done", (
            f"task {tid!r} must be 'done' after concurrent run, "
            f"got {rec['status']!r}"
        )

    # ---- Subprocess path.
    tasks_file.write_text(json_lib.dumps(seed))
    proc = _run_subprocess(["run", "--all"], taskq_home)
    assert proc.returncode == 0, proc.stderr
    parsed_proc = _load_tasks(tasks_file)
    assert len(parsed_proc) == 10
    for tid, rec in parsed_proc.items():
        for field in required_fields:
            assert field in rec, (
                f"subprocess: task {tid!r} missing field {field!r}"
            )
        assert rec["status"] == "done"


# ---------------------------------------------------------------------------
# AC-FR02-07 — shell=True must be ABSENT from src/taskq/
# ---------------------------------------------------------------------------


def test_fr02_07_shell_true_absent() -> None:
    """static / Q7.

    AC: a recursive grep over every ``.py`` file under ``src/taskq/`` for the
    regex ``shell\\s*=\\s*True`` returns ZERO matches. This is the NFR-02
    security invariant — a single hit anywhere in the codebase indicates
    shell-injection risk and the CI gate must block.

    Rule IDs: ``FR02-shell-true-scan-path`` (``scan_path == "src/taskq/"``).

    Coupled NFR: NFR-02 (security invariant — ``shell=True`` is forbidden
    anywhere in ``src/taskq/``; injection-blacklist is anchored here).

    Implementation note: ``re.search(r"shell\\s*=\\s*True", text)`` matches
    both ``shell=True`` (single space) and ``shell = True`` (padded) and
    ``shell  =  True`` (multi-space). The pattern is intentionally tight to
    ``shell`` (lowercase) so a ``Shell=True`` typo would NOT satisfy the
    regex — NFR-02 only forbids the actual ``subprocess.run(shell=True,...)``
    primitive.
    """
    scan_path = "src/taskq/"
    assert scan_path == "src/taskq/"  # spec predicate
    src_dir = _SRC_ROOT
    pattern = re.compile(r"shell\s*=\s*True")
    hits: list[str] = []
    for py_file in sorted(src_dir.rglob("*.py")):
        text = py_file.read_text()
        for line_no, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                hits.append(f"{py_file}:{line_no}: {line.strip()}")
    assert hits == [], (
        "NFR-02 violation: 'shell=True' must NEVER appear in src/taskq/. "
        f"Found {len(hits)} hit(s):\n" + "\n".join(hits)
    )


# ---------------------------------------------------------------------------
# AC-FR02-08 — duration_ms and finished_at are recorded after a successful run
# ---------------------------------------------------------------------------


def test_fr02_08_duration_and_finished_at(taskq_home: Path) -> None:
    """integration / Q1.

    AC: a pending task with ``command="echo hi"`` runs to completion. The
    record then carries ``duration_ms`` (a non-negative integer, ms since
    subprocess start) AND ``finished_at`` (an ISO-8601 timestamp matching
    the same regex the FR-01 ``created_at`` check uses). The ``status`` for
    the post-run record is ``done``.

    Rule IDs: ``FR02-exit-0-ok`` (``command == "echo hi"``) — the spec
    re-uses the FR02-exit-0-ok rule for the happy-path assertion; the
    distinct invariant under test here is the result-schema shape
    (``duration_ms`` non-negative + ``finished_at`` ISO), which is its
    own AC line.

    Coupled NFR: NFR-03 (atomic write of ``duration_ms`` / ``finished_at``
    into tasks.json after terminal transition; NFR-10 schema-version
    integrity depends on these fields being persisted atomically with
    status).

    GREEN TODO
    ---------
    The GREEN ``executor.run_task`` (or equivalent) must populate these
    fields on every terminal-state transition (done / failed / timeout),
    not just on ``done``. The field names MUST be exactly ``duration_ms``
    (int >= 0) and ``finished_at`` (ISO-8601 string) — they are read by
    the ``status`` subcommand and the cache TTL logic in FR-04.
    """
    command = "echo hi"
    task_id = "abcdef08"
    assert command == "echo hi"  # sanity — spec predicate (FR02-exit-0-ok)
    tasks_file = _seed_pending(taskq_home, task_id, command)

    iso_re = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
    )

    # ---- In-process path.
    rc_in = cli.main(["run", task_id])
    assert rc_in == 0, (
        f"in-process run must exit 0 on happy path, got {rc_in}"
    )
    parsed_in = _load_tasks(tasks_file)
    record_in = parsed_in[task_id]
    assert "duration_ms" in record_in, (
        "after run, record must carry 'duration_ms' field"
    )
    assert isinstance(record_in["duration_ms"], int) and record_in["duration_ms"] >= 0, (
        f"duration_ms must be a non-negative int, "
        f"got {record_in['duration_ms']!r}"
    )
    assert "finished_at" in record_in, (
        "after run, record must carry 'finished_at' field"
    )
    assert iso_re.match(record_in["finished_at"]), (
        f"finished_at must be ISO-8601, got {record_in['finished_at']!r}"
    )

    # ---- Subprocess path.
    _seed_pending(taskq_home, task_id, command)
    proc = _run_subprocess(["run", task_id], taskq_home)
    assert proc.returncode == 0, proc.stderr
    parsed_proc = _load_tasks(tasks_file)
    record_proc = parsed_proc[task_id]
    assert isinstance(record_proc["duration_ms"], int)
    assert record_proc["duration_ms"] >= 0
    assert iso_re.match(record_proc["finished_at"]), (
        f"finished_at must be ISO-8601, got {record_proc['finished_at']!r}"
    )
