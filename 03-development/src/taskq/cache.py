"""taskq cache — TTL result cache with atomic + thread-safe writes.

[FR-04] Citations: SPEC.md §3 FR-04 (TTL cache keyed by
``sha256(command)``; on ``--cached``, a TTL-fresh ``done`` entry must
replay without invoking subprocess; on miss / expiry the task must run
normally and the cache must be refreshed on ``done`` only); §5.2 data
file ``cache.json``; NFR-03 (atomic write via tmp-file + ``os.replace``;
crash leaves parseable JSON — either old or fully-new state).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_CACHE_FILE = "cache.json"

# Shared lock so concurrent ``run --all`` workers (FR-02/FR-04) serialise
# on the SAME mutex. Per-instance locks would let each worker win its
# own race and clobber the others' writes to ``cache.json``.
_SHARED_LOCK = threading.Lock()

# Default cache TTL in seconds when ``TASKQ_CACHE_TTL`` is unset.
_DEFAULT_CACHE_TTL = "3600"


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 ``Z`` string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_signature(command: str) -> str:
    """Return the lowercase hex ``sha256`` of ``command`` UTF-8 bytes (FR-04).

    [FR-04] Citations: SPEC.md §3 FR-04 (快取簽名 = sha256(command)).
    """
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def _cache_path() -> Path:
    """Return the path to ``cache.json`` inside ``$TASKQ_HOME``.

    Falls back to ``.taskq`` when the env var is unset so the module is
    importable outside the CLI test harness; production usage always
    sets ``TASKQ_HOME``.
    """
    home = Path(os.environ.get("TASKQ_HOME", ".taskq"))
    return home / _CACHE_FILE


def _default_ttl() -> int:
    """Read ``TASKQ_CACHE_TTL`` (integer seconds) or fall back to 1h."""
    return int(os.environ.get("TASKQ_CACHE_TTL", _DEFAULT_CACHE_TTL))


def _is_fresh(entry: dict[str, Any], ttl: int) -> bool:
    """Return True when ``entry.cached_at`` is within ``ttl`` seconds.

    A non-positive TTL forces every entry to be considered expired
    (test hook — see TEST_SPEC §FR-04 case 3 ``TASKQ_CACHE_TTL=0``).
    """
    if ttl <= 0:
        return False
    cached_at = entry.get("cached_at")
    if not cached_at:
        return False
    try:
        cached_dt = datetime.strptime(cached_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    age = (
        datetime.now(timezone.utc)
        - cached_dt.replace(tzinfo=timezone.utc)
    ).total_seconds()
    return age < ttl


class Cache:
    """Thread-safe TTL cache for command results (SPEC §3 FR-04).

    [FR-04] Citations: SPEC.md §3 FR-04 (TTL-fresh ``done`` entry
    replays without subprocess; miss/expired runs normally and refreshes
    the cache on ``done``); NFR-03 (Lock-protected reads + writes;
    atomic tmp + ``os.replace`` so an interrupted process never leaves a
    half-written ``cache.json``).
    """

    def __init__(self) -> None:
        # NFR-03 contract: every Cache instance exposes a
        # ``threading.Lock`` for serialising concurrent readers + writers.
        # Module-level shared lock so all instances — and the
        # ``run --all`` ThreadPoolExecutor workers — serialise on the
        # same mutex.
        self._lock = _SHARED_LOCK

    # ----- public API --------------------------------------------------

    def get(self, signature: str) -> Optional[dict[str, Any]]:
        """Return a TTL-fresh ``done`` entry for ``signature`` or ``None``.

        [FR-04] Citations: SPEC.md §3 FR-04 (TTL-fresh done entry must
        replay; expired/missing/absent must not).
        """
        with self._lock:
            entries = self._load_unsafe()
        ttl = _default_ttl()
        for entry in entries:
            if entry.get("signature") != signature:
                continue
            if entry.get("status") != "done":
                return None
            if not _is_fresh(entry, ttl):
                return None
            return entry
        return None

    def put(
        self,
        signature: str,
        command: str,
        result: dict[str, Any],
        task_id: str,
    ) -> None:
        """Persist ``result`` under ``signature`` atomically.

        No-ops when ``result.status`` is not ``done`` (FR-04: cache must
        only hold successful runs).
        """
        if result.get("status") != "done":
            return
        entry = {
            "signature": signature,
            "command": command,
            "status": result.get("status"),
            "exit_code": result.get("exit_code"),
            "stdout_tail": result.get("stdout_tail"),
            "stderr_tail": result.get("stderr_tail"),
            "duration_ms": result.get("duration_ms"),
            "finished_at": result.get("finished_at"),
            "cached_at": _now_iso(),
            "result_task_id": task_id,
        }
        with self._lock:
            entries = self._load_unsafe()
            # Replace any prior entry with the same signature so a
            # re-run overwrites the stale entry rather than appending
            # duplicates.
            entries = [e for e in entries if e.get("signature") != signature]
            entries.append(entry)
            self._save_unsafe(entries)

    # ----- unsafe helpers (caller MUST hold ``self._lock``) ------------

    def _load_unsafe(self) -> list[dict[str, Any]]:
        path = _cache_path()
        if not path.exists():
            return []
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupt or unreadable file: behave like a fresh cache so
            # subsequent ``_save_unsafe`` rebuilds a valid JSON document
            # (NFR-03 — crash leaves parseable JSON).
            return []
        if not isinstance(loaded, list):
            return []
        return loaded

    def _save_unsafe(self, entries: list[dict[str, Any]]) -> None:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Unique tmp per writer: concurrent ThreadPoolExecutor workers
        # must not race on a shared ``cache.json.tmp`` (NFR-03).
        fd, tmp_str = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(entries, fh, ensure_ascii=False)
            os.replace(tmp_str, path)
        except BaseException:
            try:
                os.unlink(tmp_str)
            except OSError:
                pass
            raise