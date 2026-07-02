"""[NFR-03] Secret redaction helpers.

Citations:
    - SPEC.md S4 NFR-03: stdout/stderr lines containing a secret-shaped token
      (e.g. ``sk-abcdefgh1234``) MUST be replaced with ``[REDACTED]`` BEFORE
      the record is persisted to ``tasks.json``.
    - 02-architecture/TEST_SPEC.md: AC-NFR03-redact-replaced +
      AC-NFR03-redact-no-raw-leak.

The rule is intentionally narrow — the only token shape accepted in this
project is an ``sk-`` prefix followed by 8+ alnum characters. Adding more
patterns would expand the attack surface; the per-line gate in
``redact_text`` rejects what isn't matched.
"""
from __future__ import annotations

import re

# Sk- prefix + 8+ alphanumeric chars (token-style secret).
_SECRET_RE = re.compile(r"sk-[A-Za-z0-9]{8,}")
# Broader fallback: ``token=`` / ``key=`` style, in case future tasks echo them.
_KV_SECRET_RE = re.compile(r"(?im)^(.*\b(?:token|secret|key)\s*=\s*)(\S+).*$")

_REDACTED = "[REDACTED]"


def redact_line(line: str) -> str:
    """Redact one line. Returns the line unchanged if no secret pattern matches."""
    if not line:
        return line
    if _SECRET_RE.search(line):
        return _REDACTED
    m = _KV_SECRET_RE.match(line)
    if m:
        return f"{m.group(1)}{_REDACTED}"
    return line


def redact_text(text: str | None) -> str:
    """Redact each non-empty line of *text*. Lines without a secret pass through."""
    if not text:
        return ""
    return "\n".join(redact_line(line) for line in text.splitlines())
