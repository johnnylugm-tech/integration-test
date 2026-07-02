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
    { title: 'Manifest Integrity' },
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
// FIX V: start time for budget guard (90-minute hard cap to prevent
// infinite stalls). If a workflow runs for >90 min without completing,
// it has likely hit a corruption/stall loop. Return cleanly with context
// so the operator can identify the stall point.

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
log('run-env-check (root-cause fix: CLI exit code reflects ready flag)')
// Bug #127 root-cause fix (2026-06-27): `cmd_run_env_check` now returns
// exit 0 when ready=true and 1 when ready=false (previously always 0).
// This makes the harness CLI self-sufficient — workflows check `$?`
// directly with no LLM orchestrator agent in the loop.
const envReport = await agent(
  'You MUST use the Bash tool. Run exactly this ONE command (single line, the `;` keeps $? bound to run-env-check):\n'
  + PY + ' ' + REPO + '/harness_cli.py run-env-check --phase 3 --project ' + REPO + '; echo "ENV_CHECK_RC=$?"\n'
  + 'Return the raw stdout verbatim. Do not paraphrase.',
  { label: 'env-check', phase: 'Env Check', agentType: 'general-purpose' },
)
if (!(typeof envReport === 'string' && /ENV_CHECK_RC=0\b/.test(envReport))) {
  return { error: 'Phase 3 env-check did not PASS', raw: String(envReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Manifest Integrity (Fix I — prevent silent corruption stalls)
// ════════════════════════════════════════════════════════════════════════
phase('Manifest Integrity')
// Gate 1 precheck at line ~257 reads manifest quality_complete to decide
// which FRs to skip. If the working-tree manifest was corrupted by a
// sub-agent (e.g. fr_ids truncated, gate1 emptied), the precheck sees
// zero completed FRs and re-dispatches TDD agents that also cannot
// complete — causing an infinite stall. Detect the three known corruption
// patterns before we ever read the manifest.
// Reusable checker: the 2026-07-02 incident proved corruption can ALSO happen
// MID-RUN (a Gate 2 sub-agent ran bare `pytest`, collecting harness/tests/
// whose non-hermetic tests overwrote the manifest via CWD fallback). A single
// entry check misses that window, so Gate 2 rounds and Advance re-verify.
const integrityCmd = PY + ' -c "import json, sys; m = json.load(open(\'' + REPO + '/.methodology/quality_manifest.json\')); ids = m.get(\'fr_ids\') or []; mt = m.get(\'fr_module_traceability\') or {}; g1 = (m.get(\'gate_results\',{}) or {}).get(\'gate1\',{}) or {}; ok_ids = len(ids) >= 2; ok_trace = len(mt) >= len(ids); ok_g1 = isinstance(g1, dict); print(\'OK\' if (ok_ids and ok_trace and ok_g1) else json.dumps({\'BROKEN\': True, \'fr_ids_count\': len(ids), \'traceability_count\': len(mt), \'gate1_keys\': len(g1), \'recovery\': \'git checkout HEAD -- .methodology/quality_manifest.json\'}))"'
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
  return { error: 'Manifest Integrity: quality_manifest.json appears corrupted', detail: integrity0.raw, recovery: 'git checkout HEAD -- .methodology/quality_manifest.json', note: 'Working-tree manifest does not match HEAD. A sub-agent likely wrote to it directly. Restore from HEAD and re-run the workflow.' }
}
log('  manifest integrity OK')

// ════════════════════════════════════════════════════════════════════════
// Phase: Load FRs (agent reads ctx.json — script can't read files, playbook §4)
// ════════════════════════════════════════════════════════════════════════
phase('Load FRs')
log('load-context --phase 3 → fr_ids (script holds the loop)')
// v15: retry loop — agent() + parseAgentJson both wrapped (Bug #2)
// v2.13.1: hardened against agent hallucination — verify .sessi-work/phase3_ctx.json
// actually exists and contains non-empty fr_ids before accepting (Bug #122).
let ctx = null
const ctxFile = REPO + '/.sessi-work/phase3_ctx.json'
for (let attempt = 1; attempt <= 3; attempt++) {
  // Step 1: verify file exists and is non-empty. If missing, regenerate it.
  // Bug #126 fix (2026-06-27): `wc -c` defaults to fixed-width right-padded
  // output (`     789`), so `FILE_OK_$(wc -c ...)` actually produces
  // `FILE_OK_     789` — the strict regex `/FILE_OK_\d+/` never matched.
  // Root-cause fix: control the OUTPUT side via `awk '{print $1}'` to strip
  // padding. Regex stays strict (`/FILE_OK_\d+/`) — single-sided fix.
  try {
    // Bug #134 fix (2026-06-28): root-cause fix — previous check was
    // `test -s FILE && echo FILE_OK_<size>` which passed for ANY non-zero
    // file size, including partial writes, truncated buffers, or fragments
    // left by a crashed writer. The next step (load-ctx-a) then ran
    // `balancedJsonAt` on the agent's cat output and threw PARSE_FAIL
    // because the JSON was incomplete — recovery path masked the symptom
    // (FR_COUNT_N marker) but the partial file passed FILE_OK_ twice.
    //
    // Correct fix: validate the file PARSES as JSON, not just that it
    // has bytes. `python3 -c 'json.load(...)'` raises JSONDecodeError
    // mid-write, returning non-zero → no FILE_OK marker. Use Python's
    // json module (already required by load-context) so no new deps.
    //
    // Bash is built via template literals so JS string escaping doesn't
    // fight bash single-quotes (Bug #136 sibling case — advance prompt's
    // `.current_phase // 0` was eaten by JS property-access + `//` comment).
    const ctxCheckCmd = `${PY} -c "import json,os,sys; json.load(open('${ctxFile}')); print('FILE_OK_'+str(os.path.getsize('${ctxFile}')))" || echo FILE_MISSING`
    const existsRaw = await agent(
      `You MUST use the Bash tool. Run exactly:\n${ctxCheckCmd}\nReturn the raw stdout as your final message. Do not paraphrase.`,
      { label: 'ctx-check-' + attempt, phase: 'Load FRs', agentType: 'general-purpose' },
    )
    if (!/FILE_OK_\d+/.test(String(existsRaw ?? ''))) {
      log('  ctx file missing/invalid (attempt ' + attempt + ') — regenerating')
      const ctxRegenCmd = `${PY} ${REPO}/harness_cli.py load-context --phase 3 --project ${REPO} --json > ${ctxFile} && ${PY} -c "import json,os; json.load(open('${ctxFile}')); print('REGEN_OK_'+str(os.path.getsize('${ctxFile}')))"`
      await agent(
        `You MUST use the Bash tool. Run exactly:\n${ctxRegenCmd}\nReturn the raw stdout as your final message.`,
        { label: 'ctx-regen-' + attempt, phase: 'Load FRs', agentType: 'general-purpose' },
      )
      continue
    }
  } catch (e) { log('  ctx-check agent failed: ' + String(e.message ?? e).slice(0, 80)); continue }

  // Step 2: have Python emit a single-line JSON string with EXACTLY the
  // shape the workflow needs (fr_ids + fr_count). The agent's only job is
  // to run the bash command and return raw stdout — no interpretation.
  //
  // Bug #135 fix (2026-06-28): root-cause fix — previous design did
  // `cat FILE` and asked the agent to "return raw stdout verbatim". The
  // LLM agent routinely paraphrased the JSON into prose (visible in logs
  // as tail like "Ds (FR-01, FR-02, FR-03)\n- FR_COUNT_3 marker confirmed...")
  // so `balancedJsonAt` threw PARSE_FAIL even though the file was valid.
  // The FR_COUNT_N marker escape hatch masked the symptom but never fixed
  // the underlying "agent returning prose instead of machine output" class
  // of bug.
  //
  // Correct fix: don't rely on the agent to forward raw stdout. Have Python
  // emit a single JSON line containing ONLY the workflow-relevant fields
  // (fr_ids + fr_count). The agent returns that one line; the workflow
  // parses it directly. Eliminates `balancedJsonAt` ambiguity entirely.
  // As a bonus, this also lets us drop the FR_COUNT marker check — the
  // JSON itself contains fr_count.
  let ctxResult = ''
  let frCountMarker = ''
  try {
    // J1 fix (2026-06-29): forward fr_titles too. load-context emits fr_details as a
    // DICT keyed by FR id ({"FR-01":{"title":...}}). The previous parse only forwarded
    // fr_details_keys (no titles), and the consumer (frTitle below) read it as an Array
    // — so titles silently never populated. Emit an {id:title} map the consumer uses
    // directly.
    const ctxParseCmd = `${PY} -c "import json; d=json.load(open('${ctxFile}')); fd=d.get('fr_details') or {}; print(json.dumps({'fr_ids':d.get('fr_ids',[]),'fr_count':len(d.get('fr_ids',[])),'fr_titles':{k:(v.get('title','') if isinstance(v,dict) else '') for k,v in fd.items()}}))"`
    ctxResult = await agent(
      `You MUST use the Bash tool. Run exactly:\n${ctxParseCmd}\nReturn the raw stdout as your final message. Do not paraphrase. Do not add commentary.`,
      { label: 'load-ctx-a' + attempt, phase: 'Load FRs', agentType: 'general-purpose' },
    )
    // Sanity: must contain a JSON object with fr_count >= 1. If the agent
    // paraphrased, fall through to regen retry (existing recovery path).
    if (!/"fr_count"\s*:\s*[1-9]\d*/.test(String(ctxResult ?? ''))) {
      log('  load-ctx agent did not return parseable JSON (attempt ' + attempt + '): ' + String(ctxResult ?? '').slice(0, 200))
      continue
    }
    frCountMarker = 'JSON_OK'
  } catch (e) { log('  load-ctx agent failed: ' + String(e.message ?? e).slice(0, 80)); continue }
  try {
    ctx = parseAgentJson(ctxResult, 'load-ctx')
    if (Array.isArray(ctx.fr_ids) && ctx.fr_ids.length > 0) {
      log('  load-ctx OK via ' + frCountMarker)
      break
    }
    log('  load-ctx returned empty fr_ids (attempt ' + attempt + '): keys=' + Object.keys(ctx ?? {}).join(','))
    ctx = null
  } catch (e) { log('  load-ctx parse failed (attempt ' + attempt + '): ' + e.message.slice(0, 120)); ctx = null }
}
if (!ctx) return { error: 'Load FRs: ctx failed after 3 attempts', ctxFile }
let frIds = Array.isArray(ctx.fr_ids) ? ctx.fr_ids : []
if (!frIds.length) return { error: 'Load FRs: no fr_ids found in ctx', ctxKeys: Object.keys(ctx) }
// J1: fr_titles is the {id:title} map emitted by ctxParseCmd above.
const frTitle = (ctx.fr_titles && typeof ctx.fr_titles === 'object') ? ctx.fr_titles : {}
log('  fr_ids = ' + JSON.stringify(frIds))

// Gate 1 pre-check: identify FRs that ALREADY passed Gate 1 (skip TDD on resume/re-run).
// AUTHORITATIVE source = quality_manifest.gate_results.gate1[fr].quality_complete, which
// harness_bridge writes on EVERY finalize-gate (pass OR fail). NOT the g1_p3_*.flag
// sentinel: that flag is written by run-gate (it only proves run-gate executed), so a
// finalize-gate that raised GateBlockedError on a failing dimension still leaves the
// sentinel behind — using it as a PASS signal misreports blocked FRs as done.
const precheckCmd = PY + ' -c "import json; g=(json.load(open(\'' + REPO + '/.methodology/quality_manifest.json\')).get(\'gate_results\',{}) or {}).get(\'gate1\',{}) or {}; print(chr(10).join(fr for fr,v in g.items() if isinstance(v,dict) and v.get(\'quality_complete\') is True))"'
const precheckRaw = await agent(
  'Run EXACTLY this command via the Bash tool and return its raw stdout verbatim (a newline-separated list of FR ids, possibly empty). No commentary.\n`' + precheckCmd + '`',
  { label: 'gate1-precheck', phase: 'Load FRs', agentType: 'general-purpose' }
)
const alreadyDone = new Set()
if (typeof precheckRaw === 'string') {
  for (const line of precheckRaw.split('\n')) {
    if (/^FR-\d+$/.test(line.trim())) alreadyDone.add(line.trim())
  }
}
if (alreadyDone.size > 0) log('  sentinel pre-check: Gate 1 (Phase 3) already PASS for ' + [...alreadyDone].join(', ') + ' — skipping TDD agents')

// ════════════════════════════════════════════════════════════════════════
// Phase: Per-FR TDD (script-driven loop; one narrow agent per FR)
// ════════════════════════════════════════════════════════════════════════
phase('Per-FR TDD')
const gate1Pass = []
const gate1Fail = []
let p3MidPushed = false
const p3MidThreshold = Math.ceil(frIds.length / 3)  // PUSH ③ trigger: ≥1/3 FRs Gate 1 PASS (phase3_plan.md)
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
      + '   On MIRROR FAIL: fix the TEST to match TEST_SPEC.md — do NOT edit TEST_SPEC.md (correctness was locked in Phase 2; P3 only implements). Re-run.\n'
      + '3. TDD-GREEN:  `' + PY + ' ' + REPO + '/harness_cli.py run-fr-step --phase 3 --fr-id ' + frId + ' --step TDD-GREEN --project ' + REPO + ' --srs 01-requirements/SRS.md`\n'
      + '4. TDD-IMPROVE:`' + PY + ' ' + REPO + '/harness_cli.py run-fr-step --phase 3 --fr-id ' + frId + ' --step TDD-IMPROVE --project ' + REPO + '`\n'
      + '5. GATE1:      `' + PY + ' ' + REPO + '/harness_cli.py run-fr-step --phase 3 --fr-id ' + frId + ' --step GATE1 --project ' + REPO + '`\n'
      + '   Gate 1 thresholds: linting(90) type_safety(85) test_coverage(80).\n'
      + '   - PASS → done.\n'
      + '   - FAIL → fix failing dims (ruff check . --fix; add tests for coverage; fix pyright errors), re-run GATE1. Max 3 rounds.\n'
      + '   - Still failing after 3 → report FAIL.\n'
      + '   - Architecture Amendment Protocol [BLOCKED]: if GATE1 prints "Unregistered modules detected: {…}", DO NOT hand-edit SAB.json by hand. Run `' + PY + ' ' + REPO + '/harness_cli.py amend-sab --project ' + REPO + '` to register the new modules (idempotent, scans 03-development/src/), `git -C ' + REPO + ' add .methodology/SAB.json && git -C ' + REPO + ' commit -m "amend: register SAB modules (' + frId + ')"`, then re-run GATE1. Max 1 amend round per FR.\n'
      + '   Each run-fr-step auto-pushes on completion (idempotent). Crash recovery: `resume-fr-step --phase 3 --project ' + REPO + '`.\n'
      + '6. ORCH-POST (after GATE1 PASS, per phase3_plan.md [ORCH-POST]):\n'
      + '   a. `' + PY + ' ' + REPO + '/harness_cli.py spec-coverage-check --project ' + REPO + ' --threshold 40.0 --fr-id ' + frId + '` (per-FR D4 ≥40%). FAIL → add the missing test implementations for ' + frId + ', re-run.\n'
      + '   b. `' + PY + ' ' + REPO + '/harness/scripts/generate_sab.py --project ' + REPO + ' --overwrite` (regenerate SAB.json).\n\n'
      + 'Implement the module per SPEC.md (read ' + REPO + '/SPEC.md for ' + frId + ') + SAD.md module mapping. Write source under the project\'s `src/` tree as specified in SAD §2 (do not assume a fixed project layout — read SAD §2 for the module path; e.g. for the canonical `03-development/src/<module>/` layout, use that; otherwise follow whatever SAD §2 specifies). Tests under `tests/` per project layout. Docstrings must include [' + frId + '] reference (NFR-05).\n\n'
      + 'Report final line: "' + frId + ' GATE1: PASS" or "' + frId + ' GATE1: FAIL — <reason>".\n\n'
      + 'SCOPE RULES:\n- DO NOT implement any FR OTHER than ' + frId + '.\n- DO NOT run run-gate (Gate 2), advance-phase, or push-milestone.\n- DO NOT modify harness/ (HR-17).\n- ONLY the 6 steps above for ' + frId + ' (spec-coverage-check + generate_sab.py in step 6 are allowed).',
      { label: 'tdd-' + frId, phase: 'Per-FR TDD', agentType: 'general-purpose' },
    )
    // L1: distinguish a session/rate-limit block (null/empty agent return) from a real
    // Gate 1 FAIL — mirror the Gate 2 detection (below). Without this, a rate-limit mid-
    // TDD is misreported as a code-quality Gate 1 failure. Sentinel GUARD skips completed
    // FRs on resume, so aborting here is safe.
    if (frReport === null || frReport === undefined || (typeof frReport === 'string' && frReport.length < 10)) {
      log('  ' + frId + ' agent blocked (session limit / rate limit) — aborting, resume after quota reset')
      return { session_limit_blocked: true, phase: 3, fr_id: frId, gate1Pass, message: 'Agent hit session/rate limit during ' + frId + ' TDD. Resume after quota reset — sentinel GUARD will skip completed FRs.' }
    }
    // AUTHORITATIVE Gate 1 verdict: read the harness quality_manifest (bridge writes
    // gate_results.gate1[fr].quality_complete on every finalize-gate, pass OR fail) —
    // NOT the sub-agent's self-reported "GATE1: PASS" string. A sub-agent can report
    // PASS from its own gate1_result.json overall score even when finalize-gate raised
    // GateBlockedError (e.g. spec-coverage short, or a dimension below threshold), which
    // silently advances a FR that the harness actually blocked. Verify against the
    // harness's own record so a blocked gate is never counted as passed.
    const verifyCmd = PY + ' -c "import json; g=(json.load(open(\'' + REPO + '/.methodology/quality_manifest.json\')).get(\'gate_results\',{}) or {}).get(\'gate1\',{}).get(\'' + frId + '\',{}) or {}; print(\'GATE1_VERIFIED_PASS\' if g.get(\'quality_complete\') is True else \'GATE1_VERIFIED_FAIL score=\'+str(g.get(\'score\')))"'
    const verdictRaw = await agent(
      'Run EXACTLY this command via the Bash tool and return its raw stdout verbatim. No commentary.\n`' + verifyCmd + '`',
      { label: 'gate1-verify-' + frId, phase: 'Per-FR TDD', agentType: 'general-purpose' },
    )
    const passed = typeof verdictRaw === 'string' && /GATE1_VERIFIED_PASS/.test(verdictRaw)
    if (passed) { gate1Pass.push(frId); log('  ' + frId + ' Gate 1 PASS (' + gate1Pass.length + '/' + frIds.length + ') [harness-verified]') }
    else { gate1Fail.push(frId); log('  ' + frId + ' Gate 1 FAIL [harness manifest qc != true; sub-agent self-report ignored]') }
  }

  // PUSH ③ p3-mid — fire once when ≥1/3 FRs have Gate 1 PASS (but not yet all done).
  if (!p3MidPushed && gate1Pass.length >= p3MidThreshold && gate1Pass.length < frIds.length) {
    p3MidPushed = true
    log('  ≥1/3 FRs Gate 1 PASS (' + gate1Pass.length + '/' + frIds.length + ') — pushing p3-mid milestone')
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
  // Mid-run integrity guard: a prior round's sub-agent may have corrupted the
  // manifest (2026-07-02 incident — bare pytest → harness test CWD leak).
  // Catch it BEFORE burning a full evaluation round on poisoned SAB baselines.
  const g2Integrity = await checkManifestIntegrity('Gate 2', 'g2-integrity-r' + round)
  if (!g2Integrity.ok) {
    return { error: 'Gate 2 round ' + round + ': quality_manifest.json corrupted mid-run', detail: g2Integrity.raw, recovery: 'git checkout HEAD -- .methodology/quality_manifest.json (verify HEAD is healthy first — a corrupted manifest may already be committed)', note: 'Corruption appeared AFTER the entry integrity check. Inspect the previous round\'s agent transcript for the writer before restoring.' }
  }
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
// Round loop (mirrors the Gate 2 loop above — 2026-07-02 audit finding):
// advance-phase enforces MORE independent checks than any single prompt can
// safely enumerate (ruff, mypy, pytest --cov-fail-under=100, constitution,
// reliability_lint, drift_detection, SAB, spec-coverage, Phase Truth — this
// list itself already drifted once from what an earlier prompt hardcoded).
// A static checklist goes stale the moment harness adds/changes a check.
// advance-phase is idempotent (preflight checks run before any FSM/state
// write — confirmed empirically: repeated calls just re-report blockers,
// no partial-state risk), so the robust fix is an outer retry loop where
// the agent reads advance-phase's own [BLOCKED] output each round — which
// is self-describing by construction — instead of guessing in advance.
let advancePass = false, advanceReport = ''
const ADVANCE_MAX_ROUNDS = 5
for (let round = 1; round <= ADVANCE_MAX_ROUNDS; round++) {
  log('  Advance round ' + round + '/' + ADVANCE_MAX_ROUNDS)
  // Last-line integrity guard before the milestone commit: push-milestone
  // commits .methodology/ wholesale, so a corrupted manifest here gets
  // PERMANENTLY baked into git history (2026-07-02: commit 3198402). Re-check
  // every round — a fix attempt in a prior round could reintroduce it.
  const advIntegrity = await checkManifestIntegrity('Advance', 'advance-integrity-r' + round)
  if (!advIntegrity.ok) {
    return { error: 'Advance round ' + round + ': quality_manifest.json corrupted — refusing to commit it via push-milestone', detail: advIntegrity.raw, recovery: 'git checkout HEAD -- .methodology/quality_manifest.json (verify HEAD is healthy first), then merge gate2_result.json back into gate_results.gate2 and resume', note: 'Blocking here prevents the corruption from being committed into the p3-post-gate2 milestone.' }
  }
  advanceReport = await agent(
    'YOU ARE THE PHASE-3 EXIT ORCHESTRATOR. Push formal exit + advance to Phase 4. ROUND ' + round + '.\n'
    + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
    + 'Steps:\n'
    + '0. GUARD — already advanced? `PHASE=$(jq -r .current_phase ' + REPO + '/.methodology/state.json 2>/dev/null); echo "current_phase=$PHASE"; [ "$PHASE" -ge 4 ]`. If Phase 4 is confirmed, report "ADVANCE: PASS (already advanced)" and stop.\n'
    + '1. GUARD + PUSH ⑤ p3-post-gate2: `git -C ' + REPO + ' log --oneline --grep="p3-post-gate2" -1`. If a commit exists, skip the push. Else: `' + PY + ' ' + REPO + '/harness_cli.py push-milestone --type p3-post-gate2 --project ' + REPO + ' --fr-ids ' + gate1Pass.join(',') + '`\n'
    + '   Pre-flight (enforced): gate2_result.json composite ≥75 + per-FR Gate 1 sentinel .sessi-work/sentinels/g1_p3_<fr>.flag exists for every FR. If BLOCKED, read the error list and fix.\n'
    + '2. advance-phase: `' + PY + ' ' + REPO + '/harness_cli.py advance-phase --completed 3 --project ' + REPO + '`\n'
    + '   advance-phase independently re-verifies EVERYTHING before it will advance (lint, types, coverage, document quality, reliability lint, architecture drift, Phase Truth, and more) — its own output tells you exactly what is missing. If it prints "[BLOCKED] ...", that message IS the fix instruction: read it verbatim and do exactly what it says (it often includes the precise command to run), then re-run this same advance-phase command. Do NOT guess what might be wrong — trust only what advance-phase itself reports.\n'
    + '   advance-phase is safe to re-run: it re-checks and re-reports without side effects until every check passes, so iterate within this round as many times as needed.\n'
    + '3. Read ' + REPO + '/.methodology/state.json; confirm current_phase = 4 (advance-phase atomically writes state.json when complete).\n\n'
    + 'Report final line: "ADVANCE: PASS|FAIL — <details>". If still FAIL after exhausting this round\'s turn, report the LAST [BLOCKED] message verbatim so the next round starts from where this one left off. PHASE_4_PLAN: ' + REPO + '/.methodology/phase4_plan.md\n\n'
    + 'SCOPE RULES:\n- DO NOT re-implement FRs.\n- DO NOT use --no-verify.\n- DO NOT modify harness/ (HR-17).\n- ONLY push-milestone p3-post-gate2 + advance-phase + verify HANDOVER.md + the specific fixes advance-phase\'s own output asked for.',
    { label: 'advance-r' + round, phase: 'Advance', agentType: 'general-purpose' },
  )
  // Session-limit / rate-limit detection (mirrors the Gate 2 loop above —
  // Advance never had this check before because it was never a loop).
  if (advanceReport === null || advanceReport === undefined || (typeof advanceReport === 'string' && advanceReport.length < 10)) {
    log('  Advance agent blocked (session limit / rate limit) — aborting retries, resume after quota reset')
    return { session_limit_blocked: true, phase: 3, step: 'advance', message: 'Agent hit session/rate limit during Advance. Resume after quota reset — the GUARD step skips if already advanced.' }
  }
  advancePass = typeof advanceReport === 'string' && /ADVANCE:\s*PASS/.test(advanceReport)
  if (advancePass) { log('  Advance PASS'); break }
  log('  Advance not yet PASS — retry round ' + (round + 1))
}

if (!advancePass) {
  return { error: 'Advance did not PASS in ' + ADVANCE_MAX_ROUNDS + ' rounds — check HANDOVER.md + state.json + the last [BLOCKED] message below. If Phase 4 is confirmed, resume workflow to verify.', raw: String(advanceReport ?? '').slice(-600) }
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
