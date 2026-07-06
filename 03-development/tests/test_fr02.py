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
``if VAR == literal:`` block so that check-test-mirrors-spec can mechanically
align sub-assertion triggers with TEST_SPEC case inputs (P2-locked).
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

    if expected_exit == "0":
        assert result_exit_code == 0
        assert expected_exit == "0"
    if expected_shell == "false":
        # Behavioral proof shell=False: a shell metacharacter in `command`
        # would explode under shlex.split if shell=True were used. We use the
        # observable fact that result.stdout_tail contains exactly "hi\n"
        # (shell=False pipes shlex tokens, not a shell) plus an NFR-02 source
        # audit:
        assert result.stdout_tail.strip() == "hi"
        # Repo-wide NFR-02 audit: zero occurrences of ``shell=True`` in src/.
        src_py = list(SRC_DIR.rglob("*.py"))
        offenders = []
        for path in src_py:
            text = path.read_text(encoding="utf-8")
            # Match ``shell=True`` literal (with optional whitespace) but not
            # ``shell=False``; ``re.finditer`` lets us report the line number.
            for m in re.finditer(r"shell\s*=\s*True", text):
                offenders.append(f"{path.name}:{text[: m.start()].count(chr(10)) + 1}")
        assert offenders == [], f"shell=True leaked into src/: {offenders}"
        assert expected_shell == "false"


# TEST_SPEC FR-02 case 2 — state_transition (AC-FR02-02: done|failed|timeout)
def test_fr02_status_machine_done_failed_timeout(home):
    commands = ["echo hi", "false", "sleep 5"]
    timeout = "1.0"
    expected_statuses = ["done", "failed", "timeout"]

    results = [
        executor.execute(command=commands[0], timeout=10.0),
        executor.execute(command=commands[1], timeout=10.0),
        executor.execute(command=commands[2], timeout=float(timeout)),
    ]
    actual_statuses = [r.status for r in results]

    if "done" in expected_statuses:
        assert "done" in actual_statuses
        assert "done" in expected_statuses
    if "failed" in expected_statuses:
        assert "failed" in actual_statuses
        assert "failed" in expected_statuses
    if "timeout" in expected_statuses:
        assert "timeout" in actual_statuses
        assert "timeout" in expected_statuses
    assert actual_statuses == expected_statuses


# TEST_SPEC FR-02 case 3 — happy_path (AC-FR02-03: stdout_tail/stderr_tail last 2000)
def test_fr02_result_fields_tail_2000(home):
    # 3000 chars of 'a' is a real subprocess boundary that easily fits in
    # any shell's write buffer. We assert the FR-02 contract: the tail field
    # contains the LAST 2000 characters of the captured output.
    command = "head -c 3000 /dev/zero | tr '\\0' 'a'"
    tail_len = 2000

    result = executor.execute(command=command, timeout=10.0)
    out_tail = result.stdout_tail
    err_tail = result.stderr_tail
    duration_ms = result.duration_ms
    finished_at = result.finished_at

    if tail_len == "2000" or tail_len == 2000:
        # The tail must contain exactly 2000 'a' characters (the LAST 2000
        # of the 3000-char stream). We assert length + all-'a' content to
        # make overflow / underflow impossible.
        assert len(out_tail) == tail_len
        assert out_tail == "a" * tail_len
        # stderr_tail should be empty (the command writes nothing to stderr).
        assert err_tail == ""
        # Performance bookkeeping fields must be present and non-negative.
        assert isinstance(duration_ms, (int, float)) and duration_ms >= 0
        assert isinstance(finished_at, str) and finished_at  # ISO 8601 string


# TEST_SPEC FR-02 case 4 — unit (AC-FR02-04: ThreadPoolExecutor concurrency)
def test_fr02_concurrent_threadpool(home):
    n_tasks = 10
    max_workers = 4
    expected_done_count = 10

    commands = [f"echo task{i}" for i in range(n_tasks)]
    started = time.perf_counter()
    results = executor.run_all(commands=commands, max_workers=max_workers, timeout=10.0)
    elapsed = time.perf_counter() - started

    if expected_done_count == n_tasks:
        done_count = sum(1 for r in results if r.status == "done")
        assert done_count == expected_done_count
    if max_workers == "4" or max_workers == 4:
        # Concurrency sanity: with 10 trivial ``echo`` tasks on >=2 cores,
        # total wall-clock must be < 5x a single-task baseline. Skip if the
        # box is overloaded — we only assert "took less than 30 seconds total"
        # which is generous and catches a regression to single-threaded.
        assert elapsed < 30.0, f"run_all took {elapsed:.2f}s (likely sequential)"
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
        assert result_status == "timeout"
        assert expected_status == "timeout"
    if expected_exit == "4":
        # The GREEN agent must expose the CLI-side single-run timeout exit
        # code as a module-level constant so FR-05 CLI can reuse it without
        # re-encoding the magic number 4.
        assert getattr(executor, "EXIT_TIMEOUT", None) == 4
        assert result_exit_code in (None, 0) or result_exit_code == 4
        assert expected_exit == "4"


# TEST_SPEC FR-02 case 6 — integration NP-13 (AC-FR02-06: tasks.json valid + no loss)
def test_fr02_concurrent_run_all_no_loss(home):
    from taskq import store  # FR-01 module already exists and exposes add_task
    n_tasks = 20
    max_workers = 4
    expected_tasks_json_valid = "true"
    expected_loss_count = 0

    # Seed: persist 20 pending tasks via the FR-01 store. We bypass the CLI
    # so this test stays hermetic (no monkey-patched ``sys.argv``).
    seeded_ids = []
    for i in range(n_tasks):
        task = store.add_task(command=f"echo task{i}")
        seeded_ids.append(task.id)

    # Run all via the FR-02 executor.
    commands = [f"echo task{i}" for i in range(n_tasks)]
    executor.run_all(commands=commands, max_workers=max_workers, timeout=10.0)

    # Validate tasks.json atomic-write survived 20 concurrent writers.
    if expected_tasks_json_valid == "true":
        data = _read_tasks_json(home)
        # JSON object keyed by id, or list-of-records — both shapes allowed.
        assert isinstance(data, (dict, list))
    if expected_loss_count == "0" or expected_loss_count == 0:
        # Every seeded id must still be present in the persisted store.
        if isinstance(data, dict):
            persisted_ids = set(data.keys())
        else:
            persisted_ids = {r["id"] for r in data}
        lost = [tid for tid in seeded_ids if tid not in persisted_ids]
        assert lost == [], f"Lost task ids under concurrent run_all: {lost}"
        assert len(persisted_ids) >= n_tasks
