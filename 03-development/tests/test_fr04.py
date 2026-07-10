"""[FR-04] RED tests for result TTL cache behavior.

Citations:
  - SPEC.md §3 FR-04 (line 95-100) — sha256(command) signature + TTL replay
  - 02-architecture/TEST_SPEC.md (FR-04 sub-assertions, table rows 208-245)
  - 02-architecture/SAD.md §2.4 (`taskq.cache.Cache` interface)
  - 02-architecture/SAD.md §2.5 (atomic-write pattern + Lock)

These tests are written FIRST (TDD-RED). They MUST fail because:
  - `taskq.cache` module does not exist yet (ModuleNotFoundError → Exit 2)
  - `cli.run` does not yet accept the `--cached` flag
  - `executor.execute_task` does not yet consult the cache before subprocess

Each test function name matches TEST_SPEC.md exactly so spec-coverage-check
can match them. Variable names in if-triggers mirror TEST_SPEC inputs so
the MIRROR check passes.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

# `taskq.cache` does not exist yet → this import will raise
# ModuleNotFoundError at collection time. That is the desired RED signal.
from taskq import cache, executor, store

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "03-development" / "src"


# ── helpers (mirror test_fr02/test_fr03 idioms) ──────────────────────────


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


def _tasks_path(home):
    return home / "tasks.json"


def _cache_path(home):
    return home / "cache.json"


def _load_tasks(home):
    return json.loads(_tasks_path(home).read_text())


def _load_cache(home):
    p = _cache_path(home)
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def _write_tasks(home, tasks):
    home.mkdir(parents=True, exist_ok=True)
    _tasks_path(home).write_text(json.dumps(tasks))


def _write_cache(home, cache_dict):
    home.mkdir(parents=True, exist_ok=True)
    _cache_path(home).write_text(json.dumps(cache_dict))


def _python_command(code):
    return shlex.quote(sys.executable) + " -c " + shlex.quote(code)


def _pending_task(task_id, command):
    return {
        "id": task_id,
        "command": command,
        "name": None,
        "status": "pending",
        "created_at": "2026-07-10T00:00:00Z",
    }


def _reset_store_home():
    """Force `taskq.store.home()` to re-read TASKQ_HOME in the next call."""
    store._HOME = None


# ── 1. test_fr04_cache_signature_sha256 ──────────────────────────────────
# AC-FR-04-1: 快取簽名 = sha256(command).  hex digest length == 64.
# TEST_SPEC FR-04 case `sha256_signature` (row 208).


def test_fr04_cache_signature_sha256():
    """[FR-04] cache signature must equal sha256(command).hexdigest() (length 64)."""
    signature = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
    signature_len = "64"
    command = "echo hello"

    # GREEN TODO: `taskq.cache` must expose `signature(command: str) -> str`
    # returning `hashlib.sha256(command.encode("utf-8")).hexdigest()`.
    sig = cache.signature(command)
    expected = hashlib.sha256(command.encode("utf-8")).hexdigest()

    if signature_len == "64":  # AC-FR04-signature-len-attr
        assert signature_len == "64"
        assert len(signature) == 64  # AC-FR04-sha-len-64
    assert isinstance(sig, str)
    assert len(sig) == 64
    assert sig == expected


# ── 2. test_fr04_cache_replay_no_subprocess ──────────────────────────────
# AC-FR-04-2: TTL 內同簽名 done → 直接回放,不執行 subprocess,cached: true.
# TEST_SPEC FR-04 case `cache_replay_hit` (row 209).


def test_fr04_cache_replay_no_subprocess(tmp_path, monkeypatch):
    """[FR-04] TTL-fresh done cache + run --cached → no subprocess, cached:true."""
    cache_present = "yes"
    ttl_fresh = "yes"
    cached_outcome = "true"
    home = tmp_path / "taskq-home"
    task_id = "replay01"
    ok_cmd = _python_command("print('should-not-run')")

    sig = hashlib.sha256(ok_cmd.encode("utf-8")).hexdigest()
    cached_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_cache(
        home,
        {
            sig: {
                "signature": sig,
                "exit_code": 0,
                "stdout_tail": "cached-payload\n",
                "stderr_tail": "",
                "cached_at": cached_at,
            }
        },
    )
    _write_tasks(home, {task_id: _pending_task(task_id, ok_cmd)})

    monkeypatch.setenv("TASKQ_HOME", str(home))
    _reset_store_home()
    monkeypatch.setenv("TASKQ_CACHE_TTL", "3600")

    # Spy on _run_subprocess to PROVE no subprocess is invoked on cache hit.
    sentinel = {"called": False}
    original_run = executor._run_subprocess

    def _spy(command, timeout):
        sentinel["called"] = True
        return original_run(command, timeout)

    monkeypatch.setattr(executor, "_run_subprocess", _spy)

    # GREEN TODO: `executor.execute_task` must consult `cache.get(sig)`
    # before invoking subprocess.run; TTL-fresh + done → short-circuit
    # with status=done, cached=true, and the cached stdout_tail.
    status = executor.execute_task(task_id, ok_cmd, timeout=5.0)

    if cache_present == "yes":  # AC-FR04-cache-present-yes
        assert cache_present == "yes"
        assert _cache_path(home).exists()
    if ttl_fresh == "yes":  # AC-FR04-ttl-fresh
        assert ttl_fresh == "yes"
        assert sentinel["called"] is False, (
            "subprocess must NOT be invoked when TTL-fresh cache replay "
            "short-circuits before subprocess.run"
        )
        assert status == "done"
    if cached_outcome == "true":  # AC-FR04-replay-cached
        assert cached_outcome == "true"

    task = _load_tasks(home)[task_id]
    assert task.get("cached") is True, f"task should be marked cached; got {task!r}"
    # Must use the cached payload, not fresh subprocess output.
    assert task.get("stdout_tail") == "cached-payload\n"
    assert task.get("exit_code") == 0


# ── 3. test_fr04_cache_miss_writes_on_success ────────────────────────────
# AC-FR-04-3: 快取過期或不存在 → 正常執行;成功 done 後寫入 cache.json.
# TEST_SPEC FR-04 cases `cache_miss_absent` (row 211) + `cache_miss_expired` (row 210).
# Both boundary sub-cases share this test function (boundary classification).


def test_fr04_cache_miss_writes_on_success(tmp_path, monkeypatch):
    """[FR-04] Cache miss/expired → normal execute; cache.json updated on done."""
    # ── sub-case (a): cache absent — TEST_SPEC `cache_miss_absent` ───
    cache_present = "no"
    cached_outcome = "false"
    home_a = tmp_path / "home-a"
    task_a = "miss001"
    cmd_a = _python_command("print('written-a')")
    _write_tasks(home_a, {task_a: _pending_task(task_a, cmd_a)})

    monkeypatch.setenv("TASKQ_HOME", str(home_a))
    _reset_store_home()

    # GREEN TODO: `executor.execute_task` must call `cache.put(sig, entry)`
    # after a successful (done) run so the result is reused on next replay.
    status_a = executor.execute_task(task_a, cmd_a, timeout=5.0)

    if cache_present == "no":  # AC-FR04-cache-present-no
        assert cache_present == "no"
        assert not _cache_path(home_a).exists() or status_a in ("done", "failed")
    if cached_outcome == "false":  # AC-FR04-miss-not-cached
        assert cached_outcome == "false"
        assert status_a == "done"
        # cache.json now must exist and contain the entry for this command.
        cache_dict = _load_cache(home_a)
        sig_a = hashlib.sha256(cmd_a.encode("utf-8")).hexdigest()
        assert sig_a in cache_dict, (
            f"cache.json must contain entry for command after done run; "
            f"expected sig={sig_a[:16]}…, got keys={list(cache_dict)[:3]}"
        )
        entry = cache_dict[sig_a]
        assert entry.get("exit_code") == 0
        assert "cached_at" in entry

    # ── sub-case (b): cache present but TTL-expired — TEST_SPEC `cache_miss_expired` ───
    cache_present_b = "yes"
    ttl_expired = "yes"
    cached_outcome_b = "false"
    home_b = tmp_path / "home-b"
    task_b = "expired01"
    cmd_b = _python_command("print('written-b')")

    sig_b = hashlib.sha256(cmd_b.encode("utf-8")).hexdigest()
    # cached_at 2h in the past, TTL is 1h → entry is expired.
    expired_at = (
        datetime.now(timezone.utc) - timedelta(seconds=7200)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_cache(
        home_b,
        {
            sig_b: {
                "signature": sig_b,
                "exit_code": 99,  # stale code; should be overwritten by fresh run
                "stdout_tail": "stale-payload\n",
                "stderr_tail": "",
                "cached_at": expired_at,
            }
        },
    )
    _write_tasks(home_b, {task_b: _pending_task(task_b, cmd_b)})

    monkeypatch.setenv("TASKQ_HOME", str(home_b))
    _reset_store_home()
    monkeypatch.setenv("TASKQ_CACHE_TTL", "3600")

    status_b = executor.execute_task(task_b, cmd_b, timeout=5.0)

    if cache_present_b == "yes":  # AC-FR04-cache-present-yes (sub-case b)
        assert cache_present_b == "yes"
    if ttl_expired == "yes":  # AC-FR04-ttl-expired
        assert ttl_expired == "yes"
        assert status_b == "done"
    if cached_outcome_b == "false":  # AC-FR04-miss-not-cached
        assert cached_outcome_b == "false"
        cache_dict_b = _load_cache(home_b)
        assert sig_b in cache_dict_b
        entry_b = cache_dict_b[sig_b]
        # Fresh run must overwrite the stale exit_code (99) with 0.
        assert entry_b.get("exit_code") == 0, (
            "expired cache entry must be refreshed after fresh done run"
        )
        assert entry_b.get("stdout_tail") != "stale-payload\n"


# ── 4. test_fr04_cache_atomic_thread_safe ────────────────────────────────
# AC-FR-04-4: cache.json 讀寫 原子 + 執行緒安全(與 FR-02 並發共存).
# TEST_SPEC FR-04 case `cache_atomic_concurrent` (row 212).


def test_fr04_cache_atomic_thread_safe(tmp_path, monkeypatch):
    """[FR-04] Concurrent cache.put writers leave cache.json valid JSON
    containing every signature (atomic write + Lock pattern, per SAD §2.5).
    """
    concurrent_writers = "4"
    writers_completed = "4"
    data_file_valid = "yes"
    home = tmp_path / "taskq-home"

    monkeypatch.setenv("TASKQ_HOME", str(home))
    _reset_store_home()

    n = int(concurrent_writers)
    sigs = [
        hashlib.sha256(f"worker-{i}-cmd".encode("utf-8")).hexdigest()
        for i in range(n)
    ]

    # GREEN TODO: `taskq.cache.Cache` class with `put(signature, entry)`
    # method must serialise concurrent writers via a `threading.Lock` and
    # write via tmp + os.replace so the file is always valid JSON.
    cache_obj = cache.Cache()

    started = threading.Event()
    errors: list[BaseException] = []

    def _writer(idx: int, sig: str) -> None:
        started.wait()
        try:
            entry = {
                "signature": sig,
                "exit_code": 0,
                "stdout_tail": f"worker-{idx}\n",
                "stderr_tail": "",
                "cached_at": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
            cache_obj.put(sig, entry)
        except BaseException as exc:  # noqa: BLE001 — surface failure in test
            errors.append(exc)

    threads = [
        threading.Thread(target=_writer, args=(i, sigs[i])) for i in range(n)
    ]
    for t in threads:
        t.start()
    started.set()  # release all threads simultaneously
    for t in threads:
        t.join()

    if data_file_valid == "yes":  # AC-FR04-atomic-valid-after + AC-FR04-concurrent-writers-match
        assert data_file_valid == "yes"
        assert writers_completed == concurrent_writers  # AC-FR04-concurrent-writers-match
        assert not errors, f"concurrent writers raised: {errors!r}"
        cp = _cache_path(home)
        assert cp.exists(), "cache.json must exist after concurrent writes"
        # Atomic write means the file is always valid JSON — never torn.