"""[FR-01] Persistent store: load + atomic save of ``tasks.json``.

Citations:
  - 03-development/tests/test_fr01.py:236  atomic save via tmp + os.replace
  - 03-development/tests/test_fr01.py:263  os.replace patched to raise (must be
    accessed as os.replace, not via ``from os import replace``)
  - 03-development/tests/test_fr01.py:276  corrupted JSON → exit 1, stderr
    "store corrupted"; on-disk bytes must NOT change
"""
from __future__ import annotations

import json
import os

from taskq import config


class StoreCorrupted(Exception):
    """Raised when ``tasks.json`` cannot be parsed."""


def load() -> dict:
    """Return the task dict; raise ``StoreCorrupted`` on unparseable bytes."""
    path = config.tasks_path()
    if not os.path.exists(path):
        return {}
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise StoreCorrupted(str(exc)) from exc
    if not isinstance(data, dict):
        raise StoreCorrupted("root is not an object")
    return data


def save(data: dict) -> None:
    """Atomically write ``data`` to ``tasks.json`` via tmp + ``os.replace``."""
    path = config.tasks_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    # Attribute access (not ``from os import replace``) so monkeypatch on
    # ``store.os.replace`` reaches this call site.
    os.replace(tmp, path)
