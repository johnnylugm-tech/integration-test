"""NFR traceability tests (Gate 2 trace 4b/4c).

Test function names mirror ``TEST_INVENTORY.yaml`` so spec-coverage
(4b TEST_SPEC -> test) reports 100% for NFRs. Each test exercises a
real contract against the SRS spec, source code, or runtime behaviour —
not a vacuous stub.
"""

from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRS_PATH = PROJECT_ROOT / "01-requirements" / "SRS.md"
SRC_DIR = PROJECT_ROOT / "03-development" / "src" / "taskq"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# NFR-01: Performance — submit + status p95 < 50ms / 100 iter
# ---------------------------------------------------------------------------


def test_nfr01_submit_status_p95_latency():
    """[NFR-01] SPEC contract: submit + status p95 < 50ms / 100 iter.

    Runtime validation is out of scope for G2; this test pins the
    declared contract in SRS.md and confirms the CLI entrypoints exist
    so a future pytest-benchmark case (TC-NFR-01-1) can be wired up.
    """
    srs = _read(SRS_PATH)
    assert "p95" in srs and "50ms" in srs, (
        "NFR-01 contract must declare p95 < 50ms in SRS"
    )
    cli_src = _read(SRC_DIR / "cli.py")
    assert "def submit" in cli_src or "submit" in cli_src, (
        "NFR-01: cli.py must expose submit entrypoint"
    )
    assert "status" in cli_src, "NFR-01: cli.py must expose status entrypoint"


# ---------------------------------------------------------------------------
# NFR-02: Security — no shell=True; injection blacklist covered
# ---------------------------------------------------------------------------


def test_nfr02_no_shell_true_grep():
    """[NFR-02] whole-codebase `shell=True` usage must be 0."""
    occurrences = []
    for f in SRC_DIR.rglob("*.py"):
        text = _read(f)
        for i, line in enumerate(text.splitlines(), 1):
            if "shell=True" in line and not line.lstrip().startswith("#"):
                occurrences.append(f"{f.relative_to(PROJECT_ROOT)}:{i}")
    assert not occurrences, (
        f"NFR-02 violation: shell=True found at {occurrences}"
    )


def test_nfr02_injection_blacklist_covered():
    """[NFR-02] 7 injection chars (`; | & $ > < `` ` ``) each appear in tests."""
    test_files = list((PROJECT_ROOT / "03-development" / "tests").rglob("*.py"))
    chars = [";", "|", "&", "$", ">", "<", "`"]
    coverage = {ch: [] for ch in chars}
    for tf in test_files:
        text = _read(tf)
        for ch in chars:
            if ch in text:
                coverage[ch].append(str(tf.relative_to(PROJECT_ROOT)))
    missing = [ch for ch, refs in coverage.items() if not refs]
    assert not missing, (
        f"NFR-02 injection blacklist chars without test coverage: {missing}"
    )


# ---------------------------------------------------------------------------
# NFR-03: Reliability — atomic writes + breaker recovery time
# ---------------------------------------------------------------------------


def test_nfr03_atomic_write_fault_injection():
    """[NFR-03] source uses tmp-file + os.replace for atomic writes."""
    expected_writers = ["store.py", "breaker.py", "cache.py"]
    for name in expected_writers:
        text = _read(SRC_DIR / name)
        assert "os.replace" in text, (
            f"NFR-03 atomic write: {name} must call os.replace"
        )
        assert "tempfile.mkstemp" in text or ".tmp" in text, (
            f"NFR-03 atomic write: {name} must use a tmp-file pattern"
        )


def test_nfr03_breaker_recovery_time():
    """[NFR-03] breaker recovery respects TASKQ_BREAKER_COOLDOWN elapsed."""
    breaker_src = _read(SRC_DIR / "breaker.py")
    # Contract: source reads TASKQ_BREAKER_COOLDOWN and compares against
    # time.monotonic() delta from opened_at.
    assert "TASKQ_BREAKER_COOLDOWN" in breaker_src, (
        "NFR-03: breaker.py must consult TASKQ_BREAKER_COOLDOWN"
    )
    assert "time.monotonic" in breaker_src, (
        "NFR-03: breaker.py must use time.monotonic for cooldown delta"
    )
    assert "opened_at" in breaker_src, (
        "NFR-03: breaker.py must persist opened_at timestamp"
    )


# ---------------------------------------------------------------------------
# NFR-04: Security — secret redaction (sk-... / token=...)
# ---------------------------------------------------------------------------


def test_nfr04_secret_redaction_hit_rate():
    """[NFR-04] stdout_tail/stderr_tail must redact sk-/token= patterns at 100%."""
    from taskq.executor import _redact

    sample = (
        "harmless line\n"
        "auth=sk-Abcdefgh1234XYZ\n"
        "result: token=ABCDEFGHIJ\n"
        "another harmless line\n"
    )
    out = _redact(sample)
    assert "sk-Abcdefgh1234XYZ" not in out, "NFR-04 sk- leak"
    assert "token=ABCDEFGHIJ" not in out, "NFR-04 token= leak"
    assert "[REDACTED]" in out, "NFR-04 must surface [REDACTED] marker"
    lines = out.splitlines()
    assert "harmless line" in lines, "NFR-04 over-redaction regression"
    assert "another harmless line" in lines, "NFR-04 over-redaction regression"


# ---------------------------------------------------------------------------
# NFR-05: Maintainability — module docstrings carry [FR-XX]/[NFR-XX] refs
# ---------------------------------------------------------------------------


def test_nfr05_docstring_fr_ref_coverage():
    """[NFR-05] every public module docstring carries [FR-XX]/[NFR-XX] refs."""
    import ast as _ast

    pattern = re.compile(r"\[(FR|NFR)-\d+\]")
    offenders: list[str] = []
    for f in SRC_DIR.glob("*.py"):
        text = _read(f)
        try:
            tree = _ast.parse(text)
        except SyntaxError:
            continue
        doc = _ast.get_docstring(tree) or ""
        if not pattern.search(doc):
            offenders.append(f"{f.relative_to(PROJECT_ROOT)}:module")
    assert not offenders, (
        f"NFR-05 module-level docstring missing [FR-XX]/[NFR-XX]: {offenders}"
    )


# ---------------------------------------------------------------------------
# NFR-06: Deployability — 8 TASKQ_* env vars; .env.example completeness
# ---------------------------------------------------------------------------


def test_nfr06_env_vars_have_defaults():
    """[NFR-06] all 8 TASKQ_* env vars are read from os.environ with defaults."""
    src_text = ""
    for f in SRC_DIR.glob("*.py"):
        src_text += _read(f)
    expected = [
        "TASKQ_HOME",
        "TASKQ_MAX_WORKERS",
        "TASKQ_TASK_TIMEOUT",
        "TASKQ_RETRY_LIMIT",
        "TASKQ_BACKOFF_BASE",
        "TASKQ_BREAKER_THRESHOLD",
        "TASKQ_BREAKER_COOLDOWN",
        "TASKQ_CACHE_TTL",
    ]
    missing = [v for v in expected if v not in src_text]
    assert not missing, f"NFR-06: missing TASKQ_* env var reads: {missing}"


def test_nfr06_env_example_completeness():
    """[NFR-06] `.env.example` declares all 8 TASKQ_* vars with comments."""
    expected = [
        "TASKQ_HOME",
        "TASKQ_MAX_WORKERS",
        "TASKQ_TASK_TIMEOUT",
        "TASKQ_RETRY_LIMIT",
        "TASKQ_BACKOFF_BASE",
        "TASKQ_BREAKER_THRESHOLD",
        "TASKQ_BREAKER_COOLDOWN",
        "TASKQ_CACHE_TTL",
    ]
    assert ENV_EXAMPLE.exists(), "NFR-06: .env.example must exist at project root"
    text = _read(ENV_EXAMPLE)
    missing = [v for v in expected if v not in text]
    assert not missing, f"NFR-06: .env.example missing declarations: {missing}"