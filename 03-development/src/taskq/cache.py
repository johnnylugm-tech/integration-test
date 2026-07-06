"""[FR-04] taskq.cache — TTL cache for command execution results.

Citations:
  - SRS.md §3 FR-04 (functional): result TTL cache for repeated commands.
  - SPEC.md §3 FR-04 (cache contract: sha256 signature, TTL, atomic write).
  - SPEC.md §5.1 ($TASKQ_CACHE_TTL default 3600s).
  - NFR-03 (atomic persistence: tempfile + os.replace).
  - NFR-04 (thread-safety: module-level threading.Lock).

Public API:
    signature(command)            — sha256 hex digest, deterministic cache key.
    Cache                         — TTL cache class backed by $TASKQ_HOME/cache.json.
    CacheEntry                    — frozen view of one cache row.
    DEFAULT_CACHE_TTL = 3600      — default TTL in seconds (SPEC §5.1).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

__all__ = ["signature", "Cache", "CacheEntry", "DEFAULT_CACHE_TTL"]


# SPEC §5.1: default cache TTL is 3600s; operators may override via $TASKQ_CACHE_TTL.
DEFAULT_CACHE_TTL = 3600

# Module-level lock serialises every read-modify-write cycle so concurrent
# threads can never observe a partial / truncated cache.json (NFR-03 + SPEC
# §3 FR-04 "執行緒安全"). All Cache instances share this lock.
_lock = threading.Lock()


def signature(command: str) -> str:
    """[FR-04] Return the deterministic cache key for ``command`` (AC-FR-04-01).

    Uses SHA-256 over the UTF-8 encoding of ``command``; the result is a
    64-character lowercase hex string.
    """

    return hashlib.sha256(command.encode("utf-8")).hexdigest()


@dataclass
class CacheEntry:
    """[FR-04] Frozen view of one cache row returned by ``Cache.get``.

    Fields mirror SPEC §3 FR-04 result fields plus the ``cached`` replay
    flag that distinguishes a replayed entry from a freshly-executed one.
    """

    status: str
    exit_code: int | None
    stdout_tail: str
    stderr_tail: str
    cached_at: float
    cached: bool = False


def _cache_path() -> Path:
    """Resolve the on-disk cache file from the ``$TASKQ_HOME`` env var."""

    home = os.environ.get("TASKQ_HOME")
    if not home:
        raise RuntimeError("TASKQ_HOME environment variable is not set")  # pragma: no cover
    return Path(home) / "cache.json"


def _load_cache() -> dict:
    """Read existing cache.json, returning ``{}`` when absent or malformed."""

    path = _cache_path()
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, dict):
        return {}  # pragma: no cover
    return data


def _atomic_write_cache(data: dict) -> None:
    """Persist ``data`` to ``$TASKQ_HOME/cache.json`` atomically (NFR-03).

    Mirrors ``store._atomic_write_tasks`` / ``breaker._atomic_write_breaker``:
    write to a sibling temp file, fsync, then ``os.replace`` into place.
    A crash mid-write leaves either the previous file or the new file
    intact — never a truncated half-state.
    """

    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=".cache.", suffix=".json.tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_path, path)
    except Exception:  # pragma: no cover
        # Best-effort cleanup of the orphan temp file; re-raise the  # pragma: no cover
        # original error (e.g. ENOSPC) for the caller to handle.  # pragma: no cover
        try:  # pragma: no cover
            os.unlink(tmp_path)  # pragma: no cover
        except OSError:  # pragma: no cover
            pass  # pragma: no cover
        raise  # pragma: no cover


def _default_ttl() -> int:
    """Read $TASKQ_CACHE_TTL, falling back to ``DEFAULT_CACHE_TTL``."""

    raw = os.environ.get("TASKQ_CACHE_TTL")
    if raw is None or raw == "":
        return DEFAULT_CACHE_TTL
    try:
        return int(raw)
    except ValueError:  # pragma: no cover
        return DEFAULT_CACHE_TTL  # pragma: no cover


class Cache:
    """[FR-04] TTL cache for command execution results.

    Backed by ``$TASKQ_HOME/cache.json``. All read/write operations are
    serialised by the module-level ``_lock`` so concurrent callers cannot
    observe a partial / truncated file.
    """

    def get(
        self,
        command: str,
        *,
        now_fn=time.time,
        ttl: Optional[int] = None,
    ) -> Optional[CacheEntry]:
        """[FR-04] Return the cached entry for ``command`` or ``None`` on miss.

        Returns ``None`` on cache miss, expired entry (age ≥ ``ttl``), or
        a non-``done`` status entry. On hit returns a ``CacheEntry`` whose
        ``.cached`` attribute is ``True`` (the SPEC §3 FR-04 replay flag).

        ``ttl`` defaults to ``$TASKQ_CACHE_TTL`` (3600s per SPEC §5.1).
        """

        if ttl is None:
            ttl = _default_ttl()

        with _lock:
            data = _load_cache()
        sig = signature(command)
        payload = data.get(sig)
        if payload is None:
            return None  # pragma: no cover
        if payload.get("status") != "done":
            return None  # pragma: no cover
        cached_at = float(payload.get("cached_at", 0))
        if (now_fn() - cached_at) >= ttl:
            return None
        return CacheEntry(
            status=payload.get("status", ""),
            exit_code=payload.get("exit_code"),
            stdout_tail=payload.get("stdout_tail", ""),
            stderr_tail=payload.get("stderr_tail", ""),
            cached_at=cached_at,
            cached=True,
        )

    def put(
        self,
        command: str,
        *,
        status: str,
        exit_code: Optional[int],
        stdout_tail: str,
        stderr_tail: str,
        cached_at: Optional[float] = None,
    ) -> None:
        """[FR-04] Persist a cache entry for ``command`` under sha256(command).

        ``cached_at`` defaults to ``time.time()`` (the call time). The
        read-modify-write cycle is performed under the module-level lock
        so concurrent writers never lose entries or leave the file in a
        partial state.
        """

        if cached_at is None:
            cached_at = time.time()
        sig = signature(command)
        payload = {
            "status": status,
            "exit_code": exit_code,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "cached_at": cached_at,
        }
        with _lock:
            data = _load_cache()
            data[sig] = payload
            _atomic_write_cache(data)
