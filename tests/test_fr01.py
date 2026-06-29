"""TDD-RED failing tests for FR-01: 任務模型與持久化.

Source of truth: SPEC.md §3 FR-01 + 02-architecture/TEST_SPEC.md (v1.5.0)
SAD module contract: src/taskq/core/{validation,models}.py + src/taskq/io/store.py

These tests are EXPECTED to fail (ModuleNotFoundError at collection time,
exit code 2) because the source modules do not exist yet. This is the valid
RED state for TDD-RED.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

# GREEN TODO: src/taskq/core/validation.py must expose:
#   validate_command(cmd: str) -> tuple[bool, str]
#   (ok=True, error_msg="") iff command passes all three rules
#   (ok=False, error_msg=<non-empty>) iff any rule violated
from taskq.core.validation import validate_command

# GREEN TODO: src/taskq/core/models.py must expose:
#   Task (dataclass with fields: id:str, command:str, status:TaskStatus,
#         created_at:datetime, exit_code:int|None=None, stdout_tail:str="",
#         stderr_tail:str="", duration_ms:int|None=None, finished_at:datetime|None=None)
#   TaskStatus (enum whose member for "pending" has .value == "pending")
#   INJECTION_FORBIDDEN (frozenset containing {';', '|', '&', '$', '>', '<', '`'})
from taskq.core.models import INJECTION_FORBIDDEN, Task, TaskStatus

# GREEN TODO: src/taskq/io/store.py must expose:
#   StoreCorrupted (Exception subclass)
#   load_tasks(home: Path) -> dict[str, Task]
#   save_tasks_atomic(home: Path, tasks: dict[str, Task]) -> None
# Atomic-write contract: tmp file in same dir + os.replace(tmp, final).
# load_tasks must raise StoreCorrupted on json.JSONDecodeError (no silent rebuild).
from taskq.io.store import StoreCorrupted, load_tasks, save_tasks_atomic


# ---------------------------------------------------------------------------
# AC-FR-01-01 — non-empty / non-whitespace
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["", "   "])
def test_fr01_001_empty_command_rejected(cmd):
    """SPEC §3 FR-01 row 1: empty / whitespace command → reject (exit 2)."""
    ok, err = validate_command(cmd)
    assert ok is False, f"command {cmd!r} must be rejected"
    assert err, "rejection must include a non-empty stderr message"


# ---------------------------------------------------------------------------
# AC-FR-01-02 — length <= 1000 (inclusive upper bound)
# ---------------------------------------------------------------------------

def _cmd_of_length(n: int) -> str:
    # ASCII letters only — must NOT contain any INJECTION_FORBIDDEN char, so
    # this isolates the length rule from the injection rule.
    assert n <= 1001, "fixture helper only supports lengths <= 1001"
    return "a" * n


@pytest.mark.parametrize(
    "length,should_reject",
    [
        (1001, True),   # over_limit — rule says "> 1000" → reject
        (1000, False),  # at_limit  — 1000 is the INCLUSIVE upper bound → accept
    ],
)
def test_fr01_002_length_exceeds_1000_rejected(length, should_reject):
    """SPEC §3 FR-01 row 2: command length > 1000 → reject. 1000 is accepted."""
    cmd = _cmd_of_length(length)
    ok, err = validate_command(cmd)
    if should_reject:
        assert ok is False, f"length={length} must be rejected"
        assert err
    else:
        assert ok is True, f"length={length} (boundary) must be accepted, got err={err!r}"
        assert err == ""


# ---------------------------------------------------------------------------
# AC-FR-01-03 / NFR-02 — injection-character blacklist
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "inj_char",
    [";", "|", "&", "$", ">", "<", "`"],
)
def test_fr01_003_injection_chars_rejected(inj_char):
    """SPEC §3 FR-01 row 3 / NFR-02: any of ; | & $ > < ` in command → reject.

    Each of the 7 forbidden characters is a separate parametrize case — all
    share this function name per TEST_SPEC.md cases 5–11.
    """
    cmd = f"echo a{inj_char}b"
    # sanity: the fixture is well-formed per the rule under test
    assert inj_char in cmd

    ok, err = validate_command(cmd)
    assert ok is False, f"command containing {inj_char!r} must be rejected"
    assert err, "rejection must include a non-empty stderr message"

    # Cross-check: the canonical blacklist is declared once in models.py and
    # the validator must consult it (so adding a new forbidden char later
    # automatically updates coverage here).
    assert inj_char in INJECTION_FORBIDDEN, (
        f"{inj_char!r} must be present in INJECTION_FORBIDDEN for blacklist coverage"
    )


# ---------------------------------------------------------------------------
# AC-FR-01-04 — happy path: id is uuid4 hex[:8], status pending, fields set
# ---------------------------------------------------------------------------

def test_fr01_004_pending_fields_initialized(tmp_path: Path):
    """SPEC §3 FR-01 通過驗證: 8-hex uuid id, status=pending, command, created_at."""
    cmd = "echo hi"

    # 1. Validation accepts a benign command.
    ok, err = validate_command(cmd)
    assert ok and not err, f"valid command unexpectedly rejected: err={err!r}"

    # 2. Build the Task record per the submit flow (SAD §3.2):
    #      id = uuid4().hex[:8] ; status = pending ; command ; created_at = now
    task_id = uuid4().hex[:8]
    created_at = datetime.now(timezone.utc)
    task = Task(
        id=task_id,
        command=cmd,
        status=TaskStatus.PENDING,
        created_at=created_at,
    )

    # 3. Persist atomically.
    save_tasks_atomic(tmp_path, {task.id: task})

    # 4. Reload and verify every field promised by the AC.
    loaded = load_tasks(tmp_path)
    assert task_id in loaded, f"persisted task {task_id!r} missing after reload"

    persisted = loaded[task_id]
    assert persisted.id == task_id
    # id is 8-char hex (uuid4 prefix)
    assert len(persisted.id) == 8, f"id must be 8 chars, got {len(persisted.id)}"
    int(persisted.id, 16)  # parses as hex — raises ValueError if not

    # status is exactly "pending"
    assert persisted.status.value == "pending"

    # command and created_at round-tripped
    assert persisted.command == cmd
    assert persisted.created_at is not None


# ---------------------------------------------------------------------------
# AC-FR-01-05 — atomic write (tmp + os.replace) survives concurrent I/O
# ---------------------------------------------------------------------------

def test_fr01_005_atomic_write_survives_interrupt(tmp_path: Path):
    """SPEC §3 FR-01 通過驗證 + NFR-03: atomic write — readers never observe partial JSON.

    The implementation contract is `tmp + os.replace` (POSIX-atomic rename).
    Concurrent readers sampling tasks.json across many write iterations must
    never see a syntactically invalid JSON document. A naive `open + write`
    implementation will leak partial bytes between truncate and the next
    flush; this test catches that.
    """
    tasks_file = tmp_path / "tasks.json"

    # Pre-seed one task so the file exists before the race starts.
    seed = Task(
        id="00000000",
        command="echo seed",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    save_tasks_atomic(tmp_path, {seed.id: seed})
    assert tasks_file.exists()
    json.loads(tasks_file.read_text())  # baseline sanity

    iterations = 200
    concurrent_readers = 4
    stop = threading.Event()
    reader_errors: list[BaseException] = []

    def _reader_loop() -> None:
        while not stop.is_set():
            try:
                if tasks_file.exists():
                    txt = tasks_file.read_text()
                    if txt.strip():  # tolerate empty-string window after unlink
                        json.loads(txt)  # raises json.JSONDecodeError on partial bytes
            except BaseException as exc:  # noqa: BLE001 — capture-all is intentional
                reader_errors.append(exc)

    readers = [
        threading.Thread(target=_reader_loop, daemon=True)
        for _ in range(concurrent_readers)
    ]
    for r in readers:
        r.start()

    last_id = seed.id
    try:
        for i in range(iterations):
            tid = f"{i:08x}"  # always 8 hex chars
            t = Task(
                id=tid,
                command=f"echo iter {i}",
                status=TaskStatus.PENDING,
                created_at=datetime.now(timezone.utc),
            )
            save_tasks_atomic(tmp_path, {tid: t})
            last_id = tid
    finally:
        stop.set()
        for r in readers:
            r.join(timeout=2.0)

    # Atomicity invariant: no reader ever observed partial / corrupt JSON.
    assert not reader_errors, (
        f"atomic-write contract violated — readers observed invalid JSON: "
        f"{reader_errors[:3]!r}"
    )

    # Post-condition: the store still parses and holds the last written task.
    final = load_tasks(tmp_path)
    assert final[last_id].command == f"echo iter {iterations - 1}"


# ---------------------------------------------------------------------------
# AC-FR-01-06 — corrupt store detection (no silent rebuild)
# ---------------------------------------------------------------------------

def test_fr01_006_corrupt_store_exit1(tmp_path: Path):
    """SPEC §3 FR-01 通過驗證: tasks.json containing invalid JSON →
    StoreCorrupted (cli maps this to exit 1 + stderr 'store corrupted').

    The store layer's contract is to raise StoreCorrupted, NOT to silently
    overwrite with `{}` or `[]`. The CLI exit-code mapping is FR-03 territory
    and is exercised there.
    """
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text("{not valid json")

    with pytest.raises(StoreCorrupted):
        load_tasks(tmp_path)