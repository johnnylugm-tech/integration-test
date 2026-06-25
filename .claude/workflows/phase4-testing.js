// Phase 4 — Testing (faithful to .methodology/phase4_plan.md v2.12.0)
//
// Structure: FR-loop型 + adversarial bug hunt + Gate 3 (15 dims) exit.
// CHECKPOINT-0 TEST_PLAN → per-FR GATE1-DELTA → TEST_RESULTS/COVERAGE →
// Step 4b bug hunt (adversarial_review is a Gate 3 dim, needs bug_hunt_report.json)
// → Gate 3 → p4-pre-gate3 milestone + advance.
//
// Playbook lessons: NO import/fs/process/schema:, Bash CLI, SCOPE RULES,
// PY = .venv/bin/python, scriptPath launch.

export const meta = {
  name: 'phase4-testing',
  description: 'Phase 4 Testing — TEST_PLAN + per-FR GATE1-DELTA + adversarial bug hunt + Gate 3 (15 dims) exit (phase4_plan.md v2.12.0)',
  phases: [
    { title: 'Entry & Preflight' },
    { title: 'Test Plan' },
    { title: 'Env Check' },
    { title: 'Load FRs' },
    { title: 'Per-FR Delta' },
    { title: 'Coverage' },
    { title: 'Bug Hunt' },
    { title: 'Gate 3' },
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
// Bug hunt should use a DIFFERENT model from the developer (minimise same-source bias).
const HUNT_MODEL = (args && typeof args === 'object' && typeof args.huntModel === 'string') ? args.huntModel : 'claude-opus-4-8'
log('REPO = ' + REPO + ' | PY = ' + PY + ' | HUNT_MODEL = ' + HUNT_MODEL)

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
// Phase: Entry & Preflight (incl. reliability lint + config liveness — P4+ blocking)
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

const _shortcut = await maybeShortcut(4)
if (_shortcut) return _shortcut

phase('Entry & Preflight')
log('ENTRY-CHECK Gate2 + run-phase 4 (reliability lint + config liveness) + handoff + CI')
const preflightReport = await agent(
  'YOU ARE THE PHASE-4 PREFLIGHT ORCHESTRATOR. Run bash in order; report.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. ENTRY-CHECK: confirm .methodology/quality_manifest.json records Gate 2 PASS from P3 (else FAIL → return to Phase 3).\n'
  + '2. PREFLIGHT: `' + PY + ' ' + REPO + '/harness_cli.py run-phase --phase 4 --project ' + REPO + '`. FAIL → fix, re-run (max 3). P4+ blocking fixes:\n'
  + '   - reliability lint: subprocess.run/Popen without timeout=, tempfile.mkstemp outside try/finally, os.path.exists before open/unlink (TOCTOU), time.sleep inside async def.\n'
  + '   - config liveness: env keys read in code but absent from .env.example/docker-compose/deployment. Add the key (or fix the typo).\n'
  + '3. HANDOFF: `' + PY + ' ' + REPO + '/harness_cli.py validate-handoff --from-phase 3 --project ' + REPO + '`. Must exit 0.\n'
  + '4. PREFLIGHT-CI: harness_quality_gate.yml + prepare-commit-msg exist; state.json current_phase=4. If stale: init-project --phase 4 --overwrite.\n\n'
  + 'Report: "PREFLIGHT: PASS" or "PREFLIGHT: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT generate TEST_PLAN / run TDD / run-gate / bug hunt.\n- DO NOT run advance-phase/push-milestone.\n- DO NOT modify harness/.\n- ONLY preflight commands + fixes.',
  { label: 'preflight', phase: 'Entry & Preflight', agentType: 'general-purpose' },
)
if (!(typeof preflightReport === 'string' && /PREFLIGHT:\s*PASS/.test(preflightReport))) {
  return { error: 'Phase 4 preflight did not PASS', raw: String(preflightReport ?? '').slice(-600) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Test Plan (CHECKPOINT-0 — generate TEST_PLAN.md before per-FR testing)
// ════════════════════════════════════════════════════════════════════════
phase('Test Plan')
log('Generate 04-testing/TEST_PLAN.md from SRS FR acceptance criteria')
const testPlanReport = await agent(
  'YOU ARE THE P4 TEST PLAN AUTHOR. Generate TEST_PLAN.md (runs once before per-FR testing).\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps (create 04-testing/ if missing):\n'
  + '1. Read 01-requirements/SRS.md FR acceptance criteria + .methodology/quality_manifest.json FR list.\n'
  + '2. Write ' + REPO + '/04-testing/TEST_PLAN.md. For each FR: test case ID, description, input, expected output, priority. Include positive, negative, boundary, and edge-case categories. Cover ALL FRs + NFRs.\n'
  + '3. Verify TEST_PLAN.md covers every FR from the manifest.\n\n'
  + 'Report: "TEST-PLAN: PASS" or "TEST-PLAN: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run TDD/run-gate/bug-hunt/advance.\n- DO NOT modify harness/.\n- ONLY author TEST_PLAN.md.',
  { label: 'test-plan', phase: 'Test Plan', agentType: 'general-purpose' },
)
if (!(typeof testPlanReport === 'string' && /TEST-PLAN:\s*PASS/.test(testPlanReport))) {
  return { error: 'Phase 4 TEST_PLAN did not PASS', raw: String(testPlanReport ?? '').slice(-500) }
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
  + '1. `' + PY + ' ' + REPO + '/harness_cli.py run-env-check --phase 4 --project ' + REPO + '` — read the printed prompt.\n'
  + '2. Evaluate inline and write ' + REPO + '/.sessi-work/env_check_result.json.\n'
  + '3. `' + PY + ' ' + REPO + '/harness_cli.py finalize-env-check --phase 4 --project ' + REPO + '`.\n\n'
  + 'Report: "ENV-CHECK: PASS" or "ENV-CHECK: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run TDD/gate/bug-hunt/advance commands.\n- ONLY env-check.',
  { label: 'env-check', phase: 'Env Check', agentType: 'general-purpose' },
)
if (!(typeof envReport === 'string' && /ENV-CHECK:\s*PASS/.test(envReport))) {
  return { error: 'Phase 4 env-check did not PASS', raw: String(envReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Load FRs
// ════════════════════════════════════════════════════════════════════════
phase('Load FRs')
log('load-context --phase 4 → fr_ids')
const ctxResult = await agent(
  'Use ONLY the Bash tool. Run:\n'
  + '1. `mkdir -p ' + REPO + '/.sessi-work`\n'
  + '2. `' + PY + ' ' + REPO + '/harness_cli.py load-context --phase 4 --project ' + REPO + ' --json > ' + REPO + '/.sessi-work/phase4_ctx.json`\n'
  + '3. `cat ' + REPO + '/.sessi-work/phase4_ctx.json`\n'
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
let p4MidPushed = false
const p4MidThreshold = Math.ceil(frIds.length / 2)  // PUSH ⑤ trigger: ≥50% FRs Gate 1 PASS
for (const frId of frIds) {
  log('  === ' + frId + ' — GATE1-DELTA ===')
  const frReport = await agent(
    'YOU ARE THE TEST VERIFIER for ' + frId + ' (' + (frTitle[frId] || '') + '). Re-evaluate Gate 1 for THIS ONE FR.\n'
    + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
    + 'Steps:\n'
    + '1. `' + PY + ' ' + REPO + '/harness_cli.py run-fr-step --phase 4 --fr-id ' + frId + ' --step GATE1-DELTA --project ' + REPO + '`\n'
    + '   - PASS → done.\n'
    + '   - FAIL → full TDD auto-triggered: TDD-RED → TDD-GREEN → TDD-IMPROVE → GATE1 (each for ' + frId + '). Max 3 rounds. Still failing → report FAIL.\n'
    + '   If ' + frId + '’s code is unchanged since last Gate 1 PASS, this passes immediately.\n\n'
    + 'Report final line: "' + frId + ' GATE1: PASS" or "' + frId + ' GATE1: FAIL — <reason>".\n\n'
    + 'SCOPE RULES:\n- DO NOT touch any FR OTHER than ' + frId + '.\n- DO NOT run run-gate / bug-hunt / advance-phase / push-milestone.\n- DO NOT modify harness/.\n- ONLY GATE1-DELTA (+ full TDD if needed) for ' + frId + '.',
    { label: 'delta-' + frId, phase: 'Per-FR Delta', agentType: 'general-purpose' },
  )
  const passed = typeof frReport === 'string' && new RegExp(frId + '\\s*GATE1:\\s*PASS').test(frReport)
  if (passed) { gate1Pass.push(frId); log('  ' + frId + ' Gate 1 PASS') }
  else { gate1Fail.push(frId); log('  ' + frId + ' Gate 1 FAIL') }

  // PUSH ⑤ p4-mid — fire once when ≥50% FRs have Gate 1 PASS (but not yet all done).
  if (!p4MidPushed && gate1Pass.length >= p4MidThreshold && gate1Pass.length < frIds.length) {
    p4MidPushed = true
    log('  ≥50% FRs Gate 1 PASS (' + gate1Pass.length + '/' + frIds.length + ') — pushing p4-mid milestone')
    await agent(
      'YOU ARE THE P4 MID-MILESTONE PUSHER (≥50% FRs Gate 1 PASS).\n'
      + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
      + '0. GUARD: `git -C ' + REPO + ' log --oneline --grep="p4-mid" -1`. If exists, report "MILESTONE: PASS (already pushed)" and stop.\n'
      + '1. Command: `' + PY + ' ' + REPO + '/harness_cli.py push-milestone --type p4-mid --project ' + REPO
      + ' --fr-done ' + gate1Pass.length + ' --fr-total ' + frIds.length + ' --fr-ids ' + gate1Pass.join(',') + '`\n'
      + 'Writes HANDOVER.md + commits + pushes. If a hook blocks, reword commit to start with `chore(harness):` (NOT --no-verify), retry.\n\n'
      + 'Report: "MILESTONE: PASS|FAIL — <details>".\n\n'
      + 'SCOPE RULES:\n- DO NOT run run-gate / bug-hunt / advance-phase.\n- ONLY push-milestone p4-mid.',
      { label: 'milestone-p4-mid', phase: 'Per-FR Delta', agentType: 'general-purpose' },
    )
  }
}
if (gate1Fail.length) {
  return { error: 'Phase 4: Gate 1 FAILED for FR(s): ' + gate1Fail.join(', ') + ' (escalate)', gate1Pass, gate1Fail }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Coverage (TEST_RESULTS.md + COVERAGE_REPORT.md)
// ════════════════════════════════════════════════════════════════════════
phase('Coverage')
log('Generate TEST_RESULTS.md + COVERAGE_REPORT.md (cross-artifact validated at Gate 3)')
const coverageReport = await agent(
  'YOU ARE THE P4 COVERAGE AUTHOR. Generate the test-results + coverage deliverables.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. TEST_RESULTS: write ' + REPO + '/04-testing/TEST_RESULTS.md — summarise test execution: cases run, pass/fail, deferred issues. (Real execution is enforced by advance-phase pytest --cov-fail-under=100, not by string-matching this doc.)\n'
  + '2. COVERAGE: run `' + PY + ' -m pytest --cov=03-development/src --cov-report=term-missing -q | tee ' + REPO + '/04-testing/coverage_raw.txt` then `' + PY + ' -m coverage report --format=total`. Write ' + REPO + '/04-testing/COVERAGE_REPORT.md with overall coverage % (≥80% for Gate 3), per-module breakdown, uncovered lines.\n'
  + '   WARNING: cross_artifact.py validates these numbers against live pytest --cov at Gate 3 — fabricated numbers are caught. Use REAL numbers.\n\n'
  + 'Report: "COVERAGE: PASS" or "COVERAGE: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run run-gate / bug-hunt / advance.\n- DO NOT modify harness/.\n- DO NOT fabricate coverage numbers.\n- ONLY generate the 2 docs from real pytest output.',
  { label: 'coverage', phase: 'Coverage', agentType: 'general-purpose' },
)
if (!(typeof coverageReport === 'string' && /COVERAGE:\s*PASS/.test(coverageReport))) {
  return { error: 'Phase 4 coverage docs did not PASS', raw: String(coverageReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Bug Hunt (Step 4b — adversarial_review Gate 3 dim needs bug_hunt_report.json)
// ════════════════════════════════════════════════════════════════════════
phase('Bug Hunt')
log('Adversarial bug hunt (targets → scout → hunters → verify → synthesize → resolve)')
const huntReport = await agent(
  'YOU ARE THE ADVERSARIAL BUG HUNT ORCHESTRATOR (Step 4b, before Gate 3).\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'The Gate 3 dimension adversarial_review (threshold 100) BLOCKS the gate if .methodology/bug_hunt_report.json is absent or any confirmed critical/high finding is still "open". Run the hunt NOW.\n\n'
  + 'Steps:\n'
  + '1. HUNT-TARGETS: `' + PY + ' ' + REPO + '/harness_cli.py bug-hunt-targets --project ' + REPO + '` → .methodology/bug_hunt_targets.json (CRG hubs + mutation survivors + integration gaps).\n'
  + '2. HUNT-RUN: execute the 4-phase protocol in ' + REPO + '/harness/ssi/prompts/hunt_bugs.md (scout → lens hunters → adversarial verify → synthesize). Reference workflow: ' + REPO + '/harness/templates/workflows/hunt-bugs.js. Spawn hunters/verifiers as sub-agents (you have the Agent tool); use model ' + HUNT_MODEL + ' (DIFFERENT from the developer model to minimise same-source bias). Build the CRG graph first if needed.\n'
  + '   Output: .methodology/bug_hunt_report.json (schema: harness/schemas/bug_hunt_report.schema.json) + human markdown under 03-development/.audit/.\n'
  + '3. HUNT-RESOLVE: for EACH confirmed critical/high finding set resolution.status:\n'
  + '   - resolved: include fix_commit (SHA) or repro_test (path in tests/).\n'
  + '   - refuted: include refute_evidence (explanation + line citation).\n'
  + '   Medium/low: record only (not required to resolve before Gate 3).\n\n'
  + 'Report: "BUG-HUNT: PASS" (report written AND all confirmed critical/high resolved-or-refuted) or "BUG-HUNT: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run run-gate (Gate 3) / advance-phase / push-milestone.\n- DO NOT modify harness/ (running its scripts/prompts is fine; editing is NOT — HR-17).\n- ONLY targets + hunt + resolve + write bug_hunt_report.json.',
  { label: 'bug-hunt', phase: 'Bug Hunt', agentType: 'general-purpose', model: HUNT_MODEL },
)
if (!(typeof huntReport === 'string' && /BUG-HUNT:\s*PASS/.test(huntReport))) {
  return { error: 'Phase 4 bug hunt did not PASS (Gate 3 adversarial_review will block)', raw: String(huntReport ?? '').slice(-600) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Gate 3 (run-gate → eval 15 dims → finalize → D4 80%; HR-08)
// ════════════════════════════════════════════════════════════════════════
phase('Gate 3')
log('Gate 3 exit (composite ≥80, 15 dims: 12 self-scored + traceability/architecture/adversarial_review framework-owned)')
let gate3Pass = false, gate3Report = '', gate3Blocked = false
for (let round = 1; round <= 3; round++) {
  log('  Gate 3 round ' + round + '/3')
  gate3Report = await agent(
    'YOU ARE THE GATE-3 ORCHESTRATOR (Phase 4 exit). ROUND ' + round + '.\n'
    + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
    + 'Steps:\n'
    + '0. TRACE-PRECHECK: `' + PY + ' ' + REPO + '/harness_cli.py build-trace-attestation --project ' + REPO + ' --write 2>&1 | tail -4`. If output contains "wrote canonical", commit immediately: `git -C ' + REPO + ' add .methodology/trace/attestation.json && git -C ' + REPO + ' commit -m "trace: regen attestation before Gate 3"`. Prevents trace_dirt from blocking finalize-gate.\n'
    + '1. G3a: `' + PY + ' ' + REPO + '/harness_cli.py run-gate --gate 3 --phase 4 --project ' + REPO + '` (CRG recon runs inside automatically). Read the printed evaluation prompt.\n'
    + '2. G3b: Evaluate ALL Gate 3 dimensions inline per ' + REPO + '/harness/ssi/prompts/evaluate_dimension.md. Write ' + REPO + '/.sessi-work/gate3_result.json.\n'
    + '   15 dims: linting(90) type_safety(85) test_coverage(80) security(80) secrets_scanning(100) license_compliance(100) integration_coverage(60) architecture(80) readability(80) error_handling(80) documentation(75) test_assertion_quality(60) performance(75).\n'
    + '   NOTE: mutation_testing is disabled by default via .methodology/harness_config.json (mutation_testing=false). If enabled, the harness auto-includes it and re-normalises the composite score.\n'
    + '   FRAMEWORK-OWNED (do NOT self-score): traceability + architecture (harness CRG override) + adversarial_review (from bug_hunt_report.json).\n'
    + '   For any failing dim: fix ROOT CAUSE in code (ruff/pyright/tests/bandit/radon/ast-error-handling/pytest-benchmark), re-run the tool, update score. If architecture=0 due to Orchestrator/hub-and-spoke: complete DA challenge + set da_waiver.\n'
    + '3. G3c: `' + PY + ' ' + REPO + '/harness_cli.py finalize-gate --gate 3 --phase 4 --project ' + REPO + '`.\n'
    + '   - If blocked by traceability: `build-trace-attestation --project ' + REPO + ' --write` + commit attestation.json, re-run finalize.\n'
    + '4. D4: `' + PY + ' ' + REPO + '/harness_cli.py spec-coverage-check --project ' + REPO + ' --threshold 80.0`. FAIL → add missing tests, re-run.\n\n'
    + 'finalize-gate (G3c) writes HANDOVER.md + pushes on PASS. Report final line: "GATE3: PASS" (composite ≥80 AND all dims ≥ threshold AND D4 ≥80%) or "GATE3: FAIL — <failing dims>".\n\n'
    + 'SCOPE RULES:\n- DO NOT run advance-phase.\n- DO NOT edit gate3_result.json to fake scores — fix the code.\n- DO NOT modify harness/ (HR-17).\n- ONLY run-gate/eval/finalize/spec-coverage + code fixes.',
    { label: 'gate3-r' + round, phase: 'Gate 3', agentType: 'general-purpose' },
  )
  // Detect session-limit / rate-limit failures: agent returns null or empty when blocked.
  if (gate3Report === null || gate3Report === undefined || (typeof gate3Report === 'string' && gate3Report.length < 10)) {
    gate3Blocked = true
    log('  Gate 3 agent blocked (session limit / rate limit) — aborting retries, resume after quota reset')
    break
  }
  gate3Pass = typeof gate3Report === 'string' && /GATE3:\s*PASS/.test(gate3Report)
  if (gate3Pass) { log('  Gate 3 PASS'); break }
  log('  Gate 3 not yet PASS — retry round ' + (round + 1))
}
if (gate3Blocked) {
  return { session_limit_blocked: true, gate: 3, message: 'Agent hit session/rate limit during Gate 3 evaluation. Resume after quota reset — GUARD checks will skip completed FRs.' }
}
if (!gate3Pass) {
  return { error: 'Gate 3 did not PASS in 3 rounds (HR-08; write deferred_fixes.md + escalate to human)', raw: String(gate3Report ?? '').slice(-600) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Advance (p4-pre-gate3 already snapshotted by Gate3; advance --completed 4)
// ════════════════════════════════════════════════════════════════════════
phase('Advance')
log('p4-pre-gate3 milestone + advance-phase --completed 4 (TDD-PRECHECK enforced)')
const advanceReport = await agent(
  'YOU ARE THE PHASE-4 EXIT ORCHESTRATOR. Advance to Phase 5.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '0. GUARD — already advanced? `PHASE=$(jq -r '.current_phase // 0' ' + REPO + '/.methodology/state.json 2>/dev/null); echo "current_phase=$PHASE"; [ "$PHASE" -ge 5 ]`. If Phase 5 is confirmed, report "ADVANCE: PASS (already advanced)" and stop.\n'
  + '1. PUSH ⑥ p4-pre-gate3 (if not already pushed): `' + PY + ' ' + REPO + '/harness_cli.py push-milestone --type p4-pre-gate3 --project ' + REPO + ' --fr-ids ' + gate1Pass.join(',') + '`. (Idempotent; skip if already snapshotted.)\n'
  + '2. advance-phase: `' + PY + ' ' + REPO + '/harness_cli.py advance-phase --completed 4 --project ' + REPO + '`\n'
  + '   TDD-PRECHECK enforced: gitleaks + ruff + mypy + pytest --cov-fail-under=100 + spec-coverage 80%. Fix any blocker, re-run.\n'
  + '   PHASE-TRUTH (HR-11): if advance-phase fails on Phase Truth (<90%), check phase_truth_verifier output in .sessi-work/, fix the failing phase-link/gate artifact, re-run (max 3, then escalate to human).\n'
  + '3. Read ' + REPO + '/.methodology/state.json; confirm current_phase = 5 (advance-phase atomically writes state.json when complete).\n\n'
  + 'Report: "ADVANCE: PASS|FAIL — <details>". PHASE_5_PLAN: ' + REPO + '/.methodology/phase5_plan.md\n\n'
  + 'SCOPE RULES:\n- DO NOT re-do P4 testing.\n- DO NOT use --no-verify.\n- DO NOT modify harness/ (HR-17).\n- ONLY push-milestone p4-pre-gate3 + advance-phase + verify HANDOVER.md.',
  { label: 'advance', phase: 'Advance', agentType: 'general-purpose' },
)

if (!advanceReport || !/ADVANCE:\s*PASS/.test(advanceReport)) {
  return { error: 'Advance phase did not confirm PASS — check HANDOVER.md + state.json. If Phase 5 is confirmed, resume workflow to verify.', raw: String(advanceReport ?? '').slice(-400) }
}
log('Phase 4 workflow complete. Open .methodology/phase5_plan.md to continue.')
return {
  phase: 4,
  fr_count: frIds.length,
  gate1_pass: gate1Pass,
  gate3_status: gate3Pass ? 'PASS' : 'unknown',
  advance_status: 'PASS',
  artifacts: ['04-testing/TEST_PLAN.md', '04-testing/TEST_RESULTS.md', '04-testing/COVERAGE_REPORT.md', '.methodology/bug_hunt_report.json', '.methodology/gate3_result.json', 'HANDOVER.md'],
  notes: 'Phase 4 complete per phase4_plan.md v2.12.0. All FRs Gate 1 PASS + bug hunt done + Gate 3 PASS. Phase 5 (Verification) ready.',
}
