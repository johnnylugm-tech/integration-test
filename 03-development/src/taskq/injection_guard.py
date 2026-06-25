"""Command injection guard — NFR-02.

[FR-01] [NFR-02] Pure scan over a command string, rejecting shell-injection
characters that appear OUTSIDE quoted spans. Single-quoted and double-quoted
runs are exempt; everything else is checked against the blacklist.

This module is intentionally side-effect-free (no I/O, no globals beyond the
immutable blacklist constant) so it can be unit-tested in isolation and reused
by any entry point that accepts a command string.
"""
from __future__ import annotations

import sys

# FR-01 injection character blacklist (NFR-02).
_INJECTION_CHARS: frozenset[str] = frozenset(";|&$><`")


def check_injection(command: str) -> None:
    """Raise SystemExit(2) if `command` contains injection chars outside quotes.

    [FR-01] [NFR-02] Walks the string once with a two-flag quote tracker.
    Characters in `_INJECTION_CHARS` that fall in unquoted regions trigger a
    diagnostic to stderr and a SystemExit(2) — never silently accepted.

    Args:
        command: the full command line the user wants to execute.

    Raises:
        SystemExit: with code 2 when a forbidden character is found.
    """
    in_single = False
    in_double = False
    for ch in command:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double and ch in _INJECTION_CHARS:
            print(
                f"error: command contains forbidden character {ch!r}",
                file=sys.stderr,
            )
            raise SystemExit(2)
