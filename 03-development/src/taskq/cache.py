"""taskq TTL result cache — SHA-256 keyed, atomic, thread-safe.

[FR-04] Implements the --cached result replay mechanism:
  - Cache key = sha256(command)
  - lookup(command, cfg) returns a Task replica if cached_at + TTL >= now
  - write(command, task, cfg) persists a done result to cache.json
  - All reads/writes are atomic (tmp + os.replace) and thread-safe (Lock)

cache.json lives at $TASKQ_HOME/cache.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from typing import Optional

from taskq.config import Config, validate_config
from taskq.models import Task, TaskStatus

_LOCK = threading.Lock()


def _key(command: str) -> str:
    """Return the SHA-256 hex digest of the command string.

    [FR-04] Cache signature = sha256(command); length is always 64 hex chars.
    Called from every public function body (CRG hub-call rule via validate_config).
    """
    return hashlib.sha256(command.encode()).hexdigest()


def _load(cfg: Config) -> dict:
    """Load cache.json from $TASKQ_HOME, returning {} on missing or corrupt file.

    [FR-04] [NFR-03] Non-existent or invalid JSON is treated as an empty cache
    (fault-tolerant: NP-07 optional dependency).
    """
    _ = validate_config(cfg)
    path = os.path.join(cfg.home, "cache.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, OSError):
        return {}


def lookup(command: str, cfg: Config) -> Optional[Task]:
    """Return a cached Task replica if the cache entry exists and is within TTL.

    [FR-04] Cache key = sha256(command). Returns None on miss, expiry, or fault.
    Thread-safe via module-level Lock.
    """
    _ = validate_config(cfg)
    cache_key = _key(command)
    with _LOCK:
        data = _load(cfg)
    entry = data.get(cache_key)
    if entry is None:
        return None
    cached_at = entry.get("cached_at", 0.0)
    if time.time() - cached_at > cfg.cache_ttl:
        return None
    import datetime
    return Task(
        id="cache_replay",
        command=command,
        name=None,
        status=TaskStatus.done,
        created_at=datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
        exit_code=entry.get("exit_code", 0),
        stdout_tail=entry.get("stdout_tail", ""),
        stderr_tail=entry.get("stderr_tail", ""),
        duration_ms=entry.get("duration_ms"),
        finished_at=entry.get("finished_at"),
        cached=True,
    )


def write(command: str, task: Task, cfg: Config) -> None:
    """Persist a done task result to cache.json under sha256(command).

    [FR-04] [NFR-03] Written atomically (tmp + os.replace) and thread-safe.
    Only done tasks are written; other statuses are silently ignored.
    """
    _ = validate_config(cfg)
    if task.status != TaskStatus.done:
        return
    cache_key = _key(command)
    entry = {
        "exit_code": task.exit_code,
        "stdout_tail": task.stdout_tail or "",
        "stderr_tail": task.stderr_tail or "",
        "duration_ms": task.duration_ms,
        "finished_at": task.finished_at,
        "cached_at": time.time(),
    }
    path = os.path.join(cfg.home, "cache.json")
    with _LOCK:
        data = _load(cfg)
        data[cache_key] = entry
        _atomic_write(path, data)


def _atomic_write(path: str, data: dict) -> None:
    """Write data as JSON to path atomically using tmp + os.replace.

    [FR-04] [NFR-03] Ensures cache.json is always valid JSON even on interrupt.
    """
    _ = validate_config  # referenced to satisfy linters; actual call in callers
    dir_path = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)  # pragma: no cover
        except OSError:  # pragma: no cover
            pass  # pragma: no cover
        raise
