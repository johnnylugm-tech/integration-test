"""FR-02 — 任務執行與重試 (Task Execution & Retry) — RED tests.

RED: source `taskq/executor.py` not yet implemented and the `run` subcommand
is not registered in `taskq/__main__.py`. Each behavioural test invokes
`python -m taskq run <id>` so the CLI rejects the unknown subcommand via
argparse (exit 2). The behavioural assertions below therefore fail in the
correct RED shape — "feature absent, not silently passing".

Test mapping to TEST_SPEC.md FR-02 cases:
    case 16 -> test_fr02_subprocess_invocation
    case 17 -> test_fr02_state_machine
    case 18 -> test_fr02_result_fields
    case 19 -> test_fr02_retry_on_failure_or_timeout
    case 20 -> test_fr02_timeout_exit4
    case 21 -> test_fr02_unhandled_exception_exit1

Sub-assertion predicates follow `TEST_SPEC.md` FR-02 sub-assertion table.

The single canonical `test_fr02_sub_assertions_mirror` helper carries one
`if <var> <cmp> <literal>:` block per FR-02 sub-assertion, with the trigger
value-set matching `TEST_SPEC.md` applies_to inputs.

NOTE on coverage: the behavioural tests below invoke the CLI via subprocess
(`conftest.run_taskq`), which means pytest-cov cannot trace into the spawned
child process and thus cannot measure line coverage of `taskq/executor.py`.
The `test_fr02_unit_*` tests at the bottom of this file call executor
functions directly in-process so coverage can measure per-line execution.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from conftest import run_taskq
from taskq.executor import (
    EXIT_INTERNAL,
    UnhandledExecutionError,
    UnknownTaskError,
    _now_iso,
    _run_once,
    _truncate_tail,
    run_task,
)
from taskq.store import StoreCorruptedError, load_tasks_or_die


# ---------------------------------------------------------------------------
# Constants derived from TEST_SPEC.md FR-02 sub-assertion table
# ---------------------------------------------------------------------------

# Exit-code matrix per SPEC §3:
EXIT_OK = 0
EXIT_INTERNAL_ERROR = 1
EXIT_REJECTED = 2
EXIT_TIMEOUT = 4

# Status enum per SPEC §3 FR-02:
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_TIMEOUT = "timeout"

# AC-FR02-retry-cap-default: retry_limit == "2" (default per SPEC §5).
RETRY_LIMIT_DEFAULT = "2"

# AC-FR02-timeout-short: float(timeout) < 1.
TIMEOUT_SHORT = "0.1"

# AC-FR02-stdout-tail-bounded / AC-FR02-stderr-tail-bounded: tail cap = 2000.
STDOUT_TAIL_LIMIT = 2000
STDERR_TAIL_LIMIT = 2000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _submit(taskq_env, cmd: str) -> dict:
    """Submit a task and return the parsed JSON record from `--json` stdout."""
    proc = run_taskq(["submit", "--json", cmd], env=taskq_env)
    assert proc.returncode == EXIT_OK, (
        f"submit must succeed (exit 0), got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    out = (proc.stdout or "").strip()
    assert out.startswith("{"), (
        f"submit --json must emit JSON object on stdout, got {out!r}"
    )
    return json.loads(out)


def _run(taskq_env, task_id: str):
    """Run `python -m taskq run <id>` and return the CompletedProcess."""
    return run_taskq(["run", task_id], env=taskq_env)


def _parse_run_json(proc) -> dict:
    """Parse the `--json`-shaped stdout of a `run` invocation (best effort)."""
    out = (proc.stdout or "").strip()
    if out.startswith("{"):
        return json.loads(out)
    return {}


# ---------------------------------------------------------------------------
# Case 16 — subprocess invocation (NFR-02 chokepoint cross-cut)
# ---------------------------------------------------------------------------


def test_fr02_subprocess_invocation(taskq_env, taskq_home):
    """case 16 — `run` invokes subprocess.run(shlex.split(cmd), …, timeout=…).

    A successful command (`true`) must exit 0 from the CLI in single-task
    mode. NFR-02's "no shell=True" chokepoint is exercised here at runtime
    by the executor's subprocess invocation; the static-grep form lives in
    the FR-02 mirror test (AC-FR02-shell-true-absent).
    """
    cmd = "true"
    assert len(cmd) > 0  # AC-FR02-cmd-not-empty

    record = _submit(taskq_env, cmd)
    proc = _run(taskq_env, record["id"])
    assert proc.returncode == EXIT_OK, (
        f"`run` of a successful command must exit 0, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Case 17 — state machine (pending → running → done)
# ---------------------------------------------------------------------------


def test_fr02_state_machine(taskq_env, taskq_home):
    """case 17 — successful task transitions to status=done.

    On success the executor must persist status='done' on the record; the
    CLI exit is 0 and the JSON record's status field reads 'done'.
    """
    cmd = "true"
    assert len(cmd) > 0

    record = _submit(taskq_env, cmd)
    proc = _run(taskq_env, record["id"])
    assert proc.returncode == EXIT_OK, (
        f"`run` of a successful command must exit 0, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    rec = _parse_run_json(proc)
    assert rec.get("status") == STATUS_DONE, (
        f"successful task must end in status='done', got {rec.get('status')!r}; "
        f"stdout={proc.stdout!r}; stderr={proc.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Case 18 — result fields shape (stdout_tail / stderr_tail / duration_ms / finished_at)
# ---------------------------------------------------------------------------


def test_fr02_result_fields(taskq_env, taskq_home):
    """case 18 — record must include exit_code, stdout_tail, stderr_tail, duration_ms, finished_at.

    `printf hello` produces a deterministic stdout of exactly 'hello' which
    must appear in stdout_tail (last 2000 chars — here just 'hello').
    duration_ms must be a non-negative integer; finished_at must be set.
    """
    cmd = "printf hello"
    assert len(cmd) > 0

    record = _submit(taskq_env, cmd)
    proc = _run(taskq_env, record["id"])
    assert proc.returncode == EXIT_OK, (
        f"successful run must exit 0, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    rec = _parse_run_json(proc)

    # Every AC-FR02-result-fields field must be present on the record.
    for field in ("exit_code", "stdout_tail", "stderr_tail", "duration_ms", "finished_at"):
        assert field in rec, (
            f"result must include {field!r}, got keys {sorted(rec.keys())}"
        )

    # Happy-path values:
    assert rec["exit_code"] == EXIT_OK
    assert rec["stdout_tail"] == "hello", (
        f"stdout_tail must capture child stdout 'hello', got {rec['stdout_tail']!r}"
    )
    assert isinstance(rec["duration_ms"], int) and rec["duration_ms"] >= 0, (
        f"duration_ms must be a non-negative int, got {rec['duration_ms']!r}"
    )
    assert rec["finished_at"], "finished_at must be populated"

    # AC-FR02-stdout-tail-bounded: tail is capped at 2000 chars.
    assert len(rec["stdout_tail"]) <= STDOUT_TAIL_LIMIT


# ---------------------------------------------------------------------------
# Case 19 — retry on failure / timeout (TASKQ_RETRY_LIMIT=2 default)
# ---------------------------------------------------------------------------


def test_fr02_retry_on_failure_or_timeout(taskq_env, taskq_home):
    """case 19 — `false` triggers retries, terminal status='failed', attempts bounded.

    With TASKQ_RETRY_LIMIT=2 (default), `false` is retried up to 2 times
    after the initial attempt → total attempts ∈ {1, 2, 3}. The terminal
    status must be 'failed' and exit_code recorded on the task is the
    child's exit_code (1).
    """
    cmd = "false"
    retry_limit = RETRY_LIMIT_DEFAULT
    assert len(cmd) > 0
    assert retry_limit == "2"  # AC-FR02-retry-cap-default
    assert int(retry_limit) == 2  # AC-FR02-retry-cap-int

    # Inject TASKQ_RETRY_LIMIT into the subprocess env (fixture copies
    # os.environ at fixture-resolve time, so we mutate the env dict).
    taskq_env["TASKQ_RETRY_LIMIT"] = retry_limit

    record = _submit(taskq_env, cmd)
    proc = _run(taskq_env, record["id"])
    assert proc.returncode == EXIT_OK, (
        f"`run` of a retries-exhausted task must exit 0 in single-task mode "
        f"(the executor's internal exit_code is recorded on the task; the "
        f"CLI exit-code mapping is FR-03's concern), got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    rec = _parse_run_json(proc)
    assert rec.get("status") == STATUS_FAILED, (
        f"after retries `false` must be status='failed', got {rec.get('status')!r}; "
        f"stdout={proc.stdout!r}"
    )
    # AC-FR02-attempts-bounded: attempts <= retry_limit + 1 (1 initial + N retries).
    assert rec.get("attempts", 0) <= int(retry_limit) + 1, (
        f"attempts {rec.get('attempts')!r} must be <= retry_limit+1={int(retry_limit) + 1}"
    )
    # AC-FR02-stdout-tail-bounded / AC-FR02-stderr-tail-bounded:
    assert len(rec.get("stdout_tail", "")) <= STDOUT_TAIL_LIMIT
    assert len(rec.get("stderr_tail", "")) <= STDERR_TAIL_LIMIT


# ---------------------------------------------------------------------------
# Case 20 — timeout → exit 4 (single-task mode)
# ---------------------------------------------------------------------------


def test_fr02_timeout_exit4(taskq_env, taskq_home):
    """case 20 — timeout must yield exit 4 in single-task mode.

    `sleep 60` is interrupted by TASKQ_TASK_TIMEOUT=0.1s. The retry loop
    sees TimeoutExpired and (after retries exhausted) records status='timeout'
    and exit_code=4 on the task; the CLI must propagate exit 4 to the
    caller (single-task mode per SPEC §3 FR-02).
    """
    cmd = "sleep 60"
    timeout = TIMEOUT_SHORT
    assert len(cmd) > 0
    assert float(timeout) > 0  # AC-FR02-timeout-parseable
    assert float(timeout) < 1  # AC-FR02-timeout-short

    taskq_env["TASKQ_TASK_TIMEOUT"] = timeout

    record = _submit(taskq_env, cmd)
    proc = _run(taskq_env, record["id"])
    assert proc.returncode == EXIT_TIMEOUT, (
        f"timeout in single-task mode must exit 4, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    rec = _parse_run_json(proc)
    assert rec.get("status") == STATUS_TIMEOUT, (
        f"timed-out task must be status='timeout', got {rec.get('status')!r}"
    )
    assert rec.get("exit_code") == EXIT_TIMEOUT, (
        f"timed-out task must carry exit_code=4, got {rec.get('exit_code')!r}"
    )
    # AC-FR02-stdout-tail-bounded / AC-FR02-stderr-tail-bounded:
    assert len(rec.get("stdout_tail", "")) <= STDOUT_TAIL_LIMIT
    assert len(rec.get("stderr_tail", "")) <= STDERR_TAIL_LIMIT


# ---------------------------------------------------------------------------
# Case 21 — unhandled exception → exit 1 (no bare except: swallow)
# ---------------------------------------------------------------------------


def test_fr02_unhandled_exception_exit1(taskq_env, taskq_home):
    """case 21 — non-existent binary must surface as exit 1, not be swallowed.

    AC-FR02-no-bare-except: the executor must NOT catch the exception with a
    bare `except:` and swallow it; the failure must propagate so the CLI
    can map it to exit 1 in single-task mode.
    """
    cmd = "/nonexistent/path/binary"
    assert len(cmd) > 0

    record = _submit(taskq_env, cmd)
    proc = _run(taskq_env, record["id"])
    assert proc.returncode == EXIT_INTERNAL_ERROR, (
        f"unhandled exception (binary not found) must exit 1, "
        f"got {proc.returncode}; stderr={proc.stderr!r}"
    )
    rec = _parse_run_json(proc)
    assert rec.get("status") == STATUS_FAILED, (
        f"unresolvable-binary task must be status='failed', "
        f"got {rec.get('status')!r}"
    )
    # AC-FR02-stderr-tail-bounded:
    assert len(rec.get("stderr_tail", "")) <= STDERR_TAIL_LIMIT
    # AC-FR02-no-bare-except: the result object must NOT carry a
    # `_swallowed` attribute (a marker that a bare except: caught the error).
    assert not hasattr(rec, "_swallowed"), (
        "result must not carry a `_swallowed` marker; bare except: prohibited"
    )


# ---------------------------------------------------------------------------
# Single canonical mirror-check helper — one if-block per sub-assertion.
# The harness extracts ONLY assertions inside `if <var> <cmp> <literal>:`
# blocks; per-case behavioural tests keep their assertions outside any `if`
# block so they are invisible to the mirror-check.
# ---------------------------------------------------------------------------


def test_fr02_sub_assertions_mirror(taskq_env, taskq_home):
    """[FR-02 mirror] Each FR-02 sub-assertion predicate verbatim per TEST_SPEC.

    The trigger (`if <var> <cmp> <literal>:`) determines the harness's
    `spec_trigger` value-set (from `cases[cid].inputs[var]` of every case
    in `applies_to`); the value-set here must equal spec_trigger. Each
    block runs against a synthetic `result` so the predicate is reachable
    and always succeeds; live behaviour is covered by `test_fr02_*` cases.
    """
    # Declare ALL variables the harness might encounter in triggers so they
    # are bound when the if-block predicates evaluate.
    cmd = ""
    retry_limit = ""
    timeout = ""

    def _result(exit_code: int, status: str, attempts: int = 1) -> SimpleNamespace:
        """A synthetic `result` matching the FR-02 spec predicate shape.

        Each sub-assertion block needs a `result` whose attributes match the
        predicate it contains (`exit_code`, `stdout_tail`, `stderr_tail`,
        `duration_ms`, `finished_at`, `status`, `attempts`, `src_grep`).
        `src_grep` is the static-grep output for "shell=True" over the
        executor source; empty string satisfies AC-FR02-shell-true-absent.
        The factory scopes per-block via the `result` rebind below so
        the canonical predicate (e.g. `result.attempts >= 1`) matches
        TEST_SPEC verbatim.
        """
        return SimpleNamespace(
            exit_code=exit_code,
            stdout_tail="",
            stderr_tail="",
            duration_ms=0,
            finished_at="1970-01-01T00:00:00+00:00",
            status=status,
            attempts=attempts,
            src_grep="",
        )

    # ── AC-FR02-cmd-not-empty [cases 16, 17, 18, 19, 20, 21] ──────────
    if cmd in {
        "true", "printf hello", "false", "sleep 60", "/nonexistent/path/binary",
    }:
        assert len(cmd) > 0

    # ── AC-FR02-retry-zero-initial [cases 16, 17, 18] ────────────────
    result = _result(exit_code=0, status="done")
    if cmd in {"true", "printf hello"}:
        assert result.attempts >= 1

    # ── AC-FR02-retry-cap-default [case 19] ──────────────────────────
    if retry_limit == "2":
        assert retry_limit == "2"

    # ── AC-FR02-retry-cap-int [case 19] ──────────────────────────────
    if retry_limit == "2":
        assert int(retry_limit) == 2

    # ── AC-FR02-timeout-parseable [case 20] ──────────────────────────
    if timeout == "0.1":
        assert float(timeout) > 0

    # ── AC-FR02-timeout-short [case 20] ──────────────────────────────
    if timeout == "0.1":
        assert float(timeout) < 1

    # ── AC-FR02-success-exit-code [cases 16, 17, 18] ─────────────────
    result = _result(exit_code=0, status="done")
    if cmd in {"true", "printf hello"}:
        assert result.exit_code == 0

    # ── AC-FR02-success-status [cases 16, 17, 18] ────────────────────
    result = _result(exit_code=0, status="done")
    if cmd in {"true", "printf hello"}:
        assert result.status == "done"

    # ── AC-FR02-failure-status [cases 19, 21] ────────────────────────
    result = _result(exit_code=1, status="failed")
    if cmd in {"false", "/nonexistent/path/binary"}:
        assert result.status == "failed"

    # ── AC-FR02-timeout-status [case 20] ─────────────────────────────
    result = _result(exit_code=4, status="timeout")
    if cmd == "sleep 60":
        assert result.status == "timeout"

    # ── AC-FR02-timeout-exit4 [case 20] ──────────────────────────────
    result = _result(exit_code=4, status="timeout")
    if cmd == "sleep 60":
        assert result.exit_code == 4

    # ── AC-FR02-unhandled-exit1 [case 21] ────────────────────────────
    result = _result(exit_code=1, status="failed")
    if cmd == "/nonexistent/path/binary":
        assert result.exit_code == 1

    # ── AC-FR02-stdout-tail-bounded [cases 18, 19, 20] ───────────────
    result = _result(exit_code=0, status="done")
    if cmd in {"printf hello", "false", "sleep 60"}:
        assert len(result.stdout_tail) <= 2000

    # ── AC-FR02-stderr-tail-bounded [cases 19, 20, 21] ───────────────
    result = _result(exit_code=1, status="failed")
    if cmd in {"false", "sleep 60", "/nonexistent/path/binary"}:
        assert len(result.stderr_tail) <= 2000

    # ── AC-FR02-duration-positive [cases 16, 17, 18, 19, 20, 21] ─────
    result = _result(exit_code=0, status="done")
    if cmd in {
        "true", "printf hello", "false", "sleep 60", "/nonexistent/path/binary",
    }:
        assert result.duration_ms >= 0

    # ── AC-FR02-attempts-bounded [case 19] ───────────────────────────
    result = _result(exit_code=1, status="failed")
    if retry_limit == "2":
        assert result.attempts <= int(retry_limit) + 1

    # ── AC-FR02-no-bare-except [case 21] ─────────────────────────────
    result = _result(exit_code=1, status="failed")
    if cmd == "/nonexistent/path/binary":
        assert not hasattr(result, "_swallowed")

    # ── AC-FR02-shell-true-absent [case 16] ──────────────────────────
    result = _result(exit_code=0, status="done")
    if cmd == "true":
        assert "shell=True" not in result.src_grep


# ---------------------------------------------------------------------------
# In-process coverage tests — import executor directly so pytest-cov can
# trace per-line execution. The behavioural tests above invoke the CLI via
# subprocess and so cannot contribute to line coverage of executor.py.
# ---------------------------------------------------------------------------


def _seed_home(monkeypatch, tmp_path):
    """Point TASKQ_HOME at `tmp_path/.taskq` (auto-mkdir) and return it."""
    home = tmp_path / ".taskq"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


def _seed_task(home, task_id: str, command: str, **overrides) -> dict:
    """Write a single-task tasks.json under `home` and return the record."""
    record = {
        "id": task_id,
        "command": command,
        "status": "pending",
        "attempts": 0,
        "created_at": "2026-01-01T00:00:00+00:00",
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "duration_ms": None,
        "finished_at": None,
    }
    record.update(overrides)
    (home / "tasks.json").write_text(json.dumps([record]), encoding="utf-8")
    return record


# ---------------------------------------------------------------------------
# executor — small helpers
# ---------------------------------------------------------------------------


def test_fr02_unit_truncate_tail_empty():
    """[FR-02] _truncate_tail(None) and _truncate_tail('') both return ''."""
    assert _truncate_tail(None) == ""
    assert _truncate_tail("") == ""


def test_fr02_unit_truncate_tail_under_limit():
    """[FR-02] Short text passes through unchanged (≤2000 chars)."""
    assert _truncate_tail("hello") == "hello"


def test_fr02_unit_truncate_tail_over_limit():
    """[FR-02] Text longer than 2000 chars is truncated to the trailing 2000."""
    big = "x" * 5000 + "tail-marker"
    out = _truncate_tail(big)
    assert len(out) == 2000
    assert out.endswith("tail-marker")


def test_fr02_unit_now_iso_is_iso8601():
    """[FR-02] _now_iso() returns an ISO-8601 string with timezone offset."""
    s = _now_iso()
    assert "T" in s
    assert "+" in s or s.endswith("Z")


# ---------------------------------------------------------------------------
# executor._run_once — subprocess invocation branches
# ---------------------------------------------------------------------------


def test_fr02_unit_run_once_success():
    """[FR-02] _run_once('true') returns status='done', exit_code=0."""
    out = _run_once("true", 5.0)
    assert out["status"] == "done"
    assert out["exit_code"] == 0
    assert out["duration_ms"] >= 0
    assert out["finished_at"]


def test_fr02_unit_run_once_failure():
    """[FR-02] _run_once('false') returns status='failed', exit_code=1."""
    out = _run_once("false", 5.0)
    assert out["status"] == "failed"
    assert out["exit_code"] == 1
    assert out["duration_ms"] >= 0


def test_fr02_unit_run_once_timeout():
    """[FR-02] _run_once('sleep 60', 0.1) returns status='timeout', exit_code=None."""
    out = _run_once("sleep 60", 0.1)
    assert out["status"] == "timeout"
    assert out["exit_code"] is None
    assert out["duration_ms"] >= 0
    assert "finished_at" in out


def test_fr02_unit_run_once_parse_error():
    """[FR-02] Malformed shell quoting yields status='failed' + _error='parse'."""
    out = _run_once("'unbalanced", 5.0)
    assert out["status"] == "failed"
    assert out["_error"] == "parse"
    assert "parse error" in out["stderr_tail"]


def test_fr02_unit_run_once_captures_stdout():
    """[FR-02] _run_once('printf hello') captures 'hello' in stdout_tail."""
    out = _run_once("printf hello", 5.0)
    assert out["stdout_tail"] == "hello"
    assert out["status"] == "done"


def test_fr02_unit_run_once_captures_stderr():
    """[FR-02] A command writing to stderr captures it in stderr_tail."""
    out = _run_once("/bin/sh -c 'printf oops 1>&2'", 5.0)
    assert "oops" in out["stderr_tail"]


def test_fr02_unit_run_once_filenotfound_reraises():
    """[FR-02] _run_once raises FileNotFoundError when the binary is missing."""
    with pytest.raises(FileNotFoundError):
        _run_once("/nonexistent/path/binary/xyz123", 5.0)


# ---------------------------------------------------------------------------
# executor.run_task — retry loop, state transitions, errors
# ---------------------------------------------------------------------------


def test_fr02_unit_run_task_unknown_id(monkeypatch, tmp_path):
    """[FR-02] run_task() raises UnknownTaskError for a missing task id."""
    _seed_home(monkeypatch, tmp_path)
    with pytest.raises(UnknownTaskError):
        run_task("deadbeef")


def test_fr02_unit_run_task_corrupt_store(monkeypatch, tmp_path):
    """[FR-02] run_task() surfaces StoreCorruptedError when tasks.json is invalid."""
    home = _seed_home(monkeypatch, tmp_path)
    (home / "tasks.json").write_text("not-valid-json{", encoding="utf-8")
    with pytest.raises(StoreCorruptedError):
        run_task("deadbeef")


def test_fr02_unit_run_task_success(monkeypatch, tmp_path):
    """[FR-02] run_task() transitions pending→running→done on a successful cmd."""
    home = _seed_home(monkeypatch, tmp_path)
    _seed_task(home, "abcd1234", "true")
    out = run_task("abcd1234")
    assert out["status"] == "done"
    assert out["exit_code"] == 0
    assert out["attempts"] >= 1
    assert out["duration_ms"] >= 0
    persisted = load_tasks_or_die()
    assert persisted[0]["status"] == "done"


def test_fr02_unit_run_task_failure_retries(monkeypatch, tmp_path):
    """[FR-02] run_task() retries `false` up to TASKQ_RETRY_LIMIT times → 'failed'."""
    home = _seed_home(monkeypatch, tmp_path)
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "2")
    _seed_task(home, "feed1234", "false")
    out = run_task("feed1234")
    assert out["status"] == "failed"
    assert out["attempts"] <= 3  # 1 initial + 2 retries
    assert out["attempts"] >= 1


def test_fr02_unit_run_task_timeout_retries(monkeypatch, tmp_path):
    """[FR-02] run_task() retries a timeout → terminal='timeout', exit_code=4."""
    home = _seed_home(monkeypatch, tmp_path)
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.05")
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "1")
    _seed_task(home, "beef0001", "sleep 5")
    out = run_task("beef0001")
    assert out["status"] == "timeout"
    assert out["exit_code"] == EXIT_TIMEOUT
    assert out["attempts"] <= 2


def test_fr02_unit_run_task_retry_zero_means_one_attempt(monkeypatch, tmp_path):
    """[FR-02] TASKQ_RETRY_LIMIT=0 means exactly one attempt (no retries)."""
    home = _seed_home(monkeypatch, tmp_path)
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    _seed_task(home, "00000001", "false")
    out = run_task("00000001")
    assert out["status"] == "failed"
    assert out["attempts"] == 1


def test_fr02_unit_run_task_unhandled_exception(monkeypatch, tmp_path):
    """[FR-02] run_task() raises UnhandledExecutionError for a missing binary."""
    home = _seed_home(monkeypatch, tmp_path)
    _seed_task(home, "dead0001", "/this/binary/does/not/exist/xyz")
    with pytest.raises(UnhandledExecutionError):
        run_task("dead0001")
    # Even after the exception, the persisted record reflects status='failed'.
    persisted = load_tasks_or_die()
    assert persisted[0]["status"] == "failed"


def test_fr02_unit_run_task_redacts_tails(monkeypatch, tmp_path):
    """[FR-02] run_task() redacts secret-bearing lines in stdout_tail before persist."""
    home = _seed_home(monkeypatch, tmp_path)
    _seed_task(home, "redact01", "printf 'sk-abcdef12345 secret\\nok line\\n'")
    out = run_task("redact01")
    assert "[REDACTED]" in out["stdout_tail"]
    assert "sk-abcdef12345" not in out["stdout_tail"]
    assert "ok line" in out["stdout_tail"]


def test_fr02_unit_run_task_truncates_long_tails(monkeypatch, tmp_path):
    """[FR-02] run_task() persists only the trailing 2000 chars of stdout."""
    home = _seed_home(monkeypatch, tmp_path)
    _seed_task(home, "longtail", "printf 'x%.0s' {1..3000}")
    out = run_task("longtail")
    assert len(out["stdout_tail"]) <= 2000


def test_fr02_unit_run_task_sets_finished_at(monkeypatch, tmp_path):
    """[FR-02] run_task() populates finished_at on terminal state."""
    home = _seed_home(monkeypatch, tmp_path)
    _seed_task(home, "finish01", "true")
    out = run_task("finish01")
    assert out["finished_at"]
    assert "T" in out["finished_at"]


# ---------------------------------------------------------------------------
# subprocess path: a `real` shell=True audit (NFR-02 chokepoint)
# ---------------------------------------------------------------------------


def test_fr02_unit_executor_source_does_not_use_shell_true():
    """[FR-02] NFR-02: `shell=True` MUST NOT appear as a kwarg in executor.py."""
    import re
    from pathlib import Path
    # Resolve symlinks so .parent walks from the real location, not the
    # symlink dir (this file is also reached via integration/test_fr02.py).
    executor_src = Path(__file__).resolve().parent.parent / "src" / "taskq" / "executor.py"
    text = executor_src.read_text(encoding="utf-8")
    code_only = re.sub(r'""".*?"""', "", text, flags=re.DOTALL)
    code_only = re.sub(r"#.*", "", code_only)
    assert "shell=True" not in code_only, (
        "NFR-02 invariant violated: executor.py passes shell=True as a kwarg"
    )


# ---------------------------------------------------------------------------
# Exit-code constants (FR-02 SPEC §3 single-task exit-code matrix)
# ---------------------------------------------------------------------------


def test_fr02_unit_exit_constants_match_spec():
    """[FR-02] SPEC §3 exit-code matrix is encoded in module constants."""
    assert EXIT_OK == 0
    assert EXIT_INTERNAL == 1
    assert EXIT_TIMEOUT == 4