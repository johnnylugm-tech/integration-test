"""[FR-01, FR-02, FR-03] CLI entry point: ``submit``, ``list``, ``run``,
``status``, ``clear``, ``health`` + ``--json`` flag.

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
  - 03-development/tests/test_fr03.py:86   status <known id> → exit 0, full record
  - 03-development/tests/test_fr03.py:108  status <unknown id> → exit 2, stderr
  - 03-development/tests/test_fr03.py:127  list command field truncated to 50 chars
  - 03-development/tests/test_fr03.py:168  clear empties store
  - 03-development/tests/test_fr03.py:190  status --json emits single-line JSON
  - 03-development/tests/test_fr03.py:218  list --json emits single-line JSON array
  - 03-development/tests/test_fr03.py:259  CLI exits 4 on task timeout
  - 03-development/tests/test_fr03.py:294  CLI exits 1 on internal error / corrupted store
"""
from __future__ import annotations

import json
import sys

from taskq import executor, models, store

_MAX_COMMAND_LEN = 1000
_BLACKLIST = ";|&$><`"
_LIST_COMMAND_TRUNC = 50


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


def _format_record_line(tid: str, rec: dict) -> str:
    """Return ``{tid}\\t{status}\\t{command[:_LIST_COMMAND_TRUNC]}``.

    The command field is truncated to ``_LIST_COMMAND_TRUNC`` characters per
    AC-FR03-03 so that long commands don't blow up terminal width.
    """
    cmd = rec.get("command", "")
    if len(cmd) > _LIST_COMMAND_TRUNC:
        cmd = cmd[:_LIST_COMMAND_TRUNC]
    return f"{tid}\t{rec.get('status', '')}\t{cmd}"


def _list(*, json_output: bool) -> int:
    """FR-03 ``list``: print all tasks; truncate command to 50 chars; ``--json``
    emits a single-line JSON array of the raw records (full command, no trunc).
    """
    try:
        data = store.load()
    except store.StoreCorrupted:
        print("store corrupted", file=sys.stderr)
        return 1
    if json_output:
        records = [data[tid] | {"id": tid} for tid in sorted(data.keys())]
        sys.stdout.write(json.dumps(records, separators=(",", ":")))
        sys.stdout.write("\n")
        return 0
    for tid in sorted(data.keys()):
        print(_format_record_line(tid, data[tid]))
    return 0


def _status(tid: str, *, json_output: bool) -> int:
    """FR-03 ``status``: print the full record for ``tid``; exit 2 on unknown id
    with stderr ``unknown task: <tid>``; ``--json`` emits single-line JSON."""
    try:
        data = store.load()
    except store.StoreCorrupted:
        print("store corrupted", file=sys.stderr)
        return 1
    if tid not in data:
        print(f"unknown task: {tid}", file=sys.stderr)
        return 2
    rec = data[tid]
    if json_output:
        sys.stdout.write(json.dumps(rec | {"id": tid}, separators=(",", ":")))
        sys.stdout.write("\n")
        return 0
    print(f"id:      {tid}")
    for key in ("status", "command", "created_at", "exit_code",
                "stdout_tail", "stderr_tail", "duration_ms", "finished_at"):
        if key in rec:
            print(f"{key}: {rec[key]}")
    return 0


def _clear() -> int:
    """FR-03 ``clear``: remove the store file (no tasks.json on disk after)."""
    store.clear()
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

    Exit codes:
      - 0: task completed (status done)
      - 1: unexpected exception (AC-FR02-14) or corrupted store
      - 2: bad args / unknown tid
      - 4: task timed out (AC-FR03-08) — propagate executor's timeout as
           the process exit code rather than swallowing it as rc=0.
    """
    parsed = _parse_run_args(rest)
    if isinstance(parsed, int):
        return parsed
    tid, timeout, retry = parsed
    try:
        data = store.load()
    except store.StoreCorrupted:
        print("store corrupted", file=sys.stderr)
        return 1
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
    # AC-FR03-08: timeout must propagate as CLI exit 4, not be swallowed as 0.
    if task.get("status") == "timeout":
        return 4
    return 0


def _health() -> int:
    """Smoke probe — print ``OK`` to stdout and return 0."""
    print("OK")
    return 0


def _has_json_flag(rest: list[str]) -> tuple[bool, list[str]]:
    """Extract ``--json`` flag (anywhere in argv) and return (json_mode, rest)."""
    if "--json" in rest:
        return True, [a for a in rest if a != "--json"]
    return False, rest


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
        json_mode, rest2 = _has_json_flag(rest)
        return _list(json_output=json_mode)
    if cmd == "status":
        json_mode, rest2 = _has_json_flag(rest)
        if not rest2:
            print("error: status requires a task id", file=sys.stderr)
            return 2
        return _status(rest2[0], json_output=json_mode)
    if cmd == "run":
        return _run(rest)
    if cmd == "clear":
        return _clear()
    if cmd == "health":
        return _health()
    print(f"error: unknown subcommand {cmd!r}", file=sys.stderr)
    return 2