"""TDD-RED tests for FR-05: CLI 整合 (argparse + exit codes).

Covers the 7 canonical test functions declared in
``02-architecture/TEST_SPEC.md`` §FR-05 (11 case rows total; the exit-code
case ``test_fr05_07_exit_code_map`` is parametrized over the five SPEC §7
exit codes ``0 / 1 / 2 / 3 / 4``):

* AC-FR05-01 — ``status <id>`` prints all task fields.
* AC-FR05-02 — ``status <id> --json`` prints a single-line JSON document.
* AC-FR05-03 — ``list`` with three pending tasks → all rows visible.
* AC-FR05-04 — ``list --status done`` filters out non-done rows.
* AC-FR05-05 — ``clear`` empties the data files in ``$TASKQ_HOME``.
* AC-FR05-06 — ``status deadbeef`` → exit 2 (unknown task id).
* AC-FR05-07 — exit-code map (parametrized over 5 rows under one canonical
  function name ``test_fr05_07_exit_code_map``):

  * row 7  — ``run <id>`` happy echo hi  → exit 0
  * row 8  — ``tasks.json`` invalid_json → exit 1
  * row 9  — ``submit ""`` (empty)       → exit 2
  * row 10 — breaker OPEN threshold      → exit 3
  * row 11 — ``run <id>`` sleep 5 + timeout → exit 4

This file exercises TWO execution paths per case, mirroring ``test_fr01.py``
/ ``test_fr04.py``:

* **In-process** — calls ``taskq.cli.main([...])`` directly inside the
  pytest process. Gives pytest-cov coverage of ``cli.py`` / ``__main__.py``
  (GATE1 requires >= 80% coverage of the source under
  ``03-development/src/taskq``, which subprocess calls can NEVER provide).
* **Subprocess** — spawns ``python -m taskq <args>`` with a function-scoped
  ``$TASKQ_HOME`` and an explicit ``PYTHONPATH`` (pytest's ``pythonpath``
  config does NOT propagate to child interpreters per v2.13.0 rule 3).

RED-state contract: the GREEN ``status`` / ``list`` / ``clear`` subcommands
plus the FR-05 exit-code map (specifically exit 1 on ``tasks.json``
corruption) are NOT yet implemented — cases 1-6 will route through
``cli.main``'s ``unknown command`` arm and exit 2 for the wrong reason, and
case 8 (exit 1) will silently no-op because the loader swallows the
``JSONDecodeError`` and returns an empty mapping. That is a valid RED
outcome per v2.13.0.

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
# ``taskq.cli`` is missing OR has not yet grown the ``status`` / ``list``
# / ``clear`` subcommands. Do not wrap in try/except.
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

    Extra overrides (``TASKQ_TASK_TIMEOUT``, ``TASKQ_BREAKER_THRESHOLD``,
    ...) are merged in by the caller; this lets each test pin its config
    knobs without mutating the host environment.
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

    Per v2.13.0 rule 2 (``state_mode: isolate_per_test`` on every FR-05
    row), each test gets a FRESH directory so a corruption injection in
    the exit-1 row (case 8) cannot leak into a sibling test's
    ``tasks.json``-is-valid-JSON check.
    """
    home = tmp_path / "taskq_home"
    home.mkdir()
    return home


def _seed_tasks(
    taskq_home: Path,
    tasks: dict[str, dict],
) -> Path:
    """Write ``$TASKQ_HOME/tasks.json`` with the supplied mapping and return
    the file path. Mirrors the schema that FR-01's ``submit`` writes so
    the GREEN ``status`` / ``list`` / ``clear`` implementations see the
    same on-disk shape they would in production."""
    tasks_file = taskq_home / "tasks.json"
    tasks_file.write_text(json_lib.dumps(tasks))
    return tasks_file


def _seed_pending(
    taskq_home: Path, task_id: str, command: str
) -> Path:
    """Write a single pending task to ``$TASKQ_HOME/tasks.json`` and return
    the path to the file. Convenience wrapper around ``_seed_tasks`` for
    the single-task cases."""
    record = {
        "command": command,
        "name": "",
        "status": "pending",
        "created_at": "2026-07-18T00:00:00+00:00",
    }
    return _seed_tasks(taskq_home, {task_id: record})


def _load_tasks(tasks_file: Path) -> dict[str, dict]:
    """Read ``tasks.json`` and return the parsed mapping. Raises if the
    file is missing or corrupt — both are legitimate failure modes the
    FR-05-07 exit-1 corruption case is on the hook for."""
    return json_lib.loads(tasks_file.read_text())


# ---------------------------------------------------------------------------
# AC-FR05-01 — status <id> prints all task fields
# ---------------------------------------------------------------------------


def test_fr05_01_status_all_fields(taskq_home: Path) -> None:
    """happy_path / Q1.

    AC: a pending task with ``command="echo hi"`` exists in
    ``tasks.json``. ``status <id>`` MUST (a) exit 0, (b) print a
    human-readable rendering that carries the task id, the literal
    command string, the status, and an ISO-8601 ``created_at``.

    Rule IDs: ``FR05-status-happy``
    (``command == "echo hi" and task_id == "abcdef01"``).

    Coupled NFR: NFR-08 (cross-process safety of the read; ``status``
    uses the same file lock as ``run``).
    """
    command = "echo hi"
    task_id = "abcdef01"
    assert command == "echo hi" and task_id == "abcdef01"  # spec predicate
    tasks_file = _seed_pending(taskq_home, task_id, command)

    # ---- In-process path (drives coverage of cli.py / __main__.py).
    stdout_buf = io.StringIO()
    with contextlib.redirect_stdout(stdout_buf):
        rc_in = cli.main(["status", task_id])
    assert rc_in == 0, (
        f"in-process status({task_id!r}) must exit 0, got {rc_in}"
    )
    rendered_in = stdout_buf.getvalue()
    assert task_id in rendered_in, (
        f"status output must include task id {task_id!r}, "
        f"got: {rendered_in!r}"
    )
    assert command in rendered_in, (
        f"status output must include command {command!r}, "
        f"got: {rendered_in!r}"
    )
    assert "pending" in rendered_in, (
        f"status output must include status 'pending', "
        f"got: {rendered_in!r}"
    )
    # The ISO-8601 created_at sentinel is seeded verbatim — must appear.
    assert "2026-07-18T00:00:00+00:00" in rendered_in, (
        f"status output must include ISO-8601 created_at, "
        f"got: {rendered_in!r}"
    )

    # ---- Subprocess path (AC verification against the real entry point).
    _seed_pending(taskq_home, task_id, command)
    proc = _run_subprocess(["status", task_id], taskq_home)
    assert proc.returncode == 0, proc.stderr
    assert task_id in proc.stdout
    assert command in proc.stdout
    assert "pending" in proc.stdout


# ---------------------------------------------------------------------------
# AC-FR05-02 — status <id> --json prints a single-line JSON document
# ---------------------------------------------------------------------------


def test_fr05_02_status_json(taskq_home: Path) -> None:
    """happy_path / Q1.

    AC: a pending task with ``command="echo hi"`` exists in
    ``tasks.json``. ``status <id> --json`` MUST (a) exit 0, (b) print a
    single-line JSON object carrying ``id``, ``command``, ``status``,
    ``created_at`` keys (NFR-06 machine-readable contract).

    Rule IDs: ``FR05-status-json-flag`` (``json_flag == "true"``).
    """
    command = "echo hi"
    task_id = "abcdef02"
    json_flag = "true"
    assert json_flag == "true"  # spec predicate
    assert command == "echo hi"
    _seed_pending(taskq_home, task_id, command)

    # ---- In-process path.
    stdout_buf = io.StringIO()
    with contextlib.redirect_stdout(stdout_buf):
        rc_in = cli.main(["status", "--json", task_id])
    assert rc_in == 0, (
        f"in-process status --json {task_id!r} must exit 0, got {rc_in}"
    )
    out_in = stdout_buf.getvalue().strip()
    assert "\n" not in out_in, (
        f"status --json output must be single-line, got: {out_in!r}"
    )
    payload_in = json_lib.loads(out_in)
    assert payload_in.get("id") == task_id, (
        f"status --json payload must carry id={task_id!r}, "
        f"got {payload_in.get('id')!r}"
    )
    assert payload_in.get("command") == command
    assert payload_in.get("status") == "pending"

    # ---- Subprocess path.
    _seed_pending(taskq_home, task_id, command)
    proc = _run_subprocess(["status", "--json", task_id], taskq_home)
    assert proc.returncode == 0, proc.stderr
    out_line = proc.stdout.strip()
    assert "\n" not in out_line, (
        f"status --json (subprocess) output must be single-line, "
        f"got: {out_line!r}"
    )
    payload = json_lib.loads(out_line)
    assert payload.get("id") == task_id
    assert payload.get("command") == command
    assert payload.get("status") == "pending"


# ---------------------------------------------------------------------------
# AC-FR05-03 — list with three pending tasks → all rows visible
# ---------------------------------------------------------------------------


def test_fr05_03_list_happy(taskq_home: Path) -> None:
    """happy_path / Q1.

    AC: three pending tasks with commands ``a`` / ``b`` / ``c`` exist in
    ``tasks.json``. ``list`` MUST (a) exit 0, (b) print all three task
    ids AND their command strings (one row per task, in any order).

    Rule IDs: ``FR05-list-three-rows``
    (``task_count == "3" and int(task_count) == 3``).
    """
    command_a = "echo a"
    command_b = "echo b"
    command_c = "echo c"
    task_count = "3"
    assert task_count == "3" and int(task_count) == 3  # spec predicate

    tasks_file = _seed_tasks(
        taskq_home,
        {
            "aaaaaa01": {
                "command": command_a,
                "name": "",
                "status": "pending",
                "created_at": "2026-07-18T00:00:00+00:00",
            },
            "bbbbbb01": {
                "command": command_b,
                "name": "",
                "status": "pending",
                "created_at": "2026-07-18T00:00:01+00:00",
            },
            "cccccc01": {
                "command": command_c,
                "name": "",
                "status": "pending",
                "created_at": "2026-07-18T00:00:02+00:00",
            },
        },
    )

    expected_ids = ("aaaaaa01", "bbbbbb01", "cccccc01")
    expected_commands = (command_a, command_b, command_c)

    # ---- In-process path.
    stdout_buf = io.StringIO()
    with contextlib.redirect_stdout(stdout_buf):
        rc_in = cli.main(["list"])
    assert rc_in == 0, (
        f"in-process list must exit 0 on happy path, got {rc_in}"
    )
    rendered_in = stdout_buf.getvalue()
    for tid in expected_ids:
        assert tid in rendered_in, (
            f"in-process list output must include task id {tid!r}, "
            f"got: {rendered_in!r}"
        )
    for cmd in expected_commands:
        assert cmd in rendered_in, (
            f"in-process list output must include command {cmd!r}, "
            f"got: {rendered_in!r}"
        )

    # ---- Subprocess path.
    tasks_file.write_text(
        json_lib.dumps(
            {
                tid: {
                    "command": cmd,
                    "name": "",
                    "status": "pending",
                    "created_at": f"2026-07-18T00:00:{i:02d}+00:00",
                }
                for i, (tid, cmd) in enumerate(
                    zip(expected_ids, expected_commands)
                )
            }
        )
    )
    proc = _run_subprocess(["list"], taskq_home)
    assert proc.returncode == 0, proc.stderr
    for tid in expected_ids:
        assert tid in proc.stdout, (
            f"subprocess list output must include task id {tid!r}, "
            f"got: {proc.stdout!r}"
        )
    for cmd in expected_commands:
        assert cmd in proc.stdout, (
            f"subprocess list output must include command {cmd!r}, "
            f"got: {proc.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-FR05-04 — list --status done filters out non-done rows
# ---------------------------------------------------------------------------


def test_fr05_04_list_filter_done(taskq_home: Path) -> None:
    """happy_path / Q1.

    AC: ``tasks.json`` carries ``task_total=5`` tasks, of which
    ``task_done=3`` are in ``status="done"`` and the remaining 2 are in
    other statuses (``pending`` / ``running``). ``list --status done``
    MUST (a) exit 0, (b) print ONLY the 3 done-task ids, (c) NOT print
    any of the 2 non-done ids.

    Rule IDs: ``FR05-list-filter-done``
    (``status_filter == "done" and task_done == "3" and task_total == "5"
    and int(task_done) <= int(task_total)``).
    """
    task_total = "5"
    task_done = "3"
    status_filter = "done"
    assert (
        status_filter == "done"
        and task_done == "3"
        and task_total == "5"
        and int(task_done) <= int(task_total)
    )  # spec predicate

    # 5 records: 3 done + 1 pending + 1 running.
    tasks_file = _seed_tasks(
        taskq_home,
        {
            "aaaaaa01": {
                "command": "echo done-a",
                "name": "",
                "status": "done",
                "created_at": "2026-07-18T00:00:00+00:00",
            },
            "aaaaaa02": {
                "command": "echo done-b",
                "name": "",
                "status": "done",
                "created_at": "2026-07-18T00:00:01+00:00",
            },
            "aaaaaa03": {
                "command": "echo done-c",
                "name": "",
                "status": "done",
                "created_at": "2026-07-18T00:00:02+00:00",
            },
            "bbbbbb01": {
                "command": "echo pending-x",
                "name": "",
                "status": "pending",
                "created_at": "2026-07-18T00:00:03+00:00",
            },
            "bbbbbb02": {
                "command": "echo running-y",
                "name": "",
                "status": "running",
                "created_at": "2026-07-18T00:00:04+00:00",
            },
        },
    )

    done_ids = ("aaaaaa01", "aaaaaa02", "aaaaaa03")
    other_ids = ("bbbbbb01", "bbbbbb02")

    # ---- In-process path.
    stdout_buf = io.StringIO()
    with contextlib.redirect_stdout(stdout_buf):
        rc_in = cli.main(["list", "--status", status_filter])
    assert rc_in == 0, (
        f"in-process list --status {status_filter!r} must exit 0, got {rc_in}"
    )
    rendered_in = stdout_buf.getvalue()
    for tid in done_ids:
        assert tid in rendered_in, (
            f"in-process list --status done must include done id {tid!r}, "
            f"got: {rendered_in!r}"
        )
    for tid in other_ids:
        assert tid not in rendered_in, (
            f"in-process list --status done must NOT include non-done "
            f"id {tid!r}, got: {rendered_in!r}"
        )

    # ---- Subprocess path.
    proc = _run_subprocess(
        ["list", "--status", status_filter], taskq_home
    )
    assert proc.returncode == 0, proc.stderr
    for tid in done_ids:
        assert tid in proc.stdout, (
            f"subprocess list --status done must include done id {tid!r}, "
            f"got: {proc.stdout!r}"
        )
    for tid in other_ids:
        assert tid not in proc.stdout, (
            f"subprocess list --status done must NOT include non-done "
            f"id {tid!r}, got: {proc.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-FR05-05 — clear empties the data files in $TASKQ_HOME
# ---------------------------------------------------------------------------


def test_fr05_05_clear(taskq_home: Path) -> None:
    """happy_path / Q1.

    AC: a pending task with ``command="echo hi"`` exists in
    ``tasks.json``. ``clear`` MUST (a) exit 0, (b) leave ``tasks.json``
    empty (zero records) — SPEC §3 FR-05 explicitly states
    ``clear`` clears ALL data files in ``$TASKQ_HOME``.

    Rule IDs: ``FR05-clear-clears`` (``command == "echo hi"``).

    The test seeds ONLY ``tasks.json`` (no cache.json / breaker.json);
    after ``clear`` runs, ``tasks.json`` MUST either be removed entirely
    or contain an empty mapping. Either is a valid GREEN outcome — both
    satisfy the SPEC §3 FR-05 ``清空 $TASKQ_HOME 全部資料檔`` contract.
    """
    command = "echo hi"
    task_id = "abcdef05"
    assert command == "echo hi"  # spec predicate
    tasks_file = _seed_pending(taskq_home, task_id, command)

    # ---- In-process path.
    rc_in = cli.main(["clear"])
    assert rc_in == 0, f"in-process clear must exit 0, got {rc_in}"

    if tasks_file.exists():
        post_in = json_lib.loads(tasks_file.read_text())
        assert post_in == {}, (
            f"in-process clear must leave tasks.json empty (zero records), "
            f"got {post_in!r}"
        )

    # ---- Subprocess path: re-seed and clear via the real entry point.
    _seed_pending(taskq_home, task_id, command)
    proc = _run_subprocess(["clear"], taskq_home)
    assert proc.returncode == 0, proc.stderr
    if tasks_file.exists():
        post_proc = json_lib.loads(tasks_file.read_text())
        assert post_proc == {}, (
            f"subprocess clear must leave tasks.json empty (zero records), "
            f"got {post_proc!r}"
        )


# ---------------------------------------------------------------------------
# AC-FR05-06 — status <unknown-id> → exit 2 (unknown task id)
# ---------------------------------------------------------------------------


def test_fr05_06_unknown_task_id(taskq_home: Path) -> None:
    """validation / Q2.

    AC: an 8-hex task id that is NOT present in ``tasks.json``
    (``unknown_id="deadbeef"``) is passed to ``status``. The CLI MUST
    exit 2 with a stderr message indicating the id is unknown.

    Rule IDs: ``FR05-unknown-id-format``
    (``len(unknown_id) == 8 and unknown_id == "deadbeef"``).

    SPEC §7 exit-code table explicitly maps
    ``unknown task id → 2 (輸入驗證錯誤)``.
    """
    unknown_id = "deadbeef"
    assert len(unknown_id) == 8 and unknown_id == "deadbeef"  # spec predicate

    # Empty tasks.json — no record for the requested id.
    _seed_tasks(taskq_home, {})

    # ---- In-process path.
    stderr_buf = io.StringIO()
    stdout_buf = io.StringIO()
    with contextlib.redirect_stderr(stderr_buf), contextlib.redirect_stdout(stdout_buf):
        rc_in = cli.main(["status", unknown_id])
    assert rc_in == 2, (
        f"in-process status({unknown_id!r}) on a missing id must exit 2, "
        f"got {rc_in}; stderr={stderr_buf.getvalue()!r}"
    )
    assert stderr_buf.getvalue().strip() != "", (
        "in-process unknown-id rejection must write a stderr message"
    )
    assert stdout_buf.getvalue().strip() == "", (
        "in-process unknown-id rejection must NOT write to stdout"
    )

    # ---- Subprocess path.
    _seed_tasks(taskq_home, {})
    proc = _run_subprocess(["status", unknown_id], taskq_home)
    assert proc.returncode == 2, (
        f"subprocess status({unknown_id!r}) on a missing id must exit 2, "
        f"got rc={proc.returncode}, stderr={proc.stderr!r}"
    )
    assert proc.stderr.strip() != "", (
        "subprocess unknown-id rejection must write a stderr message"
    )


# ---------------------------------------------------------------------------
# AC-FR05-07 — exit-code map (parametrized over 5 SPEC §7 rows)
# ---------------------------------------------------------------------------


# A no-op sleep — when substituted into the GREEN retry loop, every retry
# attempt fires immediately without waiting for the real wall clock. Used
# by the exit-3 (breaker) row which drives 3 final-failing tasks.
def _instant_sleep(_seconds: float) -> None:  # pragma: no cover - test-only
    return None


@pytest.mark.parametrize(
    ("expected_exit", "subcommand", "argv", "pred_args", "env_overrides", "corrupt_setup"),
    [
        # ---- Row 7 — exit 0: happy `run <id>` with command="echo hi".
        (
            0,
            "run",
            ["run", "abcdef07"],
            {"command": "echo hi"},
            {},
            None,
        ),
        # ---- Row 8 — exit 1: tasks.json invalid_json → corruption-detected.
        (
            1,
            "run",
            ["run", "abcdef08"],
            {"fault_target": "tasks.json", "corruption_kind": "invalid_json"},
            {},
            "invalid_json",
        ),
        # ---- Row 9 — exit 2: `submit ""` (empty command).
        (
            2,
            "submit",
            ["submit", ""],
            {"command": ""},
            {},
            None,
        ),
        # ---- Row 10 — exit 3: breaker OPEN after threshold trip.
        (
            3,
            "run",
            ["run", "abcdef10"],
            {"threshold_env": "3", "consecutive_failures": "3"},
            {
                "TASKQ_BREAKER_THRESHOLD": "3",
                "TASKQ_RETRY_LIMIT": "0",
                "TASKQ_BACKOFF_BASE": "0",
            },
            None,
        ),
        # ---- Row 11 — exit 4: `run <id>` with sleep 5 + timeout.
        (
            4,
            "run",
            ["run", "abcdef11"],
            {"command": "sleep 5", "timeout_env": "1"},
            {"TASKQ_TASK_TIMEOUT": "1"},
            None,
        ),
    ],
    ids=[
        "exit-0-run-happy-echo-hi",
        "exit-1-run-tasks-json-corruption",
        "exit-2-submit-empty-command",
        "exit-3-run-breaker-open-threshold",
        "exit-4-run-timeout-sleep-5",
    ],
)
def test_fr05_07_exit_code_map(
    expected_exit: int,
    subcommand: str,
    argv: list,
    pred_args: dict,
    env_overrides: dict,
    corrupt_setup: str | None,
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """integration / Q4 (exit-code map — 5 parametrize rows).

    AC: each parametrize row exercises ONE of SPEC §7's five exit codes
    (0 / 1 / 2 / 3 / 4) and MUST exit with the matching code:

    * row 7  (exit 0): ``run <id>`` on a pending ``command="echo hi"``
      task completes successfully → exit 0.
    * row 8  (exit 1): ``tasks.json`` contains invalid JSON
      (``corruption_kind == "invalid_json"``) — the GREEN CLI MUST detect
      the corruption on startup, write an error to stderr, and exit 1
      (SPEC §7 ``其他內部錯誤``). NFR-03 forbids silent rebuild; the
      loader MUST surface the failure.
    * row 9  (exit 2): ``submit ""`` (empty command) — already exits 2
      via FR-01 validation; AC is the mapping ``empty → 2``.
    * row 10 (exit 3): three consecutive final-failing ``run`` calls trip
      the breaker to ``OPEN`` (TASKQ_BREAKER_THRESHOLD=3); a fourth
      ``run <id>`` is rejected with exit 3 + stderr ``breaker open``.
    * row 11 (exit 4): ``run <id>`` with ``TASKQ_TASK_TIMEOUT=1`` on a
      ``sleep 5`` task → inner subprocess hits timeout → CLI exits 4.

    Rule IDs (one per parametrize row):

    * ``FR05-exit-0-command``        (``command == "echo hi"``) — row 7
    * ``FR05-exit-1-corruption``      (``corruption_kind == "invalid_json"
      and fault_target == "tasks.json"``) — row 8
    * ``FR05-exit-2-empty-command``   (``command == "" and len(command)
      == 0``) — row 9
    * ``FR05-exit-3-breaker-threshold`` (``threshold_env == "3" and
      consecutive_failures == "3"``) — row 10
    * ``FR05-exit-4-timeout-env``     (``command == "sleep 5" and
      timeout_env == "1"``) — row 11

    The ``subcommand`` + ``cli_args`` (callable returning the argv list)
    + ``env_overrides`` triple picks the right CLI surface per row;
    ``corrupt_setup == "invalid_json"`` is the marker for the exit-1
    row's ``tasks.json``-corruption precondition.

    state_mode: ``isolate_per_test`` ⇒ ``taskq_home`` is fresh per test.
    """
    # ---- Spec-predicate assertions (mirror the TEST_SPEC §FR-05 sub-
    # assertion table; one literal row per parametrize index so the
    # MIRROR checker can match the canonical predicate text).
    if expected_exit == 0:
        assert pred_args["command"] == "echo hi"
    elif expected_exit == 1:
        assert (
            pred_args["corruption_kind"] == "invalid_json"
            and pred_args["fault_target"] == "tasks.json"
        )
    elif expected_exit == 2:
        assert pred_args["command"] == "" and len(pred_args["command"]) == 0
    elif expected_exit == 3:
        assert (
            pred_args["threshold_env"] == "3"
            and pred_args["consecutive_failures"] == "3"
        )
    elif expected_exit == 4:
        assert (
            pred_args["command"] == "sleep 5"
            and pred_args["timeout_env"] == "1"
        )

    # ---- Pre-seed per row.
    tasks_file = taskq_home / "tasks.json"
    if expected_exit == 0:
        # Pending happy task; one record.
        _seed_pending(taskq_home, "abcdef07", "echo hi")
    elif expected_exit == 1:
        # Corrupt tasks.json on disk — the GREEN CLI must detect on
        # startup and exit 1 (NFR-03 forbids silent rebuild).
        tasks_file.write_text("{this is not valid json")
    elif expected_exit == 2:
        # submit "" path needs no pre-seed — the validation runs first.
        pass
    elif expected_exit == 3:
        # Seed 4 pending tasks of the same failing command so the first
        # 3 trips and the 4th is the breaker-rejected probe.
        seed: dict[str, dict] = {}
        for idx in range(4):
            tid = f"abcdef{idx:02x}"
            seed[tid] = {
                "command": "false",
                "name": "",
                "status": "pending",
                "created_at": f"2026-07-18T00:00:{idx:02d}+00:00",
            }
        tasks_file.write_text(json_lib.dumps(seed))
    elif expected_exit == 4:
        # Pending sleep-5 task; the run will hit TASKQ_TASK_TIMEOUT.
        _seed_pending(taskq_home, "abcdef11", "sleep 5")

    # ---- In-process env pin (matches the subprocess env_overrides).
    for key, value in env_overrides.items():
        monkeypatch.setenv(key, value)

    # The exit-3 row uses the GREEN retry loop's injected sleep hook —
    # substitute a no-op so the test does not actually wait for the
    # backoff between attempts.
    if expected_exit == 3:
        monkeypatch.setattr(
            "taskq.executor.sleep", _instant_sleep, raising=False
        )

    # ---- In-process path.
    if expected_exit == 3:
        # Drive 3 final-failing runs in-process to trip the breaker, then
        # assert the 4th run is rejected with exit 3.
        for idx in range(3):
            rc = cli.main(["run", f"abcdef{idx:02x}"])
            assert rc == 0, (
                f"in-process: pre-threshold run of {idx!r} must exit 0, "
                f"got {rc}"
            )
        stderr_buf = io.StringIO()
        with contextlib.redirect_stderr(stderr_buf):
            rc_in = cli.main(["run", "abcdef03"])
        assert rc_in == expected_exit, (
            f"in-process exit-code-map row (exit={expected_exit}) must "
            f"return {expected_exit}, got {rc_in}; "
            f"stderr={stderr_buf.getvalue()!r}"
        )
        # Row 10 also asserts the stderr substring per FR-03 row 4 contract.
        assert "breaker open" in stderr_buf.getvalue(), (
            f"in-process exit-3 row must surface 'breaker open' in stderr, "
            f"got {stderr_buf.getvalue()!r}"
        )
    else:
        stderr_buf = io.StringIO()
        stdout_buf = io.StringIO()
        with contextlib.redirect_stderr(stderr_buf), contextlib.redirect_stdout(stdout_buf):
            rc_in = cli.main(argv)
        assert rc_in == expected_exit, (
            f"in-process exit-code-map row (exit={expected_exit}) must "
            f"return {expected_exit}, got {rc_in}; "
            f"stderr={stderr_buf.getvalue()!r}"
        )
        # Row 8 (exit 1) MUST write a stderr message per SPEC §7
        # ``其他內部錯誤 → exit 1 + stderr``.
        if expected_exit == 1:
            assert stderr_buf.getvalue().strip() != "", (
                "in-process exit-1 corruption row must write a stderr "
                "message (SPEC §7 內部錯誤 → exit 1 + stderr)"
            )

    # ---- Subprocess path.
    # Re-seed to undo any in-process mutation so the subprocess sees the
    # same precondition.
    if expected_exit == 0:
        _seed_pending(taskq_home, "abcdef07", "echo hi")
    elif expected_exit == 1:
        tasks_file.write_text("{this is not valid json")
    elif expected_exit == 3:
        # Re-seed 4 pending tasks; trip in-process via a fresh call sequence.
        seed = {}
        for idx in range(4):
            tid = f"abcdef{idx:02x}"
            seed[tid] = {
                "command": "false",
                "name": "",
                "status": "pending",
                "created_at": f"2026-07-18T00:00:{idx:02d}+00:00",
            }
        tasks_file.write_text(json_lib.dumps(seed))
        # Trip in-process so the breaker.json is on disk when the
        # subprocess path probes.
        for idx in range(3):
            cli.main(["run", f"abcdef{idx:02x}"])
    elif expected_exit == 4:
        _seed_pending(taskq_home, "abcdef11", "sleep 5")

    if expected_exit == 3:
        proc = _run_subprocess(
            ["run", "abcdef03"], taskq_home, **env_overrides
        )
    else:
        proc = _run_subprocess(argv, taskq_home, **env_overrides)
    assert proc.returncode == expected_exit, (
        f"subprocess exit-code-map row (exit={expected_exit}) must "
        f"return {expected_exit}, got rc={proc.returncode!r}, "
        f"stderr={proc.stderr!r}"
    )
    if expected_exit == 3:
        assert "breaker open" in proc.stderr, (
            f"subprocess exit-3 row must surface 'breaker open' in stderr, "
            f"got {proc.stderr!r}"
        )
    if expected_exit == 1:
        assert proc.stderr.strip() != "", (
            "subprocess exit-1 corruption row must write a stderr message "
            "(SPEC §7 內部錯誤 → exit 1 + stderr)"
        )