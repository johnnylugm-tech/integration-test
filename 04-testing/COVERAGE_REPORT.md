# Coverage Report — Phase 4

**Generated:** 2026-06-24  
**Tool:** pytest-cov + coverage.py  
**Source root:** `03-development/src`  
**Raw output:** `04-testing/coverage_raw.txt`

---

## Overall Coverage

| Metric | Value |
|--------|-------|
| Total statements | 2544 |
| Missed statements | 143 |
| **Coverage** | **94%** |
| Gate 3 threshold | ≥ 80% |
| **Gate 3 status** | ✅ PASS |

---

## Per-Module Breakdown (Source Code)

| Module | Stmts | Miss | Cover | Missing Lines |
|--------|-------|------|-------|---------------|
| `taskq/__init__.py` | 0 | 0 | 100% | — |
| `taskq/breaker.py` | 74 | 0 | 100% | — |
| `taskq/cache.py` | 62 | 0 | 100% | — |
| `taskq/cli.py` | 111 | 0 | 100% | — |
| `taskq/config.py` | 39 | 0 | 100% | — |
| `taskq/executor.py` | 101 | 0 | 100% | — |
| `taskq/models.py` | 38 | 0 | 100% | — |
| `taskq/parser.py` | 19 | 0 | 100% | — |
| `taskq/store.py` | 76 | 0 | 100% | — |
| **SRC TOTAL** | **520** | **0** | **100%** | — |

## Per-Module Breakdown (Test Code)

Test files have overall 94% coverage; see uncovered lines section.

---

## Uncovered Lines

143 statements are not covered across test files. Notable coverage gaps:
- `test_fr01.py`: lines 32-33, 52-53, 76, 93, 104, 115, 128, 140, 163, 174, 192, 210, 222, 241-242, 598, 614 (94% coverage)
- `test_fr02.py`: lines 54, 71, 88, 105, 125, 143, 161, 177, 201, 225-226, 267, 293, 313, 329, 346, 671, 692-693, 695, 716 (94% coverage)
- `test_fr03.py`: multiple untested paths (90% coverage)
- `test_fr04.py`: conditional branches (90% coverage)
- `test_fr05.py`: edge cases (89% coverage)

---

## High-Risk Module Coverage

Per `CLAUDE.md` architecture constraints, the three high-risk modules are fully covered:

| High-Risk Module | Coverage |
|-----------------|----------|
| `taskq/executor.py` | 100% |
| `taskq/breaker.py` | 100% |
| `taskq/store.py` | 100% |
