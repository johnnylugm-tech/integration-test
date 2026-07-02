"""Secret-line redaction for stdout/stderr tails.

[FR-02] Citations:
- SPEC.md §4 NFR-03: "stdout_tail / stderr_tail 落盤前過濾
  (sk-[A-Za-z0-9_-]{8,}|token=\S+) 整行以 [REDACTED] 取代".
- SAD.md §2.3: `redact.redact` is line-wise replacement; stateless; deterministic.

[FR-02] This module is the sole chokepoint for secret redaction before
persistence (D-03: redact-before-persist ordering is invariant).
"""

from __future__ import annotations

import re


# [FR-02] SPEC.md §4 NFR-03: pattern anchored to the line start. A line that
# begins with an `sk-...` key (≥ 8 trailing chars) or with `token=...` is
# replaced in its entirety by `[REDACTED]`.
_REDACT_PATTERN = re.compile(r"^(sk-[A-Za-z0-9_-]{8,}|token=\S+)")
_REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    """Return `text` with secret-bearing lines replaced by `[REDACTED]`.

    [FR-02] SPEC.md §4 NFR-03 — line-wise replacement where any line matching
    `^(sk-[A-Za-z0-9_-]{8,}|token=\S+)` is replaced per line.
    """
    if not text:
        return text
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        # Strip trailing newline for matching; preserve it on output.
        stripped = line.rstrip("\n").rstrip("\r")
        if _REDACT_PATTERN.match(stripped):
            nl = line[len(stripped):]
            lines[i] = _REDACTED + nl
    return "".join(lines)