"""Global circuit breaker over consecutive final task failures.

[FR-03]
Citations: SPEC.md line 91 (FR-03 breaker: threshold/cooldown env vars,
               OPEN/HALF_OPEN/CLOSED state machine, breaker.json persistence),
           SPEC.md line 151-152 (TASKQ_BREAKER_THRESHOLD=3 / COOLDOWN=5.0 defaults),
           SAD.md line 176 (Breaker.allow()/record() signature),
           SAD.md line 267-268 (breaker.json shape).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from taskq.core.models import utcnow_iso

BREAKER_FILENAME = "breaker.json"

STATE_CLOSED = "CLOSED"
STATE_OPEN = "OPEN"
STATE_HALF_OPEN = "HALF_OPEN"


class Breaker:
    """Atomic, file-backed circuit breaker rooted at $TASKQ_HOME/breaker.json.

    [FR-03]
    Global (not per-task) consecutive-final-failure counter. `allow()` must
    be consulted before executing a task; `record()` reports the final
    outcome (after retries are exhausted) so the state machine can transition.

    Citations: SAD.md line 176 (allow/record), SPEC.md line 91-94 (state machine).
    """

    def __init__(self, home: Path, *, threshold: int, cooldown: float) -> None:
        self.home = Path(home)
        self.path = self.home / BREAKER_FILENAME
        self.threshold = threshold
        self.cooldown = cooldown

    def _load(self) -> dict:
        """Load breaker state from disk, defaulting to CLOSED if absent/empty.

        [FR-03]
        Citations: SAD.md line 267 (breaker.json shape).
        """
        if not self.path.exists():
            return {"version": 1, "state": STATE_CLOSED, "failure_count": 0, "opened_at": None}
        text = self.path.read_text()
        if not text.strip():
            return {"version": 1, "state": STATE_CLOSED, "failure_count": 0, "opened_at": None}
        return json.loads(text)

    def _save(self, data: dict) -> None:
        """Persist breaker state atomically via temp file + os.replace.

        [FR-03, NFR-03]
        Citations: SPEC.md line 91 (state persisted atomically),
                   SAD.md line 82 (atomic write pattern shared with store).
        """
        self.home.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".breaker-", suffix=".json.tmp", dir=str(self.home)
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
        except BaseException:  # pragma: no cover — defensive cleanup; requires fs failure mid-rename
            try:
                os.unlink(tmp_path)
            except OSError:  # pragma: no cover — defensive swallow if temp already gone
                pass
            raise

    def allow(self) -> bool:
        """Return whether a `run` may proceed, per the current breaker state.

        [FR-03]
        CLOSED and HALF_OPEN both permit. OPEN permits only once `cooldown`
        seconds have elapsed since the file's last write, at which point the
        state is persisted as HALF_OPEN to admit the next probe.

        Citations: SPEC.md line 93-94 (OPEN reject; cooldown -> HALF_OPEN probe).
        """
        data = self._load()
        state = data.get("state", STATE_CLOSED)
        if state in (STATE_CLOSED, STATE_HALF_OPEN):
            return True
        # OPEN: use the file's mtime as the OPENED instant reference. This
        # means both runtime-opened files (record() set opened_at = now) and
        # externally-pre-seeded files (any opened_at value, including stale
        # ones from a previous process) are treated as "freshly loaded" —
        # the cooldown clock starts at the file's last write, not at the
        # possibly-ancient pre-seeded timestamp. (SAD.md line 267-268.)
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return False
        elapsed = time.time() - mtime
        if elapsed < self.cooldown:
            return False
        data["state"] = STATE_HALF_OPEN
        self._save(data)
        return True

    def record(self, success: bool) -> None:
        """Report a final task outcome (post-retry) and update the state machine.

        [FR-03]
        Success resets to CLOSED with failure_count=0. Failure while HALF_OPEN
        re-opens immediately with a fresh cooldown window. Failure while CLOSED
        increments the consecutive counter and opens once it reaches `threshold`.

        Citations: SPEC.md line 92-94 (threshold -> OPEN; HALF_OPEN failure -> OPEN).
        """
        data = self._load()
        if success:
            data["state"] = STATE_CLOSED
            data["failure_count"] = 0
            data["opened_at"] = None
            self._save(data)
            return
        state = data.get("state", STATE_CLOSED)
        if state == STATE_HALF_OPEN:
            data["state"] = STATE_OPEN
            data["opened_at"] = utcnow_iso()
            self._save(data)
            return
        failure_count = int(data.get("failure_count", 0)) + 1
        data["failure_count"] = failure_count
        if failure_count >= self.threshold:
            data["state"] = STATE_OPEN
            data["opened_at"] = utcnow_iso()
        self._save(data)
