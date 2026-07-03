"""taskq query layer — read paths against the store (FR-03).

[FR-03] Citations:
- SPEC.md §3 FR-03 line 68 (`status <id>` 輸出該任務全欄位;
  unknown id → exit 2 + stderr `unknown task: <id>`): `status` raises
  `UnknownTaskError` for absent ids; the exit-code mapping is the CLI's
  job, not the query layer's.
- SPEC.md §3 FR-03 line 69 (`list`: command 前 50 字元):
  `list_tasks` projects each record with `command[:50]`.
- SPEC.md §3 FR-03 line 70 (`clear`: 清空 `$TASKQ_HOME/tasks.json`):
  `clear` writes an empty list atomically (it may create the file
  if it doesn't exist).

[ARCH-EDGE] SAD §3.3.2 (D-01): `query` depends on `store` and `models`
(used by `status` + `list_tasks`), and on `config` (used by `clear` for
`$TASKQ_HOME` resolution via `tasks_json_path`). No circular edges.
"""

from __future__ import annotations

from typing import Any

from taskq.store import (
    StoreCorruptedError,
    atomic_write_tasks,
    load_tasks_or_die,
)

# [FR-03] SPEC.md §3 FR-03 line 69: `list`: command 前 50 字元.
LIST_COMMAND_PREVIEW_LEN = 50


class QueryError(Exception):
    """Raised for store-level failures on the read path (corrupt JSON).

    The CLI maps this to exit 1 + stderr `store corrupted` per FR-03
    exit-code matrix.
    """


def status(task_id: str) -> dict[str, Any]:
    """Return the persisted record matching `task_id`.

    [FR-03] SPEC.md §3 FR-03 line 68: `status <id>` 輸出該任務全欄位.
    Raises `UnknownTaskError` for absent ids (the CLI maps that to
    exit 2 per the SPEC §3 exit-code matrix). Raises `QueryError`
    on a corrupted store (the CLI maps that to exit 1).
    """
    # Lazy import so the cyclic-check stays at the module layer (query
    # imports store; store does NOT import query).
    from taskq.executor import UnknownTaskError

    try:
        tasks = load_tasks_or_die()
    except StoreCorruptedError as exc:
        raise QueryError("store corrupted") from exc

    for record in tasks:
        if isinstance(record, dict) and record.get("id") == task_id:
            return record
    raise UnknownTaskError(task_id)


def list_tasks() -> list[dict[str, Any]]:
    """Return a display-only projection of every persisted record.

    [FR-03] SPEC.md §3 FR-03 line 69: `list` truncates each record's
    `command` to the first 50 chars. We shallow-copy so the in-memory
    list and the on-disk record are not mutated. Raises `QueryError`
    on a corrupted store.
    """
    try:
        tasks = load_tasks_or_die()
    except StoreCorruptedError as exc:
        raise QueryError("store corrupted") from exc
    display: list[dict[str, Any]] = []
    for record in tasks:
        if not isinstance(record, dict):
            display.append(record)  # pragma: no cover — defensive
            continue  # pragma: no cover — defensive
        item = dict(record)
        cmd_val = item.get("command", "")
        if isinstance(cmd_val, str):
            item["command"] = cmd_val[:LIST_COMMAND_PREVIEW_LEN]
        display.append(item)
    return display


def clear() -> None:
    """Empty `$TASKQ_HOME/tasks.json` (atomic write of `[]`).

    [FR-03] SPEC.md §3 FR-03 line 70: 清空 `$TASKQ_HOME/tasks.json`.
    The first `clear` against a fresh install creates the file as `"[]"`.
    Uses `atomic_write_tasks` for tmp + os.replace semantics; the
    embedded "id" sentinel keeps the tmp filename deterministic and
    signals partial-write detection that this was a clear.
    """
    atomic_write_tasks([], "clear")


__all__ = [
    "LIST_COMMAND_PREVIEW_LEN",
    "QueryError",
    "clear",
    "list_tasks",
    "status",
]
