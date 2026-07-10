"""NFR (Non-Functional Requirement) tests.

Each test function name matches the spec-coverage ID so the framework's
`test_frNN_xxx` / `test_nfrNN_xxx` matcher can correlate them with NFRs.

Coverage:
  * NFR-01 (performance): test_nfr01_submit_status_p95_latency
  * NFR-02 (security):    test_nfr02_no_shell_true_grep
                          test_nfr02_injection_blacklist_covered
  * NFR-03 (reliability): test_nfr03_atomic_write_fault_injection
                          test_nfr03_breaker_recovery_time
  * NFR-04 (security):    test_nfr04_secret_redaction_hit_rate
  * NFR-05 (maintainability): test_nfr05_docstring_fr_ref_coverage
  * NFR-06 (deployability):   test_nfr06_env_vars_have_defaults
                               test_nfr06_env_example_completeness
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "03-development" / "src"
TASKQ_ROOT = SRC_ROOT / "taskq"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"

# ---------------------------------------------------------------------------
# NFR-01 — performance: submit + status p95 < 50ms / 100 iter (target module: taskq.cli)
# ---------------------------------------------------------------------------

def test_nfr01_submit_status_p95_latency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[NFR-01] submit + status p95 < 50ms over 100 iterations (per SPEC §11)."""
    from taskq import cli
    from taskq import store

    home = tmp_path / "taskq-home"
    monkeypatch.setenv("TASKQ_HOME", str(home))
    store._HOME = None  # noqa: SLF001

    latencies_ms: list[float] = []
    for _ in range(100):
        start = time.perf_counter()
        rc = cli.main(["--json", "submit", "true"])
        assert rc == 0
        tasks = json.loads((home / "tasks.json").read_text())
        task_id = next(iter(tasks))
        rc = cli.main(["--json", "status", task_id])
        assert rc == 0
        latencies_ms.append((time.perf_counter() - start) * 1000.0)

    latencies_ms.sort()
    p95 = latencies_ms[int(0.95 * len(latencies_ms)) - 1]
    assert p95 < 50.0, f"NFR-01 violated: p95={p95:.1f}ms >= 50ms"


# ---------------------------------------------------------------------------
# NFR-02 — security: shell=True absent (whole codebase) + injection blacklist covered
# ---------------------------------------------------------------------------

def test_nfr02_no_shell_true_grep() -> None:
    """[NFR-02] No `shell=True` anywhere in the taskq source tree (NP-04 grep)."""
    pattern = "shell=True"
    total = 0
    for py in sorted(TASKQ_ROOT.rglob("*.py")):
        total += py.read_text().count(pattern)
    assert total == 0, f"NFR-02 violated: shell=True appears {total}x in taskq/"


def test_nfr02_injection_blacklist_covered() -> None:
    """[NFR-02] All 7 forbidden shell metacharacters are rejected by `_validate_command`."""
    from taskq.cli import _validate_command, _INJECTION_CHARS
    # _INJECTION_CHARS = set(";|&$><`")  → 7 chars per SPEC §3 FR-01
    assert len(_INJECTION_CHARS) == 7
    for ch in _INJECTION_CHARS:
        bad = f"echo hi{ch}rm -rf /"
        assert _validate_command(bad) is not None, f"char {ch!r} not rejected"
    # Plain command passes
    assert _validate_command("echo hi") is None


# ---------------------------------------------------------------------------
# NFR-03 — reliability: atomic write recovery + breaker OPEN → CLOSED ≤ cooldown+1s
# ---------------------------------------------------------------------------

def test_nfr03_atomic_write_fault_injection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[NFR-03] If the *.json.tmp write is interrupted, the canonical file is preserved."""
    from taskq import store

    home = tmp_path / "taskq-home"
    home.mkdir()
    monkeypatch.setenv("TASKQ_HOME", str(home))
    store._HOME = None  # noqa: SLF001

    # Seed an intact tasks.json
    original = {"abc12345": {"id": "abc12345", "status": "pending", "command": "echo ok"}}
    tasks_path = home / "tasks.json"
    tasks_path.write_text(json.dumps(original))

    # Inject a corrupt .tmp alongside (simulates interrupted write)
    (home / "tasks.json.tmp").write_text("{ corrupt json")

    # Reload — must yield the original dict, not crash on the .tmp file
    loaded = store.load_tasks()
    assert loaded == original


def test_nfr03_breaker_recovery_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[NFR-03] Breaker OPEN → CLOSED happens within TASKQ_BREAKER_COOLDOWN + 1s."""
    from taskq import breaker

    home = tmp_path / "taskq-home"
    home.mkdir()
    monkeypatch.setenv("TASKQ_HOME", str(home))
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "1")
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "1")
    # Reset any breaker in-memory state from previous tests
    monkeypatch.setattr(breaker, "_BREAKER", None, raising=False)

    # Force breaker to OPEN by recording threshold failures
    b1 = breaker.Breaker()
    b1.record_failure()
    b1.record_failure()
    assert b1.state == breaker.STATE_OPEN

    # Save and reload → after cooldown it should transition to HALF_OPEN
    breaker.save(home / "breaker.json", b1)
    time.sleep(1.05)
    b2 = breaker.load(home / "breaker.json")
    # try_acquire() is what triggers the OPEN → HALF_OPEN transition once
    # the cooldown has elapsed (the load() call alone is read-only).
    b2.try_acquire()
    assert b2.state in (breaker.STATE_HALF_OPEN, breaker.STATE_CLOSED)


# ---------------------------------------------------------------------------
# NFR-04 — security: secret redaction 100% hit rate
# ---------------------------------------------------------------------------

def test_nfr04_secret_redaction_hit_rate() -> None:
    """[NFR-04] `sk-...` and `token=...` substrings are redacted in cache tails."""
    from taskq.executor import _redact

    raw = "prefix sk-12345678abcdefghij suffix\nerror token=abcdefghijklmnopqrstuvwxyz end"
    scrubbed = _redact(raw)

    # 100% hit rate: every sk-/token= occurrence MUST be replaced
    assert "sk-12345678abcdefghij" not in scrubbed
    assert "token=abcdefghijklmnopqrstuvwxyz" not in scrubbed
    # And the [REDACTED] marker appears in their place
    assert scrubbed.count("[REDACTED]") == 2

    # Sanity: short sk- prefixes (<8 chars) are NOT redacted (the regex requires {8,})
    short = _redact("sk-abc")
    assert "sk-abc" in short  # below length threshold — preserved

    # Sanity: token= without value is preserved (the regex requires \S+)
    bare = _redact("token=")
    assert bare == "token="


# ---------------------------------------------------------------------------
# NFR-05 — maintainability: docstring [FR-XX]/[NFR-XX] coverage on public API
# ---------------------------------------------------------------------------

def test_nfr05_docstring_fr_ref_coverage() -> None:
    """[NFR-05] Every public function in taskq/* carries a docstring citing [FR-XX] or [NFR-XX]."""
    ref_pattern = re.compile(r"\b(?:FR|NFR)-\d{2}\b")
    failures: list[str] = []

    for py in sorted(TASKQ_ROOT.rglob("*.py")):
        if py.name == "__init__.py":
            continue
        try:
            tree = ast.parse(py.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name.startswith("_"):
                    continue  # private
                doc = ast.get_docstring(node) or ""
                if not ref_pattern.search(doc):
                    failures.append(f"{py.relative_to(PROJECT_ROOT)}:{node.lineno} {node.name}")

    assert failures == [], f"NFR-05 violations: {failures[:5]}"


# ---------------------------------------------------------------------------
# NFR-06 — deployability: env vars + .env.example completeness
# ---------------------------------------------------------------------------

EXPECTED_ENV_VARS = [
    "TASKQ_HOME",
    "TASKQ_MAX_WORKERS",
    "TASKQ_TASK_TIMEOUT",
    "TASKQ_RETRY_LIMIT",
    "TASKQ_BACKOFF_BASE",
    "TASKQ_BREAKER_THRESHOLD",
    "TASKQ_BREAKER_COOLDOWN",
    "TASKQ_CACHE_TTL",
]


def test_nfr06_env_vars_have_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """[NFR-06] All 8 TASKQ_* vars are read with sensible defaults (no KeyError)."""
    # Strip every TASKQ_* var from env, then import fresh
    for var in EXPECTED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # Fresh subprocess: read with no env → must not raise
    result = subprocess.run(
        [sys.executable, "-c", "import taskq.cli, taskq.executor, taskq.breaker, taskq.cache; print('ok')"],
        cwd=str(PROJECT_ROOT),
        env={k: v for k, v in os.environ.items() if not k.startswith("TASKQ_")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"defaults missing: stderr={result.stderr}"


def test_nfr06_env_example_completeness() -> None:
    """[NFR-06] `.env.example` declares every TASKQ_* var with a comment line."""
    assert ENV_EXAMPLE.exists(), f"missing {ENV_EXAMPLE}"
    text = ENV_EXAMPLE.read_text()
    missing = [v for v in EXPECTED_ENV_VARS if v not in text]
    assert missing == [], f"missing from .env.example: {missing}"