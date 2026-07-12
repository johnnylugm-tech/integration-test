"""FR-01 TDD-RED tests — Submit + Validation (AC-FR01-01..09).

In-process CLI invocation via `taskq.interface.cli:main(argv=...)` so we can
capture stdout/stderr and assert on exit codes without spinning subprocesses.
Each test isolates the storage path by setting `$TASKQ_HOME` to a tmp_path.

RED STATE: this file is EXPECTED to fail at import time. `src/taskq/`
does not exist yet — pytest will report a `ModuleNotFoundError` at
collection (Exit Code 2), which is a valid RED state for this step.
The GREEN agent must implement the public surfaces flagged below.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

import pytest

# GREEN TODO: taskq.interface.cli MUST expose `main(argv: list[str] | None = None) -> int`
# per SAD §3.1 (FR-05). Return value is the process exit code (0/1/2/3/4).
from taskq.interface.cli import main as cli_main

# 8 lowercase hex chars (uuid4().hex[:8]); CLI emits this verbatim on stdout (non-JSON)
EIGHT_HEX = re.compile(r"^[0-9a-f]{8}$")


def _run(argv: list[str], home: Path) -> int:
    """Invoke cli.main(argv) with TASKQ_HOME pinned to `home`. Returns exit code.

    Does NOT read capsys — caller is responsible for inspecting captured output
    after each call so successive `_run()` calls accumulate cleanly into the
    active capsys buffer.
    """
    old = os.environ.get("TASKQ_HOME")
    os.environ["TASKQ_HOME"] = str(home)
    try:
        return cli_main(argv)
    finally:
        if old is None:
            os.environ.pop("TASKQ_HOME", None)
        else:
            os.environ["TASKQ_HOME"] = old


# ---------------------------------------------------------------------------
# AC-FR01-01 — happy path: `submit "echo hi"` → exit 0, 8-hex id on stdout,
# tasks.json contains matching task with command / status / created_at.
# ---------------------------------------------------------------------------
def test_fr01_01_happy_submit_echo_hi(tmp_path, capsys):
    rc = _run(["submit", "echo hi"], tmp_path)
    out = capsys.readouterr().out

    assert rc == 0, f"submit happy should exit 0, got {rc}; stdout={out!r}"
    emitted = out.strip()
    assert EIGHT_HEX.match(emitted), f"stdout must be 8-hex id, got {emitted!r}"

    tasks_file = tmp_path / "tasks.json"
    assert tasks_file.exists(), "tasks.json must be written on success"
    data = json.loads(tasks_file.read_text())
    # storage shape is {id: task-dict}; id printed by CLI must be the key
    assert emitted in data, f"printed id {emitted!r} missing from tasks.json: {list(data)}"
    task = data[emitted]
    assert task["command"] == "echo hi"
    assert task["status"] == "pending"
    # created_at must parse as ISO 8601
    datetime.fromisoformat(task["created_at"])


# ---------------------------------------------------------------------------
# AC-FR01-02 — `--json` flag → stdout single-line JSON `{"id":"<8hex>","status":"pending"}`
# ---------------------------------------------------------------------------
def test_fr01_02_submit_json_output(tmp_path, capsys):
    rc = _run(["submit", "--json", "echo hi"], tmp_path)
    out = capsys.readouterr().out

    assert rc == 0, f"--json submit should exit 0, got {rc}; stdout={out!r}"
    # Single-line valid JSON: parse without internal `\n`/`\r`.
    assert "\n" not in out.rstrip("\n"), f"stdout must be single-line JSON, got {out!r}"
    payload = json.loads(out.strip())
    assert isinstance(payload, dict)
    assert EIGHT_HEX.match(payload["id"]), f"json id must be 8-hex, got {payload['id']!r}"
    assert payload["status"] == "pending"


# ---------------------------------------------------------------------------
# AC-FR01-03 — empty command → exit 2 + stderr, no new tasks.json entry
# ---------------------------------------------------------------------------
def test_fr01_03_submit_empty_command(tmp_path, capsys):
    rc = _run(["submit", ""], tmp_path)
    err = capsys.readouterr().err

    assert rc == 2, f"empty command must exit 2 (validation), got {rc}"
    assert err.strip() != "", "validation rejection must write to stderr"

    tasks_file = tmp_path / "tasks.json"
    if tasks_file.exists() and tasks_file.stat().st_size > 0:
        data = json.loads(tasks_file.read_text())
        assert data in ({}, []), f"validation failure must not add a task, got {data}"
    # If file doesn't exist or is empty, that is also a valid post-state.


# ---------------------------------------------------------------------------
# AC-FR01-04 — whitespace-only command → exit 2
# ---------------------------------------------------------------------------
def test_fr01_04_submit_whitespace_only(tmp_path, capsys):
    rc = _run(["submit", "   "], tmp_path)
    err = capsys.readouterr().err

    assert rc == 2, f"whitespace-only must exit 2, got {rc}"
    assert err.strip() != ""


# ---------------------------------------------------------------------------
# AC-FR01-05 — 1001-char command → exit 2 (length cap = 1000)
# ---------------------------------------------------------------------------
def test_fr01_05_submit_too_long(tmp_path, capsys):
    long_cmd = "a" * 1000 + "b"  # exactly 1001 chars
    assert len(long_cmd) == 1001

    rc = _run(["submit", long_cmd], tmp_path)
    err = capsys.readouterr().err

    assert rc == 2, f"1001-char command must exit 2, got {rc}"
    assert err.strip() != ""


# ---------------------------------------------------------------------------
# AC-FR01-06 — injection: `;` (one of NFR-02 blacklist chars) → exit 2
# ---------------------------------------------------------------------------
def test_fr01_06_submit_injection_semicolon(tmp_path, capsys):
    rc = _run(["submit", "echo hi; rm x"], tmp_path)
    err = capsys.readouterr().err

    assert rc == 2, f"semicolon injection must exit 2, got {rc}"
    assert err.strip() != ""

    tasks_file = tmp_path / "tasks.json"
    if tasks_file.exists() and tasks_file.stat().st_size > 0:
        data = json.loads(tasks_file.read_text())
        assert data in ({}, []), f"injection rejection must not add a task, got {data}"


# ---------------------------------------------------------------------------
# AC-FR01-07 — injection: `&` (TEST_SPEC covers ampersand as the representative
# of the 6-char blacklist `; | & $ > < ` ` per NFR-02).
# ---------------------------------------------------------------------------
def test_fr01_07_submit_injection_chars(tmp_path, capsys):
    rc = _run(["submit", "echo hi & cat"], tmp_path)
    err = capsys.readouterr().err

    assert rc == 2, f"ampersand injection must exit 2, got {rc}"
    assert err.strip() != ""


# ---------------------------------------------------------------------------
# AC-FR01-08 — `--name` collision with an existing pending/running task → exit 2
# ---------------------------------------------------------------------------
def test_fr01_08_submit_name_duplicate(tmp_path, capsys):
    rc1 = _run(["submit", "--name", "mytask", "echo hi"], tmp_path)
    out1 = capsys.readouterr().out

    assert rc1 == 0, f"first --name submit must exit 0, got {rc1}; stdout={out1!r}"
    emitted1 = out1.strip()
    assert EIGHT_HEX.match(emitted1)

    # Second submit with the same --name while the first is still pending → reject.
    rc2 = _run(["submit", "--name", "mytask", "echo hi"], tmp_path)
    err2 = capsys.readouterr().err

    assert rc2 == 2, f"duplicate --name must exit 2, got {rc2}"
    assert err2.strip() != ""

    tasks_file = tmp_path / "tasks.json"
    data = json.loads(tasks_file.read_text())
    # Exactly one task must carry name="mytask" — the second submit was rejected.
    matching = [t for t in data.values() if t.get("name") == "mytask"] if isinstance(data, dict) \
        else [t for t in data if t.get("name") == "mytask"]
    assert len(matching) == 1, f"expected exactly 1 'mytask' entry, got {len(matching)}: {matching}"


# ---------------------------------------------------------------------------
# AC-FR01-09 — Atomic write: if the write step raises OSError, tasks.json must
# remain intact (NFR-03). Pre-seed with a valid JSON, then make os.replace
# raise mid-submit; the seed file must survive untouched.
# ---------------------------------------------------------------------------
def test_fr01_09_submit_atomic_write(tmp_path, capsys, monkeypatch):
    tasks_file = tmp_path / "tasks.json"
    seed = {
        "00000001": {
            "id": "00000001",
            "command": "echo seed",
            "status": "done",
            "created_at": "2026-07-12T00:00:00",
        }
    }
    tasks_file.write_text(json.dumps(seed))

    # GREEN TODO: Store.submit (taskq.storage.store) must perform the final
    # commit step via `os.replace(tmp, final)` so that mid-write failures
    # leave the destination file untouched (NFR-03 atomic-write contract).
    # This patch forces that atomic-rename step to raise, simulating the
    # failure mode the requirement is designed to survive.
    def _raise_oserror(*_args, **_kwargs):
        raise OSError("simulated mid-write failure")

    monkeypatch.setattr(os, "replace", _raise_oserror)

    rc = _run(["submit", "echo hi"], tmp_path)
    captured = capsys.readouterr()

    # Submit must NOT exit 0 in the failure path; the CLI is free to choose
    # between a validation-style exit 2 or an internal/unexpected exit 1,
    # but it MUST signal the failure (non-zero) and stderr MUST be non-empty.
    assert rc != 0, "submit must fail when atomic write raises OSError"
    assert captured.err.strip() != "", "failed submit must write a diagnostic to stderr"

    # NFR-03 invariant: tasks.json is still valid JSON and matches pre-call state.
    assert tasks_file.exists(), "tasks.json must still exist after failed write"
    parsed = json.loads(tasks_file.read_text())
    assert parsed == seed, (
        f"tasks.json corrupted by failed write — expected unchanged seed, got {parsed}"
    )
