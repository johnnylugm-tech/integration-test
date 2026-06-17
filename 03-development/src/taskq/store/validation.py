"""[FR-01] Command validation.

Citations:
- 03-development/tests/test_fr01.py:16-19 (INJECTION_CHARS/MAX_COMMAND_LENGTH/ValidationError contract)
- SRS.md:1-22 (非空/長度/注入字元 三條驗證規則)
- NFR-02 (注入字元黑名單)
"""
from __future__ import annotations

# 6 個注入字元:NFR-02 黑名單
INJECTION_CHARS = ";|&$><`"
# 03-development/tests/test_fr01.py:166 鎖定 ==  "; | & $ > < `"
assert INJECTION_CHARS == ";|&$><`", "INJECTION_CHARS contract must be exactly 6 chars"

MAX_COMMAND_LENGTH = 1000
# 03-development/tests/test_fr01.py:140-149 邊界:1000 接受、1001 拒絕


class ValidationError(Exception):
    """Raised when a submitted command violates one of the validation rules.

    Citations:
    - 03-development/tests/test_fr01.py:19 (ValidationError contract)
    """


def validate_command(command: str) -> None:
    """Validate a command string per FR-01 rules. Raise ValidationError on failure.

    Citations:
    - 03-development/tests/test_fr01.py:16 (validate_command contract)
    - SRS.md:1-22 (非空/全空白/長度/注入字元)
    """
    # 非空 + 全空白 → 拒絕
    if not command or not command.strip():
        raise ValidationError("command must not be empty")
    # 長度 > 1000 → 拒絕
    if len(command) > MAX_COMMAND_LENGTH:
        raise ValidationError(
            f"command length {len(command)} exceeds max {MAX_COMMAND_LENGTH}"
        )
    # 注入字元黑名單 → 拒絕
    for ch in INJECTION_CHARS:
        if ch in command:
            raise ValidationError(f"command contains forbidden injection char: {ch!r}")
