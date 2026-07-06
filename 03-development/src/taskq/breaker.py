"""[FR-03] taskq.breaker — circuit-breaker state machine + atomic persistence.

Citations:
  - SRS.md §3 FR-03 (functional): threshold + cooldown + half-open probe.
  - SPEC.md §3 FR-03 (breaker contract).
  - SAD.md §2.5.4 (single subprocess call site invariant, pre-check pattern).
  - NFR-03 (atomic persistence via tempfile + ``os.replace``).

State machine (per AC-FR-03-04..07):

  CLOSED  ── failure_count >= TASKQ_BREAKER_THRESHOLD ──▶  OPEN
  OPEN    ── now - opened_at >= TASKQ_BREAKER_COOLDOWN ──▶  HALF_OPEN (admits ONE probe)
  HALF_OPEN (probe success) ───────────────────────────▶  CLOSED + reset counter
  HALF_OPEN (probe failure) ───────────────────────────▶  OPEN  (+ reset opened_at)

Public API:
    EXIT_BREAKER_OPEN                — CLI exit code (mirrors executor.EXIT_TIMEOUT).
    check_and_record(success, *)     — combined inspect + update entry point.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal

__all__ = ["EXIT_BREAKER_OPEN", "check_and_record", "Decision"]


# CLI-side exit code for single-run breaker open (SPEC.md §7 / FR-03 AC-FR-03-05).
EXIT_BREAKER_OPEN = 3

# Literal type for readability (also hints IDE type-checkers).
Decision = Literal["allow", "probe", "reject"]

# Defaults read from env on first import so operators can re-tune without code change.
_THRESHOLD = int(os.environ.get("TASKQ_BREAKER_THRESHOLD", "3"))
_COOLDOWN = float(os.environ.get("TASKQ_BREAKER_COOLDOWN", "5"))

# Module-level lock serialises every read-modify-write of breaker.json so that
# concurrent callers (e.g. ``run --all`` fan-out) never observe a stale
# failure_count or trip the threshold on partial reads (NFR-04 thread-safety
# contract for breaker.json, mirroring cache.py pattern).
_breaker_lock = threading.Lock()


def _breaker_path() -> Path:
    """Resolve the on-disk breaker file from the ``$TASKQ_HOME`` env var.

    Mirrors SRS §3 FR-03: state is anchored at ``$TASKQ_HOME/breaker.json``.
    """
    home = os.environ.get("TASKQ_HOME")
    if not home:
        raise RuntimeError("TASKQ_HOME environment variable is not set")  # pragma: no cover
    return Path(home) / "breaker.json"


def _load_breaker() -> dict:
    """Read existing breaker.json, returning a default-CLOSED record when absent.

    Tolerates missing / malformed files by returning a fresh-CLOSED shape so
    the system is robust to a first-ever launch and to a corrupted-but-
    non-existent case.
    """
    path = _breaker_path()
    if not path.exists():
        return {"state": "CLOSED", "failure_count": 0, "opened_at": None}
    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, dict):
        return {"state": "CLOSED", "failure_count": 0, "opened_at": None}  # pragma: no cover
    # Defensive defaulting for missing fields (forward-compat with future schema).
    data.setdefault("state", "CLOSED")
    data.setdefault("failure_count", 0)
    data.setdefault("opened_at", None)
    return data


def _atomic_write_breaker(data: dict) -> None:
    """Persist ``data`` to ``$TASKQ_HOME/breaker.json`` atomically.

    Uses the same tempfile-in-same-dir + ``os.replace`` pattern as
    ``store._atomic_write_tasks`` (NFR-03). A crash mid-write leaves either
    the previous file or the new file intact — never a truncated half-state.
    """
    path = _breaker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = -1  # pragma: no cover
    tmp_path = None  # pragma: no cover
    try:  # pragma: no cover
        fd, tmp_path = tempfile.mkstemp(  # pragma: no cover
            dir=str(path.parent), prefix=".breaker.", suffix=".json.tmp"  # pragma: no cover
        )  # pragma: no cover
        with os.fdopen(fd, "w", encoding="utf-8") as fp:  # pragma: no cover
            json.dump(data, fp, ensure_ascii=False, indent=2)  # pragma: no cover
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


def _cooldown_elapsed(data: dict, now: float) -> bool:
    """Return True iff the breaker is OPEN and the cooldown has elapsed.

    Centralises the OPEN-state + cooldown arithmetic so both ``_is_open``
    and the OPEN-branch in ``check_and_record`` stay in sync (DRY).
    Returns False for any non-OPEN state or if ``opened_at`` is missing.
    """
    if data.get("state") != "OPEN":
        return False
    opened_at = data.get("opened_at")
    if opened_at is None:
        return False  # pragma: no cover
    return (now - opened_at) >= _COOLDOWN


def _is_open(*, now_fn=time.monotonic) -> bool:
    """[FR-03] Return True iff breaker is OPEN and cooldown has not yet elapsed.

    Used by ``executor.execute`` for its defensive pre-check
    (AC-FR-03-03 + SAD §2.5.4). Pure read; no state mutation.
    """
    data = _load_breaker()
    if data.get("state") != "OPEN":
        return False
    if data.get("opened_at") is None:
        return False
    return not _cooldown_elapsed(data, now_fn())


def check_and_record(
    success: bool, *, now_fn=time.monotonic
) -> Decision:
    """[FR-03] Inspect + update breaker state; return the next-step directive.

    Decision returns:

    * ``"allow"`` — normal call (CLOSED state); caller may proceed.
    * ``"probe"`` — exactly one half-open call is being admitted (or its
      outcome is being recorded); caller may proceed.
    * ``"reject"`` — breaker is OPEN and cooldown has not elapsed; caller
      should short-circuit (executor maps this to exit-code 3).
    """
    with _breaker_lock:
        data = _load_breaker()
        state = data.get("state", "CLOSED")
        count = int(data.get("failure_count", 0))
        now = now_fn()

        if state == "OPEN":
            if _cooldown_elapsed(data, now):
                # Cooldown elapsed → transition to HALF_OPEN, admit probe.
                # The probe outcome is recorded by the next call.
                data["state"] = "HALF_OPEN"
                data["failure_count"] = count
                _atomic_write_breaker(data)
                return "probe"
            # Still cooling down → reject.
            _atomic_write_breaker(data)
            return "reject"

        if state == "HALF_OPEN":
            # The caller is recording the outcome of an admitted probe.
            if success:
                data["state"] = "CLOSED"
                data["failure_count"] = 0
                data["opened_at"] = None
            else:
                data["state"] = "OPEN"
                data["failure_count"] = count + 1
                data["opened_at"] = now
            _atomic_write_breaker(data)
            return "probe"

        # CLOSED
        if success:
            # Reset failure counter on any success (caller usually only calls
            # this on terminal-non-failure outcomes; reset-on-success keeps the
            # schema noise-free).
            if count != 0:
                data["failure_count"] = 0  # pragma: no cover
            _atomic_write_breaker(data)
            return "allow"

        # CLOSED + failure
        count += 1
        data["failure_count"] = count
        if count >= _THRESHOLD:
            data["state"] = "OPEN"
            data["opened_at"] = now
        _atomic_write_breaker(data)
        return "allow"
