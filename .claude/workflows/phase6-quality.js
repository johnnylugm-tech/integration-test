// Phase 6 — Quality Assurance (faithful to .methodology/phase6_plan.md v2.12.0)
//
// Structure: NO FR loop. Gate 4 (14 dims, tool-scored + artifact-backed DA
// challenge for Tier 3 dims) PLUS Agent B peer review of the QA deliverables
// (both required to exit). Then release notes + final sign-off + git tag + advance.
//
// Playbook lessons: NO import/fs/process/schema:, Bash CLI, SCOPE RULES,
// PY = .venv/bin/python, scriptPath launch.

export const meta = {
  name: 'phase6-quality',
  description: 'Phase 6 Quality — Gate 4 (14 dims + DA challenge) + Agent B peer review + release notes/sign-off + git tag (phase6_plan.md v2.12.0)',
  phases: [
    { title: 'Entry & Preflight' },
    { title: 'Gate 4' },
    { title: 'Release Docs' },
    { title: 'Peer Review' },
    { title: 'Tag & Advance' },
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

// ---- writeApprovalJson: workflow-side approval writer (Class C) ----
//
// Mirror of phase1+phase2 persistApproval (v33b 6/6 advance-phase PASS).
// Used by Phase 6 Peer Review to write 4 approval JSON files
// (QUALITY_REPORT.md.json, RELEASE_NOTES.md.json, FINAL_SIGN_OFF.md.json,
// quality_manifest.json) without depending on the sub-agent's byte-level
// file write — that path produced the v33b-class "double-encoded string"
// bug where the sub-agent emitted a JSON-quoted string and the harness
// _verify_agent_b_approvals_core rejected it as `data.get("review_status")`
// on a string. Building the JSON in the workflow and routing it through the
// deterministic `harness_cli.py write-approval` CLI delegates the
// byte-accurate contract to Python, where the v22-era 6/6 PASS lives.
//
// Returns when the CLI returns "OK" with size >= 10 bytes; throws on
// MAX_OUTER_ATTEMPTS exhaustion so the caller surfaces a real error.
async function writeApprovalJson(deliverableId, obj) {
  const approvalPayload = JSON.stringify({
    fr: deliverableId,
    review_status: obj.review_status ?? 'APPROVE',
    reason: (obj.reason ?? ('Approved ' + deliverableId + ' (reason omitted)')).slice(0, 800),
    citations: Array.isArray(obj.citations) ? obj.citations.slice(0, 20) : [],
    docs_embedded: Array.isArray(obj.docs_embedded) ? obj.docs_embedded : [],
    confidence: typeof obj.confidence === 'number' ? obj.confidence : 0.9,
  })
  const cliPath = REPO + '/harness/harness_cli.py'
  const escapedPayload = approvalPayload.replace(/'/g, "'\\''")
  const cmd = PY + ' ' + cliPath + ' write-approval --fr-id ' +
    JSON.stringify(deliverableId) + " --json '" + escapedPayload + "'"
  const MAX = 3
  let lastErr = null
  for (let attempt = 1; attempt <= MAX; attempt++) {
    let res
    try {
      res = await agent(
        'You are a SHELL WRAPPER AGENT. Run EXACTLY this Bash command and emit stdout + exit code verbatim:\n\n' + cmd + '\n\nNo commentary, no preamble, no other tool calls.',
        { label: 'write-approval-' + deliverableId + '-try' + attempt, phase: 'Peer Review', agentType: 'general-purpose' },
      )
    } catch (e) {
      lastErr = 'agent() threw: ' + (e && e.message ? e.message : String(e))
      log('  writeApprovalJson ' + deliverableId + ' attempt ' + attempt + '/' + MAX + ': ' + lastErr.slice(0, 200))
      continue
    }
    if (typeof res === 'string' && /\[write-approval\]\s*OK/.test(res)) {
      log('  wrote approval: ' + deliverableId + ' (attempt ' + attempt + '/' + MAX + ')')
      return
    }
    lastErr = 'CLI did not return OK; got: ' + String(res).slice(0, 400)
    log('  writeApprovalJson ' + deliverableId + ' attempt ' + attempt + '/' + MAX + ': ' + lastErr)
  }
  throw new Error('writeApprovalJson FAILED for ' + deliverableId + ' after ' + MAX + ' attempts. Last error: ' + lastErr)
}
const MAX_OUTER_ATTEMPTS_PEER = 3  // peer-review dispatch retry at orchestrator level
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
// Phase: Entry & Preflight (incl. D4-precheck 90% — Gate 4 blocks at 90% not 80%)
// ════════════════════════════════════════════════════════════════════════

phase('Entry & Preflight')
log('ENTRY-CHECK Gate3 + P5 artifacts + D4-precheck 90% + run-phase 6 + handoff + CI')
const preflightReport = await agent(
  'YOU ARE THE PHASE-6 PREFLIGHT ORCHESTRATOR. Run bash in order; report.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. ENTRY-CHECK: run EXACTLY this bash command to verify Gate 3 status (do NOT rely on reading the file yourself — use the command output):\n`' + PY + ' -c "import json; m=json.load(open(\'' + REPO + '/.methodology/quality_manifest.json\')); g3=(m.get(\'gate_results\',{}) or {}).get(\'gate3\',{}) or {}; print(\'GATE_VERIFIED\' if isinstance(g3,dict) and g3.get(\'quality_complete\') is True else \'GATE_MISSING\')"`\nIf GATE_MISSING → FAIL (return to Phase 4).\n'
  + '2. D4-PRECHECK: `' + PY + ' ' + REPO + '/harness_cli.py spec-coverage-check --project ' + REPO + ' --threshold 90.0`. Gate 4 blocks at 90% — if below, ADD missing test implementations NOW. Do NOT proceed until this passes.\n'
  + '3. PREFLIGHT: `' + PY + ' ' + REPO + '/harness_cli.py run-phase --phase 6 --project ' + REPO + '`. FAIL → fix (reliability lint / config liveness / attestation), re-run (max 3).\n'
  + '4. HANDOFF: `' + PY + ' ' + REPO + '/harness_cli.py validate-handoff --from-phase 5 --project ' + REPO + '`. Must exit 0.\n'
  + '5. PREFLIGHT-CI: harness_quality_gate.yml + prepare-commit-msg exist; state.json current_phase=6. If stale: init-project --phase 6 --overwrite.\n'
  + '6. PHASE-CONTEXT (load-context): `mkdir -p ' + REPO + '/.sessi-work && ' + PY + ' ' + REPO + '/harness_cli.py load-context --phase 6 --project ' + REPO + ' --json > ' + REPO + '/.sessi-work/phase6_ctx.json`.\n\n'
  + 'Report: "PREFLIGHT: PASS" or "PREFLIGHT: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run run-gate / generate release docs / peer review.\n- DO NOT run advance-phase / git tag.\n- DO NOT modify harness/.\n- ONLY preflight commands + load-context + spec-coverage fixes.',
  { label: 'preflight', phase: 'Entry & Preflight', agentType: 'general-purpose' },
)
if (!(typeof preflightReport === 'string' && /PREFLIGHT:\s*PASS/.test(preflightReport))) {
  return { error: 'Phase 6 preflight did not PASS', raw: String(preflightReport ?? '').slice(-600) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Gate 4 (run-gate → DA challenge A3 → eval 14 dims → finalize → D4 90%; HR-08)
// ════════════════════════════════════════════════════════════════════════
phase('Gate 4')
log('Gate 4 full-project eval (composite ≥85, 14 dims: 13 self-scored + traceability/architecture framework-owned)')
let gate4Pass = false, gate4Report = '', gate4Blocked = false
for (let round = 1; round <= 3; round++) {
  log('  Gate 4 round ' + round + '/3')
  // v15: wrap agent() in try/catch (Bug #2)
  try { gate4Report = await agent(
    'YOU ARE THE GATE-4 ORCHESTRATOR (Phase 6 — full project quality). ROUND ' + round + '.\n'
    + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
    + 'Pre-Gate: confirm all FRs merged to main + no open critical/high from Gate 3.\n\n'
    + 'Steps:\n'
    + '0. TRACE-PRECHECK: `' + PY + ' ' + REPO + '/harness_cli.py build-trace-attestation --project ' + REPO + ' --write 2>&1 | tail -4`. If output contains "wrote canonical", commit immediately: `git -C ' + REPO + ' add .methodology/trace/attestation.json && git -C ' + REPO + ' commit -m "trace: regen attestation before Gate 4"`. Prevents trace_dirt from blocking finalize-gate.\n'
    + '1. G4a: `' + PY + ' ' + REPO + '/harness_cli.py run-gate --gate 4 --phase 6 --project ' + REPO + '` (CRG recon runs inside). Read the printed prompt.\n'
    + '2. A3 DA CHALLENGE (artifact-backed — finalize-gate validates this BEFORE scoring): for EACH Tier 3 dim (architecture, readability, error_handling, documentation, performance), dispatch a Claude sub-agent (you have the Agent tool) with a CHALLENGER persona that critiques the design/score, then record its critique + your defence. Write into .sessi-work/gate4_result.json:\n'
    + '   "devil_advocate": {"architecture":true,"readability":true,"error_handling":true,"documentation":true,"performance":true},\n'
    + '   "devil_advocate_evidence": {"<dim>": {"challenger_model":"claude","challenge":"<≥120 chars actual critique>","response":"<≥120 chars defence>"}, ...}.\n'
    + '   A bare boolean is NOT accepted. If architecture/error_handling score 0 due to Orchestrator hub-and-spoke: also add "da_waiver": {"architecture": true} (requires the matching evidence artifact).\n'
    + '3. G4b: Evaluate all 14 dims inline per ' + REPO + '/harness/ssi/prompts/evaluate_dimension.md → .sessi-work/gate4_result.json.\n'
    + '   Dims: linting(90) type_safety(85) test_coverage(80) security(80) secrets_scanning(100) license_compliance(100) architecture(80) readability(80) error_handling(80) documentation(75) performance(75) integration_coverage(75) test_assertion_quality(70).\n'
    + '   NOTE: mutation_testing is disabled by default via .methodology/harness_config.json (mutation_testing=false). If enabled, the harness auto-includes it and re-normalises the composite score.\n'
    + '   FRAMEWORK-OWNED (do NOT self-score): traceability + architecture (CRG override). Fix failing dims at ROOT CAUSE in code.\n'
    + '4. G4c: `' + PY + ' ' + REPO + '/harness_cli.py finalize-gate --gate 4 --phase 6 --project ' + REPO + '` (writes QUALITY_REPORT.md + HANDOVER.md + pushes on PASS).\n'
    + '   - If blocked by traceability: build-trace-attestation --write + commit, re-run finalize.\n'
    + '5. D4: `' + PY + ' ' + REPO + '/harness_cli.py spec-coverage-check --project ' + REPO + ' --threshold 90.0`. FAIL → add tests, re-run.\n\n'
    + 'Report final line: "GATE4: PASS" (composite ≥85 AND all dims ≥ threshold AND DA artifacts present AND D4 ≥90%) or "GATE4: FAIL — <failing dims>".\n\n'
    + 'SCOPE RULES:\n- DO NOT generate RELEASE_NOTES/FINAL_SIGN_OFF (next phase) or run advance-phase / git tag.\n- DO NOT edit gate4_result.json scores to fake them — fix code (DA evidence is the only hand-authored part).\n- DO NOT modify harness/ (HR-17).\n- ONLY run-gate/DA-challenge/eval/finalize/spec-coverage + code fixes.',
    { label: 'gate4-r' + round, phase: 'Gate 4', agentType: 'general-purpose' },
  ) } catch (e) {
    log('  Gate 4 agent threw: ' + String(e.message ?? e).slice(0, 80) + ' -- retrying')
    gate4Report = ''
    if (round < 3) continue
  }
  // Detect session-limit / rate-limit failures: agent returns null or empty when blocked.
  if (gate4Report === null || gate4Report === undefined || (typeof gate4Report === 'string' && gate4Report.length < 10)) {
    gate4Blocked = true
    log('  Gate 4 agent blocked (session limit / rate limit) — aborting retries, resume after quota reset')
    break
  }
  gate4Pass = typeof gate4Report === 'string' && /GATE4:\s*PASS/.test(gate4Report)
  if (gate4Pass) { log('  Gate 4 PASS'); break }
  log('  Gate 4 not yet PASS — retry round ' + (round + 1))
}
if (gate4Blocked) {
  return { session_limit_blocked: true, gate: 4, message: 'Agent hit session/rate limit during Gate 4 evaluation. Resume after quota reset — GUARD checks will skip completed FRs.' }
}
if (!gate4Pass) {
  return { error: 'Gate 4 did not PASS in 3 rounds (HR-08; write deferred_fixes.md + escalate to human)', raw: String(gate4Report ?? '').slice(-600) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Release Docs (G4e RELEASE_NOTES + G4f FINAL_SIGN_OFF)
// ════════════════════════════════════════════════════════════════════════
phase('Release Docs')
log('Generate RELEASE_NOTES.md + FINAL_SIGN_OFF.md (reference Gate 4 score + provenance)')
const releaseReport = await agent(
  'YOU ARE THE P6 RELEASE AUTHOR. Generate the release deliverables (after Gate 4 PASS).\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. G4e RELEASE_NOTES: write ' + REPO + '/RELEASE_NOTES.md (project root). Summarise changes since Gate 3. Include: version, date, FR list, Gate 4 composite score (read from .methodology/quality_manifest.json — persistent SoT, per phase6_plan.md v2.12.0), known limitations. Reference 06-quality/QUALITY_REPORT.md (auto-generated by G4c).\n'
  + '2. G4f FINAL_SIGN_OFF: write ' + REPO + '/FINAL_SIGN_OFF.md (project root). Include: project name, completion date, Gate 4 composite score, sign-off statement. MUST reference 05-verification/VERIFICATION_REPORT.md (verification provenance). BASELINE.md is no longer a separate P5 artifact per phase5_plan.md v2.12.0 — do NOT reference it.\n\n'
  + 'Report: "RELEASE-DOCS: PASS" or "RELEASE-DOCS: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run advance-phase / git tag / peer review dispatch.\n- DO NOT modify harness/.\n- DO NOT re-run Gate 4.\n- ONLY generate RELEASE_NOTES.md + FINAL_SIGN_OFF.md.',
  { label: 'release-docs', phase: 'Release Docs', agentType: 'general-purpose' },
)
if (!(typeof releaseReport === 'string' && /RELEASE-DOCS:\s*PASS/.test(releaseReport))) {
  return { error: 'Phase 6 release docs did not PASS', raw: String(releaseReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Peer Review (G4g — Agent B reviews; workflow writes 4 approval JSON)
// ════════════════════════════════════════════════════════════════════════
phase('Peer Review')
log('Agent B reviews 4 deliverables; workflow writes 4 approval JSON via writeApprovalJson (Class C)')

// v22-era 4 deliverables advanced-phase expects (harness_cli.py:_PHASE_DELIVERABLES[6]).
const peerDeliverables = ['QUALITY_REPORT.md', 'RELEASE_NOTES.md', 'FINAL_SIGN_OFF.md', 'quality_manifest']

let peerVerdict = null
for (let attempt = 1; attempt <= MAX_OUTER_ATTEMPTS_PEER; attempt++) {
  const peerReport = await agent(
    'YOU ARE AGENT B (TECH_LEAD reviewer) for the Phase 6 Gate 4 deliverables (HR-01).\n'
    + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
    + 'Steps:\n'
    + '1. Review 06-quality/QUALITY_REPORT.md, RELEASE_NOTES.md, FINAL_SIGN_OFF.md (read them via Bash cat for exact content).\n'
    + '2. Cross-check .methodology/quality_manifest.json Gate 4 scoring logic. Reference 05-verification/VERIFICATION_REPORT.md for historical traceability (BASELINE.md was merged into VERIFICATION_REPORT.md per phase5_plan.md v2.12.0).\n'
    + '3. If any deliverable warrants REJECT or has medium/high gaps: fix the deliverable (or escalate), then re-review.\n\n'
    + 'Output ONLY a single JSON object (no other text, no markdown fences) in your final message:\n'
    + '{"verdicts": [\n'
    + '  {"deliverable":"QUALITY_REPORT.md","review_status":"APPROVE","reason":"<concise>","citations":["file:line"],"docs_embedded":["QUALITY_REPORT.md","RELEASE_NOTES.md","FINAL_SIGN_OFF.md","VERIFICATION_REPORT.md"],"gaps":[]},\n'
    + '  {"deliverable":"RELEASE_NOTES.md","review_status":"APPROVE","reason":"<concise>","citations":["file:line"],"docs_embedded":["QUALITY_REPORT.md","RELEASE_NOTES.md","FINAL_SIGN_OFF.md","VERIFICATION_REPORT.md"],"gaps":[]},\n'
    + '  {"deliverable":"FINAL_SIGN_OFF.md","review_status":"APPROVE","reason":"<concise>","citations":["file:line"],"docs_embedded":["QUALITY_REPORT.md","RELEASE_NOTES.md","FINAL_SIGN_OFF.md","VERIFICATION_REPORT.md"],"gaps":[]},\n'
    + '  {"deliverable":"quality_manifest","review_status":"APPROVE","reason":"<concise>","citations":["file:line"],"docs_embedded":["QUALITY_REPORT.md","RELEASE_NOTES.md","FINAL_SIGN_OFF.md","VERIFICATION_REPORT.md"],"gaps":[]}\n'
    + ']}\n'
    + 'CRITICAL: "docs_embedded" must list ALL 4 required embedded docs (QUALITY_REPORT.md, RELEASE_NOTES.md, FINAL_SIGN_OFF.md, VERIFICATION_REPORT.md) — NOT just the deliverable being reviewed. The harness _verify_agent_b_approvals_core checks every verdict includes every required doc (Bug v26 basename-match contract).\n'
    + 'Each "reason" must be ≥100 chars of substantive justification (not "APPROVE" or one-word). Each "gaps" array is empty when review_status is APPROVE. Each "citations" must include ≥1 file:line you actually cat-ed.\n\n'
    + 'SCOPE RULES:\n- DO NOT run advance-phase / git tag / run-gate.\n- DO NOT modify harness/ (HR-17).\n- DO NOT write any files (workflow writes approval JSON; you only review content).',
    { label: 'peer-review-r' + attempt, phase: 'Peer Review', agentType: 'general-purpose' },
  )
  // parseAgentJson lives at top of file (same pattern as phase1+phase2)
  try {
    const parsed = parseAgentJson(peerReport, 'PeerB-r' + attempt)
    if (!parsed || !Array.isArray(parsed.verdicts) || parsed.verdicts.length !== peerDeliverables.length) {
      throw new Error('verdicts[] missing or wrong length (expected ' + peerDeliverables.length + ')')
    }
    // Sanity: each verdict must be for one of our 4 deliverables
    for (const v of parsed.verdicts) {
      if (!peerDeliverables.includes(v.deliverable)) {
        throw new Error('unknown deliverable in verdict: ' + v.deliverable)
      }
      if (!v.reason || String(v.reason).trim().length < 100) {
        throw new Error('verdict for ' + v.deliverable + ' has reason < 100 chars')
      }
    }
    peerVerdict = parsed
    log('  peer review verdict parsed (round ' + attempt + '/' + MAX_OUTER_ATTEMPTS_PEER + ')')
    break
  } catch (e) {
    log('  Peer B parse failed: ' + String(e.message ?? e).slice(0, 120) + ' — retrying')
    if (attempt === MAX_OUTER_ATTEMPTS_PEER) {
      return { error: 'Peer B parse failed after ' + MAX_OUTER_ATTEMPTS_PEER + ' rounds', detail: String(e.message ?? e).slice(0, 400) }
    }
  }
}
if (!peerVerdict) {
  return { error: 'Peer B did not produce valid verdict' }
}

// Workflow writes 4 approval JSON files via writeApprovalJson (Class C).
// This avoids the v33b-class double-encode bug where a sub-agent emitting a
// JSON string-of-string was accepted by `size >= 10 bytes` verify but later
// failed at advance-phase _verify_agent_b_approvals_core (data.get on str).
for (const v of peerVerdict.verdicts) {
  await writeApprovalJson(v.deliverable, v)
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Tag & Advance (git tag harness-v4 + advance-phase --completed 6)
// ════════════════════════════════════════════════════════════════════════
phase('Tag & Advance')
log('git tag (Gate 4 score) + advance-phase --completed 6')
const advanceReport = await agent(
  'YOU ARE THE PHASE-6 EXIT ORCHESTRATOR. Tag the Gate 4 release + advance to Phase 7.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '0. GUARD — already advanced? `PHASE=$(jq -r .current_phase ' + REPO + '/.methodology/state.json 2>/dev/null); echo "current_phase=$PHASE"; [ "$PHASE" -ge 7 ]`. Also check: `git -C ' + REPO + ' tag -l "harness-v4-*" | head -1`. If Phase 7 is confirmed OR tag already exists, report "ADVANCE: PASS (already advanced)" and stop.\n'
  + '1. GIT-TAG: read composite_score from .methodology/quality_manifest.json (persistent SoT per phase6_plan.md v2.12.0; gate4_result.json is ephemeral), then:\n'
  + '   `git -C ' + REPO + ' tag -a "harness-v4-$(date +%Y%m%d)-score<SCORE>" -m "Gate 4 PASS (score <SCORE>)" && git -C ' + REPO + ' push origin --tags`\n'
  + '2. advance-phase: `' + PY + ' ' + REPO + '/harness_cli.py advance-phase --completed 6 --project ' + REPO + '`\n'
  + '   TDD-PRECHECK enforced: gitleaks + ruff + mypy + pytest --cov-fail-under=100 + spec-coverage 90%. Fix blockers, re-run.\n'
  + '   PHASE-TRUTH (HR-11): if advance-phase fails on Phase Truth (<90%), check phase_truth_verifier output in .sessi-work/, fix the failing phase-link/gate artifact, re-run (max 3, then escalate to human).\n'
  + '3. Read ' + REPO + '/.methodology/state.json; confirm current_phase = 7 (advance-phase atomically writes state.json when complete).\n\n'
  + 'Report: "ADVANCE: PASS|FAIL — <details>". PHASE_7_PLAN: ' + REPO + '/.methodology/phase7_plan.md\n\n'
  + 'SCOPE RULES:\n- DO NOT re-do Gate 4 / release docs.\n- DO NOT use --no-verify.\n- DO NOT modify harness/ (HR-17).\n- ONLY git tag + advance-phase + verify HANDOVER.md.',
  { label: 'tag-advance', phase: 'Tag & Advance', agentType: 'general-purpose' },
)

if (!advanceReport || !/ADVANCE:\s*PASS/.test(advanceReport)) {
  return { error: 'Advance phase did not confirm PASS — check HANDOVER.md + state.json. If Phase 7 is confirmed, resume workflow to verify.', raw: String(advanceReport ?? '').slice(-400) }
}
log('Phase 6 workflow complete. Open .methodology/phase7_plan.md to continue.')
return {
  phase: 6,
  gate4_status: gate4Pass ? 'PASS' : 'unknown',
  peer_review_status: typeof peerReport === 'string' && /PEER-REVIEW:\s*PASS/.test(peerReport) ? 'PASS' : 'unknown',
  advance_status: 'PASS',
  artifacts: ['06-quality/QUALITY_REPORT.md', 'RELEASE_NOTES.md', 'FINAL_SIGN_OFF.md', '.methodology/agent_b_approvals/', '.sessi-work/gate4_result.json', '.methodology/quality_manifest.json', 'HANDOVER.md'],
  notes: 'Phase 6 complete per phase6_plan.md v2.12.0. Gate 4 PASS + Agent B peer review APPROVE. Phase 7 (Risk Management) ready.',
}
