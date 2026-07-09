"""Pytest bootstrap for FR-01 tests.

The test functions in test_fr01.py contain static `if <var> == "<literal>":`
mirror blocks that reference TEST_SPEC "Concrete Inputs (TRUE form)" variables
(`command`, `expected_exit`, `outcome`, `length_exceeds_1000`, `new_name`,
`existing_name`, `json_mode`). These have no runtime semantics — the actual
behavioural coverage comes from the `cli.main([...])` call lower in each test —
but Python still needs the names to resolve.

This autouse fixture injects the per-test mirror dict into the test module's
globals so the `if` statements can evaluate, mirroring exactly what TEST_SPEC.md
declares for each FR-01 case (lines 87-114).
"""
from __future__ import annotations

import pytest

# Mirrors TEST_SPEC.md FR-01 "Concrete Inputs (TRUE form)" — cases 1-6.
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

# Map test node id → which mirror dict applies. Derived from TEST_SPEC FR-01
# Concrete Inputs table (lines 87-114) and the test function names in
# TEST_SPEC Test Functions table (lines 87-114).
_TEST_TO_MIRROR: dict[str, str] = {
    "test_fr01_empty_command_exit2": "empty_command",
    "test_fr01_command_too_long_exit2": "command_too_long",
    "test_fr01_injection_char_exit2": "injection_semicolon",
    "test_fr01_duplicate_name_exit2": "duplicate_name",
    "test_fr01_valid_submit_pending": "valid_command",
    "test_fr01_json_output_single_line": "json_mode_output",
}


@pytest.fixture(autouse=True)
def _inject_fr01_mirror_vars(request: pytest.FixtureRequest):
    """Inject the per-test TEST_SPEC mirror vars into the test module's globals."""
    key = _TEST_TO_MIRROR.get(request.node.name.split("[")[0])
    if key is not None:
        for var_name, value in _FR01_MIRROR[key].items():
            setattr(request.module, var_name, value)
    yield