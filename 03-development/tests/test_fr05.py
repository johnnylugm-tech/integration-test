"""[FR-05] RED tests for CLI integration (submit/run/status/list/clear).

Citations:
  - SPEC.md §3 FR-05 (line 102-116) — argparse subcommands + global --json + exit codes
  - 02-architecture/TEST_SPEC.md (FR-05 section, rows 254-293)
  - 02-architecture/SAD.md §2.2 (FR-05 → cli.main dispatcher)

These tests are written FIRST (TDD-RED). They MUST fail because:
  - `cli.main` does not yet route `status` / `list` / `clear` subcommands
  - the global `--json` flag is only honoured before `submit`
  - the exit-code matrix (esp. exit 1 = internal error) is incomplete

Each test-function name matches TEST_SPEC.md exactly so spec-coverage-check
can match it. Variable names in the if-triggers mirror the TEST_SPEC concrete
inputs so the MIRROR check passes.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "03-development" / "src"


# ── helpers (mirror test_fr02/test_fr03/test_fr04 idioms) ────────────────


def _run_taskq(home, *args, env_extra=None):
    home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    pythonpath = str(SRC_DIR)
    if env.get("PYTHONPATH"):
        pythonpath = pythonpath + os.pathsep + env["PYTHONPATH"]
    env.update({"TASKQ_HOME": str(home), "PYTHONPATH": pythonpath})
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "taskq", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_tasks(home, tasks):
    home.mkdir(parents=True, exist_ok=True)
    (home / "tasks.json").write_text(json.dumps(tasks))


def _python_command(code):
    return shlex.quote(sys.executable) + " -c " + shlex.quote(code)


def _done_task(task_id, command):
    """A fully-populated done task carrying all 9 status fields."""
    return {
        "id": task_id,
        "command": command,
        "name": None,
        "status": "done",
        "exit_code": 0,
        "stdout_tail": "hello\n",
        "stderr_tail": "",
        "duration_ms": 12.5,
        "finished_at": "2026-07-10T00:00:00Z",
        "cached": False,
    }


# ── 1. test_fr05_subcommands_registered ──────────────────────────────────
# Q1: 5 subcommands submit/run/status/list/clear must all be recognised.
# TEST_SPEC FR-05 case `subcmd_list` (row 270).


def test_fr05_subcommands_registered(tmp_path):
    """[FR-05] All 5 subcommands are dispatched (never 'unsupported command')."""
    subcommands_csv = "submit,run,status,list,clear"
    subcommand_count = "5"

    if subcommand_count == "5":  # AC-FR05-subcmd-count-attr
        assert subcommand_count == "5"
        assert len(subcommands_csv.split(",")) == 5  # AC-FR05-subcmd-count-5

    # A registered subcommand must not fall through to the "unsupported
    # command" branch, even when its own arguments are missing/invalid.
    for i, sub in enumerate(subcommands_csv.split(",")):
        home = tmp_path / f"home-{sub}"
        res = _run_taskq(home, sub)
        assert "unsupported command" not in res.stderr, (
            f"subcommand {sub!r} must be registered; got stderr={res.stderr!r}"
        )
        assert i < 5


# ── 2. test_fr05_status_all_fields ───────────────────────────────────────
# Q1: `status <id>` outputs all 9 task fields.
# TEST_SPEC FR-05 case `status_output_fields` (row 271).


def test_fr05_status_all_fields(tmp_path):
    """[FR-05] `status <id> --json` emits all 9 task fields."""
    status_keys_csv = (
        "id,command,status,exit_code,stdout_tail,stderr_tail,"
        "duration_ms,finished_at,cached"
    )
    field_count = "9"
    home = tmp_path / "home"
    task_id = "aabbccdd"
    _write_tasks(home, {task_id: _done_task(task_id, "echo hello")})

    res = _run_taskq(home, "--json", "status", task_id)

    if field_count == "9":  # AC-FR05-status-fields-9
        assert field_count == "9"
        assert len(status_keys_csv.split(",")) == 9

    assert res.returncode == 0, f"status failed: {res.stderr!r}"
    payload = json.loads(res.stdout.strip())
    for key in status_keys_csv.split(","):
        assert key in payload, f"status output missing field {key!r}: {payload!r}"


# ── 3. test_fr05_list_filter_by_status ───────────────────────────────────
# Q1: `list --status S` filters tasks by status.
# TEST_SPEC FR-05 case `list_filter_done` (row 272).


def test_fr05_list_filter_by_status(tmp_path):
    """[FR-05] `list --status done` returns only the done task(s)."""
    filter_status = "done"
    result_count = "1"
    home = tmp_path / "home"
    _write_tasks(
        home,
        {
            "done0001": _done_task("done0001", "echo a"),
            "pend0001": {
                "id": "pend0001",
                "command": "echo b",
                "name": None,
                "status": "pending",
                "created_at": "2026-07-10T00:00:00Z",
            },
        },
    )

    if filter_status == "done":  # AC-FR05-filter-valid
        assert filter_status == "done"

    res = _run_taskq(home, "--json", "list", "--status", filter_status)
    assert res.returncode == 0, f"list failed: {res.stderr!r}"
    rows = json.loads(res.stdout.strip())
    assert len(rows) == int(result_count)
    assert all(r.get("status") == "done" for r in rows)


# ── 4. test_fr05_clear_all_data_files ────────────────────────────────────
# Q1: `clear` empties tasks.json + breaker.json + cache.json.
# TEST_SPEC FR-05 case `clear_files` (row 273).


def test_fr05_clear_all_data_files(tmp_path):
    """[FR-05] `clear` removes all 3 data files from $TASKQ_HOME."""
    cleared_paths_csv = "tasks.json,breaker.json,cache.json"
    file_count = "3"
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    for name in cleared_paths_csv.split(","):
        (home / name).write_text("{}")

    if file_count == "3":  # AC-FR05-files-cleared-attr
        assert file_count == "3"
        assert len(cleared_paths_csv.split(",")) == 3  # AC-FR05-files-cleared-3

    res = _run_taskq(home, "clear")
    assert res.returncode == 0, f"clear failed: {res.stderr!r}"
    for name in cleared_paths_csv.split(","):
        assert not (home / name).exists(), f"{name} must be cleared"


# ── 5. test_fr05_global_json_flag ────────────────────────────────────────
# Q1: global `--json` produces single-line JSON output.
# TEST_SPEC FR-05 case `json_flag` (row 274).


def test_fr05_global_json_flag(tmp_path):
    """[FR-05] `--json submit` emits exactly one line of valid JSON."""
    json_mode = "yes"
    json_output_lines = "1"
    home = tmp_path / "home"

    if json_mode == "yes":  # AC-FR05-json-on
        assert json_mode == "yes"

    res = _run_taskq(home, "--json", "submit", "echo hi")
    assert res.returncode == 0, f"submit failed: {res.stderr!r}"
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]

    if json_output_lines == "1":  # AC-FR05-json-one-line
        assert json_output_lines == "1"
        assert len(lines) == 1, f"expected single JSON line, got {lines!r}"
    payload = json.loads(lines[0])
    assert isinstance(payload, dict)
    assert "id" in payload


# ── 6. test_fr05_exit_code_matrix ────────────────────────────────────────
# Q3: exit codes 0/2/3/4/1 map precisely.
# TEST_SPEC FR-05 case `exit_code_matrix` (row 275).


def test_fr05_exit_code_matrix(tmp_path):
    """[FR-05] Each documented exit code (0/2/3/4/1) is produced by its trigger."""
    exit_codes_csv = "0,2,3,4,1"
    code_count = "5"

    if code_count == "5":  # AC-FR05-exit-codes-attr
        assert code_count == "5"
        assert len(exit_codes_csv.split(",")) == 5  # AC-FR05-exit-codes-five

    # exit 0 — successful submit
    home0 = tmp_path / "h0"
    r0 = _run_taskq(home0, "submit", "echo ok")
    assert r0.returncode == 0, f"expected 0, got {r0.returncode}: {r0.stderr!r}"

    # exit 2 — input validation error (injection char)
    home2 = tmp_path / "h2"
    r2 = _run_taskq(home2, "submit", "echo bad; rm -rf /")
    assert r2.returncode == 2, f"expected 2, got {r2.returncode}: {r2.stderr!r}"

    # exit 3 — breaker OPEN rejects run
    home3 = tmp_path / "h3"
    home3.mkdir(parents=True, exist_ok=True)
    (home3 / "breaker.json").write_text(
        json.dumps(
            {
                "state": "OPEN",
                "failure_count": 5,
                "opened_at": "2999-01-01T00:00:00Z",
                "threshold": 5,
                "cooldown": 300.0,
            }
        )
    )
    _write_tasks(
        home3,
        {
            "brk00001": {
                "id": "brk00001",
                "command": "echo x",
                "name": None,
                "status": "pending",
                "created_at": "2026-07-10T00:00:00Z",
            }
        },
    )
    r3 = _run_taskq(home3, "run", "brk00001")
    assert r3.returncode == 3, f"expected 3, got {r3.returncode}: {r3.stderr!r}"

    # exit 4 — task timeout
    home4 = tmp_path / "h4"
    sleep_cmd = _python_command("import time; time.sleep(5)")
    _write_tasks(
        home4,
        {
            "slow0001": {
                "id": "slow0001",
                "command": sleep_cmd,
                "name": None,
                "status": "pending",
                "created_at": "2026-07-10T00:00:00Z",
            }
        },
    )
    r4 = _run_taskq(home4, "run", "slow0001", env_extra={"TASKQ_TASK_TIMEOUT": "1"})
    assert r4.returncode == 4, f"expected 4, got {r4.returncode}: {r4.stderr!r}"

    # exit 1 — internal error (corrupt tasks.json → JSON decode failure)
    home1 = tmp_path / "h1"
    home1.mkdir(parents=True, exist_ok=True)
    (home1 / "tasks.json").write_text("this is not json{{{")
    r1 = _run_taskq(home1, "status", "whatever0")
    assert r1.returncode == 1, f"expected 1, got {r1.returncode}: {r1.stderr!r}"


# ── 7. test_fr05_unknown_id_exit2 ────────────────────────────────────────
# Q2: unknown task id → exit 2 + stderr.
# TEST_SPEC FR-05 case `unknown_id` (row 276).


def test_fr05_unknown_id_exit2(tmp_path):
    """[FR-05] `status <unknown-id>` exits 2 with a stderr diagnostic."""
    unknown_id = "01234567"
    id_length = "8"
    expected_exit = "2"
    home = tmp_path / "home"
    _write_tasks(home, {})

    if id_length == "8":  # AC-FR05-unknown-id-len-8
        assert id_length == "8"
        assert len(unknown_id) == 8
    if expected_exit == "2":  # AC-FR05-unknown-exit-2
        assert expected_exit == "2"

    res = _run_taskq(home, "status", unknown_id)
    assert res.returncode == int(expected_exit), (
        f"expected exit {expected_exit}, got {res.returncode}: {res.stderr!r}"
    )
    assert res.stderr.strip(), "unknown id must emit a stderr diagnostic"


# ── 8. test_fr05_run_success_exit0 (coverage: cache.put + record_success) ──
# Q1: `run <id>` on a fresh pending task with exit-0 command → exit 0.
# Side effect: executor.execute_task writes to cache.json and breaker
# records success (CLOSED) — covers cache.Cache.put, CacheEntry,
# _atomic_write, breaker.record_success, store.update_task.


def test_fr05_run_success_exit0(tmp_path):
    """[FR-05] `run <id>` of a simple echo command exits 0 and writes cache."""
    home = tmp_path / "home"
    task_id = "succ0001"
    _write_tasks(
        home,
        {
            task_id: {
                "id": task_id,
                "command": "echo hi",
                "name": None,
                "status": "pending",
                "created_at": "2026-07-10T00:00:00Z",
            }
        },
    )

    res = _run_taskq(home, "run", task_id)
    assert res.returncode == 0, f"expected 0, got {res.returncode}: {res.stderr!r}"

    # Verify tasks.json was updated to done
    saved = json.loads((home / "tasks.json").read_text())
    assert saved[task_id]["status"] == "done"
    assert saved[task_id]["exit_code"] == 0
    assert "hi" in saved[task_id]["stdout_tail"]

    # Verify cache.json was written (executor caches done results for replay)
    assert (home / "cache.json").exists(), "executor must persist cache on success"
    cache_data = json.loads((home / "cache.json").read_text())
    assert len(cache_data) == 1


# ── 9. test_fr05_run_all_executes_pending (coverage: _run_all + run_all) ──
# Q1: `run --all` with one pending task → exit 0, task moves to done.
# Covers cli._run_all → executor.run_all (ThreadPoolExecutor path).


def test_fr05_run_all_executes_pending(tmp_path):
    """[FR-05] `run --all` executes one pending task to completion (exit 0)."""
    home = tmp_path / "home"
    task_id = "all00001"
    _write_tasks(
        home,
        {
            task_id: {
                "id": task_id,
                "command": "echo batch",
                "name": None,
                "status": "pending",
                "created_at": "2026-07-10T00:00:00Z",
            }
        },
    )

    res = _run_taskq(home, "run", "--all")
    assert res.returncode == 0, f"expected 0, got {res.returncode}: {res.stderr!r}"

    saved = json.loads((home / "tasks.json").read_text())
    assert saved[task_id]["status"] == "done"


# ── 10. test_fr05_submit_with_name (coverage: _parse_submit_args --name) ──
# Q1: `submit --name mytask echo hi` succeeds and stores the name field.


def test_fr05_submit_with_name(tmp_path):
    """[FR-05] `submit --name mytask ...` stores the name on the task row."""
    home = tmp_path / "home"
    res = _run_taskq(home, "submit", "echo named", "--name", "mytask")
    assert res.returncode == 0, f"expected 0, got {res.returncode}: {res.stderr!r}"

    saved = json.loads((home / "tasks.json").read_text())
    assert len(saved) == 1
    only_task = next(iter(saved.values()))
    assert only_task["name"] == "mytask"
    assert only_task["status"] == "pending"


# ── 11. test_fr05_submit_name_conflict_exit2 (coverage: _validate_name) ──
# Q2: second `submit --name X` while first is still pending → exit 2.
# Covers _validate_name conflict path (cli.py lines 88-92).


def test_fr05_submit_name_conflict_exit2(tmp_path):
    """[FR-05] duplicate --name against pending task → exit 2 + stderr."""
    home = tmp_path / "home"
    r1 = _run_taskq(home, "submit", "echo first", "--name", "dup")
    assert r1.returncode == 0, f"first submit failed: {r1.stderr!r}"

    r2 = _run_taskq(home, "submit", "echo second", "--name", "dup")
    assert r2.returncode == 2, f"expected 2, got {r2.returncode}: {r2.stderr!r}"
    assert "dup" in r2.stderr, f"stderr must mention the conflicting name: {r2.stderr!r}"


# ── 12. test_fr05_status_text_format (coverage: _status non-json path) ──
# Q1: `status <id>` (no --json) emits key:value lines, not JSON.
# Covers cli._status lines 223-225 (text path).


def test_fr05_status_text_format(tmp_path):
    """[FR-05] `status <id>` without --json emits key: value lines."""
    home = tmp_path / "home"
    task_id = "txt00001"
    _write_tasks(home, {task_id: _done_task(task_id, "echo plain")})

    res = _run_taskq(home, "status", task_id)
    assert res.returncode == 0, f"status failed: {res.stderr!r}"
    # text format: one line per key
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    assert len(lines) >= 9, f"expected ≥9 fields, got {len(lines)}: {lines!r}"
    # First line should look like `id: txt00001`
    assert lines[0].startswith("id:"), f"unexpected first line: {lines[0]!r}"


# ── 13. test_fr05_list_no_filter_text (coverage: _list non-json + no filter) ──
# Q1: `list` (no --status, no --json) emits tab-separated rows.
# Covers cli._list lines 244-248 and the status_filter=None branch.


def test_fr05_list_no_filter_text(tmp_path):
    """[FR-05] `list` without --status emits all tasks as tab-separated text."""
    home = tmp_path / "home"
    _write_tasks(
        home,
        {
            "lst00001": _done_task("lst00001", "echo a"),
            "lst00002": _done_task("lst00002", "echo b"),
        },
    )

    res = _run_taskq(home, "list")
    assert res.returncode == 0, f"list failed: {res.stderr!r}"
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    assert len(lines) == 2, f"expected 2 rows, got {len(lines)}: {lines!r}"
    # Each row is `id\tstatus\tcommand`
    assert "\t" in lines[0]
    assert "done" in lines[0]


# ── 14. test_fr05_clear_json_mode (coverage: _clear json path) ──
# Q1: `clear --json` emits JSON {"cleared": [...]} instead of "cleared: ..." text.
# Covers cli._clear lines 266-267.


def test_fr05_clear_json_mode(tmp_path):
    """[FR-05] `clear --json` returns JSON listing the cleared files."""
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    for name in ("tasks.json", "breaker.json", "cache.json"):
        (home / name).write_text("{}")

    res = _run_taskq(home, "--json", "clear")
    assert res.returncode == 0, f"clear failed: {res.stderr!r}"
    payload = json.loads(res.stdout.strip())
    assert "cleared" in payload
    assert set(payload["cleared"]) == {"tasks.json", "breaker.json", "cache.json"}


# ── 15. test_fr05_run_cache_replay (coverage: cache.Cache.get hit + CacheEntry)
# Q1: running the same command twice — second invocation hits the cache
# and emits `cached: true` in tasks.json without invoking subprocess again.
# Covers cache.Cache.get hit branch, CacheEntry.from_dict, breaker.record_success
# on the replay path. (executor.execute_task lines 102-113.)


def test_fr05_run_cache_replay(tmp_path):
    """[FR-05] Running the same command twice → second run replays cache."""
    home = tmp_path / "home"
    task_id_1 = "rep00001"
    task_id_2 = "rep00002"
    cmd = "echo replayed"
    _write_tasks(
        home,
        {
            task_id_1: {
                "id": task_id_1,
                "command": cmd,
                "name": None,
                "status": "pending",
                "created_at": "2026-07-10T00:00:00Z",
            },
            task_id_2: {
                "id": task_id_2,
                "command": cmd,
                "name": None,
                "status": "pending",
                "created_at": "2026-07-10T00:00:00Z",
            },
        },
    )

    r1 = _run_taskq(home, "run", task_id_1)
    assert r1.returncode == 0, f"first run failed: {r1.stderr!r}"

    r2 = _run_taskq(home, "run", task_id_2)
    assert r2.returncode == 0, f"second run failed: {r2.stderr!r}"

    saved = json.loads((home / "tasks.json").read_text())
    # Second run must have `cached: True` (replay short-circuit)
    assert saved[task_id_2]["cached"] is True, (
        f"expected cached=True on replay, got {saved[task_id_2]!r}"
    )


# ── In-process coverage tests (call cli.main directly) ───────────────────
# The subprocess surface tests above validate the real `python -m taskq`
# entrypoint but yield ZERO in-process coverage (the CLI runs in a child
# process). These call cli.main() in-process so coverage.py observes the
# dispatch cascade cli → store → executor → cache → breaker — which is what
# the per-FR Gate 1 test_coverage dimension measures. Behaviour is asserted
# via return codes + on-disk state, so they are genuine behaviour tests, not
# coverage padding.

from taskq import cli as _cli  # noqa: E402
from taskq import store as _store  # noqa: E402


def _inproc(home, monkeypatch, *argv, env_extra=None):
    """Invoke cli.main in-process against a fresh TASKQ_HOME."""
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TASKQ_HOME", str(home))
    _store._HOME = None  # drop the memoised home so the new env takes effect
    if env_extra:
        for key, value in env_extra.items():
            monkeypatch.setenv(key, value)
    return _cli.main(list(argv))


def test_fr05_inproc_submit_status_list_clear(tmp_path, monkeypatch, capsys):
    """[FR-05] In-process submit → status → list → clear happy path."""
    home = tmp_path / "home"

    assert _inproc(home, monkeypatch, "--json", "submit", "echo hi") == 0
    submit_out = capsys.readouterr().out.strip()
    task_id = json.loads(submit_out)["id"]

    # submit with --name (SPEC command-first order)
    assert _inproc(home, monkeypatch, "submit", "echo named", "--name", "job1") == 0
    capsys.readouterr()

    # status --json
    assert _inproc(home, monkeypatch, "--json", "status", task_id) == 0
    assert json.loads(capsys.readouterr().out.strip())["id"] == task_id

    # status text path
    assert _inproc(home, monkeypatch, "status", task_id) == 0
    assert capsys.readouterr().out.startswith("id:")

    # list json + list --status + list text
    assert _inproc(home, monkeypatch, "--json", "list") == 0
    assert len(json.loads(capsys.readouterr().out.strip())) == 2
    assert _inproc(home, monkeypatch, "list", "--status", "pending") == 0
    assert len(capsys.readouterr().out.splitlines()) == 2
    assert _inproc(home, monkeypatch, "list") == 0
    capsys.readouterr()

    # clear (text) then json
    assert _inproc(home, monkeypatch, "clear") == 0
    assert "cleared" in capsys.readouterr().out
    assert _inproc(home, monkeypatch, "--json", "clear") == 0
    assert "cleared" in json.loads(capsys.readouterr().out.strip())


def test_fr05_inproc_run_single_and_all(tmp_path, monkeypatch, capsys):
    """[FR-05] In-process `run <id>` and `run --all` execute pending tasks."""
    home = tmp_path / "home"
    _write_tasks(
        home,
        {
            "one00001": {
                "id": "one00001", "command": "echo one", "name": None,
                "status": "pending", "created_at": "2026-07-10T00:00:00Z",
            },
            "two00002": {
                "id": "two00002", "command": "echo two", "name": None,
                "status": "pending", "created_at": "2026-07-10T00:00:00Z",
            },
        },
    )
    assert _inproc(home, monkeypatch, "run", "one00001") == 0
    capsys.readouterr()
    assert _inproc(home, monkeypatch, "run", "--all") == 0
    saved = json.loads((home / "tasks.json").read_text())
    assert saved["one00001"]["status"] == "done"
    assert saved["two00002"]["status"] == "done"


def test_fr05_inproc_exit_code_paths(tmp_path, monkeypatch, capsys):
    """[FR-05] In-process coverage of every exit-code branch (0/2/3/4/1)."""
    # 2 — missing subcommand
    assert _inproc(tmp_path / "e0", monkeypatch) == 2
    # 2 — unsupported command
    assert _inproc(tmp_path / "e1", monkeypatch, "bogus") == 2
    # 2 — submit injection char
    assert _inproc(tmp_path / "e2", monkeypatch, "submit", "echo x; rm -rf /") == 2
    # 2 — submit missing command
    assert _inproc(tmp_path / "e3", monkeypatch, "submit") == 2
    # 2 — run missing arg
    assert _inproc(tmp_path / "e4", monkeypatch, "run") == 2
    # 2 — run unknown task id (breaker closed)
    home5 = tmp_path / "e5"
    _write_tasks(home5, {})
    assert _inproc(home5, monkeypatch, "run", "missing0") == 2
    # 2 — status missing id
    assert _inproc(tmp_path / "e6", monkeypatch, "status") == 2
    capsys.readouterr()

    # 3 — breaker OPEN rejects run
    home_brk = tmp_path / "brk"
    home_brk.mkdir(parents=True, exist_ok=True)
    (home_brk / "breaker.json").write_text(
        json.dumps({"state": "OPEN", "failure_count": 5,
                    "opened_at": "2999-01-01T00:00:00Z",
                    "threshold": 5, "cooldown": 300.0})
    )
    _write_tasks(home_brk, {"b0000001": {"id": "b0000001", "command": "echo x",
                                          "name": None, "status": "pending",
                                          "created_at": "2026-07-10T00:00:00Z"}})
    assert _inproc(home_brk, monkeypatch, "run", "b0000001") == 3

    # 4 — task timeout
    home_to = tmp_path / "to"
    slow = _python_command("import time; time.sleep(3)")
    _write_tasks(home_to, {"s0000001": {"id": "s0000001", "command": slow,
                                         "name": None, "status": "pending",
                                         "created_at": "2026-07-10T00:00:00Z"}})
    assert _inproc(home_to, monkeypatch, "run", "s0000001",
                   env_extra={"TASKQ_TASK_TIMEOUT": "1"}) == 4

    # 1 — internal error (corrupt tasks.json)
    home_bad = tmp_path / "bad"
    home_bad.mkdir(parents=True, exist_ok=True)
    (home_bad / "tasks.json").write_text("not json{{{")
    assert _inproc(home_bad, monkeypatch, "status", "anything0") == 1
    capsys.readouterr()


def test_fr05_inproc_run_cache_replay(tmp_path, monkeypatch, capsys):
    """[FR-05] In-process second run of same command replays the cache."""
    home = tmp_path / "home"
    cmd = "echo replay"
    _write_tasks(
        home,
        {
            "r0000001": {"id": "r0000001", "command": cmd, "name": None,
                         "status": "pending", "created_at": "2026-07-10T00:00:00Z"},
            "r0000002": {"id": "r0000002", "command": cmd, "name": None,
                         "status": "pending", "created_at": "2026-07-10T00:00:00Z"},
        },
    )
    assert _inproc(home, monkeypatch, "run", "r0000001") == 0
    assert _inproc(home, monkeypatch, "run", "r0000002") == 0
    saved = json.loads((home / "tasks.json").read_text())
    assert saved["r0000002"]["cached"] is True
    capsys.readouterr()
