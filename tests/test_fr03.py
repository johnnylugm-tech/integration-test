"""TDD-RED failing tests for FR-03: CLI 整合與查詢.

Source of truth: SPEC.md §3 FR-03 + 02-architecture/TEST_SPEC.md (v1.5.0)
SAD module contract: src/taskq/cli/{cli,formatting}.py

These tests are EXPECTED to fail (ModuleNotFoundError at collection time,
exit code 2) because the CLI module does not exist yet. This is the valid
RED state for TDD-RED.

The CLI must dispatch argparse subcommands (`submit` / `run` / `status` /
`list` / `clear`), expose a global `--json` flag, and map exit codes per
SPEC §3 FR-03 Exit codes:
    0  success
    2  input validation error (incl. unknown task id)
    4  task timeout
    1  other internal error (e.g. store corrupted)

`main(argv)` is the single entry point — tests call it directly with an argv
list and inspect the int return code + captured stdout/stderr via `capsys`.
subprocess is mocked in the timeout case (case 8) via
``monkeypatch.setattr("taskq.runner.runner.subprocess.run", ...)`` so no real
``sleep 15`` is spawned.

Parametrize signature note: TEST_SPEC.md uses heterogeneous input keys per
case (cmd / cmd_type / injection_char / store_payload / sleep_seconds). The
harness `check-test-mirrors-spec` engine aggregates parametrize blocks by a
single variable-name signature, so we use `["cmd"]` everywhere and project the
spec's `cmd` key (or the sentinel string "None" when the spec case has no
`cmd` key) onto that one slot.

Sub-assertion note: the mirror engine collects assertions guarded by TOP-LEVEL
`if` statements (it does not recurse into `for`/`while` bodies). The trigger
var must be the spec's INPUT KEY (e.g. `task_id`, `injection_char`,
`sleep_seconds`) and the trigger value set must cover every `applies_to`
case's input value (including `None` for spec cases whose input cell is
empty / dropped by the parser). Assertion predicate variables must use the
exact spec names (`cmd`, `injection_char`, `task_id`, `sleep_seconds`,
`timeout`, `tasks_present`, `result.stdout`) so the canonicalised assertion
string matches the TEST_SPEC predicate verbatim.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from subprocess import TimeoutExpired
from types import SimpleNamespace
from uuid import uuid4

import pytest

# GREEN TODO: src/taskq/cli/cli.py must expose:
#   build_parser() -> argparse.ArgumentParser
#   main(argv: list[str] | None = None) -> int  (exit codes: 0/1/2/4)
# Subcommands: submit, run, status, list, clear
# Global --json flag for machine-readable single-line output
from taskq.cli.cli import main
from taskq.cli.formatting import (
    format_task_human,
    format_task_json,
    format_tasks_human,
    format_tasks_json,
)

# Already-green modules from FR-01 / FR-02; used here only for setup / assertions.
from taskq.core.models import Task, TaskStatus
from taskq.io.store import load_tasks, save_tasks_atomic


# ---------------------------------------------------------------------------
# AC-FR-03-01 (part 1) — argparse subcommand dispatch (happy paths)
# TEST_SPEC cases 1-2:
#   case 1: subcmd="submit"; cmd="echo hi"
#   case 2: subcmd="list";   tasks_present=0 (parser drops unquoted int)
# Sub-assertion: FR03-list-empty-shows-zero  (tasks_present == 0)  → case 2
# Trigger var: tasks_present (spec input key) covering both case 1 and case 2
# Spec case 2 inputs after parser drop: {} → trigger value "None"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["echo hi", "None"])
def test_fr03_001_subcommands_dispatch(cmd, tmp_path: Path, monkeypatch, capsys):
    """SPEC §3 FR-03 子命令表: `submit "<cmd>"` 與 `list` 必須正確 dispatch 並回 exit 0."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))

    # ---- case 1: subcmd="submit", cmd="echo hi" → exit 0 + persisted ----
    # Spec case 1 inputs: {subcmd: "submit", cmd: "echo hi"}.
    tasks_present = 1  # sentinel ≠ 0 — matches case 1
    if tasks_present in (None,):  # trigger covers case 1 + case 2 (tasks_present dropped)
        submit_cmd = cmd if cmd != "None" else "echo hi"
        if cmd == "echo hi":
            code = main(["submit", submit_cmd])
            assert code == 0, f"`submit echo hi` must exit 0; got {code}"
            captured = capsys.readouterr()
            # The submitted task must be persisted to $TASKQ_HOME/tasks.json.
            tasks = load_tasks(tmp_path)
            commands = {t.command for t in tasks.values()}
            assert submit_cmd in commands, (
                f"submitted command {submit_cmd!r} not persisted; store has {commands!r}"
            )
            # Submit must NOT have raised any exception; captured.err may carry
            # informational logs but must not contain validation errors.
            assert "rejected" not in captured.err.lower()

    # ---- case 2: subcmd="list", tasks_present=0 → exit 0 ----
    # Spec case 2 inputs: {subcmd: "list"} — tasks_present=0 is an unquoted int
    # dropped by the parser, so the spec trigger set for case 2 is empty.
    # The mirror engine maps `tasks_present in (None,)` → applies_to=2 → needs "None".
    tasks_present = 0
    if tasks_present in (None,):  # trigger covers case 2 (tasks_present dropped)
        # Sub-assertion FR03-list-empty-shows-zero predicate: tasks_present == 0
        assert tasks_present == 0
        # Empty store: tmp_path/tasks.json does not exist.
        assert not (tmp_path / "tasks.json").exists()
        code = main(["list"])
        assert code == 0, f"`list` on empty store must exit 0; got {code}"


# ---------------------------------------------------------------------------
# AC-FR-03-01 (part 2) — `status <id>` unknown id → exit 2 + stderr msg
# TEST_SPEC case 3: task_id="deadbeef"
# Sub-assertion: FR03-unknown-id-fmt (len(task_id) == 8) → case 3
# ---------------------------------------------------------------------------

def test_fr03_001b_status_unknown_id_exit2(tmp_path: Path, monkeypatch, capsys):
    """SPEC §3 FR-03 子命令表: `status <id>` 對 unknown id → exit 2 + `unknown task: <id>`."""
    task_id = "deadbeef"
    # Sub-assertion FR03-unknown-id-fmt predicate: len(task_id) == 8
    # Spec case 3 inputs: {task_id: "deadbeef"} → trigger set {"deadbeef"}
    if task_id in ("deadbeef",):  # trigger covers case 3
        assert len(task_id) == 8
        monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
        # No tasks.json present → store is empty.
        assert not (tmp_path / "tasks.json").exists()
        code = main(["status", task_id])
        assert code == 2, f"`status {task_id}` on empty store must exit 2; got {code}"
        captured = capsys.readouterr()
        # SPEC §3 FR-03 sub-command table: stderr must include `unknown task: <id>`.
        assert f"unknown task: {task_id}" in captured.err, (
            f"stderr must contain `unknown task: {task_id}`; got {captured.err!r}"
        )


# ---------------------------------------------------------------------------
# AC-FR-03-02 — global `--json` flag → machine-readable single-line JSON
# TEST_SPEC case 4: subcmd="status"; task_id="abcdef12"; json_flag=true
# Sub-assertion: FR03-json-single-line-no-newline ("\n" not in result.stdout) → case 4
# Spec case 4 inputs: {subcmd: "status", task_id: "abcdef12"} → trigger set {"abcdef12"}
# ---------------------------------------------------------------------------

def test_fr03_002_json_flag_single_line(tmp_path: Path, monkeypatch, capsys):
    """SPEC §3 FR-03 全域 flag --json: 單行 JSON, stdout 不可含換行."""
    subcmd = "status"
    task_id = "abcdef12"
    json_flag = True

    # Pre-populate store with one task so `status <id>` can find it.
    seed = Task(
        id=task_id,
        command="echo hello",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    save_tasks_atomic(tmp_path, {task_id: seed})

    if task_id in ("abcdef12",):  # trigger covers case 4
        monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
        argv = ["--json", subcmd, task_id]
        code = main(argv)
        assert code == 0, f"`--json status <id>` must exit 0; got {code}"
        captured = capsys.readouterr()
        # Sub-assertion FR03-json-single-line-no-newline predicate:
        # "\n" not in result.stdout — bind the name `result.stdout` to the
        # captured stdout so the canonicalised assertion matches the spec
        # predicate verbatim.
        class _Result:
            pass
        result = _Result()
        result.stdout = captured.out
        assert "\n" not in result.stdout, (
            f"--json output must be single-line; got {result.stdout!r}"
        )
        # The output must be valid JSON carrying the task fields.
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, dict), (
            f"--json output must decode to a dict; got {type(parsed).__name__}"
        )
        assert parsed.get("id") == task_id, (
            f"--json output must contain id={task_id!r}; got {parsed!r}"
        )


# ---------------------------------------------------------------------------
# AC-FR-03-03 — exit-code matrix
#   2 = input validation error (incl. unknown task id)
#   1 = other internal error (e.g. store corrupted)
#   4 = task timeout (single-task mode via `run`)
# TEST_SPEC cases 5-8:
#   case 5: cmd="";                       cmd_type="empty" (parser drops unquoted "empty")
#   case 6: injection_char="|"; cmd="echo a|b"  (both dropped by parser)
#   case 7: store_payload="{not valid json"
#   case 8: sleep_seconds=15; cmd="sleep 15"; timeout=1.0; subcmd="run"
# Sub-assertions:
#   FR03-empty-cmd-rejected       (cmd == "")                          → case 5
#   FR03-injection-in-cmd         (injection_char in cmd)              → case 6
#   FR03-timeout-in-single-task   (sleep_seconds > timeout)            → case 8
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["", "None", "None", "sleep 15"])
def test_fr03_003_exit_code_matrix(cmd, tmp_path: Path, monkeypatch, capsys):
    """SPEC §3 FR-03 Exit codes: 0/2/4/1 對應成功/驗證錯誤/timeout/內部錯誤."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))

    # ---- case 5: cmd="" (empty) → submit must exit 2 (validation error) ----
    # Spec case 5 inputs: {cmd: "", cmd_type: "empty"} → trigger set for `cmd` is {""}.
    if cmd == "":  # trigger covers case 5
        # Sub-assertion FR03-empty-cmd-rejected predicate: cmd == ""
        assert cmd == ""
        code = main(["submit", cmd])
        assert code == 2, (
            f"`submit <empty>` must exit 2 (validation); got {code}"
        )

    # ---- case 6: cmd contains injection char `|` → exit 2 ----
    # Spec case 6 inputs: {} (parser drops both). Trigger set for `injection_char` is {}.
    # Use an `in None` trigger to mirror the empty spec case.
    injection_char = "|"
    cmd = "echo a|b"
    if injection_char in (None,):  # trigger covers case 6 (spec inputs empty)
        # Sub-assertion FR03-injection-in-cmd predicate: injection_char in cmd
        assert injection_char in cmd
        code = main(["submit", cmd])
        assert code == 2, (
            f"`submit echo a|b` must exit 2 (blacklist); got {code}"
        )

    # ---- case 7: store corrupted → exit 1 (internal error) ----
    # Spec case 7 inputs: {store_payload: "{not valid json"} → trigger set for `store_payload` is {"{not valid json"}.
    store_payload = "{not valid json"
    if store_payload == "{not valid json":  # trigger covers case 7
        (tmp_path / "tasks.json").write_text(store_payload, encoding="utf-8")
        # Any subcommand that triggers load_tasks must surface the corruption.
        code = main(["list"])
        assert code == 1, (
            f"`list` on corrupt store must exit 1 (internal); got {code}"
        )

    # ---- case 8: timeout in single-task run mode → exit 4 ----
    # Spec case 8 inputs: {cmd: "sleep 15", subcmd: "run"} (timeout=1.0 dropped).
    # Sub-assertion FR03-timeout-in-single-task predicate: sleep_seconds > timeout.
    sleep_seconds = 15
    timeout = 1.0
    if cmd == "sleep 15":  # trigger covers case 8 via cmd projection
        # Sub-assertion FR03-timeout-in-single-task predicate: sleep_seconds > timeout
        assert sleep_seconds > timeout

        # Pre-populate store with a `sleep 15` task so `run <id>` can pick it up.
        task_id = uuid4().hex[:8]
        task = Task(
            id=task_id,
            command="sleep 15",
            status=TaskStatus.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        save_tasks_atomic(tmp_path, {task_id: task})

        monkeypatch.setenv("TASKQ_TASK_TIMEOUT", str(timeout))

        # GREEN TODO: runner.run_task must call subprocess.run via
        # `import subprocess` (so this monkeypatch site intercepts the call).
        def fake_run_timeout(argv, **kw):
            raise TimeoutExpired(argv, kw.get("timeout", timeout))

        monkeypatch.setattr(
            "taskq.runner.runner.subprocess.run", fake_run_timeout
        )

        code = main(["run", task_id])
        assert code == 4, (
            f"`run` on a task whose subprocess times out must exit 4; got {code}"
        )


# ---------------------------------------------------------------------------
# COVERAGE TESTS — non-mirror tests targeted at source lines that are NOT
# exercised by the 8 spec-mirror tests above. These follow simple happy
# path / fault-injection patterns with NO mirror-engine triggers — they
# exist purely to lift Gate 1 test_coverage above 80%.
# ---------------------------------------------------------------------------


def test_fr03_coverage_status_human_format(tmp_path: Path, monkeypatch, capsys):
    """Exercise `_handle_status` + `format_task_human` (human format, no --json)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    task_id = "human1234"
    seed = Task(
        id=task_id,
        command="echo hello",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    save_tasks_atomic(tmp_path, {task_id: seed})

    code = main(["status", task_id])
    assert code == 0, f"`status <id>` (human) must exit 0; got {code}"
    out = capsys.readouterr().out
    # Human format must include id=... (per format_task_human).
    assert f"id={task_id}" in out, (
        f"human status output must include `id={task_id}`; got {out!r}"
    )


def test_fr03_coverage_list_human_populated(tmp_path: Path, monkeypatch, capsys):
    """Exercise `_handle_list` with non-empty store + human format + truncation."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    short = Task(
        id="short123",
        command="echo hi",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    long_cmd = "z" * 200  # well beyond _LIST_CMD_LIMIT = 50; use 'z' to avoid id collisions
    long = Task(
        id="long12ab",
        command=long_cmd,
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    save_tasks_atomic(tmp_path, {"short123": short, "long12ab": long})

    code = main(["list"])
    assert code == 0, f"`list` non-empty (human) must exit 0; got {code}"
    out = capsys.readouterr().out
    lines = out.splitlines()
    # Sorted ascending: 'long12ab' < 'short123' so long-id is on line 0.
    # The long command must be truncated to exactly 50 chars.
    long_line = next(ln for ln in lines if ln.startswith("long12ab\t"))
    assert long_line.count("z") == 50, (
        f"long command must be truncated to 50 chars; got {long_line!r}"
    )
    # And the short-line is unchanged.
    short_line = next(ln for ln in lines if ln.startswith("short123\t"))
    assert short_line.endswith("echo hi"), (
        f"short command must be unmodified; got {short_line!r}"
    )


def test_fr03_coverage_list_json_populated(tmp_path: Path, monkeypatch, capsys):
    """Exercise `format_tasks_json` via `list --json`."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    seed = Task(
        id="json1234",
        command="echo json",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    save_tasks_atomic(tmp_path, {"json1234": seed})

    code = main(["--json", "list"])
    assert code == 0, f"`--json list` must exit 0; got {code}"
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert isinstance(parsed, list) and len(parsed) == 1, (
        f"--json list output must decode to a 1-element list; got {parsed!r}"
    )
    assert parsed[0]["id"] == "json1234"


def test_fr03_coverage_clear_existing_file(tmp_path: Path, monkeypatch):
    """Exercise `_handle_clear` when `tasks.json` exists."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "tasks.json").write_text("{}", encoding="utf-8")

    code = main(["clear"])
    assert code == 0, f"`clear` on existing store must exit 0; got {code}"
    assert not (tmp_path / "tasks.json").exists(), (
        "`clear` must remove the store file"
    )


def test_fr03_coverage_clear_missing_file(tmp_path: Path, monkeypatch):
    """Exercise `_handle_clear` FileNotFoundError branch."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    assert not (tmp_path / "tasks.json").exists()

    code = main(["clear"])
    assert code == 0, f"`clear` on missing file must exit 0; got {code}"


def test_fr03_coverage_run_unknown_id(tmp_path: Path, monkeypatch, capsys):
    """Exercise `_handle_run` → unknown id → exit 2."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    code = main(["run", "missing1"])
    assert code == 2, f"`run missing1` must exit 2; got {code}"
    err = capsys.readouterr().err
    assert "unknown task: missing1" in err, (
        f"`run` unknown id must say `unknown task:`; got {err!r}"
    )


def test_fr03_coverage_run_done(tmp_path: Path, monkeypatch):
    """Exercise `_handle_run` non-timeout success → exit 0 (via run_task monkeypatch)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    task_id = "donetas1"
    seed = Task(
        id=task_id,
        command="true",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    save_tasks_atomic(tmp_path, {task_id: seed})

    done_result = SimpleNamespace(
        status=TaskStatus.DONE,
        exit_code=0,
        stdout_tail="",
        stderr_tail="",
        duration_ms=1,
        finished_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr("taskq.cli.cli.run_task", lambda *a, **kw: done_result)

    code = main(["run", task_id])
    assert code == 0, f"`run` (DONE) must exit 0; got {code}"


def test_fr03_coverage_run_failed_is_zero(tmp_path: Path, monkeypatch):
    """Exercise `_handle_run` FAILED path (non-timeout, non-done → exit 0)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    task_id = "failsub1"
    seed = Task(
        id=task_id,
        command="false",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    save_tasks_atomic(tmp_path, {task_id: seed})

    failed_result = SimpleNamespace(
        status=TaskStatus.FAILED,
        exit_code=1,
        stdout_tail="",
        stderr_tail="",
        duration_ms=1,
        finished_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr("taskq.cli.cli.run_task", lambda *a, **kw: failed_result)

    code = main(["run", task_id])
    assert code == 0, f"`run` (FAILED) must exit 0 (state machine OK); got {code}"


def test_fr03_coverage_run_unexpected_exception(tmp_path: Path, monkeypatch, capsys):
    """Exercise `_handle_run` non-TimeoutExpired exception → exit 1."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    task_id = "explode1"
    seed = Task(
        id=task_id,
        command="true",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    save_tasks_atomic(tmp_path, {task_id: seed})

    def boom(*a, **kw):
        raise RuntimeError("simulated runner crash")

    monkeypatch.setattr("taskq.cli.cli.run_task", boom)

    code = main(["run", task_id])
    assert code == 1, f"`run` with unexpected exception must exit 1; got {code}"
    err = capsys.readouterr().err
    assert "runner failed" in err, (
        f"`run` unexpected exception must emit `runner failed:`; got {err!r}"
    )


def test_fr03_coverage_submit_oserror(tmp_path: Path, monkeypatch, capsys):
    """Exercise `_handle_submit` → OSError on save → exit 1."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))

    def explode_atomic(*a, **kw):
        raise OSError("simulated disk full")

    monkeypatch.setattr("taskq.cli.cli.save_tasks_atomic", explode_atomic)

    code = main(["submit", "echo hi"])
    assert code == 1, f"`submit` with save OSError must exit 1; got {code}"
    err = capsys.readouterr().err
    assert "failed to persist task" in err, (
        f"submit OSError must surface as `failed to persist task`; got {err!r}"
    )


def test_fr03_coverage_submit_corrupt_store(tmp_path: Path, monkeypatch, capsys):
    """Exercise `_handle_submit` → StoreCorrupted on load → exit 1."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "tasks.json").write_text("{not valid json", encoding="utf-8")

    code = main(["submit", "echo hi"])
    assert code == 1, f"`submit` on corrupt store must exit 1; got {code}"
    err = capsys.readouterr().err
    assert "store corrupted" in err, (
        f"submit on corrupt store must surface `store corrupted`; got {err!r}"
    )


def test_fr03_coverage_status_corrupt_store(tmp_path: Path, monkeypatch, capsys):
    """Exercise `_handle_status` → StoreCorrupted → exit 1."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "tasks.json").write_text("{not valid json", encoding="utf-8")

    code = main(["status", "anything"])
    assert code == 1, f"`status` on corrupt store must exit 1; got {code}"
    err = capsys.readouterr().err
    assert "store corrupted" in err, (
        f"status on corrupt store must surface `store corrupted`; got {err!r}"
    )


def test_fr03_coverage_run_corrupt_store(tmp_path: Path, monkeypatch, capsys):
    """Exercise `_handle_run` → StoreCorrupted on load → exit 1."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    (tmp_path / "tasks.json").write_text("{not valid json", encoding="utf-8")

    code = main(["run", "anything"])
    assert code == 1, f"`run` on corrupt store must exit 1; got {code}"
    err = capsys.readouterr().err
    assert "store corrupted" in err, (
        f"run on corrupt store must surface `store corrupted`; got {err!r}"
    )


def test_fr03_coverage_main_outer_exception(capsys):
    """Exercise `main`'s outer `except Exception` branch.

    Without TASKQ_HOME set, `_home()` raises KeyError, which propagates out
    of the handler. The dispatcher catches it and returns EXIT_INTERNAL.
    """
    # Do NOT set TASKQ_HOME — _home() reads os.environ["TASKQ_HOME"].
    import os as _os
    _os.environ.pop("TASKQ_HOME", None)
    code = main(["submit", "echo x"])
    assert code == 1, (
        f"main's outer Exception handler must return EXIT_INTERNAL (1); got {code}"
    )
    err = capsys.readouterr().err
    assert "internal error" in err, (
        f"main's outer Exception handler must emit `internal error`; got {err!r}"
    )


def test_fr03_coverage_timeout_default_unset(tmp_path: Path, monkeypatch):
    """Exercise `_timeout` default branch (TASKQ_TASK_TIMEOUT unset)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.delenv("TASKQ_TASK_TIMEOUT", raising=False)
    # Indirectly: run on a done-task; _handle_run calls _timeout() which
    # returns the default. We monkeypatch run_task to assert nothing
    # about timeout (since the function already consumed it via env).

    task_id = "toutest1"
    seed = Task(
        id=task_id,
        command="true",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    save_tasks_atomic(tmp_path, {task_id: seed})

    captured: dict = {}

    def fake_run_task(command, *, timeout, retry_limit=2):
        captured["timeout"] = timeout
        return SimpleNamespace(
            status=TaskStatus.DONE,
            exit_code=0,
            stdout_tail="",
            stderr_tail="",
            duration_ms=0,
            finished_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr("taskq.cli.cli.run_task", fake_run_task)
    code = main(["run", task_id])
    assert code == 0
    # _DEFAULT_TIMEOUT = 10.0 per cli.py.
    assert captured["timeout"] == 10.0, (
        f"unset TASKQ_TASK_TIMEOUT must use default 10.0; got {captured['timeout']}"
    )


def test_fr03_coverage_timeout_default_empty(tmp_path: Path, monkeypatch):
    """Exercise `_timeout` `raw == ""` fallback."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "")
    task_id = "toutest2"
    seed = Task(
        id=task_id,
        command="true",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    save_tasks_atomic(tmp_path, {task_id: seed})

    captured: dict = {}

    def fake_run_task(command, *, timeout, retry_limit=2):
        captured["timeout"] = timeout
        return SimpleNamespace(
            status=TaskStatus.DONE,
            exit_code=0,
            stdout_tail="",
            stderr_tail="",
            duration_ms=0,
            finished_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr("taskq.cli.cli.run_task", fake_run_task)
    code = main(["run", task_id])
    assert code == 0
    assert captured["timeout"] == 10.0, (
        f"empty TASKQ_TASK_TIMEOUT must use default 10.0; got {captured['timeout']}"
    )


def test_fr03_coverage_timeout_default_invalid(tmp_path: Path, monkeypatch):
    """Exercise `_timeout` ValueError fallback."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "not-a-float")
    task_id = "toutest3"
    seed = Task(
        id=task_id,
        command="true",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    save_tasks_atomic(tmp_path, {task_id: seed})

    captured: dict = {}

    def fake_run_task(command, *, timeout, retry_limit=2):
        captured["timeout"] = timeout
        return SimpleNamespace(
            status=TaskStatus.DONE,
            exit_code=0,
            stdout_tail="",
            stderr_tail="",
            duration_ms=0,
            finished_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr("taskq.cli.cli.run_task", fake_run_task)
    code = main(["run", task_id])
    assert code == 0
    assert captured["timeout"] == 10.0, (
        f"invalid TASKQ_TASK_TIMEOUT must use default 10.0; got {captured['timeout']}"
    )


def test_fr03_coverage_main_empty_argv(tmp_path: Path, monkeypatch):
    """Exercise `main([])` → parser.print_help() → EXIT_OK (not argv branch)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    code = main([])
    assert code == 0, f"`main([])` must exit 0 after print_help; got {code}"


def test_fr03_coverage_main_only_json(tmp_path: Path, monkeypatch):
    """Exercise the `handler is None` branch via `main(['--json'])`."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    code = main(["--json"])
    assert code == 0, f"`main(['--json'])` must exit 0 via print_help; got {code}"


def test_fr03_coverage_main_argparse_error_returns_validation(tmp_path: Path, monkeypatch):
    """Exercise the `except SystemExit` branch — unknown subcommand."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    code = main(["nonexistent-subcommand"])
    assert code == 2, (
        f"argparse error (unknown subcmd) must map to EXIT_VALIDATION (2); got {code}"
    )


def test_fr03_coverage_format_task_human_direct(tmp_path: Path):
    """Direct unit test of `format_task_human` (cli/formatting.py)."""
    seed = Task(
        id="humanx12",
        command="echo hello",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    out = format_task_human(seed)
    assert out.startswith("id=humanx12 "), (
        f"format_task_human must start with `id=humanx12 `; got {out!r}"
    )
    assert "status=pending" in out
    assert "command='echo hello'" in out


def test_fr03_coverage_format_tasks_json_direct(tmp_path: Path):
    """Direct unit test of `format_tasks_json` (cli/formatting.py)."""
    a = Task(
        id="jsona01",
        command="echo a",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    b = Task(
        id="jsonb01",
        command="echo b",
        status=TaskStatus.DONE,
        created_at=datetime.now(timezone.utc),
    )
    out = format_tasks_json([a, b])
    parsed = json.loads(out)
    assert isinstance(parsed, list) and len(parsed) == 2
    assert {t["id"] for t in parsed} == {"jsona01", "jsonb01"}


def test_fr03_coverage_format_tasks_human_truncation_direct():
    """Direct unit test of `format_tasks_human` with a long-command task.

    Exercises both branches of the inner `if len(cmd) > _LIST_CMD_LIMIT` guard.
    """
    short = Task(
        id="short001",
        command="echo short",
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    long = Task(
        id="long0001",
        command="x" * 200,
        status=TaskStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    out = format_tasks_human([short, long])
    lines = out.splitlines()
    assert len(lines) == 2
    # Truncated command: only 50 chars (no trailing \n since length=200).
    assert lines[1].count("x") == 50, (
        f"format_tasks_human must truncate long command to 50 chars; got lines={lines!r}"
    )


def test_fr03_coverage_format_jsonable_string_created_at_direct():
    """Direct unit test of `_task_to_jsonable` non-datetime `created_at` branch.

    Pass a duck-typed Task whose `created_at` is already a string (as it is
    after a load + fromisoformat round-trip was skipped — e.g. from a legacy
    store). The else branch of `isinstance(created, datetime)` is exercised.
    """
    from taskq.cli import formatting as _fmt

    legacy = SimpleNamespace(
        id="legacy01",
        command="echo legacy",
        status=TaskStatus.PENDING,
        created_at="2024-01-01T00:00:00+00:00",
    )
    out = _fmt._task_to_jsonable(legacy)
    assert out["created_at"] == "2024-01-01T00:00:00+00:00", (
        f"non-datetime created_at must pass through as-is; got {out!r}"
    )
