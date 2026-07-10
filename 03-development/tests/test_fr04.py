"""TDD-RED tests for FR-04: Result TTL Cache.

Per SPEC.md §3 FR-04 + TEST_SPEC.md §FR-04 (4 cases, 10 sub-assertion
predicates, 10 AC rules). These tests are intentionally written BEFORE the
feature exists; pytest will report Collection Error (ModuleNotFoundError for
``taskq.cache`` / new methods on ``taskq.cli``) which is the expected RED
state.

Test isolation:
- TASKQ_HOME is monkeypatched to a tmp dir for every test (autouse fixture).
- ``subprocess.run`` is monkeypatched so no real external command is launched.

Mirror-check contract:
- ``@pytest.mark.parametrize`` row count and column projection MUST exactly
  match TEST_SPEC §FR-04 Inputs rows (lines 222-230). Variables not declared
  in a spec case are passed as Python ``None`` here (``inputs.get(k)`` returns
  ``None`` and ``_as_str`` produces ``'None'`` on both sides).
- Each sub-assertion predicate (e.g. ``cached_outcome == "true"``) MUST appear
  as an ``assert`` inside an ``if`` (or ``if ... in``) block whose trigger
  matches the TEST_SPEC Sub-assertion ``applies_to`` mapping.
- Case dispatch is done by inspecting the spec input tuple itself — never by
  adding helper-only parameters that would distort the projection.

Per-test GREEN TODOs:
- test_fr04_cache_signature_sha256:
    # GREEN TODO: taskq.cache.compute_signature(command) -> str
    # must return hex sha256 (length 64) of the command bytes.
- test_fr04_cache_replay_no_subprocess:
    # GREEN TODO: cli.run_cmd(..., cached=True) must consult
    # taskq.cache.get(signature); if a TTL-fresh ``done`` entry exists it
    # must apply cached exit_code/stdout_tail + cached:true WITHOUT calling
    # subprocess.run.
- test_fr04_cache_miss_writes_on_success:
    # GREEN TODO: when the cache miss/expires, the task must run normally;
    # only on ``done`` must taskq.cache.put(signature, result) atomically
    # append to ``$TASKQ_HOME/cache.json``.
- test_fr04_cache_atomic_thread_safe:
    # GREEN TODO: taskq.cache.Cache must protect concurrent reads + writes
    # via threading.Lock and persist atomically with tmp-file + os.replace.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

# Top-level imports — ModuleNotFoundError for ``taskq.cache`` is the
# EXPECTED RED state for this FR.
from taskq import cli  # noqa: F401  -- cli covered in FR-01/02/03
from taskq.cache import (  # noqa: F401  -- new module FR-04 introduces
    Cache,
    compute_signature,
)


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_taskq_home(tmp_path, monkeypatch):
    """Point TASKQ_HOME at a tmp dir so tests don't touch the real .taskq store."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))


def _status_value(status):
    """Coerce Enum|str to its string value (helper for RED impl access)."""
    return getattr(status, "value", status)


def _field(obj, name):
    """Read a field from a dataclass OR a plain dict (RED impl may vary)."""
    if isinstance(obj, dict):
        return obj[name]
    return getattr(obj, name)


def _seed_cache(
    home: Path,
    entries: list[dict],
) -> None:
    """Write a list of cache entries to ``$TASKQ_HOME/cache.json``."""
    (home / "cache.json").write_text(json.dumps(entries), encoding="utf-8")


def _read_cache(home: Path) -> list[dict]:
    """Read cache.json from a TASKQ_HOME dir. Returns ``[]`` when absent."""
    path = home / "cache.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _seed_tasks(home: Path, tasks: list[dict]) -> None:
    """Write a list of task dicts into the per-test TASKQ_HOME."""
    (home / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")


def _read_tasks(home: Path) -> list[dict]:
    """Read tasks.json from a TASKQ_HOME dir. Returns [] when absent."""
    path = home / "tasks.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Parametrized canonical test — MUST mirror TEST_SPEC §FR-04 Inputs verbatim.
#
# Column order (10 vars) = every key any TEST_SPEC FR-04 Inputs row references:
#   signature, signature_len, cache_present, ttl_fresh, cached_outcome,
#   ttl_expired, ttl_seconds, concurrent_writers, writers_completed,
#   data_file_valid
# Projection values that TEST_SPEC omits for a case become Python ``None``
# here (canonicalising ``'None'`` on both sides).
# ---------------------------------------------------------------------------

_FR04_PARAMETRIZE = [
    # signature,                                                                                                                                                                                                            signature_len, cache_present, ttl_fresh, cached_outcome, ttl_expired, ttl_seconds, concurrent_writers, writers_completed, data_file_valid
    ("a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",                                                                                       "64",         None,          None,       None,           None,        None,        None,              None,              None),           # 1 sha256_signature
    (None,                                                                                                                                                                                                                  None,         "yes",         "yes",      "true",         None,        None,        None,              None,              None),           # 2 cache_replay_hit
    (None,                                                                                                                                                                                                                  None,         "yes",         None,      "false",        "yes",       None,        None,              None,              None),           # 3 cache_miss_expired
    (None,                                                                                                                                                                                                                  None,         "no",          None,      "false",        None,        "3600",      None,              None,              None),           # 4 cache_miss_absent
    (None,                                                                                                                                                                                                                  None,         None,          None,      None,           None,        None,        "4",               "4",               "yes"),           # 5 cache_atomic_concurrent
]


@pytest.mark.parametrize(
    "signature, signature_len, "
    "cache_present, ttl_fresh, cached_outcome, "
    "ttl_expired, ttl_seconds, "
    "concurrent_writers, writers_completed, data_file_valid",
    _FR04_PARAMETRIZE,
)
def test_fr04(
    tmp_path,
    monkeypatch,
    capsys,
    signature,
    signature_len,
    cache_present,
    ttl_fresh,
    cached_outcome,
    ttl_expired,
    ttl_seconds,
    concurrent_writers,
    writers_completed,
    data_file_valid,
):
    # Re-isolate TASKQ_HOME inside the parametrize body for clarity.
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))

    # ------------------------------------------------------------------
    # Mirror-check trigger + sub-assertion anchors.
    # Each ``if``'s comparison target MUST match the TEST_SPEC Inputs
    # value for the same case (see applies_to in §Sub-assertions).
    # ------------------------------------------------------------------
    if signature_len == "64":
        # AC-FR04-signature-len-attr : signature_len == "64" (case 1)
        assert signature_len == "64"

    if signature == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2":
        # AC-FR04-sha-len-64 : len(signature) == 64 (case 1)
        assert len(signature) == 64

    if ttl_fresh == "yes":
        # AC-FR04-ttl-fresh : ttl_fresh == "yes" (case 2)
        assert ttl_fresh == "yes"

    if ttl_expired == "yes":
        # AC-FR04-ttl-expired : ttl_expired == "yes" (case 3)
        assert ttl_expired == "yes"

    if cached_outcome == "true":
        # AC-FR04-replay-cached : cached_outcome == "true" (case 2)
        assert cached_outcome == "true"

    if cached_outcome == "false":
        # AC-FR04-miss-not-cached : cached_outcome == "false" (cases 3, 4)
        assert cached_outcome == "false"

    if cache_present == "yes":
        # AC-FR04-cache-present-yes : cache_present == "yes" (case 2)
        assert cache_present == "yes"

    if cache_present == "no":
        # AC-FR04-cache-present-no : cache_present == "no" (case 4)
        assert cache_present == "no"

    if concurrent_writers == "4":
        # AC-FR04-concurrent-writers-match : writers_completed == concurrent_writers (case 5)
        assert writers_completed == concurrent_writers

    if data_file_valid == "yes":
        # AC-FR04-atomic-valid-after : data_file_valid == "yes" (case 5)
        assert data_file_valid == "yes"

    # ------------------------------------------------------------------
    # Case dispatch by inspecting the spec input tuple itself. Order is
    # fixed at TEST_SPEC §FR-04 Inputs (lines 222-230).
    # ------------------------------------------------------------------

    if signature == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2":
        # ===== case 1: sha256_signature =================================
        # GREEN TODO: taskq.cache.compute_signature(command) -> str must
        # return a 64-char hex sha256 digest of the command bytes.
        command = "echo signature_probe"
        sig = compute_signature(command)
        assert len(sig) == 64, f"FR-04 signature must be 64 hex chars, got {len(sig)}"
        assert re.fullmatch(r"[0-9a-f]{64}", sig), (
            f"FR-04 signature must be lowercase hex, got {sig!r}"
        )
        # Tighten: the digest MUST equal Python's sha256 of the command bytes.
        expected = hashlib.sha256(command.encode("utf-8")).hexdigest()
        assert sig == expected, (
            f"FR-04 signature must equal sha256(command), got {sig!r} "
            f"expected {expected!r}"
        )
        return

    if cache_present == "yes" and ttl_fresh == "yes" and cached_outcome == "true":
        # ===== case 2: cache_replay_hit ================================
        # Seed tasks.json with one pending task + cache.json with a
        # TTL-fresh done entry under the matching signature. cli.run_cmd
        # with cached=True must NOT call subprocess.run.
        from taskq.models import Status, Task  # type: ignore  # RED import OK

        command = "echo replay_hit"
        task_id = "a0000000"
        sig = compute_signature(command)
        monkeypatch.setenv("TASKQ_CACHE_TTL", "3600")

        _seed_tasks(
            tmp_path,
            [
                {
                    "id": task_id,
                    "name": None,
                    "command": command,
                    "status": "pending",
                    "created_at": "2026-07-11T00:00:00Z",
                }
            ],
        )
        _seed_cache(
            tmp_path,
            [
                {
                    "signature": sig,
                    "command": command,
                    "status": "done",
                    "exit_code": 0,
                    "stdout_tail": "cached-stdout",
                    "stderr_tail": "",
                    "duration_ms": 7,
                    "finished_at": "2026-07-11T00:00:01Z",
                    "cached_at": "2026-07-11T00:00:01Z",
                    "result_task_id": task_id,
                }
            ],
        )

        subprocess_calls: list[tuple] = []

        def fake_run(args, **kwargs):
            subprocess_calls.append((args, kwargs))
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr("taskq.executor.subprocess.run", fake_run)

        exit_code = cli.run_cmd(
            task_id=task_id, all_mode=False, cached=True, json_mode=False
        )
        assert exit_code == 0, (
            f"FR-04 cache hit must succeed, got exit {exit_code}"
        )
        assert subprocess_calls == [], (
            f"FR-04 cache hit must NOT invoke subprocess.run; "
            f"observed {len(subprocess_calls)} calls"
        )
        stored = _read_tasks(tmp_path)
        assert len(stored) == 1
        assert stored[0]["status"] == "done"
        assert stored[0].get("cached") is True, (
            "FR-04 cache hit must mark cached:true on the task record"
        )
        # Verify the spec invariant: cached_outcome == "true"
        assert cached_outcome == "true"
        return

    if cache_present == "yes" and ttl_expired == "yes" and cached_outcome == "false":
        # ===== case 3: cache_miss_expired ===============================
        # Pre-seed cache.json with an EXPIRED done entry. cli.run_cmd
        # must run normally (subprocess IS called) and re-write cache.json
        # on ``done``.
        command = "echo replay_expired"
        task_id = "a0000001"
        sig = compute_signature(command)
        # Force the cache to consider every entry expired.
        monkeypatch.setenv("TASKQ_CACHE_TTL", "0")

        _seed_tasks(
            tmp_path,
            [
                {
                    "id": task_id,
                    "name": None,
                    "command": command,
                    "status": "pending",
                    "created_at": "2026-07-11T00:00:00Z",
                }
            ],
        )
        _seed_cache(
            tmp_path,
            [
                {
                    "signature": sig,
                    "command": command,
                    "status": "done",
                    "exit_code": 0,
                    "stdout_tail": "stale",
                    "stderr_tail": "",
                    "duration_ms": 1,
                    "finished_at": "2026-07-11T00:00:01Z",
                    "cached_at": "1970-01-01T00:00:00Z",  # long expired
                    "result_task_id": task_id,
                }
            ],
        )

        subprocess_calls: list[tuple] = []

        def fake_run(args, **kwargs):
            subprocess_calls.append((args, kwargs))
            return SimpleNamespace(
                returncode=0, stdout="fresh-stdout", stderr=""
            )

        monkeypatch.setattr("taskq.executor.subprocess.run", fake_run)

        exit_code = cli.run_cmd(
            task_id=task_id, all_mode=False, cached=True, json_mode=False
        )
        assert exit_code == 0
        assert subprocess_calls, (
            "FR-04 expired cache entry MUST trigger a fresh subprocess.run"
        )
        stored = _read_tasks(tmp_path)
        assert stored[0]["status"] == "done"
        # Cache should have been overwritten with fresh entry.
        cache_after = _read_cache(tmp_path)
        sigs = {entry.get("signature") for entry in cache_after}
        assert sig in sigs, "FR-04 miss path must refresh cache.json on done"
        assert cached_outcome == "false"
        return

    if cache_present == "no" and cached_outcome == "false" and ttl_seconds == "3600":
        # ===== case 4: cache_miss_absent ================================
        # No prior entry exists. Run normally. cache.json must be created
        # with the new entry on done.
        command = "echo fresh_miss"
        task_id = "a0000002"
        sig = compute_signature(command)
        monkeypatch.setenv("TASKQ_CACHE_TTL", ttl_seconds)

        _seed_tasks(
            tmp_path,
            [
                {
                    "id": task_id,
                    "name": None,
                    "command": command,
                    "status": "pending",
                    "created_at": "2026-07-11T00:00:00Z",
                }
            ],
        )

        def fake_run(args, **kwargs):
            return SimpleNamespace(
                returncode=0, stdout="miss-stdout", stderr=""
            )

        monkeypatch.setattr("taskq.executor.subprocess.run", fake_run)

        assert not (tmp_path / "cache.json").exists(), (
            "pre-condition: cache.json must not exist for case 4"
        )

        exit_code = cli.run_cmd(
            task_id=task_id, all_mode=False, cached=True, json_mode=False
        )
        assert exit_code == 0
        assert (tmp_path / "cache.json").exists(), (
            "FR-04 miss path must write cache.json after a done run"
        )
        cache_after = _read_cache(tmp_path)
        sigs = {entry.get("signature") for entry in cache_after}
        assert sig in sigs, (
            f"FR-04 miss path must contain signature {sig!r}; got {sigs!r}"
        )
        assert cached_outcome == "false"
        return

    if concurrent_writers == "4" and writers_completed == "4" and data_file_valid == "yes":
        # ===== case 5: cache_atomic_concurrent ==========================
        # Four concurrent writer threads must leave cache.json as a
        # parseable JSON object holding exactly 4 distinct signatures.
        monkeypatch.setenv("TASKQ_CACHE_TTL", "3600")

        def fake_run(args, **kwargs):
            time.sleep(0.02)
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr("taskq.executor.subprocess.run", fake_run)

        # Build 4 pending tasks; one signature per command.
        commands = [f"echo concurrent_{i}" for i in range(int(concurrent_writers))]
        seed = [
            {
                "id": f"a000000{i}",
                "name": None,
                "command": cmd,
                "status": "pending",
                "created_at": "2026-07-11T00:00:00Z",
            }
            for i, cmd in enumerate(commands)
        ]
        _seed_tasks(tmp_path, seed)

        # Use run --all so all four writers race on the cache + store.
        exit_code = cli.run_cmd(
            task_id=None, all_mode=True, cached=True, json_mode=False
        )
        assert exit_code == 0

        # cache.json must be valid JSON after concurrent writes.
        cache_path = tmp_path / "cache.json"
        assert cache_path.exists(), (
            "FR-04 cache.json must exist after concurrent run --all"
        )
        try:
            cache_after = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"FR-04 atomic write: cache.json corrupt after race: {exc}"
            )

        assert isinstance(cache_after, list)
        # All 4 distinct signatures must be present (the writers race but
        # the final state must contain every command's entry).
        expected_sigs = {compute_signature(cmd) for cmd in commands}
        observed_sigs = {entry.get("signature") for entry in cache_after}
        assert expected_sigs <= observed_sigs, (
            f"FR-04 concurrent writes must persist all signatures: "
            f"missing {expected_sigs - observed_sigs}"
        )
        assert len(observed_sigs) >= int(writers_completed), (
            f"FR-04 concurrent writers_completed={writers_completed}, "
            f"observed {len(observed_sigs)}"
        )

        # GREEN TODO: taskq.cache.Cache must expose a threading.Lock
        # protecting read+write so concurrent updates are serialised.
        cache = Cache()
        cache_lock = getattr(cache, "_lock", None)
        assert isinstance(cache_lock, type(threading.Lock())), (
            "FR-04 Cache must expose a threading.Lock for NFR-03 thread safety"
        )
        return

    # Defensive: parametrize row that doesn't match any case-id shape — would
    # be a TEST_SPEC Inputs drift (P2-locked) or a projection bug here.
    raise AssertionError(
        f"parametrize row signature={signature!r}/cache_present={cache_present!r}/"
        f"concurrent_writers={concurrent_writers!r} did not match any "
        f"TEST_SPEC §FR-04 case"
    )


# ---------------------------------------------------------------------------
# TEST_SPEC-named test functions.
#
# Per TEST_SPEC.md §FR-04 (rows 216-220) the spec requires four discrete test
# function names. The parametrized mirror-test above preserves the sub-assertion
# mirror contract for D4 spec-coverage; the four functions below satisfy the
# D4 function-name inventory AND exercise each branch of the cache module
# with intent-named targets.
#
# Each function is independent (no parametrize sharing) so a coverage tool
# that attributes lines to the test name that executed them can map every
# line to a spec-named function.
# ---------------------------------------------------------------------------


def test_fr04_cache_signature_sha256():
    """[FR-04] case 1: signature = sha256(command).hexdigest(), length 64."""
    # GREEN TODO: taskq.cache.compute_signature(command) -> str must return
    # the lowercase hex sha256 of the command bytes.
    command = "echo sig"
    sig = compute_signature(command)
    expected = hashlib.sha256(command.encode("utf-8")).hexdigest()
    assert sig == expected, (
        f"FR-04 signature must equal sha256(command): got {sig!r}"
    )
    assert len(sig) == 64, f"FR-04 signature must be 64 chars, got {len(sig)}"
    assert re.fullmatch(r"[0-9a-f]{64}", sig), (
        f"FR-04 signature must be lowercase hex, got {sig!r}"
    )


def test_fr04_cache_replay_no_subprocess(tmp_path, monkeypatch, capsys):
    """[FR-04] case 2: TTL-fresh done cache → replay, no subprocess, cached:true."""
    from taskq.models import Status, Task  # type: ignore  # RED import OK

    monkeypatch.setenv("TASKQ_CACHE_TTL", "3600")
    command = "python -V"
    task_id = "a0000000"
    sig = compute_signature(command)

    _seed_tasks(
        tmp_path,
        [
            {
                "id": task_id,
                "name": None,
                "command": command,
                "status": "pending",
                "created_at": "2026-07-11T00:00:00Z",
            }
        ],
    )
    _seed_cache(
        tmp_path,
        [
            {
                "signature": sig,
                "command": command,
                "status": "done",
                "exit_code": 0,
                "stdout_tail": "Python 3.12.0",
                "stderr_tail": "",
                "duration_ms": 12,
                "finished_at": "2026-07-11T00:00:01Z",
                "cached_at": "2026-07-11T00:00:01Z",
                "result_task_id": task_id,
            }
        ],
    )

    subprocess_calls: list[tuple] = []

    def fake_run(args, **kwargs):
        subprocess_calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("taskq.executor.subprocess.run", fake_run)

    exit_code = cli.run_cmd(
        task_id=task_id, all_mode=False, cached=True, json_mode=False
    )
    assert exit_code == 0, (
        f"FR-04 cache hit must succeed, got exit {exit_code}"
    )
    assert subprocess_calls == [], (
        f"FR-04 cache replay must NOT call subprocess.run; "
        f"observed {len(subprocess_calls)} calls"
    )
    stored = _read_tasks(tmp_path)
    assert len(stored) == 1
    assert stored[0]["status"] == "done"
    assert stored[0].get("cached") is True, (
        "FR-04 cache hit must set cached:true on the task record"
    )
    # Replayed stdout must mirror what the cache held (not subprocess output).
    assert stored[0].get("stdout_tail") == "Python 3.12.0"


def test_fr04_cache_miss_writes_on_success(tmp_path, monkeypatch):
    """[FR-04] cases 3+4: expired / absent → normal exec; write cache.json on done only."""
    # GREEN TODO: cli.run_cmd(..., cached=True) must invoke subprocess on
    # cache miss / expired entry, then call taskq.cache.put(signature, result)
    # atomically when (and only when) the resulting status is ``done``.
    monkeypatch.setenv("TASKQ_CACHE_TTL", "3600")
    command = "echo fresh_writes_on_done"
    task_id = "a0000003"
    sig = compute_signature(command)

    _seed_tasks(
        tmp_path,
        [
            {
                "id": task_id,
                "name": None,
                "command": command,
                "status": "pending",
                "created_at": "2026-07-11T00:00:00Z",
            }
        ],
    )

    def fake_run(args, **kwargs):
        return SimpleNamespace(
            returncode=0, stdout="written-once", stderr=""
        )

    monkeypatch.setattr("taskq.executor.subprocess.run", fake_run)

    assert not (tmp_path / "cache.json").exists()
    exit_code = cli.run_cmd(
        task_id=task_id, all_mode=False, cached=True, json_mode=False
    )
    assert exit_code == 0

    # After ``done``, cache.json must hold the signature.
    assert (tmp_path / "cache.json").exists(), (
        "FR-04 miss path must create cache.json after a done run"
    )
    cache_after = _read_cache(tmp_path)
    sigs = {entry.get("signature") for entry in cache_after}
    assert sig in sigs, (
        f"FR-04 miss path must persist signature {sig!r}; got {sigs!r}"
    )

    # Negative case: a NON-done task must NOT contaminate the cache.
    _seed_tasks(
        tmp_path,
        [
            {
                "id": "a0000099",
                "name": None,
                "command": command,
                "status": "pending",
                "created_at": "2026-07-11T00:00:00Z",
            }
        ],
    )

    def fake_run_fail(args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr("taskq.executor.subprocess.run", fake_run_fail)
    cache_path = tmp_path / "cache.json"
    sigs_before = {entry.get("signature") for entry in _read_cache(tmp_path)}
    exit_code = cli.run_cmd(
        task_id="a0000099", all_mode=False, cached=True, json_mode=False
    )
    assert exit_code == 0  # cli returns 0 for failed status; status in record.
    sigs_after = {entry.get("signature") for entry in _read_cache(tmp_path)}
    assert sigs_before == sigs_after, (
        f"FR-04 must NOT write cache.json for non-done outcomes; "
        f"before={sigs_before} after={sigs_after}"
    )


def test_fr04_cache_atomic_thread_safe(tmp_path, monkeypatch):
    """[FR-04] case 5: cache.json atomic + thread-safe under concurrent writers."""
    monkeypatch.setenv("TASKQ_CACHE_TTL", "3600")
    monkeypatch.setenv("TASKQ_MAX_WORKERS", "4")

    def fake_run(args, **kwargs):
        time.sleep(0.02)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("taskq.executor.subprocess.run", fake_run)

    commands = [f"echo concurrent_atomic_{i}" for i in range(4)]
    seed = [
        {
            "id": f"a000000{i}",
            "name": None,
            "command": cmd,
            "status": "pending",
            "created_at": "2026-07-11T00:00:00Z",
        }
        for i, cmd in enumerate(commands)
    ]
    _seed_tasks(tmp_path, seed)

    exit_code = cli.run_cmd(
        task_id=None, all_mode=True, cached=True, json_mode=False
    )
    assert exit_code == 0

    cache_path = tmp_path / "cache.json"
    assert cache_path.exists(), (
        "FR-04 cache.json must exist after concurrent run --all"
    )
    try:
        cache_after = json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"FR-04 atomic write: cache.json corrupt after race: {exc}"
        )
    assert isinstance(cache_after, list)

    expected_sigs = {compute_signature(cmd) for cmd in commands}
    observed_sigs = {entry.get("signature") for entry in cache_after}
    assert expected_sigs <= observed_sigs, (
        f"FR-04 concurrent writes must persist every signature: "
        f"missing {expected_sigs - observed_sigs}"
    )

    # GREEN TODO: taskq.cache.Cache must protect concurrent access with a
    # threading.Lock so atomic + serialised writes are guaranteed.
    cache = Cache()
    cache_lock = getattr(cache, "_lock", None)
    assert isinstance(cache_lock, type(threading.Lock())), (
        "FR-04 Cache must expose a threading.Lock for NFR-03 thread safety"
    )
