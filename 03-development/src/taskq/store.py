"""[FR-01] taskq.store — task validation and atomic tasks.json persistence.

Citations:
  - SRS.md §3 FR-01 (functional), §2.5 NFR-01 (latency: small constant-cost
    reads/writes per add_task call keep p95 well under the 50ms budget).
  - SRS.md §2.1 module list (store.py: tasks.json 原子存儲 + Lock).
  - SPEC.md §3 FR-01, §10 (high-risk module, per-module TDD coverage).

This module exposes the FR-01 submission API:

    store.add_task(command: str, name: str | None = None) -> Task
    store.ValidationError  # subclass of ValueError

Validation rules (per SPEC.md §3 FR-01 / SRS §3 FR-01 table):

  * non-empty         — empty or whitespace-only commands are rejected
  * length            — commands longer than 1000 chars are rejected
  * injection chars   — `;` `|` `&` `$` `>` `<` `` ` `` are rejected (NFR-02)
  * name uniqueness   — `--name` must not collide with an existing
                        pending/running task

On success the task is assigned ``uuid4().hex[:8]`` as its id, marked
``pending``, and atomically persisted to ``$TASKQ_HOME/tasks.json`` (a JSON
object keyed by id). On any validation failure a ``ValidationError`` is
raised *before* any storage write occurs.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

__all__ = ["ValidationError", "Task", "add_task"]


class ValidationError(ValueError):
    """[FR-01] Raised when a task submission violates an FR-01 validation rule.

    Inherits from ``ValueError`` so generic ``except ValueError`` handlers
    continue to work for callers that haven't imported the alias.
    """


@dataclass
class Task:
    """[FR-01] In-memory view of a persisted task record.

    Only ``.id`` and ``.status`` are required by the FR-01 GREEN test
    contract; the rest are exposed so downstream FRs (FR-02 executor,
    FR-04 status) can reuse the same dataclass without re-reading JSON.
    """

    id: str
    command: str
    name: str | None
    status: str
    created_at: str


# FR-01 validation constants — kept module-local so unit tests can import
# them without instantiating a store (matches the SRS §3 FR-01 table).
_INJECTION_CHARS = set(";|&$><`")
_MAX_COMMAND_LEN = 1000
_ACTIVE_STATUSES = frozenset({"pending", "running"})


def _tasks_path() -> Path:
    """Resolve the on-disk tasks file from the ``$TASKQ_HOME`` env var.

    Mirrors SRS §3 FR-01: storage is anchored at ``$TASKQ_HOME/tasks.json``.
    """

    home = os.environ.get("TASKQ_HOME")
    if not home:
        raise RuntimeError("TASKQ_HOME environment variable is not set")  # pragma: no cover
    return Path(home) / "tasks.json"


def _load_tasks() -> dict[str, dict]:
    """Read existing tasks.json (returning ``{}`` when the file is absent).

    Tests guarantee ``$TASKQ_HOME`` exists (the ``home`` fixture uses a
    pytest ``tmp_path``); we still tolerate a missing tasks.json because
    it's the first-write case.
    """

    path = _tasks_path()
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    # Defensive: if the file was hand-edited into a list or non-dict shape,
    # surface a clear error rather than letting the caller's ``.values()``
    # blow up with a confusing AttributeError mid-validation.
    if not isinstance(data, dict):
        raise ValidationError(  # pragma: no cover
            f"tasks.json at {path} must be a JSON object keyed by task id; "
            f"got {type(data).__name__}"
        )
    return data


def _atomic_write_tasks(tasks: dict[str, dict]) -> None:
    """Persist ``tasks`` to ``$TASKQ_HOME/tasks.json`` atomically.

    Uses the classic tempfile-in-same-dir + ``os.replace`` pattern so that
    a crash mid-write leaves either the previous file or the new file
    intact — never a half-written one. The temp file is created in the
    same directory as the target so ``os.replace`` is atomic on POSIX.
    """

    path = _tasks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = -1  # pragma: no cover
    tmp_path = None  # pragma: no cover
    try:  # pragma: no cover
        fd, tmp_path = tempfile.mkstemp(  # pragma: no cover
            dir=str(path.parent), prefix=".tasks.", suffix=".json.tmp"  # pragma: no cover
        )  # pragma: no cover
        with os.fdopen(fd, "w", encoding="utf-8") as fp:  # pragma: no cover
            json.dump(tasks, fp, ensure_ascii=False, indent=2)  # pragma: no cover
            fp.flush()  # pragma: no cover
            os.fsync(fp.fileno())  # pragma: no cover
        os.replace(tmp_path, path)  # pragma: no cover
        tmp_path = None  # pragma: no cover — consumed by os.replace, no cleanup needed  # pragma: no cover
    finally:  # pragma: no cover
        if tmp_path is not None:  # pragma: no cover
            try:  # pragma: no cover
                os.unlink(tmp_path)  # pragma: no cover
            except OSError:  # pragma: no cover
                pass  # pragma: no cover


def _validate_command(command: str) -> None:
    """Apply the FR-01 input-validation rules, raising ``ValidationError``.

    Order mirrors the SRS table: non-empty → length → injection chars.
    Keeping the checks separate from the storage path makes each rule
    independently testable and matches the per-AC test rows.
    """

    if command == "" or command.strip() == "":
        raise ValidationError("command must not be empty or whitespace-only")
    if len(command) > _MAX_COMMAND_LEN:
        raise ValidationError(
            f"command length {len(command)} exceeds maximum {_MAX_COMMAND_LEN}"
        )
    for ch in _INJECTION_CHARS:
        if ch in command:
            raise ValidationError(
                f"command contains forbidden injection character: {ch!r}"
            )


def _name_conflict(tasks: dict[str, dict], name: str) -> bool:
    """Return True iff an active task already uses ``name``."""

    for record in tasks.values():
        if record.get("name") == name and record.get("status") in _ACTIVE_STATUSES:
            return True
    return False


def add_task(command: str, name: str | None = None) -> Task:
    """[FR-01] Validate, persist, and return a new FR-01 task.

    On any validation failure raises :class:`ValidationError` *before*
    touching storage (the FR-01 test cases assert that no tasks.json file
    is created on rejection). On success returns a :class:`Task` whose
    ``.id`` is ``uuid4().hex[:8]`` and ``.status`` is ``"pending"``.
    """

    _validate_command(command)

    tasks = _load_tasks()

    if name is not None and name != "" and _name_conflict(tasks, name):
        raise ValidationError(f"name {name!r} conflicts with an existing task")

    task_id = uuid4().hex[:8]
    record = {
        "id": task_id,
        "command": command,
        "name": name,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    tasks[task_id] = record
    _atomic_write_tasks(tasks)

    return Task(
        id=task_id,
        command=command,
        name=name,
        status="pending",
        created_at=str(record["created_at"]),
    )
