# Baseline — Phase 5 Verification

**Generated:** 2026-06-25
**Project:** integration-test (taskq)
**Phase:** 5 — Verification
**Source of truth:** `04-testing/TEST_RESULTS.md`, `04-testing/COVERAGE_REPORT.md`, `.methodology/quality_manifest.json`, `.methodology/gate3_result.json`

---

## 1. Current Version

| Item | Value |
|------|-------|
| Repo HEAD | `7660996 test: fix broken unit tests blocking CI after P5 bugfixes` |
| Last Phase 5 fix commit | `3325a6a fix: resolve Phase 5 bugs (P5-BUG-01 to P5-BUG-05)` |
| Latest pre-P5 commit | `1acc9df fix(handoff): P4→P5 uses gates.gate3.quality_complete (matches entry-gate schema)` |
| Working tree | clean (no uncommitted modifications under tracked paths) |
| Python | 3.14.6 (`.venv/bin/python`) |
| Branch | `main` |
| Architecture constraints | `no_circular_dependencies`, `no_shell_true`, `atomic_writes_only` |
| High-risk modules | `taskq.executor`, `taskq.breaker`, `taskq.store` |

---

## 2. Source Module Inventory (`03-development/src/`)

| Module | Lines (statements) | Role |
|--------|-------------------:|------|
| `taskq/__init__.py` | 0 | Package marker |
| `taskq/__main__.py` | 0 | `python -m taskq` entry shim |
| `taskq/breaker.py` | 74 | Circuit breaker (FR-03) |
| `taskq/cache.py` | 62 | TTL result cache (FR-04) |
| `taskq/cli.py` | 121 | Argparse CLI (FR-05) |
| `taskq/config.py` | 39 | Env-var reader (NFR-06) |
| `taskq/executor.py` | 86 | Subprocess executor + redaction (FR-02 / NFR-04) |
| `taskq/models.py` | 38 | Dataclasses / enums |
| `taskq/store.py` | 76 | Atomic JSON storage (FR-01 / NFR-03) |
| **TOTAL (src)** | **496** | — |

> Note: legacy `.bak` files (`breaker.py.bak`, `cache.py.bak`, `cli.py.bak`) remain on disk from a previous refactor but are not imported and are excluded from coverage measurement.

---

## 3. Test Results Summary (Phase 4 baseline, re-validated)

Sourced from `04-testing/TEST_RESULTS.md` (generated 2026-06-24, pytest 175/175 PASS, 11.12 s).

| Metric | Value |
|--------|-------|
| Total cases run | 175 |
| Passed | 175 |
| Failed | 0 |
| Errors | 0 |
| Skipped | 0 |
| xfail | 0 |
| Duration | 11.12 s (Phase-4 run) / 10.82 s (latest raw replay) |

Per-file breakdown:

| File | Cases | Result |
|------|------:|--------|
| `test_fr01.py` | 37 | PASS |
| `test_fr02.py` | 37 | PASS |
| `test_fr03.py` | 17 | PASS |
| `test_fr04.py` | 15 | PASS |
| `test_fr05.py` | 28 | PASS |
| `test_bughunt_regressions.py` | 5 | PASS |
| `test_nfr.py` | 20 | PASS |
| `integration/test_integration_e2e.py` | 10 | PASS |
| **Total** | **175** | **PASS** |

Deferred / skipped / xfail at Phase 4 exit: **None**.

---

## 4. Coverage

Source: `04-testing/COVERAGE_REPORT.md` + `04-testing/coverage_raw.txt`.

| Metric | Value |
|--------|-------|
| Source-line coverage (src) | **100%** (496/496 statements, 0 missing) |
| Combined (src + tests) coverage | 94% (2544 statements, 143 missed in test files) |
| Gate 3 threshold (`quality_manifest.json`) | ≥ 80% |
| Gate 3 status | PASS |

Per-module coverage (source only):

| Module | Stmts | Miss | Cover |
|--------|------:|-----:|------:|
| `taskq/__init__.py` | 0 | 0 | 100% |
| `taskq/__main__.py` | 0 | 0 | 100% |
| `taskq/breaker.py` | 74 | 0 | 100% |
| `taskq/cache.py` | 62 | 0 | 100% |
| `taskq/cli.py` | 121 | 0 | 100% |
| `taskq/config.py` | 39 | 0 | 100% |
| `taskq/executor.py` | 86 | 0 | 100% |
| `taskq/models.py` | 38 | 0 | 100% |
| `taskq/store.py` | 76 | 0 | 100% |

High-risk-module coverage:

| Module | Coverage |
|--------|---------:|
| `taskq/executor.py` | 100% |
| `taskq/breaker.py` | 100% |
| `taskq/store.py` | 100% |

---

## 5. Gate 3 Composite Score

Source: `.methodology/gate3_result.json` + `.methodology/quality_manifest.json::gate_results.gate3`.

| Field | Value |
|-------|-------|
| Composite score | **100.0** |
| Quality complete | `true` |
| Rounds used | 2 |
| Open critical | 0 |
| Open high | 0 |
| Phase / gate / scope | 4 / 3 / all FRs |
| Timestamp | 2026-06-25T00:00:00Z |

Per-dimension scores:

| Dimension | Score |
|-----------|------:|
| linting | 100 |
| type_safety | 100 |
| test_coverage | 94 |
| security | 100 |
| secrets_scanning | 100 |
| license_compliance | 100 |
| test_assertion_quality | 100 |
| readability | 80.0 |
| error_handling | 83.3 |
| documentation | 100 |
| performance | n/a (no benchmark tests defined; tool_score=null) |
| traceability (framework override) | 100.0 |

Notes attached to Gate 3 record:

- `mutation_testing: skipped (disabled by default)`
- `performance: no benchmark tests defined (tool_score=None)`
- `architecture: framework-owned (CRG)`
- `adversarial_review: framework-owned (bug_hunt_report)`

---

## 6. References

- `04-testing/TEST_RESULTS.md` — execution summary
- `04-testing/COVERAGE_REPORT.md` — per-module coverage
- `04-testing/coverage_raw.txt` — raw `coverage.py` text report
- `04-testing/TEST_PLAN.md` — 66-case traceability plan
- `03-development/src/taskq/` — source modules
- `.methodology/gate3_result.json` — official Gate-3 artifact
- `.methodology/quality_manifest.json` — quality targets & NFR mapping
- `.methodology/fr_progress.json` — per-FR Gate-1 scores
