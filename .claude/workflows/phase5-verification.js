// Phase 5 — Verification & Delivery (faithful to .methodology/phase5_plan.md v2.12.0)
//
// Structure: FR-loop型, NO harness run-gate (P5 cleared by Gate 3 at P4 exit).
// Per-FR GATE1-DELTA re-eval (auto-triggers full TDD on code change), then
// generate BASELINE.md + VERIFICATION_REPORT.md, p5-baseline milestone push,
// advance (advance-phase still enforces TDD-PRECHECK + D4 ≥80%, and Gate 4
// next phase needs ≥90% so we warn-check here).
//
// Playbook lessons: NO import/fs/process/schema:, Bash CLI, SCOPE RULES,
// PY = .venv/bin/python, scriptPath launch.

export const meta = {
  name: 'phase5-verification',
  description: 'Phase 5 Verification — per-FR GATE1-DELTA + BASELINE/VERIFICATION_REPORT + p5-baseline push (phase5_plan.md v2.12.0)',
  phases: [
    { title: 'Entry & Preflight' },
    { title: 'Env Check' },
    { title: 'Load FRs' },
    { title: 'Per-FR Delta' },
    { title: 'Verification Docs' },
    { title: 'Milestone' },
    { title: 'Advance' },
  ],
}

// ---- args / REPO / PY ----
const DEFAULT_REPO = '/Users/johnny/projects/integration-test'
let REPO = DEFAULT_REPO
if (typeof args === 'string') { try { args = JSON.parse(args) } catch {} }
if (args && typeof args === 'object' && typeof args.repo === 'string' && args.repo.length > 0) REPO = args.repo
const PY = REPO + '/.venv/bin/python'
log('REPO = ' + REPO + ' | PY = ' + PY)

// ---- JSON parsing (balanced-brace; playbook §5.2) ----
function balancedJsonAt(text, start) {
  if (text[start] !== '{' && text[start] !== '[') return null
  let depth = 0, inStr = false, esc = false
  for (let i = start; i < text.length; i++) {
    const c = text[i]
    if (esc) { esc = false; continue }
    if (c === '\\') { esc = true; continue }
    if (c === '"') { inStr = !inStr; continue }
    if (inStr) continue
    if (c === '{' || c === '[') depth++
    else if (c === '}' || c === ']') { depth--; if (depth === 0) return text.slice(start, i + 1) }
  }
  return null
}
function extractLastJson(text) {
  if (typeof text !== 'string') return null
  let last = null
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '{' || text[i] === '[') {
      const block = balancedJsonAt(text, i)
      if (block) { try { last = JSON.parse(block); i += block.length - 1 } catch {} }
    }
  }
  return last
}
function parseAgentJson(text, label) {
  const parsed = extractLastJson(text)
  if (parsed !== null) return parsed
  throw new Error('PARSE_FAIL [' + label + ']: no balanced JSON. tail=' + (text ?? '').toString().slice(-200))
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Entry & Preflight (incl. attestation fix per P5+ ASPICE)
// ════════════════════════════════════════════════════════════════════════
phase('Entry & Preflight')
log('ENTRY-CHECK Gate3 + run-phase 5 (reliability/config/attestation fixes) + handoff + CI')
const preflightReport = await agent(
  'YOU ARE THE PHASE-5 PREFLIGHT ORCHESTRATOR. Run bash in order; report.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. ENTRY-CHECK: confirm .methodology/quality_manifest.json records Gate 3 PASS from P4 (else FAIL → return to Phase 4).\n'
  + '2. PREFLIGHT: `' + PY + ' ' + REPO + '/harness_cli.py run-phase --phase 5 --project ' + REPO + '`. FAIL → fix, re-run (max 3). Also fix if reported:\n'
  + '   - reliability lint: subprocess without timeout=, mkstemp outside try/finally, os.path.exists-before-open (TOCTOU), time.sleep in async def.\n'
  + '   - config liveness: env keys read in code but absent from .env.example.\n'
  + '   - attestation missing/mismatch: `' + PY + ' ' + REPO + '/harness_cli.py build-trace-attestation --project ' + REPO + ' --write` then commit .methodology/trace/attestation.json; re-run run-phase until "Attestation: clean".\n'
  + '3. HANDOFF: `' + PY + ' ' + REPO + '/harness_cli.py validate-handoff --from-phase 4 --project ' + REPO + '`. Must exit 0.\n'
  + '4. PREFLIGHT-CI: harness_quality_gate.yml + prepare-commit-msg exist; state.json current_phase=5. If stale: init-project --phase 5 --overwrite.\n\n'
  + 'Report: "PREFLIGHT: PASS" or "PREFLIGHT: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT generate BASELINE/VERIFICATION docs or run TDD steps.\n- DO NOT run advance-phase/push-milestone.\n- DO NOT modify harness/.\n- ONLY preflight commands + fixes.',
  { label: 'preflight', phase: 'Entry & Preflight', agentType: 'general-purpose' },
)
if (!(typeof preflightReport === 'string' && /PREFLIGHT:\s*PASS/.test(preflightReport))) {
  return { error: 'Phase 5 preflight did not PASS', raw: String(preflightReport ?? '').slice(-600) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Env Check
// ════════════════════════════════════════════════════════════════════════
phase('Env Check')
log('run-env-check + finalize-env-check (GATE1-DELTA preflight needs env_check_result.json)')
const envReport = await agent(
  'YOU ARE THE ENV-CHECK ORCHESTRATOR. Run ONCE before the FR loop.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. `' + PY + ' ' + REPO + '/harness_cli.py run-env-check --phase 5 --project ' + REPO + '` — read the printed prompt.\n'
  + '2. Evaluate inline and write ' + REPO + '/.sessi-work/env_check_result.json.\n'
  + '3. `' + PY + ' ' + REPO + '/harness_cli.py finalize-env-check --phase 5 --project ' + REPO + '`.\n\n'
  + 'Report: "ENV-CHECK: PASS" or "ENV-CHECK: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run TDD/advance/milestone commands.\n- ONLY env-check.',
  { label: 'env-check', phase: 'Env Check', agentType: 'general-purpose' },
)
if (!(typeof envReport === 'string' && /ENV-CHECK:\s*PASS/.test(envReport))) {
  return { error: 'Phase 5 env-check did not PASS', raw: String(envReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Load FRs
// ════════════════════════════════════════════════════════════════════════
phase('Load FRs')
log('load-context --phase 5 → fr_ids')
const ctxResult = await agent(
  'Use ONLY the Bash tool. Run:\n'
  + '1. `mkdir -p ' + REPO + '/.sessi-work`\n'
  + '2. `' + PY + ' ' + REPO + '/harness_cli.py load-context --phase 5 --project ' + REPO + ' --json > ' + REPO + '/.sessi-work/phase5_ctx.json`\n'
  + '3. `cat ' + REPO + '/.sessi-work/phase5_ctx.json`\n'
  + 'Return the EXACT JSON object from step 3 as your final message. No commentary.',
  { label: 'load-ctx', phase: 'Load FRs', agentType: 'general-purpose' },
)
let ctx
try { ctx = parseAgentJson(ctxResult, 'load-ctx') }
catch (e) { return { error: 'Load FRs: ctx parse failed', detail: e.message, raw: String(ctxResult ?? '').slice(-400) } }
let frIds = Array.isArray(ctx.fr_ids) ? ctx.fr_ids
  : (Array.isArray(ctx.fr_details) ? ctx.fr_details.map(f => f.id || f.fr_id || f.fr).filter(Boolean) : [])
if (!frIds.length) return { error: 'Load FRs: no fr_ids found in ctx', ctxKeys: Object.keys(ctx) }
const frTitle = {}
if (Array.isArray(ctx.fr_details)) for (const f of ctx.fr_details) frTitle[f.id || f.fr_id] = f.title || f.name || ''
log('  fr_ids = ' + JSON.stringify(frIds))

// ════════════════════════════════════════════════════════════════════════
// Phase: Per-FR Delta (GATE1-DELTA; auto-triggers full TDD on code change)
// ════════════════════════════════════════════════════════════════════════
phase('Per-FR Delta')
const gate1Pass = []
const gate1Fail = []
for (const frId of frIds) {
  log('  === ' + frId + ' — GATE1-DELTA ===')
  const frReport = await agent(
    'YOU ARE THE VERIFIER for ' + frId + ' (' + (frTitle[frId] || '') + '). Re-evaluate Gate 1 for THIS ONE FR.\n'
    + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
    + 'Steps:\n'
    + '1. `' + PY + ' ' + REPO + '/harness_cli.py run-fr-step --phase 5 --fr-id ' + frId + ' --step GATE1-DELTA --project ' + REPO + '`\n'
    + '   - PASS → done.\n'
    + '   - FAIL → full TDD auto-triggered by crash recovery: run-fr-step --step TDD-RED → TDD-GREEN → TDD-IMPROVE → GATE1 (each for ' + frId + '). Max 3 TDD rounds.\n'
    + '   - Still failing after 3 → report FAIL.\n'
    + '   Note: if ' + frId + '’s code has not changed since its last Gate 1 PASS, GATE1-DELTA passes immediately (advance-phase auto-skip will also honour this).\n\n'
    + 'Report final line: "' + frId + ' GATE1: PASS" or "' + frId + ' GATE1: FAIL — <reason>".\n\n'
    + 'SCOPE RULES:\n- DO NOT touch any FR OTHER than ' + frId + '.\n- DO NOT run advance-phase / push-milestone / generate BASELINE docs.\n- DO NOT modify harness/.\n- ONLY GATE1-DELTA (+ full TDD if needed) for ' + frId + '.',
    { label: 'delta-' + frId, phase: 'Per-FR Delta', agentType: 'general-purpose' },
  )
  const passed = typeof frReport === 'string' && new RegExp(frId + '\\s*GATE1:\\s*PASS').test(frReport)
  if (passed) { gate1Pass.push(frId); log('  ' + frId + ' Gate 1 PASS') }
  else { gate1Fail.push(frId); log('  ' + frId + ' Gate 1 FAIL') }
}
if (gate1Fail.length) {
  return { error: 'Phase 5: Gate 1 FAILED for FR(s): ' + gate1Fail.join(', ') + ' (escalate)', gate1Pass, gate1Fail }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Verification Docs (BASELINE.md + VERIFICATION_REPORT.md + re-checks)
// ════════════════════════════════════════════════════════════════════════
phase('Verification Docs')
log('Generate BASELINE.md + VERIFICATION_REPORT.md; re-run integration + security')
const docsReport = await agent(
  'YOU ARE THE P5 VERIFICATION AUTHOR. Generate the verification deliverables.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. BASELINE: write ' + REPO + '/05-verification/BASELINE.md (create dir if missing). Document: current version, test results summary, coverage %, Gate 3 composite score. Reference 04-testing/TEST_RESULTS.md + the 03-development/src/ module list.\n'
  + '2. VERIFICATION_REPORT: write ' + REPO + '/05-verification/VERIFICATION_REPORT.md. For each FR (' + frIds.join(', ') + '): verification status, acceptance-criteria result (PASS/FAIL), evidence. Include coverage %, mutation score, deferred Gate 3 issues. Certify all Gate 3 open issues addressed or deferred-with-justification. Must be NON-trivial (validate-handoff checks this).\n'
  + '3. Re-run integration tests: `' + PY + ' -m pytest ' + REPO + '/tests/integration/ -q` (skip gracefully if dir absent).\n'
  + '4. Confirm performance NFRs: review benchmark entries in 04-testing/TEST_RESULTS.md.\n'
  + '5. Security clean: `bandit -r ' + REPO + '/03-development/src/ -ll` + `gitleaks detect --source ' + REPO + '`.\n\n'
  + 'Report: "VERIFY-DOCS: PASS" or "VERIFY-DOCS: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run advance-phase / push-milestone.\n- DO NOT modify harness/.\n- DO NOT re-implement FRs (only document verification + re-run existing checks).\n- ONLY generate the 2 docs + re-run checks.',
  { label: 'verification-docs', phase: 'Verification Docs', agentType: 'general-purpose' },
)
if (!(typeof docsReport === 'string' && /VERIFY-DOCS:\s*PASS/.test(docsReport))) {
  return { error: 'Phase 5 verification docs did not PASS', raw: String(docsReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Milestone (p5-baseline push)
// ════════════════════════════════════════════════════════════════════════
phase('Milestone')
log('push-milestone p5-baseline (after BASELINE.md generated)')
const milestoneReport = await agent(
  'YOU ARE THE P5 MILESTONE PUSHER.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + '0. GUARD: `git -C ' + REPO + ' log --oneline --grep="p5-baseline" -1`. If exists, report "MILESTONE: PASS (already pushed)" and stop.\n'
  + '1. Command: `' + PY + ' ' + REPO + '/harness_cli.py push-milestone --type p5-baseline --project ' + REPO + '`\n'
  + 'Writes HANDOVER.md + commits + pushes. If a hook blocks, reword commit to start with `chore(harness):` (NOT --no-verify), retry.\n\n'
  + 'Report: "MILESTONE: PASS|FAIL — <details>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run advance-phase.\n- ONLY push-milestone p5-baseline.',
  { label: 'milestone-baseline', phase: 'Milestone', agentType: 'general-purpose' },
)
if (!(typeof milestoneReport === 'string' && /MILESTONE:\s*PASS/.test(milestoneReport))) {
  return { error: 'Phase 5 p5-baseline milestone did not PASS', raw: String(milestoneReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Advance (D4 90% gap check + advance-phase --completed 5)
// ════════════════════════════════════════════════════════════════════════
phase('Advance')
log('D4 90% gap warning + advance-phase --completed 5 (TDD-PRECHECK enforced)')
const advanceReport = await agent(
  'YOU ARE THE PHASE-5 EXIT ORCHESTRATOR. Advance to Phase 6.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '0. GUARD — already advanced? `grep -i "resume_phase\\|phase.\\?6\\|P6-entry" ' + REPO + '/HANDOVER.md 2>/dev/null | head -3`. If Phase 6 is confirmed, report "ADVANCE: PASS (already advanced)" and stop.\n'
  + '1. D4-GAP: `' + PY + ' ' + REPO + '/harness_cli.py spec-coverage-check --project ' + REPO + ' --threshold 90.0`. Gate 4 (next phase) needs ≥90% but advance only needs 80% — if below 90%, ADD missing test implementations NOW to avoid a Gate 4 surprise.\n'
  + '2. advance-phase: `' + PY + ' ' + REPO + '/harness_cli.py advance-phase --completed 5 --project ' + REPO + '`\n'
  + '   TDD-PRECHECK enforced: gitleaks + ruff + mypy + pytest --cov-fail-under=100 + spec-coverage 80%. Auto-skip honours unchanged FR code. Fix any blocker, re-run.\n'
  + '   PHASE-TRUTH (HR-11): if advance-phase fails on Phase Truth (<90%), check phase_truth_verifier output in .sessi-work/, fix the failing phase-link/gate artifact, re-run (max 3, then escalate to human).\n'
  + '3. Read ' + REPO + '/HANDOVER.md; confirm Phase 6 entry ("P6-entry" OR "resume_phase = 6").\n\n'
  + 'Report: "ADVANCE: PASS|FAIL — <details>". PHASE_6_PLAN: ' + REPO + '/.methodology/phase6_plan.md\n\n'
  + 'SCOPE RULES:\n- DO NOT re-do P5 docs.\n- DO NOT use --no-verify.\n- DO NOT modify harness/ (HR-17).\n- ONLY spec-coverage-check + advance-phase + verify HANDOVER.md.',
  { label: 'advance', phase: 'Advance', agentType: 'general-purpose' },
)

if (!advanceReport || !/ADVANCE:\s*PASS/.test(advanceReport)) {
  return { error: 'Advance phase did not confirm PASS — check HANDOVER.md + state.json. If Phase 6 is confirmed, resume workflow to verify.', raw: String(advanceReport ?? '').slice(-400) }
}
log('Phase 5 workflow complete. Open .methodology/phase6_plan.md to continue.')
return {
  phase: 5,
  fr_count: frIds.length,
  gate1_pass: gate1Pass,
  advance_status: 'PASS',
  artifacts: ['05-verification/BASELINE.md', '05-verification/VERIFICATION_REPORT.md', 'HANDOVER.md'],
  notes: 'Phase 5 complete per phase5_plan.md v2.12.0. Phase 6 (Quality Assurance) ready. Reminder: Gate 4 needs spec-coverage ≥90%.',
}
