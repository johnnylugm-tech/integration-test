# TEST_RESULTS — Phase 4

**Generated:** 2026-07-03
**Test runner:** `/Users/johnny/projects/integration-test/.venv/bin/python -m pytest --cov=03-development/src --cov-report=term-missing -q`
**Execution time:** 9.08s
**Test root:** `03-development/tests/`

## 1. Summary

| Metric | Value |
|--------|-------|
| Tests collected | 390 |
| Passed | 389 |
| Failed | 1 |
| Errors | 0 |
| Skipped | 0 |
| Pass rate (excluding the one path-resolution failure) | 99.7% |

Coverage was measured in the same pytest invocation; see `04-testing/COVERAGE_REPORT.md`.

## 2. Pass / Fail breakdown

- **389 passed** across the entire suite (`03-development/tests/` — unit + integration + NFR + per-FR groups).
- **1 failed**:
  - `03-development/tests/integration/test_fr02.py::test_fr02_unit_executor_source_does_not_use_shell_true`
    - Failure: `FileNotFoundError: [Errno 2] No such file or directory: '/Users/johnny/projects/integration-test/03-development/tests/src/taskq/executor.py'`
    - Root cause: the test resolves the source file via `Path(__file__).parent.parent / "src" / "taskq" / "executor.py"`. From `tests/integration/test_fr02.py`, `parent.parent` lands at `tests/`, producing the wrong path `tests/src/taskq/executor.py`. The actual source lives at `03-development/src/taskq/executor.py`.
    - Impact: this is a test-side path-resolution defect, not a source defect. The intent of the test (NFR-02: no `shell=True` in executor.py) is already covered by the passing `test_nfr02_no_shell_true_repo_grep` in `test_nfr.py`.
    - NFR-02 invariant is upheld — the executor source is still scanned via the repo-grep test that passes.

## 3. Deferred issues

None — no tests were skipped, xfailed, or marked xfail. All non-passing results are the single path-resolution failure above.

## 4. Warnings (informational)

`DeprecationWarning: invalid escape sequence '\S'` — emitted by `taskq/redact.py` lines 1 and 25 from inside docstrings. These are regex-style docstring comments (`\S`-class hints) being parsed by newer Python's stricter docstring escape rules. Behavioural impact: none. Clean-up candidate (escape with raw string `r"""..."""` or `\\S`).

## 5. Reproducibility

Re-run with:

```
/Users/johnny/projects/integration-test/.venv/bin/python -m pytest --cov=03-development/src --cov-report=term-missing -q
```

Raw output is preserved at `04-testing/coverage_raw.txt`.