"""TTL result cache for taskq (FR-04).

[FR-04]
The cache lives at ``$TASKQ_HOME/cache.json`` with shape::

    { "version": 1, "entries": { "<sha256(command)>": {RunResult + cached_at} } }

``Cache.lookup(signature)`` returns the cached entry when it is present AND
the elapsed time since ``cached_at`` does not exceed ``ttl`` (TASKQ_CACHE_TTL);
otherwise it returns ``None``. ``Cache.put(signature, result)`` records the
entry under the same atomic-write contract as ``tasks.json`` /
``breaker.json`` so a crash mid-write never leaves a half-written file on
disk (NFR-03). Concurrent workers from ``run --all`` are serialized via a
``threading.Lock`` so the load-modify-write cycle is atomic across the
thread pool.

Cache writes are **best-effort** (NFR-07): when the atomic rename fails (for
example because of an injected mid-write OSError), the OSError is logged and
discarded and the underlying task outcome is preserved. The cache is an
optimization, not a hard dependency — a transient outage must not surface
to the user or abort the task.

Cache.json corruption is auto-recovered (NFR-07 "no silent rebuild") — the
corrupted file is renamed aside for audit and a fresh empty document is
returned, so the next ``put()`` rewrites a valid JSON file.

Citations:
- SPEC.md line 99 (FR-04 cache signature = ``sha256(command)``, TTL replay)
- SAD.md line 180-183 (``Cache.lookup`` / ``Cache.put`` signatures)
- SAD.md line 270 (cache.json shape: version=1, entries dict)
- SAD.md line 116 (write only when executor actually runs AND result is done)
- SAD.md line 22 (thread-safety shared Lock across storage modules)
- NFR-03 (tmp + ``os.replace`` atomic write, shared helper)
- NFR-07 (no silent swallow of corruption; cache write failure absorbed)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from taskq.core.models import RunResult
from taskq.storage._atomic import atomic_write_json

CACHE_FILENAME = "cache.json"

_log = logging.getLogger(__name__)


def _fresh_data() -> dict:
    """Return a fresh empty cache document (SAD.md line 270)."""
    return {"version": 1, "entries": {}}


class Cache:
    """TTL-bounded signature-to-RunResult cache rooted at $TASKQ_HOME/cache.json.

    [FR-04]
    Thread-safe via an internal ``threading.Lock`` so concurrent ``run --all``
    workers (SAD.md line 22) never produce a half-written entries document.
    Atomic writes go through ``atomic_write_json`` (NFR-03). Write failures
    are absorbed (NFR-07).
    """

    def __init__(self, home: Path, *, ttl: int = 0) -> None:
        self.home = Path(home)
        self.path = self.home / CACHE_FILENAME
        # ttl <= 0 means "always expired" — Cache becomes a no-op. This is
        # intentionally the conservative default so opt-in to caching is
        # explicit via TASKQ_CACHE_TTL.
        self.ttl = int(ttl)
        # FR-04 thread safety — serialize load-modify-write across workers.
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal load/save (always called with self._lock held by mutators)
    # ------------------------------------------------------------------
    def _load(self) -> dict:
        """Return the cache.json document.

        [NFR-07]
        Auto-recovers from corruption by quarantining the bad file (audit
        trail) and returning a fresh empty document. Missing / empty / wrong-
        shape files all yield the fresh empty document.
        """
        if not self.path.exists():
            return _fresh_data()
        try:
            text = self.path.read_text()
        except OSError:
            return _fresh_data()
        if not text.strip():
            return _fresh_data()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            self._quarantine()
            return _fresh_data()
        if not isinstance(data, dict):
            self._quarantine()
            return _fresh_data()
        data.setdefault("version", 1)
        data.setdefault("entries", {})
        if not isinstance(data.get("entries"), dict):
            data["entries"] = {}
        return data

    def _quarantine(self) -> None:
        """Move the on-disk cache.json aside (audit trail) before recovery.

        [NFR-07]
        Best-effort: any OSError during rename is swallowed because the
        fresh-document recovery path will overwrite the file on the next
        successful save regardless.
        """
        try:
            stamp = int(time.time() * 1000)
            quarantine = self.path.with_name(f"{CACHE_FILENAME}.corrupt-{stamp}.bak")
            os.replace(self.path, quarantine)
        except OSError as exc:
            _log.debug("cache quarantine rename failed: %s", exc)
            return

    def _save(self, data: dict) -> None:
        """Write cache.json atomically via the shared helper (NFR-03).

        Raises whatever ``atomic_write_json`` raises; callers that want
        best-effort semantics must wrap.
        """
        atomic_write_json(self.home, CACHE_FILENAME, data, tmp_prefix=".cache-")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def lookup(self, signature: str) -> Optional[RunResult]:
        """Return the cached RunResult for ``signature``, or ``None``.

        [FR-04]
        A hit requires:
          * entry present
          * ``status == done``
          * ``(now - cached_at) <= ttl`` (with ttl > 0)
        Returns ``None`` for any miss / expiry — the caller falls through to
        a fresh execution.
        """
        if self.ttl <= 0:
            return None
        with self._lock:
            data = self._load()
        entry = data.get("entries", {}).get(signature)
        if entry is None:
            return None
        if entry.get("status") != "done":
            return None
        cached_at = entry.get("cached_at")
        if not cached_at:
            return None
        try:
            ts = datetime.fromisoformat(cached_at)
            if ts.tzinfo is None:
                # We always write via datetime.utcnow().isoformat(), so a
                # naive ISO timestamp from this codebase is UTC — re-tag it
                # before converting to epoch so that local-timezone hosts
                # (e.g. CST) don't accidentally treat a freshly-written
                # entry as already-expired by the local-UTC offset.
                ts = ts.replace(tzinfo=timezone.utc)
            ts_epoch = ts.timestamp()
        except (ValueError, TypeError):
            return None
        if (time.time() - ts_epoch) > self.ttl:
            return None
        return _entry_to_runresult(entry)

    def put(self, signature: str, result: RunResult) -> None:
        """Persist ``result`` under ``signature`` (best-effort, NFR-07).

        [FR-04, NFR-03, NFR-07]
        Atomic write via the shared ``atomic_write_json`` helper. Any
        OSError is logged and discarded so a transient cache outage (e.g.
        EROFS / ENOSPC / injected mid-write OSError) never propagates to the
        task outcome. Concurrent writers are serialized via ``self._lock``
        so the load-modify-write cycle never loses updates under
        ``run --all`` (FR-02 NFR-08).
        """
        with self._lock:
            try:
                data = self._load()
            except Exception as exc:  # pragma: no cover - defensive
                _log.debug("cache.load failed: %s", exc)
                return
            entry = result.to_fields()
            entry["cached_at"] = datetime.utcnow().isoformat()
            data["entries"][signature] = entry
            try:
                self._save(data)
            except Exception as exc:
                _log.debug("cache.save failed: %s", exc)
                return


def _entry_to_runresult(entry: dict) -> RunResult:
    """Reconstruct a ``RunResult`` from a stored cache entry (FR-04)."""
    from taskq.core.models import TaskStatus  # local import avoids cycle in tests

    status_str = entry.get("status")
    status = TaskStatus(status_str) if status_str in {s.value for s in TaskStatus} else TaskStatus.DONE
    return RunResult(
        status=status,
        exit_code=entry.get("exit_code"),
        stdout_tail=entry.get("stdout_tail", ""),
        stderr_tail=entry.get("stderr_tail", ""),
        duration_ms=float(entry.get("duration_ms", 0.0) or 0.0),
        finished_at=entry.get("finished_at", ""),
    )
