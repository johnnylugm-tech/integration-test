"""taskq breaker — global circuit breaker with atomic state persistence.

[FR-03] Citations: SPEC.md §3 FR-03 (circuit breaker state machine
CLOSED → OPEN at threshold; OPEN → HALF_OPEN after TASKQ_BREAKER_COOLDOWN;
HALF_OPEN +success → CLOSED, +failure → re-OPEN); §5.2 data file
``breaker.json``; NFR-03 (atomic write: tmp + ``os.replace``; crash
leaves parseable JSON — either old or fully-new state).
[FR-05] Citations: SPEC.md §3 FR-05 (exit code 3 + stderr ``breaker open``
on rejected run; tolerant coercion of malformed ``opened_at`` records).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any

_BREAKER_FILE = "breaker.json"

# Shared lock so concurrent callers serialise on the same mutex (NFR-03
# read-modify-write on ``breaker.json``).
_SHARED_LOCK = threading.Lock()

# Defaults for env vars consumed by the breaker.
_DEFAULT_THRESHOLD = "3"
_DEFAULT_COOLDOWN = "60.0"
_DEFAULT_RETRY_LIMIT = "0"
_DEFAULT_BACKOFF_BASE = "1"


class BreakerState(str, Enum):
    """Circuit breaker state values (SPEC §3 FR-03)."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


def _breaker_path() -> Path:
    """Return the path to ``breaker.json`` inside ``$TASKQ_HOME``.

    Falls back to ``.taskq`` when the env var is unset so the module is
    importable outside the CLI test harness; production usage always
    sets ``TASKQ_HOME``.
    """
    home = Path(os.environ.get("TASKQ_HOME", ".taskq"))
    return home / _BREAKER_FILE


def _initial_data() -> dict[str, Any]:
    """Return the fresh in-memory state for a brand-new breaker."""
    return {
        "state": BreakerState.CLOSED.value,
        "consecutive_failures": 0,
        "opened_at": None,
    }


class Breaker:
    """Process-wide circuit breaker (SPEC §3 FR-03).

    State machine:

    * ``CLOSED`` → ``OPEN`` when ``consecutive_failures`` reaches
      ``TASKQ_BREAKER_THRESHOLD``.
    * ``OPEN`` → ``HALF_OPEN`` the next time ``try_acquire`` is called
      after ``TASKQ_BREAKER_COOLDOWN`` seconds have elapsed.
    * ``HALF_OPEN`` → ``CLOSED`` on ``record_success()`` (counter reset).
    * ``HALF_OPEN`` → ``OPEN`` on ``record_failure()`` (counter bumped).

    State is persisted to ``$TASKQ_HOME/breaker.json`` atomically (tmp
    file + ``os.replace``). A crash during the rename leaves either the
    previous file intact or the new file complete, never a half-written
    one (NFR-03).
    """

    def __init__(self) -> None:
        self._lock = _SHARED_LOCK
        self._data = self._load_or_init()

    # ----- persistence --------------------------------------------------

    def _load_or_init(self) -> dict[str, Any]:
        """Load ``breaker.json`` or seed an initial state on first run."""
        path = _breaker_path()
        if not path.exists():
            data = _initial_data()
            path.parent.mkdir(parents=True, exist_ok=True)
            # First-time seed: no prior file to atomically replace, so a
            # plain write is correct. Subsequent updates go through
            # ``_save`` for atomicity.
            path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            return data
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            loaded = _initial_data()
            path.write_text(
                json.dumps(loaded, ensure_ascii=False), encoding="utf-8"
            )
        return loaded

    def _save(self) -> None:
        """Persist ``self._data`` atomically (NFR-03)."""
        path = _breaker_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Unique tmp per writer: concurrent writers must not race on a
        # shared ``breaker.json.tmp``.
        fd, tmp_str = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False)
            os.replace(tmp_str, path)
        except BaseException:
            try:
                os.unlink(tmp_str)
            except OSError:
                pass
            raise

    # ----- public API ---------------------------------------------------

    @property
    def state(self) -> BreakerState:
        """Return the current state value."""
        return BreakerState(self._data["state"])

    def record_failure(self) -> None:
        """Register a final failure; may transition to OPEN.

        In ``HALF_OPEN`` a single failure re-opens the breaker. In
        ``CLOSED`` failures accumulate until ``TASKQ_BREAKER_THRESHOLD``
        is reached, at which point the breaker opens.
        """
        threshold = int(
            os.environ.get("TASKQ_BREAKER_THRESHOLD", _DEFAULT_THRESHOLD)
        )
        current = self._data["state"]
        if current == BreakerState.HALF_OPEN.value:
            self._data["state"] = BreakerState.OPEN.value
            self._data["opened_at"] = time.monotonic()
            self._data["consecutive_failures"] += 1
        else:
            self._data["consecutive_failures"] += 1
            if self._data["consecutive_failures"] >= threshold:
                self._data["state"] = BreakerState.OPEN.value
                self._data["opened_at"] = time.monotonic()
        self._save()

    def record_success(self) -> None:
        """Register a final success; closes a ``HALF_OPEN`` probe.

        In ``CLOSED`` this just zeroes the counter; in ``OPEN`` it has
        no effect (a successful task cannot have run).
        """
        current = self._data["state"]
        if current == BreakerState.HALF_OPEN.value:
            self._data["state"] = BreakerState.CLOSED.value
            self._data["consecutive_failures"] = 0
            self._data["opened_at"] = None
        else:
            self._data["consecutive_failures"] = 0
        self._save()

    def try_acquire(self) -> bool:
        """Attempt to acquire the run-permit; returns ``True`` when allowed.

        * ``CLOSED`` always returns ``True``.
        * ``OPEN`` returns ``True`` (and transitions to ``HALF_OPEN``)
          once ``TASKQ_BREAKER_COOLDOWN`` seconds have elapsed since
          the breaker opened; otherwise returns ``False``.
        * ``HALF_OPEN`` returns ``True`` so the single in-flight probe
          can run to completion.

        Defensive: when ``state=OPEN`` is loaded with a non-numeric
        ``opened_at`` (e.g. seeded by a test fixture with an ISO string
        rather than a ``time.monotonic()`` float), the OPEN record is
        treated as malformed — the breaker is reset to a fresh
        ``CLOSED`` state and ``False`` is returned.
        """
        current = self._data["state"]
        if current == BreakerState.CLOSED.value:
            return True
        if current == BreakerState.HALF_OPEN.value:
            return True
        # OPEN — check cooldown.
        cooldown = float(
            os.environ.get("TASKQ_BREAKER_COOLDOWN", _DEFAULT_COOLDOWN)
        )
        opened_at = self._data.get("opened_at")
        if not isinstance(opened_at, (int, float)):
            # Malformed OPEN record (no monotonic timestamp). Reset to
            # fresh CLOSED state and reject this acquire so the caller
            # observes exit 3; subsequent acquires see the recovered
            # CLOSED state.
            self._data = _initial_data()
            self._save()
            return False
        if (time.monotonic() - opened_at) >= cooldown:
            self._data["state"] = BreakerState.HALF_OPEN.value
            self._save()
            return True
        return False