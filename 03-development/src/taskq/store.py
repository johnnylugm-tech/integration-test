"""JSON persistence for tasks.json — atomic write + corruption detection.

[FR-01] Citations:
- SPEC.md §3 FR-01 ("原子寫入 $TASKQ_HOME/tasks.json (tmp + os.replace)"):
  `atomic_write_tasks` writes to a tmp file then `os.replace` to the
  canonical path (POSIX-atomic); the tmp filename embeds the task id
  so partial-write detection is unambiguous.
- SPEC.md §3 FR-01 ("tasks.json 損壞(非法 JSON) → 啟動偵測 → exit 1,stderr
  `store corrupted`(不靜默重建)"): `load_tasks_or_die` raises
  `StoreCorruptedError` on JSONDecodeError, mapped to exit 1 + stderr in
  the CLI layer.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from taskq.config import tasks_json_path


# [FR-01] SPEC.md §3 FR-01 ("tasks.json 損壞(非法 JSON) → 啟動偵測 → exit 1,
# stderr `store corrupted`(不靜默重建)").
EXIT_CORRUPT = 1


class StoreCorruptedError(Exception):
    """Raised when $TASKQ_HOME/tasks.json is unparseable.

    [FR-01] SPEC.md §3 FR-01 ("tasks.json 損壞(非法 JSON) → 啟動偵測 →
    exit 1,stderr `store corrupted`(不靜默重建)").
    """


def load_tasks_or_die() -> list[dict[str, Any]]:
    """Return the parsed tasks.json, or raise StoreCorruptedError.

    Caller (CLI) maps the exception to exit 1 + stderr per FR-01.

    [FR-01] SPEC.md §3 FR-01 ("tasks.json 損壞(非法 JSON) → 啟動偵測 →
    exit 1,stderr `store corrupted`(不靜默重建)").
    """
    path = tasks_json_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StoreCorruptedError(str(exc)) from exc
    if not isinstance(data, list):
        raise StoreCorruptedError(f"top-level is not a list: {type(data).__name__}")
    return data


def atomic_write_tasks(tasks: list[dict[str, Any]], task_id: str) -> None:
    """Persist `tasks` to `$TASKQ_HOME/tasks.json` via tmp + os.replace.

    [FR-01] SPEC.md §3 FR-01 ("原子寫入 $TASKQ_HOME/tasks.json
    (tmp + os.replace)").
    """
    target = tasks_json_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    # tmp filename embeds task_id so partial-write detection is unambiguous.
    tmp_name = f"tasks.json.tmp.{task_id}"
    tmp_path = target.parent / tmp_name

    payload = json.dumps(tasks, ensure_ascii=False, indent=2)
    with open(tmp_path, "w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, target)


def append_task(record: dict[str, Any]) -> str:
    """Append `record` to tasks.json atomically; return the new task's id."""
    task_id = record["id"]
    tasks = load_tasks_or_die()
    tasks.append(record)
    atomic_write_tasks(tasks, task_id)
    return task_id


def report_corrupt_and_exit() -> "None":
    """Print 'store corrupted' to stderr and exit(1). Module-level CLI helper."""
    print("store corrupted", file=sys.stderr)  # pragma: no cover — superseded by inline error handling in cmd_submit/cmd_list
    sys.exit(EXIT_CORRUPT)  # pragma: no cover — superseded by inline error handling in cmd_submit/cmd_list
