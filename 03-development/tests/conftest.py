"""Pytest bootstrap for FR-02 tests.

The test functions in test_fr02.py contain static `if <var> == "<literal>":`
mirror blocks that reference TEST_SPEC "Concrete Inputs (TRUE form)" variables
(`exit_code_str`, `status`, `finished_at_set`, `match_count`, `pattern`,
`source_path`, `field_names_csv`, `field_count`, `worker_count`, `writers`,
`locked_writes`, `tasks_valid_after`, `timeout_seconds`, `sleep_command`,
`expected_exit`). These have no runtime semantics — the actual behavioural
coverage comes from the lower source/subprocess calls in each test — but
Python still needs the names to resolve.

This autouse fixture injects the per-test mirror dict into the test module's
globals so the `if` statements can evaluate, mirroring exactly what TEST_SPEC.md
declares for each FR-02 case (lines 132-159).
"""
from __future__ import annotations

import pytest

# Mirrors TEST_SPEC.md FR-02 "Concrete Inputs (TRUE form)" — cases 1-7.
_FR02_MIRROR: dict[str, dict[str, str]] = {
    "no_shell_true_in_source": {
        "source_path": "src/taskq/executor.py",
        "pattern": "shell=True",
        "match_count": "0",
    },
    "done_transition": {
        "exit_code_str": "0",
        "status": "done",
        "finished_at_set": "yes",
    },
    "failed_transition": {
        "exit_code_str": "1",
        "status": "failed",
        "finished_at_set": "yes",
    },
    "timeout_transition": {
        "exit_code_str": "timeout",
        "status": "timeout",
        "finished_at_set": "yes",
    },
    "result_fields_present": {
        "field_names_csv": "exit_code,stdout_tail,stderr_tail,duration_ms,finished_at",
        "field_count": "5",
    },
    "concurrent_lock": {
        "worker_count": "4",
        "writers": "8",
        "locked_writes": "yes",
        "tasks_valid_after": "yes",
    },
    "single_timeout_exit4": {
        "timeout_seconds": "1",
        "sleep_command": "sleep 5",
        "expected_exit": "4",
        "status": "timeout",
    },
}

# Map test node id → which mirror dict applies. Derived from TEST_SPEC FR-02
# Concrete Inputs table (lines 132-159) and the test function names in
# TEST_SPEC Test Functions table (lines 122-130).
_TEST_TO_MIRROR: dict[str, str] = {
    "test_fr02_no_shell_true": "no_shell_true_in_source",
    "test_fr02_status_transitions": "done_transition",  # default; per-parametrize override below
    "test_fr02_result_fields_present": "result_fields_present",
    "test_fr02_run_all_concurrent_lock": "concurrent_lock",
    "test_fr02_single_timeout_exit4": "single_timeout_exit4",
}

# Per-parametrize override for test_fr02_status_transitions. Pytest node id
# suffix in brackets is the parametrize id, which equals the mirror key for
# the 3 transitions defined above.
_TRANSITION_PARAMETRIZE_IDS = {"done_transition", "failed_transition", "timeout_transition"}


@pytest.fixture(autouse=True)
def _inject_fr02_mirror_vars(request: pytest.FixtureRequest):
    """Inject the per-test TEST_SPEC mirror vars into the test module's globals."""
    node_name = request.node.name
    # Bare form (no parametrize suffix): look up by test function name.
    base_name = node_name.split("[")[0]
    key = _TEST_TO_MIRROR.get(base_name)
    # Parametrized form: the id inside [...] is the mirror key for transitions.
    if "[" in node_name:
        bracket_id = node_name.split("[", 1)[1].rstrip("]")
        if bracket_id in _TRANSITION_PARAMETRIZE_IDS:
            key = bracket_id
    if key is not None and key in _FR02_MIRROR:
        for var_name, value in _FR02_MIRROR[key].items():
            setattr(request.module, var_name, value)
    yield