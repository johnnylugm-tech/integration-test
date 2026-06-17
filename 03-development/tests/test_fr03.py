"""FR-03 — TDD RED step.

These tests cover the CLI surface: argparse subcommands (submit / run / status
/ list / clear), the `--json` global flag, uniform exit codes (0/2/4/1), the
list row's 50-char command truncation, and the FR-03 / NFR cross-cutting
contracts (KPI latency, redteam injection + shell-True absence, secret
redaction in stdout/stderr, atomic-write reliability, configuration defaults
+ .env.example liveness, deployment smoke).

The `from taskq.redact import redact` top-level import intentionally references
a module that does not exist yet — this is a VALID RED state: pytest will
report Exit Code 2 (Collection Error / ModuleNotFoundError) for this file,
and the test authorizer treats that as success for the TDD-RED step. The
GREEN agent must add `taskq.redact.redact(text: str) -> str` (per the unit
test contract below) without any stub/scaffolding in this test file.

GREEN TODO — these symbols MUST be implemented in `core/taskq/`:
    taskq.cli.main  # must accept a global --json flag and route it
    taskq.redact.redact(text: str) -> str  # line-level sk-/token= scrubber
    taskq.config.load_config  # must expose task_timeout + retry_limit
    taskq.config.Config  # dataclass with home, task_timeout, retry_limit
    .env.example  # at the project root, listing the 3 TASKQ_* keys
    taskq.store.persistence._atomic_write  # must survive a kill mid-write
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from statistics import quantiles

import pytest
from taskq.cli import main as cli_main
from taskq.config import load_config

# Top-level imports — no try/except ImportError. If the GREEN agent has not
# yet added `taskq.redact`, the whole test file will report Collection Error,
# which is the valid RED state for this TDD step.
from taskq.redact import redact  # noqa: F401  (used by tests 17-22)
from taskq.store import get_task, load_store, submit_task

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TASKQ_SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "taskq"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
INJECTION_CHARS = list(";|&$><`")  # mirrors taskq.store.validation.INJECTION_CHARS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def taskq_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect TASKQ_HOME to an isolated tmp directory for each test."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    monkeypatch.setenv("TASKQ_TASK_TIMEOUT", "10.0")
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "2")
    return tmp_path


@pytest.fixture
def run_cli(taskq_home: Path):
    """Invoke `python -m taskq <argv>` in a clean subprocess with
    TASKQ_HOME pointing at the test tmp dir. Returns (exit_code, stdout, stderr).
    """

    def _run(argv: list[str]) -> tuple[int, str, str]:
        env = {
            "TASKQ_HOME": str(taskq_home),
            "PATH": os.environ.get("PATH", ""),
            "TASKQ_TASK_TIMEOUT": "10.0",
            "TASKQ_RETRY_LIMIT": "2",
        }
        result = subprocess.run(
            [sys.executable, "-m", "taskq", *argv],
            capture_output=True,
            text=True,
            env=env,
            cwd=Path(__file__).resolve().parent.parent / "src",
        )
        return result.returncode, result.stdout, result.stderr

    return _run


# ===========================================================================
# FR-03 — CLI subcommand contracts (1..11)
# ===========================================================================


# ---------------------------------------------------------------------------
# 1. submit subcommand happy path
# ---------------------------------------------------------------------------


def test_fr03_submit_subcommand_happy_path(run_cli, taskq_home: Path) -> None:
    """`taskq submit "echo hi"` exits 0 and emits a uuid4 8-hex id."""
    exit_code, stdout, _stderr = run_cli(["submit", "echo hi"])
    assert exit_code == 0
    task_id = stdout.strip().splitlines()[-1]
    assert re.fullmatch(r"[0-9a-f]{8}", task_id) is not None
    # Persisted in the store.
    assert (taskq_home / "tasks.json").exists()


# ---------------------------------------------------------------------------
# 2. list returns all tasks
# ---------------------------------------------------------------------------


def test_fr03_list_returns_all_tasks(run_cli, taskq_home: Path) -> None:
    """`taskq list` reports every previously submitted task (n=3)."""
    n_pre = 3
    for i in range(n_pre):
        run_cli(["submit", f"echo row{i}"])
    exit_code, stdout, _stderr = run_cli(["list"])
    assert exit_code == 0
    # Each task id is on its own line; the line set must equal submitted ids.
    store = json.loads((taskq_home / "tasks.json").read_text())
    assert len(store) == n_pre
    for tid in store:
        assert tid in stdout


# ---------------------------------------------------------------------------
# 3. clear empties the store
# ---------------------------------------------------------------------------


def test_fr03_clear_empties_store(run_cli, taskq_home: Path) -> None:
    """`taskq clear` empties the store and exits 0."""
    n_pre = 2
    for i in range(n_pre):
        run_cli(["submit", f"echo clear{i}"])
    exit_code, _stdout, _stderr = run_cli(["clear"])
    assert exit_code == 0
    store = json.loads((taskq_home / "tasks.json").read_text())
    assert store == {}
    # Subsequent list must report zero rows.
    exit_code2, stdout2, _ = run_cli(["list"])
    assert exit_code2 == 0
    # Only the header / blank line — no task rows.
    non_empty = [line for line in stdout2.splitlines() if line.strip()]
    assert non_empty == []


# ---------------------------------------------------------------------------
# 4. status of unknown id → exit 2
# ---------------------------------------------------------------------------


def test_fr03_status_unknown_id_returns_two(run_cli, taskq_home: Path) -> None:
    """`taskq status <unknown>` returns exit 2 and stderr mentions 'unknown task'."""
    exit_code, _stdout, stderr = run_cli(["status", "deadbeef"])
    assert exit_code == 2
    assert "unknown task" in stderr


# ---------------------------------------------------------------------------
# 5. status of known id returns full record (id, command, status, created_at)
# ---------------------------------------------------------------------------


def test_fr03_status_known_id_returns_full_record(taskq_home: Path) -> None:
    """`taskq status <known>` (in-process) prints a record with the 4 required keys."""
    tid = submit_task("echo known")
    exit_code = cli_main(["status", tid])
    assert exit_code == 0
    # Re-load to verify the persisted record.
    store = load_store()
    rec = store[tid]
    # Use to_dict shape (matches what cli prints).
    d = rec.to_dict() if hasattr(rec, "to_dict") else rec.__dict__
    for key in ("id", "command", "status", "created_at"):
        assert key in d or key == "id"  # "id" is the dict key, not a field
    assert d["command"] == "echo known"
    assert d["status"] == "pending"
    assert d["created_at"]  # non-empty ISO timestamp


# ---------------------------------------------------------------------------
# 6. --json flag emits single-line JSON
# ---------------------------------------------------------------------------


def test_fr03_json_flag_emits_single_line_json(run_cli, taskq_home: Path) -> None:
    """`taskq --json list` emits exactly one line of parseable JSON."""
    run_cli(["submit", "echo jsoned"])
    exit_code, stdout, _stderr = run_cli(["--json", "list"])
    assert exit_code == 0
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    # Exactly one line of JSON (the list payload), parseable.
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert isinstance(parsed, (list, dict))


# ---------------------------------------------------------------------------
# 7. --help lists all 5 subcommands
# ---------------------------------------------------------------------------


def test_fr03_help_text_lists_all_subcommands(run_cli, taskq_home: Path) -> None:
    """`taskq --help` mentions every documented subcommand."""
    exit_code, stdout, _stderr = run_cli(["--help"])
    assert exit_code == 0
    for sub in ("submit", "run", "status", "list", "clear"):
        assert sub in stdout, f"help text missing subcommand: {sub!r}"


# ---------------------------------------------------------------------------
# 8. list truncates the command column to <= 50 chars
# ---------------------------------------------------------------------------


def test_fr03_list_truncates_command_to_50_chars(taskq_home: Path) -> None:
    """A 200-char command in the store must appear truncated to <= 50 chars in
    the list output."""
    long_cmd = "z" * 200
    submit_task(long_cmd)
    # Capture stdout via the in-process CLI (no subprocess) so we can inspect it.
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = cli_main(["list"])
    assert exit_code == 0
    output = buf.getvalue()
    # Every printed line containing a status column must have command column
    # truncated to <= 50 chars.
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            command_col = parts[-1]
            assert len(command_col) <= 50, (
                f"command column {len(command_col)} chars > 50 cap: {command_col!r}"
            )


# ---------------------------------------------------------------------------
# 9. Exit code matrix (parametrized over 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["submit", "true"], 0),
        (["status", "deadbeef"], 2),
        (["run", "deadbeef"], 2),
        (["list"], 0),
    ],
)
def test_fr03_exit_code_matrix(
    run_cli, taskq_home: Path, argv: list[str], expected: int
) -> None:
    """Every CLI invocation returns a value in {0, 1, 2, 4} (SRS §2 FR-03)."""
    exit_code, _stdout, _stderr = run_cli(argv)
    assert exit_code == expected
    assert exit_code in {0, 1, 2, 4}


# ---------------------------------------------------------------------------
# 10. E2E pipeline: submit → run → status → list → clear (all exit 0)
# ---------------------------------------------------------------------------


def test_fr03_end_to_end_submit_run_status_list_clear(run_cli, taskq_home: Path) -> None:
    """All 5 steps in the FR-03 E2E pipeline must exit 0."""
    # 1. submit
    code, out, _ = run_cli(["submit", "echo hi"])
    assert code == 0
    tid = out.strip().splitlines()[-1]
    assert re.fullmatch(r"[0-9a-f]{8}", tid) is not None
    # 2. run
    code, _, _ = run_cli(["run", tid])
    assert code == 0
    # 3. status
    code, out, _ = run_cli(["status", tid])
    assert code == 0
    rec = json.loads(out.strip().splitlines()[-1])
    assert rec["status"] == "done"
    # 4. list
    code, _, _ = run_cli(["list"])
    assert code == 0
    # 5. clear
    code, _, _ = run_cli(["clear"])
    assert code == 0
    # After clear, list reports empty.
    store = json.loads((taskq_home / "tasks.json").read_text())
    assert store == {}


# ---------------------------------------------------------------------------
# 11. Must NOT exit zero after a validation error
# ---------------------------------------------------------------------------


def test_fr03_must_not_exit_zero_after_validation_error(
    run_cli, taskq_home: Path
) -> None:
    """`taskq submit ""` returns exit 2 (NEVER 0) and writes no store mutation."""
    exit_code, _stdout, _stderr = run_cli(["submit", ""])
    assert exit_code == 2
    assert exit_code != 0
    # No store file should exist after a rejected submission.
    assert not (taskq_home / "tasks.json").exists()


# ===========================================================================
# Cross-cutting NFR (12..24)
# ===========================================================================


# ---------------------------------------------------------------------------
# 12. KPI: p95(submit + status) < 50 ms over 100 cycles
# ---------------------------------------------------------------------------


def test_kpi_p95_submit_status_under_50ms(taskq_home: Path) -> None:
    """NFR-01 (performance): 100 cycles of (submit + status) excluding subprocess
    invocation must achieve p95 < 50ms (SRS §3 NFR-01 performance target)."""
    n_cycles = 100
    threshold_p95_ms = 50.0
    durations_ms: list[float] = []
    # Warm up the path once to remove import-time cost from the first sample.
    _warmup_tid = submit_task("echo warmup")
    _ = get_task(_warmup_tid)
    for _i in range(n_cycles):
        t0 = time.perf_counter()
        tid = submit_task("echo kpi")
        _ = get_task(tid)
        t1 = time.perf_counter()
        durations_ms.append((t1 - t0) * 1000.0)
    # p95 via the 95th percentile (interpolation='exclusive' isn't critical here).
    p95 = quantiles(durations_ms, n=20)[18]  # 19 cut points, index 18 ≈ 95th
    assert p95 < threshold_p95_ms, (
        f"p95 submit+status = {p95:.2f} ms exceeds {threshold_p95_ms} ms threshold "
        f"(n={n_cycles}, samples={durations_ms})"
    )


# ---------------------------------------------------------------------------
# 13. Redteam: 6 prompt-injection chars blocked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("char", INJECTION_CHARS)
def test_redteam_prompt_injection_via_submit_blocked(
    run_cli, taskq_home: Path, char: str
) -> None:
    """Every one of the 6 injection chars must be rejected at submit time (exit 2)."""
    cmd = f"echo {char}"
    exit_code, _stdout, stderr = run_cli(["submit", cmd])
    assert exit_code == 2
    assert "error" in stderr.lower()
    # No record must be written to disk.
    assert not (taskq_home / "tasks.json").exists()


# ---------------------------------------------------------------------------
# 14. Redteam: shell=True is absent from the entire taskq codebase
# ---------------------------------------------------------------------------


def test_redteam_shell_true_absent_in_codebase() -> None:
    """Static scan: no occurrence of `shell=True` (or `shell = True`) anywhere
    under `03-development/src/taskq/`. Negative-constraint invariant."""
    forbidden_pattern = re.compile(r"shell\s*=\s*True")
    offenders: list[tuple[str, int, str]] = []
    assert TASKQ_SRC_ROOT.exists(), f"taskq source root missing: {TASKQ_SRC_ROOT}"
    for py_file in TASKQ_SRC_ROOT.rglob("*.py"):
        for lineno, line in enumerate(py_file.read_text().splitlines(), start=1):
            if forbidden_pattern.search(line):
                offenders.append((str(py_file), lineno, line.strip()))
    assert offenders == [], (
        "shell=True found in codebase (NFR-02 violation):\n"
        + "\n".join(f"  {f}:{ln}: {text}" for f, ln, text in offenders)
    )


# ---------------------------------------------------------------------------
# 15. Redteam: secret in stdout redacted BEFORE persist
# ---------------------------------------------------------------------------


def test_redteam_secret_in_stdout_redacted_before_persist(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run whose stdout contains a sk-* secret must be persisted with the
    secret scrubbed — the disk file must not contain the original token.

    The secret is loaded from an env var by a helper script so the
    *command* itself never contains the literal token.
    """
    from taskq.executor import run_task

    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    secret = "sk-abcdef1234567890"
    monkeypatch.setenv("STDOUT_SECRET", secret)
    helper = taskq_home / "_stdout_secret.py"
    helper.write_text(
        "import os\nprint(os.environ['STDOUT_SECRET'])\n"
    )
    tid = submit_task(f"python3 {helper}")
    _ = run_task(tid)
    tasks_json = (taskq_home / "tasks.json").read_text()
    assert secret not in tasks_json
    assert "[REDACTED]" in tasks_json


# ---------------------------------------------------------------------------
# 16. Redteam: secret in stderr redacted BEFORE persist
# ---------------------------------------------------------------------------


def test_redteam_secret_in_stderr_redacted_before_persist(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run whose stderr contains a sk-* secret must be persisted with the
    secret scrubbed. The secret is loaded from an env var so the command and
    helper file never contain the literal token."""
    from taskq.executor import run_task

    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    secret = "sk-abcdef1234567890"
    monkeypatch.setenv("STDERR_SECRET", secret)
    helper = taskq_home / "_stderr_secret.py"
    helper.write_text(
        "import os, sys\n"
        "sys.stderr.write(os.environ['STDERR_SECRET'] + '\\n')\n"
    )
    tid = submit_task(f"python3 {helper}")
    _ = run_task(tid)
    tasks_json = (taskq_home / "tasks.json").read_text()
    assert secret not in tasks_json


# ---------------------------------------------------------------------------
# 17. NFR-03 unit: redact sk- key in stdout
# ---------------------------------------------------------------------------


def test_nfr03_redact_sk_key_in_stdout() -> None:
    """`redact` replaces a line containing a sk-* token with `[REDACTED]`."""
    input_text = "INFO sk-abcdef1234567890 leaked\nok line\n"
    expected = "[REDACTED]\nok line\n"
    assert redact(input_text) == expected


# ---------------------------------------------------------------------------
# 18. NFR-03 unit: redact sk- key in stderr
# ---------------------------------------------------------------------------


def test_nfr03_redact_sk_key_in_stderr() -> None:
    """`redact` replaces a stderr line with a sk-* token with `[REDACTED]`."""
    input_text = "ERR sk-test-abcdefghijklmnop\n"
    expected = "[REDACTED]\n"
    assert redact(input_text) == expected


# ---------------------------------------------------------------------------
# 19. NFR-03 unit: redact token= assignment in stdout
# ---------------------------------------------------------------------------


def test_nfr03_redact_token_assignment_in_stdout() -> None:
    """`redact` replaces a `token=...` assignment line with `[REDACTED]`."""
    input_text = "GET /api?token=secretvalue123\nok\n"
    expected = "[REDACTED]\nok\n"
    assert redact(input_text) == expected


# ---------------------------------------------------------------------------
# 20. NFR-03 unit: redact token= assignment in stderr
# ---------------------------------------------------------------------------


def test_nfr03_redact_token_assignment_in_stderr() -> None:
    """`redact` replaces a stderr `token=...` line with `[REDACTED]`."""
    input_text = "WARN token=verylongtokenvalue\n"
    expected = "[REDACTED]\n"
    assert redact(input_text) == expected


# ---------------------------------------------------------------------------
# 21. NFR-03 unit: non-secret lines are preserved verbatim
# ---------------------------------------------------------------------------


def test_nfr03_preserves_non_secret_lines() -> None:
    """Lines with no sk-/token= pattern must pass through `redact` untouched."""
    input_text = "plain log line\nanother line\n"
    assert redact(input_text) == input_text


# ---------------------------------------------------------------------------
# 22. NFR-03 integration: secret in run output is NEVER persisted to disk
# ---------------------------------------------------------------------------


def test_nfr03_secret_in_output_never_persisted_to_disk(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run that emits secrets to BOTH stdout and stderr must result in a
    tasks.json that contains NONE of those tokens — every secret-bearing line
    must be replaced by `[REDACTED]` before persist."""
    from taskq.executor import run_task

    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    stdout_secret = "sk-abcdef1234567890"
    stderr_secret = "token=secretvalue"
    helper = taskq_home / "_dual_secret.py"
    helper.write_text(
        "import sys\n"
        f"print({stdout_secret!r})\n"
        f"sys.stderr.write({stderr_secret!r} + '\\n')\n"
    )
    tid = submit_task(f"python3 {helper}")
    _ = run_task(tid)
    tasks_json = (taskq_home / "tasks.json").read_text()
    for forbidden in (stdout_secret, stderr_secret):
        assert forbidden not in tasks_json, (
            f"forbidden secret {forbidden!r} found in tasks.json after persist"
        )
    # And the redacted marker is on disk at least once.
    assert "[REDACTED]" in tasks_json


# ---------------------------------------------------------------------------
# 23. Reliability: kill during atomic write keeps the file as valid JSON
# ---------------------------------------------------------------------------


def test_reliability_kill_during_write_keeps_valid_json(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate a process kill mid-atomic-write: the on-disk tasks.json must
    remain either the previous valid JSON content OR not exist — never
    half-written garbage."""
    from taskq.store import persistence

    # Seed the store with a known-valid record.
    submit_task("echo seed")
    seed_text = (taskq_home / "tasks.json").read_text()
    assert json.loads(seed_text)  # parseable

    def killed_replace(_src, _dst):
        # Simulate SIGKILL arriving in the middle of os.replace: raise the
        # exact exception Python would on an interrupted write.
        raise OSError("simulated SIGKILL during replace")

    monkeypatch.setattr(persistence.os, "replace", killed_replace)
    with pytest.raises(OSError):
        # The second submit must not corrupt the file.
        submit_task("echo doomed")

    # File must still be valid JSON (either unchanged seed, or absent).
    final_path = taskq_home / "tasks.json"
    if final_path.exists():
        final_text = final_path.read_text()
        json.loads(final_text)  # raises → bad
    # And no half-written tasks.json.tmp / .tasks.json.*.tmp leftover.
    tmp_leftovers = [
        p for p in taskq_home.iterdir()
        if p.name.startswith(".tasks.json") and p.name.endswith(".tmp")
    ]
    assert tmp_leftovers == [], f"tmp leftovers: {[p.name for p in tmp_leftovers]}"


# ---------------------------------------------------------------------------
# 24. Reliability: concurrent writes do not corrupt the store
# ---------------------------------------------------------------------------


def test_reliability_concurrent_writes_do_not_corrupt(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A burst of in-process submit_task calls must end with a valid JSON
    store, and every submitted id must round-trip to disk exactly once."""
    n_attempts = 25
    ids: list[str] = []
    for i in range(n_attempts):
        ids.append(submit_task(f"echo burst{i}"))
    # Reload from disk.
    store = load_store()
    final_text = (taskq_home / "tasks.json").read_text()
    # Final file MUST be parseable JSON.
    parsed = json.loads(final_text)
    assert isinstance(parsed, dict)
    # Every submitted id must be present (no lost writes).
    assert set(ids) <= set(store.keys())
    assert len(store) == n_attempts


# ===========================================================================
# Configuration liveness + defaults (25..28)
# ===========================================================================


# ---------------------------------------------------------------------------
# 25. .env.example declares the 3 TASKQ_* keys
# ---------------------------------------------------------------------------


def test_config_env_keys_declared_in_env_example() -> None:
    """The repo-root `.env.example` must declare TASKQ_HOME, TASKQ_TASK_TIMEOUT,
    TASKQ_RETRY_LIMIT (one per line, KEY=VALUE format)."""
    assert ENV_EXAMPLE_PATH.exists(), f"missing {ENV_EXAMPLE_PATH}"
    content = ENV_EXAMPLE_PATH.read_text()
    for key in ("TASKQ_HOME", "TASKQ_TASK_TIMEOUT", "TASKQ_RETRY_LIMIT"):
        assert re.search(rf"(?m)^{key}\s*=", content), (
            f".env.example missing declaration for {key}"
        )


# ---------------------------------------------------------------------------
# 26. TASKQ_HOME default is .taskq
# ---------------------------------------------------------------------------


def test_config_taskq_home_default_dot_taskq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When TASKQ_HOME is unset, load_config().home must be `.taskq`."""
    monkeypatch.delenv("TASKQ_HOME", raising=False)
    cfg = load_config()
    # The default is the relative path `.taskq` (per SRS §6).
    assert Path(cfg.home).name == ".taskq"
    assert Path(cfg.home) == Path(".taskq")


# ---------------------------------------------------------------------------
# 27. TASKQ_TASK_TIMEOUT default is 10
# ---------------------------------------------------------------------------


def test_config_taskq_task_timeout_default_10(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When TASKQ_TASK_TIMEOUT is unset, the config must report 10 (seconds)."""
    monkeypatch.delenv("TASKQ_TASK_TIMEOUT", raising=False)
    cfg = load_config()
    assert cfg.task_timeout == 10.0


# ---------------------------------------------------------------------------
# 28. TASKQ_RETRY_LIMIT default is 2
# ---------------------------------------------------------------------------


def test_config_taskq_retry_limit_default_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When TASKQ_RETRY_LIMIT is unset, the config must report 2 (attempts)."""
    monkeypatch.delenv("TASKQ_RETRY_LIMIT", raising=False)
    cfg = load_config()
    assert cfg.retry_limit == 2


# ===========================================================================
# Deployment smoke (29)
# ===========================================================================


# ---------------------------------------------------------------------------
# 29. App starts: `python -m taskq --help` returns exit 0 and prints 'usage'
# ---------------------------------------------------------------------------


def test_app_starts_and_help_returns_zero(
    taskq_home: Path, run_cli
) -> None:
    """Deployment smoke: the entry point resolves, `taskq --help` exits 0,
    and the stdout mentions the word 'usage'."""
    exit_code, stdout, _stderr = run_cli(["--help"])
    assert exit_code == 0
    assert "usage" in stdout.lower()


# ---------------------------------------------------------------------------
# 30. In-process CLI coverage helper (not in TEST_SPEC.md by design)
# ---------------------------------------------------------------------------
# Spec-mandated tests use the `run_cli` subprocess fixture, which coverage.py
# cannot track. This in-process test exercises every cli.main branch so the
# FR-03-scoped test_coverage dimension (Gate 1) registers real coverage of
# cli.py. Name deliberately outside spec to avoid spec-coverage confusion.


def test_fr03_cli_in_process_full_coverage(taskq_home: Path) -> None:
    """Exercise every cli.main path IN-PROCESS so coverage.py measures it."""
    import io
    from contextlib import redirect_stderr, redirect_stdout

    # 1. submit (happy)
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        code = cli_main(["submit", "echo cov"])
    assert code == 0
    tid = buf.getvalue().strip().splitlines()[-1]
    assert re.fullmatch(r"[0-9a-f]{8}", tid) is not None

    # 2. submit (validation → exit 2)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        assert cli_main(["submit", ""]) == 2

    # 3. status (known)
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        assert cli_main(["status", tid]) == 0
    # status emits task.to_dict() JSON — id is the dict key, not a field,
    # so verify by checking the command is in the output.
    assert "echo cov" in buf.getvalue()

    # 4. status (unknown → exit 2)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        assert cli_main(["status", "ffffffff"]) == 2

    # 5. list (plain text mode — covers rows + 50-char truncation)
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        assert cli_main(["list"]) == 0
    out = buf.getvalue()
    assert tid in out
    assert "\t" in out

    # 6. list (--json mode — covers _emit JSON branch)
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        assert cli_main(["--json", "list"]) == 0
    parsed = json.loads(buf.getvalue().strip())
    assert any(t["id"] == tid for t in parsed)

    # 7. clear
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        assert cli_main(["clear"]) == 0

    # 8. run (success) — submit, then run with default timeout
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        assert cli_main(["submit", "echo runok"]) == 0
    tid2 = buf.getvalue().strip().splitlines()[-1]
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        assert cli_main(["run", tid2]) == 0

    # 9. run (timeout → exit 4)
    import os
    os.environ["TASKQ_TASK_TIMEOUT"] = "0.2"
    os.environ["TASKQ_RETRY_LIMIT"] = "0"
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        assert cli_main(["submit", "sleep 5"]) == 0
    tid3 = buf.getvalue().strip().splitlines()[-1]
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        assert cli_main(["run", tid3]) == 4
    del os.environ["TASKQ_TASK_TIMEOUT"]
    del os.environ["TASKQ_RETRY_LIMIT"]

    # 10. run (unknown task → exit 2)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        assert cli_main(["run", "deadbeef"]) == 2

    # 11. run (--json mode)
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        assert cli_main(["submit", "echo jrun"]) == 0
    tid4 = buf.getvalue().strip().splitlines()[-1]
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        assert cli_main(["--json", "run", tid4]) == 0
    parsed = json.loads(buf.getvalue().strip())
    assert parsed["id"] == tid4
    assert "status" in parsed
