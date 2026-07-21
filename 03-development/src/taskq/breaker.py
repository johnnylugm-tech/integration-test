"""[FR-03] Circuit breaker — global, cross-task, cross-process state.

The breaker persists to ``$TASKQ_HOME/breaker.json`` (atomic write). It
tracks consecutive final-failures (``failed`` or ``timeout``) and trips
to ``OPEN`` once the count reaches ``TASKQ_BREAKER_THRESHOLD``. While
``OPEN``, every ``run`` is rejected with exit 3 + stderr ``breaker open``
and no subprocess is spawned. After ``TASKQ_BREAKER_COOLDOWN`` seconds
elapse, a single ``HALF_OPEN`` probe is admitted: success closes the
breaker and resets the counter, failure re-opens with a fresh cooldown.

Citations:
  SPEC §3 FR-03 (circuit-breaker state machine, threshold/cooldown envs).
  SPEC §8 line 212 (persistence contract — atomic write of breaker.json).
"""

from __future__ import annotations

import json
import os
import time
from enum import Enum
from pathlib import Path


class BreakerState(str, Enum):
    """Circuit-breaker states per SPEC §3 FR-03."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


# Defaults chosen so a single task's failure under FR-03 retry does NOT
# trip the breaker in tests that don't pin ``TASKQ_BREAKER_THRESHOLD``.
_DEFAULT_THRESHOLD: int = 5
_DEFAULT_COOLDOWN: float = 60.0


def breaker_path() -> Path:
    """Return ``$TASKQ_HOME/breaker.json`` (used when caller doesn't pin a path)."""
    home = os.environ.get("TASKQ_HOME")
    return (Path(home) if home else Path(".")) / "breaker.json"


def threshold() -> int:
    """Resolve ``$TASKQ_BREAKER_THRESHOLD`` (>= 1); fall back to the default."""
    raw = os.environ.get("TASKQ_BREAKER_THRESHOLD")
    if raw is None or raw.strip() == "":
        return _DEFAULT_THRESHOLD
    return max(1, int(raw))


def cooldown() -> float:
    """Resolve ``$TASKQ_BREAKER_COOLDOWN`` (seconds); fall back to the default."""
    raw = os.environ.get("TASKQ_BREAKER_COOLDOWN")
    if raw is None or raw.strip() == "":
        return _DEFAULT_COOLDOWN
    return float(raw)


class Breaker:
    """Persistent circuit breaker.

    State transitions:

    * ``CLOSED`` → ``OPEN`` when ``consecutive_failures >= threshold``.
    * ``OPEN`` → ``HALF_OPEN`` once ``time.time() - opened_at >= cooldown``
      (this transition is in-memory; the on-disk state stays ``OPEN`` until
      the probe resolves).
    * ``HALF_OPEN`` → ``CLOSED`` on probe success (counter reset to 0).
    * ``HALF_OPEN`` → ``OPEN`` on probe failure (fresh ``opened_at``).
    """

    def __init__(
        self,
        threshold_value: int | None = None,
        cooldown_value: float | None = None,
        path: Path | None = None,
    ) -> None:
        self.threshold = max(1, int(threshold_value if threshold_value is not None else threshold()))
        self.cooldown = float(cooldown_value if cooldown_value is not None else cooldown())
        self.path = path or breaker_path()
        self.state: BreakerState = BreakerState.CLOSED
        self.consecutive_failures: int = 0
        self.opened_at: float | None = None
        self._load()

    def _load(self) -> None:
        """Read the on-disk breaker state. Missing/corrupt file ⇒ CLOSED."""
        if not self.path.exists():
            self.state = BreakerState.CLOSED
            self.consecutive_failures = 0
            self.opened_at = None
            return
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            self.state = BreakerState.CLOSED
            self.consecutive_failures = 0
            self.opened_at = None
            return
        if not isinstance(data, dict):
            self.state = BreakerState.CLOSED
            self.consecutive_failures = 0
            self.opened_at = None
            return
        try:
            self.state = BreakerState(data.get("state", "CLOSED"))
        except ValueError:
            self.state = BreakerState.CLOSED
        self.consecutive_failures = int(data.get("consecutive_failures", 0) or 0)
        opened_at = data.get("opened_at")
        self.opened_at = float(opened_at) if opened_at is not None else None

    def _save(self) -> None:
        """Atomically persist state + counter (+ opened_at when set)."""
        payload: dict[str, object] = {
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
        }
        if self.opened_at is not None:
            payload["opened_at"] = self.opened_at
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload))
        try:
            os.replace(tmp, self.path)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise

    def before_run(self) -> bool:
        """Return True if a run is admitted; may transition ``OPEN → HALF_OPEN``."""
        if self.state == BreakerState.CLOSED:
            return True
        if self.state == BreakerState.OPEN:
            if (
                self.opened_at is not None
                and (time.time() - self.opened_at) >= self.cooldown
            ):
                # Cooldown elapsed → allow one probe (HALF_OPEN). The on-disk
                # state stays OPEN until the probe resolves (NFR-03 invariant:
                # never half-write the breaker file).
                self.state = BreakerState.HALF_OPEN
                return True
            return False
        # HALF_OPEN — a probe is already in flight; reject further runs.
        return False

    def record_success(self) -> None:
        """A terminal ``done`` ⇒ close the breaker and reset the counter."""
        self.state = BreakerState.CLOSED
        self.consecutive_failures = 0
        self.opened_at = None
        self._save()

    def record_failure(self) -> None:
        """A terminal ``failed``/``timeout`` ⇒ bump counter / trip / reopen."""
        if self.state == BreakerState.HALF_OPEN:
            # Probe failed → reopen with a fresh cooldown window.
            self.state = BreakerState.OPEN
            self.opened_at = time.time()
            self._save()
            return
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.threshold:
            self.state = BreakerState.OPEN
            self.opened_at = time.time()
        self._save()
