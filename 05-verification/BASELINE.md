# BASELINE.md - integration-test

> On-demand Lazy Load template — filled at Phase 5 (Verification) checkpoint.
> Source template: `harness/templates/BASELINE.md` (this file conforms 1:1 to its 7 `## ` sections).

## 1. Baseline Overview
- Author: Phase 5 Verification (P5 authoring agent)
- Reviewer: Phase 6 — Quality Gate (Gate 4)
- session_id: `phase5-verification` (`.sessi-work/phase5_ctx.json` → `phase: 5`)
- Date: 2026-07-03

| Identity item | Value |
|---------------|-------|
| Project | `integration-test` |
| Package | `taskq` |
| Package version | `0.1.0` (`03-development/src/pyproject.toml`) |
| Git describe | `baseline-v6-90-g7d66d0d` |
| HEAD | `7d66d0d2daeec9aa9b2f838e938a1b7cfcbb441c` |
| Python | 3.11.15 (aarch64-apple-darwin) |
| Framework | harness-methodology v2.12.0 |
| Architecture constraint | `no_circular_dependencies` (Gate 2 upheld) |
| High-risk modules | `taskq.executor`, `taskq.store` |
| NFR → Dimension | NFR-01 → performance, NFR-02 → security, NFR-03 → error_handling |

## 2. Functional Baseline (maps to SRS FR, 100% complete)

| FR ID | Feature Description | Baseline Status | Notes |
|-------|---------------------|-----------------|-------|
| FR-01 | 任務模型與持久化 (Task Model & Persistence) | PASS | Gate 1 score = 100.0; `taskq.models` + `taskq.store` 100% covered; atomic-write crash-safety test green |
| FR-02 | 任務執行與重試 (Task Execution & Retry) | PASS | Gate 1 score = 100.0; `taskq.executor` 100% covered; `shell=False` invariant enforced + injection blacklist covered |
| FR-03 | CLI 整合與查詢 (CLI Integration & Query) | PASS | Gate 1 score = 100.0; `taskq.cli` 100% covered; single-line JSON no-trailing-newline contract upheld |

FR list source: `.sessi-work/phase5_ctx.json` → `fr_ids = [FR-01, FR-02, FR-03]`. All 3 FRs are at `quality_complete: true` with `open_critical: 0, open_high: 0`.

## 3. Quality Baseline

| Metric | Threshold | Actual | Status |
|--------|-----------|--------|--------|
| Constitution (P5+) | >= 80% | 97.67 (Gate 3 composite) | PASS |
| Coverage | >= 80% | 100% (385/385 stmts; 0 miss across 10 modules) | PASS |
| Logic Correctness | >= 90 | Gate 3 `test_assertion_quality` = 100 | PASS |
| Type safety | >= 85 | Gate 3 `type_safety` = 100 (0 errors, 2 informational warnings on `redact.py` docstring `\S` escapes) | PASS |
| Linting | >= 90 | Gate 3 `linting` = 100 (0 violations) | PASS |
| Security (bandit -ll) | 0 high / 0 medium | 0 high / 0 medium (2 low below `-ll` threshold: B404 subprocess import + B603 subprocess call — both intentional per NFR-02) | PASS |
| Secrets (gitleaks) | 0 leaks | 0 leaks (366 commits / 6.73 MB scanned) | PASS |
| License compliance | 100 | 100 (33 files, 0 third-party-licensed) | PASS |
| Traceability | >= 85 | Gate 3 `traceability` = 100 | PASS |
| Performance | >= 85 | Gate 3 `performance` = 100 (NFR-01 p95 well below 50ms target) | PASS |
| Error handling | >= 85 | Gate 3 `error_handling` = 100 | PASS |
| Documentation | >= 85 | Gate 3 `documentation` = 100 | PASS |

Test execution: `.venv/bin/python -m pytest 03-development/tests/ -q --cov=03-development/src` → **461 passed, 0 failed, 0 errors, 0 skipped** in 24.12s (includes 3 pytest-benchmark cases).

## 4. Performance Baseline (A/B monitoring)

Source: `03-development/tests/test_benchmark.py` (pytest-benchmark, warm-process, excluding subprocess spawn).

| Metric | Baseline Value | Source / Test |
|--------|----------------|---------------|
| `load_tasks_or_die` p50 (median) | **18.67 µs** (min 18.29 µs, mean 18.84 µs, σ 0.84 µs) | `test_bench_load_tasks_or_die` |
| `atomic_write_tasks` p50 (median) | **145.79 µs** (min 135.71 µs, mean 158.44 µs) | `test_bench_atomic_write_tasks` |
| `submit_status_round_trip` p50 (median) | **3.41 ms** (mean 3.38 ms, σ 1.83 ms; min 0.21 ms / max 11.55 ms reflects cold OS-process tail) | `test_bench_submit_status_round_trip` |
| NFR-01 p95 budget (warm-process submit+status, 100 iter, subprocess excluded) | < 50 ms — well within budget | `test_nfr01_p95_latency` PASS |
| Memory | not separately instrumented (no process-RSS baseline recorded; project is small, runtime < 50 MB in practice) | n/a |
| Error Rate | 0% (461/461 PASS, 0 ERROR, 0 FAIL) | full pytest suite |

## 5. Known Issues

| Severity | Count | Description |
|----------|-------|-------------|
| HIGH | 0 | — |
| MEDIUM | 0 | — |
| LOW (informational) | 2 | `DeprecationWarning: invalid escape sequence '\S'` — `03-development/src/taskq/redact.py` lines 1 and 25 (regex-style docstring hints parsed by stricter Python; cosmetic, zero behavioural impact; cleanup candidate: raw-string docstring) |
| LOW (informational) | 2 | bandit `-ll` skipped findings: B404 `subprocess` import in `executor.py:23` and B603 subprocess call in `executor.py:122` — both intentional NFR-02 chokepoints |

> HIGH severity count = 0. Baseline is established (per template rule).

## 6. Change Log

| Date | Change | Commit / Ref |
|------|--------|--------------|
| 2026-07-03 | feat(FR-02): Gate1 PASS — score=100.0 [phase=5] | `7d66d0d` |
| 2026-07-03 | feat(FR-01): Gate1 PASS — score=100.0 [phase=5] | `5639154` |
| 2026-07-03 | fix(workflows): DELTA fast-path phase-scoped verdict + restore P5 BASELINE.md generation | `856f0b1` |
| 2026-07-03 | docs(P5): BASELINE.md — review baseline checkpoint | `34e5158` |
| 2026-07-03 | chore(trace): regen attestation after SAD-aligned source split | `f834c3f` |
| 2026-07-03 | refactor(taskq): split __main__.py into cli.py + query.py per SAD §2.1 module decomposition | `3099f95` |
| 2026-07-03 | feat(workflows): GATE1-DELTA fast-path — batch CLI probe skips full per-FR loop for immediately-passing FRs (phase4/5/7/8) | `04dbb9b` |
| 2026-07-03 | chore: phase 4 clean-up | `94320ce` |
| 2026-07-03 | handover: advance to Phase 5 | `7c6aafd` |
| 2026-07-03 | test(P4): Gate3 PASS score=97.7 — full test suite | `905586c` |

## 7. Acceptance Sign-off

- Agent A (P5 Verification author): Phase 5 Verification agent (`phase5-verification`) — 2026-07-03
- Approver: Phase 6 — Quality Gate (Gate 4) — pending (this baseline is the input to Gate 4 verification at P6 entry)