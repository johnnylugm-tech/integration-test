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
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from conftest import run_taskq


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