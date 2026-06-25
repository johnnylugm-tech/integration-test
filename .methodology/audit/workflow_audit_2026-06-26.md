# Workflow JS Audit — phase 1~8 vs regenerated plans

- **Date**: 2026-06-26
- **Trigger**: `git submodule update --remote` (harness 0906cb3 → 3f1fd73) + `plan-all`
- **Baseline for diff**: `b41c38f chore(p7): bump harness submodule + amend SAB.json + regen plans` (last committed plan generation)
- **New plans**: `.methodology/phase{1..8}_plan.md` (v2.12.0, 2026-06-26)
- **Method**: `diff -u /tmp/plan-old/phaseN_plan.md .methodology/phaseN_plan.md`

---

## 1. Plan Diff Summary (harness impact)

Harness submodule went from `0906cb3` to `3f1fd73`. New commits most relevant to plans:

| Harness commit | Effect on plans |
|----------------|-----------------|
| `3f1fd73` fix(p8): align CONFIG_RECORDS template vars + fix P8-ARCHIVE cp source | P8 plan: `cp -r .sessi-work/` → `cp -r .methodology/` (BUG FIX) |
| `50a265d` fix(plan-generator): surface phase8 deterministic baseline in P7/P8 plans | P7 + P8 plans: add auto-trigger note for `phase8_doc_gen.py` |
| `4738542` feat(phase8): deterministic CONFIG_RECORDS + RELEASE_CHECKLIST generator | P8 plan: rewrite CONFIG-RECORDS / RELEASE-CHECKLIST steps (LLM reviews, doesn't generate) |
| `35d341e` test(constitution): remove dead test_main_unknown_command | (test-only, no plan impact) |
| `51bd4a8` fix(review): address 8 findings from post-merge code review (round 2) | P4 + P6: `gate4_result.json` → `quality_manifest.json` for da_waiver + composite score |
| `a830b7e` fix(review): address 3 findings from post-merge code review (#12) | P3 + P4 + P6: readability tool switch `radon mi` → `readability_v2` |
| `abc1a95` fix(audit-structure): accept FR_XX / FRXX / FR(XX) variants in P1-P4 | (no plan impact — runtime parser tolerance) |
| `9958406` fix(audit-structure): align P7 expected artifacts with workflow output | (no plan impact — audit gate) |
| `d95fff6` fix(gate1-fr-scope): prefer fr_module_traceability over import-based scope | (no plan impact — gate logic) |
| `8445e91` fix(plan-all): preserve quality_manifest.json on --force | (plan-all behavior change — does not affect generated plan content) |

### Per-phase diff (lines changed)

| Phase | Diff lines | Semantic change |
|-------|-----------|-----------------|
| P1 | 11 (date only) | None |
| P2 | 11 (date only) | None |
| P3 | 20 | readability tool (`radon mi` → `readability_v2`) |
| P4 | 29 | readability tool + DA-waiver target file |
| P5 | 46 | "BASELINE.md" reorganized into VERIFICATION_REPORT.md (P5 only emits VERIFICATION_REPORT.md now; BASELINE.md no longer required) |
| P6 | 63 | (a) entry check no longer requires BASELINE.md; (b) da_waiver path; (c) readability tool; (d) GIT-TAG score source `gate4_result.json` → `quality_manifest.json`; (e) FINAL_SIGN_OFF / Agent B cross-check drop BASELINE.md reference |
| P7 | 28 | Add "Auto-trigger on P7→P8 advance" note (deterministic generator) |
| P8 | 57 | (a) CONFIG_RECORDS / RELEASE_CHECKLIST now deterministic via `phase8_doc_gen.py` (P8 = review+append); (b) **P8-ARCHIVE bug fix**: `cp -r .sessi-work/` → `cp -r .methodology/` |

---

## 2. Workflow JS audit

For each of the 8 workflow JS files in `.claude/workflows/`, flag whether it needs modification and why.

### `.claude/workflows/phase1-requirements.js`
- Grep hits: none of the impacted patterns
- **Status**: ✅ NO CHANGE NEEDED

### `.claude/workflows/phase2-architecture.js`
- Grep hits: none of the impacted patterns
- **Status**: ✅ NO CHANGE NEEDED

### `.claude/workflows/phase3-implementation.js`
- Grep hits: none for BASELINE.md / radon / gate4_result.json / readability_v2
- **Status**: ✅ NO CHANGE NEEDED (the plan-table mention of `readability_v2` is in the dim-fix table, not in any per-FR step the workflow executes — workflow JS doesn't drive dim fixes directly)

### `.claude/workflows/phase4-testing.js`
- Line 315: lists `radon/ast-error-handling` as a tool that may need re-running; new plan replaces `radon mi` with `readability_v2` as the readability scorer
- **Required edit**:
  - Replace `radon` with `readability_v2` in the failure-fix guidance string
- **Status**: ⚠️ 1-LINE EDIT

### `.claude/workflows/phase5-verification.js`
- Line 5: header comment says "generate BASELINE.md + VERIFICATION_REPORT.md" — new plan only generates VERIFICATION_REPORT.md
- Line 213: `Phase: Verification Docs (BASELINE.md + VERIFICATION_REPORT.md + re-checks)` — header misleading
- Line 216: `log('Generate BASELINE.md + VERIFICATION_REPORT.md; re-run integration + security')` — should drop BASELINE.md
- Line 221: `1. BASELINE: write 05-verification/BASELINE.md ...` — step must be removed (P5 no longer emits BASELINE.md)
- Line 222: VERIFICATION_REPORT step — keep as-is (now the primary deliverable)
- Line 238: `push-milestone p5-baseline (after BASELINE.md generated)` — should say "VERIFICATION_REPORT.md generated"
- Line 282: `artifacts: ['05-verification/BASELINE.md', '05-verification/VERIFICATION_REPORT.md', 'HANDOVER.md']` — drop BASELINE.md
- **Status**: ⚠️ ~5 LINES EDIT (header + step 1 removal + log + artifacts)

### `.claude/workflows/phase6-quality.js`
- Line 121: `EN-TRY-CHECK: confirm ... AND 05-verification/VERIFICATION_REPORT.md + 05-verification/BASELINE.md exist (P5 outputs). Else FAIL.` — new plan drops BASELINE.md requirement
- Line 154: `da_waiver` written to `.sessi-work/gate4_result.json` — STAYS (harness CLI reads da_waiver from gate4_result.json — line 2855 of harness_cli.py); the new P6 plan's `quality_manifest.json` mention is documentation drift, not a code change. Keep as-is.
- Line 191: G4e RELEASE_NOTES reads composite_score from `.sessi-work/gate4_result.json` — should switch to `.methodology/quality_manifest.json` (matches new GIT-TAG pattern; quality_manifest is the persistent source-of-truth)
- Line 192: G4f FINAL_SIGN_OFF `MUST reference 05-verification/BASELINE.md and 05-verification/VERIFICATION_REPORT.md` — drop BASELINE.md
- Line 211: Agent B cross-check `Reference 05-verification/VERIFICATION_REPORT.md + BASELINE.md` — drop BASELINE.md
- Line 235: GIT-TAG `read composite_score from .sessi-work/gate4_result.json` — change to `.methodology/quality_manifest.json` (matches new plan line 270)
- Line 255: `artifacts: [..., '.sessi-work/gate4_result.json', ...]` — replace with `.methodology/quality_manifest.json`
- **Status**: ⚠️ ~5-LINE EDIT (5 sites)

### `.claude/workflows/phase7-risk.js`
- Grep hits: only the existing `advance-phase --completed 7` flow + da_waiver (no architectural change)
- New P7 plan adds an informational note about `phase8_doc_gen.py` auto-trigger on advance — this is a doc-only addition, doesn't change workflow behavior
- **Optional**: add a 1-line log statement noting that `phase8_doc_gen.py` runs automatically in advance-phase (informational; not required for correctness)
- **Status**: ✅ NO MANDATORY CHANGE (optional polish)

### `.claude/workflows/phase8-config.js` — **HIGHEST IMPACT**
- Line 5: header comment "generate CONFIG_RECORDS + RELEASE_CHECKLIST + archive + p8 push" — outdated
- Lines 207-223: **`Config Docs` phase INSTRUCTS AGENT TO WRITE** `08-config/CONFIG_RECORDS.md` and `RELEASE_CHECKLIST.md` from scratch. New plan: these are **deterministically generated** by `scripts/phase8_doc_gen.py` during P7→P8 advance-phase (harness_cli.py line 6016-6030). P8 should REVIEW the framework-generated baseline + APPEND human-only context (ownership, runbook, on-call rotation), not regenerate.
- Line 234: **CRITICAL BUG** — `cp -r ' + REPO + '/.sessi-work/ ' + REPO + '/.methodology-archive/'` — new plan (harness commit `3f1fd73`) says it must be `cp -r .methodology/`. If left as-is, the archive will contain only ephemeral scratch files, missing the actual `.methodology/` audit trail.
- **Required edits**:
  1. Header comment (line 5) — note deterministic baseline
  2. `Config Docs` phase prompt (lines 211-219) — rewrite to:
     - verify the auto-generated baseline exists at `08-config/CONFIG_RECORDS.md` + `RELEASE_CHECKLIST.md`
     - if missing, regenerate via `python3 scripts/phase8_doc_gen.py --project .` (fallback per harness advance-phase behavior)
     - append human-only context (ownership, rotation cadence, runbook, on-call)
     - DO NOT overwrite the deterministic version
  3. `Archive` phase prompt (line 234) — `cp -r` source: `.sessi-work/` → `.methodology/`
- **Status**: 🚨 **CRITICAL** — bug fix + prompt rewrite (~30 lines changed)

---

## 3. Summary — what needs editing

| File | Severity | Lines | Action |
|------|----------|-------|--------|
| phase1-requirements.js | none | 0 | ✅ no change |
| phase2-architecture.js | none | 0 | ✅ no change |
| phase3-implementation.js | none | 0 | ✅ no change |
| phase4-testing.js | low | 1 | `radon` → `readability_v2` |
| phase5-verification.js | medium | ~5 | drop BASELINE.md from P5 (P5 only emits VERIFICATION_REPORT.md now) |
| phase6-quality.js | medium | ~5 | entry check, FINAL_SIGN_OFF, Agent B, GIT-TAG, artifacts — drop BASELINE.md; switch GIT-TAG source to quality_manifest.json |
| phase7-risk.js | none | 0 (optional +1) | ✅ no mandatory change |
| phase8-config.js | **CRITICAL** | ~30 | fix P8-ARCHIVE cp source (`.sessi-work/` → `.methodology/`) + rewrite Config Docs phase as review+append |

**Total estimated diff**: ~41 lines across 4 files.

---

## 4. Open questions / decisions

1. **P6 line 154 (`da_waiver` in `gate4_result.json`)** — keep as-is (matches harness_cli.py code at line 2855) despite new plan text mentioning `quality_manifest.json`? Confirmed via grep: harness reads `g4.get("da_waiver")` where `g4` = gate4_result.json. **Decision: keep gate4_result.json.**
2. **P6 line 191 (RELEASE_NOTES composite_score source)** — new plan only says GIT-TAG uses quality_manifest.json, doesn't explicitly say RELEASE_NOTES. Apply same principle for consistency? **Decision: yes — switch RELEASE_NOTES to quality_manifest.json to match.**
3. **P7 informational log** — add or skip? **Decision: skip — non-mandatory; P7 plan just documents an existing auto-trigger.**

---

## 5. Recommended action order

1. **First**: fix phase8-config.js P8-ARCHIVE bug (harness commit `3f1fd73` explicitly addresses this; without the fix the archive will be empty of audit trail). This is a **silently-broken** invariant — no error, just wrong content.
2. **Second**: rewrite phase8-config.js Config Docs phase to review+append (deterministic baseline).
3. **Third**: apply phase6-quality.js edits (5 sites).
4. **Fourth**: apply phase5-verification.js edits (5 sites).
5. **Fifth**: apply phase4-testing.js 1-line edit.

After edits, run `harness/tests/test_harness_cli.py` (no impact — workflow JS is project-side, not tested by harness) and visual review of each diff.

No new tests required (workflow JS lives in main repo, not in harness tests).
