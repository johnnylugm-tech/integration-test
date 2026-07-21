"""TDD-RED tests for FR-04: 結果 TTL 快取 (`taskq run <id> --cached`).

Covers the 6 canonical test functions declared in
``02-architecture/TEST_SPEC.md`` §FR-04 (cache hit / miss / signature /
only-done / atomic-write / thread-safety):

* AC-FR04-01 — TTL-fresh ``--cached`` replay: NO subprocess; ``status=done``;
  ``cached: true``.
* AC-FR04-02 — TTL-expired ``--cached`` re-executes subprocess; ``cache.json``
  is updated.
* AC-FR04-03 — different ``command`` signatures (sha256) do not cross-hit.
* AC-FR04-04 — ``failed`` / ``timeout`` results are NOT written to
  ``cache.json``; replay only hits ``done`` entries.
* AC-FR04-05 — mid-write ``OSError`` leaves ``cache.json`` as valid JSON.
* AC-FR04-06 — concurrent ``run --all`` leaves ``cache.json`` as valid JSON.

Pattern mirrors ``test_fr02.py`` / ``test_fr03.py``:

* **In-process** — calls ``taskq.cli.main([...])`` directly inside the pytest
  process. Drives pytest-cov coverage of ``cli.py`` / ``__main__.py``
  (GATE1 requires >= 80% coverage under ``03-development/src/taskq``, which
  subprocess calls can NEVER provide).
* **Subprocess** — spawns ``python -m taskq <args>`` with a function-scoped
  ``$TASKQ_HOME`` and an explicit ``PYTHONPATH`` (pytest's ``pythonpath``
  config does NOT propagate to child interpreters per v2.13.0 rule 3).

RED-state contract: source code is NOT yet implemented. The top-level
``from taskq import cache`` import is INTENTIONAL and UNGUARDED — pytest is
expected to crash with ``ModuleNotFoundError`` (Exit Code 2 = Collection
Error) until the GREEN phase lands ``cache.py`` and adds the ``--cached``
flag to ``cli.run_command``. That is a valid RED outcome per v2.13.0.

Forbidden patterns (per v2.13.0 test-author rules):

* No try/except ImportError anywhere.
* No source-file edits.
* No lazy imports.
* Local-variable names must not shadow stdlib modules (``json``, ``os``,
  ``sys``, ``time``, ``subprocess``, ``pathlib``, ``asyncio``, ``typing``,
  ``logging``, ``path``, ``file``, ``id``, ``type``, ``dict``, ``list``,
  ``set``, ``tuple``, ``str``, ``int``, ``bool``, ``bytes``). The alias
  ``json_lib`` is used in place of a bare ``json`` local.
"""

from __future__ import annotations

import hashlib
import json as json_lib
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Top-level imports are INTENTIONAL — RED expects Collection Error if any
# of ``taskq.cache`` / ``taskq.cli`` / ``taskq.executor`` is missing OR has
# not yet grown the cache + --cached machinery. Do not wrap in try/except.
from taskq import cli  # noqa: F401  (used in the in-process calls below)
from taskq import cache as _cache_mod  # GREEN TODO: provide Cache class + lookup()/store() helpers
from taskq import executor as _executor_mod  # GREEN TODO: subprocess.run path used by counter

# Silence unused-import lint: the tests below DO touch both helpers; this
# is here ONLY so static linters don't flag the top-level imports during
# the RED window.
_ = (_cache_mod, _executor_mod)


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------

# Path to the in-tree source so subprocess children can import ``taskq``
# even though it is not installed. pytest's ``pythonpath = 03-development/src``
# only injects the parent interpreter; child interpreters via
# ``subprocess.run([sys.executable, "-m", "taskq"])`` do NOT inherit it.
_SRC_ROOT = Path(__file__).resolve().parent.parent / "src"


def _make_env(taskq_home: Path, **overrides: str) -> dict[str, str]:
    """Build a child-process env with ``TASKQ_HOME`` + ``PYTHONPATH``.

    Both vars are REQUIRED for child invocations:

    * ``TASKQ_HOME`` isolates each test's ``tasks.json`` + ``cache.json`` to
      its own ``tmp_path`` (v2.13.0 rule 2: ``state_mode:
      isolate_per_test``).
    * ``PYTHONPATH`` lets the spawned interpreter find ``taskq`` on the
      import path (v2.13.0 rule 3: pytest ``pythonpath`` config does NOT
      propagate to children).

    Extra overrides (``TASKQ_CACHE_TTL``, ...) are merged in by the caller;
    this lets each test pin its config knobs without mutating the host
    environment.
    """
    env = os.environ.copy()
    env["TASKQ_HOME"] = str(taskq_home)
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_SRC_ROOT) + os.pathsep + existing_pp
    for key, value in overrides.items():
        env[key] = value
    return env


def _run_subprocess(
    args: list[str],
    taskq_home: Path,
    **env_overrides: str,
) -> subprocess.CompletedProcess:
    """Run ``python -m taskq <args>`` with the isolated env and return the
    completed ``subprocess.CompletedProcess`` (text mode, stdout/stderr
    captured)."""
    return subprocess.run(
        [sys.executable, "-m", "taskq", *args],
        capture_output=True,
        text=True,
        env=_make_env(taskq_home, **env_overrides),
    )


@pytest.fixture
def taskq_home(tmp_path: Path) -> Path:
    """Function-scoped ``$TASKQ_HOME`` directory.

    Per v2.13.0 rule 2 (``state_mode: isolate_per_test`` on every FR-04 row),
    each test gets a FRESH directory so the seeded ``cache.json`` from the
    fresh-hit case (case 1) cannot leak into the expired case (case 2) or
    the atomic-write case (case 5).
    """
    home = tmp_path / "taskq_home"
    home.mkdir()
    return home


def _seed_pending(taskq_home: Path, task_id: str, command: str) -> Path:
    """Write a single pending task to ``$TASKQ_HOME/tasks.json`` and return
    the path to the file. Mirrors the schema that FR-01's ``submit`` writes
    so the GREEN ``run`` implementation sees the same on-disk shape it would
    in production."""
    tasks_file = taskq_home / "tasks.json"
    record = {
        "command": command,
        "name": "",
        "status": "pending",
        "created_at": "2026-07-18T00:00:00+00:00",
    }
    tasks_file.write_text(json_lib.dumps({task_id: record}))
    return tasks_file


def _load_tasks(tasks_file: Path) -> dict[str, dict]:
    """Read ``tasks.json`` and return the parsed mapping."""
    return json_lib.loads(tasks_file.read_text())


def _cache_signature(command: str) -> str:
    """Return ``sha256(command).hexdigest()`` — the canonical cache key.

    Mirrors the SPEC §3 FR-04 contract ``快取簽名 = sha256(command)``.
    """
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def _iso_now() -> str:
    """Return current UTC time as ISO-8601 (matches the regex used in
    earlier FR test files)."""
    return datetime.now(timezone.utc).isoformat()


def _seed_cache(
    taskq_home: Path,
    entries: dict[str, dict],
) -> Path:
    """Write ``$TASKQ_HOME/cache.json`` with the supplied entry mapping and
    return the file path. Mirrors the SPEC §5.2 schema
    ``{version: 1, entries: {signature -> done result + cached_at}}``.

    Each entry MUST at minimum carry ``exit_code``, ``stdout_tail``, and
    ``cached_at`` (ISO-8601 string). The caller is responsible for picking
    a ``cached_at`` timestamp that puts the entry either inside or outside
    ``TASKQ_CACHE_TTL``.
    """
    cache_file = taskq_home / "cache.json"
    payload = {"version": 1, "entries": dict(entries)}
    cache_file.write_text(json_lib.dumps(payload, indent=2, sort_keys=True))
    return cache_file


def _load_cache(taskq_home: Path) -> dict:
    """Read ``$TASKQ_HOME/cache.json`` and return the parsed mapping.

    Returns ``{}`` if the file is missing (the GREEN initial state on a
    fresh ``$TASKQ_HOME`` is no cache file).
    """
    cp = taskq_home / "cache.json"
    if not cp.exists():
        return {}
    return json_lib.loads(cp.read_text())


class _CountingSubprocess:
    """Injectable ``subprocess.run`` proxy that counts invocations and then
    delegates to the real ``subprocess.run``.

    The GREEN executor MUST call ``subprocess.run`` (the FR-02 happy path
    contract); we monkeypatch the attribute on the executor module so the
    counter intercepts every invocation regardless of where in the
    call stack it originates. This is the AC-FR04-01 "monkeypatch
    subprocess.run 計次驗證" mechanism declared in TEST_SPEC.md.
    """

    def __init__(self) -> None:
        self.calls: int = 0

    def __call__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        return subprocess.run(*args, **kwargs)


# ---------------------------------------------------------------------------
# AC-FR04-01 — cache hit (fresh): --cached replay, no subprocess, cached:true
# ---------------------------------------------------------------------------


def test_fr04_01_cache_hit_fresh(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """happy_path / Q1.

    AC: a pending task with ``command="echo hi"`` exists AND the cache
    ``sha256("echo hi")`` is pre-seeded with a ``cached_at`` timestamp
    inside ``TASKQ_CACHE_TTL`` seconds. ``run <id> --cached`` MUST (a)
    exit 0, (b) NOT call ``subprocess.run``, (c) record ``status="done"``,
    (d) record ``cached: true``.

    Rule IDs: ``FR04-ttl-fresh-hit``
    (``ttl_env == "3600" and cached_flag == "true"``).

    Coupled NFR: NFR-08 (cross-process state — replay reads cache.json
    atomically under a lock).

    The ``TASKQ_CACHE_TTL=3600`` default is pinned via ``monkeypatch.setenv``
    so the test is deterministic independent of any future GREEN default
    change.

    GREEN TODO
    ---------
    ``cli.run_command`` must accept ``--cached`` (action="store_true") and
    delegate to ``cache.lookup(signature)`` before invoking the executor.
    On hit (entry present + ``now - cached_at <= cache_ttl``) the executor
    MUST be bypassed entirely and the replay result merged into the
    pending record with ``cached: true``.
    """
    command = "echo hi"
    task_id = "abcdef01"
    ttl_env = "3600"
    cached_flag = "true"
    assert ttl_env == "3600" and cached_flag == "true"  # spec predicate

    # Pre-seed cache.json with a fresh entry (cached_at = now) for the
    # signature of this command. TTL=3600 s ⇒ guaranteed fresh.
    sig = _cache_signature(command)
    cache_file = _seed_cache(
        taskq_home,
        {
            sig: {
                "exit_code": 0,
                "stdout_tail": "hi\n",
                "cached_at": _iso_now(),
            }
        },
    )
    tasks_file = _seed_pending(taskq_home, task_id, command)

    monkeypatch.setenv("TASKQ_CACHE_TTL", ttl_env)

    # Count subprocess.run invocations via a proxy installed on the
    # executor module (where the GREEN code calls it).
    counter = _CountingSubprocess()
    monkeypatch.setattr(
        "taskq.executor.subprocess.run", counter, raising=False
    )

    # ---- In-process path (drives coverage of cli.py / __main__.py).
    rc_in = cli.main(["run", task_id, "--cached"])
    assert rc_in == 0, (
        f"in-process run --cached (cache hit) must exit 0, got {rc_in}"
    )
    assert counter.calls == 0, (
        f"cache HIT must NOT invoke subprocess.run; got {counter.calls} call(s)"
    )
    parsed_in = _load_tasks(tasks_file)
    record_in = parsed_in[task_id]
    assert record_in["status"] == "done", (
        f"cache HIT replay must persist status='done', "
        f"got {record_in['status']!r}"
    )
    assert record_in.get("cached") is True, (
        f"cache HIT replay must persist cached=true, "
        f"got {record_in.get('cached')!r}"
    )
    assert record_in.get("exit_code") == 0, (
        f"cache HIT replay must surface exit_code=0 from the cached entry, "
        f"got {record_in.get('exit_code')!r}"
    )
    # cache.json should NOT be re-written on a hit (entry already exists).
    # Verify the file is still valid JSON (no half-write).
    assert cache_file.exists(), "cache.json must persist from the pre-seed"
    _load_cache(taskq_home)  # raises if cache.json is invalid

    # ---- Subprocess path (AC verification against real entry point).
    cache_file.write_text(
        json_lib.dumps(
            {
                "version": 1,
                "entries": {
                    sig: {
                        "exit_code": 0,
                        "stdout_tail": "hi\n",
                        "cached_at": _iso_now(),
                    }
                },
            }
        )
    )
    _seed_pending(taskq_home, task_id, command)

    proc = _run_subprocess(
        ["run", task_id, "--cached"],
        taskq_home,
        TASKQ_CACHE_TTL=ttl_env,
    )
    assert proc.returncode == 0, proc.stderr
    parsed_proc = _load_tasks(tasks_file)
    record_proc = parsed_proc[task_id]
    assert record_proc["status"] == "done"
    assert record_proc.get("cached") is True


# ---------------------------------------------------------------------------
# AC-FR04-02 — cache miss (expired): --cached re-executes, cache.json updated
# ---------------------------------------------------------------------------


def test_fr04_02_cache_miss_expired(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """boundary / Q3.

    AC: ``TASKQ_CACHE_TTL=1`` AND ``cache.json`` has a ``sha256("echo hi")``
    entry whose ``cached_at`` is ``elapsed_secs=5`` seconds in the past
    (TTL window = 1 s, so the entry IS expired). ``run <id> --cached``
    MUST (a) treat the cache as MISS, (b) execute the subprocess, (c) on
    success overwrite ``cache.json`` with a fresh entry (same signature,
    newer ``cached_at``).

    Rule IDs: ``FR04-ttl-expired``
    (``ttl_env == "1" and int(elapsed_secs) > int(ttl_env)``).

    Coupled NFR: NFR-03 (atomic write of ``cache.json`` after the fresh
    execution completes).

    GREEN TODO
    ---------
    ``cache.lookup(signature)`` must compare
    ``time.time() - cached_at`` against ``TASKQ_CACHE_TTL`` and return
    ``None`` when the entry is expired. ``cli.run_command`` must treat
    ``None`` as MISS even when ``--cached`` is passed.
    """
    command = "echo hi"
    task_id = "abcdef02"
    ttl_env = "1"
    elapsed_secs = "5"
    cached_flag = "true"
    assert (
        ttl_env == "1" and int(elapsed_secs) > int(ttl_env)
    )  # spec predicate
    assert cached_flag == "true"

    sig = _cache_signature(command)
    # cached_at = now - elapsed_secs, well beyond TTL=1 s.
    expired_cached_at = (
        datetime.fromtimestamp(time.time() - int(elapsed_secs), tz=timezone.utc)
        .isoformat()
    )
    _seed_cache(
        taskq_home,
        {
            sig: {
                "exit_code": 0,
                "stdout_tail": "stale\n",
                "cached_at": expired_cached_at,
            }
        },
    )
    tasks_file = _seed_pending(taskq_home, task_id, command)

    monkeypatch.setenv("TASKQ_CACHE_TTL", ttl_env)

    counter = _CountingSubprocess()
    monkeypatch.setattr(
        "taskq.executor.subprocess.run", counter, raising=False
    )

    # ---- In-process path.
    rc_in = cli.main(["run", task_id, "--cached"])
    assert rc_in == 0, (
        f"in-process run --cached (cache miss, expired) must exit 0, "
        f"got {rc_in}"
    )
    assert counter.calls >= 1, (
        f"cache MISS (expired) MUST re-execute subprocess; "
        f"got {counter.calls} call(s)"
    )
    parsed_in = _load_tasks(tasks_file)
    record_in = parsed_in[task_id]
    assert record_in["status"] == "done", (
        f"after cache-miss re-exec, status must be 'done', "
        f"got {record_in['status']!r}"
    )
    # On a fresh execution (NOT a cache hit) the ``cached`` flag must NOT
    # be set — the task genuinely ran.
    assert record_in.get("cached") is not True, (
        f"cache MISS replay must NOT set cached=true; "
        "the task genuinely executed. "
        f"got {record_in.get('cached')!r}"
    )

    # cache.json must still be valid JSON (NFR-03 invariant — fresh write
    # MUST go through the tmp + os.replace pattern).
    cache_data = _load_cache(taskq_home)
    assert sig in cache_data.get("entries", {}), (
        f"after a successful cache-miss re-execution, cache.json must "
        f"contain a fresh entry for signature {sig!r}; "
        f"got entries={list(cache_data.get('entries', {}).keys())!r}"
    )

    # ---- Subprocess path.
    _seed_cache(
        taskq_home,
        {
            sig: {
                "exit_code": 0,
                "stdout_tail": "stale\n",
                "cached_at": expired_cached_at,
            }
        },
    )
    _seed_pending(taskq_home, task_id, command)
    proc = _run_subprocess(
        ["run", task_id, "--cached"],
        taskq_home,
        TASKQ_CACHE_TTL=ttl_env,
    )
    assert proc.returncode == 0, proc.stderr
    parsed_proc = _load_tasks(tasks_file)
    record_proc = parsed_proc[task_id]
    assert record_proc["status"] == "done"
    assert record_proc.get("cached") is not True


# ---------------------------------------------------------------------------
# AC-FR04-03 — cache signature: different commands do NOT cross-hit
# ---------------------------------------------------------------------------


def test_fr04_03_cache_signature(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """happy_path / Q1.

    AC: ``cache.json`` is pre-seeded with a fresh entry ONLY for
    ``sha256("echo hi")``. ``run <id_b> --cached`` for a DIFFERENT command
    ``"echo hi2"`` MUST NOT hit the cache — the signature
    ``sha256("echo hi2")`` differs from ``sha256("echo hi")``, so the
    subprocess IS executed and the record's ``cached`` flag is NOT set.
    Conversely, ``run <id_a> --cached`` for the original ``"echo hi"``
    MUST hit (no subprocess).

    Rule IDs: ``FR04-different-signatures``
    (``command_a == "echo hi" and command_b == "echo hi2"``).

    GREEN TODO
    ---------
    ``cache.lookup(signature)`` MUST key by the SHA-256 of the literal
    command string — NOT by task id, NOT by command prefix, NOT by any
    other collation key. ``executor.run_task`` MUST compute the signature
    from the on-disk ``record["command"]`` field.
    """
    command_a = "echo hi"
    command_b = "echo hi2"
    cached_flag = "true"
    assert (
        command_a == "echo hi" and command_b == "echo hi2"
    )  # spec predicate
    assert cached_flag == "true"

    sig_a = _cache_signature(command_a)
    sig_b = _cache_signature(command_b)
    assert sig_a != sig_b, (
        f"distinct commands must produce distinct SHA-256 signatures; "
        f"both collapsed to {sig_a!r}"
    )

    # Pre-seed cache.json with ONLY sig_a's entry (fresh).
    _seed_cache(
        taskq_home,
        {
            sig_a: {
                "exit_code": 0,
                "stdout_tail": "hi\n",
                "cached_at": _iso_now(),
            }
        },
    )

    # Seed two pending tasks (different ids, different commands).
    tasks_file = taskq_home / "tasks.json"
    tasks_file.write_text(
        json_lib.dumps(
            {
                "aaaaaa01": {
                    "command": command_a,
                    "name": "",
                    "status": "pending",
                    "created_at": "2026-07-18T00:00:00+00:00",
                },
                "bbbbbb01": {
                    "command": command_b,
                    "name": "",
                    "status": "pending",
                    "created_at": "2026-07-18T00:00:01+00:00",
                },
            }
        )
    )

    monkeypatch.setenv("TASKQ_CACHE_TTL", "3600")
    counter = _CountingSubprocess()
    monkeypatch.setattr(
        "taskq.executor.subprocess.run", counter, raising=False
    )

    # ---- First: command_b (signature NOT in cache) → MUST miss.
    rc_b = cli.main(["run", "bbbbbb01", "--cached"])
    assert rc_b == 0, (
        f"in-process run --cached on command_b (cache miss) must exit 0, "
        f"got {rc_b}"
    )
    assert counter.calls >= 1, (
        f"command_b's signature {sig_b!r} must NOT hit cache; "
        f"expected >= 1 subprocess call, got {counter.calls}"
    )
    parsed = _load_tasks(tasks_file)
    record_b = parsed["bbbbbb01"]
    assert record_b["status"] == "done"
    assert record_b.get("cached") is not True, (
        f"cache MISS must NOT set cached=true on command_b's record; "
        f"got {record_b.get('cached')!r}"
    )

    # ---- Then: command_a (signature IS in cache) → MUST hit, no subprocess.
    counter.calls = 0
    rc_a = cli.main(["run", "aaaaaa01", "--cached"])
    assert rc_a == 0, (
        f"in-process run --cached on command_a (cache hit) must exit 0, "
        f"got {rc_a}"
    )
    assert counter.calls == 0, (
        f"command_a's signature {sig_a!r} MUST hit the cache; "
        f"expected 0 subprocess calls, got {counter.calls}"
    )
    parsed = _load_tasks(tasks_file)
    record_a = parsed["aaaaaa01"]
    assert record_a["status"] == "done"
    assert record_a.get("cached") is True, (
        f"cache HIT must set cached=true on command_a's record; "
        f"got {record_a.get('cached')!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR04-04 — only ``done`` results are cached; failed/timeout replay MISS
# ---------------------------------------------------------------------------


def test_fr04_04_only_done_cached(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """validation / Q2.

    AC: a pending task with ``command="false"`` is run normally (without
    ``--cached``). It transitions to ``status="failed"``. ``cache.json``
    MUST NOT contain any entry for ``sha256("false")`` — the FR-04 cache
    contract writes ONLY ``done`` results. A subsequent
    ``run <id> --cached`` MUST treat the absence as a MISS and re-execute
    the subprocess (still ``failed``).

    Rule IDs: ``FR04-failed-not-cached`` (``outcome == "failed"``).

    GREEN TODO
    ---------
    The GREEN executor MUST call ``cache.store(signature, result)`` ONLY
    when ``result["status"] == "done"``. The cache write MUST be skipped
    for ``"failed"`` and ``"timeout"`` terminal states — otherwise a
    stale "failed" entry would block any retry from re-running.
    """
    command = "false"
    task_id = "abcdef04"
    outcome = "failed"
    cached_flag = "true"
    assert outcome == "failed"  # spec predicate
    assert cached_flag == "true"

    sig = _cache_signature(command)

    # Disable retries so the run deterministically final-fails after a
    # single attempt — keeps the test fast and predictable.
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0")

    tasks_file = _seed_pending(taskq_home, task_id, command)

    # ---- Phase 1: normal run (no --cached) → status=failed.
    rc_in = cli.main(["run", task_id])
    assert rc_in == 0, (
        f"in-process run of 'false' (non-timeout failure) must exit 0, "
        f"got {rc_in}"
    )
    parsed = _load_tasks(tasks_file)
    record = parsed[task_id]
    assert record["status"] == "failed", (
        f"after run of 'false', status must be 'failed', "
        f"got {record['status']!r}"
    )

    # ---- Phase 2: cache.json MUST NOT contain an entry for sig("false").
    # Either the file is missing (GREEN wrote nothing) or it exists with
    # an entries dict that does NOT include sig. Either is valid.
    cache_file = taskq_home / "cache.json"
    if cache_file.exists():
        cache_data = _load_cache(taskq_home)
        entries = cache_data.get("entries", {})
        assert sig not in entries, (
            f"failed tasks must NOT be cached; found signature {sig!r} "
            f"in cache entries {sorted(entries.keys())!r}"
        )

    # ---- Phase 3: re-run with --cached → MUST miss + re-execute.
    counter = _CountingSubprocess()
    monkeypatch.setattr(
        "taskq.executor.subprocess.run", counter, raising=False
    )
    _seed_pending(taskq_home, task_id, command)

    rc_cached = cli.main(["run", task_id, "--cached"])
    assert rc_cached == 0, (
        f"in-process run --cached (failed task) must exit 0, "
        f"got {rc_cached}"
    )
    assert counter.calls >= 1, (
        f"failed task MUST NOT be replayed from cache; expected >= 1 "
        f"subprocess call, got {counter.calls}"
    )
    parsed = _load_tasks(tasks_file)
    record_cached = parsed[task_id]
    assert record_cached["status"] == "failed", (
        f"after --cached re-execution of 'false', status must remain "
        f"'failed', got {record_cached['status']!r}"
    )
    assert record_cached.get("cached") is not True, (
        f"failed re-execution must NOT set cached=true; "
        f"got {record_cached.get('cached')!r}"
    )


# ---------------------------------------------------------------------------
# AC-FR04-05 — atomic write: mid-write OSError leaves cache.json valid JSON
# ---------------------------------------------------------------------------


def test_fr04_05_cache_atomic_write(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """integration / Q7.

    AC: a pending task with ``command="echo hi"`` runs while ``os.replace``
    is monkeypatched to raise ``OSError`` whenever the destination path
    ends with ``cache.json``. The simulation mimics a mid-write crash on
    the cache write. After the run completes (the GREEN flow absorbs the
    OSError and surfaces a normal task outcome), ``cache.json`` MUST be
    valid JSON — either the pre-seeded content is preserved OR the GREEN
    tmp-file orphan is cleaned up and no half-written entry is left
    behind. Either way the file MUST parse as JSON (NFR-03 invariant).

    Rule IDs: ``FR04-atomic-mid-write`` (``mid_write_error == "oserror"``).

    The test pre-seeds ``cache.json`` with a sentinel entry so we can
    distinguish "preserved atomic write" (sentinel intact) from "file
    missing / corrupt" (test fails).

    GREEN TODO
    ---------
    The GREEN ``cache.Cache.store`` (or equivalent) MUST write via the
    same tmp + ``os.replace`` primitive as ``cli._atomic_write_json``:
    dump to ``cache.json.tmp``, then ``os.replace(cache.json.tmp,
    cache.json)``. On ``OSError`` from ``os.replace`` the orphan tmp
    MUST be cleaned up and the on-disk ``cache.json`` MUST remain valid
    JSON (NFR-03 invariant).
    """
    command = "echo hi"
    task_id = "abcdef05"
    mid_write_error = "oserror"
    assert mid_write_error == "oserror"  # spec predicate
    # NFR-03: cache.json is the third atomic-write data file; a mid-write
    # OSError must leave it as valid JSON (tmp + os.replace invariant).

    sig = _cache_signature(command)

    # Pre-seed cache.json with an EXPIRED entry (TTL=1 s; cached_at far in
    # the past) so the GREEN cache lookup MISSES and the post-failure
    # write path is exercised.
    expired_cached_at = (
        datetime.fromtimestamp(time.time() - 100, tz=timezone.utc)
        .isoformat()
    )
    _seed_cache(
        taskq_home,
        {
            sig: {
                "exit_code": 0,
                "stdout_tail": "stale\n",
                "cached_at": expired_cached_at,
            }
        },
    )
    tasks_file = _seed_pending(taskq_home, task_id, command)

    monkeypatch.setenv("TASKQ_CACHE_TTL", "1")
    monkeypatch.setenv("TASKQ_RETRY_LIMIT", "0")
    monkeypatch.setenv("TASKQ_BACKOFF_BASE", "0")

    # ---- Inject OSError on os.replace ONLY for cache.json destinations.
    # The tasks.json write MUST succeed (so the run's status=done is
    # persisted); only the cache.json write fails — mimicking a
    # mid-write crash on that specific file (NFR-07 oserror-on-write
    # scenario, scoped to the cache module).
    real_replace = os.replace

    def _raising_replace(src: str, dst: str) -> None:  # type: ignore[no-untyped-def]
        dst_str = os.fspath(dst)
        if dst_str.endswith("cache.json"):
            raise OSError("simulated mid-write failure on cache.json")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _raising_replace)

    # ---- In-process: run --cached → MISS → subprocess → write cache.json
    # → os.replace raises OSError. The GREEN atomic-write boundary must
    # clean up the orphan tmp without corrupting the destination file.
    rc_in = cli.main(["run", task_id, "--cached"])
    # The CLI itself MUST still succeed (the run completed; only the
    # cache.json write failed, which is a side-effect).
    assert rc_in == 0, (
        f"in-process run --cached (cache write OSError) must exit 0, "
        f"got {rc_in}"
    )

    parsed_in = _load_tasks(tasks_file)
    record_in = parsed_in[task_id]
    assert record_in["status"] == "done", (
        f"even when cache.json write fails, the run's status must be "
        f"persisted as 'done' in tasks.json, got {record_in['status']!r}"
    )

    # ---- The atomic-write invariant: cache.json MUST remain valid JSON.
    # Either the pre-seeded content is preserved (atomic write absorbed
    # the failure) or the orphan tmp was cleaned up and the file is
    # missing — but it must NEVER be a half-written, unparseable file.
    cache_file = taskq_home / "cache.json"
    if cache_file.exists():
        try:
            cache_data = json_lib.loads(cache_file.read_text())
        except json_lib.JSONDecodeError as exc:
            pytest.fail(
                "NFR-03 invariant violated: cache.json must remain valid "
                f"JSON after a mid-write OSError, but it is corrupt: {exc}"
            )
        # If parse succeeded, ensure the root shape is the canonical
        # {version, entries} dict (i.e. not a half-written other file).
        assert isinstance(cache_data, dict), (
            f"cache.json root must be a JSON object, got {type(cache_data).__name__}"
        )
        assert "version" in cache_data, (
            f"cache.json must carry 'version' field even after a "
            f"failed write; got keys {list(cache_data.keys())!r}"
        )
        assert "entries" in cache_data, (
            f"cache.json must carry 'entries' field even after a "
            f"failed write; got keys {list(cache_data.keys())!r}"
        )

    # ---- Any orphan tmp must have been cleaned up.
    orphan_tmp = taskq_home / "cache.json.tmp"
    assert not orphan_tmp.exists(), (
        f"atomic-write invariant violated: orphan {orphan_tmp!s} was "
        f"left behind after the OSError; tmp cleanup must always run"
    )


# ---------------------------------------------------------------------------
# AC-FR04-06 — thread safety: concurrent run --all leaves cache.json valid
# ---------------------------------------------------------------------------


def test_fr04_06_cache_thread_safety(
    taskq_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """integration / Q7.

    AC: 10 pending tasks with the SAME command (``command_x="echo x"``)
    are dispatched via ``run --all`` (FR-02 ThreadPoolExecutor path). All
    tasks share ``sha256("echo x")`` as their cache signature. After the
    concurrent run completes:

    * ``tasks.json`` MUST be valid JSON (FR-02 contract), every record
      MUST be ``status="done"``;
    * ``cache.json`` MUST be valid JSON (NP-07/NFR-03 invariant) — no
      half-written entry, every record MUST survive the concurrent
      writers;
    * ``cache.json`` MUST contain exactly ONE entry for ``sha256("echo x")``
      (the 10 writers all collapsed onto the same signature).

    Rule IDs: ``FR04-concurrent-cache`` (``task_count == "10"``).

    GREEN TODO
    ---------
    The GREEN ``executor.run_all`` MUST funnel cache writes through the
    same shared ``threading.Lock`` that already protects tasks.json
    writes (per NFR-08). The ``cache.Cache`` module MUST own its own
    atomic-write boundary so concurrent ``cache.store(sig, done_result)``
    calls never produce a half-written entry.
    """
    command_x = "echo x"
    task_count = "10"
    cached_flag = "true"
    assert task_count == "10"  # spec predicate
    assert cached_flag == "true"
    # NFR-08: cache.json shares the concurrency lock under `run --all`; 10
    # concurrent writers must not corrupt the file or duplicate the entry.

    sig = _cache_signature(command_x)

    tasks_file = taskq_home / "tasks.json"
    seed: dict[str, dict] = {}
    for idx in range(int(task_count)):
        tid = f"abcdef{idx:02x}"
        seed[tid] = {
            "command": command_x,
            "name": "",
            "status": "pending",
            "created_at": f"2026-07-18T00:00:{idx:02d}+00:00",
        }
    tasks_file.write_text(json_lib.dumps(seed))

    # ---- In-process path: concurrent dispatch via ThreadPoolExecutor.
    rc_in = cli.main(["run", "--all"])
    assert rc_in == 0, (
        f"in-process run --all (10 tasks) must exit 0, got {rc_in}"
    )

    # tasks.json MUST remain valid JSON + every record MUST be done.
    parsed_in = _load_tasks(tasks_file)
    assert len(parsed_in) == int(task_count), (
        f"all 10 task records must survive concurrent writers, "
        f"got {len(parsed_in)} records"
    )
    for tid, rec in parsed_in.items():
        assert rec["status"] == "done", (
            f"task {tid!r} must be 'done' after concurrent run --all, "
            f"got {rec['status']!r}"
        )

    # cache.json MUST exist and be valid JSON (NFR-03 + NFR-08 invariants).
    cache_file = taskq_home / "cache.json"
    assert cache_file.exists(), (
        "after 10 concurrent successful runs of the SAME command, "
        "cache.json must be written by the GREEN cache module"
    )
    cache_data = _load_cache(taskq_home)  # raises on invalid JSON
    assert isinstance(cache_data, dict), (
        f"cache.json root must be a JSON object, got "
        f"{type(cache_data).__name__}"
    )
    entries = cache_data.get("entries", {})
    assert isinstance(entries, dict), (
        f"cache.json 'entries' must be a JSON object, got "
        f"{type(entries).__name__}"
    )

    # All 10 tasks share the same signature, so exactly 1 entry must
    # remain after the writes converge (10 → 1 by signature).
    assert sig in entries, (
        f"after concurrent run --all with shared command, cache.json "
        f"must carry entry for signature {sig!r}; "
        f"got entries={sorted(entries.keys())!r}"
    )
    assert len(entries) == 1, (
        f"all 10 concurrent writers collapse onto the same signature "
        f"{sig!r}; cache.json must contain exactly 1 entry, "
        f"got {len(entries)}: {sorted(entries.keys())!r}"
    )

    # ---- Subprocess path: same expectation via the real entry point.
    tasks_file.write_text(json_lib.dumps(seed))
    cache_file.unlink(missing_ok=True)

    proc = _run_subprocess(["run", "--all"], taskq_home)
    assert proc.returncode == 0, proc.stderr
    parsed_proc = _load_tasks(tasks_file)
    assert len(parsed_proc) == int(task_count)
    for tid, rec in parsed_proc.items():
        assert rec["status"] == "done", (
            f"subprocess: task {tid!r} must be 'done', "
            f"got {rec['status']!r}"
        )
    # cache.json must STILL be valid JSON after the subprocess dispatch.
    cache_data_proc = _load_cache(taskq_home)
    assert sig in cache_data_proc.get("entries", {}), (
        f"subprocess: cache.json must carry entry for signature "
        f"{sig!r}; got entries="
        f"{sorted(cache_data_proc.get('entries', {}).keys())!r}"
    )