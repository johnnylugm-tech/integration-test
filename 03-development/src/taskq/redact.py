"""[FR-03] taskq.redact — line-level secret scrubber for NFR-03.

Citations:
- 03-development/tests/test_fr03.py:17-22 (redact contract)
- 03-development/tests/test_fr03.py:392-457 (unit tests: sk-/token= replacement)
- 03-development/tests/test_fr03.py:460-484 (integration: secret on disk)
- SRS.md:104-107 (NFR-03 stdout_tail/stderr_tail 落盤前 redaction)
"""
from __future__ import annotations

import re

# sk-* token: 8+ chars of alnum / dash / underscore after the prefix.
# token= assignment: any non-whitespace run after `token=`.
_SECRET_LINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"token=\S+"),
)


def redact(text: str) -> str:
    """Return ``text`` with every secret-bearing line replaced by ``[REDACTED]``.

    A "secret line" is any line whose content matches one of:
      - ``sk-[A-Za-z0-9_-]{8,}`` (OpenAI-style key, ≥8 suffix chars)
      - ``token=...`` (assignment-style secret, any non-whitespace value)

    Non-matching lines are preserved verbatim, including their trailing
    newline characters.

    Citations:
    - 03-development/tests/test_fr03.py:392-457 (unit tests)
    - SRS.md:104-107 (NFR-03 line-level redaction)
    """
    out_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if any(p.search(line) for p in _SECRET_LINE_PATTERNS):
            out_lines.append("[REDACTED]" + ("\n" if line.endswith("\n") else ""))
        else:
            out_lines.append(line)
    return "".join(out_lines)


__all__ = ["redact"]
