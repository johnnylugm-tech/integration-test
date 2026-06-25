// Phase 3 — Implementation (faithful to .methodology/phase3_plan.md v2.12.0)
//
// Structure: FR-loop型 + Gate 2 exit. Script holds the per-FR loop (playbook
// "plan as code"): load fr_ids via an agent, then for each FR dispatch a
// narrow agent that runs the TDD chain (RED→MIRROR→GREEN→IMPROVE→GATE1).
// Milestone pushes are script-driven (≥50% → p3-mid; all done → p3-pre-gate2).
// Gate 2 is one orchestrator agent (run-gate → eval → finalize → D4 60%).
//
// Playbook lessons: NO import/fs/process/schema:, Bash for all harness CLI,
// SCOPE RULES per agent, PY = .venv/bin/python, scriptPath launch.

export const meta = {
  name: 'phase3-implementation',
  description: 'Phase 3 Implementation — per-FR TDD (RED/GREEN/IMPROVE/GATE1) + milestones + Gate 2 exit (phase3_plan.md v2.12.0)',
  phases: [
    { title: 'Entry & Preflight' },
    { title: 'Env Check' },
    { title: 'Load FRs' },
    { title: 'Per-FR TDD' },
    { title: 'Milestones' },
    { title: 'Gate 2' },
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

// ---- G: state.json re-run shortcut (opt-in via args.shortcut=true) ----
// When re-running a phase that already PASSED, we can skip env-check +
// plan-all re-dispatch by reading state.json up front. The shortcut
// dispatches a haiku agent (cheap, <5s) to read the JSON file directly,
// since workflow JS cannot use fs.* / process.* (playbook §4 hard rule).
// Pass args.shortcut=true when re-invoking to activate.
async function maybeShortcut(plannedPhase) {
  if (!args || args.shortcut !== true) return null
  const r = await agent(
    'Read ' + REPO + '/.methodology/state.json and report ONLY a JSON object ' +
    'with two keys: "current_phase" (integer) and "phase_truth_passed" (boolean). ' +
    'Reply with just the JSON, no prose.',
    { label: 'state-shortcut', phase: 'State Shortcut', agentType: 'general-purpose', model: 'haiku' },
  )
  try {
    const s = parseAgentJson(String(r), 'state-shortcut')
    if (s && s.phase_truth_passed === true && Number(s.current_phase) >= plannedPhase) {
      log('[SHORTCUT] state.json shows phase ' + s.current_phase + ' already passed (≥ ' + plannedPhase + '); skipping to verification.')
      return { shortcut: true, current_phase: s.current_phase, phase_truth_passed: true }
    }
  } catch (e) {
    log('[SHORTCUT] state.json parse failed (' + e.message + ') — continuing normally')
  }
  return null
}

const _shortcut = await maybeShortcut(3)
if (_shortcut) return _shortcut

phase('Entry & Preflight')
log('ENTRY-CHECK + P2-ARTIFACTS + run-phase 3 + validate-handoff + CI')
const preflightReport = await agent(
  'YOU ARE THE PHASE-3 PREFLIGHT ORCHESTRATOR. Run bash in order; report.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. ENTRY-CHECK: `git -C ' + REPO + ' log --oneline --grep="phase2(review-complete)" -1` OR confirm P2 artifacts exist.\n'
  + '2. P2-ARTIFACTS: `ls ' + REPO + '/02-architecture/SAD.md ' + REPO + '/02-architecture/adr/ADR.md ' + REPO + '/02-architecture/TEST_SPEC.md ' + REPO + '/.methodology/quality_manifest.json ' + REPO + '/.methodology/SAB.json`. ALL must exist (else FAIL → return to Phase 2).\n'
  + '3. PREFLIGHT: `' + PY + ' ' + REPO + '/harness_cli.py run-phase --phase 3 --project ' + REPO + '`. FAIL → fix FSM/Constitution/Drift, re-run (max 3).\n'
  + '4. HANDOFF: `' + PY + ' ' + REPO + '/harness_cli.py validate-handoff --from-phase 2 --project ' + REPO + '`. Must exit 0.\n'
  + '5. PREFLIGHT-CI: harness_quality_gate.yml + prepare-commit-msg exist; state.json current_phase=3. If stale: `init-project --phase 3 --project ' + REPO + ' --overwrite`.\n\n'
  + 'Report: "PREFLIGHT: PASS" or "PREFLIGHT: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT implement any FR or run TDD steps.\n- DO NOT run advance-phase/push-milestone/run-gate.\n- DO NOT modify harness/.\n- ONLY preflight commands + fixes.',
  { label: 'preflight', phase: 'Entry & Preflight', agentType: 'general-purpose' },
)
if (!(typeof preflightReport === 'string' && /PREFLIGHT:\s*PASS/.test(preflightReport))) {
  return { error: 'Phase 3 preflight did not PASS', raw: String(preflightReport ?? '').slice(-600) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Env Check (run-env-check + finalize — required before any GATE1)
// ════════════════════════════════════════════════════════════════════════
phase('Env Check')
log('run-env-check + finalize-env-check (GATE1 preflight needs env_check_result.json)')
const envReport = await agent(
  'YOU ARE THE ENV-CHECK ORCHESTRATOR. Run ONCE before the FR loop.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. `' + PY + ' ' + REPO + '/harness_cli.py run-env-check --phase 3 --project ' + REPO + '` — read the printed evaluation prompt.\n'
  + '2. Evaluate inline and write the result to ' + REPO + '/.sessi-work/env_check_result.json (per the printed instructions).\n'
  + '3. `' + PY + ' ' + REPO + '/harness_cli.py finalize-env-check --phase 3 --project ' + REPO + '`.\n\n'
  + 'Report: "ENV-CHECK: PASS" or "ENV-CHECK: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run TDD/gate/advance commands.\n- ONLY env-check.',
  { label: 'env-check', phase: 'Env Check', agentType: 'general-purpose' },
)
if (!(typeof envReport === 'string' && /ENV-CHECK:\s*PASS/.test(envReport))) {
  return { error: 'Phase 3 env-check did not PASS', raw: String(envReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Load FRs (agent reads ctx.json — script can't read files, playbook §4)
// ════════════════════════════════════════════════════════════════════════
phase('Load FRs')
log('load-context --phase 3 → fr_ids (script holds the loop)')
const ctxResult = await agent(
  'Use ONLY the Bash tool. Run these commands:\n'
  + '1. `mkdir -p ' + REPO + '/.sessi-work`\n'
  + '2. `' + PY + ' ' + REPO + '/harness_cli.py load-context --phase 3 --project ' + REPO + ' --json > ' + REPO + '/.sessi-work/phase3_ctx.json`\n'
  + '3. `cat ' + REPO + '/.sessi-work/phase3_ctx.json`\n'
  + 'Return the EXACT JSON object from step 3 as your final message. No commentary, no markdown fences.',
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

// Sentinel pre-check: identify Gate 1 already-done FRs to skip TDD agent invocations on resume/re-run
const sentinelRaw = await agent(
  'Use ONLY the Bash tool: `ls ' + REPO + '/.sessi-work/sentinels/ 2>/dev/null | grep "^g1_" | grep "\\.flag$" || true`. Return raw output, no commentary.',
  { label: 'sentinel-precheck', phase: 'Load FRs' }
)
const alreadyDone = new Set()
if (typeof sentinelRaw === 'string') {
  for (const line of sentinelRaw.split('\n')) {
    const m = line.trim().match(/^g1_fr(\d+)\.flag$/)
    if (m) alreadyDone.add('FR-' + m[1].padStart(2, '0'))
  }
}
if (alreadyDone.size > 0) log('  sentinel pre-check: Gate 1 already PASS for ' + [...alreadyDone].join(', ') + ' — skipping TDD agents')

// ════════════════════════════════════════════════════════════════════════
// Phase: Per-FR TDD (script-driven loop; one narrow agent per FR)
// ════════════════════════════════════════════════════════════════════════
phase('Per-FR TDD')
const gate1Pass = []
const gate1Fail = []
let p3MidPushed = false
const p3MidThreshold = Math.ceil(frIds.length / 2)  // PUSH ③ trigger: ≥50% FRs Gate 1 PASS
for (const frId of frIds) {
  if (alreadyDone.has(frId)) {
    log('  ' + frId + ' — sentinel exists, Gate 1 PASS (skip TDD)')
    gate1Pass.push(frId)
  } else {
    log('  === ' + frId + ' (' + (frTitle[frId] || '') + ') — TDD chain ===')
    const frReport = await agent(
      'YOU ARE THE IMPLEMENTER for ' + frId + ' (' + (frTitle[frId] || '') + '). Run the full TDD chain for THIS ONE FR.\n'
      + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
      + 'Run these harness steps IN ORDER (each is a bash command; read its output before the next):\n'
      + '1. TDD-RED:    `' + PY + ' ' + REPO + '/harness_cli.py run-fr-step --phase 3 --fr-id ' + frId + ' --step TDD-RED --project ' + REPO + ' --srs 01-requirements/SRS.md`\n'
      + '2. MIRROR:     `' + PY + ' ' + REPO + '/harness_cli.py check-test-mirrors-spec --phase 3 --fr-id ' + frId + ' --test-file tests/test_*.py --project ' + REPO + '`\n'
      + '3. TDD-GREEN:  `' + PY + ' ' + REPO + '/harness_cli.py run-fr-step --phase 3 --fr-id ' + frId + ' --step TDD-GREEN --project ' + REPO + ' --srs 01-requirements/SRS.md`\n'
      + '4. TDD-IMPROVE:`' + PY + ' ' + REPO + '/harness_cli.py run-fr-step --phase 3 --fr-id ' + frId + ' --step TDD-IMPROVE --project ' + REPO + '`\n'
      + '5. GATE1:      `' + PY + ' ' + REPO + '/harness_cli.py run-fr-step --phase 3 --fr-id ' + frId + ' --step GATE1 --project ' + REPO + '`\n'
      + '   Gate 1 thresholds: linting(90) type_safety(85) test_coverage(80).\n'
      + '   - PASS → done.\n'
      + '   - FAIL → fix failing dims (ruff check . --fix; add tests for coverage; fix pyright errors), re-run GATE1. Max 3 rounds.\n'
      + '   - Still failing after 3 → report FAIL.\n'
      + '   Each run-fr-step auto-pushes on completion (idempotent). Crash recovery: `resume-fr-step --phase 3 --project ' + REPO + '`.\n\n'
      + 'Implement the module per SPEC.md (read ' + REPO + '/SPEC.md for ' + frId + ') + SAD.md module mapping. Write source under 03-development/src/ (or src/taskq/ per SAD), tests under tests/. Docstrings must include [' + frId + '] reference (NFR-05).\n\n'
      + 'Report final line: "' + frId + ' GATE1: PASS" or "' + frId + ' GATE1: FAIL — <reason>".\n\n'
      + 'SCOPE RULES:\n- DO NOT implement any FR OTHER than ' + frId + '.\n- DO NOT run run-gate (Gate 2), advance-phase, or push-milestone.\n- DO NOT modify harness/ (HR-17).\n- ONLY the 5 steps above for ' + frId + '.',
      { label: 'tdd-' + frId, phase: 'Per-FR TDD', agentType: 'general-purpose' },
    )
    const passed = typeof frReport === 'string' && new RegExp(frId + '\\s*GATE1:\\s*PASS').test(frReport)
    if (passed) { gate1Pass.push(frId); log('  ' + frId + ' Gate 1 PASS (' + gate1Pass.length + '/' + frIds.length + ')') }
    else { gate1Fail.push(frId); log('  ' + frId + ' Gate 1 FAIL') }
  }

  // PUSH ③ p3-mid — fire once when ≥50% FRs have Gate 1 PASS (but not yet all done).
  if (!p3MidPushed && gate1Pass.length >= p3MidThreshold && gate1Pass.length < frIds.length) {
    p3MidPushed = true
    log('  ≥50% FRs Gate 1 PASS (' + gate1Pass.length + '/' + frIds.length + ') — pushing p3-mid milestone')
    await agent(
      'YOU ARE THE P3 MID-MILESTONE PUSHER (≥50% FRs Gate 1 PASS).\n'
      + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
      + '0. GUARD: `git -C ' + REPO + ' log --oneline --grep="p3-mid" -1`. If a p3-mid commit already exists, report "MILESTONE: PASS (already pushed)" and stop — do NOT push again.\n'
      + '1. Command: `' + PY + ' ' + REPO + '/harness_cli.py push-milestone --type p3-mid --project ' + REPO
      + ' --fr-done ' + gate1Pass.length + ' --fr-total ' + frIds.length + ' --fr-ids ' + gate1Pass.join(',') + '`\n'
      + '   Writes HANDOVER.md + commits + pushes. If a hook blocks, reword commit to start with `chore(harness):` (NOT --no-verify), retry.\n\n'
      + 'Report: "MILESTONE: PASS|FAIL — <details>".\n\n'
      + 'SCOPE RULES:\n- DO NOT run run-gate / advance-phase / implement FRs.\n- ONLY push-milestone p3-mid.',
      { label: 'milestone-p3-mid', phase: 'Per-FR TDD', agentType: 'general-purpose' },
    )
  }
}
if (gate1Fail.length) {
  return { error: 'Phase 3: Gate 1 FAILED for FR(s): ' + gate1Fail.join(', ') + ' (escalate — fix code/tests, resume-fr-phase)', gate1Pass, gate1Fail }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Milestones (p3-mid pushed in-loop at ≥50%; p3-pre-gate2 here = all done)
// ════════════════════════════════════════════════════════════════════════
phase('Milestones')
log('All ' + frIds.length + ' FRs Gate 1 PASS — push p3-pre-gate2 (last stable snapshot before Gate 2)')
const preGate2Report = await agent(
  'YOU ARE THE P3 MILESTONE PUSHER. Push the pre-Gate-2 milestone.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + '0. GUARD: `git -C ' + REPO + ' log --oneline --grep="p3-pre-gate2" -1`. If a p3-pre-gate2 commit already exists, report "MILESTONE: PASS (already pushed)" and stop.\n'
  + '1. Command: `' + PY + ' ' + REPO + '/harness_cli.py push-milestone --type p3-pre-gate2 --project ' + REPO + ' --fr-ids ' + gate1Pass.join(',') + '`\n'
  + '   Writes HANDOVER.md + commits + pushes. If a hook blocks, reword commit to start with `chore(harness):` (NOT --no-verify), retry.\n\n'
  + 'Report: "MILESTONE: PASS|FAIL — <details>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run run-gate or advance-phase.\n- ONLY push-milestone p3-pre-gate2.',
  { label: 'milestone-pre-gate2', phase: 'Milestones', agentType: 'general-purpose' },
)
if (!(typeof preGate2Report === 'string' && /MILESTONE:\s*PASS/.test(preGate2Report))) {
  log('  WARNING: p3-pre-gate2 milestone push did not confirm PASS — continuing to Gate 2 (milestone is a snapshot, not a hard gate)')
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Gate 2 (run-gate → eval dims → finalize → D4 60% → retry; HR-08)
// ════════════════════════════════════════════════════════════════════════
phase('Gate 2')
log('Gate 2 exit (composite ≥75, 9 dims: 8 self-scored + traceability framework-owned)')
let gate2Pass = false, gate2Report = ''
for (let round = 1; round <= 3; round++) {
  log('  Gate 2 round ' + round + '/3')
  gate2Report = await agent(
    'YOU ARE THE GATE-2 ORCHESTRATOR (Phase 3 exit). ROUND ' + round + '.\n'
    + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
    + 'Steps:\n'
    + '0. TRACE-PRECHECK: `' + PY + ' ' + REPO + '/harness_cli.py build-trace-attestation --project ' + REPO + ' --write 2>&1 | tail -4`. If output contains "wrote canonical", commit immediately: `git -C ' + REPO + ' add .methodology/trace/attestation.json && git -C ' + REPO + ' commit -m "trace: regen attestation before Gate 2"`. Prevents trace_dirt from blocking finalize-gate.\n'
    + '1. G2a: `' + PY + ' ' + REPO + '/harness_cli.py run-gate --gate 2 --phase 3 --project ' + REPO + '` — read the printed evaluation prompt.\n'
    + '2. G2b: Evaluate ALL Gate 2 dimensions inline per ' + REPO + '/harness/ssi/prompts/evaluate_dimension.md. Write ' + REPO + '/.sessi-work/gate2_result.json.\n'
    + '   Dims: linting(90) type_safety(85) test_coverage(80) security(80) secrets_scanning(100) license_compliance(100) integration_coverage(60) test_assertion_quality(60).\n'
    + '   NOTE: mutation_testing is disabled by default via .methodology/harness_config.json (mutation_testing=false). If enabled, the harness auto-includes it and re-normalises the composite score.\n'
    + '   NOTE: traceability is FRAMEWORK-OWNED — do NOT score it; the harness injects it in finalize-gate.\n'
    + '   For any failing dim: fix the ROOT CAUSE in code (ruff/pyright/add tests/bandit/mutation), re-run the tool, update the score. (No auto-fix engine.)\n'
    + '3. G2c: `' + PY + ' ' + REPO + '/harness_cli.py finalize-gate --gate 2 --phase 3 --project ' + REPO + '`.\n'
    + '   - If blocked by traceability: `' + PY + ' ' + REPO + '/harness_cli.py build-trace-attestation --project ' + REPO + ' --write` then `git -C ' + REPO + ' add .methodology/trace/attestation.json && git -C ' + REPO + ' commit -m "trace: regen attestation"`, re-run finalize.\n'
    + '4. D4: `' + PY + ' ' + REPO + '/harness_cli.py spec-coverage-check --project ' + REPO + ' --threshold 60.0`. FAIL → add missing test implementations, re-run.\n\n'
    + 'finalize-gate (G2c) writes HANDOVER.md + pushes on PASS. Report final line: "GATE2: PASS" (composite ≥75 AND all dims ≥ threshold AND D4 ≥60%) or "GATE2: FAIL — <failing dims>".\n\n'
    + 'SCOPE RULES:\n- DO NOT run advance-phase or push-milestone p3-post-gate2 (next phase does that).\n- DO NOT edit .sessi-work/gate2_result.json to fake scores — fix the code.\n- DO NOT modify harness/ (HR-17).\n- ONLY run-gate/eval/finalize/spec-coverage + code fixes.',
    { label: 'gate2-r' + round, phase: 'Gate 2', agentType: 'general-purpose' },
  )
  // Detect session-limit / rate-limit failures: agent returns null or empty when blocked.
  if (gate2Report === null || gate2Report === undefined || (typeof gate2Report === 'string' && gate2Report.length < 10)) {
    log('  Gate 2 agent blocked (session limit / rate limit) — aborting retries, resume after quota reset')
    return { session_limit_blocked: true, gate: 2, message: 'Agent hit session/rate limit during Gate 2 evaluation. Resume after quota reset — GUARD checks will skip completed FRs.' }
  }
  gate2Pass = typeof gate2Report === 'string' && /GATE2:\s*PASS/.test(gate2Report)
  if (gate2Pass) { log('  Gate 2 PASS'); break }
  log('  Gate 2 not yet PASS — retry round ' + (round + 1))
}
if (!gate2Pass) {
  return { error: 'Gate 2 did not PASS in 3 rounds (HR-08; write deferred_fixes.md + escalate to human)', raw: String(gate2Report ?? '').slice(-600) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Advance (p3-post-gate2 push + advance-phase --completed 3)
// ════════════════════════════════════════════════════════════════════════
phase('Advance')
log('p3-post-gate2 milestone + advance-phase --completed 3 (TDD-PRECHECK enforced)')
const advanceReport = await agent(
  'YOU ARE THE PHASE-3 EXIT ORCHESTRATOR. Push formal exit + advance to Phase 4.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '0. GUARD — already advanced? `PHASE=$(jq -r '.current_phase // 0' ' + REPO + '/.methodology/state.json 2>/dev/null); echo "current_phase=$PHASE"; [ "$PHASE" -ge 4 ]`. If Phase 4 is confirmed, report "ADVANCE: PASS (already advanced)" and stop.\n'
  + '1. GUARD + PUSH ⑤ p3-post-gate2: `git -C ' + REPO + ' log --oneline --grep="p3-post-gate2" -1`. If a commit exists, skip the push. Else: `' + PY + ' ' + REPO + '/harness_cli.py push-milestone --type p3-post-gate2 --project ' + REPO + ' --fr-ids ' + gate1Pass.join(',') + '`\n'
  + '   Pre-flight (enforced): gate2_result.json composite ≥75 + per-FR Gate 1 sentinel .sessi-work/sentinels/g1_<fr>.flag exists for every FR. If BLOCKED, read the error list and fix.\n'
  + '2. advance-phase: `' + PY + ' ' + REPO + '/harness_cli.py advance-phase --completed 3 --project ' + REPO + '`\n'
  + '   TDD-PRECHECK enforced: gitleaks + ruff + mypy + pytest --cov-fail-under=100 + spec-coverage 60%. Fix any blocker, re-run.\n'
  + '   PHASE-TRUTH (HR-11): if advance-phase fails on Phase Truth (<90%), check phase_truth_verifier output in .sessi-work/, fix the failing phase-link/gate artifact, re-run (max 3, then escalate to human).\n'
  + '3. Read ' + REPO + '/.methodology/state.json; confirm current_phase = 4 (advance-phase atomically writes state.json when complete).\n\n'
  + 'Report: "ADVANCE: PASS|FAIL — <details>". PHASE_4_PLAN: ' + REPO + '/.methodology/phase4_plan.md\n\n'
  + 'SCOPE RULES:\n- DO NOT re-implement FRs.\n- DO NOT use --no-verify.\n- DO NOT modify harness/ (HR-17).\n- ONLY push-milestone p3-post-gate2 + advance-phase + verify HANDOVER.md.',
  { label: 'advance', phase: 'Advance', agentType: 'general-purpose' },
)

if (!advanceReport || !/ADVANCE:\s*PASS/.test(advanceReport)) {
  return { error: 'Advance phase did not confirm PASS — check HANDOVER.md + state.json. If Phase 4 is confirmed, resume workflow to verify.', raw: String(advanceReport ?? '').slice(-400) }
}
log('Phase 3 workflow complete. Open .methodology/phase4_plan.md to continue.')
return {
  phase: 3,
  fr_count: frIds.length,
  gate1_pass: gate1Pass,
  gate2_status: gate2Pass ? 'PASS' : 'unknown',
  advance_status: 'PASS',
  artifacts: ['03-development/src/', 'tests/', '.methodology/gate2_result.json', 'HANDOVER.md'],
  notes: 'Phase 3 complete per phase3_plan.md v2.12.0. All FRs Gate 1 PASS + Gate 2 PASS. Phase 4 (Testing) ready.',
}
