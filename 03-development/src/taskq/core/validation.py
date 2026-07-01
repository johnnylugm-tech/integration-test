r"""[FR-01]

Command validation for `taskq submit` (FR-01 §3 validation rules).

Citations:
- SPEC.md §3 FR-01 (rules: 非空, 長度 > 1000 chars, 注入字元 `;|&$><\``).
- SPEC.md §4 NFR-02 (security — injection blacklist MUST reject before write).

Design note:
    `cmd` may legally be `None` (matrix test feeds `None` as one
    reject-case), so every rule guards against non-string inputs as
    equivalent to "empty" — this keeps validation total without raising.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# SPEC.md §3 FR-01 row "注入字元" — verbatim character set.
_BLACKLIST = set(";|&$><`")

# SPEC.md §3 FR-01 row "長度" — strict `>` 1000.
_MAX_LEN = 1000


@dataclass(frozen=True)
class ValidationOutcome:
    ok: bool
    reason: str = ""


def validate(cmd: object) -> ValidationOutcome:
    """Return whether `cmd` passes FR-01 validation; never raises.

    Citations:
        - SPEC.md §3 FR-01 (all three rules + 任一違反 → exit 2).
    """
    if not isinstance(cmd, str):
        return ValidationOutcome(False, "command must be a non-empty string")

    if len(cmd) == 0 or cmd.strip() == "":
        return ValidationOutcome(False, "command must be a non-empty string")

    if len(cmd) > _MAX_LEN:
        return ValidationOutcome(False, f"command exceeds {_MAX_LEN} characters")

    hit: Optional[str] = next((ch for ch in cmd if ch in _BLACKLIST), None)
    if hit is not None:
        return ValidationOutcome(False, f"disallowed character: {hit!r}")

    return ValidationOutcome(True)
