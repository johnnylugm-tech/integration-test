// Phase 7 — Risk Management (faithful to .methodology/phase7_plan.md v2.12.0)
//
// Structure: FR-loop型, NO harness run-gate (P7 cleared by Gate 4). Per-FR
// GATE1-DELTA re-eval, then generate the 3 risk deliverables, p7 milestone
// push, advance (TDD-PRECHECK + D4 ≥90% enforced by advance-phase).
//
// Playbook lessons: NO import/fs/process/schema:, Bash CLI, SCOPE RULES,
// PY = .venv/bin/python, scriptPath launch.

export const meta = {
  name: 'phase7-risk',
  description: 'Phase 7 Risk — per-FR GATE1-DELTA + RISK_REGISTER/MITIGATION/STATUS + p7 push (phase7_plan.md v2.12.0)',
  phases: [
    { title: 'Entry & Preflight' },
    { title: 'Env Check' },
    { title: 'Load FRs' },
    { title: 'Per-FR Delta' },
    { title: 'Risk Docs' },
    { title: 'Milestone' },
    { title: 'Advance' },
  ],
}

// ---- args / REPO / PY ----
// REPO precedence: args.repo override wins, then DEFAULT_REPO canonical path.
// process.env.HARNESS_REPO cannot be read here — playbook §4 forbids process.*
// in workflow JS. Caller scripts (run-e2e.mjs / harness-e2e.js /
// phase1-workflow.mjs) read HARNESS_REPO and inject it via args.repo.
const DEFAULT_REPO = '/Users/johnny/projects/integration-test'
let REPO = DEFAULT_REPO
if (typeof args === 'string') { try { args = JSON.parse(args) } catch {} }
if (args && typeof args === 'object' && typeof args.repo === 'string' && args.repo.length > 0) REPO = args.repo
const PY = REPO + '/.venv/bin/python'
log('REPO = ' + REPO + ' | PY = ' + PY)
// v15: budget guard (Bug #3 — port from phase2-architecture)
if (typeof budget !== 'undefined' && budget.remaining && budget.remaining() < 200000) {
  log('WARNING: budget low (' + Math.round((budget.remaining() || 0) / 1000) + 'k remaining) — workflow may not complete')
}

// ---- J: WRITE SCOPE convention for LLM agent debug artifacts ----
// All agent-generated debug scripts, coverage reports, and exploration
// artifacts MUST go under ${REPO}/.sessi-work/tmp/<random_id>/. This
// directory is gitignored and gets cleaned automatically. Direct writes
// to 03-development/, scripts/, .claude/, harness/, .methodology/, or
// .github/ require explicit user approval per agent scope rules.
//
// Why this matters: debug_* scripts (fr04_cov.py, show_cov.py, etc.)
// otherwise pollute the source tree and require manual cleanup before
// commit. Sandboxing them keeps the working tree clean by default.
//
// Self-audit (add to agent prompt end): "List every Write/Edit file
// path used in this task; confirm all paths start with .sessi-work/tmp/."
const WRITE_SCOPE_TMP = REPO + '/.sessi-work/tmp'
log('WRITE SCOPE: debug artifacts → ' + WRITE_SCOPE_TMP)

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
// Phase: Entry & Preflight
// ════════════════════════════════════════════════════════════════════════

phase('Entry & Preflight')
log('ENTRY-CHECK Gate4 + run-phase 7 (reliability/config/attestation fixes) + handoff + CI')
const preflightReport = await agent(
  'YOU ARE THE PHASE-7 PREFLIGHT ORCHESTRATOR. Run bash in order; report.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. ENTRY-CHECK: confirm .methodology/quality_manifest.json records Gate 4 PASS from P6 (else FAIL → return to Phase 6).\n'
  + '2. PREFLIGHT: `' + PY + ' ' + REPO + '/harness_cli.py run-phase --phase 7 --project ' + REPO + '`. FAIL → fix, re-run (max 3). Also fix if reported: reliability lint (subprocess timeout / mkstemp / TOCTOU / sleep-in-async), config liveness (env keys absent from .env.example), attestation missing/mismatch (build-trace-attestation --write + commit; re-run until "Attestation: clean").\n'
  + '3. HANDOFF: `' + PY + ' ' + REPO + '/harness_cli.py validate-handoff --from-phase 6 --project ' + REPO + '`. Must exit 0.\n'
  + '4. PREFLIGHT-CI: harness_quality_gate.yml + prepare-commit-msg exist; state.json current_phase=7. If stale: init-project --phase 7 --overwrite.\n\n'
  + 'Report: "PREFLIGHT: PASS" or "PREFLIGHT: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT generate risk docs or run TDD steps.\n- DO NOT run advance-phase/push-milestone.\n- DO NOT modify harness/.\n- ONLY preflight commands + fixes.',
  { label: 'preflight', phase: 'Entry & Preflight', agentType: 'general-purpose' },
)
if (!(typeof preflightReport === 'string' && /PREFLIGHT:\s*PASS/.test(preflightReport))) {
  return { error: 'Phase 7 preflight did not PASS', raw: String(preflightReport ?? '').slice(-600) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Env Check
// ════════════════════════════════════════════════════════════════════════
phase('Env Check')
log('run-env-check + finalize-env-check')
const envReport = await agent(
  'YOU ARE THE ENV-CHECK ORCHESTRATOR. Run ONCE before the FR loop.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. `' + PY + ' ' + REPO + '/harness_cli.py run-env-check --phase 7 --project ' + REPO + '` — read the printed prompt.\n'
  + '2. Evaluate inline and write ' + REPO + '/.sessi-work/env_check_result.json.\n'
  + '3. `' + PY + ' ' + REPO + '/harness_cli.py finalize-env-check --phase 7 --project ' + REPO + '`.\n\n'
  + 'Report: "ENV-CHECK: PASS" or "ENV-CHECK: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run TDD/advance/milestone commands.\n- ONLY env-check.',
  { label: 'env-check', phase: 'Env Check', agentType: 'general-purpose' },
)
if (!(typeof envReport === 'string' && /ENV-CHECK:\s*PASS/.test(envReport))) {
  return { error: 'Phase 7 env-check did not PASS', raw: String(envReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Load FRs
// ════════════════════════════════════════════════════════════════════════
phase('Load FRs')
log('load-context --phase 7 → fr_ids')
// v15: retry loop — agent() + parseAgentJson both wrapped (Bug #2)
let ctx = null, ctxResult = ''
for (let attempt = 1; attempt <= 3; attempt++) {
  try { ctxResult = await agent(
    'Use ONLY the Bash tool. Run:\n'
    + '1. `mkdir -p ' + REPO + '/.sessi-work`\n'
    + '2. `' + PY + ' ' + REPO + '/harness_cli.py load-context --phase 7 --project ' + REPO + ' --json > ' + REPO + '/.sessi-work/phase7_ctx.json`\n'
    + '3. `cat ' + REPO + '/.sessi-work/phase7_ctx.json`\n'
    + 'Return the EXACT JSON object from step 3 as your final message. No commentary.',
    { label: 'load-ctx-a' + attempt, phase: 'Load FRs', agentType: 'general-purpose' },
  ) } catch (e) { log('  load-ctx agent failed: ' + String(e.message ?? e).slice(0, 80)); continue }
  try { ctx = parseAgentJson(ctxResult, 'load-ctx'); break }
  catch (e) { log('  load-ctx parse failed: ' + e.message.slice(0, 80)); continue }
}
if (!ctx) return { error: 'Load FRs: ctx failed after 3 attempts', raw: String(ctxResult ?? '').slice(-400) }
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
    'YOU ARE THE RISK-AWARE VERIFIER for ' + frId + ' (' + (frTitle[frId] || '') + '). Re-evaluate Gate 1 for THIS ONE FR.\n'
    + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
    + 'Steps:\n'
    + '1. `' + PY + ' ' + REPO + '/harness_cli.py run-fr-step --phase 7 --fr-id ' + frId + ' --step GATE1-DELTA --project ' + REPO + '`\n'
    + '   - PASS → done.\n'
    + '   - FAIL → full TDD auto-triggered: TDD-RED → TDD-GREEN → TDD-IMPROVE → GATE1 (each for ' + frId + '). Max 3 rounds. Still failing → report FAIL.\n'
    + '   If ' + frId + '’s code is unchanged since last Gate 1 PASS, this passes immediately.\n\n'
    + 'Report final line: "' + frId + ' GATE1: PASS" or "' + frId + ' GATE1: FAIL — <reason>".\n\n'
    + 'SCOPE RULES:\n- DO NOT touch any FR OTHER than ' + frId + '.\n- DO NOT run advance-phase / push-milestone / generate risk docs.\n- DO NOT modify harness/.\n- ONLY GATE1-DELTA (+ full TDD if needed) for ' + frId + '.',
    { label: 'delta-' + frId, phase: 'Per-FR Delta', agentType: 'general-purpose' },
  )
  const passed = typeof frReport === 'string' && new RegExp(frId + '\\s*GATE1:\\s*PASS').test(frReport)
  if (passed) { gate1Pass.push(frId); log('  ' + frId + ' Gate 1 PASS') }
  else { gate1Fail.push(frId); log('  ' + frId + ' Gate 1 FAIL') }
}
if (gate1Fail.length) {
  return { error: 'Phase 7: Gate 1 FAILED for FR(s): ' + gate1Fail.join(', ') + ' (escalate)', gate1Pass, gate1Fail }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Risk Docs (RISK_REGISTER + RISK_MITIGATION_PLANS + RISK_STATUS_REPORT)
// ════════════════════════════════════════════════════════════════════════
phase('Risk Docs')
log('Generate the 3 risk deliverables under 07-risk/')
const docsReport = await agent(
  'YOU ARE THE P7 RISK AUTHOR. Generate the risk deliverables.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps (create 07-risk/ if missing):\n'
  + '1. RISK_REGISTER: write ' + REPO + '/07-risk/RISK_REGISTER.md. Review open issues from Gate 3/4, .methodology/deferred_fixes.md, .sessi-work/issue_registry.json. For each risk: ID, name, likelihood (1–5), impact (1–5), category, mitigation approach. Seed from SPEC.md §9 risk matrix (R1 concurrent write / R2 subprocess hang / R3 breaker deadlock / R4 stale cache).\n'
  + '2. RISK_MITIGATION_PLANS: write ' + REPO + '/07-risk/RISK_MITIGATION_PLANS.md. For HIGH risks (likelihood × impact ≥ 9): formal mitigation plan with owner + deadline.\n'
  + '3. RISK_STATUS_REPORT: write ' + REPO + '/07-risk/RISK_STATUS_REPORT.md. Summary of all risks, current status, mitigation owner, target date.\n\n'
  + 'All 3 must be NON-trivial (validate-handoff checks presence + well-formedness).\n'
  + 'Report: "RISK-DOCS: PASS" or "RISK-DOCS: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run advance-phase / push-milestone.\n- DO NOT modify harness/.\n- DO NOT re-implement FRs.\n- ONLY generate the 3 risk docs.',
  { label: 'risk-docs', phase: 'Risk Docs', agentType: 'general-purpose' },
)
if (!(typeof docsReport === 'string' && /RISK-DOCS:\s*PASS/.test(docsReport))) {
  return { error: 'Phase 7 risk docs did not PASS', raw: String(docsReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Milestone (p7 push)
// ════════════════════════════════════════════════════════════════════════
phase('Milestone')
log('push-milestone p7 (after risk register complete)')
const milestoneReport = await agent(
  'YOU ARE THE P7 MILESTONE PUSHER.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + '0. GUARD: `git -C ' + REPO + ' log --oneline --grep="p7" -1`. If exists, report "MILESTONE: PASS (already pushed)" and stop.\n'
  + '1. Command: `' + PY + ' ' + REPO + '/harness_cli.py push-milestone --type p7 --project ' + REPO + '`\n'
  + 'Writes HANDOVER.md + commits + pushes. If a hook blocks, reword commit to start with `chore(harness):` (NOT --no-verify), retry.\n\n'
  + 'Report: "MILESTONE: PASS|FAIL — <details>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run advance-phase.\n- ONLY push-milestone p7.',
  { label: 'milestone-p7', phase: 'Milestone', agentType: 'general-purpose' },
)
if (!(typeof milestoneReport === 'string' && /MILESTONE:\s*PASS/.test(milestoneReport))) {
  return { error: 'Phase 7 p7 milestone did not PASS', raw: String(milestoneReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Advance (advance-phase --completed 7)
// ════════════════════════════════════════════════════════════════════════
phase('Advance')
log('advance-phase --completed 7 (TDD-PRECHECK + D4 90% enforced)')
const advanceReport = await agent(
  'YOU ARE THE PHASE-7 EXIT ORCHESTRATOR. Advance to Phase 8.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '0. GUARD — already advanced? `PHASE=$(jq -r '.current_phase // 0' ' + REPO + '/.methodology/state.json 2>/dev/null); echo "current_phase=$PHASE"; [ "$PHASE" -ge 8 ]`. If Phase 8 is confirmed, report "ADVANCE: PASS (already advanced)" and stop.\n'
  + '1. advance-phase: `' + PY + ' ' + REPO + '/harness_cli.py advance-phase --completed 7 --project ' + REPO + '`\n'
  + '   TDD-PRECHECK enforced: gitleaks + ruff + mypy + pytest --cov-fail-under=100 + spec-coverage 90%. Auto-skip honours unchanged FR code. Fix any blocker, re-run.\n'
  + '   PHASE-TRUTH (HR-11): if advance-phase fails on Phase Truth (<90%), check phase_truth_verifier output in .sessi-work/, fix the failing phase-link/gate artifact, re-run (max 3, then escalate to human).\n'
  + '2. Read ' + REPO + '/.methodology/state.json; confirm current_phase = 8 (advance-phase atomically writes state.json when complete).\n\n'
  + 'Report: "ADVANCE: PASS|FAIL — <details>". PHASE_8_PLAN: ' + REPO + '/.methodology/phase8_plan.md\n\n'
  + 'SCOPE RULES:\n- DO NOT re-do P7 docs.\n- DO NOT use --no-verify.\n- DO NOT modify harness/ (HR-17).\n- ONLY advance-phase + verify HANDOVER.md.',
  { label: 'advance', phase: 'Advance', agentType: 'general-purpose' },
)

if (!advanceReport || !/ADVANCE:\s*PASS/.test(advanceReport)) {
  return { error: 'Advance phase did not confirm PASS — check HANDOVER.md + state.json. If Phase 8 is confirmed, resume workflow to verify.', raw: String(advanceReport ?? '').slice(-400) }
}
log('Phase 7 workflow complete. Open .methodology/phase8_plan.md to continue.')
return {
  phase: 7,
  fr_count: frIds.length,
  gate1_pass: gate1Pass,
  advance_status: 'PASS',
  artifacts: ['07-risk/RISK_REGISTER.md', '07-risk/RISK_MITIGATION_PLANS.md', '07-risk/RISK_STATUS_REPORT.md', 'HANDOVER.md'],
  notes: 'Phase 7 complete per phase7_plan.md v2.12.0. Phase 8 (Configuration Management) ready.',
}
