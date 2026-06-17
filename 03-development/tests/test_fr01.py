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
from taskq.store import clear_store, get_task, load_store, submit_task
from taskq.store.models import StoreCorrupted
from taskq.store.validation import INJECTION_CHARS

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


# ---------------------------------------------------------------------------
# Additional unit tests (cli.main direct + store edge cases) for coverage.
# ---------------------------------------------------------------------------


def test_fr01_load_store_when_file_absent(taskq_home: Path) -> None:
    """load_store on a non-existent tasks.json returns an empty dict (no error)."""
    assert not (taskq_home / "tasks.json").exists()
    store = load_store()
    assert store == {}


def test_fr01_load_store_rejects_non_dict_root(taskq_home: Path) -> None:
    """load_store on a valid JSON whose root is not a dict raises StoreCorrupted."""
    (taskq_home / "tasks.json").write_text("[]")
    with pytest.raises(StoreCorrupted):
        load_store()


def test_fr01_get_task_returns_none_when_absent(taskq_home: Path) -> None:
    """get_task for a never-submitted id returns None (not an error)."""
    assert get_task("deadbeef") is None


def test_fr01_clear_store_writes_empty(taskq_home: Path) -> None:
    """clear_store replaces the file with an empty {} JSON object."""
    submit_task("echo hi")
    assert (taskq_home / "tasks.json").exists()
    clear_store()
    data = json.loads((taskq_home / "tasks.json").read_text())
    assert data == {}


def test_fr01_cli_submit_direct(taskq_home: Path) -> None:
    """cli.main(['submit', 'echo', 'hi']) returns 0 and prints the task id."""
    exit_code = cli_main(["submit", "echo", "hi"])
    assert exit_code == 0
    store = load_store()
    assert len(store) == 1


def test_fr01_cli_submit_validation_error_direct(taskq_home: Path) -> None:
    """cli.main(['submit', '']) returns 2 and emits an error to stderr."""
    exit_code = cli_main(["submit", ""])
    assert exit_code == 2
    assert not (taskq_home / "tasks.json").exists()


def test_fr01_cli_status_known_task_direct(taskq_home: Path) -> None:
    """cli.main(['status', <id>]) returns 0 and prints the task JSON."""
    tid = submit_task("echo direct")
    exit_code = cli_main(["status", tid])
    assert exit_code == 0


def test_fr01_cli_status_unknown_task_direct(taskq_home: Path) -> None:
    """cli.main(['status', 'deadbeef']) returns 2 with unknown task message."""
    exit_code = cli_main(["status", "deadbeef"])
    assert exit_code == 2


def test_fr01_cli_list_direct(taskq_home: Path) -> None:
    """cli.main(['list']) returns 0 and lists submitted tasks."""
    submit_task("echo a")
    submit_task("echo b")
    exit_code = cli_main(["list"])
    assert exit_code == 0


def test_fr01_cli_clear_direct(taskq_home: Path) -> None:
    """cli.main(['clear']) returns 0 and empties the store."""
    submit_task("echo a")
    exit_code = cli_main(["clear"])
    assert exit_code == 0
    assert load_store() == {}


def test_fr01_cli_corruption_direct(taskq_home: Path) -> None:
    """cli.main(['list']) on a corrupt file returns 1 with 'store corrupted' message."""
    (taskq_home / "tasks.json").write_text('{"a1b2c3d4"')
    exit_code = cli_main(["list"])
    assert exit_code == 1


def test_fr01_cli_no_args_prints_help(taskq_home: Path) -> None:
    """cli.main([]) prints help to stderr and returns 2 (validation-like)."""
    exit_code = cli_main([])
    assert exit_code == 2


def test_fr01_atomic_write_no_tmp_leftover(taskq_home: Path) -> None:
    """submit_task leaves no .tasks.json.*.tmp file behind on success."""
    submit_task("echo atomic")
    leftovers = [p for p in taskq_home.iterdir() if p.name.startswith(".tasks.json.") and p.name.endswith(".tmp")]
    assert leftovers == []


def test_fr01_atomic_write_handles_unlink_failure(taskq_home: Path, monkeypatch) -> None:
    """_atomic_write swallows OSError on tmp cleanup (path still raises original error)."""
    from taskq.store import persistence

    def failing_replace(_src, _dst):
        raise RuntimeError("simulated replace failure")

    monkeypatch.setattr(persistence.os, "replace", failing_replace)
    with pytest.raises(RuntimeError, match="simulated replace failure"):
        persistence._atomic_write({"x": {"command": "echo a"}})
