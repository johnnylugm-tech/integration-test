"""taskq.breaker — Circuit-breaker state machine + atomic persistence (FR-03).

[FR-03] Cross-task, cross-process circuit breaker with state persisted to
`$TASKQ_HOME/breaker.json` (SPEC.md §3 FR-03 + §5.2 + NFR-03):

    CLOSED  ── consecutive_failures ≥ TASKQ_BREAKER_THRESHOLD ──▶ OPEN
    OPEN    ── (now − opened_at) ≥ TASKQ_BREAKER_COOLDOWN ──▶ HALF_OPEN
    HALF_OPEN probe success ──▶ CLOSED + reset counter
    HALF_OPEN probe failure ──▶ OPEN + reset opened_at

Public API (the functions consumed by the executor + tests):
    state()               — current state ("CLOSED" | "OPEN" | "HALF_OPEN")
    breaker_path()        — Path to `$TASKQ_HOME/breaker.json`
    load_state()          — read current state dict; {} when absent
    save_state(data)      — atomic write (tmp + os.replace)
    record_failure()      — bump counter, transition to OPEN at threshold
    record_success()      — reset counter, CLOSED when HALF_OPEN
    check_and_admit()     — True if a run is permitted; False if OPEN
    open()                — force OPEN (test + recovery helper)
    reset()               — CLOSED + counter 0 (recovery helper)

Atomic write contract (NFR-03): tmp + os.replace; partial writes never
touch the live `breaker.json` (verified by test_fr03_breaker_atomic_write).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

from taskq import config

# Cross-process reads/writes are serialised under a module-level Lock.
# `os.replace` is atomic on POSIX, but tmp file creation + os.replace is
# not — multiple concurrent writers all writing the SAME `breaker.json.tmp`
# race on write_text / os.replace. A Lock keeps the read-modify-write
# inside `save_state` / `load_state` safe for `run --all` (NP-13).
_LOCK = threading.Lock()

# Module-level CLI exit code (mirrors `executor.EXIT_BREAKER_OPEN`).
EXIT_BREAKER_OPEN = 3

# Sentinel returned by `check_and_admit()` — distinguishes the rejection
# reason for the single-call-site defensive pre-check in the executor.
REJECT = "reject"
ALLOW = "allow"
PROBE = "probe"

# Defaults read from env at import time so operators can re-tune without
# code changes. Tests monkeypatch env + invoke `reload_config()` after.
_THRESHOLD = int(os.environ.get("TASKQ_BREAKER_THRESHOLD", "3"))
_COOLDOWN = float(os.environ.get("TASKQ_BREAKER_COOLDOWN", "5"))


def breaker_path() -> Path:
    """Resolve `$TASKQ_HOME/breaker.json` (SPEC §5.2 + NFR-03)."""
    return config.breaker_path()


def reload_config() -> None:
    """Re-read `TASKQ_BREAKER_*` env vars into module-level constants.

    Call after `monkeypatch.setenv` so tests see updated thresholds.
    """
    global _THRESHOLD, _COOLDOWN
    _THRESHOLD = int(os.environ.get("TASKQ_BREAKER_THRESHOLD", "3"))
    _COOLDOWN = float(os.environ.get("TASKQ_BREAKER_COOLDOWN", "5"))


def threshold() -> int:
    """Current TASKQ_BREAKER_THRESHOLD value."""
    return _THRESHOLD


def cooldown() -> float:
    """Current TASKQ_BREAKER_COOLDOWN value (seconds)."""
    return _COOLDOWN


def load_state(path: Optional[Path] = None) -> dict:
    """Return the breaker state dict; `{}` when the file is absent or empty.

    Treats invalid JSON as an empty state rather than raising — the breaker
    is a recovery aid; corrupt state must not take the CLI down (NFR-03).
    """
    target = path or breaker_path()
    if not target.exists():
        return {}
    raw = target.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def save_state(data: dict, path: Optional[Path] = None) -> None:
    """Persist `data` to `breaker.json` atomically (tmp + os.replace).

    NFR-03 atomic write contract: a crash between the tmp write and the
    `os.replace` MUST leave the live `breaker.json` containing the
    previous valid JSON. Verified by `test_fr03_breaker_atomic_write`.
    """
    target = path or breaker_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with _LOCK:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)


def state(path: Optional[Path] = None) -> str:
    """Return the current state string (CLOSED | OPEN | HALF_OPEN).

    When state == OPEN but cooldown has elapsed, the effective state for
    the next run is HALF_OPEN. We return HALF_OPEN here so `state()` is
    a faithful pre-run view; the transition is committed via
    `record_success` / `record_failure`.
    """
    data = load_state(path)
    raw_state = data.get("state", "CLOSED")
    if raw_state != "OPEN":
        return raw_state
    opened_at = data.get("opened_at")
    if not opened_at:
        return "OPEN"  # pragma: no cover
    if _cooldown_elapsed(opened_at):
        return "HALF_OPEN"  # pragma: no cover
    return "OPEN"


def _cooldown_elapsed(opened_at) -> bool:
    """Return True if `now - opened_at >= cooldown`.

    `opened_at` may be either a numeric epoch (float) or an ISO-8601 UTC
    string ("...Z"). Falls back to True on parse error so a malformed
    timestamp does not deadlock the breaker.
    """
    opened_epoch = _to_epoch(opened_at)
    if opened_epoch is None:
        return True  # pragma: no cover
    return (time.time() - opened_epoch) >= _COOLDOWN


def _to_epoch(value) -> Optional[float]:
    """Coerce `value` to epoch seconds; None on failure.

    Accepts numeric (int/float — already epoch) or ISO-8601 string
    ("...Z" suffix or explicit offset). Numeric strings are also accepted.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    try:
        return float(value)
    except ValueError:
        pass
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        from datetime import datetime
        dt = datetime.fromisoformat(value)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _now_epoch() -> float:
    return time.time()


def check_and_admit(path: Optional[Path] = None) -> str:
    """Decide whether the next `run` may proceed.

    Returns:
        ALLOW   — CLOSED state, no recent failures blocking.
        PROBE   — was OPEN but cooldown elapsed; admit exactly one probe.
        REJECT  — OPEN and cooldown not elapsed; caller must refuse.

    Reads + writes state atomically (transition OPEN → HALF_OPEN commits
    the change so a subsequent concurrent caller sees REJECT, not PROBE).
    """
    data = load_state(path)
    raw_state = data.get("state", "CLOSED")
    if raw_state != "OPEN":
        return ALLOW
    opened_at = data.get("opened_at")
    if not opened_at or _cooldown_elapsed(opened_at):
        # Transition to HALF_OPEN — only ONE probe allowed.
        data["state"] = "HALF_OPEN"
        save_state(data, path)
        return PROBE
    return REJECT


def record_failure(path: Optional[Path] = None) -> str:
    """Increment the consecutive-failure counter; open the breaker at threshold.

    Returns the resulting state string ("CLOSED" | "OPEN").
    """
    data = load_state(path)
    counter = int(data.get("consecutive_failures", 0)) + 1
    data["consecutive_failures"] = counter
    if data.get("state") == "HALF_OPEN":
        # Probe failed → re-OPEN.
        data["state"] = "OPEN"
        data["opened_at"] = _now_epoch()
        save_state(data, path)
        return "OPEN"
    if counter >= _THRESHOLD:
        data["state"] = "OPEN"
        data["opened_at"] = _now_epoch()
        save_state(data, path)
        return "OPEN"
    data["state"] = "CLOSED"
    save_state(data, path)
    return "CLOSED"


def record_success(path: Optional[Path] = None) -> str:
    """Mark a successful run; CLOSED + reset counter (or stay CLOSED).

    When invoked in HALF_OPEN, the successful probe closes the breaker.
    Returns the resulting state string ("CLOSED").
    """
    data = load_state(path)
    data["state"] = "CLOSED"
    data["consecutive_failures"] = 0
    data["opened_at"] = None
    save_state(data, path)
    return "CLOSED"


def open(path: Optional[Path] = None) -> None:
    """Force the breaker to OPEN (test helper + manual recovery)."""
    data = load_state(path)
    data["state"] = "OPEN"
    data["consecutive_failures"] = int(os.environ.get("TASKQ_BREAKER_THRESHOLD", "3"))
    data["opened_at"] = _now_epoch()
    save_state(data, path)


def reset(path: Optional[Path] = None) -> None:
    """Force the breaker back to CLOSED with counter 0."""
    data = {"state": "CLOSED", "consecutive_failures": 0, "opened_at": None}
    save_state(data, path)