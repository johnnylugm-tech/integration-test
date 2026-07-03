# RISK_STATUS_REPORT.md — integration-test (taskq)

> Phase 7 — Risk Management
> Generated: 2026-07-04
> Source: `RISK_REGISTER.md` + `RISK_MITIGATION_PLANS.md`
> Window: Phase 7 → Phase 8 transition (deadline: 2026-08-01 for H1–H4 except H3 which extends to 2026-08-01 with waiver backstop)

## 1. Status Snapshot

| Tier | Count | Open | Mitigated | Accepted | Refuted | Deferred |
|------|-------|------|-----------|----------|---------|----------|
| HIGH (L×I ≥ 9) | 4 | 3 | 1 | 0 | 0 | 0 |
| MED (4–8)       | 6 | 0 | 4 | 1 | 1 | 1 |
| LOW (1–3)       | 7 | 1 | 0 | 6 | 0 | 0 |
| **TOTAL**       | **17** | **4** | **5** | **7** | **1** | **1** |

Gate entry posture: Gate 4 PASS at composite 96.41 — no risk currently threatens a re-gate. Three HIGH risks are open but with mitigation plans filed; one HIGH (R-15) is mitigated-by-design.

## 2. Per-Risk Status

| Risk ID | Title | L×I | Status | Mitigation Owner | Target Date | Phase 8 Action |
|---------|-------|-----|--------|------------------|-------------|---------------|
| R-01 | Concurrent/interrupted write corruption | 1×4 | MITIGATED | Johnny (atomic write trust) | rolled in v0 (FR-01) | Monitor on each FR-01 delta |
| R-02 | Subprocess hang | 2×2 | MITIGATED | taskq.executor | rolled in v0 (FR-02) | Monitor on each FR-02 delta |
| R-03 | Secret persistence leak | 2×3 | MITIGATED | taskq.redact | rolled in v0 (FR-02) | Optional: redaction-audit test |
| R-04 | Stale cache | 1×2 | NOT-PRESENT | taskq maintainer | n/a | Review only if cache added |
| R-05 | Retry-stale running snapshot | 3×3 | **OPEN** | taskq.executor maintainer | **2026-07-11** | Ship with FR-02 delta; 1 test + 3 LOC |
| R-06 | Concurrent run read-modify-write | 2×3 | REFUTED (SPEC scope) | taskq.store | n/a | Document single-writer assumption in store.py docstring |
| R-07 | Bandit LOW findings (subprocess) | 2×2 | ACCEPTED | Johnny | 2026-07-11 | Add `# nosec B404,B603 — see NFR-02` |
| R-08 | Pyright info (redact.py escape) | 1×1 | ACCEPTED | taskq.redact | optional | Convert to raw strings |
| R-09 | Readability MI buffer thin | 3×3 | **OPEN — MONITOR** | taskq.executor / cli | 2026-07-18 (pre-commit hook) | Add hook + refactor criteria comment |
| R-10 | Architecture cohesion low (waivered) | 4×3 | **OPEN — WAIVERED** | Johnny (human) + CRG | 2026-08-01 (refactor) | `__main__.py` split into cli_dispatch + _persist |
| R-11 | 1-line coverage gap (cli.py) | 1×1 | ACCEPTED | test maintainer | optional | Fault-injection test for StoreCorruptedError |
| R-12 | Dead `_error` field | 2×1 | OPEN | taskq.executor | 2026-07-11 | Pack with R-05 PR (1 LOC) |
| R-13 | Gate verdict authority (sub-agent reliability) | 2×4 | MITIGATED | workflow maintainer | rolled in v0 | E2E test per phase |
| R-14 | Harness submodule drift | 2×4 | MONITORED | Johnny | ongoing | Pin to `edcbefd`; check at each gate boundary |
| R-15 | Workflow JS regression history | 3×4 | **MITIGATED — MONITOR** | workflow maintainer | 2026-07-18 (lint script) | Add `workflow-js-lint` scanner |
| R-16 | Mutation testing disabled | 2×2 | DEFERRED | Johnny | next gate review | Discuss at P8 entry |
| R-17 | Gap-report ORPHANED (heuristic) | 1×2 | ACCEPTED — TOOL LIMIT | tooling | n/a | Tighten gap-report heuristic |

## 3. Critical Path (next 4 weeks)

| Date | Milestone | Risks Touched |
|------|-----------|---------------|
| 2026-07-04 | Phase 7 entry (this report) | all 17 logged |
| 2026-07-11 | FR-02 delta + R-05/R-12 fix | R-05, R-12, R-07 |
| 2026-07-18 | R-09 hook + R-15 lint script | R-09, R-15 |
| 2026-07-25 | CRG smoke run for architecture | R-10 |
| 2026-08-01 | Phase 8 entry review (last deadline) | R-10, R-16 |

## 4. Open Decisions

- **D-1**: Whether to ship R-05 + R-12 in one PR or separate. Recommendation: one PR (6 LOC + 1 test, atomic story).
- **D-2**: Whether `__main__.py` refactor (R-10) should happen in Phase 7 or Phase 8. Recommendation: Phase 8 (avoid mid-phase churn).
- **D-3**: Whether to enable mutation testing now (R-16) or defer again. Recommendation: defer; revisit at Phase 8 entry.
- **D-4**: Whether the R-13 mitigation should be encoded as a workflow assertion or just a code review note. Recommendation: keep both — code review note + workflow precheck.

## 5. Cross-References

- `RISK_REGISTER.md` — full risk matrix.
- `RISK_MITIGATION_PLANS.md` — formal plans for R-05/R-09/R-10/R-15.
- `.methodology/quality_manifest.json` — high_risk_modules (taskq.executor / taskq.store) anchor R-05/R-09/R-12.
- `.methodology/bug_hunt_report.json` — R-05 (open medium), R-12 (open low), R-06 (refuted).
- `.methodology/gate4_result.json` — R-07, R-08, R-09, R-10, R-11 findings.
- `.methodology/gap_report.json` — R-17.
- MEMORY.md — R-13, R-14, R-15 historical evidence.

## 6. Acknowledgement

- **HANDOFF**: This report closes Phase 7 risk-artifact generation. Per scope, `advance-phase` / `push-milestone` are NOT executed by this author; the orchestrator owns the FSM transition and HANDOVER.md update.
- **NO harness edits**: HR-17 respected; all tooling planned for this report lives outside `harness/`.
- **NO FR re-implementation**: R-05 fix is the only planned code change; it is ≤ 5 LOC inside an existing FR-02 surface and follows FR-02's existing test layer.
