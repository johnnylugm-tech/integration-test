# Phase 3 Full Execution Plan -- integration-test

> **Version**: v2.12.0 (project plan)
> **Project**: integration-test
> **Date**: 2026-06-29
> **Framework**: harness-methodology v2.12.0
> **Phase**: 3 - Implementation
> **Status**: Full version (including Phase 3 detailed tasks)

> **Hard Rules in Force (this plan)** — explicit reminders:
> - HR-04: HybridWorkflow ON — Agent A authors, a separate Agent B sub-agent reviews. Never role-play A or B yourself.
> - HR-05: harness-methodology wins all conflicts — if a project decision contradicts SKILL.md / INIT / this plan, the harness wins.
> - HR-16: Trace 4a = 100% required (G2/G3/G4 only). `gate_score_overrides` is a **threshold floor (raises, not lowers)** per `sab_parser.derive_gate_score_overrides` — cannot bypass a failing trace dim. Remediation: fix code/FRs to 100%, accept gate block, or escalate to human. No automated override.
> - HR-17: NEVER modify files inside `harness/` — debug the framework, never hot-patch the submodule.

---

## Phase 3 Tasks: Implementation

### Phase 3 Overview
Phase 3 implements all FR modules according to SAD, including unit tests.
Each FR ends with a Gate 1 quality evaluation (CHECKPOINT). Phase exits via Gate 2.

> **Crash Recovery**: `python3 harness_cli.py resume-fr-phase --phase 3 --project .`
> prints the next pending step. Each `run-fr-step` auto-pushes to GitHub on completion.
> Per-FR TDD-RED/GREEN/IMPROVE/GATE1 each push immediately (idempotent on re-run).
> At milestones, `HANDOVER.md` is written with phase/FR/status summary.

> **Checkpoint Index**:
> - CHECKPOINT-1: Gate 1 / FR-01 *(auto-push via run-fr-step)*
> - CHECKPOINT-2: Gate 1 / FR-02 *(auto-push via run-fr-step)*
> - CHECKPOINT-3: Gate 1 / FR-03 *(auto-push via run-fr-step)*
> - MILESTONE: P3-mid push (≥50% FRs Gate 1 PASS) → **HANDOVER.md**
> - MILESTONE: P3-pre-gate2 push (all FRs done) → **HANDOVER.md**
> - CHECKPOINT-GATE-2: Gate 2 (Phase 3 Exit) → **push + HANDOVER.md**

### Entry Gate Verification

- **[ENTRY-CHECK]** P2 review-complete:
  Proof: git log contains commit 'phase2(review-complete): Phase 2 deliverables APPROVED'.
  If NOT confirmed: return to Phase 2 and complete exit gate first.

- **[P2-ARTIFACTS]** Verify Phase 2 output artifacts exist:
  ```bash
  ls -la 02-architecture/SAD.md 02-architecture/adr/ADR.md 02-architecture/TEST_SPEC.md \
     .methodology/quality_manifest.json .methodology/SAB.json
  git log --oneline --grep="APPROVE" -1
  ```
  If any file missing: return to Phase 2 and complete missing deliverables.

### Pre-Phase Preflight

- **[PREFLIGHT]** Run phase hooks (FSM, Constitution, Kill-Switch, Drift, CI Readiness):
  ```bash
  python3 harness_cli.py run-phase --phase 3 --project .
  ```
  If FAILED: fix FSM/Constitution/Drift issues. There is no gate bypass flag.
  Re-run `run-phase` after each fix. Max 3 attempts.
  After 3 FAIL: escalate to human — provide last `run-phase --phase 3` full output.
  Human fix → re-run `run-phase --phase 3 --project .` → PASS required before continuing.

- **[V2.9.1-B.1-HANDOFF]** Cross-deliverable dependency check (P2 → P3) — v2.9.1 B.1. **Must PASS** before any Phase 3 work begins:
  ```bash
  python3 harness_cli.py validate-handoff --from-phase 2 --project .
  ```
  > Verifies P2 deliverables are present and well-formed (e.g. P1 TEST_INVENTORY.yaml non-empty + covers all FRs; P2 TEST_SPEC.md has parseable named test cases; P3 all FRs have per-FR Gate 1 sentinels; P4 TEST_RESULTS.md non-trivial; P5 VERIFICATION_REPORT.md non-trivial; P6 06-quality/QUALITY_REPORT.md + RELEASE_NOTES.md + FINAL_SIGN_OFF.md + .methodology/quality_manifest.json gate_results.gate4.quality_complete=true; P7 07-risk/RISK_REGISTER.md + RISK_MITIGATION_PLANS.md + RISK_STATUS_REPORT.md).
  > If exit 1: read the error list, fix the upstream deliverable, re-run until exit 0. Do NOT proceed with Phase 3 work on a BLOCKED handoff.

- **[PREFLIGHT-CI]** Confirm CI wiring unchanged (should be set since P1):
  1. `.github/workflows/harness_quality_gate.yml` exists
  2. Git hooks installed (`ls .git/hooks/prepare-commit-msg`)
  3. harness importable (submodule, PYTHONPATH, or vendored `quality_gate/`)
  4. Phase 3 confirmed in `.methodology/state.json` (`advance-phase` already run)
  > If stale: run `python3 harness_cli.py init-project --phase 3 --project . --overwrite`

### FR Implementation Tasks (3 total)

#### FR-01: 任務模型與持久化 (Task model and persistence)
**Task**: 
**Forbidden**:
- app/infrastructure/ (deprecated)
- @covers: L1 Error
- @type: edge

**TDD — FR-01** (Orchestrator dispatches sub-agents · push after each step):

- **[ORCH-RED]** Dispatch TDD-RED sub-agent for FR-01:
  ```bash
  python3 harness_cli.py run-fr-step --phase 3 --fr-id FR-01 --step TDD-RED \
    --project . --srs 01-requirements/SRS.md
  ```
  → Verify: `git log --oneline -1` shows `test(RED): failing test for FR-01`
  → GitHub push: ✅ auto-done by run-fr-step

- **[P3-MIRROR]** Verify the RED test mirrors TEST_SPEC.md (P3 only implements — correctness was locked in P2; on FAIL fix the TEST, not TEST_SPEC):
  ```bash
  python3 harness_cli.py check-test-mirrors-spec --project . --fr-id FR-01 \
    --test-file tests/test_fr01.py
  ```
  → trigger_mismatch / assertion_missing / param drift = test diverged from spec.

- **[ORCH-GREEN]** Dispatch TDD-GREEN sub-agent for FR-01:
  ```bash
  python3 harness_cli.py run-fr-step --phase 3 --fr-id FR-01 --step TDD-GREEN \
    --project . --srs 01-requirements/SRS.md
  ```
  → Verify: `pytest tests/test_fr01.py -q` all pass
  → GitHub push: ✅ auto-done by run-fr-step

- **[ORCH-IMPROVE]** Dispatch TDD-IMPROVE sub-agent for FR-01:
  ```bash
  python3 harness_cli.py run-fr-step --phase 3 --fr-id FR-01 --step TDD-IMPROVE \
    --project .
  ```
  → Verify: `pytest tests/test_fr01.py -q` still pass
  → GitHub push: ✅ auto-done by run-fr-step

- **[ORCH-GATE1]** Dispatch GATE1 evaluator sub-agent for FR-01:
  ```bash
  python3 harness_cli.py run-fr-step --phase 3 --fr-id FR-01 --step GATE1 \
    --project .
  ```
  → Verify: `git log --oneline -1` shows `feat(FR-01): Gate1 PASS`
  → GitHub push: ✅ auto-done by run-fr-step
  → GATE1 FAIL: auto-dispatches CODE-FIX sub-agent → retries (max 3 rounds)
  → exit 2 = BLOCKED: human intervention required before continuing
  → Human fix → re-run `run-fr-step --step GATE1 --fr-id FR-01` → exit 0 required before continuing.

- **[ORCH-POST]** After GATE1 PASS — orchestrator runs directly:
  ```bash
  python3 harness_cli.py spec-coverage-check --project . --threshold 40.0 --fr-id FR-01
  python3 harness/scripts/generate_sab.py --project .
  # Note: if SAB.json exists, append --overwrite to regenerate
  ```

> 💡 **Crash recovery**: `python3 harness_cli.py resume-fr-phase --phase 3 --project .`
> prints the next pending step (idempotent on re-run).

#### FR-02: 任務執行與重試 (Task execution and retry)
**Task**: 
**Forbidden**:
- app/infrastructure/ (deprecated)
- @covers: L1 Error
- @type: edge

**TDD — FR-02** (Orchestrator dispatches sub-agents · push after each step):

- **[ORCH-RED]** Dispatch TDD-RED sub-agent for FR-02:
  ```bash
  python3 harness_cli.py run-fr-step --phase 3 --fr-id FR-02 --step TDD-RED \
    --project . --srs 01-requirements/SRS.md
  ```
  → Verify: `git log --oneline -1` shows `test(RED): failing test for FR-02`
  → GitHub push: ✅ auto-done by run-fr-step

- **[P3-MIRROR]** Verify the RED test mirrors TEST_SPEC.md (P3 only implements — correctness was locked in P2; on FAIL fix the TEST, not TEST_SPEC):
  ```bash
  python3 harness_cli.py check-test-mirrors-spec --project . --fr-id FR-02 \
    --test-file tests/test_fr02.py
  ```
  → trigger_mismatch / assertion_missing / param drift = test diverged from spec.

- **[ORCH-GREEN]** Dispatch TDD-GREEN sub-agent for FR-02:
  ```bash
  python3 harness_cli.py run-fr-step --phase 3 --fr-id FR-02 --step TDD-GREEN \
    --project . --srs 01-requirements/SRS.md
  ```
  → Verify: `pytest tests/test_fr02.py -q` all pass
  → GitHub push: ✅ auto-done by run-fr-step

- **[ORCH-IMPROVE]** Dispatch TDD-IMPROVE sub-agent for FR-02:
  ```bash
  python3 harness_cli.py run-fr-step --phase 3 --fr-id FR-02 --step TDD-IMPROVE \
    --project .
  ```
  → Verify: `pytest tests/test_fr02.py -q` still pass
  → GitHub push: ✅ auto-done by run-fr-step

- **[ORCH-GATE1]** Dispatch GATE1 evaluator sub-agent for FR-02:
  ```bash
  python3 harness_cli.py run-fr-step --phase 3 --fr-id FR-02 --step GATE1 \
    --project .
  ```
  → Verify: `git log --oneline -1` shows `feat(FR-02): Gate1 PASS`
  → GitHub push: ✅ auto-done by run-fr-step
  → GATE1 FAIL: auto-dispatches CODE-FIX sub-agent → retries (max 3 rounds)
  → exit 2 = BLOCKED: human intervention required before continuing
  → Human fix → re-run `run-fr-step --step GATE1 --fr-id FR-02` → exit 0 required before continuing.

- **[ORCH-POST]** After GATE1 PASS — orchestrator runs directly:
  ```bash
  python3 harness_cli.py spec-coverage-check --project . --threshold 40.0 --fr-id FR-02
  python3 harness/scripts/generate_sab.py --project .
  # Note: if SAB.json exists, append --overwrite to regenerate
  ```

> 💡 **Crash recovery**: `python3 harness_cli.py resume-fr-phase --phase 3 --project .`
> prints the next pending step (idempotent on re-run).

#### FR-03: CLI 整合與查詢 (CLI integration and query)
**Task**: 
**Forbidden**:
- app/infrastructure/ (deprecated)
- @covers: L1 Error
- @type: edge

**TDD — FR-03** (Orchestrator dispatches sub-agents · push after each step):

- **[ORCH-RED]** Dispatch TDD-RED sub-agent for FR-03:
  ```bash
  python3 harness_cli.py run-fr-step --phase 3 --fr-id FR-03 --step TDD-RED \
    --project . --srs 01-requirements/SRS.md
  ```
  → Verify: `git log --oneline -1` shows `test(RED): failing test for FR-03`
  → GitHub push: ✅ auto-done by run-fr-step

- **[P3-MIRROR]** Verify the RED test mirrors TEST_SPEC.md (P3 only implements — correctness was locked in P2; on FAIL fix the TEST, not TEST_SPEC):
  ```bash
  python3 harness_cli.py check-test-mirrors-spec --project . --fr-id FR-03 \
    --test-file tests/test_fr03.py
  ```
  → trigger_mismatch / assertion_missing / param drift = test diverged from spec.

- **[ORCH-GREEN]** Dispatch TDD-GREEN sub-agent for FR-03:
  ```bash
  python3 harness_cli.py run-fr-step --phase 3 --fr-id FR-03 --step TDD-GREEN \
    --project . --srs 01-requirements/SRS.md
  ```
  → Verify: `pytest tests/test_fr03.py -q` all pass
  → GitHub push: ✅ auto-done by run-fr-step

- **[ORCH-IMPROVE]** Dispatch TDD-IMPROVE sub-agent for FR-03:
  ```bash
  python3 harness_cli.py run-fr-step --phase 3 --fr-id FR-03 --step TDD-IMPROVE \
    --project .
  ```
  → Verify: `pytest tests/test_fr03.py -q` still pass
  → GitHub push: ✅ auto-done by run-fr-step

- **[ORCH-GATE1]** Dispatch GATE1 evaluator sub-agent for FR-03:
  ```bash
  python3 harness_cli.py run-fr-step --phase 3 --fr-id FR-03 --step GATE1 \
    --project .
  ```
  → Verify: `git log --oneline -1` shows `feat(FR-03): Gate1 PASS`
  → GitHub push: ✅ auto-done by run-fr-step
  → GATE1 FAIL: auto-dispatches CODE-FIX sub-agent → retries (max 3 rounds)
  → exit 2 = BLOCKED: human intervention required before continuing
  → Human fix → re-run `run-fr-step --step GATE1 --fr-id FR-03` → exit 0 required before continuing.

- **[ORCH-POST]** After GATE1 PASS — orchestrator runs directly:
  ```bash
  python3 harness_cli.py spec-coverage-check --project . --threshold 40.0 --fr-id FR-03
  python3 harness/scripts/generate_sab.py --project .
  # Note: if SAB.json exists, append --overwrite to regenerate
  ```

> 💡 **Crash recovery**: `python3 harness_cli.py resume-fr-phase --phase 3 --project .`
> prints the next pending step (idempotent on re-run).

### NFR Coverage (3 total)

> NFRs are implemented **within FRs** — each FR satisfies one or more NFRs.
> Verify NFR compliance via Gate 2/3 tool-scored dimensions, not separate tasks.

| NFR | Type | FRs Implementing |
|-----|------|-----------------|
| NFR-01 | 1 (1.a) | — |
| NFR-02 | 2 (2.a–b) | — |
| NFR-03 | 2 (3.a–b) | — |

> ⚠️ **NFR→FR mapping not found** — `—` entries above indicate no `NFR Association`
> column was detected in SRS.md FR tables. To enable auto-mapping, add an
> `NFR Association` column to each FR row in `01-requirements/SRS.md §2`.

**Gate 2 NFR dimensions** (tool-scored, see Gate 2 config):
- `security` (bandit), `secrets_scanning` (gitleaks), `mutation_testing` (mutmut 2.x — `pip install 'mutmut<3'`)
- `integration_coverage` (pytest), `test_assertion_quality` (pytest)

### P3 Milestone Pushes (10-Push Strategy ③④⑤)

> Per-FR steps push automatically via `run-fr-step`. The milestone pushes below
> also write `HANDOVER.md` with phase/FR/status summary and push to origin.
> All FR IDs in this project: FR-01,FR-02,FR-03

- **PUSH ③ — P3-mid** (trigger when ≥1/3 FRs have Gate 1 PASS):
  ```bash
  python3 harness_cli.py push-milestone --type p3-mid --project . \
    --fr-done 1 --fr-total 3 --fr-ids FR-01
  ```
  > `--fr-ids` lists the FRs with Gate 1 PASS so far. Replace `FR-01` with actual.
  > Writes HANDOVER.md + commits + pushes. Next session reads HANDOVER.md to resume.

- **PUSH ④ — P3-pre-gate2** (trigger when all 3 FRs Gate 1 PASS, before Gate 2):
  ```bash
  python3 harness_cli.py push-milestone --type p3-pre-gate2 --project . \
    --fr-ids FR-01,FR-02,FR-03
  ```
  > Last stable snapshot before Gate 2 evaluation. HANDOVER.md + push.

- **PUSH ⑤ — P3-post-gate2** (trigger when Gate 2 PASSes, all 3 FRs Gate 1 PASS — formal P3 exit):
  ```bash
  python3 harness_cli.py push-milestone --type p3-post-gate2 --project . \
    --fr-ids FR-01,FR-02,FR-03
  ```
  > **v2.9.1 B.2** -- replaces label-only `chore(P3-exit): ...` commits.
  > Pre-flight (enforced) checks:
  >   1. `.methodology/gate2_result.json` composite ≥ phase threshold
  >   2. Per-FR Gate 1 sentinel `.sessi-work/sentinels/g1_<fr>.flag` exists for every FR in `--fr-ids`
  > If either fails the push is BLOCKED with a clear error list (exit 1).
  > On success: writes HANDOVER.md with `resume_phase=4` + commits + pushes.


### 🔒 CHECKPOINT-GATE-2: Phase 3 Exit
> linting(90) · type_safety(85) · test_coverage(80) · security(80) · secrets_scanning(100) · license_compliance(100) · integration_coverage(60) · test_assertion_quality(60) · traceability(100) · composite ≥ 75  [traceability: framework-owned, harness-computed · D4 spec-coverage unified ≥60%]
> HR-08: Phase end requires Quality Gate pass — never advance past a failing gate (max 3 retry rounds, then escalate).
> _Design note_: HR-08 only appears in P3-P6 (Gate 2/3/4 exits). P5/P7/P8 have no gate-exit checkpoint so HR-08 is correctly absent from those plans.

- **G2a** Prepare Gate 2:
  ```bash
  python3 harness_cli.py run-gate --gate 2 --phase 3 --project .
  ```
  Read the evaluation prompt printed above.

- **G2b** Evaluate all Gate 2 dimensions inline:
  - Follow `harness/ssi/prompts/evaluate_dimension.md`
  - Write result to `.sessi-work/gate2_result.json`
  - Failing dim: fix code → re-evaluate → re-score
  > Failing dims: fix the root cause in code, then re-evaluate → re-score.
  > (Auto-fix engine is NOT wired — fixes require manual code changes or targeted tools.)
  > **traceability** is framework-owned: the harness calls `compute_trace_dimension()`
  > inside `finalize-gate` and injects the score automatically. Do NOT report a traceability
  > score in gate_result.json. If the gate is blocked by traceability, fix gaps then run:
  > `python3 harness_cli.py build-trace-attestation --project . --write`
  > `git add .methodology/trace/attestation.json && git commit -m 'trace: regen attestation'`

- **G2c** Finalize Gate 2:
  ```bash
  python3 harness_cli.py finalize-gate --gate 2 --phase 3 --project .
  ```
- **[D4]** D4 spec-coverage-check — unified v2.6 (Gate 2 threshold 60%):
  ```bash
  python3 harness_cli.py spec-coverage-check --project . --threshold 60.0
  ```
  FAIL → fix missing test implementations → re-run until coverage meets threshold

  **Early-stop cases after G2c:**
  - CASE 1 PASS:     score ≥ score_gate AND all dims ≥ threshold → `quality_complete=True` → G2d
  - CASE 2 REJECT:   score ≥ score_gate BUT ≤2 dims below threshold → fix below → retry loop
  - CASE 3 BLOCKED:  score < score_gate OR >2 dims below threshold → fix below → retry loop
  - CASE 4 PLATEAU:  3 consecutive rounds, no score improvement → `deferred_fixes.md` → escalate to human
  - CASE 5 ABORT:    max_rounds exhausted → escalate to human

### 🔄 REJECT LOOP — Gate 2 dim(s) below threshold

> `finalize-gate` prints the failing dims with their scores and gaps.
> Read the output CAREFULLY — it tells you exactly what to fix.

**General fix strategies by dimension:**
| Dimension | Fix |
|-----------|-----|
| mutation_testing | Framework-owned score: `python3 harness_cli.py mutation-test-score --project .` runs `compute_mutation_score()` (harness-managed workdir + setup.cfg rewrite + sqlite cache parse). To investigate surviving mutants manually: `mutmut results` (legacy). Exclude data-only files (constants, dicts, Pydantic models) via `paths_to_exclude` in setup.cfg. Target: kill rate ≥ threshold. |
| architecture (G3/G4 only) | Community cohesion low → add cross-module integration tests, break hub-and-spoke coupling, or file a DA waiver if the pattern is intentional (Orchestrator). |
| error_handling | (1) **Presence**: add try/except blocks. `grep -r 'try:' 03-development/src/` to see coverage. (2) **Anti-patterns** (v2.9 A1, −5 each): remove `except BaseException:` (flagged even with re-raise), bare `except:` without re-raise, `except Exception: pass`. Run `python3 harness_cli.py run-tool ast-error-handling --project .` to see exact deductions. |
| documentation | Add docstrings to public functions/classes. `python3 -m ast_docstrings` or manual: every `def`/`class` in `03-development/src/` needs a docstring. |
| readability | Refactor complex functions (readability_v2 < 65). Run `python3 -m harness.toolchains.readability_v2 03-development/src/` to see scores per file. |
| performance | Add pytest-benchmark tests. Create `tests/test_perf.py` with `def test_latency(benchmark): ...` |
| test_assertion_quality | Add `assert` statements to test functions. Every test must have ≥1 substantive assertion. |
| integration_coverage | Add integration tests in `03-development/tests/integration/` that exercise end-to-end flows. |
| security | Fix bandit HIGH/MEDIUM issues. Run `bandit -r 03-development/src/ -f json` to see them. |
| linting | Run `ruff check .` — fix violations. |
| type_safety | Run `pyright . --outputjson` — fix errorCount > 0. |
| test_coverage | Add tests to cover uncovered lines. Run `pytest --cov=03-development/src --cov-report=term-missing` |
| secrets_scanning | Remove committed secrets. Run `gitleaks detect --source .` |
| license_compliance | Replace non-MIT dependencies. Run `pip-licenses` to audit. |

**Retry workflow:**
1. Read the failing dims from `finalize-gate` output above
2. Fix the ROOT CAUSE in code (NOT by editing gate_result.json)
3. Re-run the tool for each fixed dim to confirm the score change
4. Update `.sessi-work/gate{gate_num}_result.json` with new scores
5. Re-run: `python3 harness_cli.py finalize-gate --gate 2 --phase 3 --project .`
6. Repeat until CASE 1 PASS or 9 fix rounds exhausted
7. If stuck after 3 rounds: write `.methodology/deferred_fixes.md` with each remaining dim as a checkbox item ('- [ ] <dim>: <reason>'); every item MUST be resolved and marked '- [x]' before advance-phase (hard-blocked, exit 17, otherwise), then escalate


- **G2d** ✅ Verify checkpoint saved (finalize-gate above already pushed + wrote HANDOVER.md):
  ```bash
  # Confirm HANDOVER.md exists at project root (written by finalize-gate → commit_and_push_gate)
  ls -la HANDOVER.md
  git log --oneline -1
  ```
  > `finalize-gate --gate 2` (G2c) calls `commit_and_push_gate()` which writes
  > `HANDOVER.md` **before** committing + pushing. No separate push needed here.
  > If HANDOVER.md is missing, re-run `finalize-gate` (do **not** raw-push).

- **[PHASE-TRUTH]** Phase Truth ≥ 90% (HR-11) — verified by advance-phase
  > **FAIL** → check `phase_truth_verifier` output in `.sessi-work/`
  >   → identify which phase link or gate artifact failed
  >   → fix artifacts → re-run `advance-phase`
  >   → If 3 consecutive failures: escalate to human with `phase_truth_verifier` log

### Phase 3 Deliverables
- `03-development/src/` - All FR modules implemented
- `tests/` - Unit tests (≥80% coverage per FR)
- [x] `.methodology/sessions_spawn.log` — auto-populated by AgentSpawner (non-blocking debug trail)
- Gate 1 PASS for every FR
- Gate 2 PASS (phase exit, composite ≥ 75)

### Phase 3 → Phase 4: Testing

- Generate Phase 4 plan:
  ```bash
  python3 harness_cli.py plan-phase --phase 4 --project . \
    --output .methodology/phase4_plan.md
  ```
- **[TDD-PRECHECK]** Verify TDD checks pass — advance-phase enforces:
  - secrets scanning: `gitleaks detect --source .` (exit 20) — whole-repo, runs before linting
  - linting: `ruff check .` (exit 18) — fix violations before advancing
  - type safety: `python3 -m mypy . --ignore-missing-imports` (exit 19)
    > Note: advance-phase uses mypy; Gate scoring uses pyright. Both must pass.
  - `pytest --tb=short -q --cov=03-development/src --cov-fail-under=100` (exit 9)
  - `python3 harness_cli.py spec-coverage-check --project . --threshold 60.0` (exit 10, D4 unified v2.6)
  > For genuinely untestable lines add: `# pragma: no cover` (requires justification comment).

- Advance FSM to Phase 4 (writes new HANDOVER.md + local commit):
  ```bash
  python3 harness_cli.py advance-phase --completed 3 --project .
  ```
  > **Note**: `advance-phase` will automatically check for harness submodule drift.
  > If it prints a warning that you are behind `origin/main`, it is non-blocking and for your information only.
- Confirm `HANDOVER.md` reflects Phase 4 entry (`P4-entry` checkpoint, correct plan path)
- Open `phase4_plan.md` and follow from the top.
- If session crashes during Phase 4: read `HANDOVER.md` or run `generate-next-plan`
