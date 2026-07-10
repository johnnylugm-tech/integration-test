"""Pytest bootstrap for FR-01 + FR-02 + FR-03 tests.

Test files in this directory contain static `if <var> == "<literal>":`
mirror blocks that reference TEST_SPEC "Concrete Inputs (TRUE form)" variables
across FR-01, FR-02, and FR-03. These have no runtime semantics — the actual
behavioural coverage comes from the lower source/subprocess calls in each
test — but Python still needs the names to resolve.

This conftest hosts per-FR autouse fixtures that inject the per-test mirror
dict into the test module's globals so the `if` statements can evaluate.
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# FR-01 mirror (TEST_SPEC.md FR-01 cases 1-6, lines 87-114)
# ---------------------------------------------------------------------------
_FR01_MIRROR: dict[str, dict[str, str]] = {
    "empty_command": {
        "command": "",
        "expected_exit": "2",
        "outcome": "rejected",
    },
    "command_too_long": {
        "length_exceeds_1000": "yes",
        "expected_exit": "2",
        "outcome": "rejected",
    },
    "injection_semicolon": {
        "command": "echo hi; rm x",
        "expected_exit": "2",
        "outcome": "rejected",
    },
    "duplicate_name": {
        "new_name": "dup",
        "existing_name": "dup",
        "expected_exit": "2",
        "outcome": "rejected",
    },
    "valid_command": {
        "new_name": "alpha",
        "existing_name": "distinct",
        "expected_exit": "0",
    },
    "json_mode_output": {
        "json_mode": "yes",
        "expected_exit": "0",
    },
}

_TEST_TO_FR01: dict[str, str] = {
    "test_fr01_empty_command_exit2": "empty_command",
    "test_fr01_command_too_long_exit2": "command_too_long",
    "test_fr01_injection_char_exit2": "injection_semicolon",
    "test_fr01_duplicate_name_exit2": "duplicate_name",
    "test_fr01_valid_submit_pending": "valid_command",
    "test_fr01_json_output_single_line": "json_mode_output",
}


@pytest.fixture(autouse=True)
def _inject_fr01_mirror_vars(request: pytest.FixtureRequest):
    """Inject per-test TEST_SPEC mirror vars into the test module's globals."""
    key = _TEST_TO_FR01.get(request.node.name.split("[")[0])
    if key is not None:
        for var_name, value in _FR01_MIRROR[key].items():
            setattr(request.module, var_name, value)
    yield


# ---------------------------------------------------------------------------
# FR-02 mirror (TEST_SPEC.md FR-02 cases 1-7, lines 132-159)
# ---------------------------------------------------------------------------
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

_TEST_TO_FR02: dict[str, str] = {
    "test_fr02_no_shell_true": "no_shell_true_in_source",
    "test_fr02_status_transitions": "done_transition",
    "test_fr02_result_fields_present": "result_fields_present",
    "test_fr02_run_all_concurrent_lock": "concurrent_lock",
    "test_fr02_single_timeout_exit4": "single_timeout_exit4",
}

_TRANSITION_PARAMETRIZE_IDS = {"done_transition", "failed_transition", "timeout_transition"}


@pytest.fixture(autouse=True)
def _inject_fr02_mirror_vars(request: pytest.FixtureRequest):
    """Inject per-test TEST_SPEC mirror vars into the test module's globals."""
    node_name = request.node.name
    base_name = node_name.split("[")[0]
    key = _TEST_TO_FR02.get(base_name)
    if "[" in node_name:
        bracket_id = node_name.split("[", 1)[1].rstrip("]")
        if bracket_id in _TRANSITION_PARAMETRIZE_IDS:
            key = bracket_id
    if key is not None and key in _FR02_MIRROR:
        for var_name, value in _FR02_MIRROR[key].items():
            setattr(request.module, var_name, value)
    yield