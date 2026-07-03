# COVERAGE_REPORT — Phase 4

**Generated:** 2026-07-03
**Tool:** coverage.py (via `pytest --cov=03-development/src --cov-report=term-missing`)
**Python:** 3.11.15 (aarch64-apple-darwin)
**Gate 3 threshold:** ≥ 80%

## 1. Overall coverage

| Metric | Value |
|--------|-------|
| **TOTAL** | **100%** |
| Stmts | 349 |
| Miss | 0 |
| Cover | 100 |

`coverage report --format=total` → `100`.

Gate 3 threshold (≥80%): **PASS** by 20 points of headroom.

## 2. Per-module breakdown

| Module | Stmts | Miss | Cover | Missing lines |
|--------|------:|-----:|------:|---------------|
| `03-development/src/taskq/__init__.py` | 8 | 0 | 100% | — |
| `03-development/src/taskq/__main__.py` | 124 | 0 | 100% | — |
| `03-development/src/taskq/config.py` | 26 | 0 | 100% | — |
| `03-development/src/taskq/executor.py` | 99 | 0 | 100% | — |
| `03-development/src/taskq/models.py` | 30 | 0 | 100% | — |
| `03-development/src/taskq/redact.py` | 14 | 0 | 100% | — |
| `03-development/src/taskq/store.py` | 37 | 0 | 100% | — |
| `03-development/src/taskq/validation.py` | 11 | 0 | 100% | — |
| **TOTAL** | **349** | **0** | **100%** | — |

## 3. Uncovered lines

None. Every statement in `03-development/src/taskq/` is exercised by at least one passing test in the 389-test passing set.

## 4. Notes on the failing test vs coverage

The single failing test (`test_fr02_unit_executor_source_does_not_use_shell_true`) is a static-source assertion that fails with `FileNotFoundError` before any coverage probe is recorded for it. Its failure does **not** create a coverage gap: every executable statement in `executor.py` is exercised by the surrounding 389 passing tests, so `executor.py` remains at 100% coverage (99 stmts / 0 miss).

## 5. Reproducibility

```
/Users/johnny/projects/integration-test/.venv/bin/python -m pytest --cov=03-development/src --cov-report=term-missing -q | tee /Users/johnny/projects/integration-test/04-testing/coverage_raw.txt
/Users/johnny/projects/integration-test/.venv/bin/python -m coverage report --format=total
```

Both commands were executed; raw output is in `04-testing/coverage_raw.txt`.