"""[FR-04] Result TTL cache.

Citations:
  - SPEC.md §3 FR-04 (line 95-100) — sha256(command) + TTL replay + cache.json
  - 02-architecture/SAD.md §2.4 (`Cache.get` / `Cache.put` interface)
  - 02-architecture/SAD.md §2.5 (atomic tmp + os.replace + threading.Lock)
  - SPEC.md §4 NFR-03 (line 125) — atomic write survives crash mid-write
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

# Process-wide lock guarding the atomic tmp + os.replace sequence for
# cache.json. FR-04 requires thread-safe writes concurrent with FR-02
# `run --all` fan-out.
_lock = threading.Lock()

_DEFAULT_TTL_SECONDS = 3600


def _now_iso() -> str:
    """Return current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    """Parse ``YYYY-MM-DDTHH:MM:SSZ`` into an aware UTC datetime."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def signature(command: str) -> str:
    """[FR-04] Return the sha256 hex-digest of ``command``.

    Per SPEC.md §3 FR-04: ``快取簽名 = sha256(command)``.

    Returns:
        The hex digest string (length 64).
    """
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def cache_path(home: Path | None = None) -> Path:
    """[FR-04] Path to ``$TASKQ_HOME/cache.json``.

    Citations: SPEC.md §5.2 — cache.json layout.
    """
    if home is None:
        home = Path(os.environ["TASKQ_HOME"])
    return home / "cache.json"


def _load_entries(path: Path) -> dict[str, dict[str, object]]:
    """[FR-04] Return the cache dict, or ``{}`` if the file is absent."""
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _atomic_write(path: Path, data: dict[str, dict[str, object]]) -> None:
    """[FR-04] Atomically replace ``path`` with ``data``.

    Writes to ``<path>.tmp`` then ``os.replace`` onto ``path`` so a
    crash mid-write leaves either the previous valid file or the new
    valid file — never a half-written one. The orphan ``.tmp`` is
    always consumed by the replace.

    Citations: SPEC.md §4 NFR-03.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _lock:
        tmp.write_text(json.dumps(data))
        os.replace(tmp, path)


class CacheEntry:
    """[FR-04] A single cache row — the captured ``done`` result.

    Attributes:
        signature: sha256(command) hex digest.
        exit_code: exit code from the captured run.
        stdout_tail: tail (last 2000 chars) of stdout.
        stderr_tail: tail (last 2000 chars) of stderr.
        cached_at: ISO-8601 timestamp when the entry was written.
    """

    def __init__(
        self,
        signature: str,
        exit_code: int,
        stdout_tail: str,
        stderr_tail: str,
        cached_at: str | None = None,
    ) -> None:
        self.signature = signature
        self.exit_code = exit_code
        self.stdout_tail = stdout_tail
        self.stderr_tail = stderr_tail
        self.cached_at = cached_at if cached_at is not None else _now_iso()

    def to_dict(self) -> dict[str, object]:
        """[FR-04] Serialise to the on-disk dict shape."""
        return {
            "signature": self.signature,
            "exit_code": self.exit_code,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "cached_at": self.cached_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "CacheEntry":
        """[FR-04] Build a CacheEntry from the on-disk dict shape."""
        sig_raw = data.get("signature", "")
        code_raw = data.get("exit_code", 0)
        out_raw = data.get("stdout_tail", "")
        err_raw = data.get("stderr_tail", "")
        cached_raw = data.get("cached_at")
        return cls(
            signature=sig_raw if isinstance(sig_raw, str) else str(sig_raw),
            exit_code=code_raw if isinstance(code_raw, int) and not isinstance(code_raw, bool) else int(str(code_raw)),
            stdout_tail=out_raw if isinstance(out_raw, str) else str(out_raw),
            stderr_tail=err_raw if isinstance(err_raw, str) else str(err_raw),
            cached_at=cached_raw if isinstance(cached_raw, str) else None,
        )


class Cache:
    """[FR-04] TTL-bounded result cache for completed tasks.

    Backed by ``$TASKQ_HOME/cache.json`` (atomic write + shared Lock).
    Reads consult ``TASKQ_CACHE_TTL`` (default 3600s) and treat
    expired entries as misses. Writes happen only after a fresh
    ``done`` run; failed/timeout tasks are NOT cached.
    """

    def __init__(
        self,
        home: Path | None = None,
        ttl_seconds: float | None = None,
    ) -> None:
        self.path = cache_path(home)
        if ttl_seconds is None:
            ttl_seconds = float(
                os.environ.get("TASKQ_CACHE_TTL", _DEFAULT_TTL_SECONDS)
            )
        self.ttl_seconds = ttl_seconds

    def get(self, sig: str) -> CacheEntry | None:
        """[FR-04] Return the cached entry if present and within TTL.

        Returns ``None`` for missing or expired entries.
        """
        entries = _load_entries(self.path)
        raw = entries.get(sig)
        if raw is None:
            return None
        cached_at_raw = raw.get("cached_at")
        if not cached_at_raw:
            return None
        try:
            cached_at = _parse_iso(str(cached_at_raw))
        except (ValueError, TypeError):
            return None
        elapsed = (datetime.now(timezone.utc) - cached_at).total_seconds()
        if elapsed >= self.ttl_seconds:
            return None
        return CacheEntry.from_dict(raw)

    def put(self, sig: str, entry: CacheEntry | dict[str, object]) -> None:
        """[FR-04] Persist a fresh done result, atomically.

        Concurrent writers are serialised by a module-level
        ``threading.Lock`` and the on-disk file is always valid JSON.
        Accepts a ``CacheEntry`` instance or a plain dict matching the
        on-disk shape (``signature``, ``exit_code``, ``stdout_tail``,
        ``stderr_tail``, ``cached_at``).
        """
        entries = _load_entries(self.path)
        if isinstance(entry, CacheEntry):
            entries[sig] = entry.to_dict()
        else:
            # dict path — used by tests that build the on-disk shape directly.
            sig_raw = entry.get("signature", sig)
            code_raw = entry.get("exit_code", 0)
            out_raw = entry.get("stdout_tail", "")
            err_raw = entry.get("stderr_tail", "")
            cached_raw = entry.get("cached_at")
            entries[sig] = {
                "signature": sig_raw if isinstance(sig_raw, str) else str(sig_raw),
                "exit_code": code_raw if isinstance(code_raw, int) and not isinstance(code_raw, bool) else int(str(code_raw)),
                "stdout_tail": out_raw if isinstance(out_raw, str) else str(out_raw),
                "stderr_tail": err_raw if isinstance(err_raw, str) else str(err_raw),
                "cached_at": (cached_raw if isinstance(cached_raw, str) else None) or _now_iso(),
            }
        _atomic_write(self.path, entries)