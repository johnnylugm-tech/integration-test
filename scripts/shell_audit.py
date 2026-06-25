#!/usr/bin/env python3
"""NFR-02 shell=True audit. Delegates to harness core.audit.audit_grep so
docstring stripping logic is shared with every future audit (os.system,
eval, pickle.loads, …). Add new forbidden-API audits by following the
same pattern in scripts/ — no need to reimplement docstring handling."""
import pathlib
import re
import sys

# Path setup so this works whether invoked from project root (scripts/ is
# on sys.path implicitly) or from anywhere else.
_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO / "harness"))
sys.path.insert(0, str(_REPO))

from core.audit import audit_grep  # noqa: E402

src_dir = sys.argv[1] if len(sys.argv) > 1 else "03-development/src"

# shell=True is the only NFR-02 keyword we check today; future audits
# (os.system, eval, …) follow the same one-line pattern.
hits = audit_grep(
    pathlib.Path(src_dir),
    re.compile(r"shell\s*=\s*True"),
    exclude_docstrings=True,
    exclude_comments=False,
)

if hits:
    print("NFR-02 FAIL: shell=True used in code (not comment/docstring):")
    for h in hits:
        print(f"  {h.path}:{h.line_no}: {h.line_text}")
    sys.exit(1)
print(f"NFR-02 OK: shell=True absent from {src_dir}/")