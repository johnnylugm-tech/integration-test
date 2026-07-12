"""JSON atomic-write helper shared by Store and Breaker.

[NFR-03]
Both `tasks.json` and `breaker.json` need the same crash-safe write pattern:
write to a temp file in the same directory, ``fsync`` it, then ``os.replace``
onto the target. This module is the single source of truth so the two files
can't drift apart.

Citations: SAD.md line 82 (atomic write pattern shared with store).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(home: Path, filename: str, data: dict, *, tmp_prefix: str) -> None:
    """Write ``data`` as JSON to ``home/filename`` atomically (NFR-03).

    The temp file is created in ``home`` so ``os.replace`` is a same-directory
    rename on every platform. On any failure mid-write the temp file is removed
    and the existing target (if any) is left untouched.
    """
    home.mkdir(parents=True, exist_ok=True)
    target = home / filename
    fd, tmp_path = tempfile.mkstemp(prefix=tmp_prefix, suffix=".json.tmp", dir=str(home))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)  # atomic rename (NFR-03)
    except BaseException:
        # On any failure, remove the temp file; the destination is untouched.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
