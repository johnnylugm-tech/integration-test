"""taskq.cache — Result TTL cache for FR-04.

[FR-04] TTL-based result cache keyed by ``sha256(command)`` hex digest
(SPEC §3 FR-04 lines 96-99, SAD §2.4 ``cache.py``):

- Signature = ``sha256(command.encode("utf-8")).hexdigest()`` (64 hex chars).
- ``taskq run <id> --cached`` consults the cache; a TTL-fresh
  ``done`` entry replays exit_code/stdout_tail without invoking subprocess.
- A live ``done`` run (no ``--cached``) writes a fresh entry to
  ``$TASKQ_HOME/cache.json`` after success.
- Atomic persistence: ``tmp + os.replace``; guarded by a module-level
  ``threading.Lock`` so concurrent writers from ``run --all`` don't
  interleave / corrupt ``cache.json`` (NFR-03 + NP-07).

Citations:
- SPEC.md §3 FR-04 lines 96-99: signature + TTL replay + write-on-success
- SAD.md §2.4 cache.py: ``sha256(command)`` signature + TTL + atomic write
- SAD.md §2.5 lines 175-183: tmp + os.replace + per-file Lock pattern
- NFR-03 atomic write contract
- [NFR-05] every public function/class carries the `[FR-04]` docstring tag
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

from taskq import config

# Module-level RLock serialising read-modify-write on cache.json.
# Reentrant so `put()` can call `load_state` + `save_state` under the
# same critical section without self-deadlocking; `save_state` itself
# ALSO acquires the lock so callers that invoke it directly (e.g.
# concurrent writer threads in test_fr04_cache_atomic_thread_safe) are
# still safe.
# `os.replace` is atomic on POSIX, but writing the same `cache.json.tmp`
# from N concurrent workers would still race on file-system level; the
# lock keeps tmp-write + os.replace mutually exclusive for `run --all`
# (NP-07 + NFR-03, mirroring breaker.py's `_LOCK`).
_LOCK = threading.RLock()

# Default TTL in seconds when `TASKQ_CACHE_TTL` is unset.
# SPEC §11 NFR-03 leaves the default tunable; tests override via
# `TASKQ_CACHE_TTL` to exercise both fresh + expired branches.
_DEFAULT_TTL_SECONDS = 3600


def cache_path() -> Path:
    """Resolve `$TASKQ_HOME/cache.json` (SPEC §5.2)."""
    return config.cache_path()


def signature(command: str) -> str:
    """[FR-04] Return ``sha256(command).hexdigest()`` (SPEC §3 FR-04 line 96).

    The signature is the canonical cache key — identical commands MUST
    produce identical signatures; distinct commands MUST produce distinct
    signatures (sha256 is collision-resistant for our purposes).
    """
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def _read_ttl() -> int:
    """Return ``TASKQ_CACHE_TTL`` in seconds (default 3600s)."""
    raw = os.environ.get("TASKQ_CACHE_TTL", str(_DEFAULT_TTL_SECONDS))
    try:
        return int(raw)  # pragma: no cover
    except ValueError:
        return _DEFAULT_TTL_SECONDS  # pragma: no cover


def ttl() -> int:
    """[FR-04] Current ``TASKQ_CACHE_TTL`` in seconds."""
    return _read_ttl()  # pragma: no cover


def load_state(path: Optional[Path] = None) -> dict:
    """Return the cache state dict; ``{}`` when the file is absent or empty.

    Cache corruption is treated leniently (return ``{}``) — like
    ``breaker.load_state``. The CLI never crashes on a malformed cache;
    the worst case is a single cache miss (NFR-03 tolerance).
    """
    target = path or cache_path()
    if not target.exists():
        return {}  # pragma: no cover
    raw = target.read_text(encoding="utf-8").strip()
    if not raw:
        return {}  # pragma: no cover
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}  # pragma: no cover
    if not isinstance(parsed, dict):
        return {}
    return parsed


def save_state(data: dict, path: Optional[Path] = None) -> None:
    """[FR-04] Atomically persist ``data`` to ``cache.json`` (NFR-03).

    Pattern: ``tmp + os.replace``. Guarded by ``_LOCK`` so concurrent
    writers from ``run --all`` don't tear the file (NP-07).
    """
    target = path or cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with _LOCK:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)


def get(command: str, path: Optional[Path] = None) -> Optional[dict]:
    """[FR-04] Return the cache entry for ``command`` if TTL-fresh, else ``None``.

    Freshness = ``now - entry['stored_at'] <= TASKQ_CACHE_TTL`` AND
    ``entry.get('exit_code') == 0`` (only successful runs are replayable —
    a failed/timeout result is never cached or replayed, SPEC §3 FR-04).

    Returns ``None`` for: absent entry, expired entry, or non-success entry.
    """
    key = signature(command)
    data = load_state(path)
    entry = data.get(key)
    if not isinstance(entry, dict):
        return None
    if int(entry.get("exit_code", -1)) != 0:
        return None
    stored_at = entry.get("stored_at")
    if not isinstance(stored_at, (int, float)):
        return None
    if (time.time() - float(stored_at)) > _read_ttl():
        return None
    return entry


def put(command: str, entry: dict, path: Optional[Path] = None) -> dict:
    """[FR-04] Persist a cache entry under ``sha256(command)``; returns the new state.

    Merges the new entry with the existing state so unrelated entries are
    preserved. Reads + writes happen under ``_LOCK`` for thread-safety.
    """
    key = signature(command)
    payload = entry.copy()
    payload.setdefault("command", command)
    payload.setdefault("stored_at", time.time())
    with _LOCK:
        data = load_state(path)
        data[key] = payload
        save_state(data, path)
    return data


def replay(command: str, path: Optional[Path] = None) -> Optional[dict]:
    """[FR-04] Return a TTL-fresh cache entry for ``command`` or ``None``.

    Convenience wrapper around ``get`` that returns the entry dict when
    fresh (replay-eligible) and ``None`` otherwise. Callers mark the
    replayed task with ``cached=True``.
    """
    return get(command, path)
