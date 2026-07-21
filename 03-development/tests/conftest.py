"""Auto-wire ``$TASKQ_HOME`` for in-process ``cli.main([...])`` calls.

The ``taskq_home`` fixture in test_fr01.py is documented as the
"function-scoped $TASKQ_HOME directory" but only creates the directory and
returns its path — it does not export the path to ``os.environ``. The
subprocess path passes the env var explicitly via ``_make_env``, so it
works without this conftest. The in-process path (``cli.main([...])`` in
the parent interpreter) needs ``TASKQ_HOME`` set in the parent process,
otherwise it falls back to ``cwd`` and never sees the seeded fixtures.

This autouse fixture reuses the same per-test path that the explicit
``taskq_home`` fixture creates (``tmp_path / "taskq_home"``) and binds it
to ``TASKQ_HOME`` via ``monkeypatch``. It does NOT ``mkdir`` (the test's
fixture does that without ``exist_ok=True``, so a second ``mkdir`` would
race-fail); it assumes any test using the cli in-process is paired with
the ``taskq_home`` fixture (every test in test_fr01.py is).
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _export_taskq_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path / "taskq_home"))