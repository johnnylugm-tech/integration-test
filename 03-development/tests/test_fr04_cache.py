"""FR-04 — 結果 TTL 快取 (RED phase failing tests).

Traces SRS §3 FR-04 (AC-FR-04-01..04) and TEST_SPEC FR-04 cases 1-4.

GREEN CONTRACT (what the GREEN agent must implement in src/taskq/cache.py):

  - ``cache.signature(command: str) -> str``
      * Returns ``hashlib.sha256(command.encode("utf-8")).hexdigest()``,
        a 64-character lowercase hex string (AC-FR-04-01).

  - ``taskq.cache.Cache`` class — TTL cache backed by
    ``$TASKQ_HOME/cache.json``:
      * ``Cache.get(command, *, now_fn=time.time, ttl=None) -> Optional[CacheEntry]``
        - Returns ``None`` on miss, expired entry, or non-``done`` status.
        - On hit returns a ``CacheEntry`` whose ``.cached`` attribute is
          set to ``True`` (the replay flag — SPEC.md §3 FR-04).
        - ``ttl`` defaults to ``$TASKQ_CACHE_TTL`` (3600s per SPEC §5.1).
      * ``Cache.put(command, *, status, exit_code, stdout_tail,
                     stderr_tail, cached_at=None) -> None``
        - Persists an entry under ``sha256(command)`` with ``cached_at``
          defaulting to ``time.time()``; non-blocking for callers.
      * Reads/writes to ``cache.json`` are serialized by a module-level
        ``threading.Lock`` (NFR-03 + SPEC.md §3 FR-04 "執行緒安全").
      * Writes are atomic via ``tmp + os.replace`` (NFR-03).

  - ``taskq.cache.CacheEntry`` dataclass — frozen view of one cache row:
      * ``status: str``, ``exit_code: int | None``,
        ``stdout_tail: str``, ``stderr_tail: str``,
        ``cached_at: float``, ``cached: bool = False``.

Every sub-assertion predicate from TEST_SPEC.md is asserted verbatim inside
an ``if VAR == LITERAL:`` block (LHS = input variable, RHS = spec input
value) so that ``check-test-mirrors-spec`` can mechanically align
sub-assertion triggers with TEST_SPEC case inputs (P2-locked).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from taskq import cache  # GREEN will create this module → RED Collection Error


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Isolate storage under a tmp $TASKQ_HOME so tests don't touch real files."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_CACHE_TTL", "3600")
    return tmp_path


def _read_cache_json(home_dir: Path) -> dict:
    """Read raw cache.json content and return parsed dict (validates JSON)."""
    return json.loads((home_dir / "cache.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# TEST_SPEC FR-04 case 1 — happy_path (AC-FR04-01: sha256 signature len=64)
# ---------------------------------------------------------------------------
def test_fr04_signature_sha256(home):
    command = "echo hi"
    expected_sig_len = "64"

    sig = cache.signature(command)

    if expected_sig_len == "64":
        # AC-FR04-01-sha256-len-64: SHA-256 hex digest is 64 lowercase hex chars.
        assert isinstance(sig, str)
        assert len(sig) == 64, (
            f"signature length expected 64 (sha256 hex), got {len(sig)}"
        )
        assert all(c in "0123456789abcdef" for c in sig), (
            "signature must be lowercase hex"
        )
        # Determinism: same command → same signature.
        assert cache.signature(command) == sig
        # AC-FR04-01-sha256-len-64: mirror spec input verbatim.
        assert expected_sig_len == "64"


# ---------------------------------------------------------------------------
# TEST_SPEC FR-04 case 2 — happy_path (AC-FR04-02: TTL hit replays without subprocess)
# ---------------------------------------------------------------------------
def test_fr04_cached_replay_no_subprocess(home):
    command = "echo hi"
    cached_at_offset = "0"
    ttl = "3600"
    expected_status = "done"
    expected_cached = "true"

    # Seed the cache with a "done" entry cached "now" (offset=0 → still fresh).
    cache.Cache().put(
        command=command,
        status="done",
        exit_code=0,
        stdout_tail="hi\n",
        stderr_tail="",
    )

    # GREEN TODO: Cache.get must (a) load cache.json, (b) compute signature,
    # (c) check status == "done" + cached_at + ttl > now, (d) return entry
    # with .cached == True on hit, (e) NEVER spawn a subprocess.
    entry = cache.Cache().get(command)

    if expected_status == "done":
        # AC-FR04-02-replay-status: replayed status must equal "done".
        assert entry is not None, "expected cache hit"
        assert entry.status == "done"
        assert expected_status == "done"
    if expected_cached == "true":
        # AC-FR04-02-cached-true: replayed entry must carry cached=True flag.
        assert entry is not None
        assert entry.cached is True
        assert expected_cached == "true"
    if ttl == "3600":
        # AC-FR04-02-ttl-3600: TTL default of 3600s is what protected the hit.
        # Spot-check: the default TTL constant is exposed at module level.
        assert getattr(cache, "DEFAULT_CACHE_TTL", None) == 3600
        assert ttl == "3600"
    # mirror spec input verbatim
    assert cached_at_offset == "0"


# ---------------------------------------------------------------------------
# TEST_SPEC FR-04 case 3 — boundary (AC-FR04-03: expired → normal exec, cached=false)
# ---------------------------------------------------------------------------
def test_fr04_expiry_normal_execution(home):
    command = "echo hi"
    cached_at_offset = "7200"
    ttl = "3600"
    expected_status = "done"
    expected_cached = "false"

    # Seed the cache with an entry whose cached_at is 7200s in the past
    # (well beyond the default 3600s TTL).
    stale_time = time.time() - int(cached_at_offset)
    cache.Cache().put(
        command=command,
        status="done",
        exit_code=0,
        stdout_tail="hi\n",
        stderr_tail="",
        cached_at=stale_time,
    )

    # GREEN TODO: Cache.get must return None (or signal miss) for an entry
    # whose age exceeds the TTL — no replay, no subprocess.
    entry = cache.Cache().get(command)

    if cached_at_offset == "7200":
        # AC-FR04-03-expired: entry 7200s old exceeds 3600s TTL → not replayed.
        assert entry is None, (
            f"expected cache miss for expired entry (offset={cached_at_offset}, "
            f"ttl={ttl}), got entry={entry!r}"
        )
        assert cached_at_offset == "7200"
    # AC-FR04-03-expiry-reruns / -cached-false: normal execution after expiry
    # produces a fresh result with status="done" and cached=False.
    # GREEN TODO: this requires a `cached: bool` flag on the cached-execution
    # result path; the GREEN impl must add it (or expose a helper that does).
    from taskq import executor as _executor

    result = _executor.execute(command=command, timeout=10.0)
    if expected_status == "done":
        assert result.status == "done"
        assert expected_status == "done"
    if expected_cached == "false":
        # Normal (non-cached) execution must NOT advertise cached=True.
        assert getattr(result, "cached", False) is False
        assert expected_cached == "false"


# ---------------------------------------------------------------------------
# TEST_SPEC FR-04 case 4 — unit Q5 (AC-FR04-04: 8 concurrent writers, no loss, valid JSON)
# ---------------------------------------------------------------------------
def test_fr04_atomic_thread_safe_write(home):
    n_writers = "8"
    command = "echo hi"
    expected_cache_json_valid = "true"
    expected_loss_count = "0"

    # GREEN TODO: cache.Cache.put must serialize concurrent writers via a
    # threading.Lock so that 8 racing writes do not lose entries or leave
    # cache.json in a partial / truncated state.
    errors: list[BaseException] = []

    def writer(idx: int) -> None:
        try:
            cache.Cache().put(
                command=f"{command}-{idx}",
                status="done",
                exit_code=0,
                stdout_tail=f"out-{idx}\n",
                stderr_tail="",
            )
        except BaseException as exc:  # noqa: BLE001 — propagate via shared list
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(int(n_writers))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if expected_cache_json_valid == "true":
        # AC-FR04-04-json-valid: cache.json must parse as JSON after concurrent writes.
        path = home / "cache.json"
        assert path.exists(), "cache.json was not written"
        raw = path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            pytest.fail(f"cache.json is not valid JSON after concurrent writes: {exc}")
        assert isinstance(data, dict)
        assert expected_cache_json_valid == "true"
    # AC-FR04-04-no-loss: all n_writes entries must be present (zero loss).
    if n_writers == "8":
        data = _read_cache_json(home)
        written = sum(
            1
            for sig, payload in data.items()
            if payload.get("stdout_tail", "").startswith("out-")
        )
        assert written == int(n_writers) - int(expected_loss_count), (
            f"expected {n_writers} entries, found {written}; errors={errors}"
        )
        # AC-FR04-04-no-loss: mirror spec input verbatim.
        assert expected_loss_count == "0"
        # AC-FR04-04-writers: mirror spec input verbatim.
        assert n_writers == "8"
    assert not errors, f"concurrent writers raised: {errors}"