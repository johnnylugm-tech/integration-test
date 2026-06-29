"""Command validation per SPEC.md §3 FR-01 驗證規則.

[FR-01] Citations:
- SPEC.md §3 FR-01 驗證規則 row 1 — 命令為空或全空白 → 拒絕.
- SPEC.md §3 FR-01 驗證規則 row 2 — 命令 > 1000 字元 → 拒絕 (1000 接受).
- SPEC.md §3 FR-01 驗證規則 row 3 / NFR-02 — 含 ; | & $ > < ` 任一 → 拒絕.

Returns ``(ok, err)`` — ``ok`` is True iff the command passes every rule;
``err`` is the human-readable rejection reason (empty string on success).
The boundary "exit 2 + stderr" is owned by the CLI layer per SPEC.md §3 FR-01.
"""
from __future__ import annotations

from taskq.core.models import INJECTION_FORBIDDEN

_MAX_LEN = 1000


def validate_command(cmd: str) -> tuple[bool, str]:
    """Apply FR-01 validation rules in order.

    [FR-01] Citations: SPEC.md §3 FR-01 驗證規則 rows 1-3 + NFR-02.
    """
    if not cmd or not cmd.strip():
        return False, "command is empty or whitespace"
    if len(cmd) > _MAX_LEN:
        return False, f"command length {len(cmd)} exceeds limit {_MAX_LEN}"
    for ch in cmd:
        if ch in INJECTION_FORBIDDEN:
            return False, f"command contains forbidden character: {ch!r}"
    return True, ""