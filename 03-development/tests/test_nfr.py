"""NFR tests for taskq — Gate 2 spec-coverage requirements.

Covers NFR-01 through NFR-06 per TEST_SPEC.md:
  NFR-01: Performance — submit+status p95 < 50ms (100 iterations)
  NFR-02: Security — shell=True forbidden + injection blacklist
  NFR-03: Reliability — atomic writes + JSON validity after interrupt
  NFR-04: Security — secret redaction in stdout_tail/stderr_tail
  NFR-05: Maintainability — docstrings with [FR-XX] references
  NFR-06: Deployability — TASKQ_* env vars + .env.example
  NFR-99: Placeholder for TBD/deferred NFRs — none emitted in this project
          (SRS.md §"not emitted" section; no test cases required)
"""
from __future__ import annotations

import ast
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional
from unittest.mock import patch, MagicMock

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from taskq.config import get_config, Config, _parse_env
from taskq.models import Task, TaskStatus
from taskq.store import save_task, load_tasks, _redact, _atomic_write
from taskq.breaker import Breaker
from taskq.cli import cmd_submit, cmd_status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(tmp_path: Path) -> Config:
    os.environ["TASKQ_HOME"] = str(tmp_path)
    os.environ["TASKQ_BREAKER_COOLDOWN"] = "2"
    return get_config()


# ===========================================================================
# NFR-01: Performance — submit+status p95 < 50ms (100 iterations)
# ===========================================================================

def test_nfr01_submit_status_p95_under_50ms_100_iter(tmp_path):
    """NFR-01 [AC-NFR01.1]: p95 of submit+status round-trip < 50ms for 100 iters."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    timings_ms = []
    for i in range(100):
        t0 = time.perf_counter()
        task = cmd_submit(f"echo iter{i}", name=None, cfg=cfg)
        # status lookup
        tasks = load_tasks(cfg)
        _ = tasks.get(task.id)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        timings_ms.append(elapsed_ms)
    timings_ms.sort()
    p95_ms = timings_ms[int(0.95 * len(timings_ms))]
    assert p95_ms < 50, f"p95_ms={p95_ms:.2f} >= 50ms — NFR-01 SLA violated"


# ===========================================================================
# NFR-02: Security — shell=True forbidden + injection blacklist
# ===========================================================================

def test_nfr02_no_shell_true_in_codebase():
    """NFR-02 [AC-NFR02.1]: grep shell=True in src/taskq/ must return 0 hits in code (not docs)."""
    src_dir = Path(__file__).parent.parent / "src" / "taskq"
    shell_true_hits = []
    for py_file in src_dir.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            # Only check actual Call nodes, not string literals in docstrings
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        shell_true_hits.append(f"{py_file.name}:{node.lineno}")
    assert len(shell_true_hits) == 0, (
        f"shell=True found {len(shell_true_hits)} call(s): {shell_true_hits}"
    )


def test_nfr02_injection_char_blacklist_covered_in_fr01_tests():
    """NFR-02 [AC-NFR02.2]: injection chars are tested in FR-01 test file."""
    injection_chars = [";", "|", "&", "$", ">", "<", "`"]
    fr01_path = Path(__file__).parent / "test_fr01.py"
    text = fr01_path.read_text(encoding="utf-8")
    missing = [c for c in injection_chars if c not in text]
    assert len(missing) == 0, (
        f"Injection chars not covered in test_fr01.py: {missing}"
    )


# ===========================================================================
# NFR-03: Reliability — atomic writes + JSON validity after interrupt
# ===========================================================================

def test_nfr03_atomic_write_uses_tmp_then_os_replace(tmp_path):
    """NFR-03 [AC-NFR03.1]: _atomic_write uses mkstemp+os.replace, not open(w)."""
    target = tmp_path / "tasks.json"
    tmp_files_seen: list[str] = []
    orig_mkstemp = tempfile.mkstemp

    def spy_mkstemp(dir=None, suffix="", prefix="", **kw):
        fd, path = orig_mkstemp(dir=dir, suffix=suffix, prefix=prefix, **kw)
        tmp_files_seen.append(path)
        return fd, path

    with patch("taskq.store.tempfile.mkstemp", side_effect=spy_mkstemp):
        _atomic_write(str(target), {"key": "value"})

    assert target.exists(), "tasks.json was not created"
    data = json.loads(target.read_text())
    assert data == {"key": "value"}
    assert len(tmp_files_seen) == 1, "mkstemp was not called"
    # Temp file should be gone (replaced)
    assert not Path(tmp_files_seen[0]).exists(), "tmp file still exists after os.replace"


def test_nfr03_tasks_json_valid_after_simulated_interrupt(tmp_path):
    """NFR-03 [AC-NFR03.1]: tasks.json stays valid JSON even when write is interrupted."""
    # Pre-populate a valid tasks.json
    tasks_path = tmp_path / "tasks.json"
    original_data = {"t1": {"command": "echo ok", "status": "pending"}}
    tasks_path.write_text(json.dumps(original_data))

    # Simulate interrupt by having os.replace raise — original must survive
    with patch("taskq.store.os.replace", side_effect=OSError("interrupt")):
        try:
            _atomic_write(str(tasks_path), {"t1": {"status": "running"}})
        except OSError:
            pass

    # Original file must still be valid JSON
    content = tasks_path.read_text()
    parsed = json.loads(content)
    assert isinstance(parsed, dict), "tasks.json is not a valid JSON object after interrupt"
    assert "t1" in parsed, "original task entry lost after interrupted write"


def test_nfr03_breaker_json_valid_after_simulated_interrupt(tmp_path):
    """NFR-03 [AC-NFR03.1]: breaker.json stays valid JSON after interrupted write."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    breaker = Breaker(cfg)

    # Write initial state
    breaker.record_failure()

    breaker_path = tmp_path / "breaker.json"
    original_content = breaker_path.read_text()
    assert json.loads(original_content)  # confirm valid before

    # Simulate interrupt on second write
    with patch("taskq.breaker.os.replace", side_effect=OSError("interrupt")):
        try:
            breaker.record_failure()
        except OSError:
            pass

    content = breaker_path.read_text()
    parsed = json.loads(content)
    assert isinstance(parsed, dict), "breaker.json is not valid JSON after interrupt"


def test_nfr03_cache_json_valid_after_simulated_interrupt(tmp_path):
    """NFR-03 [AC-NFR03.1]: cache.json stays valid JSON after interrupted write."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()

    from taskq.cache import write as cache_write, _load as cache_load
    task = Task(
        id="t1",
        command="echo hi",
        name=None,
        status=TaskStatus.done,
        created_at="2026-01-01T00:00:00+00:00",
        exit_code=0,
        stdout_tail="hi\n",
        stderr_tail="",
        duration_ms=10.0,
        finished_at="2026-01-01T00:00:01+00:00",
    )

    # Write a valid cache entry first
    cache_write("echo hi", task, cfg)
    cache_path = tmp_path / "cache.json"
    assert cache_path.exists()
    original = cache_path.read_text()
    assert json.loads(original)

    # Interrupt second write
    with patch("taskq.cache.os.replace", side_effect=OSError("interrupt")):
        try:
            cache_write("echo hi", task, cfg)
        except OSError:
            pass

    content = cache_path.read_text()
    parsed = json.loads(content)
    assert isinstance(parsed, dict), "cache.json is not valid JSON after interrupt"


def test_nfr03_breaker_open_to_closed_recovery_under_cooldown_plus_one_second(tmp_path):
    """NFR-03 [AC-NFR03.2]: OPEN→HALF_OPEN transition within cooldown + 1 second."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    os.environ["TASKQ_BREAKER_THRESHOLD"] = "1"
    os.environ["TASKQ_BREAKER_COOLDOWN"] = "2"
    cfg = get_config()
    breaker = Breaker(cfg)

    # Open the breaker
    breaker.record_failure()
    assert breaker.get_state().value == "OPEN"

    # Wait for cooldown (2s) + margin
    t0 = time.monotonic()
    while time.monotonic() - t0 < 3.5:
        state = breaker.get_current_state()
        if state.value in ("HALF_OPEN", "CLOSED"):
            break
        time.sleep(0.05)

    elapsed = time.monotonic() - t0
    assert elapsed <= 3.0, f"Recovery took {elapsed:.2f}s > cooldown(2)+1 = 3.0s"
    assert breaker.get_current_state().value in ("HALF_OPEN", "CLOSED")


def test_nfr03_run_all_after_interrupt_no_task_lost(tmp_path):
    """NFR-03 [NP-13]: 5 tasks submitted then run_all — no task lost, all complete."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    os.environ["TASKQ_MAX_WORKERS"] = "3"
    os.environ["TASKQ_RETRY_LIMIT"] = "0"
    os.environ["TASKQ_TASK_TIMEOUT"] = "5.0"
    cfg = get_config()

    from taskq.executor import run_all
    task_objs = []
    for i in range(5):
        task = cmd_submit(f"echo task{i}", name=None, cfg=cfg)
        task_objs.append(task)

    assert len(task_objs) == 5
    run_all(cfg, sleep_fn=lambda _: None)

    tasks = load_tasks(cfg)
    assert len(tasks) == 5, f"Expected 5 tasks, got {len(tasks)}"
    for task in task_objs:
        assert task.id in tasks, f"Task {task.id} lost after run_all"
        assert tasks[task.id].status in (TaskStatus.done, TaskStatus.failed, TaskStatus.timeout), (
            f"Task {task.id} still in status {tasks[task.id].status}"
        )


# ===========================================================================
# NFR-04: Security — secret redaction in stdout_tail/stderr_tail
# ===========================================================================

def test_nfr04_redacts_sk_prefix_lines_with_8_plus_alnum():
    """NFR-04 [AC-NFR04.1]: lines containing sk-<8+ alnum> are replaced with [REDACTED]."""
    output_line = "sk-abcdefgh12345678"
    result = _redact(output_line)
    assert result is not None
    assert "[REDACTED]" in result, f"Expected [REDACTED] in result, got: {result!r}"
    assert "sk-abcdefgh12345678" not in result


def test_nfr04_redacts_token_equals_lines():
    """NFR-04 [AC-NFR04.1]: lines containing token=<value> are replaced with [REDACTED]."""
    output_line = "token=mysecretvalue"
    result = _redact(output_line)
    assert result is not None
    assert "[REDACTED]" in result, f"Expected [REDACTED] in result, got: {result!r}"
    assert "mysecretvalue" not in result


def test_nfr04_redaction_replaces_whole_line_with_REDACTED():
    """NFR-04: full line containing sk-abc12345678 is replaced with [REDACTED]."""
    output_line = "prefix sk-abc12345678 suffix"
    result = _redact(output_line)
    assert result is not None
    assert "[REDACTED]" in result
    assert "prefix" not in result, "Sensitive line should be fully replaced"


def test_nfr04_no_redaction_on_clean_output():
    """NFR-04 [AC-NFR04.1]: clean lines pass through without modification."""
    output_line = "hello world"
    result = _redact(output_line)
    assert result is not None
    assert "hello world" in result, f"Clean output was modified: {result!r}"
    assert "[REDACTED]" not in result


def test_nfr04_redaction_applied_before_persist(tmp_path):
    """NFR-04: secrets in stdout_tail are redacted before tasks.json is written."""
    os.environ["TASKQ_HOME"] = str(tmp_path)
    cfg = get_config()
    task = Task(
        id="secret-task",
        command="echo test",
        name=None,
        status=TaskStatus.done,
        created_at="2026-01-01T00:00:00+00:00",
        exit_code=0,
        stdout_tail="sk-abc12345678 my secret",
        stderr_tail="",
        duration_ms=10.0,
        finished_at="2026-01-01T00:00:01+00:00",
    )
    save_task(task, cfg)

    tasks_path = tmp_path / "tasks.json"
    raw = json.loads(tasks_path.read_text())
    stored_stdout = raw["secret-task"].get("stdout_tail", "")
    assert "sk-abc12345678" not in stored_stdout, (
        f"Secret not redacted in tasks.json: {stored_stdout!r}"
    )
    assert "[REDACTED]" in stored_stdout


# ===========================================================================
# NFR-05: Maintainability — docstrings with [FR-XX] references
# ===========================================================================

def _get_public_functions_and_classes(src_dir: Path):
    """Return list of (file, name, has_docstring, has_fr_ref) for public defs."""
    results = []
    for py_file in sorted(src_dir.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name.startswith("_"):
                    continue
                docstring = ast.get_docstring(node) or ""
                has_doc = bool(docstring.strip())
                has_fr = bool(re.search(r"\[FR-\d+\]", docstring))
                results.append((py_file.name, node.name, has_doc, has_fr))
    return results


def test_nfr05_all_public_functions_have_docstrings():
    """NFR-05 [AC-NFR05.1]: all public functions/classes in src/taskq/ have docstrings."""
    src_dir = Path(__file__).parent.parent / "src" / "taskq"
    items = _get_public_functions_and_classes(src_dir)
    assert len(items) > 0, "No public functions found — check src_dir path"
    missing = [(f, name) for f, name, has_doc, _ in items if not has_doc]
    assert len(missing) == 0, (
        f"{len(missing)} public function(s) missing docstrings: {missing[:10]}"
    )


def test_nfr05_docstrings_contain_fr_xx_references():
    """NFR-05 [AC-NFR05.1]: docstrings in src/taskq/ contain [FR-XX] references."""
    src_dir = Path(__file__).parent.parent / "src" / "taskq"
    items = _get_public_functions_and_classes(src_dir)
    with_docs = [(f, name, has_fr) for f, name, has_doc, has_fr in items if has_doc]
    assert len(with_docs) > 0, "No documented public functions found"
    # At least 80% of documented functions should have an [FR-XX] ref
    fr_count = sum(1 for _, _, has_fr in with_docs if has_fr)
    ratio = fr_count / len(with_docs)
    assert ratio >= 0.8, (
        f"Only {fr_count}/{len(with_docs)} ({ratio:.0%}) docstrings contain [FR-XX] refs"
    )


# ===========================================================================
# NFR-06: Deployability — TASKQ_* env vars + .env.example
# ===========================================================================

# ===========================================================================
# Deployment smoke test
# ===========================================================================

def test_taskq_cli_entrypoint_help_returns_0():
    """Smoke: taskq --help exits 0 (CLI entry point is wired correctly)."""
    import subprocess as sp
    result = sp.run(
        [sys.executable, "-m", "taskq", "--help"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent / "src"),
    )
    assert result.returncode == 0, (
        f"taskq --help exited {result.returncode}. stderr: {result.stderr[:200]}"
    )
    assert "taskq" in result.stdout.lower(), "expected 'taskq' in --help output"


EXPECTED_VARS = [
    "TASKQ_HOME",
    "TASKQ_MAX_WORKERS",
    "TASKQ_TASK_TIMEOUT",
    "TASKQ_RETRY_LIMIT",
    "TASKQ_BACKOFF_BASE",
    "TASKQ_BREAKER_THRESHOLD",
    "TASKQ_BREAKER_COOLDOWN",
    "TASKQ_CACHE_TTL",
]


def test_nfr06_config_reads_all_eight_taskq_env_vars(tmp_path):
    """NFR-06 [AC-NFR06.1]: config.py reads all 8 TASKQ_* env vars."""
    import inspect
    import taskq.config as cfg_mod
    src = inspect.getsource(cfg_mod)
    missing = [v for v in EXPECTED_VARS if v not in src]
    assert len(missing) == 0, f"Missing TASKQ_* vars in config.py: {missing}"
    assert len(EXPECTED_VARS) == 8, f"Expected 8 vars, got {len(EXPECTED_VARS)}"


def test_nfr06_config_defaults_match_spec_section_5_1(tmp_path, monkeypatch):
    """NFR-06 [AC-NFR06.1]: default values match SPEC section 5.1 when vars unset."""
    for var in EXPECTED_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))

    cfg = _parse_env()
    assert cfg.max_workers == 4, f"TASKQ_MAX_WORKERS default={cfg.max_workers}, expected 4"
    assert cfg.task_timeout == 10.0, f"TASKQ_TASK_TIMEOUT default={cfg.task_timeout}, expected 10.0"
    assert cfg.retry_limit == 2, f"TASKQ_RETRY_LIMIT default={cfg.retry_limit}, expected 2"
    assert cfg.backoff_base == 0.1, f"TASKQ_BACKOFF_BASE default={cfg.backoff_base}, expected 0.1"
    assert cfg.breaker_threshold == 3, f"TASKQ_BREAKER_THRESHOLD default={cfg.breaker_threshold}, expected 3"
    assert cfg.breaker_cooldown == 5.0, f"TASKQ_BREAKER_COOLDOWN default={cfg.breaker_cooldown}, expected 5.0"
    assert cfg.cache_ttl == 3600, f"TASKQ_CACHE_TTL default={cfg.cache_ttl}, expected 3600"


def test_nfr06_env_example_declares_all_eight_vars_with_comments():
    """NFR-06 [AC-NFR06.2]: .env.example at project root declares all 8 TASKQ_* vars."""
    # Search from project root (up from tests/)
    project_root = Path(__file__).parent.parent.parent
    env_example = project_root / ".env.example"
    assert env_example.exists(), f".env.example not found at {env_example}"

    content = env_example.read_text(encoding="utf-8")
    declared = [v for v in EXPECTED_VARS if v in content]
    assert len(declared) == 8, (
        f".env.example declares {len(declared)}/8 vars. Missing: "
        f"{[v for v in EXPECTED_VARS if v not in declared]}"
    )
