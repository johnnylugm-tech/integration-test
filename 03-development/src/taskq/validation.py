"""Submit-command validation.

[FR-01] Citations:
- SPEC.md §3 FR-01 row 「非空」: `validate_command` empty/whitespace check.
- SPEC.md §3 FR-01 row 「長度」: `COMMAND_MAX_LENGTH` and length check.
- SPEC.md §3 FR-01 row 「注入字元」 / NFR-02: `INJECTION_CHARS` blacklist
  (``; | & $ > < ` ``) and injection check.
- SPEC.md §3 FR-01 preamble ("任一違反 → exit 2 + stderr 錯誤訊息,不寫入存儲"):
  `validate_command` returning a non-None error signals rejection.
"""

from __future__ import annotations


# [FR-01] SPEC.md §3 FR-01 row 「長度」: 命令 > 1000 字元 → 拒絕.
COMMAND_MAX_LENGTH = 1000


# [FR-01] SPEC.md §3 FR-01 row 「注入字元」 / NFR-02:
# 命令含 ; | & $ > < ` 任一 → 拒絕.
INJECTION_CHARS = frozenset(";|&$><`")


def validate_command(cmd: str) -> str | None:
    """Return None if `cmd` is acceptable, else a human-readable error.

    [FR-01] SPEC.md §3 FR-01 table rows 「非空」 / 「長度」 / 「注入字元」;
    preamble "任一違反 → exit 2 + stderr 錯誤訊息,不寫入存儲".
    """
    if cmd == "" or cmd.strip() == "":
        return "command must not be empty or whitespace"
    if len(cmd) > COMMAND_MAX_LENGTH:
        return (
            f"command length {len(cmd)} exceeds limit {COMMAND_MAX_LENGTH}"
        )
    if any(ch in INJECTION_CHARS for ch in cmd):
        return "command contains forbidden injection character"
    return None
