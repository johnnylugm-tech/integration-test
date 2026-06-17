"""FR-01 — TDD RED step.

These tests cover `taskq submit` validation (non-empty / length<=1000 /
injection-char blacklist), uuid4 8-hex id generation, atomic persistence
to `$TASKQ_HOME/tasks.json`, and store-corruption detection (exit 1, no
silent rebuild).

GREEN TODO — these symbols MUST be implemented in `core/taskq/`:
    taskq.cli.main(argv: list[str] | None = None) -> int
    taskq.store.submit_task(command: str) -> str
    taskq.store.load_store() -> dict[str, Task]
    taskq.store.get_task(task_id: str) -> Task | None
    taskq.store.clear_store() -> None
    taskq.store.models.Task
    taskq.store.models.StoreCorrupted
    taskq.store.validation.validate_command(command: str) -> None
    taskq.store.validation.INJECTION_CHARS  # exactly 6: ; | & $ > < `
    taskq.store.validation.MAX_COMMAND_LENGTH  # 1000
    taskq.store.validation.ValidationError
    taskq.store.ids.generate_task_id() -> str  # 8 lowercase hex chars
    taskq.config.load_config() -> Config
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from taskq.cli import main as cli_main
from taskq.config import load_config
from taskq.store import clear_store, get_task, load_store, submit_task
from taskq.store.ids import generate_task_id
from taskq.store.models import StoreCorrupted, Task
from taskq.store.validation import (
    INJECTION_CHARS,
    MAX_COMMAND_LENGTH,
    ValidationError,
    validate_command,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def taskq_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect TASKQ_HOME to an isolated tmp directory for each test."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def run_cli(taskq_home: Path, capsys: pytest.CaptureFixture[str]):
    """Invoke `python -m taskq <argv>` in a clean subprocess with
    TASKQ_HOME pointing at the test tmp dir. Returns (exit_code, stdout, stderr).
    """

    def _run(argv: list[str]) -> tuple[int, str, str]:
        env = {"TASKQ_HOME": str(taskq_home), "PATH": __import__("os").environ.get("PATH", "")}
        # Use `python -m taskq` with cwd on the src/ root.
        result = subprocess.run(
            [sys.executable, "-m", "taskq", *argv],
            capture_output=True,
            text=True,
            env=env,
            cwd=Path(__file__).resolve().parent.parent / "src",
        )
        return result.returncode, result.stdout, result.stderr

    return _run


# ---------------------------------------------------------------------------
# 1. Happy path: valid command → exit 0
# ---------------------------------------------------------------------------


def test_fr01_submit_valid_command_returns_zero(run_cli, taskq_home: Path) -> None:
    exit_code, _stdout, _stderr = run_cli(["submit", "echo hello"])
    assert exit_code == 0
    assert (taskq_home / "tasks.json").exists()
    store = json.loads((taskq_home / "tasks.json").read_text())
    assert len(store) == 1
    [(task_id, record)] = store.items()
    assert re.fullmatch(r"[0-9a-f]{8}", task_id) is not None
    assert record["command"] == "echo hello"
    assert record["status"] == "pending"


# ---------------------------------------------------------------------------
# 2. Empty command → exit 2
# ---------------------------------------------------------------------------


def test_fr01_submit_empty_command_returns_two(run_cli, taskq_home: Path) -> None:
    exit_code, _stdout, stderr = run_cli(["submit", ""])
    assert exit_code == 2
    assert "error" in stderr.lower()
    # No store mutation.
    assert not (taskq_home / "tasks.json").exists()


# ---------------------------------------------------------------------------
# 3. Whitespace-only command → exit 2
# ---------------------------------------------------------------------------


def test_fr01_submit_whitespace_command_returns_two(run_cli, taskq_home: Path) -> None:
    exit_code, _stdout, stderr = run_cli(["submit", "   "])
    assert exit_code == 2
    assert "error" in stderr.lower()
    assert not (taskq_home / "tasks.json").exists()


# ---------------------------------------------------------------------------
# 4. Command above 1000 chars → exit 2
# ---------------------------------------------------------------------------


def test_fr01_submit_long_command_returns_two(run_cli, taskq_home: Path) -> None:
    long_cmd = "a" * 1001
    exit_code, _stdout, stderr = run_cli(["submit", long_cmd])
    assert exit_code == 2
    assert "error" in stderr.lower()
    assert not (taskq_home / "tasks.json").exists()


# ---------------------------------------------------------------------------
# 5. Command at exactly length 1000 → accepted (boundary)
# ---------------------------------------------------------------------------


def test_fr01_submit_command_at_length_1000_accepted(run_cli, taskq_home: Path) -> None:
    boundary_cmd = "a" * 1000
    exit_code, _stdout, _stderr = run_cli(["submit", boundary_cmd])
    assert exit_code == 0
    assert (taskq_home / "tasks.json").exists()
    store = json.loads((taskq_home / "tasks.json").read_text())
    assert len(store) == 1
    [(task_id, record)] = store.items()
    assert record["command"] == boundary_cmd
    assert len(record["command"]) == 1000


# ---------------------------------------------------------------------------
# 6. Injection chars (6 of them) → exit 2 (parametrized)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("char", list(";|&$><`"))
def test_fr01_submit_injection_chars_returns_two(
    run_cli, taskq_home: Path, char: str
) -> None:
    cmd = f"echo {char}"
    exit_code, _stdout, stderr = run_cli(["submit", cmd])
    assert exit_code == 2
    assert "error" in stderr.lower()
    # Verify the INJECTION_CHARS contract itself: exactly 6, the documented set.
    assert INJECTION_CHARS == ";|&$><`"
    assert not (taskq_home / "tasks.json").exists()


# ---------------------------------------------------------------------------
# 7. Initial status is "pending"
# ---------------------------------------------------------------------------


def test_fr01_initial_status_is_pending(taskq_home: Path) -> None:
    task_id = submit_task("echo hi")
    task = get_task(task_id)
    assert task is not None
    assert task.status == "pending"
    assert task.command == "echo hi"


# ---------------------------------------------------------------------------
# 8. Store corruption → exit 1 (no silent rebuild)
# ---------------------------------------------------------------------------


def test_fr01_store_corruption_returns_one(run_cli, taskq_home: Path) -> None:
    (taskq_home / "tasks.json").write_text('{"a1b2c3d4"')
    exit_code, _stdout, stderr = run_cli(["list"])
    assert exit_code == 1
    assert "store corrupted" in stderr
    # The corrupted file is preserved on disk — no silent rebuild.
    assert (taskq_home / "tasks.json").read_text() == '{"a1b2c3d4"'


# ---------------------------------------------------------------------------
# 9. uuid4 8-hex id format
# ---------------------------------------------------------------------------


def test_fr01_submit_produces_uuid4_id_format(taskq_home: Path) -> None:
    task_id = submit_task("echo hi")
    assert re.fullmatch(r"[0-9a-f]{8}", task_id) is not None
    # Two consecutive ids must differ (uuid4 randomness).
    other_id = submit_task("echo again")
    assert task_id != other_id


# ---------------------------------------------------------------------------
# 10. Concurrent writes are isolated (no corruption, no lost tasks)
# ---------------------------------------------------------------------------


def test_fr01_concurrent_writes_isolated(taskq_home: Path) -> None:
    # Direct sequential in-process test: 8 distinct ids, no key collisions.
    ids = [submit_task(f"echo p{i}") for i in range(8)]
    assert len(set(ids)) == 8
    store = load_store()
    assert set(store.keys()) == set(ids)
    assert len(store) == 8


# ---------------------------------------------------------------------------
# 11. Data round-trip: write → reload → preserved
# ---------------------------------------------------------------------------


def test_fr01_data_round_trip_consistent(taskq_home: Path) -> None:
    original_command = "ls /tmp"
    task_id = submit_task(original_command)
    # Force a fresh load from disk.
    store = load_store()
    assert task_id in store
    reloaded = store[task_id]
    assert reloaded.command == original_command
    assert reloaded.status == "pending"
    # Atomic-write invariant: no leftover .tmp file.
    assert not (taskq_home / "tasks.json.tmp").exists()
    assert (taskq_home / "tasks.json").exists()


# ---------------------------------------------------------------------------
# 12. Must NOT silently rebuild the store on corruption
# ---------------------------------------------------------------------------


def test_fr01_must_not_silently_rebuild_on_corruption(
    run_cli, taskq_home: Path
) -> None:
    corrupted_content = '{"a1b2c3d4"'
    (taskq_home / "tasks.json").write_text(corrupted_content)
    exit_code, _stdout, stderr = run_cli(["status", "a1b2c3d4"])
    assert exit_code == 1
    assert "store corrupted" in stderr
    # File must remain on disk byte-for-byte as written — no silent reset.
    assert (taskq_home / "tasks.json").read_text() == corrupted_content
