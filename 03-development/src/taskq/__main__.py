"""taskq CLI entry point — `python -m taskq`.

[ARCH] SAD §2.4: thin shim, forwards to the composition root in
`taskq.cli`. No business logic here — all command dispatch lives in
`taskq.cli`; query helpers (`status` / `list_tasks` / `clear`) live in
`taskq.query`.

[RE-EXPORT] Phase 3 tests reach into this module via
`taskq.__main__.<symbol>` for monkeypatching (e.g.
`monkeypatch.setattr(_main_mod, "run_task", fake)`) and for direct
unit coverage of CLI helpers. Those names are re-exported below so
existing tests stay green without modification.
"""

from __future__ import annotations

# Re-exports for backward compatibility with the Phase 3 / Phase 4 test
# suite that imports directly from `taskq.__main__`. The implementation
# lives in `taskq.cli` (per SAD §2.1) and `taskq.query` (per SAD §2.1).
#
# `run_task` is imported from `taskq.executor` here (NOT from `taskq.cli`)
# so that `cli.cmd_run`'s lazy call into `__main__.run_task` breaks the
# import cycle: tests monkeypatch `taskq.__main__.run_task` to drive
# `cmd_run` exit-code logic without spinning a real subprocess.
from taskq.cli import (  # noqa: F401 — re-exported for test monkeypatch + direct coverage
    _generate_task_id,
    build_parser,
    cmd_clear,
    cmd_list,
    cmd_run,
    cmd_status,
    cmd_submit,
    main,
)
from taskq.executor import run_task  # noqa: F401 — re-exported; cli.cmd_run calls via this module so monkeypatch.setattr(_main_mod, "run_task", ...) takes effect.
from taskq.query import (  # noqa: F401 — re-exported for direct unit coverage of FR-03 list preview constant
    LIST_COMMAND_PREVIEW_LEN,
)


if __name__ == "__main__":  # pragma: no cover — script entrypoint
    from taskq.cli import main as _cli_main
    import sys
    sys.exit(_cli_main())
