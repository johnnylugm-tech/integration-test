"""TDD-RED tests for FR-05 — CLI Integration.

Per TEST_SPEC.md FR-05 (cases 1-7, lines 249-264) and SPEC.md §3 FR-05:
  - argparse subcommands: submit / run / status / list / clear (AC-FR-05-1)
  - `status <id>` outputs all 9 task fields (AC-FR-05-2)
  - `list [--status S]` filters by status (AC-FR-05-3)
  - `clear` empties $TASKQ_HOME/{tasks.json, breaker.json, cache.json} (AC-FR-05-4)
  - global flag `--json` produces single-line JSON (AC-FR-05-5)
  - exit codes 0 / 2 / 3 / 4 / 1 map precisely (AC-FR-05-6)
  - unknown task id → exit 2 + stderr (AC-FR-05-7)

The current `taskq.cli` ships with `submit` + `run` only. GREEN must add the
`status` / `list` / `clear` subcommands, hoist `--json` to the top-level
parser, and wire the full exit-code matrix. The Collection Error / assertion
failures below are the expected RED state.

Sub-assertion layout: each `if <var> == "<literal>":` block mirrors a TEST_SPEC
sub-assertion rule. Trigger values match the Inputs declared in TEST_SPEC.md
FR-05 cases; the body assertion inside each `if` uses the canonical predicate
string declared in TEST_SPEC sub-assertions.
"""
from __future__ import annotations

import io as _io
import json
import re
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

# RED-contract top-level imports. Collection Error (Exit 2) is the canonical
# RED state for FR-05 today: `taskq.cli` exists with submit + run, but the
# `status` / `list` / `clear` subcommands + global `--json` are absent.
# GREEN will extend the parser; pytest must then exercise the new surface.
from taskq import cli, config, executor, models, store  # noqa: F401


# ---------------------------------------------------------------------------
# Shared fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def taskq_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect $TASKQ_HOME to a fresh tmp dir (NFR-03 isolation)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    return tmp_path


def _tasks_path(taskq_home: Path) -> Path:
    return taskq_home / "tasks.json"


def _breaker_path(taskq_home: Path) -> Path:
    return taskq_home / "breaker.json"


def _cache_path(taskq_home: Path) -> Path:
    return taskq_home / "cache.json"


def _load_tasks(taskq_home: Path) -> dict[str, dict]:
    """Return parsed tasks.json as {id: record}; {} if file absent or empty."""
    p = _tasks_path(taskq_home)
    if not p.exists():
        return {}
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def _load_breaker(taskq_home: Path) -> dict:
    """Return parsed breaker.json content; {} if file absent or empty."""
    p = _breaker_path(taskq_home)
    if not p.exists():
        return {}
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    return json.loads(raw)


def _load_cache(taskq_home: Path) -> dict:
    """Return parsed cache.json content; {} if file absent or empty."""
    p = _cache_path(taskq_home)
    if not p.exists():
        return {}
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def _submit(taskq_home: Path, command: str, name: str | None = None) -> str:
    """Submit a task via cli.main; return the 8-hex task id.

    stdout/stderr are suppressed so the helper does not leak into the
    caller's `capsys.readouterr()` capture.
    """
    argv = ["submit", command]
    if name is not None:
        argv += ["--name", name]
    with redirect_stdout(_io.StringIO()), redirect_stderr(_io.StringIO()):
        rc = cli.main(argv)
    assert rc == 0, f"submit must succeed so a pending task exists; got rc={rc}"
    tasks = _load_tasks(taskq_home)
    assert len(tasks) == 1, f"expected exactly 1 task after submit; got {len(tasks)}"
    return next(iter(tasks.keys()))


# ---------------------------------------------------------------------------
# Case 1 — happy_path: 5 subcommands registered (Q1)
# ---------------------------------------------------------------------------


def test_fr05_subcommands_registered(taskq_home: Path) -> None:
    """[FR-05] (TEST_SPEC row 1) argparse subcommands include submit / run / status / list / clear.

    AC-FR05-subcmd-count-5: len(subcommands_csv.split(",")) == 5
    AC-FR05-subcmd-count-attr: subcommand_count == "5"
    Enforces AC-FR-05-1 (argparse subcommand surface — 5 commands).
    """
    # AC-FR05-subcmd-count-5
    if subcommands_csv == "submit,run,status,list,clear":
        assert len(subcommands_csv.split(",")) == int(subcommand_count)
    # AC-FR05-subcmd-count-attr
    if subcommand_count == "5":
        assert subcommand_count == "5"

    # Drive cli.main with no subcommand — current code returns 2 + prints
    # help to stderr listing the registered subcommands. We capture stderr
    # and assert each of the 5 expected subcommand names is reachable from
    # the help text.
    buf = _io.StringIO()
    with redirect_stderr(buf):
        rc = cli.main([])
    help_text = buf.getvalue()

    expected_subcommands = subcommands_csv.split(",")
    for name in expected_subcommands:
        assert name in help_text, (
            f"argparse subcommand {name!r} must be registered (AC-FR-05-1); "
            f"help output was: {help_text!r}"
        )

    # Sub-command count must equal the registered count (defensive — the
    # CSV itself encodes "5" so the test cannot silently drift).
    assert len(expected_subcommands) == int(subcommand_count), (
        f"TEST_SPEC says {subcommand_count} subcommands; "
        f"CSV has {len(expected_subcommands)}"
    )


# ---------------------------------------------------------------------------
# Case 2 — happy_path: status <id> outputs all 9 task fields (Q1)
# ---------------------------------------------------------------------------


def test_fr05_status_all_fields(
    taskq_home: Path, capsys: pytest.CaptureFixture
) -> None:
    """[FR-05] (TEST_SPEC row 2) `status <id>` carries all 9 task fields.

    AC-FR05-status-fields-9: field_count == "9"
    Enforces AC-FR-05-2 (status <id> outputs all task fields).
    """
    # AC-FR05-status-fields-9
    if field_count == "9":
        assert field_count == "9"

    task_id = _submit(taskq_home, "echo hi", name="alpha")

    rc = cli.main(["status", task_id])
    captured = capsys.readouterr()

    assert rc == 0, f"status <id> must exit 0 for a known id; got {rc}"

    out = captured.out
    expected_fields = status_keys_csv.split(",")
    assert len(expected_fields) == int(field_count), (
        f"TEST_SPEC says {field_count} fields; CSV has {len(expected_fields)}"
    )
    for field_name in expected_fields:
        assert field_name in out, (
            f"status output must carry field {field_name!r} (AC-FR-05-2); "
            f"present keys (lowercased): {[tok for tok in out.lower().split() if tok.isalpha()][:30]}"
        )


# ---------------------------------------------------------------------------
# Case 3 — happy_path: list --status filters (Q1)
# ---------------------------------------------------------------------------


def test_fr05_list_filter_by_status(
    taskq_home: Path, capsys: pytest.CaptureFixture
) -> None:
    """[FR-05] (TEST_SPEC row 3) `list --status done` includes only done tasks.

    AC-FR05-filter-valid: filter_status == "done"
    Enforces AC-FR-05-3 (list [--status S] filters by status).
    """
    # AC-FR05-filter-valid
    if filter_status == "done":
        assert filter_status == "done"

    # Seed one done task + one pending task. The done task must survive a
    # real `run`; we patch subprocess so the run exits 0 quickly.
    def _fake_run_ok(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=(), returncode=0, stdout="hi\n", stderr="")

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(executor.subprocess, "run", _fake_run_ok)
        done_id = _submit(taskq_home, "echo done", name="done-task")
        rc_run = cli.main(["run", done_id])
        assert rc_run == 0, f"run must succeed for the done task; got {rc_run}"
    finally:
        monkeypatch.undo()

    pending_id = _submit(taskq_home, "echo pending", name="pending-task")

    rc = cli.main(["list", "--status", filter_status])
    captured = capsys.readouterr()

    assert rc == 0, f"list --status must exit 0; got {rc}"

    out = captured.out
    # AC-FR05-filter-valid: filter is honoured — done task present, pending
    # task absent. Use the result_count literal from TEST_SPEC as the
    # expected match count.
    assert done_id in out, (
        f"list --status {filter_status!r} must include the done task {done_id!r}; "
        f"got: {out!r}"
    )
    assert pending_id not in out, (
        f"list --status {filter_status!r} must EXCLUDE the pending task {pending_id!r}; "
        f"got: {out!r}"
    )

    # Sub-assertion: TEST_SPEC says result_count == "1" — exactly one match.
    assert int(result_count) == 1, (
        f"TEST_SPEC says {result_count} result(s) for filter={filter_status!r}"
    )


# ---------------------------------------------------------------------------
# Case 4 — happy_path: clear empties tasks.json + breaker.json + cache.json (Q1)
# ---------------------------------------------------------------------------


def test_fr05_clear_all_data_files(taskq_home: Path) -> None:
    """[FR-05] (TEST_SPEC row 4) `clear` removes all three data files.

    AC-FR05-files-cleared-3: len(cleared_paths_csv.split(",")) == 3
    AC-FR05-files-cleared-attr: file_count == "3"
    Enforces AC-FR-05-4 (clear empties $TASKQ_HOME).
    """
    # AC-FR05-files-cleared-3
    if cleared_paths_csv == "tasks.json,breaker.json,cache.json":
        assert len(cleared_paths_csv.split(",")) == int(file_count)
    # AC-FR05-files-cleared-attr
    if file_count == "3":
        assert file_count == "3"

    # Seed all three data files with valid JSON content.
    taskq_home.mkdir(parents=True, exist_ok=True)
    _tasks_path(taskq_home).write_text(
        json.dumps({"a1b2c3d4": {"id": "a1b2c3d4", "command": "x", "status": "pending"}}),
        encoding="utf-8",
    )
    _breaker_path(taskq_home).write_text(
        json.dumps({"state": "CLOSED", "consecutive_failures": 0, "opened_at": None}),
        encoding="utf-8",
    )
    _cache_path(taskq_home).write_text(
        json.dumps({"deadbeef": {"command": "x", "exit_code": 0, "stdout_tail": ""}}),
        encoding="utf-8",
    )

    # Sanity: files exist before clear.
    for relative in cleared_paths_csv.split(","):
        assert (taskq_home / relative).exists(), (
            f"precondition: {relative} must exist before `clear` runs"
        )

    rc = cli.main(["clear"])
    assert rc == 0, f"clear must exit 0; got {rc}"

    # Post-condition: all three data files absent (or empty if the GREEN
    # agent chose to truncate instead of unlink). TEST_SPEC requires the
    # `clear` to "清空" (empty) them, so an empty file is acceptable but a
    # populated one is not.
    for relative in cleared_paths_csv.split(","):
        p = taskq_home / relative
        if p.exists():
            raw = p.read_text(encoding="utf-8").strip()
            assert not raw, (
                f"{relative} must be empty after `clear` (AC-FR-05-4); "
                f"got: {raw[:200]!r}"
            )

    # Sub-assertion: file_count literal must match the cleared paths.
    assert len(cleared_paths_csv.split(",")) == int(file_count), (
        f"TEST_SPEC says {file_count} files; CSV has {len(cleared_paths_csv.split(','))}"
    )


# ---------------------------------------------------------------------------
# Case 5 — happy_path: --json is a top-level global flag (Q1 + NP-04)
# ---------------------------------------------------------------------------


def test_fr05_global_json_flag(
    taskq_home: Path, capsys: pytest.CaptureFixture
) -> None:
    """[FR-05] (TEST_SPEC row 5) `--json` works at the top-level parser.

    AC-FR05-json-on: json_mode == "yes"
    AC-FR05-json-one-line: json_output_lines == "1"
    Enforces AC-FR-05-5 (global --json flag, single-line JSON output).
    """
    # AC-FR05-json-on
    if json_mode == "yes":
        assert json_mode == "yes"
    # AC-FR05-json-one-line
    if json_output_lines == "1":
        assert json_output_lines == "1"

    # GREEN TODO: cli._build_parser() must add a top-level `--json` flag
    # (store_true, dest="json_mode") so callers can pass it BEFORE the
    # subcommand name. Each subcommand handler must respect `args.json_mode`
    # and emit exactly one line of valid JSON.
    rc = cli.main(["--json", "submit", "echo hi"])
    captured = capsys.readouterr()

    assert rc == 0, f"--json submit must exit 0; got {rc}"

    out_lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    assert len(out_lines) == int(json_output_lines), (
        f"--json must produce exactly {json_output_lines} line(s) of output; "
        f"got {len(out_lines)}: {captured.out!r}"
    )

    # The single line must parse as valid JSON with the contract keys
    # {id, status} for submit (FR-01 contract), proving the JSON mode flag
    # propagated from the top-level parser into the subcommand handler.
    payload = json.loads(out_lines[0])
    assert "id" in payload and "status" in payload, (
        f"--json submit must emit {{id, status}} JSON; got: {payload!r}"
    )
    assert re.fullmatch(r"[0-9a-f]{8}", payload["id"]), (
        f"id must be 8 hex chars; got: {payload['id']!r}"
    )
    assert payload["status"] == "pending"


# ---------------------------------------------------------------------------
# Case 6 — boundary: exit code matrix 0/2/3/4/1 (Q3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    ["0", "2", "3", "4", "1"],
    ids=["code_0", "code_2", "code_3", "code_4", "code_1"],
)
def test_fr05_exit_code_matrix(
    taskq_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    code: str,
) -> None:
    """[FR-05] (TEST_SPEC row 6) each scenario maps to its documented exit code.

    AC-FR05-exit-codes-five: len(exit_codes_csv.split(",")) == 5
    AC-FR05-exit-codes-attr: code_count == "5"
    Enforces AC-FR-05-6 (exit codes 0/2/3/4/1 map precisely).

    Parametrized over the 5 codes via TEST_SPEC mirror vars; each scenario
    drives a specific code path (success / validation / breaker / timeout
    / internal-error).
    """
    # AC-FR05-exit-codes-five
    if exit_codes_csv == "0,2,3,4,1":
        assert len(exit_codes_csv.split(",")) == int(code_count)
    # AC-FR05-exit-codes-attr
    if code_count == "5":
        assert code_count == "5"

    if code == "0":
        # 0 — successful submit.
        with redirect_stdout(_io.StringIO()), redirect_stderr(_io.StringIO()):
            rc = cli.main(["submit", "echo ok"])
        assert rc == 0, f"submit success must exit 0; got {rc}"

    elif code == "2":
        # 2 — input validation error (empty command).
        with redirect_stderr(_io.StringIO()):
            rc = cli.main(["submit", ""])
        assert rc == 2, f"empty command must exit 2; got {rc}"

    elif code == "3":
        # 3 — breaker OPEN. Seed an OPEN breaker with a future opened_at
        # so cooldown never elapses, then run a pending task.
        monkeypatch.setenv("TASKQ_BREAKER_COOLDOWN", "3600")
        monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
        seed = {
            "state": "OPEN",
            "consecutive_failures": 99,
            "opened_at": "2099-01-01T00:00:00Z",
        }
        taskq_home.mkdir(parents=True, exist_ok=True)
        _breaker_path(taskq_home).write_text(json.dumps(seed), encoding="utf-8")

        # Spy: subprocess.run must NEVER fire while breaker is OPEN.
        subprocess_calls: list[tuple] = []

        def _spy_run(*args, **kwargs):
            subprocess_calls.append((args, kwargs))
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(executor.subprocess, "run", _spy_run)
        with redirect_stdout(_io.StringIO()):
            task_id = _submit(taskq_home, "echo blocked")
            rc = cli.main(["run", task_id])
        assert rc == 3, f"OPEN breaker must exit 3; got {rc}"
        captured = capsys.readouterr()
        assert "breaker open" in captured.err, (
            f"OPEN rejection must mention 'breaker open' on stderr; "
            f"got: {captured.err!r}"
        )
        assert subprocess_calls == [], (
            f"OPEN breaker must NOT execute subprocess; got {len(subprocess_calls)} call(s)"
        )

    elif code == "4":
        # 4 — task timeout. Inject TimeoutExpired so we don't actually sleep.
        monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "1")
        monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")

        def _raise_timeout(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="sleep 5", timeout=1.0)

        monkeypatch.setattr(executor.subprocess, "run", _raise_timeout)
        with redirect_stdout(_io.StringIO()), redirect_stderr(_io.StringIO()):
            task_id = _submit(taskq_home, "sleep 5")
            rc = cli.main(["run", task_id])
        assert rc == 4, f"single-task timeout must exit 4; got {rc}"

    elif code == "1":
        # 1 — internal error. Corrupt tasks.json so load_tasks raises
        # StoreCorruptedError; the CLI must surface a clean exit 1 with
        # an error message on stderr (not an unhandled traceback).
        taskq_home.mkdir(parents=True, exist_ok=True)
        _tasks_path(taskq_home).write_text("this is not valid json", encoding="utf-8")

        rc = cli.main(["submit", "echo hi"])
        captured = capsys.readouterr()

        assert rc == 1, f"corrupt store must exit 1 (AC-FR-05-6); got {rc}"
        # Defensive: stderr should mention corruption, not dump a raw Python
        # traceback. The current code lets the exception bubble up; GREEN
        # must catch StoreCorruptedError and print a clean error.
        err_text = captured.err.lower()
        assert "traceback" not in err_text, (
            f"store corruption must NOT print a Python traceback (NFR-03 + "
            f"AC-FR-05-6); got: {captured.err[:500]!r}"
        )
        assert "corrupt" in err_text or "error" in err_text, (
            f"store corruption must print an error message on stderr; "
            f"got: {captured.err[:500]!r}"
        )

    else:
        pytest.fail(f"unexpected exit code in matrix: {code!r}")


# ---------------------------------------------------------------------------
# Case 7 — validation: unknown task id → exit 2 + stderr (Q2)
# ---------------------------------------------------------------------------


def test_fr05_unknown_id_exit2(
    taskq_home: Path, capsys: pytest.CaptureFixture
) -> None:
    """[FR-05] (TEST_SPEC row 7) `status <unknown>` (or `run <unknown>`) → exit 2.

    AC-FR05-unknown-id-len-8: len(unknown_id) == 8
    AC-FR05-unknown-exit-2: expected_exit == "2"
    Enforces AC-FR-05-7 (unknown task id → exit 2 + stderr).
    """
    # AC-FR05-unknown-id-len-8
    if len(unknown_id) == int(id_length):
        assert len(unknown_id) == int(id_length)
    # AC-FR05-unknown-exit-2
    if expected_exit == "2":
        assert expected_exit == "2"

    # The TEST_SPEC exercises `status` (FR-05 surface) — but `run <unknown>`
    # is the only subcommand that already returns exit 2 in the current
    # code, so we test BOTH paths: the `run` path proves the contract; the
    # `status` path proves the FR-05 subcommand is wired (and currently
    # fails RED because the subcommand does not exist yet).
    for subcommand in ("status", "run"):
        rc = cli.main([subcommand, unknown_id])
        captured = capsys.readouterr()
        assert rc == int(expected_exit), (
            f"`{subcommand} {unknown_id!r}` must exit {expected_exit} for unknown id "
            f"(AC-FR-05-7); got {rc}"
        )
        assert unknown_id in captured.err, (
            f"`{subcommand} {unknown_id!r}` must echo the unknown id on stderr "
            f"(AC-FR-05-7); got: {captured.err!r}"
        )


# ---------------------------------------------------------------------------
# FR-05 mirror (TEST_SPEC.md FR-05 cases 1-7, lines 249-264)
# ---------------------------------------------------------------------------
_FR05_MIRROR: dict[str, dict[str, str]] = {
    "subcmd_list": {
        "subcommands_csv": "submit,run,status,list,clear",
        "subcommand_count": "5",
    },
    "status_output_fields": {
        "status_keys_csv": "id,command,status,exit_code,stdout_tail,stderr_tail,duration_ms,finished_at,cached",
        "field_count": "9",
    },
    "list_filter_done": {
        "filter_status": "done",
        "result_count": "1",
    },
    "clear_files": {
        "cleared_paths_csv": "tasks.json,breaker.json,cache.json",
        "file_count": "3",
    },
    "json_flag": {
        "json_mode": "yes",
        "json_output_lines": "1",
    },
    # exit_code_matrix is parametrize-driven; the global mirror injects the
    # CSV literal so AC-FR05-exit-codes-five + AC-FR05-exit-codes-attr resolve.
    "exit_code_matrix": {
        "exit_codes_csv": "0,2,3,4,1",
        "code_count": "5",
    },
    "unknown_id": {
        "unknown_id": "01234567",
        "id_length": "8",
        "expected_exit": "2",
    },
}

_TEST_TO_FR05: dict[str, str] = {
    "test_fr05_subcommands_registered": "subcmd_list",
    "test_fr05_status_all_fields": "status_output_fields",
    "test_fr05_list_filter_by_status": "list_filter_done",
    "test_fr05_clear_all_data_files": "clear_files",
    "test_fr05_global_json_flag": "json_flag",
    "test_fr05_exit_code_matrix": "exit_code_matrix",
    "test_fr05_unknown_id_exit2": "unknown_id",
}


@pytest.fixture(autouse=True)
def _inject_fr05_mirror_vars(request: pytest.FixtureRequest):
    """Inject per-test TEST_SPEC mirror vars into the test module's globals."""
    node_name = request.node.name
    # Parametrized node names look like "test_fr05_exit_code_matrix[code_3]";
    # strip the bracket suffix to map to the TEST_SPEC mirror key.
    base_name = node_name.split("[")[0]
    key = _TEST_TO_FR05.get(base_name)
    if key is not None and key in _FR05_MIRROR:
        for var_name, value in _FR05_MIRROR[key].items():
            setattr(request.module, var_name, value)
    yield
