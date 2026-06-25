"""taskq atomic-write helper — single source of truth for tmp+os.replace JSON writes.

[NFR-03] Provides atomic_write used by store.py and cache.py so both JSON files
(tasks.json + cache.json) follow the same write semantics. Extracted from
duplicated inline implementations to create a direct cross-module edge between
store and cache (CRG cohesion fix: taskq-task-sub1 had 0 internal edges).
"""
from __future__ import annotations

import json
import os
import tempfile


def atomic_write(path: str, data: dict, indent: int = 2) -> None:
    """Write data as JSON to path atomically using tmp + os.replace.

    [NFR-03] Ensures the file is always valid JSON even on process interrupt.
    Caller is responsible for ensuring the parent directory exists.
    `indent` defaults to 2 (tasks.json, cache.json) but breaker uses 3.
    """
    dir_path = os.path.dirname(path) or "."
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)  # pragma: no cover
            except OSError:  # pragma: no cover
                pass  # pragma: no cover
