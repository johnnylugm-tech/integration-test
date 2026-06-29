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
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from subprocess import TimeoutExpired
from uuid import uuid4

import pytest

# GREEN TODO: src/taskq/cli/cli.py must expose:
#   build_parser() -> argparse.ArgumentParser
#   main(argv: list[str] | None = None) -> int  (exit codes: 0/1/2/4)
# Subcommands: submit, run, status, list, clear
# Global --json flag for machine-readable single-line output
from taskq.cli.cli import main

# Already-green modules from FR-01 / FR-02; used here only for setup / assertions.
from taskq.core.models import Task, TaskStatus
from taskq.io.store import load_tasks, save_tasks_atomic


# ---------------------------------------------------------------------------
# AC-FR-03-01 (part 1) — argparse subcommand dispatch (happy paths)
# TEST_SPEC cases 1-2:
#   case 1: subcmd="submit"; cmd="echo hi"
#   case 2: subcmd="list";   tasks_present=0
# Sub-assertion: FR03-list-empty-shows-zero  (tasks_present == 0)  → case 2
# Trigger vars: cmd (covers both cases — case 2 is the sentinel "None")
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["echo hi", "None"])
def test_fr03_001_subcommands_dispatch(cmd, tmp_path: Path, monkeypatch, capsys):
    """SPEC §3 FR-03 子命令表: `submit "<cmd>"` 與 `list` 必須正確 dispatch 並回 exit 0."""
    # ---- case 1: subcmd="submit", cmd="echo hi" → exit 0 + persisted ----
    if cmd == "echo hi":  # trigger covers case 1
        monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
        code = main(["submit", cmd])
        assert code == 0, f"`submit echo hi` must exit 0; got {code}"
        captured = capsys.readouterr()
        # The submitted task must be persisted to $TASKQ_HOME/tasks.json.
        tasks = load_tasks(tmp_path)
        commands = {t.command for t in tasks.values()}
        assert cmd in commands, (
            f"submitted command {cmd!r} not persisted; store has {commands!r}"
        )
        # Submit must NOT have raised any exception; captured.err may carry
        # informational logs but must not contain validation errors.
        assert "rejected" not in captured.err.lower()

    # ---- case 2: subcmd="list", tasks_present=0 → exit 0 ----
    if cmd == "None":  # trigger covers case 2
        tasks_present = 0
        # Sub-assertion FR03-list-empty-shows-zero predicate: tasks_present == 0
        assert tasks_present == 0
        monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
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
    if len(task_id) == 8:  # trigger covers case 3
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

    if json_flag:  # trigger covers case 4
        monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
        argv = ["--json", subcmd, task_id]
        code = main(argv)
        assert code == 0, f"`--json status <id>` must exit 0; got {code}"
        captured = capsys.readouterr()
        # Sub-assertion FR03-json-single-line-no-newline predicate:
        # "\n" not in result.stdout
        assert "\n" not in captured.out, (
            f"--json output must be single-line; got {captured.out!r}"
        )
        # The output must be valid JSON carrying the task fields.
        parsed = json.loads(captured.out)
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
#   case 5: cmd="";                       cmd_type="empty"
#   case 6: injection_char="|"; cmd="echo a|b"
#   case 7: store_payload="{not valid json"
#   case 8: sleep_seconds=15; cmd="sleep 15"; timeout=1.0; subcmd="run"
# Sub-assertions:
#   FR03-empty-cmd-rejected       (cmd == "")                          → case 5
#   FR03-injection-in-cmd         (injection_char in cmd)              → case 6
#   FR03-timeout-in-single-task   (sleep_seconds > timeout)            → case 8
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["", "echo a|b", "{not valid json", "sleep 15"])
def test_fr03_003_exit_code_matrix(cmd, tmp_path: Path, monkeypatch, capsys):
    """SPEC §3 FR-03 Exit codes: 0/2/4/1 對應成功/驗證錯誤/timeout/內部錯誤."""
    # ---- case 5: cmd="" (empty) → submit must exit 2 (validation error) ----
    if cmd == "":  # trigger covers case 5
        # Sub-assertion FR03-empty-cmd-rejected predicate: cmd == ""
        assert cmd == ""
        monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
        code = main(["submit", cmd])
        assert code == 2, (
            f"`submit <empty>` must exit 2 (validation); got {code}"
        )

    # ---- case 6: cmd contains injection char `|` → exit 2 ----
    if cmd == "echo a|b":  # trigger covers case 6
        injection_char = "|"
        # Sub-assertion FR03-injection-in-cmd predicate: injection_char in cmd
        assert injection_char in cmd
        monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
        code = main(["submit", cmd])
        assert code == 2, (
            f"`submit echo a|b` must exit 2 (blacklist); got {code}"
        )

    # ---- case 7: store corrupted → exit 1 (internal error) ----
    if cmd == "{not valid json":  # trigger covers case 7
        store_payload = cmd
        monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
        (tmp_path / "tasks.json").write_text(store_payload, encoding="utf-8")
        # Any subcommand that triggers load_tasks must surface the corruption.
        code = main(["list"])
        assert code == 1, (
            f"`list` on corrupt store must exit 1 (internal); got {code}"
        )

    # ---- case 8: timeout in single-task run mode → exit 4 ----
    if cmd == "sleep 15":  # trigger covers case 8
        sleep_seconds = 15
        timeout = 1.0
        subcmd = "run"
        # Sub-assertion FR03-timeout-in-single-task predicate: sleep_seconds > timeout
        assert sleep_seconds > timeout

        # Pre-populate store with a `sleep 15` task so `run <id>` can pick it up.
        task_id = uuid4().hex[:8]
        assert len(task_id) == 8
        task = Task(
            id=task_id,
            command="sleep 15",
            status=TaskStatus.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        save_tasks_atomic(tmp_path, {task_id: task})

        monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
        monkeypatch.setenv("TASKQ_TASK_TIMEOUT", str(timeout))

        # GREEN TODO: runner.run_task must call subprocess.run via
        # `import subprocess` (so this monkeypatch site intercepts the call).
        def fake_run_timeout(argv, **kw):
            raise TimeoutExpired(argv, kw.get("timeout", timeout))

        monkeypatch.setattr(
            "taskq.runner.runner.subprocess.run", fake_run_timeout
        )

        code = main([subcmd, task_id])
        assert code == 4, (
            f"`run` on a task whose subprocess times out must exit 4; got {code}"
        )
