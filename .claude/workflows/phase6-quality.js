// Phase 6 — Quality Assurance (faithful to .methodology/phase6_plan.md v2.12.0)
//
// Structure: NO FR loop. Gate 4 (15 dims, tool-scored + artifact-backed DA
// challenge for Tier 3 dims) PLUS Agent B peer review of the QA deliverables
// (both required to exit). Then release notes + final sign-off + git tag + advance.
//
// Playbook lessons: NO import/fs/process/schema:, Bash CLI, SCOPE RULES,
// PY = .venv/bin/python, scriptPath launch.

export const meta = {
  name: 'phase6-quality',
  description: 'Phase 6 Quality — Gate 4 (15 dims + DA challenge) + Agent B peer review + release notes/sign-off + git tag (phase6_plan.md v2.12.0)',
  phases: [
    { title: 'Entry & Preflight' },
    { title: 'Gate 4' },
    { title: 'Release Docs' },
    { title: 'Peer Review' },
    { title: 'Tag & Advance' },
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
// Phase: Entry & Preflight (incl. D4-precheck 90% — Gate 4 blocks at 90% not 80%)
// ════════════════════════════════════════════════════════════════════════
phase('Entry & Preflight')
log('ENTRY-CHECK Gate3 + P5 artifacts + D4-precheck 90% + run-phase 6 + handoff + CI')
const preflightReport = await agent(
  'YOU ARE THE PHASE-6 PREFLIGHT ORCHESTRATOR. Run bash in order; report.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. ENTRY-CHECK: confirm .methodology/quality_manifest.json records Gate 3 PASS from P4, AND 05-verification/VERIFICATION_REPORT.md + 05-verification/BASELINE.md exist (P5 outputs). Else FAIL.\n'
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
// Phase: Gate 4 (run-gate → DA challenge A3 → eval 15 dims → finalize → D4 90%; HR-08)
// ════════════════════════════════════════════════════════════════════════
phase('Gate 4')
log('Gate 4 full-project eval (composite ≥85, 15 dims + artifact-backed DA challenge)')
let gate4Pass = false, gate4Report = ''
for (let round = 1; round <= 3; round++) {
  log('  Gate 4 round ' + round + '/3')
  gate4Report = await agent(
    'YOU ARE THE GATE-4 ORCHESTRATOR (Phase 6 — full project quality). ROUND ' + round + '.\n'
    + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
    + 'Pre-Gate: confirm all FRs merged to main + no open critical/high from Gate 3.\n\n'
    + 'Steps:\n'
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
  )
  gate4Pass = typeof gate4Report === 'string' && /GATE4:\s*PASS/.test(gate4Report)
  if (gate4Pass) { log('  Gate 4 PASS'); break }
  log('  Gate 4 not yet PASS — retry round ' + (round + 1))
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
  + '1. G4e RELEASE_NOTES: write ' + REPO + '/RELEASE_NOTES.md (project root). Summarise changes since Gate 3. Include: version, date, FR list, Gate 4 composite score (read from .sessi-work/gate4_result.json), known limitations. Reference 06-quality/QUALITY_REPORT.md (auto-generated by G4c).\n'
  + '2. G4f FINAL_SIGN_OFF: write ' + REPO + '/FINAL_SIGN_OFF.md (project root). Include: project name, completion date, Gate 4 composite score, sign-off statement. MUST reference 05-verification/BASELINE.md and 05-verification/VERIFICATION_REPORT.md (verification provenance).\n\n'
  + 'Report: "RELEASE-DOCS: PASS" or "RELEASE-DOCS: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run advance-phase / git tag / peer review dispatch.\n- DO NOT modify harness/.\n- DO NOT re-run Gate 4.\n- ONLY generate RELEASE_NOTES.md + FINAL_SIGN_OFF.md.',
  { label: 'release-docs', phase: 'Release Docs', agentType: 'general-purpose' },
)
if (!(typeof releaseReport === 'string' && /RELEASE-DOCS:\s*PASS/.test(releaseReport))) {
  return { error: 'Phase 6 release docs did not PASS', raw: String(releaseReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Peer Review (G4g — Agent B reviews + writes 4 approval JSON files)
// ════════════════════════════════════════════════════════════════════════
phase('Peer Review')
log('Agent B (reviewer) writes 4 approval JSON to .methodology/agent_b_approvals/')
const peerReport = await agent(
  'YOU ARE AGENT B (TECH_LEAD reviewer) for the Phase 6 Gate 4 deliverables (HR-01).\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. Review 06-quality/QUALITY_REPORT.md, RELEASE_NOTES.md, FINAL_SIGN_OFF.md (read them via Bash cat for exact content).\n'
  + '2. Cross-check .methodology/quality_manifest.json Gate 4 scoring logic. Reference 05-verification/VERIFICATION_REPORT.md + BASELINE.md for historical traceability.\n'
  + '3. Write 4 approval JSON files into ' + REPO + '/.methodology/agent_b_approvals/ with these EXACT filenames (Bug #114 — advance-phase checks these, the dispatch auto-persist only makes HR-01.json):\n'
  + '   QUALITY_REPORT.md.json, RELEASE_NOTES.md.json, FINAL_SIGN_OFF.md.json, quality_manifest.json\n'
  + '   Each file content: {"review_status":"APPROVE"|"REJECT","reason":"<concise>","citations":["file:line"],"gaps":[{"severity":"low|medium|high","message":"...","fr_id":"<FR-XX or null>"}]}\n'
  + '   Create the dir if missing. Use file-write tools (Write) — do NOT only print.\n'
  + '4. If any deliverable warrants REJECT or has medium/high gaps: fix the deliverable (or escalate), then re-write the approval as APPROVE.\n\n'
  + 'Report: "PEER-REVIEW: PASS" (all 4 approval JSON written with review_status APPROVE) or "PEER-REVIEW: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT run advance-phase / git tag / run-gate.\n- DO NOT modify harness/ (HR-17).\n- ONLY review + write the 4 approval JSON (+ fix deliverables if needed).',
  { label: 'peer-review', phase: 'Peer Review', agentType: 'general-purpose' },
)
if (!(typeof peerReport === 'string' && /PEER-REVIEW:\s*PASS/.test(peerReport))) {
  return { error: 'Phase 6 peer review did not PASS', raw: String(peerReport ?? '').slice(-500) }
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
  + '1. GIT-TAG: read composite_score from .sessi-work/gate4_result.json, then:\n'
  + '   `git -C ' + REPO + ' tag -a "harness-v4-$(date +%Y%m%d)-score<SCORE>" -m "Gate 4 PASS (score <SCORE>)" && git -C ' + REPO + ' push origin --tags`\n'
  + '2. advance-phase: `' + PY + ' ' + REPO + '/harness_cli.py advance-phase --completed 6 --project ' + REPO + '`\n'
  + '   TDD-PRECHECK enforced: gitleaks + ruff + mypy + pytest --cov-fail-under=100 + spec-coverage 90%. Fix blockers, re-run.\n'
  + '   PHASE-TRUTH (HR-11): if advance-phase fails on Phase Truth (<90%), check phase_truth_verifier output in .sessi-work/, fix the failing phase-link/gate artifact, re-run (max 3, then escalate to human).\n'
  + '3. Read ' + REPO + '/HANDOVER.md; confirm Phase 7 entry ("P7-entry" OR "resume_phase = 7").\n\n'
  + 'Report: "ADVANCE: PASS|FAIL — <details>". PHASE_7_PLAN: ' + REPO + '/.methodology/phase7_plan.md\n\n'
  + 'SCOPE RULES:\n- DO NOT re-do Gate 4 / release docs.\n- DO NOT use --no-verify.\n- DO NOT modify harness/ (HR-17).\n- ONLY git tag + advance-phase + verify HANDOVER.md.',
  { label: 'tag-advance', phase: 'Tag & Advance', agentType: 'general-purpose' },
)

log('Phase 6 workflow complete. Open .methodology/phase7_plan.md to continue.')
return {
  phase: 6,
  gate4_status: gate4Pass ? 'PASS' : 'unknown',
  peer_review_status: typeof peerReport === 'string' && /PEER-REVIEW:\s*PASS/.test(peerReport) ? 'PASS' : 'unknown',
  advance_status: typeof advanceReport === 'string' && /ADVANCE:\s*PASS/.test(advanceReport) ? 'PASS' : 'unknown',
  artifacts: ['06-quality/QUALITY_REPORT.md', 'RELEASE_NOTES.md', 'FINAL_SIGN_OFF.md', '.methodology/agent_b_approvals/', '.sessi-work/gate4_result.json', 'HANDOVER.md'],
  notes: 'Phase 6 complete per phase6_plan.md v2.12.0. Gate 4 PASS + Agent B peer review APPROVE. Phase 7 (Risk Management) ready.',
}
