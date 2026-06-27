"""[FR-01] CLI entry point: ``submit`` and ``list`` subcommands.

Citations:
  - 03-development/tests/test_fr01.py:54   _run_cli spawns ``python -m taskq``
  - 03-development/tests/test_fr01.py:76   submit "" → exit 2
  - 03-development/tests/test_fr01.py:94   submit 1000 chars → exit 0
  - 03-development/tests/test_fr01.py:108  blacklist chars ; | & $ > < `
  - 03-development/tests/test_fr01.py:265  list on corrupted file → exit 1, stderr
  - 03-development/tests/test_fr01.py:294  on-disk bytes unchanged after corruption
"""
from __future__ import annotations

import sys

from taskq import config, models, store

_MAX_COMMAND_LEN = 1000
_BLACKLIST = ";|&$><`"


def _validate(command: str) -> str | None:
    """Return None if ``command`` is acceptable, else an error message."""
    if not command or not command.strip():
        return "error: command must not be empty or whitespace"
    if len(command) > _MAX_COMMAND_LEN:
        return f"error: command exceeds maximum length of {_MAX_COMMAND_LEN}"
    for ch in _BLACKLIST:
        if ch in command:
            return f"error: command contains forbidden character {ch!r}"
    return None


def _submit(command: str) -> int:
    err = _validate(command)
    if err is not None:
        print(err, file=sys.stderr)
        return 2
    data = store.load()
    tid = models.new_task_id()
    data[tid] = models.new_record(command)
    store.save(data)
    return 0


def _list() -> int:
    try:
        data = store.load()
    except store.StoreCorrupted:
        print("store corrupted", file=sys.stderr)
        return 1
    for tid, rec in sorted(data.items()):
        print(f"{tid}\t{rec.get('status', '')}\t{rec.get('command', '')}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print("error: missing subcommand", file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "submit":
        if not rest:
            print("error: submit requires a command argument", file=sys.stderr)
            return 2
        return _submit(rest[0])
    if cmd == "list":
        return _list()
    print(f"error: unknown subcommand {cmd!r}", file=sys.stderr)
    return 2
