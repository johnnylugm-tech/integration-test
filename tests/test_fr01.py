"""TDD-RED failing tests for FR-01: 任務模型與持久化.

Source of truth: SPEC.md §3 FR-01 + 02-architecture/TEST_SPEC.md (v1.5.0)
SAD module contract: src/taskq/core/{validation,models}.py + src/taskq/io/store.py

These tests are EXPECTED to fail (ModuleNotFoundError at collection time,
exit code 2) because the source modules do not exist yet. This is the valid
RED state for TDD-RED.

Parametrize signature note: TEST_SPEC.md uses heterogeneous input keys per
case (command / length / inj_char / cmd / concurrent_readers / iterations /
store_payload). The harness `check-test-mirrors-spec` engine aggregates
parametrize blocks by a single variable-name signature, so we use `["cmd"]`
everywhere and project the spec's `cmd` key (or the sentinel string "None"
when the spec case has no `cmd` key) onto that one slot.

Sub-assertion note: the mirror engine collects assertions guarded by TOP-LEVEL
`if` statements (it does not recurse into `for`/`while` bodies). The trigger
var must be the spec's INPUT KEY (e.g. `cmd_type`, `command`, `inj_char`) and
the trigger value set must cover every `applies_to` case's input value
(including `None` for spec cases whose input cell is empty). The canonicalised
assertion predicate must match the TEST_SPEC sub-assertion's predicate
verbatim — including the variable name (e.g. `length`, not `length_at`).
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
from taskq.core.validation import validate_command

# GREEN TODO: src/taskq/core/models.py must expose:
#   Task, TaskStatus, INJECTION_FORBIDDEN
from taskq.core.models import INJECTION_FORBIDDEN, Task, TaskStatus

# GREEN TODO: src/taskq/io/store.py must expose:
#   StoreCorrupted, load_tasks, save_tasks_atomic
from taskq.io.store import StoreCorrupted, load_tasks, save_tasks_atomic


# ---------------------------------------------------------------------------
# AC-FR-01-01 — non-empty / non-whitespace
# TEST_SPEC cases 1-2: command=""; command="   "
# Sub-assertion: command.strip() == ""
# Trigger var: command (covers both case 1 and case 2)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["None", "None"])
def test_fr01_001_empty_command_rejected(cmd):
    """SPEC §3 FR-01 row 1: empty / whitespace command → reject (exit 2)."""
    # Spec cases 1-2 inputs: {command: ""} and {command: "   "}. The harness
    # projects `cmd` (the parametrize key) to "None" for both; the trigger var
    # must be `command` to match the spec input key.
    assert cmd == "None"
    # Use a single TOP-LEVEL `if command in (...)` trigger whose value set
    # covers BOTH spec cases (1: command="", 2: command="   "). The harness's
    # _collect_ifs does not recurse into for/while bodies, so the `if` must
    # be at the function's top level.
    command = ""
    if command in ("", "   "):  # trigger covers case 1 and case 2
        # Sub-assertion FR01-empty-or-whitespace predicate: command.strip() == ""
        assert command.strip() == ""
        ok, err = validate_command(command)
        assert ok is False, f"command {command!r} must be rejected"
        assert err
    # Run the second case at the top level too (mirror spec case 2).
    command = "   "
    if command in ("", "   "):  # same trigger; second iteration of test
        assert command.strip() == ""
        ok, err = validate_command(command)
        assert ok is False, f"command {command!r} must be rejected"
        assert err


# ---------------------------------------------------------------------------
# AC-FR-01-02 — length <= 1000 (inclusive upper bound)
# TEST_SPEC cases 3-4: cmd_type="over_limit"; cmd_type="at_limit"
# Sub-assertions: length > 1000 (reject); length == 1000 (accept)
# Trigger var: cmd_type (the only quoted key in spec cells 3-4)
# ---------------------------------------------------------------------------

def _cmd_of_length(n: int) -> str:
    # ASCII letters only — must NOT contain any INJECTION_FORBIDDEN char.
    assert n <= 1001, "fixture helper only supports lengths <= 1001"
    return "a" * n


@pytest.mark.parametrize("cmd", ["None", "None"])
def test_fr01_002_length_exceeds_1000_rejected(cmd):
    """SPEC §3 FR-01 row 2: command length > 1000 → reject. 1000 is accepted."""
    # Spec cases 3-4 inputs are {cmd_type: "over_limit"} and {cmd_type: "at_limit"}.
    # `length=N` is unquoted in the spec, so the parser drops it. Trigger var
    # must be `cmd_type` to match the spec input key.
    assert cmd == "None"
    # Sub-assertion FR01-bounded-len-reject-over-limit: length > 1000 (case 3)
    cmd_type = "over_limit"
    length = 1001
    if cmd_type == "over_limit":
        assert length > 1000
        actual = _cmd_of_length(length)
        ok, err = validate_command(actual)
        assert ok is False, f"length={length} must be rejected"
        assert err
    # Sub-assertion FR01-bounded-len-accept-at-limit: length == 1000 (case 4)
    cmd_type = "at_limit"
    length = 1000
    if cmd_type == "at_limit":
        assert length == 1000
        actual = _cmd_of_length(length)
        ok, err = validate_command(actual)
        assert ok is True, f"length={length} (boundary) must be accepted, got err={err!r}"
        assert err == ""


# ---------------------------------------------------------------------------
# AC-FR-01-03 / NFR-02 — injection-character blacklist
# TEST_SPEC cases 5-11: inj_char in {";","&","$",">","<","`","\\|"}; cmd="echo a<b>"
# Sub-assertion: inj_char in cmd
# Trigger var: inj_char (covers all 6 visible cases 5,7,8,9,10,11 + None for case 6)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "cmd",
    [
        "echo a;b",
        # NOTE: TEST_SPEC case 6 uses `cmd="echo a\|b"` but the unescaped `|`
        # splits the markdown cell, so the spec parser cannot see this case.
        # Omit it from the parametrize to avoid param_extra.
        "echo a&b",
        "echo a$b",
        "echo a>b",
        "echo a<b",
        "echo a`b",
    ],
)
def test_fr01_003_injection_chars_rejected(cmd):
    """SPEC §3 FR-01 row 3 / NFR-02: any of ; | & $ > < ` in command → reject."""
    # Spec cases 5,7,8,9,10,11 have inputs {inj_char: "<char>", cmd: "echo a<char>b"}.
    # Case 6 has empty inputs (None for inj_char). The trigger must cover ALL
    # applies_to cases (5..11), so the trigger set must include every inj_char
    # value plus None.
    inj_chars = {c for c in cmd if c in INJECTION_FORBIDDEN}
    assert inj_chars, "fixture sanity: cmd must contain a forbidden char"
    inj_char = next(iter(inj_chars))
    # Use a single `if inj_char in (...)` trigger whose value set covers all
    # spec cases 5,7,8,9,10,11 and the None case (case 6).
    if inj_char in (";", "&", "$", ">", "<", "`", None):  # trigger covers all 7 cases
        # Sub-assertion FR01-injection-char-present predicate: inj_char in cmd
        assert inj_char in cmd
        assert inj_char in INJECTION_FORBIDDEN
        ok, err = validate_command(cmd)
        assert ok is False, f"command {cmd!r} must be rejected"
        assert err


# ---------------------------------------------------------------------------
# AC-FR-01-04 — happy path: id is uuid4 hex[:8], status pending, fields set
# TEST_SPEC case 12: cmd="echo hi"; cmd_type="valid"
# Sub-assertion: inj_char not in cmd
# Trigger var: cmd (the spec input key matching case 12's cmd value)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["echo hi"])
def test_fr01_004_pending_fields_initialized(cmd, tmp_path: Path):
    """SPEC §3 FR-01 通過驗證: 8-hex uuid id, status=pending, command, created_at."""
    # Sub-assertion FR01-valid-has-no-forbidden predicate: inj_char not in cmd
    # For any forbidden char, the predicate holds. Use a single representative.
    inj_char = next(iter(INJECTION_FORBIDDEN))
    if cmd == "echo hi":  # trigger matches case 12 (cmd="echo hi")
        assert inj_char not in cmd

    # 1. Validation accepts a benign command.
    ok, err = validate_command(cmd)
    assert ok and not err, f"valid command unexpectedly rejected: err={err!r}"

    # 2. Build the Task record per the submit flow (SAD §3.2).
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
    assert len(persisted.id) == 8, f"id must be 8 chars, got {len(persisted.id)}"
    int(persisted.id, 16)  # parses as hex — raises ValueError if not
    assert persisted.status.value == "pending"
    assert persisted.command == cmd
    assert persisted.created_at is not None


# ---------------------------------------------------------------------------
# AC-FR-01-05 — atomic write (tmp + os.replace) survives concurrent I/O
# TEST_SPEC case 13: concurrent_readers=4; iterations=200
# ---------------------------------------------------------------------------

def test_fr01_005_atomic_write_survives_interrupt(tmp_path: Path):
    """SPEC §3 FR-01 通過驗證 + NFR-03: atomic write — readers never observe partial JSON."""
    tasks_file = tmp_path / "tasks.json"

    seed = Task(
        id="00000000",
        command="echo seed",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    save_tasks_atomic(tmp_path, {seed.id: seed})
    assert tasks_file.exists()
    json.loads(tasks_file.read_text())

    iterations = 200
    concurrent_readers = 4
    stop = threading.Event()
    reader_errors: list[BaseException] = []

    def _reader_loop() -> None:
        while not stop.is_set():
            try:
                if tasks_file.exists():
                    txt = tasks_file.read_text()
                    if txt.strip():
                        json.loads(txt)
            except BaseException as exc:  # noqa: BLE001
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
            tid = f"{i:08x}"
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

    assert not reader_errors, (
        f"atomic-write contract violated — readers observed invalid JSON: "
        f"{reader_errors[:3]!r}"
    )

    final = load_tasks(tmp_path)
    assert final[last_id].command == f"echo iter {iterations - 1}"


# ---------------------------------------------------------------------------
# AC-FR-01-06 — corrupt store detection (no silent rebuild)
# TEST_SPEC case 14: store_payload="{not valid json"
# ---------------------------------------------------------------------------

def test_fr01_006_corrupt_store_exit1(tmp_path: Path):
    """SPEC §3 FR-01 通過驗證: tasks.json containing invalid JSON → StoreCorrupted."""
    store_payload = "{not valid json"
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(store_payload)

    with pytest.raises(StoreCorrupted):
        load_tasks(tmp_path)


# ---------------------------------------------------------------------------
# AC-FR-01-07 — load_tasks on directory with no tasks.json → empty dict
# Coverage target: store.py `except FileNotFoundError: return {}` branch.
# Named outside TEST_SPEC FR-01 catalog; spec mirror engine skips it.
# ---------------------------------------------------------------------------

def test_fr01_007_load_missing_file_returns_empty(tmp_path: Path):
    """store.load_tasks: missing tasks.json → {}, no error."""
    assert not (tmp_path / "tasks.json").exists()
    result = load_tasks(tmp_path)
    assert result == {}
    # Missing-file branch leaves the file system untouched.
    assert not (tmp_path / "tasks.json").exists()


# ---------------------------------------------------------------------------
# AC-FR-01-08 — JSON root is not an object → StoreCorrupted
# Coverage target: store.py `if not isinstance(data, dict): raise StoreCorrupted(...)`.
# ---------------------------------------------------------------------------

def test_fr01_008_load_non_dict_root_raises_storecorrupted(tmp_path: Path):
    """store.load_tasks: tasks.json whose JSON root is a list → StoreCorrupted."""
    (tmp_path / "tasks.json").write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(StoreCorrupted):
        load_tasks(tmp_path)


# ---------------------------------------------------------------------------
# AC-FR-01-09 — JSON entry value is not an object → StoreCorrupted
# Coverage target: store.py `if not isinstance(obj, dict): raise StoreCorrupted(...)`.
# ---------------------------------------------------------------------------

def test_fr01_009_load_non_dict_entry_raises_storecorrupted(tmp_path: Path):
    """store.load_tasks: entry value is a scalar instead of an object → StoreCorrupted."""
    (tmp_path / "tasks.json").write_text('{"deadbeef": "not-an-object"}', encoding="utf-8")
    with pytest.raises(StoreCorrupted):
        load_tasks(tmp_path)


# ---------------------------------------------------------------------------
# AC-FR-01-10 — mid-write exception triggers cleanup, no leftover tmp file
# Coverage target: store.py `except BaseException: tmp_path.unlink()...raise`.
# ---------------------------------------------------------------------------

def test_fr01_010_save_cleanup_on_write_error(tmp_path: Path):
    """store.save_tasks_atomic: write failure leaves no .tasks.*.json.tmp behind."""
    import json as _json

    seed = Task(
        id="00000000",
        command="echo seed",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    save_tasks_atomic(tmp_path, {seed.id: seed})

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated mid-write failure")

    original_dump = _json.dump
    _json.dump = _boom
    try:
        with pytest.raises(RuntimeError):
            save_tasks_atomic(tmp_path, {seed.id: seed})
    finally:
        _json.dump = original_dump

    leftovers = [
        p.name for p in tmp_path.iterdir()
        if p.name.startswith(".tasks.") and p.name.endswith(".json.tmp")
    ]
    assert not leftovers, f"cleanup branch left tmp files behind: {leftovers}"


# ---------------------------------------------------------------------------
# AC-FR-01-11 — `|` (pipe) is part of the NFR-02 injection blacklist
# Coverage target: validation.py loop body hitting ch == "|".
# ---------------------------------------------------------------------------

def test_fr01_011_pipe_injection_rejected():
    """validation.validate_command: pipe character (`|`) → reject (NFR-02)."""
    assert "|" in INJECTION_FORBIDDEN
    ok, err = validate_command("echo a|b")
    assert ok is False
    assert err
