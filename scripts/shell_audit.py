#!/usr/bin/env python3
"""NFR-02 shell=True audit. Excludes comments and ALL docstring content."""
import pathlib
import re
import sys

src_dir = sys.argv[1] if len(sys.argv) > 1 else "03-development/src"
hits = []

for p in sorted(pathlib.Path(src_dir).rglob("*.py")):
    text = p.read_text(encoding="utf-8")
    # Strip all triple-quoted strings (module/function/class docstrings).
    stripped = re.sub(r'"""[\s\S]*?"""', "", text)
    stripped = re.sub(r"'''[\s\S]*?'''", "", stripped)
    for i, line in enumerate(stripped.splitlines(), 1):
        if re.search(r"shell\s*=\s*True", line):
            hits.append(f"{p}:{i}: {line.rstrip()}")

if hits:
    print("NFR-02 FAIL: shell=True used in code (not comment/docstring):")
    for h in hits:
        print(f"  {h}")
    sys.exit(1)
print(f"NFR-02 OK: shell=True absent from {src_dir}/")