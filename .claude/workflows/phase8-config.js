// Phase 8 — Configuration Management (faithful to .methodology/phase8_plan.md v2.12.0)
//
// Structure: FR-loop型 + FINAL phase (NO advance-phase — pipeline ends here).
// Per-FR GATE1-DELTA re-eval, then generate config deliverables, create the
// .methodology-archive/ (CI p8-archive-check), verify no Phase 9 refs, p8 push.
//
// Playbook lessons: NO import/fs/process/schema:, Bash CLI, SCOPE RULES,
// PY = .venv/bin/python, scriptPath launch.

export const meta = {
  name: 'phase8-config',
  description: 'Phase 8 Config — per-FR GATE1-DELTA + CONFIG_RECORDS/RELEASE_CHECKLIST + archive + p8 push (phase8_plan.md v2.12.0)',
  phases: [
    { title: 'Entry & Preflight' },
    { title: 'Env Check' },
    { title: 'Load FRs' },
    { title: 'Per-FR Delta' },
    { title: 'Config Docs' },
    { title: 'Archive' },
    { title: 'Final Push' },
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
// Phase: Entry & Preflight
// ════════════════════════════════════════════════════════════════════════
phase('Entry & Preflight')
log('ENTRY-CHECK Gate4 + run-phase 8 (reliability/config/attestation fixes) + handoff + CI')
const preflightReport = await agent(
  'YOU ARE THE PHASE-8 PREFLIGHT ORCHESTRATOR. Run bash in order; report.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. ENTRY-CHECK: confirm .methodology/quality_manifest.json records Gate 4 PASS from P6 (else FAIL → return to Phase 6).\n'
  + '2. PREFLIGHT: `' + PY + ' ' + REPO + '/harness_cli.py run-phase --phase 8 --project ' + REPO + '`. FAIL → fix, re-run (max 3). Also fix if reported: reliability lint (subprocess timeout / mkstemp / TOCTOU / sleep-in-async), config liveness (env keys absent from .env.example), attestation missing/mismatch (build-trace-attestation --write + commit; re-run until "Attestation: clean").\n'
  + '3. HANDOFF: `' + PY + ' ' + REPO + '/harness_cli.py validate-handoff --from-phase 7 --project ' + REPO + '`. Must exit 0.\n'
  + '4. PREFLIGHT-CI: harness_quality_gate.yml + prepare-commit-msg exist; state.json current_phase=8. If stale: init-project --phase 8 --overwrite.\n\n'
  + 'Report: "PREFLIGHT: PASS" or "PREFLIGHT: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT generate config docs / run TDD steps / create archive.\n- DO NOT run push-milestone.\n- DO NOT modify harness/.\n- ONLY preflight commands + fixes.',
  { label: 'preflight', phase: 'Entry & Preflight', agentType: 'general-purpose' },
)
if (!(typeof preflightReport === 'string' && /PREFLIGHT:\s*PASS/.test(preflightReport))) {
  return { error: 'Phase 8 preflight did not PASS', raw: String(preflightReport ?? '').slice(-600) }
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
  + '1. `' + PY + ' ' + REPO + '/harness_cli.py run-env-check --phase 8 --project ' + REPO + '` — read the printed prompt.\n'
  + '2. Evaluate inline and write ' + REPO + '/.sessi-work/env_check_result.json.\n'
  + '3. `' + PY + ' ' + REPO + '/harness_cli.py finalize-env-check --phase 8 --project ' + REPO + '`.\n\n'
  + 'Report: "ENV-CHECK: PASS" or "ENV-CHECK: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run TDD/milestone/archive commands.\n- ONLY env-check.',
  { label: 'env-check', phase: 'Env Check', agentType: 'general-purpose' },
)
if (!(typeof envReport === 'string' && /ENV-CHECK:\s*PASS/.test(envReport))) {
  return { error: 'Phase 8 env-check did not PASS', raw: String(envReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Load FRs
// ════════════════════════════════════════════════════════════════════════
phase('Load FRs')
log('load-context --phase 8 → fr_ids')
const ctxResult = await agent(
  'Use ONLY the Bash tool. Run:\n'
  + '1. `mkdir -p ' + REPO + '/.sessi-work`\n'
  + '2. `' + PY + ' ' + REPO + '/harness_cli.py load-context --phase 8 --project ' + REPO + ' --json > ' + REPO + '/.sessi-work/phase8_ctx.json`\n'
  + '3. `cat ' + REPO + '/.sessi-work/phase8_ctx.json`\n'
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
    'YOU ARE THE CONFIG-AWARE VERIFIER for ' + frId + ' (' + (frTitle[frId] || '') + '). Re-evaluate Gate 1 for THIS ONE FR.\n'
    + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
    + 'Steps:\n'
    + '1. `' + PY + ' ' + REPO + '/harness_cli.py run-fr-step --phase 8 --fr-id ' + frId + ' --step GATE1-DELTA --project ' + REPO + '`\n'
    + '   - PASS → done.\n'
    + '   - FAIL → full TDD auto-triggered: TDD-RED → TDD-GREEN → TDD-IMPROVE → GATE1 (each for ' + frId + '). Max 3 rounds. Still failing → report FAIL.\n'
    + '   If ' + frId + '’s code is unchanged since last Gate 1 PASS, this passes immediately.\n\n'
    + 'Report final line: "' + frId + ' GATE1: PASS" or "' + frId + ' GATE1: FAIL — <reason>".\n\n'
    + 'SCOPE RULES:\n- DO NOT touch any FR OTHER than ' + frId + '.\n- DO NOT run push-milestone / generate config docs / create archive.\n- DO NOT modify harness/.\n- ONLY GATE1-DELTA (+ full TDD if needed) for ' + frId + '.',
    { label: 'delta-' + frId, phase: 'Per-FR Delta', agentType: 'general-purpose' },
  )
  const passed = typeof frReport === 'string' && new RegExp(frId + '\\s*GATE1:\\s*PASS').test(frReport)
  if (passed) { gate1Pass.push(frId); log('  ' + frId + ' Gate 1 PASS') }
  else { gate1Fail.push(frId); log('  ' + frId + ' Gate 1 FAIL') }
}
if (gate1Fail.length) {
  return { error: 'Phase 8: Gate 1 FAILED for FR(s): ' + gate1Fail.join(', ') + ' (escalate)', gate1Pass, gate1Fail }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Config Docs (CONFIG_RECORDS + RELEASE_CHECKLIST under 08-config/)
// ════════════════════════════════════════════════════════════════════════
phase('Config Docs')
log('Generate CONFIG_RECORDS.md + RELEASE_CHECKLIST.md')
const docsReport = await agent(
  'YOU ARE THE P8 CONFIG AUTHOR. Generate the configuration deliverables.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps (create 08-config/ if missing):\n'
  + '1. CONFIG_RECORDS: write ' + REPO + '/08-config/CONFIG_RECORDS.md. Review all env vars, secrets, feature flags, deployment settings. For each item: name, value/source, access method, owner, environment (dev/staging/prod). Reference 03-development/src/ module configs + .env.example. taskq has 8 TASKQ_* env vars (TASKQ_HOME / MAX_WORKERS / TASK_TIMEOUT / RETRY_LIMIT / BACKOFF_BASE / BREAKER_THRESHOLD / BREAKER_COOLDOWN / CACHE_TTL).\n'
  + '2. RELEASE_CHECKLIST: write ' + REPO + '/08-config/RELEASE_CHECKLIST.md. Pre-release (all Gate 4 dims PASS, no open critical, security clean), Deployment (env vars set, secrets rotated, smoke tests), Post-release (monitoring, rollback plan).\n\n'
  + 'Report: "CONFIG-DOCS: PASS" or "CONFIG-DOCS: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run push-milestone / create archive (next phases do that).\n- DO NOT modify harness/.\n- DO NOT re-implement FRs.\n- ONLY generate the 2 config docs.',
  { label: 'config-docs', phase: 'Config Docs', agentType: 'general-purpose' },
)
if (!(typeof docsReport === 'string' && /CONFIG-DOCS:\s*PASS/.test(docsReport))) {
  return { error: 'Phase 8 config docs did not PASS', raw: String(docsReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Archive (P8-ARCHIVE + P8-HANDOVER-CHECK — required by CI p8-archive-check)
// ════════════════════════════════════════════════════════════════════════
phase('Archive')
log('Create .methodology-archive/ + verify HANDOVER.md has no Phase 9 refs')
const archiveReport = await agent(
  'YOU ARE THE P8 ARCHIVE ORCHESTRATOR. Prepare the archive (REQUIRED before p8 push).\n'
  + 'REPO: ' + REPO + '\n\n'
  + 'Steps (Bash):\n'
  + '1. P8-ARCHIVE: `mkdir -p ' + REPO + '/.methodology-archive && cp -r ' + REPO + '/.sessi-work/ ' + REPO + '/.methodology-archive/`. (push-milestone _validate_p8_completion + CI p8-archive-check both verify this dir.)\n'
  + '2. P8-HANDOVER-CHECK: `grep -qi "phase 9\\|phase9\\|phase9_plan" ' + REPO + '/HANDOVER.md && echo "HAS_P9" || echo "NO_P9"`. Phase 8 is final — if HAS_P9, remove the Phase 9 references from HANDOVER.md (Edit).\n\n'
  + 'Report: "ARCHIVE: PASS" (dir created AND no Phase 9 refs) or "ARCHIVE: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run push-milestone yet.\n- DO NOT modify harness/.\n- ONLY create .methodology-archive/ + clean HANDOVER.md Phase 9 refs.',
  { label: 'archive', phase: 'Archive', agentType: 'general-purpose' },
)
if (!(typeof archiveReport === 'string' && /ARCHIVE:\s*PASS/.test(archiveReport))) {
  return { error: 'Phase 8 archive prep did not PASS', raw: String(archiveReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Final Push (p8 — pipeline complete; NO advance-phase, P8 is last)
// ════════════════════════════════════════════════════════════════════════
phase('Final Push')
log('push-milestone p8 (final — pipeline complete)')
const pushReport = await agent(
  'YOU ARE THE P8 FINAL PUSHER. This is the LAST step of the 8-phase pipeline.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. P8 completion checklist (TDD-PRECHECK): confirm gitleaks + ruff + mypy + pytest --cov-fail-under=100 + spec-coverage 90% all pass. Fix blockers.\n'
  + '2. PUSH ⑩: `' + PY + ' ' + REPO + '/harness_cli.py push-milestone --type p8 --project ' + REPO + '`. _validate_p8_completion auto-verifies .methodology-archive/ exists. Writes HANDOVER.md + commits + pushes. If a hook blocks, reword commit to start with `chore(harness):` (NOT --no-verify), retry.\n'
  + '   PHASE-TRUTH (HR-11): push-milestone p8 / _validate_p8_completion verifies Phase Truth ≥90%; if it fails, check phase_truth_verifier output in .sessi-work/, fix the failing phase-link/gate artifact, re-run (max 3, then escalate to human).\n'
  + '3. Confirm: pipeline complete (all 8 phases done).\n\n'
  + 'Report: "P8-PUSH: PASS|FAIL — <details>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run advance-phase (Phase 8 is the final phase — there is no Phase 9).\n- DO NOT use --no-verify.\n- DO NOT modify harness/ (HR-17).\n- ONLY the completion checklist + push-milestone p8.',
  { label: 'final-push', phase: 'Final Push', agentType: 'general-purpose' },
)
const p8Ok = typeof pushReport === 'string' && /P8-PUSH:\s*PASS/.test(pushReport)
if (!p8Ok) return { error: 'Phase 8 p8 push did not PASS', raw: String(pushReport ?? '').slice(-500) }

log('Phase 8 workflow complete. 🎉 8-phase pipeline complete.')
return {
  phase: 8,
  fr_count: frIds.length,
  gate1_pass: gate1Pass,
  p8_push_status: p8Ok ? 'PASS' : 'unknown',
  artifacts: ['08-config/CONFIG_RECORDS.md', '08-config/RELEASE_CHECKLIST.md', '.methodology-archive/', 'HANDOVER.md'],
  notes: 'Phase 8 complete per phase8_plan.md v2.12.0. 🎉 Full P1→P8 pipeline complete — archive .methodology/ for the audit trail.',
}
