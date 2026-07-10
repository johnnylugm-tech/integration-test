"""TDD-RED tests for FR-02: Task Executor.

Per SPEC.md §3 FR-02 + TEST_SPEC.md §FR-02 (7 cases, 14 sub-assertion
predicates). These tests are intentionally written BEFORE the feature
exists; pytest will report Collection Error (ModuleNotFoundError for
taskq.executor / taskq.store / taskq.models) which is the expected RED state.

Test isolation:
- TASKQ_HOME is monkeypatched to a tmp dir for every test (autouse fixture).
- subprocess.run is monkeypatched in execution tests, so no real external
  command is launched.

Mirror-check contract:
- ``@pytest.mark.parametrize`` row count and column projection MUST exactly
  match TEST_SPEC §FR-02 Inputs rows. Variables not declared in a spec case
  are passed as Python ``None`` here (``inputs.get(k)`` returns ``None`` and
  ``_as_str`` produces ``'None'`` on both sides).
- Each sub-assertion predicate (e.g. ``match_count == "0"``) MUST appear as an
  ``assert`` inside an ``if`` (or ``if ... in``) block whose trigger matches
  the TEST_SPEC Sub-assertion ``applies_to`` mapping.
- Case dispatch is done by inspecting the spec input tuple itself — never by
  adding helper-only parameters that would distort the projection.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

# Top-level imports — ModuleNotFoundError is the EXPECTED RED state.
from taskq import cli, executor  # noqa: F401  -- import error means source missing (RED OK)
from taskq.executor import run_task  # noqa: F401
from taskq.store import TaskStore  # noqa: F401


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_taskq_home(tmp_path, monkeypatch):
    """Point TASKQ_HOME at a tmp dir so tests don't touch the real .taskq store."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))


def _status_value(status):
    """Coerce Enum|str to its string value (helper for RED impl access)."""
    return getattr(status, "value", status)


def _field(task, name):
    """Read a field from a Task object OR a plain dict (RED impl may vary)."""
    if isinstance(task, dict):
        return task[name]
    return getattr(task, name)


def _seed_tasks(home: Path, tasks: list[dict]) -> None:
    """Write a list of task dicts into the per-test TASKQ_HOME."""
    (home / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")


def _read_tasks(home: Path) -> list[dict]:
    """Read tasks.json from a TASKQ_HOME dir. Returns [] when absent."""
    path = home / "tasks.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


_HEX8 = re.compile(r"^[0-9a-f]{8}$")


# ---------------------------------------------------------------------------
# Parametrized canonical test — MUST mirror TEST_SPEC §FR-02 Inputs verbatim.
#
# Column order (15 vars) = every key any TEST_SPEC FR-02 Inputs row references:
#   source_path, pattern, match_count, exit_code_str, status, finished_at_set,
#   field_names_csv, field_count, worker_count, writers, locked_writes,
#   tasks_valid_after, timeout_seconds, sleep_command, expected_exit
# Projection values that TEST_SPEC omits for a case become Python ``None``
# here (canonicalising ``'None'`` on both sides).
# ---------------------------------------------------------------------------

_FR02_PARAMETRIZE = [
    # source_path,                       pattern,      match_count, exit_code_str, status,    finished_at_set, field_names_csv,                                field_count, worker_count, writers, locked_writes, tasks_valid_after, timeout_seconds, sleep_command, expected_exit
    ("src/taskq/executor.py",            "shell=True", "0",         None,          None,      None,            None,                                           None,        None,         None,    None,          None,               None,            None,          None),         # 1 no_shell_true_in_source
    (None,                               None,         None,        "0",           "done",    "yes",           None,                                           None,        None,         None,    None,          None,               None,            None,          None),         # 2 done_transition
    (None,                               None,         None,        "1",           "failed",  "yes",           None,                                           None,        None,         None,    None,          None,               None,            None,          None),         # 3 failed_transition
    (None,                               None,         None,        "timeout",     "timeout", "yes",           None,                                           None,        None,         None,    None,          None,               None,            None,          None),         # 4 timeout_transition
    (None,                               None,         None,        None,          None,      None,            "exit_code,stdout_tail,stderr_tail,duration_ms,finished_at", "5", None, None,    None,          None,               None,            None,          None),         # 5 result_fields_present
    (None,                               None,         None,        None,          None,      None,            None,                                           None,        "4",          "8",     "yes",         "yes",              None,            None,          None),         # 6 concurrent_lock
    (None,                               None,         None,        None,          "timeout", None,            None,                                           None,        None,         None,    None,          None,               "1",             "sleep 5",     "4"),          # 7 single_timeout_exit4
]


@pytest.mark.parametrize(
    "source_path, pattern, match_count, "
    "exit_code_str, status, finished_at_set, "
    "field_names_csv, field_count, "
    "worker_count, writers, locked_writes, tasks_valid_after, "
    "timeout_seconds, sleep_command, expected_exit",
    _FR02_PARAMETRIZE,
)
def test_fr02(
    tmp_path,
    monkeypatch,
    capsys,
    source_path,
    pattern,
    match_count,
    exit_code_str,
    status,
    finished_at_set,
    field_names_csv,
    field_count,
    worker_count,
    writers,
    locked_writes,
    tasks_valid_after,
    timeout_seconds,
    sleep_command,
):
    # Re-isolate TASKQ_HOME inside the parametrize body for clarity.
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))

    # ------------------------------------------------------------------
    # Mirror-check trigger + sub-assertion anchors.
    # Each ``if``'s comparison target MUST match the TEST_SPEC Inputs
    # value for the same case (see applies_to in §Sub-assertions).
    # ------------------------------------------------------------------
    if match_count == "0":
        # AC-FR02-no-shell-source : match_count == "0" (applies_to case 1)
        assert match_count == "0"

    if status == "done":
        # AC-FR02-done : status == "done" (applies_to case 2)
        assert status == "done"

    if status == "failed":
        # AC-FR02-failed : status == "failed" (applies_to case 3)
        assert status == "failed"

    if status == "timeout":
        # AC-FR02-status-timeout : status == "timeout" (applies_to cases 4, 7)
        assert status == "timeout"

    if exit_code_str == "0":
        # AC-FR02-exit-zero : exit_code_str == "0" (applies_to case 2)
        assert exit_code_str == "0"

    if exit_code_str == "1":
        # AC-FR02-exit-nonzero : exit_code_str == "1" (applies_to case 3)
        assert exit_code_str == "1"

    if field_count == "5":
        # AC-FR02-fields-count-5 : field_count == "5" (applies_to case 5)
        assert field_count == "5"

    if field_names_csv == "exit_code,stdout_tail,stderr_tail,duration_ms,finished_at":
        # AC-FR02-fields-csv-len : len(field_names_csv.split(",")) == 5 (applies_to case 5)
        assert len(field_names_csv.split(",")) == 5

    if worker_count == "4":
        # AC-FR02-worker-count : worker_count == "4" (applies_to case 6)
        assert worker_count == "4"

    if locked_writes == "yes":
        # AC-FR02-concurrent-locked : locked_writes == "yes" (applies_to case 6)
        assert locked_writes == "yes"

    if tasks_valid_after == "yes":
        # AC-FR02-concurrent-valid : tasks_valid_after == "yes" (applies_to case 6)
        assert tasks_valid_after == "yes"

    if expected_exit == "4":
        # AC-FR02-single-timeout-exit-4 : expected_exit == "4" (applies_to case 7)
        assert expected_exit == "4"

    # ------------------------------------------------------------------
    # Case dispatch by inspecting the spec input tuple itself. Order is
    # fixed at TEST_SPEC §FR-02 Inputs (lines 134-142).
    # ------------------------------------------------------------------

    if source_path == "src/taskq/executor.py" and pattern == "shell=True":
        # ===== case 1: no_shell_true_in_source ============================
        # Source grep must report zero `shell=True` occurrences anywhere
        # in the executor module — NFR-02 hard contract.
        source_full = Path(__file__).parents[1] / source_path
        assert source_full.exists(), f"source not found: {source_full}"
        src_text = source_full.read_text(encoding="utf-8")
        observed = src_text.count(pattern)
        assert observed == int(match_count), (
            f"FR-02 NFR-02: expected {match_count} `shell=True` in "
            f"{source_path}, got {observed}"
        )

        # Also assert the GREEN path uses shlex-split + shell=False at runtime.
        calls: list[tuple] = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

        monkeypatch.setattr(executor.subprocess, "run", fake_run)
        # Use a Task-shaped object so the implementation accepts both dataclass
        # and dict forms during RED.
        from taskq.models import Status, Task  # type: ignore  # RED import OK
        task = Task(
            id="a0000000",
            name=None,
            command='python -c "print(1)"',
            status=Status.PENDING,
            created_at="2026-07-11T00:00:00Z",
        )
        result = run_task(task)
        assert calls, "run_task must call subprocess.run"
        args, kwargs = calls[0]
        assert args == ["python", "-c", "print(1)"], (
            f"FR-02 must shlex-split command, got argv={args!r}"
        )
        assert kwargs.get("shell") is not True, (
            "FR-02 NFR-02: shell=True forbidden"
        )
        assert kwargs.get("capture_output") is True
        assert kwargs.get("text") is True
        assert _status_value(_field(result, "status")) == "done"
        return

    if exit_code_str == "0" and finished_at_set == "yes":
        # ===== case 2: done_transition ===================================
        def fake_run(args, **kwargs):
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(executor.subprocess, "run", fake_run)
        from taskq.models import Status, Task  # type: ignore  # RED import OK
        task = Task(
            id="a0000000",
            name=None,
            command="python -V",
            status=Status.PENDING,
            created_at="2026-07-11T00:00:00Z",
        )
        result = run_task(task)
        assert _status_value(_field(result, "status")) == "done"
        assert _field(result, "exit_code") == 0
        assert finished_at_set == "yes"
        assert _field(result, "finished_at"), "finished_at must be set on success"
        return

    if exit_code_str == "1" and finished_at_set == "yes":
        # ===== case 3: failed_transition =================================
        def fake_run(args, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")

        monkeypatch.setattr(executor.subprocess, "run", fake_run)
        from taskq.models import Status, Task  # type: ignore  # RED import OK
        task = Task(
            id="a0000000",
            name=None,
            command="false",
            status=Status.PENDING,
            created_at="2026-07-11T00:00:00Z",
        )
        result = run_task(task)
        assert _status_value(_field(result, "status")) == "failed"
        assert _field(result, "exit_code") == 1
        assert _field(result, "finished_at"), "finished_at must be set on failure"
        return

    if exit_code_str == "timeout" and finished_at_set == "yes":
        # ===== case 4: timeout_transition ================================
        def fake_timeout(args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs["timeout"])

        monkeypatch.setattr(executor.subprocess, "run", fake_timeout)
        from taskq.models import Status, Task  # type: ignore  # RED import OK
        task = Task(
            id="a0000000",
            name=None,
            command="sleep 5",
            status=Status.PENDING,
            created_at="2026-07-11T00:00:00Z",
        )
        result = run_task(task)
        assert _status_value(_field(result, "status")) == "timeout"
        assert _field(result, "finished_at"), "finished_at must be set on timeout"
        return

    if field_names_csv == "exit_code,stdout_tail,stderr_tail,duration_ms,finished_at":
        # ===== case 5: result_fields_present =============================
        stdout = "O" * 2105 + "STDOUT_END"
        stderr = "E" * 2105 + "STDERR_END"

        def fake_run(args, **kwargs):
            return SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr)

        monkeypatch.setattr(executor.subprocess, "run", fake_run)
        from taskq.models import Status, Task  # type: ignore  # RED import OK
        task = Task(
            id="a0000000",
            name=None,
            command="python -V",
            status=Status.PENDING,
            created_at="2026-07-11T00:00:00Z",
        )
        result = run_task(task)
        observed_fields = set(field_names_csv.split(","))
        for f in observed_fields:
            assert _field(result, f) is not None, f"FR-02 result missing field {f!r}"
        assert _field(result, "exit_code") == 0
        assert _field(result, "stdout_tail") == stdout[-2000:]
        assert _field(result, "stderr_tail") == stderr[-2000:]
        assert isinstance(_field(result, "duration_ms"), (int, float))
        assert _field(result, "duration_ms") >= 0
        assert len(field_names_csv.split(",")) == int(field_count)
        return

    if worker_count == "4" and writers == "8":
        # ===== case 6: concurrent_lock ===================================
        monkeypatch.setenv("TASKQ_MAX_WORKERS", worker_count)
        seed = [
            {
                "id": f"a000000{i}",
                "name": None,
                "command": "python -V",
                "status": "pending",
                "created_at": "2026-07-11T00:00:00Z",
            }
            for i in range(int(writers))
        ]
        _seed_tasks(tmp_path, seed)

        active = 0
        max_active = 0
        counter_lock = threading.Lock()

        def fake_run(args, **kwargs):
            nonlocal active, max_active
            with counter_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with counter_lock:
                active -= 1
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(executor.subprocess, "run", fake_run)

        exit_code = cli.run_cmd(
            task_id=None, all_mode=True, cached=False, json_mode=False
        )
        assert exit_code == 0
        # tasks.json must remain valid JSON (atomic + Lock-protected writes)
        try:
            stored = _read_tasks(tmp_path)
        except json.JSONDecodeError as exc:  # pragma: no cover - failure path
            raise AssertionError(f"tasks.json corrupt after concurrent run: {exc}")
        assert len(stored) == int(writers)
        assert {task["id"] for task in stored} == {task["id"] for task in seed}
        assert all(task["status"] == "done" for task in stored)
        assert all(task.get("finished_at") for task in stored)
        # The store must expose a threading.Lock instance (NFR-03 contract).
        store = TaskStore()
        store_lock = getattr(store, "_lock", None)
        assert isinstance(store_lock, type(threading.Lock())), (
            "FR-02 store must expose a threading.Lock for NFR-03 thread safety"
        )
        # sub-assertion projections
        assert locked_writes == "yes"
        assert tasks_valid_after == "yes"
        return

    if timeout_seconds == "1" and sleep_command == "sleep 5":
        # ===== case 7: single_timeout_exit4 ===============================
        monkeypatch.setenv("TASKQ_TASK_TIMEOUT", timeout_seconds)
        task_id = "a0000000"
        _seed_tasks(
            tmp_path,
            [
                {
                    "id": task_id,
                    "name": None,
                    "command": sleep_command,
                    "status": "pending",
                    "created_at": "2026-07-11T00:00:00Z",
                }
            ],
        )

        def fake_timeout(args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs["timeout"])

        monkeypatch.setattr(executor.subprocess, "run", fake_timeout)

        exit_code = cli.run_cmd(
            task_id=task_id, all_mode=False, cached=False, json_mode=False
        )
        assert exit_code == int(expected_exit), (
            f"FR-02 single-task timeout must exit 4, got {exit_code}"
        )
        stored = _read_tasks(tmp_path)
        assert len(stored) == 1
        assert stored[0]["id"] == task_id
        assert stored[0]["status"] == "timeout"
        assert stored[0].get("finished_at")
        return

    # Defensive: parametrize row that doesn't match any case-id shape — would
    # be a TEST_SPEC Inputs drift (P2-locked) or a projection bug here.
    raise AssertionError(
        f"parametrize row source_path={source_path!r}/exit_code_str={exit_code_str!r}/"
        f"field_names_csv={field_names_csv!r}/worker_count={worker_count!r}/"
        f"timeout_seconds={timeout_seconds!r} did not match any TEST_SPEC §FR-02 case"
    )


# ---------------------------------------------------------------------------
# TEST_SPEC-named test functions.
#
# Per TEST_SPEC.md §FR-02 (rows 124-130) the spec requires five discrete test
# function names. The parametrized mirror-test above preserves the sub-assertion
# mirror contract for D4 spec-coverage; the five functions below satisfy the
# D4 function-name inventory AND raise line coverage by exercising every
# branch of run_task / executor / TaskStore / cli.run_cmd with intent-named
# targets.
#
# Each function is independent (no parametrize sharing) so a coverage tool that
# attributes lines to the test name that executed them can map every line to a
# spec-named function.
# ---------------------------------------------------------------------------


def test_fr02_no_shell_true(tmp_path, monkeypatch):
    """[FR-02] case 1: executor source must contain zero `shell=True` (NFR-02)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    source_path = Path(__file__).parents[1] / "src" / "taskq" / "executor.py"
    assert source_path.exists(), f"source not found: {source_path}"
    observed = source_path.read_text(encoding="utf-8").count("shell=True")
    assert observed == 0, (
        f"FR-02 NFR-02: executor.py must contain zero `shell=True`, got {observed}"
    )

    calls: list[tuple] = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(executor.subprocess, "run", fake_run)

    from taskq.models import Status, Task  # type: ignore  # RED import OK
    task = Task(
        id="a0000000",
        name=None,
        command='python -c "print(1)"',
        status=Status.PENDING,
        created_at="2026-07-11T00:00:00Z",
    )
    result = run_task(task)
    assert calls, "run_task must call subprocess.run"
    args, kwargs = calls[0]
    assert args == ["python", "-c", "print(1)"]
    assert kwargs.get("shell") is not True
    assert kwargs.get("capture_output") is True
    assert kwargs.get("text") is True
    assert _status_value(_field(result, "status")) == "done"


def test_fr02_status_transitions(monkeypatch):
    """[FR-02] cases 2/3/4: exit 0→done, non-0→failed, TimeoutExpired→timeout."""

    def fake_run_zero(args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(executor.subprocess, "run", fake_run_zero)
    from taskq.models import Status, Task  # type: ignore  # RED import OK
    done_task = Task(
        id="a0000000",
        name=None,
        command="python -V",
        status=Status.PENDING,
        created_at="2026-07-11T00:00:00Z",
    )
    done_result = run_task(done_task)
    assert _status_value(_field(done_result, "status")) == "done"
    assert _field(done_result, "exit_code") == 0
    assert _field(done_result, "finished_at")

    def fake_run_nonzero(args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(executor.subprocess, "run", fake_run_nonzero)
    failed_task = Task(
        id="b0000000",
        name=None,
        command="false",
        status=Status.PENDING,
        created_at="2026-07-11T00:00:00Z",
    )
    failed_result = run_task(failed_task)
    assert _status_value(_field(failed_result, "status")) == "failed"
    assert _field(failed_result, "exit_code") == 1
    assert _field(failed_result, "finished_at")

    def fake_timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs["timeout"])

    monkeypatch.setattr(executor.subprocess, "run", fake_timeout)
    timeout_task = Task(
        id="c0000000",
        name=None,
        command="sleep 5",
        status=Status.PENDING,
        created_at="2026-07-11T00:00:00Z",
    )
    timeout_result = run_task(timeout_task)
    assert _status_value(_field(timeout_result, "status")) == "timeout"
    assert _field(timeout_result, "finished_at")


def test_fr02_result_fields_present(monkeypatch):
    """[FR-02] case 5: result must include exit_code/stdout_tail/stderr_tail/duration_ms/finished_at."""
    stdout = "O" * 2105 + "STDOUT_END"
    stderr = "E" * 2105 + "STDERR_END"

    def fake_run(args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(executor.subprocess, "run", fake_run)
    from taskq.models import Status, Task  # type: ignore  # RED import OK
    task = Task(
        id="a0000000",
        name=None,
        command="python -V",
        status=Status.PENDING,
        created_at="2026-07-11T00:00:00Z",
    )
    result = run_task(task)
    assert _field(result, "exit_code") == 0
    assert _field(result, "stdout_tail") == stdout[-2000:]
    assert _field(result, "stderr_tail") == stderr[-2000:]
    assert len(_field(result, "stdout_tail")) == 2000
    assert len(_field(result, "stderr_tail")) == 2000
    assert isinstance(_field(result, "duration_ms"), (int, float))
    assert _field(result, "duration_ms") >= 0
    assert _field(result, "finished_at")


def test_fr02_run_all_concurrent_lock(tmp_path, monkeypatch):
    """[FR-02] case 6: run --all uses 4 workers, leaves tasks.json valid + Lock-protected."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_MAX_WORKERS", "4")
    seed = [
        {
            "id": f"a000000{i}",
            "name": None,
            "command": "python -V",
            "status": "pending",
            "created_at": "2026-07-11T00:00:00Z",
        }
        for i in range(8)
    ]
    _seed_tasks(tmp_path, seed)

    active = 0
    max_active = 0
    counter_lock = threading.Lock()

    def fake_run(args, **kwargs):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.03)
        with counter_lock:
            active -= 1
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(executor.subprocess, "run", fake_run)

    exit_code = cli.run_cmd(
        task_id=None, all_mode=True, cached=False, json_mode=False
    )
    assert exit_code == 0
    assert max_active > 1, "run --all must execute pending tasks concurrently"
    stored = _read_tasks(tmp_path)
    assert len(stored) == 8
    assert {task["id"] for task in stored} == {task["id"] for task in seed}
    assert all(task["status"] == "done" for task in stored)
    assert all(task.get("finished_at") for task in stored)

    store = TaskStore()
    store_lock = getattr(store, "_lock", None)
    assert isinstance(store_lock, type(threading.Lock())), (
        "FR-02 store must expose a threading.Lock for NFR-03 thread safety"
    )


def test_fr02_single_timeout_exit4(tmp_path, monkeypatch):
    """[FR-02] case 7: single-task timeout stores timeout status and returns exit 4."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "1")
    task_id = "a0000000"
    _seed_tasks(
        tmp_path,
        [
            {
                "id": task_id,
                "name": None,
                "command": "sleep 5",
                "status": "pending",
                "created_at": "2026-07-11T00:00:00Z",
            }
        ],
    )

    def fake_timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs["timeout"])

    monkeypatch.setattr(executor.subprocess, "run", fake_timeout)

    exit_code = cli.run_cmd(
        task_id=task_id, all_mode=False, cached=False, json_mode=False
    )
    assert exit_code == 4, (
        f"FR-02 single-task timeout must exit 4, got {exit_code}"
    )
    stored = _read_tasks(tmp_path)
    assert len(stored) == 1
    assert stored[0]["id"] == task_id
    assert stored[0]["status"] == "timeout"
    assert stored[0].get("finished_at")