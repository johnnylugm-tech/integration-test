"""[FR-01, FR-02] CLI entry point: ``submit``, ``list``, ``run``, ``health``.

Citations:
  - 03-development/tests/test_fr01.py:54   _run_cli spawns ``python -m taskq``
  - 03-development/tests/test_fr01.py:76   submit "" → exit 2
  - 03-development/tests/test_fr01.py:94   submit 1000 chars → exit 0
  - 03-development/tests/test_fr01.py:108  blacklist chars ; | & $ > < `
  - 03-development/tests/test_fr01.py:265  list on corrupted file → exit 1, stderr
  - 03-development/tests/test_fr01.py:294  on-disk bytes unchanged after corruption
  - 03-development/tests/test_fr02.py:118  ``cli.main(["run", "--id", tid])`` drives
    the executor end-to-end
  - 03-development/tests/test_fr02.py:266  unexpected ``executor.run`` exception
    must surface as CLI exit code 1
  - 03-development/tests/test_fr02.py:316  ``cli.main(["health"])`` returns 0 with
    ``OK`` on stdout / empty stderr
"""
from __future__ import annotations

import sys

from taskq import executor, models, store

_MAX_COMMAND_LEN = 1000
_BLACKLIST = ";|&$><`"


def _validate(command: str) -> str | None:
    """Return None if ``command`` is acceptable, else an error message.

    Blacklisted shell metacharacters are rejected only when they appear
    OUTSIDE a quoted region (``"..."`` or ``'...'``), so compound Python
    snippets like ``python -c "import sys; sys.exit(7)"`` remain valid.
    """
    if not command or not command.strip():
        return "error: command must not be empty or whitespace"
    if len(command) > _MAX_COMMAND_LEN:
        return f"error: command exceeds maximum length of {_MAX_COMMAND_LEN}"
    in_quote: str | None = None
    for ch in command:
        if in_quote is not None:
            if ch == in_quote:
                in_quote = None
            continue
        if ch == '"' or ch == "'":
            in_quote = ch
            continue
        if ch in _BLACKLIST:
            return f"error: command contains forbidden character {ch!r}"
    if in_quote is not None:
        return "error: command has unterminated quote"
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


def _parse_run_args(rest: list[str]) -> tuple[str, float | None, int] | int:
    """Parse ``run`` flags. Return ``(tid, timeout, retry)`` or an exit code."""
    tid: str | None = None
    timeout: float | None = None
    retry = 0
    i = 0
    while i < len(rest):
        flag = rest[i]
        if flag == "--id":
            if i + 1 >= len(rest):
                print("error: --id requires a value", file=sys.stderr)
                return 2
            tid = rest[i + 1]
            i += 2
        elif flag == "--timeout":
            if i + 1 >= len(rest):
                print("error: --timeout requires a value", file=sys.stderr)
                return 2
            try:
                timeout = float(rest[i + 1])
            except ValueError:
                print("error: --timeout must be a number", file=sys.stderr)
                return 2
            i += 2
        elif flag == "--retry":
            if i + 1 >= len(rest):
                print("error: --retry requires a value", file=sys.stderr)
                return 2
            try:
                retry = int(rest[i + 1])
            except ValueError:
                print("error: --retry must be an integer", file=sys.stderr)
                return 2
            i += 2
        else:
            print(f"error: unknown flag {flag!r}", file=sys.stderr)
            return 2
    if not tid:
        print("error: run requires --id", file=sys.stderr)
        return 2
    return tid, timeout, retry


def _run(rest: list[str]) -> int:
    """Execute the stored task referenced by ``--id``.

    Any exception raised by ``executor.run`` (other than the controlled
    non-zero exit / timeout flows, which are handled inside the executor)
    is surfaced as exit code 1 per AC-FR02-14.
    """
    parsed = _parse_run_args(rest)
    if isinstance(parsed, int):
        return parsed
    tid, timeout, retry = parsed
    data = store.load()
    if tid not in data:
        print(f"error: task {tid!r} not found", file=sys.stderr)
        return 2
    task = data[tid]
    try:
        executor.run(task, timeout=timeout, retry=retry)
    except Exception as exc:  # AC-FR02-14: surface unexpected failures as exit 1
        print(f"error: run failed: {exc}", file=sys.stderr)
        return 1
    store.save(data)
    return 0


def _health() -> int:
    """Smoke probe — print ``OK`` to stdout and return 0."""
    print("OK")
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
    if cmd == "run":
        return _run(rest)
    if cmd == "health":
        return _health()
    print(f"error: unknown subcommand {cmd!r}", file=sys.stderr)
    return 2
