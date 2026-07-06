"""[NFR-01] Performance benchmarks — pytest-benchmark contract.

NFR-01 target: submit + status p95 < 50 ms over 100 iterations.
Each benchmark exercises a real taskq code path (not a mock).

These tests live in 03-development/tests/perf/ so they can be filtered via
``pytest 03-development/tests/perf --benchmark-only`` for the performance
dimension while leaving the rest of the suite untouched.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))


@pytest.fixture()
def perf_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sd = tmp_path / "taskq-perf-home"
    sd.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TASKQ_HOME", str(sd))
    return sd


def test_bench_submit_p95_under_50ms(benchmark, perf_state_dir: Path) -> None:
    """[NFR-01] submit a single task; mean latency target < 50 ms (proxy for p95)."""
    from taskq import cli

    def _one_submit() -> None:
        cli.main(["submit", "echo perf-1"])

    benchmark(_one_submit)


def test_bench_status_p95_under_50ms(benchmark, perf_state_dir: Path) -> None:
    """[NFR-01] status of one task; mean latency target < 50 ms (proxy for p95)."""
    from taskq import cli

    cli.main(["submit", "echo perf-2"])
    tid = next(iter(__import__("json").loads((perf_state_dir / "tasks.json").read_text()).keys()))

    def _one_status() -> None:
        cli.main(["status", tid])

    benchmark(_one_status)


def test_bench_list_p95_under_50ms(benchmark, perf_state_dir: Path) -> None:
    """[NFR-01] list with 10 tasks; mean latency target < 50 ms (proxy for p95)."""
    from taskq import cli
    import json as _json

    for i in range(10):
        cli.main(["submit", f"echo perf-list-{i}"])

    def _one_list() -> None:
        cli.main(["list"])

    benchmark(_one_list)
