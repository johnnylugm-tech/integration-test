"""RED-phase failing tests for FR-01: Task Submission and Validation.

Covers SPEC.md §3 FR-01 + Acceptance Criteria AC-FR-01-1..6 (6 cases).
Test function names are verbatim per 02-architecture/TEST_SPEC.md §FR-01.

RED contract: top-level import of `taskq.cli.main` is expected to fail with
ModuleNotFoundError (Exit Code 2 / Collection Error) until GREEN implements
the module. We do not use try/except ImportError to mask that.
"""
from __future__ import annotations

import json
import re

import pytest

# GREEN TODO: taskq.cli must define `main(argv: list[str] | None = None) -> int`
# that dispatches argparse subcommands (submit/run/status/list/clear) and returns
# the process exit code (0/2/3/4/1 per SPEC §3 FR-05 / §7).
from taskq.cli import main as cli_main

# GREEN TODO: taskq.config must read `TASKQ_HOME` (env var) and resolve the data
# directory; defaults to ".taskq" (SPEC §5.1). Tests monkeypatch this env var in
# an autouse fixture so writes are hermetic.
from taskq.config import TASKQ_HOME  # noqa: F401  -- used transitively via env


# ---------------------------------------------------------------------------
# Hermetic TASKQ_HOME — autouse so every test has an isolated data dir.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_taskq_home(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> "Path":  # noqa: F821
    """Per-test TASKQ_HOME pointing into tmp_path.

    AC-FR-01-rejection-outcome (cases 1-4): the validation-rejection cases
    must NOT write to tasks.json — verified via this fixture + helper below.
    """
    from pathlib import Path

    home = tmp_path / ".taskq"
    home.mkdir()
    monkeypatch.setenv("TASKQ_HOME", str(home))
    return home


def _tasks_file(home: "Path") -> "Path":  # noqa: F821
    return home / "tasks.json"


def _read_tasks(home: "Path") -> list:  # noqa: F821
    """Return parsed tasks.json content; [] if the file is absent.

    Cases 1-4 must leave the file absent or empty.
    """
    from pathlib import Path

    p: Path = _tasks_file(home)
    if not p.exists():
        return []
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    parsed = json.loads(raw)
    # tasks.json may store as list OR as dict mapping id -> task (SAD §2.4).
    # Normalize to a list of task dicts so assertions don't depend on shape.
    if isinstance(parsed, dict):
        return list(parsed.values())
    return parsed


# ---------------------------------------------------------------------------
# Case 1 — empty/whitespace command (Q2 validation)
# ---------------------------------------------------------------------------

def test_fr01_empty_command_exit2(isolated_taskq_home: "Path") -> None:  # noqa: F821
    """AC-FR-01-1: command empty / all-whitespace → exit 2, no write to tasks.json."""
    rc = cli_main(["submit", ""])
    assert rc == 2
    assert _read_tasks(isolated_taskq_home) == [], (
        "empty command must NOT produce any task records"
    )


# ---------------------------------------------------------------------------
# Case 2 — command too long (Q2 validation)
# ---------------------------------------------------------------------------

def test_fr01_command_too_long_exit2(isolated_taskq_home: "Path") -> None:  # noqa: F821
    """AC-FR-01-2: command > 1000 chars → exit 2, no write."""
    cmd = "x" * 1001  # strictly greater than 1000
    rc = cli_main(["submit", cmd])
    assert rc == 2
    assert _read_tasks(isolated_taskq_home) == []


# ---------------------------------------------------------------------------
# Case 3 — injection char blacklist (Q2 validation + NFR-02)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_char", [";", "|", "&", "$", ">", "<", "`"])
def test_fr01_injection_char_exit2(
    isolated_taskq_home: "Path", bad_char: str  # noqa: F821
) -> None:
    r"""AC-FR-01-3 + NFR-02: each injection char in ``; | & $ > < ` `` triggers exit 2.

    Test name is singular per TEST_SPEC; parametrize instances cover all 7
    blacklist chars from SPEC §3 FR-01 injection row.
    """
    rc = cli_main(["submit", f"echo hi{bad_char}rm x"])
    assert rc == 2, f"injection char {bad_char!r} must be rejected (exit 2)"
    assert _read_tasks(isolated_taskq_home) == [], (
        f"injection char {bad_char!r} must NOT produce task records"
    )


# ---------------------------------------------------------------------------
# Case 4 — duplicate --name (Q2 validation)
# ---------------------------------------------------------------------------

def test_fr01_duplicate_name_exit2(isolated_taskq_home: "Path") -> None:  # noqa: F821
    """AC-FR-01-4: --name colliding with existing pending/running task → exit 2."""
    rc_first = cli_main(["submit", "echo first", "--name", "dup"])
    assert rc_first == 0, (
        "prerequisite — first submit must succeed so a pending 'dup' exists"
    )

    rc_dup = cli_main(["submit", "echo second", "--name", "dup"])
    assert rc_dup == 2, "second submit with same --name must be rejected"

    tasks = _read_tasks(isolated_taskq_home)
    assert len(tasks) == 1, (
        f"exactly one (the first) task must be persisted, got {len(tasks)}"
    )
    assert tasks[0]["command"] == "echo first"
    assert tasks[0]["name"] == "dup"
    assert tasks[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Case 5 — happy path: valid submit yields pending task (Q1 happy_path)
# ---------------------------------------------------------------------------

_HEX8_RE = re.compile(r"\b[0-9a-f]{8}\b")


def test_fr01_valid_submit_pending(
    isolated_taskq_home: "Path",  # noqa: F821
    capsys: pytest.CaptureFixture,
) -> None:
    """AC-FR-01-5: valid submit → exit 0, stdout contains 8-hex id, task status pending."""
    rc = cli_main(["submit", "echo hi", "--name", "alpha"])
    assert rc == 0
    captured = capsys.readouterr()

    # stdout must contain the 8-hex task id (uuid4 hex prefix per SPEC §3 FR-01).
    assert _HEX8_RE.search(captured.out), (
        f"expected 8-hex task id in stdout, got: {captured.out!r}"
    )

    tasks = _read_tasks(isolated_taskq_home)
    assert len(tasks) == 1
    task = tasks[0]
    # SPEC §3 FR-01: pending, records command, name, created_at
    assert task["status"] == "pending"
    assert task["command"] == "echo hi"
    assert task["name"] == "alpha"
    assert "created_at" in task, "task record must carry created_at timestamp"
    # id must be the 8-hex printed to stdout
    assert re.fullmatch(r"[0-9a-f]{8}", task["id"])


# ---------------------------------------------------------------------------
# Case 6 — --json produces single-line machine-readable output (Q1 + NP-04)
# ---------------------------------------------------------------------------

def test_fr01_json_output_single_line(
    isolated_taskq_home: "Path",  # noqa: F821
    capsys: pytest.CaptureFixture,
) -> None:
    """AC-FR-01-6 + NP-04: `--json` output must be exactly one line of valid JSON
    containing ``{"id": "<8-hex>", "status": "pending"}``.
    """
    rc = cli_main(["submit", "echo hi", "--json"])
    assert rc == 0
    captured = capsys.readouterr()

    # Single non-empty line (no human-readable table / multi-line JSON).
    out_lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    assert len(out_lines) == 1, (
        f"--json must produce exactly one line, got {len(out_lines)}: "
        f"{captured.out!r}"
    )

    payload = json.loads(out_lines[0])
    assert "id" in payload and "status" in payload, (
        f"JSON payload must include id + status keys, got: {payload!r}"
    )
    assert re.fullmatch(r"[0-9a-f]{8}", payload["id"]), (
        f"id must be 8 hex chars, got: {payload['id']!r}"
    )
    assert payload["status"] == "pending"
