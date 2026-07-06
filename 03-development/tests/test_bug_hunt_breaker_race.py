"""[bug-hunt 2026-07-07] Repro test for the FR-03 breaker lost-update race.

Bug: ``taskq.breaker.check_and_record`` performs a read-modify-write of
``$TASKQ_HOME/breaker.json`` WITHOUT serialising concurrent callers.
When ``run --all`` fans out N failing subprocesses through a
``ThreadPoolExecutor``, every worker's ``_run_once`` failure routes
through ``check_and_record``. The lack of a per-file lock means racing
threads each read the prior state, increment locally, and the last
write wins -- silently dropping failures.

Production impact: with TASKQ_BREAKER_THRESHOLD=10 and 20 concurrent
failures, observation shows ``failure_count=5`` (15 failures lost). The
breaker stays CLOSED while 20 failures have already happened, defeating
the FR-03 "consecutive failures trip the breaker" guarantee.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from taskq import breaker


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Isolate storage under a tmp $TASKQ_HOME (mirrors fr03 home fixture)."""
    monkeypatch.setenv("TASKQ_HOME", str(tmp_path))
    return tmp_path


def _read_breaker_json(home_dir: Path) -> dict:
    return json.loads((home_dir / "breaker.json").read_text(encoding="utf-8"))


def test_breaker_concurrent_check_and_record_no_lost_updates(
    home, monkeypatch: pytest.MonkeyPatch
):
    """REGRESSION: 20 concurrent failure records must all count.

    Mirrors the production ``run --all`` path: ThreadPoolExecutor with
    multiple workers each calling ``breaker.check_and_record``.
    """

    n_workers = 20
    threshold = 100  # well above n_workers so the breaker stays CLOSED

    monkeypatch.setattr(breaker, "_THRESHOLD", threshold, raising=False)
    monkeypatch.setattr(breaker, "_COOLDOWN", 60.0, raising=False)

    barrier = threading.Barrier(n_workers)

    def record_one(_i: int) -> None:
        barrier.wait()  # release all threads simultaneously
        breaker.check_and_record(success=False)

    threads = [
        threading.Thread(target=record_one, args=(i,))
        for i in range(n_workers)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = _read_breaker_json(home)
    assert data.get("failure_count") == n_workers, (
        f"Lost updates under concurrent check_and_record: "
        f"got {data.get('failure_count')}, expected {n_workers} "
        f"(state={data.get('state')})"
    )


def test_breaker_concurrent_failures_trip_threshold(
    home, monkeypatch: pytest.MonkeyPatch
):
    """REGRESSION: with threshold = N/2, N concurrent failures MUST trip OPEN.

    Documents the FR-03 safety contract: under ``run --all`` the breaker
    must open after ``TASKQ_BREAKER_THRESHOLD`` *concurrent* failures,
    not just sequential ones.
    """

    n_workers = 12
    threshold = 5  # half of N -- race-induced lost-updates could keep it CLOSED

    monkeypatch.setattr(breaker, "_THRESHOLD", threshold, raising=False)
    monkeypatch.setattr(breaker, "_COOLDOWN", 60.0, raising=False)

    barrier = threading.Barrier(n_workers)

    def record_one(_i: int) -> None:
        barrier.wait()
        breaker.check_and_record(success=False)

    threads = [
        threading.Thread(target=record_one, args=(i,))
        for i in range(n_workers)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = json.loads((home / "breaker.json").read_text(encoding="utf-8"))
    assert data.get("state") == "OPEN", (
        f"Breaker should have OPENed after {n_workers} concurrent failures "
        f"(threshold={threshold}); got state={data.get('state')}, "
        f"count={data.get('failure_count')}"
    )
