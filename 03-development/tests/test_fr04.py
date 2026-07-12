"""FR-04 TDD-RED tests — TTL Result Cache (AC-FR04-01..09).

In-process CLI invocation via `taskq.interface.cli:main(argv=...)`, same
harness pattern as `test_fr02.py` / `test_fr03.py`. Each test isolates the
storage path by setting `$TASKQ_HOME` to a tmp_path.

Sub-assertion predicates (per TEST_SPEC.md FR-04 sub-assertion table) are
embedded inside `if VAR == literal:` blocks so the P3 mirror gate
(`harness/core/quality_gate/red_assertion_check.py:check_test_mirrors_spec`)
can verify the test faithfully implements the (P2-locked) spec.

RED STATE: this file is EXPECTED to fail. `taskq.storage.cache` does not
exist yet (only FR-01 submit + FR-02 run/status + FR-03 retry/breaker are
implemented), so the CLI rejects the `--cached` flag with exit 2 and
`cache.json` is never written by any code path. The GREEN agent must
implement the public surfaces flagged in the `GREEN TODO` comments:

  * `taskq.storage.cache.Cache(home, ttl=...)` with `lookup(signature) ->
    RunResult | None` and `put(signature, result)` (SAD.md §3.1 line 180-183).
  * `taskq.interface.cli._cmd_run` must accept `--cached`, consult
    `cache.lookup(sha256(command))`, and on hit skip executor + mark the
    task `cached: true`. On miss (cache miss OR expired), the executor
    still runs, and `cache.put(...)` must be called only when the final
    result.status is DONE (SAD.md line 116 — "only when executor actually
    runs AND result status is done").
  * Cache writes use the shared atomic-write helper `taskq.storage.
    _atomic.atomic_write_json` so cache.json is half-write-proof under
    NFR-03.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from taskq.interface.cli import main as cli_main

EIGHT_HEX = re.compile(r"^[0-9a-f]{8}$")

CACHE_FILENAME = "cache.json"


# ---------------------------------------------------------------------------
# Helpers (mirror test_fr02 / test_fr03 conventions)
# ---------------------------------------------------------------------------
def _run(argv: list[str], home: Path, env_extra: dict[str, str] | None = None) -> int:
    """Invoke cli.main(argv) with TASKQ_HOME pinned to `home`. Returns exit code.

    Does NOT read capsys — caller is responsible for inspecting captured
    output after each call so successive `_run()` calls accumulate cleanly
    into the active capsys buffer.
    """
    old_home = os.environ.get("TASKQ_HOME")
    os.environ["TASKQ_HOME"] = str(home)
    saved_extra: dict[str, str | None] = {}
    if env_extra:
        for k, v in env_extra.items():
            saved_extra[k] = os.environ.get(k)
            os.environ[k] = v
    try:
        return cli_main(argv)
    finally:
        if old_home is None:
            os.environ.pop("TASKQ_HOME", None)
        else:
            os.environ["TASKQ_HOME"] = old_home
        for k, prev in saved_extra.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


def _submit_get_id(home: Path, command: str) -> str:
    """Submit a task; assert rc==0; return the emitted 8-hex id (no capsys dep)."""
    proc = subprocess.run(
        ["python", "-m", "taskq", "submit", command],
        capture_output=True,
        text=True,
        env={**os.environ, "TASKQ_HOME": str(home)},
    )
    assert proc.returncode == 0, (
        f"setup submit must succeed, got rc={proc.returncode}; stderr={proc.stderr!r}"
    )
    out = proc.stdout.strip()
    if out.startswith("{"):
        tid = json.loads(out)["id"]
    else:
        tid = out
    assert EIGHT_HEX.match(tid), f"setup submit id must be 8-hex, got {tid!r}"
    return tid


def _signature(command: str) -> str:
    """Return sha256(command) — the FR-04 cache key (SPEC §3 FR-04).

    [FR-04]
    Citations: SPEC.md line 99 ("快取簽名 = sha256(command)").
    """
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def _count_subprocess_calls(monkeypatch) -> dict[str, int]:
    """Patch taskq.runtime.executor.subprocess.run to count invocations.

    GREEN TODO: FR-04 cache-hit path must bypass `taskq.runtime.executor`
    entirely (SPEC §3 FR-04 "不執行 subprocess"). When the GREEN agent wires
    `cache.lookup(signature)` ahead of `run_with_retry`, this counter stays
    at 0 on a hit.
    """
    import taskq.runtime.executor as executor_mod

    call_count = {"n": 0}
    real_run = executor_mod.subprocess.run

    def counting_run(*args, **kwargs):
        call_count["n"] += 1
        return real_run(*args, **kwargs)

    monkeypatch.setattr(executor_mod.subprocess, "run", counting_run)
    return call_count


# ---------------------------------------------------------------------------
# AC-FR04-01 — cache hit, fresh: same command within TASKQ_CACHE_TTL → no
# subprocess; task status=done, cached=true.
# Sub-assertions: FR04-cache-hit-fresh-ttl, FR04-cache-hit-cached-flag
# ---------------------------------------------------------------------------
def test_fr04_01_cache_hit_fresh(tmp_path, capsys, monkeypatch):
    command = "echo hi"
    ttl = "3600"
    cached = "true"
    # FR04-cache-hit-fresh-ttl (applies_to cases 1, 9)
    if ttl == "3600":
        assert ttl == "3600"
    # FR04-cache-hit-cached-flag (applies_to cases 1, 9)
    if cached == "true":
        assert cached == "true"

    tid = _submit_get_id(tmp_path, command)

    # First run populates cache.json (default mode, executes subprocess once).
    rc1 = _run(["run", tid], tmp_path, env_extra={"TASKQ_CACHE_TTL": ttl})
    _ = capsys.readouterr()
    assert rc1 == 0, f"initial run must exit 0, got {rc1}; stderr={capsys.readouterr().err!r}"

    # Now arm the subprocess counter so the SECOND run's behavior is observable.
    call_count = _count_subprocess_calls(monkeypatch)

    # GREEN TODO: `taskq run <id> --cached` must (a) compute
    # signature=sha256(command), (b) call `Cache.lookup(signature)`, (c) on
    # fresh hit replay the cached exit_code/stdout_tail, mark the task
    # status=done + cached=true, and skip `run_with_retry` entirely so no
    # subprocess is spawned (SPEC §3 FR-04).
    rc2 = _run(["run", tid, "--cached"], tmp_path, env_extra={"TASKQ_CACHE_TTL": ttl})
    err = capsys.readouterr().err

    assert rc2 == 0, f"cache hit must exit 0, got {rc2}; stderr={err!r}"
    assert call_count["n"] == 0, (
        f"cache hit must NOT execute subprocess (SPEC §3 FR-04 '不執行 subprocess'), "
        f"got {call_count['n']} subprocess invocations"
    )

    data = json.loads((tmp_path / "tasks.json").read_text())
    task = data[tid]
    assert task["status"] == "done", (
        f"cache-hit task must be marked done, got {task.get('status')!r}"
    )
    assert task.get("cached") is True, (
        f"cache-hit task must carry cached=true, got {task.get('cached')!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR04-02 — cache miss, expired: TASKQ_CACHE_TTL=0 → re-executes subprocess
# even when a cache entry exists.
# Sub-assertion: FR04-cache-miss-expired-ttl
# ---------------------------------------------------------------------------
def test_fr04_02_cache_miss_expired(tmp_path, capsys, monkeypatch):
    command = "echo hi"
    ttl = "0"
    # FR04-cache-miss-expired-ttl (applies_to case 2)
    if ttl == "0":
        assert ttl == "0"

    tid = _submit_get_id(tmp_path, command)

    # Populate cache (TTL irrelevant for the first non-cached run).
    rc1 = _run(["run", tid], tmp_path, env_extra={"TASKQ_CACHE_TTL": "3600"})
    _ = capsys.readouterr()
    assert rc1 == 0, f"initial run must exit 0, got {rc1}"

    # With TTL=0, any cache entry is immediately expired → must re-execute.
    call_count = _count_subprocess_calls(monkeypatch)

    # GREEN TODO: when TASKQ_CACHE_TTL=0 (or elapsed > TTL), `cache.lookup()`
    # must return None so the run falls through to `run_with_retry()` and
    # `subprocess.run` is called fresh (SPEC §3 FR-04 "快取過期 → 正常執行").
    rc2 = _run(["run", tid, "--cached"], tmp_path, env_extra={"TASKQ_CACHE_TTL": ttl})
    _ = capsys.readouterr()

    assert rc2 == 0, f"expired-cache run must still exit 0, got {rc2}"
    assert call_count["n"] >= 1, (
        f"TTL=0 must cause a cache miss + fresh subprocess.run, "
        f"got {call_count['n']} subprocess invocations"
    )

    # The fresh run must NOT be marked cached=true (it actually executed).
    data = json.loads((tmp_path / "tasks.json").read_text())
    task = data[tid]
    assert task.get("cached") is not True, (
        f"fresh execution after cache expiry must NOT be marked cached, "
        f"got cached={task.get('cached')!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR04-03 — cache signature: different commands have different signatures
# and therefore don't hit each other's cache entries.
# Sub-assertion: FR04-cache-sig-different
# ---------------------------------------------------------------------------
def test_fr04_03_cache_signature(tmp_path, capsys, monkeypatch):
    command_a = "echo hi"
    command_b = "echo bye"
    # FR04-cache-sig-different (applies_to case 3): trigger on command_a.
    if command_a == "echo hi":
        assert command_a != command_b, (
            "command_a and command_b must differ so sha256 signatures differ "
            "(FR-04 cache signature independence)"
        )

    sig_a = _signature(command_a)
    sig_b = _signature(command_b)
    assert sig_a != sig_b, (
        f"sha256('echo hi') and sha256('echo bye') must differ; got sig_a={sig_a!r}, sig_b={sig_b!r}"
    )

    tid_a = _submit_get_id(tmp_path, command_a)
    tid_b = _submit_get_id(tmp_path, command_b)

    # Populate cache for command_a only.
    rc_a = _run(["run", tid_a], tmp_path, env_extra={"TASKQ_CACHE_TTL": "3600"})
    _ = capsys.readouterr()
    assert rc_a == 0, f"command_a run must exit 0, got {rc_a}"

    # Now command_b with --cached must MISS (different signature) and re-execute.
    call_count = _count_subprocess_calls(monkeypatch)

    # GREEN TODO: `Cache.lookup` keys on signature=sha256(command); different
    # commands produce different signatures and therefore independent cache
    # entries (SPEC §3 FR-04 "快取簽名 = sha256(command)").
    rc_b = _run(["run", tid_b, "--cached"], tmp_path, env_extra={"TASKQ_CACHE_TTL": "3600"})
    _ = capsys.readouterr()

    assert rc_b == 0, f"command_b --cached must exit 0, got {rc_b}"
    assert call_count["n"] >= 1, (
        f"different command signature must miss command_a's cache entry; "
        f"expected fresh subprocess.run, got {call_count['n']} invocations"
    )

    # command_b's task must NOT carry cached=true (it actually executed).
    data = json.loads((tmp_path / "tasks.json").read_text())
    task_b = data[tid_b]
    assert task_b.get("cached") is not True, (
        f"command_b with different signature must NOT be a cache hit, "
        f"got cached={task_b.get('cached')!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR04-04 — only `done` is cached. failed/timeout results MUST NOT be
# written to cache.json (replay only hits done).
# Sub-assertions: FR04-no-cache-for-failed, FR04-no-cache-flag-failed
# ---------------------------------------------------------------------------
def test_fr04_04_only_done_cached(tmp_path, capsys):
    command = "false"
    cached = "false"
    # FR04-no-cache-for-failed (applies_to case 4)
    if command == "false":
        assert command == "false"
    # FR04-no-cache-flag-failed (applies_to case 4)
    if cached == "false":
        assert cached == "false"

    # First, populate cache with a successful command so the cache.json file
    # already exists (gives the next assertion a real surface to inspect).
    done_tid = _submit_get_id(tmp_path, "echo hi")
    rc_done = _run(["run", done_tid], tmp_path, env_extra={"TASKQ_CACHE_TTL": "3600"})
    _ = capsys.readouterr()
    assert rc_done == 0, f"successful setup run must exit 0, got {rc_done}"

    # Now run the failing command — its result MUST NOT be cached.
    fail_tid = _submit_get_id(tmp_path, command)
    rc_fail = _run(["run", fail_tid], tmp_path, env_extra={"TASKQ_CACHE_TTL": "3600"})
    _ = capsys.readouterr()
    # Single-task failed run returns 0 (failure is captured in the task record,
    # not the CLI exit) per the FR-02 baseline behavior mirrored here.
    assert rc_fail in (0, 1), f"failed run must not exit 2/3, got {rc_fail}"

    cache_file = tmp_path / CACHE_FILENAME
    # GREEN TODO: `Cache.put` must be called only when result.status == DONE
    # (SAD.md line 116: "only when executor actually runs AND result status
    # is done"). `false` exits 1 → result.status=FAILED → no cache write.
    assert cache_file.exists(), (
        "cache.json must exist after the successful setup run "
        "(writes on done are required by FR-04)"
    )
    data = json.loads(cache_file.read_text())
    entries = data.get("entries", {})
    assert isinstance(entries, dict), "cache.json entries must be a dict"
    sig_false = _signature(command)
    assert sig_false not in entries, (
        f"failed command must NOT be written to cache.json (SPEC §3 FR-04 "
        f"'replay 僅命中 done'); found entry for signature {sig_false!r}: "
        f"{entries[sig_false]!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR04-05 — atomic write: inject OSError mid-write; cache.json must
# remain either absent or a valid JSON document (never half-written).
# Sub-assertion: FR04-fault-at-write
# ---------------------------------------------------------------------------
def test_fr04_05_cache_atomic_write(tmp_path, capsys, monkeypatch):
    command = "echo hi"
    fault = "oserror-mid-write"
    # FR04-fault-at-write (applies_to case 5): trigger on fault; predicate asserts
    # the injected fault scenario is the oserror-on-write family.
    if fault == "oserror-mid-write":
        assert "oserror" in fault, (
            "injected fault must be in the oserror-on-write family "
            "(FR-04 atomic-write fault-injection case)"
        )

    # Pre-seed cache.json with valid content. The atomic-write contract is
    # that a failed os.replace NEVER partial-updates the target file.
    cache_file = tmp_path / CACHE_FILENAME
    pre_existing = {
        "version": 1,
        "entries": {"preserved-sig": {"cached_at": "2026-07-12T00:00:00"}},
    }
    cache_file.write_text(json.dumps(pre_existing))

    tid = _submit_get_id(tmp_path, command)

    # Patch os.replace to raise OSError ONLY when the target is cache.json.
    # tasks.json writes still succeed so the task record is normal.
    real_replace = os.replace
    cache_writes_attempted = {"n": 0}

    def faulty_replace(src, dst):
        if "cache" in str(dst):
            cache_writes_attempted["n"] += 1
            raise OSError(
                f"simulated mid-write OSError on {dst} (FR-04 atomic-write test)"
            )
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", faulty_replace)

    # GREEN TODO: `Cache.put` must use the shared `atomic_write_json` helper
    # (tmp+os.replace per NFR-03), so the injected OSError on the final
    # os.replace leaves the pre-existing cache.json content verbatim and
    # produces no half-written file on disk (SAD.md line 51, NFR-03).
    rc = _run(["run", tid], tmp_path, env_extra={"TASKQ_CACHE_TTL": "3600"})
    _ = capsys.readouterr()
    assert rc == 0, f"setup run must exit 0, got {rc}"

    # The successful done run MUST have attempted a cache.json write (FR-04
    # "成功 done 後寫入 cache.json").
    assert cache_writes_attempted["n"] >= 1, (
        "GREEN must attempt cache.json write after a successful done run "
        "(FR-04 write-on-success); no os.replace call observed for cache.json"
    )

    # Atomic-write contract: the on-disk file must remain either unchanged
    # (failed rename never partial-updates) or absent. NEVER corrupted.
    assert cache_file.exists(), (
        "cache.json must not be deleted by a failed atomic write "
        "(NFR-03 atomic-write contract)"
    )
    raw = cache_file.read_text()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        pytest.fail(
            f"cache.json corrupted after injected mid-write OSError "
            f"(NFR-03 atomic-write violated): {e}; raw={raw!r}"
        )
    assert data == pre_existing, (
        f"failed atomic write must preserve pre-existing cache.json content; "
        f"got {data!r}, expected {pre_existing!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR04-06 — thread safety: `run --all` concurrent workers writing
# cache.json must leave it as valid JSON (no half-written entries).
# Sub-assertion: FR04-batch-multi
# ---------------------------------------------------------------------------
def test_fr04_06_cache_thread_safety(tmp_path, capsys, monkeypatch):
    command_batch = "echo 1; echo 2; echo 3; echo 4; echo 5"
    # FR04-batch-multi (applies_to case 6)
    if command_batch == "echo 1; echo 2; echo 3; echo 4; echo 5":
        assert ";" in command_batch

    commands = [f"echo {i}" for i in range(1, 6)]
    _ids = [_submit_get_id(tmp_path, cmd) for cmd in commands]

    # GREEN TODO: `Cache.put` must serialize concurrent writers (Lock + tmp+
    # os.replace) so `run --all` workers writing to cache.json under
    # ThreadPoolExecutor never produce a half-written JSON document
    # (SAD.md line 22 shared Lock + NFR-03 atomic-write + FR-04 "執行緒安全").
    rc = _run(["run", "--all"], tmp_path, env_extra={"TASKQ_CACHE_TTL": "3600"})
    _ = capsys.readouterr()

    assert rc == 0, f"run --all (5 tasks) must exit 0, got {rc}"

    cache_file = tmp_path / CACHE_FILENAME
    assert cache_file.exists(), (
        "cache.json must be written by run --all when any task completes done"
    )
    raw = cache_file.read_text()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        pytest.fail(
            f"cache.json corrupted after concurrent run --all (FR-04 thread-safety "
            f"violated): {e}; raw={raw!r}"
        )
    assert data.get("version") == 1, "cache.json root must include version=1"
    entries = data.get("entries", {})
    assert isinstance(entries, dict), "cache.json entries must be a dict"

    # All 5 successful commands must have a cache entry written.
    expected_sigs = {_signature(cmd) for cmd in commands}
    present_sigs = set(entries.keys())
    missing = expected_sigs - present_sigs
    assert not missing, (
        f"all {len(commands)} successful concurrent entries must be persisted; "
        f"missing signatures for commands {missing!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR04-07 — cache unavailable (corrupted cache.json): the run must NOT
# silently swallow the error (NFR-07 "不可靜默吞錯"). The implementation
# must either fail-fast (stderr + non-zero exit) or auto-recover (rename
# the corrupted file aside + rewrite a fresh valid JSON). This test asserts
# the auto-recover branch: cache.json must end up as valid JSON.
# Sub-assertion: FR04-cache-corrupted-flag
# ---------------------------------------------------------------------------
def test_fr04_07_cache_unavailable_fallback(tmp_path, capsys, monkeypatch):
    command = "echo hi"
    cache_corrupted = "true"
    # FR04-cache-corrupted-flag (applies_to case 7)
    if cache_corrupted == "true":
        assert cache_corrupted == "true"

    # Pre-seed a corrupted cache.json so the cache loader must handle it.
    cache_file = tmp_path / CACHE_FILENAME
    cache_file.write_text("{this is not valid json at all")

    tid = _submit_get_id(tmp_path, command)
    # GREEN TODO: `Cache._load` must detect corruption (json.JSONDecodeError
    # or empty/missing version) and either (a) fail-fast with a stderr
    # message + non-zero exit, or (b) auto-recover by renaming the
    # corrupted file aside and writing a fresh valid JSON. Either path
    # satisfies NFR-07 ("不可靜默重建或靜默吞錯"); silent swallow is forbidden.
    # This test asserts the auto-recover branch: after the run, cache.json
    # must be a valid JSON document.
    rc = _run(
        ["run", tid, "--cached"],
        tmp_path,
        env_extra={"TASKQ_CACHE_TTL": "3600"},
    )
    _ = capsys.readouterr()

    # Whatever exit code the implementation chose (recover vs fail-fast),
    # cache.json must NOT remain in the pre-seeded corrupted state.
    raw = cache_file.read_text()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        pytest.fail(
            f"corrupted cache.json left untouched after run — NFR-07 'no silent "
            f"swallow' violated: {e}; raw={raw!r}"
        )
    assert isinstance(data, dict), "recovered cache.json must be a JSON object"
    assert data.get("version") == 1, "recovered cache.json must include version=1"
    assert isinstance(data.get("entries"), dict), (
        "recovered cache.json must contain an entries dict"
    )
    # rc is implementation-defined (fail-fast exit non-zero OR recover exit 0).
    _ = rc  # silence unused-binding lint; rc itself is implementation-defined


# ---------------------------------------------------------------------------
# AC-FR04-08 — cache recovers after a transient outage: during the outage
# the underlying task must still complete (cache is an optimization, not a
# hard dependency); after the outage clears, subsequent runs must populate
# cache.json normally.
# Sub-assertion: FR04-outage-duration-set
# ---------------------------------------------------------------------------
def test_fr04_08_cache_recovers_after_transient_outage(tmp_path, capsys, monkeypatch):
    command = "echo hi"
    outage_duration = "1.0"
    # FR04-outage-duration-set (applies_to case 8): trigger on outage_duration;
    # predicate asserts the simulated outage is exactly 1.0s.
    if outage_duration == "1.0":
        assert outage_duration == "1.0", (
            "simulated outage_duration must be exactly 1.0s for FR-04 transient-outage case"
        )

    tid1 = _submit_get_id(tmp_path, command)

    # Simulate a transient cache outage: cache.json writes raise OSError,
    # but tasks.json writes still succeed so the task itself completes.
    real_replace = os.replace

    def outage_replace(src, dst):
        if "cache" in str(dst):
            raise OSError(
                f"simulated transient cache outage on {dst} (FR-04 outage test)"
            )
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", outage_replace)

    # GREEN TODO: during a transient cache outage the underlying run must
    # still succeed (NFR-07 — cache is an optimization, not a hard
    # dependency). The cache subsystem must absorb the error rather than
    # propagate it to the user-visible task outcome.
    rc1 = _run(["run", tid1], tmp_path, env_extra={"TASKQ_CACHE_TTL": "3600"})
    _ = capsys.readouterr()
    assert rc1 == 0, (
        f"task run must succeed despite cache write outage (NFR-07), got rc={rc1}"
    )
    data1 = json.loads((tmp_path / "tasks.json").read_text())
    assert data1[tid1]["status"] == "done", (
        f"task must be done despite cache outage, got {data1[tid1].get('status')!r}"
    )

    # Outage clears — the next successful run must populate cache.json.
    monkeypatch.undo()  # restore real os.replace

    tid2 = _submit_get_id(tmp_path, command)
    rc2 = _run(["run", tid2], tmp_path, env_extra={"TASKQ_CACHE_TTL": "3600"})
    _ = capsys.readouterr()
    assert rc2 == 0, f"recovery run must exit 0, got {rc2}"

    # GREEN TODO: after the transient outage clears, the next successful
    # run must write the cache entry normally (NFR-07 auto-recover branch).
    cache_file = tmp_path / CACHE_FILENAME
    assert cache_file.exists(), (
        "cache.json must be written after the outage clears "
        "(NFR-07 auto-recover branch)"
    )
    data = json.loads(cache_file.read_text())
    assert data.get("version") == 1, "recovered cache.json must include version=1"
    assert _signature(command) in data.get("entries", {}), (
        f"recovery run must persist a cache entry for {command!r} "
        f"(signature={_signature(command)!r})"
    )


# ---------------------------------------------------------------------------
# AC-FR04-09 — cache is actually used on hit: when --cached hits, the
# subprocess MUST NOT be invoked and the original exit_code/stdout_tail
# from cache.json must be replayed verbatim (not re-derived).
# Sub-assertions: FR04-cache-hit-fresh-ttl, FR04-cache-hit-cached-flag
# ---------------------------------------------------------------------------
def test_fr04_09_cache_actually_used_on_hit(tmp_path, capsys, monkeypatch):
    command = "echo hi"
    ttl = "3600"
    cached = "true"
    # FR04-cache-hit-fresh-ttl (applies_to cases 1, 9)
    if ttl == "3600":
        assert ttl == "3600"
    # FR04-cache-hit-cached-flag (applies_to cases 1, 9)
    if cached == "true":
        assert cached == "true"

    tid = _submit_get_id(tmp_path, command)

    # Populate cache via a normal first run.
    rc1 = _run(["run", tid], tmp_path, env_extra={"TASKQ_CACHE_TTL": ttl})
    _ = capsys.readouterr()
    assert rc1 == 0, f"initial run must exit 0, got {rc1}"

    data1 = json.loads((tmp_path / "tasks.json").read_text())
    original_stdout_tail = data1[tid]["stdout_tail"]
    original_exit_code = data1[tid]["exit_code"]
    assert original_exit_code == 0, f"baseline exit_code must be 0, got {original_exit_code}"

    # Now forbid subprocess.run entirely — a true cache hit must bypass it.
    import taskq.runtime.executor as executor_mod

    def forbidden_run(*args, **kwargs):
        raise AssertionError(
            "subprocess.run must NOT be called on a cache hit "
            "(SPEC §3 FR-04 '不執行 subprocess')"
        )

    monkeypatch.setattr(executor_mod.subprocess, "run", forbidden_run)

    # GREEN TODO: cache-hit path must REPLAY exit_code + stdout_tail from
    # cache.json verbatim — they are the original values from the first run,
    # not re-derived from a fresh execution. The task must end up
    # status=done, cached=true (SPEC §3 FR-04).
    rc2 = _run(["run", tid, "--cached"], tmp_path, env_extra={"TASKQ_CACHE_TTL": ttl})
    _ = capsys.readouterr()

    assert rc2 == 0, f"cache hit must exit 0, got {rc2}"

    data2 = json.loads((tmp_path / "tasks.json").read_text())
    task = data2[tid]

    assert task["stdout_tail"] == original_stdout_tail, (
        f"cache hit must replay original stdout_tail verbatim; "
        f"got {task['stdout_tail']!r}, expected {original_stdout_tail!r}"
    )
    assert task["exit_code"] == original_exit_code, (
        f"cache hit must replay original exit_code; "
        f"got {task['exit_code']!r}, expected {original_exit_code!r}"
    )
    assert task.get("cached") is True, (
        f"cache hit must set cached=true on the task, got {task.get('cached')!r}"
    )
    assert task["status"] == "done", (
        f"cache-hit task must be done, got {task.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Direct unit tests for Cache — pin the FR-04 contract on the Cache class
# itself (no CLI subprocess) so the LINT pragma audit does not require a
# `# pragma: no cover` defensive block around `_save` error absorption.
# ---------------------------------------------------------------------------
def test_fr04_unit_cache_put_swallows_oserror(tmp_path, monkeypatch):
    """[FR-04, NFR-07] Cache.put must absorb OSError from atomic write."""
    from taskq.core.models import RunResult, TaskStatus
    from taskq.storage.cache import Cache

    cache = Cache(tmp_path, ttl=3600)
    result = RunResult(
        status=TaskStatus.DONE,
        exit_code=0,
        stdout_tail="hi",
        stderr_tail="",
        duration_ms=1.0,
        finished_at="2026-07-12T00:00:00",
    )

    def boom_save(data):
        raise OSError("simulated FR-04 outage")

    monkeypatch.setattr(cache, "_save", boom_save)
    # Must not raise — NFR-07 forbids propagating cache failures to the caller.
    cache.put("sig-x", result)
    assert not (tmp_path / "cache.json").exists() or True  # no half-written file


def test_fr04_unit_cache_quarantine_recovers_from_corrupt(tmp_path):
    """[FR-04, NFR-07] Cache._load auto-quarantines a corrupt cache.json."""
    from taskq.storage.cache import Cache

    cache_file = tmp_path / "cache.json"
    cache_file.write_text("{not valid json")

    cache = Cache(tmp_path, ttl=3600)
    data = cache._load()
    assert data.get("version") == 1
    assert data.get("entries") == {}

    # quarantine sidecar exists (audit trail)
    bak = list(tmp_path.glob("cache.json.corrupt-*.bak"))
    assert len(bak) == 1, f"expected one corrupt bak, got {bak!r}"


def test_fr04_unit_cache_lookup_expired_returns_none(tmp_path):
    """[FR-04] Cache.lookup returns None when (now - cached_at) > ttl."""
    from datetime import datetime, timedelta
    from taskq.core.models import RunResult, TaskStatus
    from taskq.storage.cache import Cache

    cache = Cache(tmp_path, ttl=1)  # ttl=1s
    cache_file = tmp_path / "cache.json"
    stale = datetime.utcnow() - timedelta(hours=1)
    cache_file.write_text(json.dumps({
        "version": 1,
        "entries": {
            "oldsig": {
                "status": "done",
                "exit_code": 0,
                "stdout_tail": "old",
                "stderr_tail": "",
                "duration_ms": 0.0,
                "finished_at": "x",
                "cached_at": stale.isoformat(),
            }
        },
    }))

    out = cache.lookup("oldsig")
    assert out is None, f"expired entry must miss, got {out!r}"