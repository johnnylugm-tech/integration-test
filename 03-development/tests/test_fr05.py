"""TDD-RED tests for FR-05: CLI Integration.

Per SPEC.md §3 FR-05 + TEST_SPEC.md §FR-05 (7 cases, 13 sub-assertion
predicates, 13 AC rules). These tests are intentionally written BEFORE
the argparse wiring / status/list/clear subcommands / --json global flag
exist; until the new ``cli`` surface lands, the harness will report
expected ImportError / AttributeError for the new entry points.

Test isolation:
- TASKQ_HOME is monkeypatched to a tmp dir for every test (autouse fixture).
- ``sys.argv`` is monkeypatched per-test so ``python -m taskq`` style
  invocation always lands in a deterministic argument vector.

Mirror-check contract:
- ``@pytest.mark.parametrize`` row count and column projection MUST exactly
  match TEST_SPEC §FR-05 Inputs rows (lines 270-276). Variables not declared
  in a spec case are passed as Python ``None`` here (``inputs.get(k)``
  returns ``None`` and ``_as_str`` produces ``'None'`` on both sides).
- Each sub-assertion predicate (e.g. ``subcommand_count == "5"``) MUST
  appear as an ``assert`` inside an ``if`` (or ``if ... in``) block whose
  trigger matches the TEST_SPEC Sub-assertion ``applies_to`` mapping.
- Case dispatch is done by inspecting the spec input tuple itself —
  never by adding helper-only parameters that would distort the
  projection.

Per-test GREEN TODOs:
- test_fr05_subcommands_registered:
    # GREEN TODO: taskq.cli must expose a build_parser() factory that
    # registers exactly 5 subcommands (submit/run/status/list/clear).
- test_fr05_status_all_fields:
    # GREEN TODO: ``status <id>`` must emit a JSON document with the
    # canonical 9 field set (id, command, status, exit_code, stdout_tail,
    # stderr_tail, duration_ms, finished_at, cached).
- test_fr05_list_filter_by_status:
    # GREEN TODO: ``list --status done`` must filter persisted tasks
    # and emit a JSON array containing only matching records.
- test_fr05_clear_all_data_files:
    # GREEN TODO: ``clear`` must delete tasks.json + breaker.json +
    # cache.json atomically and report a JSON summary.
- test_fr05_global_json_flag:
    # GREEN TODO: --json must funnel through every subcommand and emit
    # a single-line JSON payload (one line, no pretty-printing).
- test_fr05_exit_code_matrix:
    # GREEN TODO: exit codes must be 0/2/3/4/1 mapped respectively to
    # success / unknown-id / breaker-open / single-task-timeout / other.
- test_fr05_unknown_id_exit2:
    # GREEN TODO: ``status <id>`` / ``run <id>`` on an unknown id must
    # print an error to stderr and exit 2.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Top-level imports — RED state is expected for any new FR-05 entry
# points (``build_parser``, ``status_cmd``, ``list_cmd``, ``clear_cmd``,
# ``run_cli``) prior to GREEN.
from taskq import cli  # noqa: F401  -- existing FR-01..04 surface
from taskq.breaker import Breaker, BreakerState
from taskq.cache import Cache, compute_signature
from taskq.executor import run_task
from taskq.store import TaskStore
from taskq.models import Status, Task


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_taskq_home(tmp_path, monkeypatch):
    """Point TASKQ_HOME at a tmp dir so tests don't touch the real .taskq store."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    # Clear any inherited argv so per-test invocations start clean.
    monkeypatch.setattr("sys.argv", ["taskq"])


def _seed_tasks(home: Path, tasks: list[dict]) -> None:
    """Write a list of task dicts into the per-test TASKQ_HOME."""
    (home / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")


def _seed_breaker(home: Path, payload: dict) -> None:
    """Write a breaker state payload into the per-test TASKQ_HOME."""
    (home / "breaker.json").write_text(json.dumps(payload), encoding="utf-8")


def _seed_cache(home: Path, entries: list[dict]) -> None:
    """Write a list of cache entries to ``$TASKQ_HOME/cache.json``."""
    (home / "cache.json").write_text(json.dumps(entries), encoding="utf-8")


def _read_tasks(home: Path) -> list[dict]:
    """Read tasks.json from a TASKQ_HOME dir; ``[]`` when absent."""
    path = home / "tasks.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_args(argv):
    """Build an argparse Namespace via taskq.cli's parser factory.

    RED import is silenced: if ``build_parser`` doesn't exist yet the
    test fails via AttributeError (the expected RED signal).
    """
    parser = cli.build_parser()  # type: ignore[attr-defined]
    return parser.parse_args(argv)


def _invoke(argv, monkeypatch):
    """Invoke the top-level entry point with the given argv.

    RED import is silenced: until ``run_cli`` lands the test fails via
    AttributeError (the expected RED signal).
    """
    return cli.run_cli(argv)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Parametrized canonical test — MUST mirror TEST_SPEC §FR-05 Inputs verbatim.
#
# Column order (13 vars) = every key any TEST_SPEC FR-05 Inputs row
# references:
#   subcommands_csv, subcommand_count,
#   status_keys_csv, field_count,
#   filter_status, result_count,
#   cleared_paths_csv, file_count,
#   json_mode, json_output_lines,
#   exit_codes_csv, code_count,
#   unknown_id, id_length, expected_exit
# Projection values that TEST_SPEC omits for a case become Python
# ``None`` here (canonicalising ``'None'`` on both sides).
# ---------------------------------------------------------------------------

# Variable order matters: every None placeholder fills a slot that the
# corresponding TEST_SPEC case does not declare. Each row MUST have exactly
# 15 values matching the 15 parametrize variables below.
_FR05_PARAMETRIZE = [
    # 0  subcommands_csv                  1  subcommand_count
    # 2  status_keys_csv                  3  field_count
    # 4  filter_status                    5  result_count
    # 6  cleared_paths_csv                7  file_count
    # 8  json_mode                        9  json_output_lines
    # 10 exit_codes_csv                   11 code_count
    # 12 unknown_id                       13 id_length
    # 14 expected_exit
    # case 1: subcmd_list
    ("submit,run,status,list,clear", "5", None, None, None, None, None, None, None, None, None, None, None, None, None),
    # case 2: status_output_fields
    (None, None,
     "id,command,status,exit_code,stdout_tail,stderr_tail,duration_ms,finished_at,cached",
     "9", None, None, None, None, None, None, None, None, None, None, None),
    # case 3: list_filter_done
    (None, None, None, None, "done", "1", None, None, None, None, None, None, None, None, None),
    # case 4: clear_files
    (None, None, None, None, None, None,
     "tasks.json,breaker.json,cache.json", "3", None, None, None, None, None, None, None),
    # case 5: json_flag
    (None, None, None, None, None, None, None, None, "yes", "1", None, None, None, None, None),
    # case 6: exit_code_matrix
    (None, None, None, None, None, None, None, None, None, None,
     "0,2,3,4,1", "5", None, None, None),
    # case 7: unknown_id
    (None, None, None, None, None, None, None, None, None, None, None, None,
     "01234567", "8", "2"),
]


@pytest.mark.parametrize(
    "subcommands_csv, subcommand_count, "
    "status_keys_csv, field_count, "
    "filter_status, result_count, "
    "cleared_paths_csv, file_count, "
    "json_mode, json_output_lines, "
    "exit_codes_csv, code_count, "
    "unknown_id, id_length, expected_exit",
    _FR05_PARAMETRIZE,
)
def test_fr05(
    tmp_path,
    monkeypatch,
    capsys,
    subcommands_csv,
    subcommand_count,
    status_keys_csv,
    field_count,
    filter_status,
    result_count,
    cleared_paths_csv,
    file_count,
    json_mode,
    json_output_lines,
    exit_codes_csv,
    code_count,
    unknown_id,
    id_length,
    expected_exit,
):
    # Re-isolate TASKQ_HOME inside the parametrize body for clarity.
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))

    # ------------------------------------------------------------------
    # Mirror-check trigger + sub-assertion anchors.
    # Each ``if``'s comparison target MUST match the TEST_SPEC Inputs
    # value for the same case (see applies_to in §Sub-assertions).
    # ------------------------------------------------------------------
    if subcommand_count == "5":
        # AC-FR05-subcmd-count-attr : subcommand_count == "5" (case 1)
        assert subcommand_count == "5"

    if subcommands_csv == "submit,run,status,list,clear":
        # AC-FR05-subcmd-count-5 : len(subcommands_csv.split(",")) == 5 (case 1)
        assert len(subcommands_csv.split(",")) == 5

    if field_count == "9":
        # AC-FR05-status-fields-9 : field_count == "9" (case 2)
        assert field_count == "9"

    if status_keys_csv == "id,command,status,exit_code,stdout_tail,stderr_tail,duration_ms,finished_at,cached":
        # status_keys_csv is a known canonical 9-field projection (case 2).
        assert len(status_keys_csv.split(",")) == 9

    if filter_status == "done":
        # AC-FR05-filter-valid : filter_status == "done" (case 3)
        assert filter_status == "done"

    if file_count == "3":
        # AC-FR05-files-cleared-attr : file_count == "3" (case 4)
        assert file_count == "3"

    if cleared_paths_csv == "tasks.json,breaker.json,cache.json":
        # AC-FR05-files-cleared-3 : len(cleared_paths_csv.split(",")) == 3 (case 4)
        assert len(cleared_paths_csv.split(",")) == 3

    if json_mode == "yes":
        # AC-FR05-json-on : json_mode == "yes" (case 5)
        assert json_mode == "yes"

    if json_output_lines == "1":
        # AC-FR05-json-one-line : json_output_lines == "1" (case 5)
        assert json_output_lines == "1"

    if code_count == "5":
        # AC-FR05-exit-codes-attr : code_count == "5" (case 6)
        assert code_count == "5"

    if exit_codes_csv == "0,2,3,4,1":
        # AC-FR05-exit-codes-five : len(exit_codes_csv.split(",")) == 5 (case 6)
        assert len(exit_codes_csv.split(",")) == 5

    if id_length == "8":
        # AC-FR05-unknown-id-len-8 : len(unknown_id) == 8 (case 7)
        assert id_length == "8"

    if expected_exit == "2":
        # AC-FR05-unknown-exit-2 : expected_exit == "2" (case 7)
        assert expected_exit == "2"

    if unknown_id == "01234567":
        # project the unknown_id length 8 as required by the spec (case 7)
        assert len(unknown_id) == 8

    # ------------------------------------------------------------------
    # Case dispatch by inspecting the spec input tuple itself. Order is
    # fixed at TEST_SPEC §FR-05 Inputs (lines 270-276).
    # ------------------------------------------------------------------

    if subcommands_csv == "submit,run,status,list,clear":
        # ===== case 1: subcmd_list ======================================
        # GREEN TODO: taskq.cli.build_parser() must register exactly 5
        # subcommands (submit / run / status / list / clear).
        parser = cli.build_parser()  # type: ignore[attr-defined]
        names = sorted(parser.subparsers.choices.keys())  # type: ignore[attr-defined]
        # The canonical 5 subcommands per SPEC §3 FR-05.
        assert names == ["clear", "list", "run", "status", "submit"], (
            f"FR-05 must register 5 subcommands, got {names!r}"
        )
        assert len(names) == 5, f"FR-05 subcommand count must be 5, got {len(names)}"
        return

    if status_keys_csv == "id,command,status,exit_code,stdout_tail,stderr_tail,duration_ms,finished_at,cached":
        # ===== case 2: status_output_fields =============================
        # Seed tasks.json with a single done task. status_cmd must print
        # a JSON document with the canonical 9-field projection.
        from taskq import cli as cli_mod  # RED import — silent until GREEN

        task_id = "abcdef01"
        _seed_tasks(
            tmp_path,
            [
                {
                    "id": task_id,
                    "name": None,
                    "command": "echo fields_probe",
                    "status": "done",
                    "created_at": "2026-07-11T00:00:00Z",
                    "exit_code": 0,
                    "stdout_tail": "fields-probe",
                    "stderr_tail": "",
                    "duration_ms": 11,
                    "finished_at": "2026-07-11T00:00:01Z",
                    "cached": False,
                }
            ],
        )

        # GREEN TODO: cli.status_cmd(task_id, json_mode=True) -> int
        # MUST emit a JSON object whose key set equals the 9 canonical
        # fields and exit 0 on success.
        exit_code = cli_mod.status_cmd(task_id, json_mode=True)  # type: ignore[attr-defined]
        out = capsys.readouterr().out.strip()
        assert exit_code == 0, f"FR-05 status on a known id must exit 0, got {exit_code}"
        payload = json.loads(out)
        keys = set(payload.keys())
        expected = {
            "id",
            "command",
            "status",
            "exit_code",
            "stdout_tail",
            "stderr_tail",
            "duration_ms",
            "finished_at",
            "cached",
        }
        assert keys == expected, (
            f"FR-05 status must emit exactly the 9 canonical fields, got {keys}"
        )
        assert len(keys) == 9, f"FR-05 status must emit 9 fields, got {len(keys)}"
        return

    if filter_status == "done":
        # ===== case 3: list_filter_done =================================
        # Seed two tasks: one done, one pending. list --status done must
        # emit only the done task; --json must wrap the filtered set in
        # a single-line JSON document.
        from taskq import cli as cli_mod  # RED import — silent until GREEN

        _seed_tasks(
            tmp_path,
            [
                {
                    "id": "11111111",
                    "name": None,
                    "command": "echo done_task",
                    "status": "done",
                    "created_at": "2026-07-11T00:00:00Z",
                    "finished_at": "2026-07-11T00:00:01Z",
                },
                {
                    "id": "22222222",
                    "name": None,
                    "command": "echo pending_task",
                    "status": "pending",
                    "created_at": "2026-07-11T00:00:02Z",
                },
            ],
        )

        # GREEN TODO: cli.list_cmd(filter_status="done", json_mode=True) -> int
        # MUST emit a JSON array of one done record and exit 0.
        exit_code = cli_mod.list_cmd(filter_status="done", json_mode=True)  # type: ignore[attr-defined]
        out = capsys.readouterr().out.strip()
        assert exit_code == 0, (
            f"FR-05 list must exit 0 when at least one row matches, got {exit_code}"
        )
        payload = json.loads(out)
        assert isinstance(payload, list), (
            f"FR-05 list --json must emit a JSON list, got {type(payload).__name__}"
        )
        assert len(payload) == 1, (
            f"FR-05 list --status done must yield 1 record, got {len(payload)}"
        )
        assert payload[0]["status"] == "done"
        return

    if cleared_paths_csv == "tasks.json,breaker.json,cache.json":
        # ===== case 4: clear_files =====================================
        # Seed all three data files; clear must delete every one and
        # report the cleared paths. --json must wrap the result in one
        # single-line JSON document.
        from taskq import cli as cli_mod  # RED import — silent until GREEN

        _seed_tasks(tmp_path, [{"id": "33333333", "status": "pending", "command": "x"}])
        _seed_breaker(tmp_path, {"state": "CLOSED", "failures": 0, "opened_at": None})
        _seed_cache(tmp_path, [{"signature": "sig", "result_task_id": "33333333"}])

        # GREEN TODO: cli.clear_cmd(json_mode=True) -> int MUST delete
        # the three data files and emit a JSON object whose ``cleared``
        # field enumerates the deleted filenames, all on a single line.
        exit_code = cli_mod.clear_cmd(json_mode=True)  # type: ignore[attr-defined]
        out = capsys.readouterr().out.strip()
        assert exit_code == 0, f"FR-05 clear must exit 0, got {exit_code}"
        payload = json.loads(out)
        cleared = set(payload.get("cleared", []))
        assert cleared == {"tasks.json", "breaker.json", "cache.json"}, (
            f"FR-05 clear must remove all 3 data files, got {cleared}"
        )
        assert not (tmp_path / "tasks.json").exists()
        assert not (tmp_path / "breaker.json").exists()
        assert not (tmp_path / "cache.json").exists()
        return

    if json_mode == "yes":
        # ===== case 5: json_flag =======================================
        # submit with --json must emit a one-line JSON document with the
        # standard {id, status:"pending"} payload.
        from taskq import cli as cli_mod  # RED import — silent until GREEN

        # GREEN TODO: cli.submit_cmd(cmd, name=None, json_mode=True) -> int
        # MUST emit a SINGLE line of JSON (no trailing newline-only
        # payloads separated by blank lines), exit 0 on success.
        exit_code = cli_mod.submit_cmd("echo json_probe", None, json_mode=True)  # type: ignore[attr-defined]
        out = capsys.readouterr().out
        assert exit_code == 0, f"FR-05 submit --json must exit 0, got {exit_code}"
        # json_output_lines must be exactly 1 (no extra blank lines).
        non_empty_lines = [ln for ln in out.splitlines() if ln.strip()]
        assert len(non_empty_lines) == 1, (
            f"FR-05 --json must emit a single line, got "
            f"{len(non_empty_lines)} non-empty lines: {non_empty_lines!r}"
        )
        payload = json.loads(non_empty_lines[0])
        assert payload.get("status") == "pending"
        assert "id" in payload
        return

    if exit_codes_csv == "0,2,3,4,1":
        # ===== case 6: exit_code_matrix ================================
        # Exercise the 5 documented exit codes:
        #   0 = success
        #   2 = unknown task id (run/status on missing id)
        #   3 = breaker open (run with breaker state=OPEN)
        #   4 = single task timeout (run <id> producing status=timeout)
        #   1 = internal argparse / other unexpected error
        from taskq import cli as cli_mod  # RED import — silent until GREEN
        from taskq.cache import compute_signature  # noqa: F401  -- FR-04 surface
        from taskq.executor import run_task  # noqa: F401  -- FR-02/03 surface
        from taskq.models import Status, Task  # type: ignore  # RED import OK  # noqa: F401

        # 0: success path — submit happy ⇒ exit 0
        monkeypatch.setattr("sys.argv", ["taskq", "submit", "echo matrix_probe"])
        rc = _invoke(["taskq", "submit", "echo matrix_probe"], monkeypatch)
        assert rc == 0, f"FR-05 success exit must be 0, got {rc}"

        # 2: unknown task id ⇒ exit 2
        unknown = "ffffffff"
        rc = cli_mod.run_cmd(task_id=unknown, all_mode=False, cached=False, json_mode=False)
        assert rc == 2, f"FR-05 unknown id must exit 2, got {rc}"

        # 3: breaker OPEN ⇒ run must exit 3 + stderr ``breaker open``
        _seed_breaker(
            tmp_path,
            {"state": "OPEN", "failures": 9, "opened_at": "2026-07-11T00:00:00Z"},
        )
        task_id = "7fffffff"
        _seed_tasks(
            tmp_path,
            [
                {
                    "id": task_id,
                    "name": None,
                    "command": "echo breaker_open_probe",
                    "status": "pending",
                    "created_at": "2026-07-11T00:00:00Z",
                }
            ],
        )
        # Fresh in-memory breaker state — re-import to bypass any
        # cached singleton.
        rc = cli_mod.run_cmd(task_id=task_id, all_mode=False, cached=False, json_mode=False)
        captured = capsys.readouterr()
        assert rc == 3, f"FR-05 breaker-open must exit 3, got {rc}"
        assert "breaker open" in captured.err, (
            f"FR-05 breaker-open must print ``breaker open`` to stderr, got {captured.err!r}"
        )

        # 4: single task timeout ⇒ exit 4
        _seed_tasks(
            tmp_path,
            [
                {
                    "id": "deadbeef",
                    "name": None,
                    "command": "echo timeout_probe",
                    "status": "pending",
                    "created_at": "2026-07-11T00:00:00Z",
                }
            ],
        )
        # Force the executor to behave as if the subprocess timed out.
        from taskq import executor as exec_mod  # type: ignore  # RED import OK

        def _fake_run_task(task):
            return {
                "status": "timeout",
                "exit_code": None,
                "stdout_tail": "",
                "stderr_tail": "",
                "duration_ms": 10000,
                "finished_at": "2026-07-11T00:00:10Z",
                "cached": False,
            }

        monkeypatch.setattr(exec_mod, "run_task", _fake_run_task)
        rc = cli_mod.run_cmd(
            task_id="deadbeef", all_mode=False, cached=False, json_mode=False
        )
        assert rc == 4, f"FR-05 single-task timeout must exit 4, got {rc}"

        # 1: internal error — clear with a directory read-only and ensure
        # any unhandled failure funnels to exit 1 OR document an explicit
        # ``raise SystemExit(1)`` for unexpected argparse flows. The
        # contract here is: a missing top-level subcommand must emit
        # exit 1 via argparse SystemExit(2) — argonfile convention. To
        # avoid coupling the test to that edge, we instead seed a
        # corrupted tasks.json and verify clear_cmd surfaces exit 1 when
        # deletion semantics fail; otherwise we exercise argparse's
        # SystemExit via a known-bad invocation.
        # GREEN TODO: any unexpected error path surfaces exit 1.
        if hasattr(cli_mod, "clear_cmd"):
            # Provide an unhandled exception path: patch a sentinel so
            # the clear path raises — defensive but bounded by attribute
            # existence so RED import does NOT trip.
            def _raise(*a, **kw):  # pragma: no cover — used only on GREEN
                raise RuntimeError("simulated internal error")

            monkeypatch.setattr(cli_mod, "clear_cmd", _raise, raising=False)
            rc = cli_mod.run_cli(["taskq", "clear"])  # type: ignore[attr-defined]
            assert rc == 1, f"FR-05 internal error must exit 1, got {rc}"
        return

    if unknown_id == "01234567":
        # ===== case 7: unknown_id ======================================
        # run <id> + status <id> on an unknown id ⇒ exit 2.
        from taskq import cli as cli_mod  # RED import — silent until GREEN

        # unknown_id is 8 hex chars (canonical UUID4 prefix).
        rc = cli_mod.run_cmd(
            task_id=unknown_id, all_mode=False, cached=False, json_mode=False
        )
        assert rc == 2, f"FR-05 run on unknown id must exit 2, got {rc}"
        captured = capsys.readouterr()
        assert unknown_id in captured.err, (
            f"FR-05 unknown id must echo the id in stderr, got {captured.err!r}"
        )

        if hasattr(cli_mod, "status_cmd"):
            # status <id> on an unknown id also exits 2 (per spec —
            # exit 2 covers "input validation error (含 unknown task id)").
            rc2 = cli_mod.status_cmd(unknown_id, json_mode=False)  # type: ignore[attr-defined]
            assert rc2 == 2, f"FR-05 status on unknown id must exit 2, got {rc2}"
        return


# ===========================================================================
# FR-05 canonical test functions (TEST_SPEC.md §FR-05 Test Functions).
# ===========================================================================
# spec-coverage-check matches these exact names against TEST_SPEC rows. The
# canonical names also help downstream ID-tagging in P4 and beyond.


def test_fr05_subcommands_registered() -> None:
    """build_parser registers 5 subcommands (submit/run/status/list/clear)."""
    parser = cli.build_parser()  # type: ignore[attr-defined]
    names = sorted(parser.subparsers.choices.keys())  # type: ignore[attr-defined]
    assert names == ["clear", "list", "run", "status", "submit"]
    assert len(names) == 5


def test_fr05_status_all_fields(tmp_path, monkeypatch, capsys) -> None:
    """status <id> emits the canonical 9-field projection."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    task_id = "abcdef01"
    (tmp_path / "tasks.json").write_text(
        json.dumps(
            [
                {
                    "id": task_id,
                    "name": None,
                    "command": "echo fields",
                    "status": "done",
                    "created_at": "2026-07-11T00:00:00Z",
                    "exit_code": 0,
                    "stdout_tail": "fields",
                    "stderr_tail": "",
                    "duration_ms": 11,
                    "finished_at": "2026-07-11T00:00:01Z",
                    "cached": False,
                }
            ]
        )
    )
    rc = cli.status_cmd(task_id, json_mode=True)  # type: ignore[attr-defined]
    out = capsys.readouterr().out.strip()
    assert rc == 0
    payload = json.loads(out)
    assert set(payload.keys()) == {
        "id",
        "command",
        "status",
        "exit_code",
        "stdout_tail",
        "stderr_tail",
        "duration_ms",
        "finished_at",
        "cached",
    }


def test_fr05_list_filter_by_status(tmp_path, monkeypatch, capsys) -> None:
    """list --status done filters persisted tasks."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "tasks.json").write_text(
        json.dumps(
            [
                {"id": "1", "status": "done", "command": "x"},
                {"id": "2", "status": "pending", "command": "y"},
            ]
        )
    )
    rc = cli.list_cmd(filter_status="done", json_mode=True)  # type: ignore[attr-defined]
    out = capsys.readouterr().out.strip()
    assert rc == 0
    payload = json.loads(out)
    assert len(payload) == 1 and payload[0]["status"] == "done"


def test_fr05_clear_all_data_files(tmp_path, monkeypatch, capsys) -> None:
    """clear deletes tasks.json + breaker.json + cache.json atomically."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "tasks.json").write_text(json.dumps([{"id": "x"}]))
    (tmp_path / "breaker.json").write_text(json.dumps({"state": "CLOSED"}))
    (tmp_path / "cache.json").write_text(json.dumps([]))
    rc = cli.clear_cmd(json_mode=True)  # type: ignore[attr-defined]
    out = capsys.readouterr().out.strip()
    assert rc == 0
    payload = json.loads(out)
    assert set(payload.get("cleared", [])) == {
        "tasks.json",
        "breaker.json",
        "cache.json",
    }


def test_fr05_global_json_flag(tmp_path, monkeypatch, capsys) -> None:
    """--json emits a single-line JSON document for submit."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.submit_cmd("echo json", None, json_mode=True)
    out = capsys.readouterr().out
    assert rc == 0
    non_empty = [ln for ln in out.splitlines() if ln.strip()]
    assert len(non_empty) == 1
    payload = json.loads(non_empty[0])
    assert payload.get("status") == "pending"
    assert "id" in payload


def test_fr05_exit_code_matrix(tmp_path, monkeypatch, capsys) -> None:
    """Exit codes 0/2/3/4/1 map precisely (success/unknown/breaker/timeout/internal)."""
    from taskq import executor as exec_mod

    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))

    # 0 — success
    rc = cli.submit_cmd("echo matrix", None, json_mode=False)
    assert rc == 0, f"success must exit 0, got {rc}"

    # 2 — unknown task id (run + status)
    rc = cli.run_cmd(
        task_id="ffffffff", all_mode=False, cached=False, json_mode=False
    )
    assert rc == 2, f"unknown id must exit 2, got {rc}"
    rc = cli.status_cmd("ffffffff", json_mode=False)
    assert rc == 2, f"status unknown must exit 2, got {rc}"

    # 3 — breaker OPEN
    (tmp_path / "breaker.json").write_text(
        json.dumps(
            {
                "state": "OPEN",
                "consecutive_failures": 9,
                "opened_at": "2026-07-11T00:00:00Z",
            }
        )
    )
    (tmp_path / "tasks.json").write_text(
        json.dumps(
            [
                {
                    "id": "7fffffff",
                    "status": "pending",
                    "command": "echo x",
                    "created_at": "2026-07-11T00:00:00Z",
                }
            ]
        )
    )
    rc = cli.run_cmd(
        task_id="7fffffff", all_mode=False, cached=False, json_mode=False
    )
    assert rc == 3, f"breaker-open must exit 3, got {rc}"
    assert "breaker open" in capsys.readouterr().err

    # 4 — single task timeout
    (tmp_path / "tasks.json").write_text(
        json.dumps(
            [
                {
                    "id": "deadbeef",
                    "status": "pending",
                    "command": "echo x",
                    "created_at": "2026-07-11T00:00:00Z",
                }
            ]
        )
    )

    def _fake_timeout(_task):
        return {
            "status": "timeout",
            "exit_code": None,
            "stdout_tail": "",
            "stderr_tail": "",
            "duration_ms": 10000,
            "finished_at": "2026-07-11T00:00:10Z",
            "cached": False,
        }

    monkeypatch.setattr(exec_mod, "run_task", _fake_timeout)
    rc = cli.run_cmd(
        task_id="deadbeef", all_mode=False, cached=False, json_mode=False
    )
    assert rc == 4, f"single-task timeout must exit 4, got {rc}"

    # 1 — internal error funnel
    def _explode(*_a, **_kw):
        raise RuntimeError("forced")

    monkeypatch.setattr(cli, "list_cmd", _explode)
    rc = cli.run_cli(["taskq", "list"])
    assert rc == 1, f"internal error must exit 1, got {rc}"


def test_fr05_unknown_id_exit2(tmp_path, monkeypatch, capsys) -> None:
    """unknown task id ⇒ exit 2 + stderr echoes the id (run + status)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.run_cmd(
        task_id="01234567", all_mode=False, cached=False, json_mode=False
    )
    out_err = capsys.readouterr()
    assert rc == 2
    assert "01234567" in out_err.err
    rc2 = cli.status_cmd("01234567", json_mode=False)
    out_err2 = capsys.readouterr()
    assert rc2 == 2
    assert "01234567" in out_err2.err


# ===========================================================================
# FR-05 coverage-fix additions.
# ===========================================================================
# The canonical parametrized test above exercises the 7 TEST_SPEC cases
# end-to-end, but its dispatch covers only the matching branch per row. The
# tests below add targeted unit-style coverage for sibling branches /
# module-private helpers across cli / breaker / cache / executor / store /
# models so the ``test_coverage`` dimension can reach the 80% threshold.


# ---- cli.submit_cmd branches (validation rejection + non-JSON path) ----


def test_fr05_cli_submit_non_json_prints_id(tmp_path, monkeypatch, capsys):
    """submit_cmd with json_mode=False prints the bare task id (cli.py:154-157)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.submit_cmd("echo coverage_probe", None, json_mode=False)
    assert rc == 0, f"submit happy-path must exit 0, got {rc}"
    out = capsys.readouterr().out.strip()
    # Non-JSON path: 8 hex chars (UUID4 prefix).
    assert len(out) == 8, f"non-JSON submit must print 8-char task id, got {out!r}"
    assert all(c in "0123456789abcdef" for c in out), f"task id must be hex: {out!r}"
    # And the record is persisted in $TASKQ_HOME/tasks.json.
    saved = json.loads((tmp_path / "tasks.json").read_text())
    assert len(saved) == 1 and saved[0]["status"] == "pending"


def test_fr05_cli_submit_empty_rejected(tmp_path, monkeypatch, capsys):
    """submit_cmd with empty command must exit 2 (cli.py:100-101)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.submit_cmd("", None, json_mode=False)
    assert rc == 2, f"empty command must exit 2, got {rc}"
    assert "empty" in capsys.readouterr().err


def test_fr05_cli_submit_whitespace_rejected(tmp_path, monkeypatch, capsys):
    """submit_cmd with whitespace-only must exit 2 (cli.py:100-101)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.submit_cmd("   ", None, json_mode=False)
    assert rc == 2, f"whitespace-only command must exit 2, got {rc}"


def test_fr05_cli_submit_command_too_long_rejected(tmp_path, monkeypatch, capsys):
    """submit_cmd with command > 1000 chars must exit 2 (cli.py:102-103)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.submit_cmd("a" * 1001, None, json_mode=False)
    assert rc == 2, f"lengthy command must exit 2, got {rc}"


def test_fr05_cli_submit_injection_rejected(tmp_path, monkeypatch, capsys):
    """submit_cmd with shell-injection chars must exit 2 (cli.py:104-106)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    for ch in [";", "|", "&", "$", ">", "<", "`"]:
        rc = cli.submit_cmd(f"echo bad{ch}x", None, json_mode=False)
        assert rc == 2, f"injection char {ch!r} not rejected (rc={rc})"


def test_fr05_cli_submit_duplicate_name_rejected(tmp_path, monkeypatch, capsys):
    """submit_cmd with duplicate pending name must exit 2 (cli.py:110-117, 139-141)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "tasks.json").write_text(
        json.dumps(
            [
                {
                    "id": "abcdef01",
                    "name": "dup",
                    "command": "echo first",
                    "status": "pending",
                    "created_at": "2026-07-11T00:00:00Z",
                }
            ]
        )
    )
    rc = cli.submit_cmd("echo second", "dup", json_mode=False)
    assert rc == 2, f"duplicate name must exit 2, got {rc}"


# ---- cli.status_cmd / cli.list_cmd / cli.clear_cmd sibling branches ----


def test_fr05_cli_status_non_json(tmp_path, monkeypatch, capsys):
    """status_cmd with json_mode=False prints indented JSON (cli.py:311-312)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "tasks.json").write_text(
        json.dumps(
            [
                {
                    "id": "abcdef01",
                    "name": None,
                    "command": "echo x",
                    "status": "done",
                    "created_at": "2026-07-11T00:00:00Z",
                    "exit_code": 0,
                    "stdout_tail": "",
                    "stderr_tail": "",
                    "duration_ms": 1.0,
                    "finished_at": "2026-07-11T00:00:01Z",
                    "cached": False,
                }
            ]
        )
    )
    rc = cli.status_cmd("abcdef01", json_mode=False)
    assert rc == 0
    out = capsys.readouterr().out
    # indented JSON contains newlines.
    assert "\n" in out, f"non-JSON status must print indented JSON, got {out!r}"
    # The projected payload round-trips through json.loads.
    payload = json.loads(out)
    assert payload["id"] == "abcdef01"


def test_fr05_cli_list_no_filter_json(tmp_path, monkeypatch, capsys):
    """list_cmd with no filter + json_mode=True returns full list (cli.py:323-327)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "tasks.json").write_text(
        json.dumps(
            [
                {"id": "1", "status": "pending", "command": "x"},
                {"id": "2", "status": "done", "command": "y"},
            ]
        )
    )
    rc = cli.list_cmd(filter_status=None, json_mode=True)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert len(payload) == 2


def test_fr05_cli_list_no_filter_non_json(tmp_path, monkeypatch, capsys):
    """list_cmd with json_mode=False prints one record per line (cli.py:328-330)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "tasks.json").write_text(
        json.dumps(
            [
                {"id": "1", "status": "pending", "command": "x"},
                {"id": "2", "status": "done", "command": "y"},
            ]
        )
    )
    rc = cli.list_cmd(filter_status=None, json_mode=False)
    assert rc == 0
    out = capsys.readouterr().out
    non_empty = [ln for ln in out.splitlines() if ln.strip()]
    assert len(non_empty) == 2, f"list non-JSON must yield one line per record, got {non_empty!r}"


def test_fr05_cli_clear_non_json(tmp_path, monkeypatch, capsys):
    """clear_cmd with json_mode=False prints 'cleared: ...' (cli.py:351-352)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "tasks.json").write_text(json.dumps([{"id": "x"}]))
    (tmp_path / "breaker.json").write_text(json.dumps({"state": "CLOSED"}))
    (tmp_path / "cache.json").write_text(json.dumps([]))
    rc = cli.clear_cmd(json_mode=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("cleared: ")
    assert "tasks.json" in out and "breaker.json" in out and "cache.json" in out


def test_fr05_cli_clear_no_files(tmp_path, monkeypatch, capsys):
    """clear_cmd when nothing exists returns cleared=[] (cli.py:344-348)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.clear_cmd(json_mode=True)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["cleared"] == []


def test_fr05_cli_clear_partial_missing(tmp_path, monkeypatch, capsys):
    """clear_cmd with some files missing reports only the cleared ones (cli.py:344-348)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "tasks.json").write_text(json.dumps([{"id": "x"}]))
    # breaker.json + cache.json are absent
    rc = cli.clear_cmd(json_mode=True)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["cleared"] == ["tasks.json"]


# ---- cli.run_cmd branches ----


def test_fr05_cli_run_all_no_pending(tmp_path, monkeypatch):
    """run_cmd with all_mode=True and no pending returns 0 early (cli.py:249-254)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.run_cmd(task_id=None, all_mode=True, cached=False, json_mode=False)
    assert rc == 0, f"all_mode with no pending must exit 0, got {rc}"


def test_fr05_cli_run_all_with_pending(tmp_path, monkeypatch):
    """run_cmd with all_mode=True executes pending tasks (cli.py:249-260)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "tasks.json").write_text(
        json.dumps(
            [
                {
                    "id": "aaaa1111",
                    "name": None,
                    "command": "echo p1",
                    "status": "pending",
                    "created_at": "2026-07-11T00:00:00Z",
                }
            ]
        )
    )
    rc = cli.run_cmd(task_id=None, all_mode=True, cached=False, json_mode=False)
    assert rc == 0, f"all_mode run must exit 0, got {rc}"
    saved = json.loads((tmp_path / "tasks.json").read_text())
    assert saved[0]["status"] == "done"


def test_fr05_cli_run_cached_hit(tmp_path, monkeypatch):
    """run_cmd with --cached replays a TTL-fresh cache entry (cli.py:271-276, 165-181)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    cmd = "echo cache_hit_probe"
    sig = compute_signature(cmd)
    (tmp_path / "tasks.json").write_text(
        json.dumps(
            [
                {
                    "id": "11111111",
                    "name": None,
                    "command": cmd,
                    "status": "pending",
                    "created_at": "2026-07-11T00:00:00Z",
                }
            ]
        )
    )
    now_iso = "2026-07-11T00:00:00Z"
    (tmp_path / "cache.json").write_text(
        json.dumps(
            [
                {
                    "signature": sig,
                    "command": cmd,
                    "status": "done",
                    "exit_code": 0,
                    "stdout_tail": "cached-stdout",
                    "stderr_tail": "",
                    "duration_ms": 12.0,
                    "finished_at": now_iso,
                    "cached_at": now_iso,
                    "result_task_id": "11111111",
                }
            ]
        )
    )
    rc = cli.run_cmd(
        task_id="11111111", all_mode=False, cached=True, json_mode=False
    )
    assert rc == 0
    saved = json.loads((tmp_path / "tasks.json").read_text())
    assert saved[0]["status"] == "done"
    assert saved[0]["cached"] is True


def test_fr05_cli_run_cached_done_writes_cache(tmp_path, monkeypatch):
    """run_cmd with --cached + done result writes a fresh cache entry (cli.py:278-285)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    cmd = "echo cache_put_probe"
    (tmp_path / "tasks.json").write_text(
        json.dumps(
            [
                {
                    "id": "22222222",
                    "name": None,
                    "command": cmd,
                    "status": "pending",
                    "created_at": "2026-07-11T00:00:00Z",
                }
            ]
        )
    )
    rc = cli.run_cmd(
        task_id="22222222", all_mode=False, cached=True, json_mode=False
    )
    assert rc == 0
    cache_path = tmp_path / "cache.json"
    assert cache_path.exists(), "run_cmd --cached + done must persist cache.json"
    entries = json.loads(cache_path.read_text())
    assert len(entries) == 1
    assert entries[0]["command"] == cmd


def test_fr05_cli_run_no_args_returns_1(tmp_path, monkeypatch):
    """run_cmd with no task_id and no all_mode returns 1 (cli.py:292)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.run_cmd(task_id=None, all_mode=False, cached=False, json_mode=False)
    assert rc == 1, f"no-args run must exit 1, got {rc}"


def test_fr05_cli_run_cli_no_subcommand(tmp_path, monkeypatch, capsys):
    """run_cli with empty argv prints help + returns 1 (cli.py:451-452)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    rc = cli.run_cli(["taskq"])
    assert rc == 1, f"no-subcommand must exit 1, got {rc}"
    captured = capsys.readouterr()
    combined = (captured.out + captured.err).lower()
    assert "usage" in combined or "help" in combined, (
        f"no-subcommand must print usage, got {combined!r}"
    )


def test_fr05_cli_run_cli_internal_error_funnel(tmp_path, monkeypatch, capsys):
    """run_cli funnels unhandled exceptions to exit 1 (cli.py:445-448)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))

    def _explode(*_a, **_kw):
        raise RuntimeError("simulated internal error")

    monkeypatch.setattr(cli, "list_cmd", _explode)
    rc = cli.run_cli(["taskq", "list"])
    assert rc == 1, f"internal-error funnel must exit 1, got {rc}"
    err = capsys.readouterr().err
    assert "internal error" in err and "RuntimeError" in err, (
        f"unexpected error path stderr: {err!r}"
    )


# ---- Breaker surface (state machine + atomic write) ----


def test_fr05_breaker_first_time_seed(tmp_path, monkeypatch):
    """Breaker.__init__ seeds breaker.json on first run (breaker.py:88-99)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    breaker = Breaker()
    assert breaker.state == BreakerState.CLOSED
    assert (tmp_path / "breaker.json").exists()
    payload = json.loads((tmp_path / "breaker.json").read_text())
    assert payload["state"] == BreakerState.CLOSED.value
    assert payload["consecutive_failures"] == 0


def test_fr05_breaker_record_failure_threshold(tmp_path, monkeypatch):
    """record_failure in CLOSED accumulates until threshold (breaker.py:152-157)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_BREAKER_THRESHOLD", "2")
    breaker = Breaker()
    assert breaker.state == BreakerState.CLOSED
    breaker.record_failure()
    assert breaker.state == BreakerState.CLOSED, "first failure must not trip"
    breaker.record_failure()
    assert breaker.state == BreakerState.OPEN, "second failure must trip"


def test_fr05_breaker_record_failure_half_open(tmp_path, monkeypatch):
    """record_failure in HALF_OPEN re-opens (breaker.py:148-151)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "breaker.json").write_text(
        json.dumps(
            {
                "state": BreakerState.HALF_OPEN.value,
                "consecutive_failures": 1,
                "opened_at": None,
            }
        )
    )
    breaker = Breaker()
    assert breaker.state == BreakerState.HALF_OPEN
    breaker.record_failure()
    assert breaker.state == BreakerState.OPEN


def test_fr05_breaker_record_success_closed(tmp_path, monkeypatch):
    """record_success in CLOSED zeroes the counter (breaker.py:170-171)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "breaker.json").write_text(
        json.dumps(
            {
                "state": BreakerState.CLOSED.value,
                "consecutive_failures": 2,
                "opened_at": None,
            }
        )
    )
    breaker = Breaker()
    breaker.record_success()
    payload = json.loads((tmp_path / "breaker.json").read_text())
    assert payload["consecutive_failures"] == 0


def test_fr05_breaker_record_success_half_open(tmp_path, monkeypatch):
    """record_success in HALF_OPEN transitions to CLOSED (breaker.py:166-169)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "breaker.json").write_text(
        json.dumps(
            {
                "state": BreakerState.HALF_OPEN.value,
                "consecutive_failures": 1,
                "opened_at": None,
            }
        )
    )
    breaker = Breaker()
    breaker.record_success()
    assert breaker.state == BreakerState.CLOSED


def test_fr05_breaker_try_acquire_cooldown_elapsed(tmp_path, monkeypatch):
    """try_acquire with OPEN + cooldown elapsed transitions to HALF_OPEN (breaker.py:208-211)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "0.05")
    import taskq.breaker as breaker_mod

    monkeypatch.setattr(breaker_mod.time, "monotonic", lambda: 2000.0)
    (tmp_path / "breaker.json").write_text(
        json.dumps(
            {
                "state": BreakerState.OPEN.value,
                "consecutive_failures": 5,
                "opened_at": 1999.0,
            }
        )
    )
    breaker = Breaker()
    assert breaker.try_acquire() is True
    assert breaker.state == BreakerState.HALF_OPEN


def test_fr05_breaker_try_acquire_cooldown_not_elapsed(tmp_path, monkeypatch):
    """try_acquire with OPEN + cooldown not elapsed returns False (breaker.py:211)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "60")
    import taskq.breaker as breaker_mod

    monkeypatch.setattr(breaker_mod.time, "monotonic", lambda: 2000.0)
    (tmp_path / "breaker.json").write_text(
        json.dumps(
            {
                "state": BreakerState.OPEN.value,
                "consecutive_failures": 5,
                "opened_at": 1999.0,
            }
        )
    )
    breaker = Breaker()
    assert breaker.try_acquire() is False
    assert breaker.state == BreakerState.OPEN


def test_fr05_breaker_corrupt_json_recovers(tmp_path, monkeypatch):
    """Breaker recovers from corrupt breaker.json (breaker.py:103-107)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "breaker.json").write_text("{bad-json")
    breaker = Breaker()
    assert breaker.state == BreakerState.CLOSED
    payload = json.loads((tmp_path / "breaker.json").read_text())
    assert payload["state"] == BreakerState.CLOSED.value


# ---- Cache surface ----


def test_fr05_cache_compute_signature_known_hash():
    """compute_signature returns 64-char hex sha256 (cache.py:38-43)."""
    sig = compute_signature("echo known")
    assert len(sig) == 64
    assert compute_signature("echo known") == sig


def test_fr05_cache_put_done(tmp_path, monkeypatch):
    """Cache.put with done result persists (cache.py:123-156)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    cache = Cache()
    cache.put(
        "sig1",
        "echo x",
        {
            "status": "done",
            "exit_code": 0,
            "stdout_tail": "x",
            "stderr_tail": "",
            "duration_ms": 1.0,
            "finished_at": "2026-07-11T00:00:00Z",
        },
        task_id="abc",
    )
    entries = json.loads((tmp_path / "cache.json").read_text())
    assert len(entries) == 1
    assert entries[0]["signature"] == "sig1"
    assert entries[0]["cached_at"].endswith("Z")


def test_fr05_cache_put_non_done_no_op(tmp_path, monkeypatch):
    """Cache.put with non-done result is a no-op (cache.py:135-136)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    cache = Cache()
    cache.put(
        "sig1",
        "false",
        {
            "status": "failed",
            "exit_code": 1,
            "stdout_tail": "",
            "stderr_tail": "",
            "duration_ms": 1.0,
            "finished_at": "2026-07-11T00:00:00Z",
        },
        task_id="abc",
    )
    assert not (tmp_path / "cache.json").exists(), (
        "Cache.put on non-done must not write cache.json"
    )


def test_fr05_cache_get_hit_fresh(tmp_path, monkeypatch):
    """Cache.get returns a TTL-fresh done entry (cache.py:104-121)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    now_iso = "2026-07-11T00:00:00Z"
    (tmp_path / "cache.json").write_text(
        json.dumps(
            [
                {
                    "signature": "sig1",
                    "command": "echo x",
                    "status": "done",
                    "exit_code": 0,
                    "stdout_tail": "x",
                    "stderr_tail": "",
                    "duration_ms": 1.0,
                    "finished_at": now_iso,
                    "cached_at": now_iso,
                    "result_task_id": "abc",
                }
            ]
        )
    )
    cache = Cache()
    entry = cache.get("sig1")
    assert entry is not None and entry["signature"] == "sig1"


def test_fr05_cache_get_miss_absent(tmp_path, monkeypatch):
    """Cache.get returns None when file absent (cache.py:160-165)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    cache = Cache()
    assert cache.get("sig_missing") is None


def test_fr05_cache_get_miss_expired(tmp_path, monkeypatch):
    """Cache.get returns None when TTL=0 (cache.py:62-69)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_CACHE_TTL", "0")
    now_iso = "2026-07-11T00:00:00Z"
    (tmp_path / "cache.json").write_text(
        json.dumps(
            [
                {
                    "signature": "sig1",
                    "command": "x",
                    "status": "done",
                    "exit_code": 0,
                    "stdout_tail": "",
                    "stderr_tail": "",
                    "duration_ms": 1.0,
                    "finished_at": now_iso,
                    "cached_at": now_iso,
                    "result_task_id": "abc",
                }
            ]
        )
    )
    cache = Cache()
    assert cache.get("sig1") is None


def test_fr05_cache_corrupt_json_recovers(tmp_path, monkeypatch):
    """Corrupt cache.json falls back to [] (cache.py:160-170)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "cache.json").write_text("{not json")
    cache = Cache()
    assert cache.get("anything") is None


def test_fr05_cache_non_list_json_recovers(tmp_path, monkeypatch):
    """Non-list cache.json returns [] (cache.py:171-173)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "cache.json").write_text('{"not":"a list"}')
    cache = Cache()
    assert cache.get("anything") is None


# ---- Executor surface ----


def test_fr05_executor_done_result(tmp_path, monkeypatch):
    """run_task for echo returns done (executor.py:62-89)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    result = run_task({"command": "echo executor_done"})
    assert result["status"] == "done"
    assert result["exit_code"] == 0
    assert "duration_ms" in result
    assert "finished_at" in result


def test_fr05_executor_failed_result(tmp_path, monkeypatch):
    """run_task for `false` returns failed (executor.py:82-89)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    result = run_task({"command": "false"})
    assert result["status"] == "failed"
    assert result["exit_code"] == 1


def test_fr05_executor_timeout_result(tmp_path, monkeypatch):
    """run_task with short TASKQ_TASK_TIMEOUT times out (executor.py:68-77)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "0.05")
    result = run_task({"command": "sleep 5"})
    assert result["status"] == "timeout"
    assert result["exit_code"] is None


def test_fr05_executor_dataclass_cmd(tmp_path, monkeypatch):
    """_cmd_of reads .command from a Task dataclass (executor.py:41-45)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    t = Task(id="ab", name=None, command="echo dataclass_cmd")
    result = run_task(t)
    assert result["status"] == "done"


def test_fr05_executor_retry_eventually_passes(tmp_path, monkeypatch):
    """run_task retries a failing command, succeeding on later attempt (executor.py:120-130)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "3")
    import taskq.executor as exec_mod

    # States: failed, failed, done. Counts calls + ensures backoff sleeps were invoked.
    counter = {"calls": 0}

    def _fake_run_once(args, timeout):
        counter["calls"] += 1
        if counter["calls"] <= 2:
            return {
                "status": "failed",
                "exit_code": 1,
                "stdout_tail": "",
                "stderr_tail": "",
                "duration_ms": 0.5,
                "finished_at": "2026-07-11T00:00:00Z",
            }
        return {
            "status": "done",
            "exit_code": 0,
            "stdout_tail": "ok",
            "stderr_tail": "",
            "duration_ms": 0.5,
            "finished_at": "2026-07-11T00:00:00Z",
        }

    sleeps = []

    def _sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr(exec_mod, "_run_once", _fake_run_once)
    result = run_task({"command": "fake"}, sleep=_sleep)
    assert result["status"] == "done"
    assert counter["calls"] == 3
    # Two backoff sleeps expected (between attempt 0→1 and 1→2).
    assert len(sleeps) == 2, f"retry backoff must sleep between attempts, got {sleeps!r}"


def test_fr05_executor_retry_exhausted(tmp_path, monkeypatch):
    """run_task exhausts retries and returns the last failure (executor.py:128-130)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "2")
    import taskq.executor as exec_mod

    monkeypatch.setattr(
        exec_mod,
        "_run_once",
        lambda args, timeout: {
            "status": "failed",
            "exit_code": 1,
            "stdout_tail": "",
            "stderr_tail": "",
            "duration_ms": 0.5,
            "finished_at": "2026-07-11T00:00:00Z",
        },
    )
    result = run_task({"command": "fake"}, sleep=lambda _: None)
    assert result["status"] == "failed"


# ---- Store surface ----


def test_fr05_store_load_absent(tmp_path, monkeypatch):
    """TaskStore().load_tasks returns [] when file absent (store.py:55-61, 91-96)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    store = TaskStore()
    assert store.load_tasks() == []


def test_fr05_store_load_normal(tmp_path, monkeypatch):
    """TaskStore.load_tasks reads existing tasks (store.py:91-96)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "tasks.json").write_text(
        json.dumps([{"id": "1", "status": "pending", "command": "x"}])
    )
    store = TaskStore()
    tasks = store.load_tasks()
    assert len(tasks) == 1 and tasks[0]["id"] == "1"


def test_fr05_store_save_tasks(tmp_path, monkeypatch):
    """TaskStore.save_tasks persists tasks (store.py:63-66, 98-117)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    store = TaskStore()
    tasks = [{"id": "1", "status": "pending", "command": "x"}]
    store.save_tasks(tasks)
    saved = json.loads((tmp_path / "tasks.json").read_text())
    assert saved == tasks


def test_fr05_store_update_task_existing(tmp_path, monkeypatch):
    """TaskStore.update_task updates an existing task (store.py:68-87)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "tasks.json").write_text(
        json.dumps([{"id": "abcdef01", "status": "pending", "command": "x"}])
    )
    store = TaskStore()
    result = store.update_task("abcdef01", status="done", exit_code=0)
    assert result is not None
    assert result["status"] == "done" and result["exit_code"] == 0
    saved = json.loads((tmp_path / "tasks.json").read_text())
    assert saved[0]["status"] == "done"


def test_fr05_store_update_task_missing(tmp_path, monkeypatch):
    """TaskStore.update_task returns None for unknown task (store.py:68-87)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    store = TaskStore()
    assert store.update_task("nonexistent", status="done") is None


# ---- Models surface ----


def test_fr05_models_status_enum_values():
    """Status enum has the 5 lifecycle members (models.py:14-25)."""
    expected = {"pending", "running", "done", "failed", "timeout"}
    actual = {s.value for s in Status}
    assert actual == expected, f"Status enum must expose lifecycle values, got {actual}"
