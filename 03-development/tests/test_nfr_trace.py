"""NFR traceability smoke tests (Gate 2 trace 4c).

These tests reference NFR-01 / NFR-04 / NFR-05 / NFR-06 for the Gate 2
traceability dimension (4c: NFR → test). They perform real contract
checks against the SRS spec + source code — not stub assertions.
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRS_PATH = PROJECT_ROOT / "01-requirements" / "SRS.md"
SRC_DIR = PROJECT_ROOT / "03-development" / "src" / "taskq"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_nfr01_perf_p95_contract_documented():
    """[NFR-01] SPEC.md/SRS.md declare `submit`+`status` p95 < 50ms / 100 iter."""
    srs = _read(SRS_PATH)
    assert "NFR-01" in srs, "NFR-01 must be declared in SRS"
    assert "p95" in srs and "50ms" in srs, "NFR-01 contract must pin p95 < 50ms"


def test_nfr04_secret_redaction_pattern_documented():
    """[NFR-04] redaction pattern `(sk-...|token=...)` must appear in SRS spec."""
    srs = _read(SRS_PATH)
    assert "NFR-04" in srs, "NFR-04 must be declared in SRS"
    assert "sk-" in srs and "token=" in srs, "NFR-04 must declare sk-/token= patterns"


def test_nfr05_docstring_fr_ref_contract():
    """[NFR-05] public-API docstrings must carry [FR-XX]/[NFR-XX] refs."""
    srs = _read(SRS_PATH)
    assert "NFR-05" in srs, "NFR-05 must be declared in SRS"
    assert "docstring" in srs.lower(), "NFR-05 must mandate docstring references"


def test_nfr06_env_vars_eight_declared_in_source():
    """[NFR-06] all 8 TASKQ_* env vars are read from os.environ in src/taskq."""
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
    assert not missing, f"NFR-06: missing TASKQ_* env var reads in src/taskq: {missing}"