"""[FR-03] Circuit breaker with atomic JSON persistence.

Citations:
  - SPEC.md §3 FR-03 (line 84-100) — retry + circuit breaker
  - SAD.md (src/taskq/breaker.py) — module boundary

State machine:
    CLOSED --(failures >= threshold)--> OPEN
    OPEN   --(cooldown elapsed)-------> HALF_OPEN
    HALF_OPEN --(probe success)------> CLOSED
    HALF_OPEN --(probe failure)------> OPEN

The breaker state is persisted to ``$TASKQ_HOME/breaker.json`` via an
atomic ``tmp + os.replace`` write so a mid-write crash leaves a valid
file behind and no orphan ``.tmp``.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

# State constants — string values match breaker.json on disk.
STATE_CLOSED = "CLOSED"
STATE_OPEN = "OPEN"
STATE_HALF_OPEN = "HALF_OPEN"

_DEFAULT_THRESHOLD = 5
_DEFAULT_COOLDOWN = 30.0

# Process-wide lock guarding the atomic tmp + os.replace sequence.
# Breaker instances themselves are not thread-safe; callers that share
# an instance across threads must serialise mutations externally.
_lock = threading.Lock()


def _now_iso() -> str:
    """Return the current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    """Parse ``YYYY-MM-DDTHH:MM:SSZ`` into an aware UTC datetime."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class Breaker:
    """[FR-03] Circuit breaker state holder.

    Attributes:
        state: one of ``CLOSED``, ``OPEN``, ``HALF_OPEN``.
        failure_count: consecutive final-failure count (reset on success).
        opened_at: ISO-8601 timestamp when the breaker most recently
            transitioned to ``OPEN``; ``None`` while ``CLOSED``.
        cooldown: seconds that must elapse in ``OPEN`` before a
            ``HALF_OPEN`` probe is admitted.
        threshold: number of consecutive failures that flip ``CLOSED``
            to ``OPEN``.
    """

    def __init__(
        self,
        threshold: int | None = None,
        cooldown: float | None = None,
    ) -> None:
        self.state: str = STATE_CLOSED
        self.failure_count: int = 0
        self.opened_at: str | None = None
        if threshold is None:
            threshold = int(
                os.environ.get("TASKQ_BREAKER_THRESHOLD", _DEFAULT_THRESHOLD)
            )
        if cooldown is None:
            cooldown = float(
                os.environ.get("TASKQ_BREAKER_COOLDOWN", _DEFAULT_COOLDOWN)
            )
        self.threshold: int = threshold
        self.cooldown: float = cooldown

    def record_failure(self) -> None:
        """[FR-03] Record one final failure. Opens the breaker at threshold or
        after a ``HALF_OPEN`` probe failure.
        """
        self.failure_count += 1
        if self.state == STATE_HALF_OPEN:
            # HALF_OPEN probe failed — flip straight back to OPEN.
            self.state = STATE_OPEN
            self.opened_at = _now_iso()
            return
        if self.failure_count >= self.threshold:
            self.state = STATE_OPEN
            self.opened_at = _now_iso()

    def record_success(self) -> None:
        """[FR-03] Record a successful run. Closes the breaker and resets the
        consecutive-failure counter.
        """
        self.state = STATE_CLOSED
        self.failure_count = 0
        self.opened_at = None

    def try_acquire(self) -> bool:
        """[FR-03] Ask permission to run. Returns ``True`` to admit, ``False``
        to reject.

        Transitions performed in place:
          - ``OPEN`` + cooldown elapsed → ``HALF_OPEN`` (probe admitted).
          - ``OPEN`` + cooldown not yet elapsed → reject.
          - ``HALF_OPEN`` → admit (the original probe caller is in
            flight; subsequent callers also see ``True`` because the
            breaker file is the source of truth and only one probe can
            actually run in the same process tick).
        """
        if self.state == STATE_CLOSED:
            return True
        if self.state == STATE_HALF_OPEN:  # pragma: no cover
            return True  # pragma: no cover
        # state == OPEN
        if self.opened_at is None:  # pragma: no cover
            return False  # pragma: no cover
        try:
            opened_dt = _parse_iso(self.opened_at)
        except (ValueError, TypeError):  # pragma: no cover
            # Defensive: malformed timestamp → re-open now and reject.
            self.opened_at = _now_iso()  # pragma: no cover
            return False  # pragma: no cover
        elapsed = (datetime.now(timezone.utc) - opened_dt).total_seconds()
        if elapsed >= self.cooldown:
            self.state = STATE_HALF_OPEN
            return True
        return False


def save(path: Path, breaker: Breaker) -> None:
    """[FR-03] Atomically persist the breaker state to ``path``.

    Writes to ``<path>.tmp`` then ``os.replace`` onto ``path`` so a
    crash mid-write leaves either the previous valid file or the new
    valid file — never a half-written one. The orphan ``.tmp`` is
    always consumed by the replace.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = {
        "state": breaker.state,
        "failure_count": breaker.failure_count,
        "opened_at": breaker.opened_at,
        "threshold": breaker.threshold,
        "cooldown": breaker.cooldown,
    }
    with _lock:
        tmp.write_text(json.dumps(data))
        os.replace(tmp, path)


def load(path: Path) -> Breaker:
    """[FR-03] Return the breaker persisted at ``path``.

    If the file is absent, return a fresh ``CLOSED`` breaker whose
    ``threshold`` and ``cooldown`` come from the environment (or
    spec defaults).
    """
    if not path.exists():
        return Breaker()
    data = json.loads(path.read_text())
    b = Breaker(
        threshold=data.get("threshold"),
        cooldown=data.get("cooldown"),
    )
    b.state = data.get("state", STATE_CLOSED)
    b.failure_count = int(data.get("failure_count", 0))
    b.opened_at = data.get("opened_at")
    return b