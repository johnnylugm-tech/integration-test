"""FR-02 — direct unit tests for the FR-02 modules (executor + redact + config).

These tests import the production modules directly (no subprocess) so
coverage can measure lines per module. They complement the integration
tests in `test_fr02.py` (which exercise the CLI end-to-end via
`python -m taskq run <id>` and so don't contribute to pytest-cov for
the executor module).

Coverage goal: lift `03-development/src/taskq/executor.py`,
`03-development/src/taskq/redact.py`, and `03-development/src/taskq/config.py`
above 80% for the FR-scoped Gate 1 evaluation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from taskq import redact as _redact_fn_re
from taskq.config import retry_limit, task_timeout
from taskq.executor import (
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_REJECTED,
    EXIT_TIMEOUT,
    UnhandledExecutionError,
    UnknownTaskError,
    _now_iso,
    _run_once,
    _truncate_tail,
    run_task,
)
from taskq.redact import redact as _redact_fn
from taskq.store import StoreCorruptedError, load_tasks_or_die


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point TASKQ_HOME at `tmp_path/.taskq` (auto-mkdir) and return it."""
    home = tmp_path / ".taskq"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


def _seed_task(home: Path, task_id: str, command: str, **overrides) -> dict:
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
# redact — NFR-03 line redaction
# ---------------------------------------------------------------------------


def test_redact_module_reexport():
    """[FR-02] `taskq.redact` re-exports the function callable."""
    assert callable(_redact_fn_re)
    assert _redact_fn_re is _redact_fn


def test_redact_redacts_sk_line():
    """[FR-02] A line beginning with `sk-XXXXXXXX` is replaced with `[REDACTED]`."""
    out = _redact_fn("sk-abcdef12345 secret payload\nnext line\n")
    assert "[REDACTED]" in out
    assert "sk-abcdef12345" not in out
    assert "next line" in out


def test_redact_redacts_token_line():
    """[FR-02] A line beginning with `token=...` is replaced with `[REDACTED]`."""
    out = _redact_fn("token=xyz123 abc\nnormal line\n")
    assert "[REDACTED]" in out
    assert "token=xyz123" not in out
    assert "normal line" in out


def test_redact_keeps_normal_lines():
    """[FR-02] Lines without a leading secret pattern pass through."""
    txt = "hello\nworld\nnormal token=later-on-line\n"
    out = _redact_fn(txt)
    assert "hello" in out
    assert "world" in out
    assert "normal token=later-on-line" in out


def test_redact_empty_string():
    """[FR-02] Empty input returns empty output (no crash)."""
    assert _redact_fn("") == ""


def test_redact_handles_crlf():
    """[FR-02] CRLF line endings are preserved on output."""
    out = _redact_fn("sk-abcdef1234 line\r\nnext\r\n")
    assert "[REDACTED]\r\n" in out
    assert "next" in out


# ---------------------------------------------------------------------------
# config — TASKQ_TASK_TIMEOUT / TASKQ_RETRY_LIMIT
# ---------------------------------------------------------------------------


def test_config_task_timeout_default(monkeypatch):
    """[FR-02] `task_timeout()` defaults to 10.0 when env unset."""
    monkeypatch.delenv("TASKQ_TASK_TIMEOUT", raising=False)
    assert task_timeout() == 10.0


def test_config_task_timeout_from_env(monkeypatch):
    """[FR-02] `task_timeout()` reads TASKQ_TASK_TIMEOUT when set."""
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "2.5")
    assert task_timeout() == 2.5


def test_config_task_timeout_invalid_env(monkeypatch):
    """[FR-02] Unparseable TASKQ_TASK_TIMEOUT falls back to default 10.0."""
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "not-a-number")
    assert task_timeout() == 10.0


def test_config_retry_limit_default(monkeypatch):
    """[FR-02] `retry_limit()` defaults to 2 when env unset."""
    monkeypatch.delenv("TASKQ_RETRY_LIMIT", raising=False)
    assert retry_limit() == 2


def test_config_retry_limit_from_env(monkeypatch):
    """[FR-02] `retry_limit()` reads TASKQ_RETRY_LIMIT when set."""
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "5")
    assert retry_limit() == 5


def test_config_retry_limit_invalid_env(monkeypatch):
    """[FR-02] Unparseable TASKQ_RETRY_LIMIT falls back to default 2."""
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "not-an-int")
    assert retry_limit() == 2


# ---------------------------------------------------------------------------
# executor — small helpers
# ---------------------------------------------------------------------------


def test_truncate_tail_empty():
    """[FR-02] _truncate_tail(None) and _truncate_tail('') return empty string."""
    assert _truncate_tail(None) == ""
    assert _truncate_tail("") == ""


def test_truncate_tail_under_limit():
    """[FR-02] Short text passes through unchanged."""
    assert _truncate_tail("hello") == "hello"


def test_truncate_tail_over_limit():
    """[FR-02] Text longer than 2000 chars is truncated to the trailing 2000."""
    big = "x" * 5000 + "tail-marker"
    out = _truncate_tail(big)
    assert len(out) == 2000
    assert out.endswith("tail-marker")


def test_now_iso_is_iso8601_with_tz():
    """[FR-02] _now_iso() returns an ISO-8601 string with timezone offset."""
    s = _now_iso()
    # The naive parse just verifies the format contains 'T' and a timezone suffix.
    assert "T" in s
    assert "+" in s or s.endswith("Z")


# ---------------------------------------------------------------------------
# executor._run_once — subprocess invocation branches
# ---------------------------------------------------------------------------


def test_run_once_success_path():
    """[FR-02] _run_once('true') returns status='done', exit_code=0, redacted tails."""
    out = _run_once("true", 5.0)
    assert out["status"] == "done"
    assert out["exit_code"] == 0
    assert out["duration_ms"] >= 0
    assert out["finished_at"]


def test_run_once_failure_path():
    """[FR-02] _run_once('false') returns status='failed', exit_code=1."""
    out = _run_once("false", 5.0)
    assert out["status"] == "failed"
    assert out["exit_code"] == 1
    assert out["duration_ms"] >= 0


def test_run_once_timeout_path():
    """[FR-02] _run_once('sleep 60', timeout=0.1) returns status='timeout', exit_code=None."""
    out = _run_once("sleep 60", 0.1)
    assert out["status"] == "timeout"
    assert out["exit_code"] is None
    assert out["duration_ms"] >= 0


def test_run_once_parse_error():
    """[FR-02] Malformed shell quoting yields a 'failed' result with `_error='parse'`."""
    out = _run_once("'unbalanced", 5.0)
    assert out["status"] == "failed"
    assert out["_error"] == "parse"
    assert "parse error" in out["stderr_tail"]


def test_run_once_captures_stdout():
    """[FR-02] _run_once('printf hello') captures 'hello' in stdout_tail."""
    out = _run_once("printf hello", 5.0)
    assert out["stdout_tail"] == "hello"
    assert out["status"] == "done"


def test_run_once_captures_stderr():
    """[FR-02] A command writing to stderr captures it in stderr_tail."""
    out = _run_once("/bin/sh -c 'printf oops 1>&2'", 5.0)
    assert "oops" in out["stderr_tail"]


# ---------------------------------------------------------------------------
# executor.run_task — retry loop, state transitions, errors
# ---------------------------------------------------------------------------


def test_run_task_unknown_id_raises(monkeypatch, tmp_path):
    """[FR-02] run_task() raises UnknownTaskError for a missing task id."""
    _seed_home(monkeypatch, tmp_path)
    with pytest.raises(UnknownTaskError):
        run_task("deadbeef")


def test_run_task_corrupt_store_raises(monkeypatch, tmp_path):
    """[FR-02] run_task() surfaces StoreCorruptedError when tasks.json is invalid."""
    home = _seed_home(monkeypatch, tmp_path)
    (home / "tasks.json").write_text("not-valid-json{", encoding="utf-8")
    with pytest.raises(StoreCorruptedError):
        run_task("deadbeef")


def test_run_task_success(monkeypatch, tmp_path):
    """[FR-02] run_task() transitions pending→running→done on a successful cmd."""
    home = _seed_home(monkeypatch, tmp_path)
    _seed_task(home, "abcd1234", "true")
    out = run_task("abcd1234")
    assert out["status"] == "done"
    assert out["exit_code"] == 0
    assert out["attempts"] >= 1
    assert out["duration_ms"] >= 0
    # Persisted state survives the call.
    persisted = load_tasks_or_die()
    assert persisted[0]["status"] == "done"


def test_run_task_failure_retries_then_terminal(monkeypatch, tmp_path):
    """[FR-02] run_task() retries `false` up to TASKQ_RETRY_LIMIT times, terminal='failed'."""
    home = _seed_home(monkeypatch, tmp_path)
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "2")
    _seed_task(home, "feed1234", "false")
    out = run_task("feed1234")
    assert out["status"] == "failed"
    assert out["attempts"] <= 3  # 1 initial + 2 retries
    assert out["attempts"] >= 1


def test_run_task_timeout_retries_then_terminal(monkeypatch, tmp_path):
    """[FR-02] run_task() retries a timeout, terminal='timeout', exit_code=4."""
    home = _seed_home(monkeypatch, tmp_path)
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.05")
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "1")
    _seed_task(home, "beef0001", "sleep 5")
    out = run_task("beef0001")
    assert out["status"] == "timeout"
    assert out["exit_code"] == EXIT_TIMEOUT
    assert out["attempts"] <= 2


def test_run_task_retry_zero_means_one_attempt(monkeypatch, tmp_path):
    """[FR-02] TASKQ_RETRY_LIMIT=0 means exactly one attempt (no retries)."""
    home = _seed_home(monkeypatch, tmp_path)
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    _seed_task(home, "00000001", "false")
    out = run_task("00000001")
    assert out["status"] == "failed"
    assert out["attempts"] == 1


def test_run_task_unhandled_exception(monkeypatch, tmp_path):
    """[FR-02] run_task() raises UnhandledExecutionError for a missing binary, after persisting failure."""
    home = _seed_home(monkeypatch, tmp_path)
    _seed_task(home, "dead0001", "/this/binary/does/not/exist/xyz")
    with pytest.raises(UnhandledExecutionError):
        run_task("dead0001")
    # Even after the exception, the persisted record reflects status='failed'.
    persisted = load_tasks_or_die()
    assert persisted[0]["status"] == "failed"


def test_run_task_redacts_tails(monkeypatch, tmp_path):
    """[FR-02] run_task() redacts secret-bearing lines in stdout/stderr tails before persist."""
    home = _seed_home(monkeypatch, tmp_path)
    _seed_task(home, "redact01", "printf 'sk-abcdef12345 secret\\nok line\\n'")
    out = run_task("redact01")
    assert "[REDACTED]" in out["stdout_tail"]
    assert "sk-abcdef12345" not in out["stdout_tail"]
    assert "ok line" in out["stdout_tail"]


def test_run_task_truncates_long_tails(monkeypatch, tmp_path):
    """[FR-02] run_task() persists only the trailing 2000 chars of stdout/stderr."""
    home = _seed_home(monkeypatch, tmp_path)
    # printf with no trailing newline emits exactly the chars we ask for.
    _seed_task(home, "longtail", "printf 'x%.0s' {1..3000}")
    out = run_task("longtail")
    assert len(out["stdout_tail"]) <= 2000


def test_run_task_sets_finished_at(monkeypatch, tmp_path):
    """[FR-02] run_task() populates finished_at on terminal state."""
    home = _seed_home(monkeypatch, tmp_path)
    _seed_task(home, "finish01", "true")
    out = run_task("finish01")
    assert out["finished_at"]
    assert "T" in out["finished_at"]


# ---------------------------------------------------------------------------
# executor exit-code constants
# ---------------------------------------------------------------------------


def test_exit_constants_match_spec():
    """[FR-02] SPEC §3 exit-code matrix is encoded in module constants."""
    assert EXIT_OK == 0
    assert EXIT_INTERNAL == 1
    assert EXIT_REJECTED == 2
    assert EXIT_TIMEOUT == 4


# ---------------------------------------------------------------------------
# subprocess path: a `real` shell=True audit (NFR-02 chokepoint)
# ---------------------------------------------------------------------------


def test_executor_source_does_not_use_shell_true():
    """[FR-02] NFR-02: `shell=True` MUST NOT appear as a kwarg in executor.py."""
    import re
    executor_src = Path(__file__).parent.parent / "src" / "taskq" / "executor.py"
    text = executor_src.read_text(encoding="utf-8")
    # Strip docstrings/comments: find only `shell=True` as a real kwarg.
    code_only = re.sub(r'""".*?"""', "", text, flags=re.DOTALL)
    code_only = re.sub(r"#.*", "", code_only)
    assert "shell=True" not in code_only, (
        "NFR-02 invariant violated: executor.py passes shell=True as a kwarg"
    )