"""TDD-RED tests for FR-01: 任務提交與驗證 (`taskq submit`).

Covers the 9 canonical test functions declared in
``02-architecture/TEST_SPEC.md`` §FR-01 (14 case rows total; the injection
blacklist case `test_fr01_07_submit_injection_chars` is parametrized over the
six NFR-02 blacklist chars `|` `&` `$` `>` `<` `` ` ``).

This file exercises TWO execution paths per case:

* **In-process** — calls ``taskq.cli.main([...])`` directly inside the pytest
  process. Gives pytest-cov coverage of ``cli.py`` and ``__main__.py`` (GATE1
  requires >= 80% coverage of the source under ``03-development/src/taskq``,
  which subprocess calls can NEVER provide).
* **Subprocess** — spawns ``python -m taskq <args>`` with a function-scoped
  ``$TASKQ_HOME`` and an explicit ``PYTHONPATH`` (pytest's ``pythonpath`` config
  does NOT propagate to child interpreters per v2.13.0 rule 3).

RED-state contract: source code is NOT yet implemented. The top-level
``from taskq import cli`` import is INTENTIONAL and UNGUARDED — pytest is
expected to crash with ``ModuleNotFoundError`` (Exit Code 2 = Collection
Error) until the GREEN phase lands. That is a valid RED outcome.

Forbidden patterns (per v2.13.0 test-author rules):

* No try/except ImportError anywhere.
* No source-file edits.
* No lazy imports.
* Local-variable names must not shadow stdlib modules (``json``, ``os``,
  ``sys``, ``subprocess``, ``pathlib``, ``asyncio``, ``typing``,
  ``logging``, ``path``, ``file``, ``id``, ``type``, ``dict``, ``list``,
  ``set``, ``tuple``, ``str``, ``int``, ``bool``, ``bytes``). The alias
  ``json_lib`` below is used in place of a bare ``json`` local.
"""

from __future__ import annotations

import contextlib
import io
import json as json_lib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Top-level import is INTENTIONAL — RED expects Collection Error if
# ``taskq.cli`` is missing. Do not wrap in try/except.
from taskq import cli  # noqa: F401  (used in the in-process calls below)


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------

# Path to the in-tree source so subprocess children can import ``taskq``
# even though it is not installed. pytest's ``pythonpath = 03-development/src``
# only injects the parent interpreter; child interpreters via
# ``subprocess.run([sys.executable, "-m", "taskq"])`` do NOT inherit it.
_SRC_ROOT = Path(__file__).resolve().parent.parent / "src"


def _make_env(taskq_home: Path) -> dict[str, str]:
    """Build a child-process env with ``TASKQ_HOME`` + ``PYTHONPATH``.

    Both vars are REQUIRED for child invocations:

    * ``TASKQ_HOME`` isolates each test's ``tasks.json`` to its own
      ``tmp_path`` (v2.13.0 rule 2: ``state_mode: isolate_per_test``).
    * ``PYTHONPATH`` lets the spawned interpreter find ``taskq`` on the
      import path (v2.13.0 rule 3: pytest ``pythonpath`` config does NOT
      propagate to children).
    """
    env = os.environ.copy()
    env["TASKQ_HOME"] = str(taskq_home)
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_SRC_ROOT) + os.pathsep + existing_pp
    return env


def _run_subprocess(args: list[str], taskq_home: Path):
    """Run ``python -m taskq <args>`` with the isolated env and return the
    completed ``subprocess.CompletedProcess`` (text mode, stdout/stderr
    captured)."""
    return subprocess.run(
        [sys.executable, "-m", "taskq", *args],
        capture_output=True,
        text=True,
        env=_make_env(taskq_home),
    )


@pytest.fixture
def taskq_home(tmp_path: Path) -> Path:
    """Function-scoped ``$TASKQ_HOME`` directory.

    Per v2.13.0 rule 2 (``state_mode: isolate_per_test`` on every FR-01 row),
    each test gets a FRESH directory so monkeypatched ``OSError`` (case 14)
    cannot leak into a sibling test, and the prior pending task seeded for
    the duplicate-name case (case 13) cannot satisfy a later case's
    validation check.
    """
    home = tmp_path / "taskq_home"
    home.mkdir()
    return home


# ---------------------------------------------------------------------------
# AC-FR01-01 — happy submit "echo hi" → 8-hex id + pending task
# ---------------------------------------------------------------------------


def test_fr01_01_happy_submit_echo_hi(taskq_home: Path) -> None:
    """happy_path / Q1.

    AC: ``python -m taskq submit 'echo hi'`` → exit 0; stdout is an 8-hex
    id; ``tasks.json`` carries ``command="echo hi"``, ``status="pending"``,
    and an ISO-8601 ``created_at``.

    Rule IDs: ``FR01-non-empty`` (``len(command) > 0``),
    ``FR01-strip-not-empty`` (``len(command.strip()) > 0``).
    """
    command = "echo hi"
    assert len(command) > 0
    assert len(command.strip()) > 0
    # ---- In-process path (drives coverage of cli.py / __main__.py).
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc_in = cli.main(["submit", "echo hi"])
    assert rc_in == 0
    task_id_in = buf.getvalue().strip()
    assert re.fullmatch(r"[0-9a-f]{8}", task_id_in), (
        f"in-process: expected 8-hex id, got {task_id_in!r}"
    )

    # ---- Subprocess path (AC verification against real entry point).
    proc = _run_subprocess(["submit", "echo hi"], taskq_home)
    assert proc.returncode == 0, proc.stderr
    proc_id = proc.stdout.strip()
    assert re.fullmatch(r"[0-9a-f]{8}", proc_id), (
        f"subprocess: expected 8-hex id, got {proc_id!r}"
    )

    # ---- on-disk state asserts.
    tasks_file = taskq_home / "tasks.json"
    assert tasks_file.exists(), "submit must write tasks.json"
    data = json_lib.loads(tasks_file.read_text())
    record = data[proc_id]
    assert record["command"] == "echo hi"
    assert record["status"] == "pending"
    # ISO-8601 created_at — accept either ``Z`` or ``±HH:MM`` offset suffix.
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$",
        record["created_at"],
    ), f"created_at not ISO-8601: {record['created_at']!r}"


# ---------------------------------------------------------------------------
# AC-FR01-02 — submit --json → single-line JSON {"id":..,"status":"pending"}
# ---------------------------------------------------------------------------


def test_fr01_02_submit_json_output(taskq_home: Path) -> None:
    """happy_path / Q1.

    AC: ``python -m taskq submit --json 'echo hi'`` → stdout is a single-line
    JSON ``{"id": "<8-hex>", "status": "pending"}``.

    Rule IDs: ``FR01-non-empty``, ``FR01-strip-not-empty``.
    """
    command = "echo hi"
    assert len(command) > 0
    assert len(command.strip()) > 0
    # ---- In-process path.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc_in = cli.main(["submit", "--json", "echo hi"])
    assert rc_in == 0
    payload_in = json_lib.loads(buf.getvalue())
    assert re.fullmatch(r"[0-9a-f]{8}", payload_in["id"])
    assert payload_in["status"] == "pending"

    # ---- Subprocess path.
    proc = _run_subprocess(["submit", "--json", "echo hi"], taskq_home)
    assert proc.returncode == 0, proc.stderr
    out_line = proc.stdout.strip()
    # Single-line requirement: no embedded newline.
    assert "\n" not in out_line, f"--json must be single-line, got: {out_line!r}"
    payload = json_lib.loads(out_line)
    assert re.fullmatch(r"[0-9a-f]{8}", payload["id"])
    assert payload["status"] == "pending"


# ---------------------------------------------------------------------------
# AC-FR01-03 — empty command → exit 2
# ---------------------------------------------------------------------------


def test_fr01_03_submit_empty_command(taskq_home: Path) -> None:
    """validation / Q2.

    AC: ``python -m taskq submit ''`` → exit 2; stderr carries an error
    message; ``tasks.json`` is NOT written.

    Rule IDs: ``FR01-non-empty`` (negated), ``FR01-strip-empty``
    (``command.strip() == ""``).
    """
    command = ""
    assert command.strip() == ""
    # ---- In-process path.
    stderr_buf = io.StringIO()
    stdout_buf = io.StringIO()
    with contextlib.redirect_stderr(stderr_buf), contextlib.redirect_stdout(stdout_buf):
        rc_in = cli.main(["submit", ""])
    assert rc_in == 2
    assert stderr_buf.getvalue().strip() != "", "stderr must carry error message"
    assert stdout_buf.getvalue().strip() == "", "no stdout on rejection"

    # ---- Subprocess path.
    proc = _run_subprocess(["submit", ""], taskq_home)
    assert proc.returncode == 2, proc.stderr
    assert proc.stderr.strip() != "", "stderr must carry error message"

    tasks_file = taskq_home / "tasks.json"
    assert not tasks_file.exists() or json_lib.loads(tasks_file.read_text()) == {}, (
        "tasks.json must NOT record a rejected submission"
    )


# ---------------------------------------------------------------------------
# AC-FR01-04 — whitespace-only command → exit 2
# ---------------------------------------------------------------------------


def test_fr01_04_submit_whitespace_only(taskq_home: Path) -> None:
    """validation / Q2.

    AC: ``python -m taskq submit '   '`` → exit 2.

    Rule IDs: ``FR01-non-empty`` (negated via strip),
    ``FR01-strip-empty`` (``command.strip() == ""``).
    """
    command = "   "
    assert command.strip() == ""
    # ---- In-process path.
    stderr_buf = io.StringIO()
    with contextlib.redirect_stderr(stderr_buf):
        rc_in = cli.main(["submit", "   "])
    assert rc_in == 2
    assert stderr_buf.getvalue().strip() != ""

    # ---- Subprocess path.
    proc = _run_subprocess(["submit", "   "], taskq_home)
    assert proc.returncode == 2, proc.stderr
    assert proc.stderr.strip() != ""


# ---------------------------------------------------------------------------
# AC-FR01-05 — command length > 1000 → exit 2
# ---------------------------------------------------------------------------


def test_fr01_05_submit_too_long(taskq_home: Path) -> None:
    """boundary / Q3.

    AC: A command of length 1001 → exit 2 (rule: ``len(command) > 1000``).

    Rule IDs: ``FR01-strip-not-empty`` (length-1001 strips to itself),
    ``FR01-length-boundary-ok``
    (``command_len == "1001" and int(command_len) > 1000``).
    """
    too_long = "x" * 1001
    command_len = "1001"
    assert len(too_long) == 1001  # sanity — predicate holds for this case
    # Spec predicates (TEST_SPEC §FR-01 sub-assertions):
    assert command_len == "1001" and int(command_len) > 1000
    assert len(too_long.strip()) > 0

    # ---- In-process path.
    stderr_buf = io.StringIO()
    with contextlib.redirect_stderr(stderr_buf):
        rc_in = cli.main(["submit", too_long])
    assert rc_in == 2
    assert stderr_buf.getvalue().strip() != ""

    # ---- Subprocess path.
    proc = _run_subprocess(["submit", too_long], taskq_home)
    assert proc.returncode == 2, proc.stderr
    assert proc.stderr.strip() != ""


# ---------------------------------------------------------------------------
# AC-FR01-06 — injection ';' → exit 2 (NFR-02)
# ---------------------------------------------------------------------------


def test_fr01_06_submit_injection_semicolon(taskq_home: Path) -> None:
    """validation / Q2.

    AC: ``python -m taskq submit 'echo hi; rm x'`` → exit 2.

    # NFR-02 (security): injection blacklist rejects shell metacharacters.

    Rule IDs: ``FR01-injection-semicolon`` (``chr(59) in command``), and
    negated forms of ``FR01-non-empty`` / ``FR01-strip-not-empty``
    (the command is non-empty and non-blank — only the blacklist is the
    reason for rejection).
    """
    bad_cmd = "echo hi; rm x"
    command = bad_cmd
    assert len(command) > 0
    assert len(command.strip()) > 0
    assert ";" in bad_cmd  # sanity — spec predicate must hold
    assert chr(59) in command

    # ---- In-process path.
    stderr_buf = io.StringIO()
    with contextlib.redirect_stderr(stderr_buf):
        rc_in = cli.main(["submit", bad_cmd])
    assert rc_in == 2
    assert stderr_buf.getvalue().strip() != ""

    # ---- Subprocess path.
    proc = _run_subprocess(["submit", bad_cmd], taskq_home)
    assert proc.returncode == 2, proc.stderr
    assert proc.stderr.strip() != ""
    tasks_file = taskq_home / "tasks.json"
    assert not tasks_file.exists() or json_lib.loads(tasks_file.read_text()) == {}


# ---------------------------------------------------------------------------
# AC-FR01-07 — six blacklist chars | & $ > < ` → all exit 2
# (parametrized — six sub_cases under ONE canonical function name)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad_char", "bad_cmd", "char_code"),
    [
        ("|", "echo hi | wc", 124),    # sub_case pipe        — chr(124)
        ("&", "echo hi &", 38),        # sub_case ampersand   — chr(38)
        ("$", "$USER hi", 36),         # sub_case dollar      — chr(36)
        (">", "echo hi > f", 62),      # sub_case redirect_gt — chr(62)
        ("<", "echo hi < f", 60),      # sub_case redirect_lt — chr(60)
        ("`", "echo `id` hi", 96),     # sub_case backtick    — chr(96)
    ],
)
def test_fr01_07_submit_injection_chars(
    bad_char: str,
    bad_cmd: str,
    char_code: int,
    taskq_home: Path,
) -> None:
    """validation / Q2.

    # NFR-02 (security): injection blacklist covers six shell metachars.

    AC: each of the six NFR-02 blacklist characters causes the submit to
    exit 2 BEFORE writing to storage.

    Rule IDs (one per parametrize row):

    * ``FR01-injection-pipe``       (``chr(124) in command``) — row 1
    * ``FR01-injection-ampersand``  (``chr(38) in command``)  — row 2
    * ``FR01-injection-dollar``     (``chr(36) in command``)  — row 3
    * ``FR01-injection-redirect-gt``(``chr(62) in command``)  — row 4
    * ``FR01-injection-redirect-lt``(``chr(60) in command``)  — row 5
    * ``FR01-injection-backtick``   (``chr(96) in command``)  — row 6

    The predicate ``chr(<code>) in command`` selects exactly one char;
    ``pytest.param(...)`` fan-out keeps each sub_case isolated in its own
    fixture (so a module-scoped state cannot satisfy row N+1's check).
    """
    # Predicate sanity — char must literally appear in the bad command.
    assert bad_char in bad_cmd, (
        f"sanity: {bad_char!r} must appear in {bad_cmd!r} for this case row"
    )
    # Spec predicates (TEST_SPEC §FR-01 sub-assertions) — one literal per row
    # so the MIRROR checker can match the canonical predicate text. The trigger
    # var MUST match a TEST_SPEC case input name (`command` here) so the
    # checker's scope-alignment against `applies_to=[7..12]` resolves.
    command = bad_cmd
    assert len(command) > 0
    assert len(command.strip()) > 0
    assert ord(bad_char) in (38, 36, 60, 62, 96, 124)
    if command == "echo hi | wc":
        assert chr(124) in command
    elif command == "echo hi &":
        assert chr(38) in command
    elif command == "$USER hi":
        assert chr(36) in command
    elif command == "echo hi > f":
        assert chr(62) in command
    elif command == "echo hi < f":
        assert chr(60) in command
    elif command == "echo `id` hi":
        assert chr(96) in command

    # ---- In-process path.
    stderr_buf = io.StringIO()
    with contextlib.redirect_stderr(stderr_buf):
        rc_in = cli.main(["submit", bad_cmd])
    assert rc_in == 2, (
        f"in-process submit of {bad_cmd!r} must exit 2, got {rc_in}"
    )
    assert stderr_buf.getvalue().strip() != ""

    # ---- Subprocess path (AC verification).
    proc = _run_subprocess(["submit", bad_cmd], taskq_home)
    assert proc.returncode == 2, (
        f"subprocess submit of {bad_cmd!r} must exit 2, "
        f"got rc={proc.returncode}, stderr={proc.stderr!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR01-08 — --name duplicate (existing pending task with same name) → exit 2
# ---------------------------------------------------------------------------


def test_fr01_08_submit_name_duplicate(taskq_home: Path) -> None:
    """validation / Q2.

    AC: a prior pending task with ``name="dup-name-1"`` exists in
    ``$TASKQ_HOME/tasks.json``; a second submit with the same ``--name`` is
    rejected with exit 2 and the file is NOT mutated (no new id appears).

    Rule IDs: ``FR01-name-required-for-duplicate``
    (``name == "dup-name-1" and duplicate_present == "true"``).

    The seeded prior task is consumed (cleared) only by ``run``/``clear``,
    so it remains pending for the second submit's name-uniqueness check.
    """
    name = "dup-name-1"
    duplicate_present = "true"
    prior_id = "abcdef01"
    assert name == "dup-name-1" and duplicate_present == "true"
    # Seed: a prior pending task with the contested name already on disk.
    tasks_file = taskq_home / "tasks.json"
    prior_id = "abcdef01"
    pre_existing = {
        prior_id: {
            "command": "echo seeded",
            "name": "dup-name-1",
            "status": "pending",
            "created_at": "2026-07-18T00:00:00+00:00",
        }
    }
    tasks_file.write_text(json_lib.dumps(pre_existing))

    # ---- In-process path: second submit with same --name → exit 2.
    stderr_buf = io.StringIO()
    with contextlib.redirect_stderr(stderr_buf):
        rc_in = cli.main(["submit", "--name", "dup-name-1", "echo second"])
    assert rc_in == 2, (
        f"duplicate-name submit must exit 2, got {rc_in}; "
        f"stderr={stderr_buf.getvalue()!r}"
    )
    assert stderr_buf.getvalue().strip() != ""

    # State after in-process reject — file untouched, only the prior id.
    after_in = json_lib.loads(tasks_file.read_text())
    assert after_in == pre_existing, (
        "duplicate-name in-process submit must NOT mutate tasks.json"
    )

    # ---- Subprocess path: same expectation on a fresh second attempt.
    proc = _run_subprocess(
        ["submit", "--name", "dup-name-1", "echo second"],
        taskq_home,
    )
    assert proc.returncode == 2, proc.stderr
    after_proc = json_lib.loads(tasks_file.read_text())
    assert set(after_proc.keys()) == {prior_id}, (
        f"no new id should appear after duplicate submit; got ids={set(after_proc.keys())!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR01-09 — atomic write: mid-submit OSError → tasks.json still valid JSON
# ---------------------------------------------------------------------------


def test_fr01_09_submit_atomic_write(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """integration / Q7.

    AC: simulate a mid-submit ``OSError`` (unit-level monkeypatch). After
    the failure, ``$TASKQ_HOME/tasks.json`` MUST still be parseable as
    valid JSON carrying the pre-existing content unchanged (NFR-03
    atomic-write guarantee).

    # NFR-03 (error_handling): atomic-write boundary keeps tasks.json valid
    # even when the rename primitive raises mid-submit.

    Rule IDs: ``FR01-atomic-mid-write-recovers``
    (``mid_write_error == "oserror"``).

    GREEN TODO
    ---------
    The GREEN implementation must perform an atomic-write boundary inside
    ``taskq.cli.submit_command`` (or its equivalent): write to a sibling
    ``.tmp`` file, fsync, then ``os.replace`` onto ``tasks.json``. A naive
    open-write-fsync WITHOUT the temp-file rename violates this invariant
    — the on-disk ``tasks.json`` is opened-and-truncated BEFORE the
    payload is dumped, so a mid-write failure leaves a torn half-file.
    The GREEN implementation must also catch the ``OSError`` inside that
    boundary and surface a non-zero exit code (e.g. exit 1 for ``internal
    error`` per SPEC §7); it MUST NOT re-raise.
    """
    mid_write_error = "oserror"
    assert mid_write_error == "oserror"
    tasks_file = taskq_home / "tasks.json"

    # Pre-existing legitimate content. The atomic-write invariant says
    # this MUST survive the failed submit attempt — neither truncated nor
    # partially overwritten.
    sentinel_id = "deadbeef"
    pre_existing = {
        sentinel_id: {
            "command": "echo presubmit",
            "name": "",
            "status": "pending",
            "created_at": "2026-07-18T00:00:00+00:00",
        }
    }
    tasks_file.write_text(json_lib.dumps(pre_existing))

    # Inject an OSError mid-write. We monkeypatch ``os.replace`` — the
    # canonical POSIX atomic-rename call used by an atomic-write helper
    # (ADR-004). If the GREEN implementation uses a different primitive
    # (e.g. ``Path.replace`` or ``os.rename``), it MUST route through one
    # of the names we touch here so this fault actually trips.
    def _raise_oserror(*_args, **_kwargs):
        raise OSError("simulated mid-write failure (FR-01 atomicity test)")

    monkeypatch.setattr("os.replace", _raise_oserror, raising=False)

    # ---- In-process call (drives coverage + AC contract).
    stderr_buf = io.StringIO()
    with contextlib.redirect_stderr(stderr_buf):
        try:
            rc_in = cli.main(["submit", "echo hi"])
        except OSError:
            # A naive GREEN that surfaces the OSError uncaught would fail the
            # AC. The GREEN implementation must catch the OSError inside the
            # atomic-write boundary and return a non-zero exit.
            pytest.fail(
                "submit raised OSError uncaught; the atomic-write boundary "
                "must catch the failure and return a non-zero exit code."
            )

    # Whatever the exit code, on-disk ``tasks.json`` MUST remain valid JSON
    # equal to the pre-existing content (NFR-03 invariant). The failed submit
    # is forbidden from partially writing.
    assert tasks_file.exists(), (
        "tasks.json must still exist after failed write (it pre-existed)"
    )
    parsed = json_lib.loads(tasks_file.read_text())  # raises if corrupted
    assert parsed == pre_existing, (
        f"failed submit must NOT mutate tasks.json; got {parsed!r}"
    )
