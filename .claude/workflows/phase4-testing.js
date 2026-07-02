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
    { title: 'Manifest Integrity' },
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
// Phase: Entry & Preflight (incl. reliability lint + config liveness — P4+ blocking)
// ════════════════════════════════════════════════════════════════════════

phase('Entry & Preflight')
log('ENTRY-CHECK Gate2 + run-phase 4 (reliability lint + config liveness) + handoff + CI')
const preflightReport = await agent(
  'YOU ARE THE PHASE-4 PREFLIGHT ORCHESTRATOR. Run bash in order; report.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. ENTRY-CHECK: run EXACTLY this bash command to verify Gate 2 status (do NOT rely on reading the file yourself — use the command output):\n`' + PY + ' -c "import json; m=json.load(open(\'' + REPO + '/.methodology/quality_manifest.json\')); g2=(m.get(\'gate_results\',{}) or {}).get(\'gate2\',{}) or {}; print(\'GATE_VERIFIED\' if isinstance(g2,dict) and g2.get(\'quality_complete\') is True else \'GATE_MISSING\')"`\nIf GATE_MISSING → FAIL (return to Phase 3).\n'
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
log('run-env-check (root-cause fix: CLI exit code reflects ready flag)')
// Bug #127 root-cause fix (2026-06-27): `cmd_run_env_check` now returns
// exit 0 when ready=true and 1 when ready=false (previously always 0).
// Workflows check `$?` directly with no LLM orchestrator agent in the loop.
const envReport = await agent(
  'You MUST use the Bash tool. Run exactly:\n'
  + PY + ' ' + REPO + '/harness_cli.py run-env-check --phase 4 --project ' + REPO + '\n'
  + 'echo "ENV_CHECK_RC=$?"\n'
  + 'Return the raw stdout verbatim. Do not paraphrase.',
  { label: 'env-check', phase: 'Env Check', agentType: 'general-purpose' },
)
if (!(typeof envReport === 'string' && /ENV_CHECK_RC=0\b/.test(envReport))) {
  return { error: 'Phase 4 env-check did not PASS', raw: String(envReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Manifest Integrity (ported from phase3, 155ec07 + 286ccca)
// ════════════════════════════════════════════════════════════════════════
phase('Manifest Integrity')
// 2026-07-02 incident class: a sub-agent action (bare pytest → harness test
// CWD leak) can corrupt quality_manifest.json MID-RUN, not just before entry.
// Detect the three known corruption patterns (fr_ids truncated, traceability
// cleared, gate1 wiped) at entry AND re-check before the phase-exit push so
// corruption is never baked into a milestone commit.
const integrityCmd = PY + ' -c "import json, sys; m = json.load(open(\'' + REPO + '/.methodology/quality_manifest.json\')); ids = m.get(\'fr_ids\') or []; mt = m.get(\'fr_module_traceability\') or {}; g1 = (m.get(\'gate_results\',{}) or {}).get(\'gate1\',{}) or {}; ok_ids = len(ids) >= 2; ok_trace = len(mt) >= len(ids); ok_g1 = isinstance(g1, dict) and len(g1) >= len(ids); print(\'OK\' if (ok_ids and ok_trace and ok_g1) else json.dumps({\'BROKEN\': True, \'fr_ids_count\': len(ids), \'traceability_count\': len(mt), \'gate1_keys\': len(g1), \'recovery\': \'git checkout HEAD -- .methodology/quality_manifest.json\'}))"'
async function checkManifestIntegrity(phaseLabel, agentLabel) {
  const raw = await agent(
    'Run EXACTLY this command via the Bash tool and return its raw stdout verbatim. No commentary.\n`' + integrityCmd + '`',
    { label: agentLabel, phase: phaseLabel, agentType: 'general-purpose' },
  )
  const ok = typeof raw === 'string' && /^OK$/.test(String(raw).trim())
  if (!ok) log('  manifest integrity FAIL [' + agentLabel + ']: ' + String(raw ?? '').trim())
  return { ok, raw: String(raw ?? '').trim() }
}
const integrity0 = await checkManifestIntegrity('Manifest Integrity', 'manifest-integrity')
if (!integrity0.ok) {
  return { error: 'Manifest Integrity: quality_manifest.json appears corrupted', detail: integrity0.raw, recovery: 'git checkout HEAD -- .methodology/quality_manifest.json (verify HEAD is healthy first)', note: 'Working-tree manifest fails the P4+ shape check (fr_ids/traceability/gate1 per-FR records). A sub-agent likely wrote to it directly. Restore a healthy copy and re-run.' }
}
log('  manifest integrity OK')

// ════════════════════════════════════════════════════════════════════════
// Phase: Load FRs
// ════════════════════════════════════════════════════════════════════════
phase('Load FRs')
log('load-context --phase 4 → fr_ids')
// v15: retry loop — agent() + parseAgentJson both wrapped (Bug #2)
// v2.13.1: hardened against agent hallucination — verify file exists + non-empty
// fr_ids before accepting (Bug #122).
let ctx = null
const ctxFile = REPO + '/.sessi-work/phase4_ctx.json'
for (let attempt = 1; attempt <= 3; attempt++) {
  try {
    // Bug #134 fix (2026-06-28): validate JSON-parseable, not just non-zero size.
    // Previous `test -s FILE && echo FILE_OK_<size>` passed for partial writes.
    // Root-cause: use `python3 -c 'json.load(...)'` so incomplete JSON raises
    // mid-write → no FILE_OK marker → regen path triggered.
    // Bug #136 sibling: bash built via template literal (single quotes safe).
    const ctxCheckCmd = `${PY} -c "import json,os,sys; json.load(open('${ctxFile}')); print('FILE_OK_'+str(os.path.getsize('${ctxFile}')))" || echo FILE_MISSING`
    const existsRaw = await agent(
      `You MUST use the Bash tool. Run exactly:\n${ctxCheckCmd}\nReturn the raw stdout as your final message. Do not paraphrase.`,
      { label: 'ctx-check-' + attempt, phase: 'Load FRs', agentType: 'general-purpose' },
    )
    if (!/FILE_OK_\d+/.test(String(existsRaw ?? ''))) {
      log('  ctx file missing/invalid (attempt ' + attempt + ') — regenerating')
      const ctxRegenCmd = `${PY} ${REPO}/harness_cli.py load-context --phase 4 --project ${REPO} --json > ${ctxFile} && ${PY} -c "import json,os; json.load(open('${ctxFile}')); print('REGEN_OK_'+str(os.path.getsize('${ctxFile}')))"`
      await agent(
        `You MUST use the Bash tool. Run exactly:\n${ctxRegenCmd}\nReturn the raw stdout as your final message.`,
        { label: 'ctx-regen-' + attempt, phase: 'Load FRs', agentType: 'general-purpose' },
      )
      continue
    }
  } catch (e) { log('  ctx-check agent failed: ' + String(e.message ?? e).slice(0, 80)); continue }

  // Bug #135 fix (2026-06-28): emit parseable JSON via Python, not `cat`.
  // Root-cause: agent LLM paraphrased cat output into prose → balancedJsonAt
  // failed. Have Python emit a single JSON line with ONLY fr_ids + fr_count.
  let ctxResult = ''
  try {
    const ctxParseCmd = `${PY} -c "import json; d=json.load(open('${ctxFile}')); print(json.dumps({'fr_ids':d.get('fr_ids',[]),'fr_count':len(d.get('fr_ids',[])),'fr_details_keys':list((d.get('fr_details') or {}).keys())}))"`
    ctxResult = await agent(
      `You MUST use the Bash tool. Run exactly:\n${ctxParseCmd}\nReturn the raw stdout as your final message. Do not paraphrase. Do not add commentary.`,
      { label: 'load-ctx-a' + attempt, phase: 'Load FRs', agentType: 'general-purpose' },
    )
    if (!/"fr_count"\s*:\s*[1-9]\d*/.test(String(ctxResult ?? ''))) {
      log('  load-ctx agent did not return parseable JSON (attempt ' + attempt + '): ' + String(ctxResult ?? '').slice(0, 200))
      continue
    }
  } catch (e) { log('  load-ctx agent failed: ' + String(e.message ?? e).slice(0, 80)); continue }
  try {
    ctx = parseAgentJson(ctxResult, 'load-ctx')
    if (Array.isArray(ctx.fr_ids) && ctx.fr_ids.length > 0) break
    log('  load-ctx returned empty fr_ids (attempt ' + attempt + '): keys=' + Object.keys(ctx ?? {}).join(','))
    ctx = null
  } catch (e) { log('  load-ctx parse failed (attempt ' + attempt + '): ' + e.message.slice(0, 120)); ctx = null }
}
if (!ctx) return { error: 'Load FRs: ctx failed after 3 attempts', ctxFile }
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
  // L1 (ported from phase3): distinguish a session/rate-limit block (null/empty
  // agent return) from a real Gate 1 FAIL — a rate-limit mid-DELTA must not be
  // misreported as a code-quality failure. DELTA auto-skip makes resume safe.
  if (frReport === null || frReport === undefined || (typeof frReport === 'string' && frReport.length < 10)) {
    log('  ' + frId + ' agent blocked (session limit / rate limit) — aborting, resume after quota reset')
    return { session_limit_blocked: true, phase: 4, fr_id: frId, gate1Pass, message: 'Agent hit session/rate limit during ' + frId + ' GATE1-DELTA. Resume after quota reset — completed FRs skip via DELTA auto-satisfy.' }
  }
  // AUTHORITATIVE Gate 1 verdict (ported from phase3, 9fe2036): read the harness
  // quality_manifest — NOT the sub-agent's self-reported "GATE1: PASS" string. A
  // sub-agent can report PASS even when finalize-gate raised GateBlockedError,
  // silently advancing a FR the harness actually blocked (2026-06-30 incident).
  const verifyCmd = PY + ' -c "import json; g=(json.load(open(\'' + REPO + '/.methodology/quality_manifest.json\')).get(\'gate_results\',{}) or {}).get(\'gate1\',{}).get(\'' + frId + '\',{}) or {}; print(\'GATE1_VERIFIED_PASS\' if g.get(\'quality_complete\') is True else \'GATE1_VERIFIED_FAIL score=\'+str(g.get(\'score\')))"'
  const verdictRaw = await agent(
    'Run EXACTLY this command via the Bash tool and return its raw stdout verbatim. No commentary.\n`' + verifyCmd + '`',
    { label: 'gate1-verify-' + frId, phase: 'Per-FR Delta', agentType: 'general-purpose' },
  )
  const passed = typeof verdictRaw === 'string' && /GATE1_VERIFIED_PASS/.test(verdictRaw)
  if (passed) { gate1Pass.push(frId); log('  ' + frId + ' Gate 1 PASS [harness-verified]') }
  else { gate1Fail.push(frId); log('  ' + frId + ' Gate 1 FAIL [harness manifest qc != true; sub-agent self-report ignored]') }

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
    + '   For any failing dim: fix ROOT CAUSE in code (ruff/pyright/tests/bandit/readability_v2/ast-error-handling/pytest-benchmark), re-run the tool, update score. (readability tool is `python3 -m harness.toolchains.readability_v2` — NOT `radon mi` — per phase3/4/6_plan.md v2.12.0.) If architecture=0 due to Orchestrator/hub-and-spoke: complete DA challenge + set da_waiver.\n'
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
// Round loop (2026-07-02 audit finding, ported from phase3): advance-phase
// enforces more independent checks than any single prompt can safely
// enumerate, and a static checklist goes stale the moment harness adds or
// changes one. advance-phase is idempotent (preflight runs before any
// FSM/state write), so the robust fix is an outer retry loop where the
// agent reads advance-phase's own [BLOCKED] output each round instead of
// guessing in advance.
let advancePass = false, advanceReport = ''
const ADVANCE_MAX_ROUNDS = 5
for (let round = 1; round <= ADVANCE_MAX_ROUNDS; round++) {
  log('  Advance round ' + round + '/' + ADVANCE_MAX_ROUNDS)
  // Last-line integrity guard: the phase-exit push commits .methodology/
  // wholesale — block here so mid-run corruption never reaches git history
  // (2026-07-02: commit 3198402 baked a corrupted manifest into main).
  // Re-check every round — a fix attempt in a prior round could reintroduce it.
  const advIntegrity = await checkManifestIntegrity('Advance', 'advance-integrity-r' + round)
  if (!advIntegrity.ok) {
    return { error: 'Advance round ' + round + ': quality_manifest.json corrupted — refusing to commit it', detail: advIntegrity.raw, recovery: 'git checkout HEAD -- .methodology/quality_manifest.json (verify HEAD is healthy first), merge the latest gate result back into gate_results, then resume', note: 'Blocking prevents the corruption from being committed by the phase-exit push.' }
  }
  advanceReport = await agent(
    'YOU ARE THE PHASE-4 EXIT ORCHESTRATOR. Advance to Phase 5. ROUND ' + round + '.\n'
    + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
    + 'Steps:\n'
    + '0. GUARD — already advanced? `PHASE=$(jq -r .current_phase ' + REPO + '/.methodology/state.json 2>/dev/null); echo "current_phase=$PHASE"; [ "$PHASE" -ge 5 ]`. If Phase 5 is confirmed, report "ADVANCE: PASS (already advanced)" and stop.\n'
    + '1. PUSH ⑥ p4-pre-gate3 (if not already pushed): `' + PY + ' ' + REPO + '/harness_cli.py push-milestone --type p4-pre-gate3 --project ' + REPO + ' --fr-ids ' + gate1Pass.join(',') + '`. (Idempotent; skip if already snapshotted.)\n'
    + '2. advance-phase: `' + PY + ' ' + REPO + '/harness_cli.py advance-phase --completed 4 --project ' + REPO + '`\n'
    + '   advance-phase independently re-verifies EVERYTHING before it will advance — its own output tells you exactly what is missing. If it prints "[BLOCKED] ...", that message IS the fix instruction: read it verbatim and do exactly what it says, then re-run this same advance-phase command. Do NOT guess what might be wrong — trust only what advance-phase itself reports. It is safe to re-run repeatedly within this round.\n'
    + '3. Read ' + REPO + '/.methodology/state.json; confirm current_phase = 5 (advance-phase atomically writes state.json when complete).\n\n'
    + 'Report final line: "ADVANCE: PASS|FAIL — <details>". If still FAIL after exhausting this round\'s turn, report the LAST [BLOCKED] message verbatim so the next round starts from where this one left off. PHASE_5_PLAN: ' + REPO + '/.methodology/phase5_plan.md\n\n'
    + 'SCOPE RULES:\n- DO NOT re-do P4 testing.\n- DO NOT use --no-verify.\n- DO NOT modify harness/ (HR-17).\n- ONLY push-milestone p4-pre-gate3 + advance-phase + verify HANDOVER.md + the specific fixes advance-phase\'s own output asked for.',
    { label: 'advance-r' + round, phase: 'Advance', agentType: 'general-purpose' },
  )
  if (advanceReport === null || advanceReport === undefined || (typeof advanceReport === 'string' && advanceReport.length < 10)) {
    log('  Advance agent blocked (session limit / rate limit) — aborting retries, resume after quota reset')
    return { session_limit_blocked: true, phase: 4, step: 'advance', message: 'Agent hit session/rate limit during Advance. Resume after quota reset — the GUARD step skips if already advanced.' }
  }
  advancePass = typeof advanceReport === 'string' && /ADVANCE:\s*PASS/.test(advanceReport)
  if (advancePass) { log('  Advance PASS'); break }
  log('  Advance not yet PASS — retry round ' + (round + 1))
}

if (!advancePass) {
  return { error: 'Advance did not PASS in ' + ADVANCE_MAX_ROUNDS + ' rounds — check HANDOVER.md + state.json + the last [BLOCKED] message below. If Phase 5 is confirmed, resume workflow to verify.', raw: String(advanceReport ?? '').slice(-600) }
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
