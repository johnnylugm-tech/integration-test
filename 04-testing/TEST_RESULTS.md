# P4 — Test Results

> Generated: 2026-07-07
> Python: 3.11.15
> Test runner: pytest 8.4.2 + cov 7.1.0 (via `.venv/bin/python -m pytest`)

## Summary

| Metric | Value |
|--------|-------|
| Total tests collected | 53 |
| Passed | 53 |
| Failed | 0 |
| Skipped | 0 |
| Errors | 0 |
| Wall time | 7.15 s |

**Verdict: 53/53 PASS — 0 failures, 0 errors, 0 skips.**

```
============================== 53 passed in 7.15s ==============================
```

## Per-file breakdown

| Test File | Count | Result |
|-----------|------:|--------|
| `03-development/tests/test_fr01.py` | 6 | 6 PASS |
| `03-development/tests/test_fr02.py` | 6 | 6 PASS |
| `03-development/tests/test_fr03.py` | 9 | 9 PASS |
| `03-development/tests/test_fr04.py` | 4 | 4 PASS |
| `03-development/tests/test_fr04_cache.py` | 4 | 4 PASS |
| `03-development/tests/test_fr05.py` | 12 | 12 PASS |
| `03-development/tests/test_nfr.py` | 12 | 12 PASS |
| **Total** | **53** | **53 PASS** |

## Per-FR coverage of behaviour

| FR ID | Behaviour under test | Tests | File |
|-------|----------------------|------:|------|
| FR-01 | Atomic add-task with input validation | 6 | test_fr01.py |
| FR-02 | Subprocess (no `shell=True`), status machine, tail 2000, timeout, concurrency | 6 | test_fr02.py |
| FR-03 | Exponential backoff, retry cap, breaker threshold/open/half-open | 9 | test_fr03.py |
| FR-04 | Cache signature (SHA-256), replay, expiry, atomic thread-safe write | 4+4 | test_fr04.py / test_fr04_cache.py |
| FR-05 | argparse subcommands, --json round-trip, exit-code matrix, list/status | 12 | test_fr05.py |

## NFR coverage

| NFR | Dimension | Tests | File |
|-----|-----------|------:|------|
| NFR-01 | performance (p95 < 50 ms) | 1 | test_nfr.py |
| NFR-02 | security (no `shell=True`, injection blacklist) | 2 | test_nfr.py |
| NFR-03 | error handling (atomic write kill-9 recovery, cooldown close) | 2 | test_nfr.py |
| NFR-04 | security (secret redaction: sk-*, token) | 4 | test_nfr.py |
| NFR-05 | readability (every public symbol has FR ref) | 1 | test_nfr.py |
| NFR-06 | env-var defaults + override + completeness | 3 | test_nfr.py |

## Deferred / Known issues

- **None.** All 53 tests pass on the first run; no `@pytest.mark.skip`, `xfail`, or pending
  decorators were observed in the collected suite.
- The only uncovered lines (cli.py 251-252) are an unreachable-but-defensive
  `FileNotFoundError: pass` inside `_cmd_clear`. See `04-testing/COVERAGE_REPORT.md`
  for the uncovered-line inventory.

## Reproducibility

```bash
cd /Users/johnny/projects/integration-test
.venv/bin/python -m pytest --cov=03-development/src --cov-report=term-missing -v
```

Raw pytest+coverage output is preserved at `04-testing/coverage_raw.txt`.
