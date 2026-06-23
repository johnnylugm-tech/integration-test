"""taskq circuit breaker — global FSM with atomic persistence.

[FR-03] Implements the circuit breaker pattern:
    CLOSED → OPEN (after threshold consecutive final failures)
    OPEN → HALF_OPEN (after cooldown seconds)
    HALF_OPEN → CLOSED (on success, counter zeroed)
    HALF_OPEN → OPEN (on failure)

State is persisted atomically to $TASKQ_HOME/breaker.json (NFR-03).
All operations are thread-safe via a module-level Lock.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from typing import Optional

from taskq.config import Config, validate_config
from taskq.models import BreakerRecord, BreakerState

_LOCK = threading.Lock()


class Breaker:
    """Circuit breaker FSM with persistent state in breaker.json.

    [FR-03] Tracks consecutive final failures across tasks and processes.
    Uses atomic writes (tmp + os.replace) for durability (NFR-03).
    """

    def __init__(self, cfg: Config) -> None:
        """Initialise the breaker with the given config.

        [FR-03] Config provides breaker_threshold and breaker_cooldown.
        """
        self._cfg = cfg

    def _path(self) -> str:
        """Return the path to breaker.json.

        [FR-03] Stored in $TASKQ_HOME/breaker.json.
        """
        return os.path.join(self._cfg.home, "breaker.json")

    def _load(self) -> BreakerRecord:
        """Load breaker state from breaker.json; return defaults if absent/corrupt.

        [FR-03] Non-existent or corrupt file is treated as CLOSED/0 (safe default).
        """
        path = self._path()
        if not os.path.exists(path):
            return BreakerRecord()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            state = BreakerState(data.get("state", "CLOSED"))
            return BreakerRecord(
                state=state,
                consecutive_failures=int(data.get("consecutive_failures", 0)),
                opened_at=data.get("opened_at"),
            )
        except (json.JSONDecodeError, ValueError, OSError):
            return BreakerRecord()

    def _save(self, record: BreakerRecord) -> None:
        """Atomically write breaker state to breaker.json.

        [FR-03] [NFR-03] Uses tmp + os.replace for atomicity.
        """
        path = self._path()
        data = {
            "state": record.state.value,
            "consecutive_failures": record.consecutive_failures,
            "opened_at": record.opened_at,
        }
        dir_path = os.path.dirname(path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get_state(self) -> BreakerState:
        """Return the raw persisted FSM state (ignoring cooldown).

        [FR-03] Does NOT apply cooldown transition — use get_current_state()
        for time-aware state evaluation.
        """
        with _LOCK:
            record = self._load()
            return record.state

    def get_current_state(self) -> BreakerState:
        """Return the effective FSM state, applying cooldown if OPEN.

        [FR-03] If state is OPEN and opened_at + cooldown has elapsed,
        transitions to HALF_OPEN (persists the change).
        """
        with _LOCK:
            record = self._load()
            if record.state == BreakerState.OPEN:
                if record.opened_at is not None:
                    elapsed = time.time() - record.opened_at
                    if elapsed >= self._cfg.breaker_cooldown:
                        record = BreakerRecord(
                            state=BreakerState.HALF_OPEN,
                            consecutive_failures=record.consecutive_failures,
                            opened_at=record.opened_at,
                        )
                        self._save(record)
            return record.state

    def get_failure_count(self) -> int:
        """Return the current consecutive failure counter.

        [FR-03] Used to check whether the breaker is at/above threshold.
        """
        with _LOCK:
            record = self._load()
            return record.consecutive_failures

    def is_open(self) -> bool:
        """Return True if the breaker is currently OPEN (not HALF_OPEN or CLOSED).

        [FR-03] Callers use this to reject run requests with exit 3.
        Applies cooldown transition before evaluating.
        """
        return self.get_current_state() == BreakerState.OPEN

    def is_half_open(self) -> bool:
        """Return True if the breaker is currently HALF_OPEN.

        [FR-03] HALF_OPEN allows exactly one trial task through.
        """
        return self.get_current_state() == BreakerState.HALF_OPEN

    def record_success(self) -> None:
        """Record a successful task execution; reset counter and close if HALF_OPEN.

        [FR-03] In HALF_OPEN: → CLOSED + counter=0.
        In CLOSED: just reset counter to 0 (successive successes).
        """
        with _LOCK:
            record = self._load()
            if record.state in (BreakerState.HALF_OPEN, BreakerState.CLOSED):
                record = BreakerRecord(
                    state=BreakerState.CLOSED,
                    consecutive_failures=0,
                    opened_at=None,
                )
                self._save(record)

    def record_failure(self) -> None:
        """Record a final failure (retries exhausted); may open the breaker.

        [FR-03] Increments consecutive_failures. If it reaches breaker_threshold,
        transitions to OPEN. If already HALF_OPEN, re-opens.
        """
        with _LOCK:
            record = self._load()
            new_count = record.consecutive_failures + 1
            if record.state == BreakerState.HALF_OPEN or new_count >= self._cfg.breaker_threshold:
                # Open or re-open the breaker
                record = BreakerRecord(
                    state=BreakerState.OPEN,
                    consecutive_failures=new_count,
                    opened_at=time.time(),
                )
            else:
                record = BreakerRecord(
                    state=BreakerState.CLOSED,
                    consecutive_failures=new_count,
                    opened_at=None,
                )
            self._save(record)
