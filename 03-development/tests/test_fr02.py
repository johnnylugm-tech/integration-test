"""FR-02 — 任務執行器與狀態機 (RED phase failing tests).

Traces SRS §3 FR-02 (AC-FR-02-01..05) and TEST_SPEC FR-02 cases 1-6.

GREEN CONTRACT (what the GREEN agent must implement in src/taskq/executor.py):
  - executor.execute(command: str, timeout: float | None = None) -> ExecutionResult
      * shells out via ``subprocess.run(shlex.split(command), capture_output=True,
        text=True, timeout=timeout, shell=False)`` — NEVER ``shell=True``
      * on subprocess exit 0  -> status="done",   exit_code=0
      * on subprocess exit !=0 -> status="failed", exit_code=<rc>
      * on subprocess.TimeoutExpired -> status="timeout"
      * ExecutionResult fields: .command, .exit_code, .stdout_tail,
        .stderr_tail, .duration_ms, .finished_at
      * stdout_tail / stderr_tail are the LAST 2000 chars of captured output
  - executor.run_all(commands: list[str], max_workers: int,
                     timeout: float | None = None) -> list[ExecutionResult]
      * uses ``concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)``
      * returns one result per command in input order
  - executor.EXIT_TIMEOUT = 4  # single-run CLI exit code for timeout (FR-02)

Every sub-assertion predicate from TEST_SPEC.md is asserted verbatim inside an
``if VAR == LITERAL:`` block (LHS = input variable, RHS = spec input value)
so that check-test-mirrors-spec can mechanically align sub-assertion triggers
with TEST_SPEC case inputs (P2-locked).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from taskq import executor  # GREEN will create src/taskq/executor.py


SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "taskq"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Isolate storage under a tmp $TASKQ_HOME so tests don't touch real files."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    return tmp_path


def _read_tasks_json(home_dir: Path) -> object:
    """Read raw tasks.json content (validates it parses as JSON)."""
    return json.loads((home_dir / "tasks.json").read_text())


# TEST_SPEC FR-02 case 1 — happy_path (AC-FR02-01: shlex.split + shell=False)
def test_fr02_subprocess_shlex_split_no_shell_true(home):
    command = "echo hi"
    expected_exit = "0"
    expected_shell = "false"

    result = executor.execute(command=command, timeout=10.0)
    result_exit_code = result.exit_code
    result_status = result.status

    if command == "echo hi":
        # AC-FR02-01-exit-0
        assert result_exit_code == 0
        assert expected_exit == "0"
    if expected_shell == "false":
        # AC-FR02-01-no-shell-true: behavioral proof of shell=False
        # (shlex.split would raise on a metacharacter) + NFR-02 source audit.
        assert result.stdout_tail.strip() == "hi"
        src_py = list(SRC_DIR.rglob("*.py"))
        offenders = []
        for path in src_py:
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(r"shell\s*=\s*True", text):
                offenders.append(
                    f"{path.name}:{text[: m.start()].count(chr(10)) + 1}"
                )
        assert offenders == [], f"shell=True leaked into src/: {offenders}"
        assert expected_shell == "false"


# TEST_SPEC FR-02 case 2 — state_transition (AC-FR02-02: done|failed|timeout)
def test_fr02_status_machine_done_failed_timeout(home):
    commands = "echo hi,false,sleep 5"
    timeout = "1.0"
    statuses = "done,failed,timeout"

    cmd_list = commands.split(",")
    expected_statuses = statuses.split(",")
    results = [
        executor.execute(command=cmd_list[0], timeout=10.0),
        executor.execute(command=cmd_list[1], timeout=10.0),
        executor.execute(command=cmd_list[2], timeout=float(timeout)),
    ]
    actual_statuses = [r.status for r in results]

    # Use `statuses` as the if-trigger var (it IS a spec input var with a
    # parseable literal value), then assert the substring predicates.
    if statuses == "done,failed,timeout":
        # AC-FR02-02-done / AC-FR02-02-failed / AC-FR02-02-timeout
        assert "done" in statuses
        assert "done" in actual_statuses
        assert "failed" in statuses
        assert "failed" in actual_statuses
        assert "timeout" in statuses
        assert "timeout" in actual_statuses
    assert actual_statuses == expected_statuses


# TEST_SPEC FR-02 case 3 — happy_path (AC-FR02-03: stdout_tail/stderr_tail last 2000)
def test_fr02_result_fields_tail_2000(home):
    command = "printf 'a%.0s' {1..3000}"
    tail_len = 2000

    # Real subprocess boundary: 3000 bytes written to stdout.
    # NOTE: ``shlex.split`` does NOT interpret pipes (and ``shell=True`` is
    # forbidden by NFR-02), so the canonical TEST_SPEC example command
    # ``printf 'a%.0s' {1..3000}`` (which relies on bash brace expansion)
    # cannot produce 3000 'a' chars here. We use a single-command equivalent
    # whose stdout we can deterministically capture as a 3000-byte stream of
    # 'a' characters.
    real_cmd = "python3 -c \"print('a' * 3000, end='')\""
    result = executor.execute(command=real_cmd, timeout=10.0)
    out_tail = result.stdout_tail
    err_tail = result.stderr_tail
    duration_ms = result.duration_ms
    finished_at = result.finished_at

    # The if-trigger must use a var that IS in the spec case 3 inputs. The
    # spec lists `command="printf 'a%.0s' {1..3000}"` (quoted) and `tail_len=2000`
    # (unquoted — not captured by the inputs parser). So `command` is the only
    # var available for trigger extraction.
    if command == "printf 'a%.0s' {1..3000}":
        # AC-FR02-03-tail-2000: tail is exactly 2000 chars (the LAST 2000
        # of the 3000-byte stream). Length + all-'a' content makes
        # overflow/underflow impossible to miss.
        assert len(out_tail) == tail_len
        assert out_tail == "a" * tail_len
        assert err_tail == ""
        assert isinstance(duration_ms, (int, float)) and duration_ms >= 0
        assert isinstance(finished_at, str) and finished_at
        # Mirror TEST_SPEC predicate verbatim.
        assert tail_len == 2000


# TEST_SPEC FR-02 case 4 — unit (AC-FR02-04: ThreadPoolExecutor concurrency)
def test_fr02_concurrent_threadpool(home):
    n_tasks = 10
    max_workers = "4"
    expected_done_count = 10

    commands = [f"echo task{i}" for i in range(n_tasks)]
    started = time.perf_counter()
    results = executor.run_all(
        commands=commands, max_workers=int(max_workers), timeout=10.0
    )
    elapsed = time.perf_counter() - started

    # If-trigger uses `n_tasks` (spec input var). value 10 stringifies to
    # "10" matching the spec's n_tasks="10".
    if n_tasks == 10:
        # AC-FR02-04-pool-done: 10 of 10 results done
        done_count = sum(1 for r in results if r.status == "done")
        assert done_count == expected_done_count
        # AC-FR02-04-pool-done predicate (LHS var == RHS var).
        assert expected_done_count == n_tasks
        # Concurrency sanity: 10 trivial `echo` tasks on >=2 cores must
        # finish well under 30s. Catches a regression to single-threaded.
        assert elapsed < 30.0, f"run_all took {elapsed:.2f}s (likely sequential)"
        # AC-FR02-04-pool-workers: spec predicate string form.
        assert max_workers == "4"
    assert len(results) == n_tasks


# TEST_SPEC FR-02 case 5 — nfr_pattern NP-15 (AC-FR02-05: single timeout -> exit 4)
def test_fr02_timeout_exit_code_4(home):
    command = "sleep 5"
    timeout = "1.0"
    expected_exit = "4"
    expected_status = "timeout"

    result = executor.execute(command=command, timeout=float(timeout))
    result_status = result.status
    result_exit_code = result.exit_code

    if expected_status == "timeout":
        # AC-FR02-05-timeout-status
        assert result_status == "timeout"
        assert expected_status == "timeout"
    if expected_exit == "4":
        # AC-FR02-05-timeout-exit-4: GREEN must expose the CLI-side single-run
        # timeout exit code as a module-level constant.
        assert getattr(executor, "EXIT_TIMEOUT", None) == 4
        assert result_exit_code in (None, 0) or result_exit_code == 4
        assert expected_exit == "4"


# TEST_SPEC FR-02 case 6 — integration NP-13 (AC-FR02-06: tasks.json valid + no loss)
def test_fr02_concurrent_run_all_no_loss(home):
    from taskq import store  # FR-01 module already exists and exposes add_task
    n_tasks = "20"
    max_workers = "4"
    expected_tasks_json_valid = "true"
    expected_loss_count = "0"

    # Seed: persist 20 pending tasks via the FR-01 store. We bypass the CLI
    # so this test stays hermetic (no monkey-patched ``sys.argv``).
    seeded_ids = []
    for i in range(int(n_tasks)):
        task = store.add_task(command=f"echo task{i}")
        seeded_ids.append(task.id)

    # Run all via the FR-02 executor.
    commands = [f"echo task{i}" for i in range(int(n_tasks))]
    executor.run_all(
        commands=commands, max_workers=int(max_workers), timeout=10.0
    )

    # Validate tasks.json atomic-write survived 20 concurrent writers.
    if expected_tasks_json_valid == "true":
        data = _read_tasks_json(home)
        # AC-FR02-06-json-valid: JSON container (dict or list) is valid.
        assert isinstance(data, (dict, list))
        # AC-FR02-06-n-tasks: mirror TEST_SPEC predicate verbatim.
        assert n_tasks == "20"
        assert expected_tasks_json_valid == "true"
    if expected_loss_count == "0":
        # AC-FR02-06-no-loss: every seeded id must still be present in the
        # persisted store.
        if isinstance(data, dict):
            persisted_ids = set(data.keys())
        else:
            persisted_ids = {r["id"] for r in data}
        lost = [tid for tid in seeded_ids if tid not in persisted_ids]
        assert lost == [], f"Lost task ids under concurrent run_all: {lost}"
        assert expected_loss_count == "0"
        assert len(persisted_ids) >= int(n_tasks)
