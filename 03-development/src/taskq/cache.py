"""[FR-04] 結果 TTL 快取 — result TTL cache for ``taskq run <id> --cached``.

Persists successful (``done``) task results to ``$TASKQ_HOME/cache.json`` and
replays them, keyed by ``sha256(command)``, while the entry is younger than
``$TASKQ_CACHE_TTL`` seconds. A fresh hit lets ``run --cached`` skip the
subprocess entirely and mark the task ``done`` with ``cached: true``.

Design contract:

* **Signature** = ``sha256(command).hexdigest()`` (SPEC §3 FR-04
  ``快取簽名 = sha256(command)``); distinct commands never cross-hit.
* **Lookup** returns the cached entry only when it exists AND
  ``now - cached_at <= TASKQ_CACHE_TTL``; expired / missing → ``None`` (miss).
* **Store** writes ONLY the caller-supplied result; the caller (executor)
  guarantees it stores ``done`` results and skips ``failed`` / ``timeout``.
* **Atomic write** — dump to ``cache.json.tmp`` then ``os.replace`` onto
  ``cache.json``; on ``OSError`` the orphan tmp is cleaned up and the failure
  re-raised so the destination is NEVER left half-written (NFR-03 invariant,
  the third atomic-write data file).
* **Concurrency** — ``store`` is a read-modify-write of ``cache.json`` and MUST
  run under the caller's shared ``threading.Lock`` so concurrent ``run --all``
  writers never corrupt the file or lose an entry (NFR-08; best-effort
  in-process defense layered on top of the atomic write).

Citations:
  SPEC §3 FR-04 (signature, TTL replay, done-only cache, atomic + thread-safe).
  SPEC §5.2 (``cache.json`` schema = ``{version:1, entries:{sig→result+cached_at}}``).
  SAD §3.2 (``cache.Cache`` module; owns its atomic-write boundary).
  NFR-03 (atomic write of the third data file), NFR-08 (concurrent writers).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# SPEC §5.2 — cache.json root schema version (NFR-10 evolvability).
_CACHE_VERSION: int = 1

# SPEC §5.1 — default TTL (seconds) when ``TASKQ_CACHE_TTL`` is unset.
_DEFAULT_CACHE_TTL: float = 3600.0


def signature(command: str) -> str:
    """Return ``sha256(command).hexdigest()`` — the canonical cache key [FR-04].

    Mirrors the SPEC §3 FR-04 contract ``快取簽名 = sha256(command)``. Keying by
    the literal command string (not task id or prefix) guarantees distinct
    commands never cross-hit.
    """
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def _cache_ttl() -> float:
    """Resolve ``$TASKQ_CACHE_TTL`` (seconds); fall back to the default [FR-04]."""
    raw = os.environ.get("TASKQ_CACHE_TTL")
    if raw is None or raw.strip() == "":
        return _DEFAULT_CACHE_TTL
    return float(raw)


def _cached_at_epoch(cached_at: str) -> float | None:
    """Parse an ISO-8601 ``cached_at`` string to a POSIX timestamp [FR-04].

    Returns ``None`` when the value is missing or unparseable so a malformed
    entry is treated as a cache miss rather than crashing the run.
    """
    if not cached_at:
        return None
    try:
        return datetime.fromisoformat(cached_at).timestamp()
    except ValueError:
        return None


class Cache:
    """TTL result cache backed by ``$TASKQ_HOME/cache.json`` [FR-04].

    Instantiated with the concrete ``cache.json`` path (resolved by ``cli``
    from ``$TASKQ_HOME``). Exposes ``lookup`` (TTL-aware read) and ``store``
    (atomic write). The instance is stateless beyond the path; all state lives
    on disk so multiple ``run --all`` worker threads share one view.
    """

    def __init__(self, cache_path: Path) -> None:
        """Bind the cache to its on-disk ``cache.json`` path [FR-04]."""
        self._path = Path(cache_path)

    def _read(self) -> dict[str, Any]:
        """Return the parsed ``{version, entries}`` mapping [FR-04].

        A missing file yields a fresh empty structure. The file is only ever
        written through :meth:`store`, so a present file is always the
        canonical shape.
        """
        if not self._path.exists():
            return {"version": _CACHE_VERSION, "entries": {}}
        data = json.loads(self._path.read_text())
        if not isinstance(data, dict):
            return {"version": _CACHE_VERSION, "entries": {}}
        data.setdefault("entries", {})
        return data

    def _atomic_write(self, data: dict[str, Any]) -> None:
        """Atomically write ``data`` to ``cache.json`` [FR-04][NFR-03].

        Dump to ``cache.json.tmp`` then ``os.replace`` onto the destination.
        On ``OSError`` from ``os.replace`` the orphan tmp is removed and the
        error re-raised, so ``cache.json`` is NEVER left half-written (the
        third atomic-write data file invariant).
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_name(self._path.name + ".tmp")
        tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True))
        try:
            os.replace(tmp_path, self._path)
        except OSError:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise

    def _is_fresh(self, entry: dict[str, Any]) -> bool:
        """Return True iff ``entry``'s ``cached_at`` parses AND is within TTL.

        [FR-04] The TTL predicate is the sole freshness gate for a cache hit:
        both a missing / unparseable ``cached_at`` and an age past
        ``$TASKQ_CACHE_TTL`` are treated as a cache miss.
        """
        cached_at = _cached_at_epoch(entry.get("cached_at", ""))
        if cached_at is None:
            return False
        age = datetime.now(timezone.utc).timestamp() - cached_at
        return age <= _cache_ttl()

    def lookup(self, sig: str) -> dict[str, Any] | None:
        """Return the cached result for ``sig`` if fresh, else ``None`` [FR-04].

        A hit requires the entry to exist AND pass :meth:`_is_fresh`. Missing
        files, absent signatures, malformed ``entries``, non-dict entries, and
        stale or unparseable ``cached_at`` values all yield ``None`` (a cache
        miss), so ``run --cached`` falls through to a normal execution.
        """
        data = self._read()
        entries = data.get("entries")
        if not isinstance(entries, dict):
            return None
        entry = entries.get(sig)
        if not isinstance(entry, dict) or not self._is_fresh(entry):
            return None
        return entry

    def store(self, sig: str, result: dict[str, Any]) -> None:
        """Persist ``result`` under ``sig`` with a fresh ``cached_at`` [FR-04].

        Read-modify-write of ``cache.json``: preserves other signatures'
        entries and overwrites (or inserts) ``sig``. Only the replay-relevant
        fields (``exit_code`` / ``stdout_tail`` / ``stderr_tail``) plus the
        write-time ``cached_at`` timestamp are stored. Callers MUST invoke this
        under the shared ``threading.Lock`` (NFR-08) and MUST only pass
        ``done`` results (SPEC §3 FR-04 — failed/timeout are never cached).

        Raises ``OSError`` if the atomic write fails; the caller treats a cache
        write as best-effort and MUST NOT let that failure fail the task run.
        """
        data = self._read()
        entries = data.get("entries")
        if not isinstance(entries, dict):
            entries = {}
        entries[sig] = {
            "exit_code": result.get("exit_code"),
            "stdout_tail": result.get("stdout_tail", ""),
            "stderr_tail": result.get("stderr_tail", ""),
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        self._atomic_write({"version": _CACHE_VERSION, "entries": entries})
