# Phase 8 Full Execution Plan -- integration-test

> **Version**: v2.12.0 (project plan)
> **Project**: integration-test
> **Date**: 2026-06-24
> **Framework**: harness-methodology v2.12.0
> **Phase**: 8 - Configuration Management
> **Status**: Full version (including Phase 8 detailed tasks)
> **Mode**: Dynamic (load-context at execution time)


> **Hard Rules in Force (this plan)** — explicit reminders:
> - HR-04: HybridWorkflow ON — Agent A authors, a separate Agent B sub-agent reviews. Never role-play A or B yourself.
> - HR-05: harness-methodology wins all conflicts — if a project decision contradicts SKILL.md / INIT / this plan, the harness wins.
> - HR-16: Trace 4a = 100% required (G2/G3/G4 only). `gate_score_overrides` is a **threshold floor (raises, not lowers)** per `sab_parser.derive_gate_score_overrides` — cannot bypass a failing trace dim. Remediation: fix code/FRs to 100%, accept gate block, or escalate to human. No automated override.
> - HR-17: NEVER modify files inside `harness/` — debug the framework, never hot-patch the submodule.

---

## Phase 8 Tasks: Configuration Management

### Phase 8 Overview
Phase 8 establishes a complete configuration management system ensuring traceability.
Each FR gets a Gate 1 config-aware re-evaluation (CHECKPOINT). No harness run-gate — P8 cleared by Gate 4. However, advance-phase still enforces TDD-PRECHECK (gitleaks + ruff + mypy + pytest 100% + D4 spec-coverage ≥90% + mutmut mutation testing) before FSM transition.

> If configuration changes require code modifications to any FR, run full TDD: `run-fr-step --step TDD-RED` → TDD-GREEN → TDD-IMPROVE → GATE1. Crash recovery (`resume-fr-phase`) auto-detects code changes and switches from GATE1-DELTA to full TDD when needed.

> **Crash Recovery**: `python3 harness_cli.py resume-fr-phase --phase 8 --project .`
> prints the next pending step. Each `run-fr-step` auto-pushes to GitHub on completion.
> Per-FR GATE1-DELTA auto-pushes on completion; when code-change triggers full TDD, TDD-RED → GREEN → IMPROVE → GATE1 each push immediately (idempotent on re-run).
> At milestones, `HANDOVER.md` is written with phase/FR/status summary.

> **Checkpoint Index**:
> - MILESTONE: P8 exit push (config records complete) → **HANDOVER.md**

### Entry Gate Verification

- **[ENTRY-CHECK]** Gate 4 PASS (P6 exit — P7 has no exit gate, P7 completed stands between):
  Proof: .methodology/quality_manifest.json records Gate 4 PASS from P6.
  If NOT confirmed: return to Phase 6 and complete exit gate first.

### Pre-Phase Preflight

- **[PREFLIGHT]** Run phase hooks (FSM, Constitution, Kill-Switch, Drift, CI Readiness):
  ```bash
  python3 harness_cli.py run-phase --phase 8 --project .
  ```
  If FAILED: fix FSM/Constitution/Drift issues. There is no gate bypass flag.
  Re-run `run-phase` after each fix. Max 3 attempts.
  After 3 FAIL: escalate to human — provide last `run-phase --phase 8` full output.
  Human fix → re-run `run-phase --phase 8 --project .` → PASS required before continuing.
  **Reliability lint fix** (P4+ blocking — if `preflight_reliability_lint` reports findings):
  Fix flagged patterns before continuing: `subprocess.run/Popen` without `timeout=`,
  `tempfile.mkstemp` outside try/finally, `os.path.exists` before open/unlink (TOCTOU),
  `time.sleep` inside async def. Re-run `run-phase` after each fix.
  **Config liveness fix** (P4+ blocking — if `preflight_config_liveness` reports orphans):
  Env keys read in code but absent from `.env.example`/`docker-compose*.yml`/`deployment/`.
  Add the key to the declaration source (or fix the typo). Re-run `run-phase` after each fix.
  **Attestation fix** (P5+ — if ASPICE Traceability preflight shows `attestation: missing` or `mismatch`):
  ```bash
  python3 harness_cli.py build-trace-attestation --project . --write
  git add .methodology/trace/attestation.json
  git commit -m 'trace: regenerate attestation'
  ```
  Re-run `run-phase` to confirm `Attestation: clean` before continuing.

- **[V2.9.1-B.1-HANDOFF]** Cross-deliverable dependency check (P7 → P8) — v2.9.1 B.1. **Must PASS** before any Phase 8 work begins:
  ```bash
  python3 harness_cli.py validate-handoff --from-phase 7 --project .
  ```
  > Verifies P7 deliverables are present and well-formed (e.g. P1 TEST_INVENTORY.yaml non-empty + covers all FRs; P2 TEST_SPEC.md has parseable named test cases; P3 all FRs have per-FR Gate 1 sentinels; P4 VERIFICATION_REPORT.md non-trivial; P5 BASELINE.md exists; P6 06-quality/QUALITY_REPORT.md + RELEASE_NOTES.md + FINAL_SIGN_OFF.md + .sessi-work/gate4_result.json verdict=PASS; P7 07-risk/RISK_REGISTER.md + RISK_MITIGATION_PLANS.md + RISK_STATUS_REPORT.md).
  > If exit 1: read the error list, fix the upstream deliverable, re-run until exit 0. Do NOT proceed with Phase 8 work on a BLOCKED handoff.

- **[PREFLIGHT-CI]** Confirm CI wiring unchanged (should be set since P1):
  1. `.github/workflows/harness_quality_gate.yml` exists
  2. Git hooks installed (`ls .git/hooks/prepare-commit-msg`)
  3. harness importable (submodule, PYTHONPATH, or vendored `quality_gate/`)
  4. Phase 8 confirmed in `.methodology/state.json` (`advance-phase` already run)
  > If stale: run `python3 harness_cli.py init-project --phase 8 --project . --overwrite`

### 🔄 [PHASE-CONTEXT] — Load Before Starting

```bash
python3 harness_cli.py load-context --phase 8 --project . --json \
  > .sessi-work/phase8_ctx.json
```
> Outputs `fr_ids`, `fr_details`, `modules` from current project state.
> All `{FR-ID}` references in tasks below come from this file.

### FR Tasks — Expanded at Execution Time

- **[ENV-CHECK]** Run ONCE before the FR loop — `GATE1`/`GATE1-DELTA` preflight requires `.sessi-work/env_check_result.json`:
  ```bash
  python3 harness_cli.py run-env-check --phase 8 --project .
  # evaluate inline → write .sessi-work/env_check_result.json →
  python3 harness_cli.py finalize-env-check --phase 8 --project .
  ```
  > Without this, every `run-fr-step --step GATE1-DELTA` blocks on 'env_check_result.json not found'.

> Read `fr_ids` from `.sessi-work/phase8_ctx.json`.
> For each `{FR-ID}` in the list, execute the template below:

---
**{FR-ID} — {FR-TITLE from fr_details}**

- **[ORCH-GATE1-DELTA]** `run-fr-step --phase 8 --fr-id {FR-ID} --step GATE1-DELTA --project .`
> Crash recovery: `resume-fr-phase` auto-detects code changes → switches to full TDD if needed.
> **Auto-skip**: if NO FR's code changed since its last Gate 1 PASS, `advance-phase --completed 8`
> treats this entire DELTA loop as satisfied automatically — you may skip the per-FR steps.
> Only FRs whose code actually changed need a re-evaluation.
>
> **GATE1-DELTA outcomes:**
> - CASE 1 PASS:    Gate 1 PASS → continue to next {FR-ID}
> - CASE 2 FAIL:    Gate 1 FAIL → full TDD auto-triggered by crash recovery:
>   `run-fr-step --phase 8 --fr-id {FR-ID} --step TDD-RED` → TDD-GREEN → TDD-IMPROVE → GATE1
> - CASE 3 BLOCKED: 3 TDD rounds still failing → escalate to human.
>   Provide: last Gate 1 output + pytest failure log.

---

### P8 Configuration Records Generation

> Generate config deliverables ONCE before push-milestone (orchestrator runs directly).

- **[CONFIG-RECORDS]** Generate `CONFIG_RECORDS.md` in `08-config/` directory:
  - Review all env vars, secrets, feature flags, and deployment settings
  - For each config item: name, value/source, access method, owner, environment (dev/staging/prod)
  - Reference: `03-development/src/` module configs + any `.env.example` or `settings.py`
- **[RELEASE-CHECKLIST]** Generate `RELEASE_CHECKLIST.md` in `08-config/` directory:
  - Pre-release: all Gate 4 dims PASS, no open critical issues, security scan clean
  - Deployment: env vars set, secrets rotated, DB migrations run, smoke tests pass
  - Post-release: monitoring alerts configured, rollback plan documented

### P8 Archive — REQUIRED before push-milestone (CI p8-archive-check)

- **[P8-ARCHIVE]** Create `.methodology-archive/` directory (required for CI `p8-archive-check`):
  ```bash
  mkdir -p .methodology-archive
  cp -r .sessi-work/ .methodology-archive/
  ```
  > Must run BEFORE `push-milestone --type p8`; `_validate_p8_completion()` in push-milestone auto-verifies.
  > CI job `p8-archive-check` also validates this directory on push to main.

- **[P8-HANDOVER-CHECK]** Verify `HANDOVER.md` has no Phase 9 references (validated by CI `p8-archive-check`):
  ```bash
  grep -qi "phase 9\|phase9\|phase9_plan" HANDOVER.md \
    && echo "ERROR: Phase 9 refs found — remove them" \
    || echo "OK: no Phase 9 refs"
  ```
  Phase 8 is the final phase. Any Phase 9 references must be removed.

### P8 Milestone Push (10-Push Strategy ⑩)

- **PUSH ⑩ — P8 exit** (after config records are complete):
  ```bash
  python3 harness_cli.py push-milestone --type p8 --project .
  ```
  > Writes HANDOVER.md + commits + pushes. Pipeline complete.

### Phase 8 Deliverables
- `CONFIG_RECORDS.md` - Configuration records
- `RELEASE_CHECKLIST.md` - Release checklist
- [x] `.methodology/sessions_spawn.log` — auto-populated by AgentSpawner (non-blocking debug trail)
- Gate 1 PASS for every FR

- **[PHASE-TRUTH]** Phase Truth ≥ 90% (HR-11) — verified by advance-phase

- **[TDD-PRECHECK]** P8 completion checklist (final quality gate before archive):
  - secrets scanning: `gitleaks detect --source .` (exit 20) — whole-repo, runs before linting
  - linting: `ruff check .` (exit 18) — fix violations before advancing
  - type safety: `python3 -m mypy . --ignore-missing-imports` (exit 19)
  - `pytest --tb=short -q --cov=03-development/src --cov-fail-under=100` (exit 9)
  - `python3 harness_cli.py spec-coverage-check --project . --threshold 90.0` (exit 10, D4 unified v2.6)
  > For genuinely untestable lines add: `# pragma: no cover` (requires justification comment).

### 🎉 Pipeline Complete

- All 8 phases complete. Archive `.methodology/` for the audit trail.
