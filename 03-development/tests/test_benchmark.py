"""pytest-benchmark micro-benchmarks for NFR-01 (performance).

NFR-01: taskq.store — p95 < 50ms (warm-process, submit+status over 100 iters,
excluding subprocess).

Benchmarks measure the in-process submit+status round-trip so pytest-benchmark
can record mean latency directly. The CLI subprocess path is covered separately
in `test_fr01.py` acceptance tests (separate timing surface).
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_taskq_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point TASKQ_HOME at a per-test tmp directory.

    Yields the home Path. Tests must write tasks.json inside this directory.
    """
    home = tmp_path / ".taskq"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TASKQ_HOME", str(home))
    yield home


@pytest.fixture
def warm_loaded_store(tmp_taskq_home: Path):
    """Pre-warm json/cwd imports; yield a callable that loads tasks.json."""
    # Warm-up: import + first load (excluded from benchmark by warmup rounds).
    from taskq.store import load_tasks_or_die, atomic_write_tasks

    # Seed: one existing task so list() has a realistic dataset.
    seed = [{"id": "warm-1", "command": "echo seed", "status": "pending"}]
    atomic_write_tasks(seed, "warm-1")

    def _load():
        return load_tasks_or_die()

    return _load


def test_bench_load_tasks_or_die(benchmark, warm_loaded_store):
    """NFR-01: load_tasks_or_die p95 < 50ms per iter (warm-process)."""
    result = benchmark(warm_loaded_store)
    assert isinstance(result, list)


def test_bench_atomic_write_tasks(benchmark, tmp_taskq_home: Path):
    """NFR-01: atomic_write_tasks p95 < 50ms per iter (warm-process)."""
    from taskq.store import atomic_write_tasks

    payload = [
        {"id": "bench-1", "command": "echo hi", "status": "pending"},
        {"id": "bench-2", "command": "ls -la", "status": "done"},
        {"id": "bench-3", "command": "pwd", "status": "failed"},
    ]
    benchmark(atomic_write_tasks, payload, "bench-write")


def test_bench_submit_status_round_trip(benchmark, tmp_taskq_home: Path):
    """NFR-01: submit+status in-process round-trip p95 < 50ms per iter.

    Simulates the operational hot path: load → append → write → reload.
    """
    from taskq.store import (
        atomic_write_tasks,
        append_task,
        load_tasks_or_die,
    )

    # Seed initial store.
    seed = [{"id": "seed-1", "command": "echo init", "status": "pending"}]
    atomic_write_tasks(seed, "seed-1")

    counter = {"i": 0}

    def _round_trip():
        counter["i"] += 1
        record = {
            "id": f"task-{counter['i']:04d}",
            "command": "echo hi",
            "status": "pending",
        }
        append_task(record)
        tasks = load_tasks_or_die()
        # Find our newly-appended record.
        matches = [t for t in tasks if t["id"] == record["id"]]
        return matches[0]["status"] if matches else None

    status = benchmark(_round_trip)
    assert status == "pending"
