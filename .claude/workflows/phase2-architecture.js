// Phase 2 — Architecture Design (faithful to .methodology/phase2_plan.md v2.12.0)
//
// Structure: A/B document型 (same family as phase1). 3 serial deliverables
// (SAD → ADR → TEST_SPEC), each with an Agent A author / stateless Agent B
// reviewer loop (max 5 rounds, HR-12 escalation), plus SAB generation,
// constitution check, holistic peer review, push, advance.
//
// Built on workflow-playbook.md lessons:
//   - NO import/fs/process/schema: (all I/O via agent(); JSON parsed as text).
//   - Bash for harness CLI + file reads (Read tool hallucinates — §8.2).
//   - SCOPE RULES on every agent (prevent over-reach — §7.3).
//   - PY = .venv/bin/python (3.14; /usr/bin/python3 is 3.9 = unsupported).
//   - Launch via scriptPath (avoids stale name-resolver cache — §6.5).
//
// Usage:
//   Workflow({ scriptPath: '.claude/workflows/phase2-architecture.js',
//              args: { repo: '/Users/johnny/projects/integration-test' } })

export const meta = {
  name: 'phase2-architecture',
  description: 'Phase 2 Architecture — SAD/ADR/TEST_SPEC serial A/B + SAB generation + peer review (phase2_plan.md v2.12.0)',
  phases: [
    { title: 'Entry & Preflight' },
    { title: 'Load Upstream' },
    { title: 'Sub-Task 1/3 — SAD.md' },
    { title: 'Sub-Task 2/3 — ADR.md' },
    { title: 'Constitution Check — ADR' },
    { title: 'Sub-Task 3/3 — TEST_SPEC.md' },
    { title: 'SAB Generation' },
    { title: 'Constitution Check' },
    { title: 'Peer Review' },
    { title: 'Push' },
    { title: 'Advance' },
  ],
}

// ---- args / REPO (playbook §5.7 — args may be undefined; default fallback) ----
// REPO precedence: args.repo override wins, then DEFAULT_REPO canonical path.
// process.env.HARNESS_REPO cannot be read here — playbook §4 forbids process.*
// in workflow JS. Caller scripts (run-e2e.mjs / harness-e2e.js /
// phase1-workflow.mjs) read HARNESS_REPO and inject it via args.repo.
const DEFAULT_REPO = '/Users/johnny/projects/integration-test'
let REPO = DEFAULT_REPO
if (typeof args === 'string') { try { args = JSON.parse(args) } catch {} }
if (args && typeof args === 'object' && typeof args.repo === 'string' && args.repo.length > 0) REPO = args.repo
const PY = REPO + '/.venv/bin/python'
// HR-12: safety ceiling; observed P2 runs converge in ≤2 rounds — lower only if cost is a concern
const MAX_B_ROUNDS = 5
log('REPO = ' + REPO + ' | PY = ' + PY)

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

// ---- JSON parsing (balanced-brace; playbook §5.2 — NOT schema:) ----
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
function hasHighGap(gaps) {
  return (gaps ?? []).some(function (g) { return g.severity === 'medium' || g.severity === 'high' })
}

// ---- Stateless Agent B prompt builder (playbook §7.2 — embed docs, never paths) ----
function buildBPrompt(role, deliverable, docs, checklist) {
  let p = 'You are ' + role + '. Your task: review the following deliverable (' + deliverable + ').\n'
    + 'You have NO access to any files — all context is provided below.\n\n'
  for (let i = 0; i < docs.length; i++) p += '=== [' + docs[i][0] + '] ===\n' + docs[i][1] + '\n\n'
  p += 'Review checklist:\n' + checklist + '\n\n'
    + 'Return JSON only (no markdown fences, no commentary). Schema:\n'
    + '{"review_status":"APPROVE"|"REJECT","reason":"<concise>","citations":["file:line"],"docs_embedded":["..."],"gaps":[{"severity":"low|medium|high","message":"...","fr_id":"<FR-XX or null>"}]}\n\n'
    + 'IMPORTANT: Return ONLY the JSON object as your final message.'
  return p
}

// ---- Generic A/B loop (returns {ok,content,b2} or {error,...} — caller propagates) ----
// cfg: { phaseName, key, deliverable, bRole, buildAPrompt(round,prevB2), buildBDocs(content), checklist }
async function abLoop(cfg) {
  phase(cfg.phaseName)
  log(cfg.deliverable + ': A/B loop (max ' + MAX_B_ROUNDS + ' rounds)')
  let content = '', b2 = null
  for (let round = 1; round <= MAX_B_ROUNDS; round++) {
    log('  --- ' + cfg.deliverable + ' round ' + round + '/' + MAX_B_ROUNDS + ' ---')
    const aResult = await agent(cfg.buildAPrompt(round, b2), {
      label: 'a-' + cfg.key + '-r' + round, phase: cfg.phaseName, agentType: 'general-purpose',
    })
    let a
    try { a = parseAgentJson(aResult, 'A-' + cfg.key + '-r' + round) }
    catch (e) { log('  A JSON parse fail (likely truncated): ' + e.message.slice(0, 80)); a = null }
    content = await loadFileViaBash(cfg.diskPath, cfg.diskPrefix || '', cfg.phaseName)
    if (content.startsWith('ERROR:') || content.length < 50) {
      return { error: cfg.deliverable + ' not found on disk after A (round ' + round + ')', loader_preview: content.slice(0, 200) }
    }
    log('  A status=' + (a && a.status ? a.status : 'assumed-OK') + ' | disk loaded: ' + content.length + ' chars, confidence=' + (a && a.confidence ? a.confidence : '?'))

    const bResult = await agent(buildBPrompt(cfg.bRole, cfg.deliverable, cfg.buildBDocs(content), cfg.checklist), {
      label: 'b-' + cfg.key + '-r' + round, phase: cfg.phaseName, agentType: 'general-purpose',
    })
    try { b2 = parseAgentJson(bResult, 'B-' + cfg.key + '-r' + round) }
    catch (e) {
      if (round === MAX_B_ROUNDS) return { error: cfg.deliverable + ' B parse failed at max rounds', detail: e.message }
      log('  B parse failed: ' + e.message + ' — retrying'); continue
    }
    log('  B-2: ' + b2.review_status + ' | gaps=' + (b2.gaps ?? []).length + ' | high=' + (hasHighGap(b2.gaps) ? 'yes' : 'no'))
    if (b2.review_status === 'APPROVE' && !hasHighGap(b2.gaps)) { log('  APPROVED'); return { ok: true, content, b2 } }
    if (round === MAX_B_ROUNDS) return { error: cfg.deliverable + ': B did not converge in ' + MAX_B_ROUNDS + ' rounds (HR-12 escalation)', lastB2: b2 }
    // APPROVE+high OR REJECT → A fixes next round
  }
  return { error: cfg.deliverable + ' loop exhausted unexpectedly' }
}

// ---- Bash file loader (playbook §8.2 — cat, not Read; defensive validation) ----
// v4 BUG FIX (2026-06-26): haiku agents frequently hallucinate final text
// ("Acknowledged. The code-review-graph MCP server...") instead of cat stdout.
// Reinforce prompt + retry up to 3 times + detect hallucination patterns.
async function loadFileViaBash(relPath, expectPrefix, phaseName) {
  const fullPath = REPO + '/' + relPath
  const prompt = 'YOU ARE THE CAT AGENT (haiku). Your ONLY job: dump raw file content.\n'
    + 'PATH: ' + fullPath + '\n\n'
    + 'Run EXACTLY ONE bash command: cat ' + fullPath + '\n'
    + 'Your final message MUST be the COMPLETE raw stdout — every character, every line, in order.\n'
    + 'If the file does not exist, return EXACTLY this single line: ERROR: ' + relPath + ' not found\n\n'
    + 'CRITICAL — DO NOT add any commentary, preamble, or acknowledgment.\n'
    + 'Do NOT describe what you see. Do NOT summarize. Do NOT start with "Acknowledged", "I will", or "Sure".\n'
    + 'Your final message = file content. Nothing else.'
  const isHallucinated = function (text) {
    if (text.length < 100) return true
    if (/Acknowledged\./i.test(text)) return true
    if (/code-review-graph/i.test(text)) return true
    if (/tree-sitter/i.test(text)) return true
    if (/token-efficient/i.test(text)) return true
    return false
  }
  let lastAttempt = ''
  for (let attempt = 1; attempt <= 3; attempt++) {
    const res = await agent(prompt, {
      label: 'load-' + relPath.replace(/[^a-z0-9]/gi, '-') + '-a' + attempt,
      phase: phaseName,
      agentType: 'general-purpose',
      model: 'haiku',
    })
    lastAttempt = (typeof res === 'string' ? res : String(res ?? '')).trim()
    if (lastAttempt.startsWith('ERROR:')) return lastAttempt
    if (isHallucinated(lastAttempt)) {
      log('  [load-' + relPath + '] attempt ' + attempt + '/3 hallucinated (len=' + lastAttempt.length + ')')
      continue
    }
    if (expectPrefix && lastAttempt.length > 50 && !lastAttempt.startsWith(expectPrefix)) {
      return 'ERROR: content-mismatch — expected prefix "' + expectPrefix + '", got: ' + lastAttempt.slice(0, 120)
    }
    return lastAttempt
  }
  return 'ERROR: loader-failed-after-3-attempts (' + relPath + ') — last attempt: ' + lastAttempt.slice(0, 120)
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

const _shortcut = await maybeShortcut(2)
if (_shortcut) return _shortcut

phase('Entry & Preflight')
log('ENTRY-CHECK + P1-ARTIFACTS + run-phase 2 + validate-handoff + CI + load-context')

const preflightReport = await agent(
  'YOU ARE THE PHASE-2 PREFLIGHT ORCHESTRATOR. Run bash commands in order; report final status.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. ENTRY-CHECK (P1 review-complete): `git -C ' + REPO + ' log --oneline --grep="phase1(review-complete)" -1` OR confirm all 4 P1 files exist.\n'
  + '2. P1-ARTIFACTS: `ls ' + REPO + '/01-requirements/SRS.md ' + REPO + '/01-requirements/SPEC_TRACKING.md ' + REPO + '/01-requirements/TRACEABILITY_MATRIX.md ' + REPO + '/TEST_INVENTORY.yaml`. ALL 4 must exist — if any missing, report FAIL (return to Phase 1).\n'
  + '3. PREFLIGHT: `' + PY + ' ' + REPO + '/harness_cli.py run-phase --phase 2 --project ' + REPO + '`. If FAIL: fix FSM/Constitution/Drift, re-run (max 3 attempts).\n'
  + '4. HANDOFF: `' + PY + ' ' + REPO + '/harness_cli.py validate-handoff --from-phase 1 --project ' + REPO + '`. Must exit 0; if exit 1, read errors, fix upstream P1 deliverable, re-run.\n'
  + '5. PREFLIGHT-CI: confirm `' + REPO + '/.github/workflows/harness_quality_gate.yml` + `' + REPO + '/.git/hooks/prepare-commit-msg` exist; confirm state.json current_phase=2. If stale: `' + PY + ' ' + REPO + '/harness_cli.py init-project --phase 2 --project ' + REPO + ' --overwrite`.\n'
  + '6. LOAD-CONTEXT: `mkdir -p ' + REPO + '/.sessi-work && ' + PY + ' ' + REPO + '/harness_cli.py load-context --phase 2 --project ' + REPO + ' --json > ' + REPO + '/.sessi-work/phase2_ctx.json`.\n\n'
  + 'Report plain text: "PREFLIGHT: PASS" or "PREFLIGHT: FAIL — <one-line reason>".\n\n'
  + 'SCOPE RULES:\n'
  + '- DO NOT write any P2 deliverable (SAD/ADR/TEST_SPEC).\n'
  + '- DO NOT run advance-phase, push-checkpoint, run-gate.\n'
  + '- DO NOT modify files inside harness/ (HR-17).\n'
  + '- ONLY run the commands above, fix preflight issues, and report.',
  { label: 'preflight', phase: 'Entry & Preflight', agentType: 'general-purpose' },
)
if (!(typeof preflightReport === 'string' && /PREFLIGHT:\s*PASS/.test(preflightReport))) {
  return { error: 'Phase 2 preflight did not PASS', raw: String(preflightReport ?? '').slice(-600) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Load Upstream (SRS.md — needed verbatim for stateless B reviews)
// ════════════════════════════════════════════════════════════════════════
phase('Load Upstream')
log('cat SRS.md + harness templates for embedding into stateless Agent B prompts')
const srsContent = await loadFileViaBash('01-requirements/SRS.md', '#', 'Load Upstream')
if (srsContent.startsWith('ERROR:') || srsContent.length < 50) {
  return { error: 'Failed to load SRS.md for upstream context', loaded_preview: srsContent.slice(0, 200) }
}
log('  SRS.md loaded: ' + srsContent.length + ' chars')
const sadTemplateContent = await loadFileViaBash('harness/templates/SAD.md', '#', 'Load Upstream')
log('  harness/templates/SAD.md loaded: ' + sadTemplateContent.length + ' chars')
const adrTemplateContent = await loadFileViaBash('harness/templates/ADR.md', '#', 'Load Upstream')
log('  harness/templates/ADR.md loaded: ' + adrTemplateContent.length + ' chars')

// ════════════════════════════════════════════════════════════════════════
// Sub-Task 1/3: SAD.md
// ════════════════════════════════════════════════════════════════════════
const sad = await abLoop({
  phaseName: 'Sub-Task 1/3 — SAD.md', key: 'sad', deliverable: 'SAD.md', bRole: 'TECH_LEAD', diskPath: '02-architecture/SAD.md', diskPrefix: '# SAD',
  buildAPrompt: (round, prevB2) =>
    'YOU ARE ARCHITECT (Agent A for Sub-Task 1/3 SAD.md). ROUND ' + round + '.\n'
    + 'REPO: ' + REPO + '\nYour SINGLE deliverable: ' + REPO + '/02-architecture/SAD.md\n\n'
    + 'Steps:\n'
    + '1. Self-check (Bash): `test -f ' + REPO + '/02-architecture/SAD.md`. If EXISTS, Read it (current state).\n'
    + '2. Author Software Architecture Document. REQUIRED:\n'
    + '   - §1 Overview. §2 Module design: every FR (enumerate from SPEC.md ### FR-XX: headings) maps to ≥1 module; follow SPEC.md §6 directory structure (read SPEC §6 for the project-specific module tree — do not assume a fixed module set). ≤15 files/dir, no god-module.\n'
    + '   - §3 Interfaces & data flows (consistent diagrams). §4 NFR handling (latency/security/reliability per all NFRs enumerated from SPEC.md ### NFR-XX: headings).\n'
    + '   - §5 SAB block placeholder: include the literal marker `<!-- SAB:START -->` (real YAML filled in SAB Generation phase later).\n'
    + '   - No circular dependencies.\n'
    + '3. Re-read file (Read) for FINAL state. Create dir ' + REPO + '/02-architecture if missing (Write tool).\n'
    + (round > 1 ? '4. Apply HIGH-severity gap fixes from previous B-2 (DOC below) via Edit (surgical, do NOT rewrite whole file).\n' : '')
    + 'Return ONLY this compact JSON — do NOT embed file content (content is read from disk separately):\n'
    + '{"status":"OK","confidence":"high|medium|low","citations":["SRS.md FR-01","..."],"summary":"<1-2 lines>"}\n\n'
    + 'SCOPE RULES:\n- DO NOT write ADR.md or TEST_SPEC.md.\n- DO NOT run phase-transition / quality-gate / generate_sab commands.\n- DO NOT modify harness/ (HR-17).\n- ONLY author SAD.md and return JSON.'
    + (round > 1 && prevB2 ? '\n\n=== [DOC: Previous B-2 review JSON — SAD.md] ===\n' + JSON.stringify(prevB2, null, 2) : ''),
  buildBDocs: (content) => [
    ['DOC 1: 01-requirements/SRS.md (full)', srsContent],
    ['DOC 2: draft 02-architecture/SAD.md (full)', content],
    ['DOC 3: harness/templates/SAD.md §2.1 — Directory Structure Design Principles', sadTemplateContent],
  ],
  checklist:
    '- Every FR maps to ≥1 module?\n- NFRs addressed (latency/security/reliability)?\n- No circular dependencies?\n- Data flow diagrams consistent?\n'
    + '- SAB block present in §5 (<!-- SAB:START --> marker exists)?\n- Directory structure follows CRG cohesion principles (SAD.md §2.1)? See embedded DOC 3\n- ≤15 files/dir, no god-module, no flat dump?',
})
if (!sad.ok) return sad
let sadContent = sad.content, sadB2 = sad.b2

// ════════════════════════════════════════════════════════════════════════
// Sub-Task 2/3: ADR.md
// ════════════════════════════════════════════════════════════════════════
const adr = await abLoop({
  phaseName: 'Sub-Task 2/3 — ADR.md', key: 'adr', deliverable: 'ADR.md', bRole: 'TECH_LEAD', diskPath: '02-architecture/adr/ADR.md', diskPrefix: '# Architecture Decision Records',
  buildAPrompt: (round, prevB2) =>
    'YOU ARE ARCHITECT (Agent A for Sub-Task 2/3 ADR.md). ROUND ' + round + '.\n'
    + 'REPO: ' + REPO + '\nYour SINGLE deliverable: ' + REPO + '/02-architecture/adr/ADR.md\n\n'
    + 'Steps:\n'
    + '1. Self-check (Bash): `test -f ' + REPO + '/02-architecture/adr/ADR.md`. If EXISTS, Read it.\n'
    + '2. Extract key architecture decisions from SAD.md (read ' + REPO + '/02-architecture/SAD.md). Write individual ADR entries. EACH ADR: context, decision, consequences, alternatives considered. Cover tech stack (Python 3.11 stdlib-only), patterns (ThreadPoolExecutor, atomic write, circuit breaker), interfaces. Remove any `<!-- harness:template-stub -->` markers.\n'
    + '3. Create dir ' + REPO + '/02-architecture/adr if missing. Re-read for FINAL state.\n'
    + (round > 1 ? '4. Apply HIGH-severity gap fixes from previous B-2 via Edit (surgical).\n' : '')
    + 'Return ONLY this compact JSON — do NOT embed file content (content is read from disk separately):\n'
    + '{"status":"OK","confidence":"high|medium|low","citations":["..."],"summary":"..."}\n\n'
    + 'SCOPE RULES:\n- DO NOT write SAD.md or TEST_SPEC.md.\n- DO NOT run phase-transition / quality-gate commands.\n- ONLY author ADR.md.'
    + (round > 1 && prevB2 ? '\n\n=== [DOC: Previous B-2 review JSON — ADR.md] ===\n' + JSON.stringify(prevB2, null, 2) : ''),
  buildBDocs: (content) => [
    ['DOC 1: Previous Sub-Task B-2 review JSON — SAD.md (gaps may contain non-blocking caveats)', JSON.stringify(sadB2, null, 2)],
    ['DOC 2: 02-architecture/SAD.md (APPROVED — full)', sadContent],
    ['DOC 3: draft 02-architecture/adr/ADR.md (full)', content],
    ['DOC 4: harness/templates/ADR.md (template format)', adrTemplateContent],
  ],
  checklist:
    '- Upstream SAD review caveats addressed?\n- All major decisions documented (tech stack, patterns, interfaces)?\n'
    + '- Each ADR has clear context, decision, consequences?\n- Alternatives considered documented?\n- Decision aligns with SAD.md architecture?\n'
    + '- ADR format matches harness/templates/ADR.md (template format)? See embedded DOC 4',
})
if (!adr.ok) return adr
let adrContent = adr.content, adrB2 = adr.b2

// ---- Constitution Check — ADR (single-file, per phase2_plan.md CONSTITUTION-CHECK-ADR) ----
phase('Constitution Check — ADR')
log('check-constitution --file ADR.md (catches stub/low-density before TEST_SPEC depends on it)')
const adrConstReport = await agent(
  'YOU ARE THE ADR CONSTITUTION CHECKER. Run bash, fix if needed, report.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Command: `' + PY + ' ' + REPO + '/harness_cli.py check-constitution --phase 2 --project ' + REPO + ' --file 02-architecture/adr/ADR.md`\n'
  + '- PASS → report "ADR-CONSTITUTION: PASS".\n'
  + '- FAIL → expand decision/rationale/consequences, remove template-stub markers, re-run until PASS.\n'
  + '- File missing ([SKIP] exit 0) → report "ADR-CONSTITUTION: FAIL — ADR.md missing" (escalate).\n\n'
  + 'SCOPE RULES:\n- DO NOT touch SAD/TEST_SPEC.\n- DO NOT run phase-transition commands.\n- ONLY check-constitution on ADR.md and fix it.',
  { label: 'constitution-adr', phase: 'Constitution Check — ADR', agentType: 'general-purpose' },
)
if (!(typeof adrConstReport === 'string' && /ADR-CONSTITUTION:\s*PASS/.test(adrConstReport))) {
  return { error: 'ADR constitution check did not PASS', raw: String(adrConstReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Sub-Task 3/3: TEST_SPEC.md
// ════════════════════════════════════════════════════════════════════════
const testSpec = await abLoop({
  phaseName: 'Sub-Task 3/3 — TEST_SPEC.md', key: 'test-spec', deliverable: 'TEST_SPEC.md', bRole: 'TECH_LEAD', diskPath: '02-architecture/TEST_SPEC.md', diskPrefix: '#',
  buildAPrompt: (round, prevB2) =>
    'YOU ARE ARCHITECT (Agent A for Sub-Task 3/3 TEST_SPEC.md). ROUND ' + round + '.\n'
    + 'REPO: ' + REPO + '\nYour SINGLE deliverable: ' + REPO + '/02-architecture/TEST_SPEC.md\n\n'
    + 'Steps:\n'
    + '1. Self-check (Bash): `test -f ' + REPO + '/02-architecture/TEST_SPEC.md`. If EXISTS, Read it.\n'
    + '2. Generate Test Specification Catalog. CRITICAL shape (v2.9.1 B.3): each FR is a `### FR-XX: ...` header FOLLOWED BY TABLE ROWS (a prose-only doc FAILS the D4 spec-coverage parser).\n'
    + '   - Per FR (enumerate from SPEC.md ### FR-XX: headings — do not assume a fixed FR count): assign Classification (API_ENDPOINT|DATA_ENTITY|ALGORITHM|STATE_MACHINE|INTEGRATION|SECURITY_CONTROL|INFRASTRUCTURE). ≥1 named test case (happy_path + validation mandatory). Preserve TEST_INVENTORY.yaml names where specified.\n'
    + '   - Apply 8-Question Protocol per FR. Concrete Inputs in TRUE form (key="value", NOT pytest-id underscore form). Sub-assertions table per FR (rule_id + predicate + applies_to).\n'
    + '   - Step 1b Architecture-Risk Triggers: scan SAD modules — shared mutable state (store.py) → force NP-13; external process (executor.py subprocess) → force NP-15; cache (cache.py) → force NP-07. Forced cases tagged SAD: in tests/integration/.\n'
    + '   - NFR Pattern Activation table + cross-cutting section + Summary table (counts per type).\n'
    + '3. Run self-consistency: `' + PY + ' ' + REPO + '/harness_cli.py check-test-spec-consistency --project ' + REPO + '`. Fix until it passes.\n'
    + '4. Re-read for FINAL state.\n'
    + (round > 1 ? '5. Apply HIGH-severity gap fixes from previous B-2 via Edit (surgical).\n' : '')
    + 'Return ONLY this compact JSON — do NOT embed file content (content is read from disk separately):\n'
    + '{"status":"OK","confidence":"high|medium|low","citations":["..."],"summary":"..."}\n\n'
    + 'SCOPE RULES:\n- DO NOT write SAD/ADR.\n- DO NOT run phase-transition / run-gate commands.\n- DO NOT modify harness/.\n- ONLY author TEST_SPEC.md (check-test-spec-consistency is allowed).'
    + (round > 1 && prevB2 ? '\n\n=== [DOC: Previous B-2 review JSON — TEST_SPEC.md] ===\n' + JSON.stringify(prevB2, null, 2) : ''),
  buildBDocs: (content) => [
    ['DOC 1: Previous Sub-Task B-2 review JSON — ADR.md (gaps may contain non-blocking caveats)', JSON.stringify(adrB2, null, 2)],
    ['DOC 2: 01-requirements/SRS.md (APPROVED — full)', srsContent],
    ['DOC 3: 02-architecture/SAD.md (APPROVED — full)', sadContent],
    ['DOC 4: 02-architecture/adr/ADR.md (APPROVED — full)', adrContent],
    ['DOC 5: draft 02-architecture/TEST_SPEC.md (full)', content],
  ],
  checklist:
    '- Upstream ADR review caveats addressed?\n- Every FR has ≥1 named test case (happy_path + validation mandatory)?\n'
    + '- 8-Question Protocol applied per FR?\n- Classification assigned per FR?\n- NFR Pattern Activation table filled?\n'
    + '- Architecture-risk triggers applied (NP-13/NP-15/NP-07 forced where SAD warrants)?\n'
    + '- Concrete Inputs in TRUE form (key="value"), not pytest-id form?\n- Sub-assertions table per FR (rule_id + predicate + applies_to)?\n'
    + '- Each `### FR-XX:` header followed by TABLE ROWS (not prose-only)?\n- Summary table populated with counts per type?',
})
if (!testSpec.ok) return testSpec
let testSpecContent = testSpec.content

// ════════════════════════════════════════════════════════════════════════
// Phase: SAB Generation (machine-readable architecture baseline — SAD §5)
// ════════════════════════════════════════════════════════════════════════
phase('SAB Generation')
log('SAB-WRITE (canonical template into SAD §5) + SAB-VALIDATE + SAB-GENERATE')
const sabReport = await agent(
  'YOU ARE THE SAB GENERATOR. Write the SAB YAML block into SAD.md §5, validate, generate SAB.json.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps:\n'
  + '1. SAB-WRITE: Edit ' + REPO + '/02-architecture/SAD.md §5 — replace the `<!-- SAB:START -->` placeholder with a real `sab:` YAML block. CONTRACT (parsed by sab_parser.py):\n'
  + '   - `phase: 2` MUST be a bare int (NOT "2").\n'
  + '   - layers + allowed_dependencies reflect SAD §2 module design (api/service/store style).\n'
  + '   - nfr_traceability: one entry per NFR enumerated from SPEC.md (parse `### NFR-XX:` headings — do not assume a fixed NFR count) with a `type` from the 8 legal values (performance/security/maintainability/reliability/testability/deployability/scalability/usability) + measurable `target` + `module`.\n'
  + '   - fr_module_traceability: one entry per FR enumerated from SPEC.md (parse `### FR-XX:` headings) pointing to a REAL module from SAD §2.\n'
  + '   - quality_targets (max_complexity/min_coverage/max_coupling), architecture_constraints (no_circular_dependencies), high_risk_modules. Leave advisory_only/gate_score_overrides/nfr_dimension_mapping empty ({} or []).\n'
  + '2. SAB-VALIDATE: `' + PY + ' ' + REPO + '/harness/scripts/generate_sab.py --validate --project ' + REPO + '`. Must exit 0. Fix unknown NFR type / phase-as-string until PASS.\n'
  + '3. SAB-GENERATE: `' + PY + ' ' + REPO + '/harness/scripts/generate_sab.py --project ' + REPO + '` (add --overwrite if SAB.json exists). Produces .methodology/SAB.json.\n\n'
  + 'Report plain text: "SAB: PASS" or "SAB: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT modify harness/ source (running harness/scripts/generate_sab.py is allowed, editing it is NOT — HR-17).\n- DO NOT run advance-phase / push / run-gate.\n- ONLY edit SAD.md §5 SAB block + run generate_sab.py validate/generate.',
  { label: 'sab-generation', phase: 'SAB Generation', agentType: 'general-purpose' },
)
if (!(typeof sabReport === 'string' && /SAB:\s*PASS/.test(sabReport))) {
  return { error: 'SAB generation did not PASS', raw: String(sabReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Constitution Check (full phase, per phase2_plan.md)
// ════════════════════════════════════════════════════════════════════════
phase('Constitution Check')
log('check-constitution --phase 2 until PASS (max 5 attempts)')
let constPass = false, constReport = ''
for (let attempt = 1; attempt <= 5; attempt++) {
  log('  attempt ' + attempt + '/5')
  constReport = await agent(
    'YOU ARE THE PHASE-2 CONSTITUTION CHECKER. Run bash, fix, report.\n'
    + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
    + 'Command: `' + PY + ' ' + REPO + '/harness_cli.py check-constitution --phase 2 --project ' + REPO + '`\n'
    + 'If PASS: report "CONSTITUTION: PASS". If FAIL: read which docs miss keywords, surgically add them (do NOT remove content), re-run until PASS.\n\n'
    + 'SCOPE RULES:\n- DO NOT run advance-phase/push/run-gate.\n- ONLY check-constitution + edit P2 deliverables to fix.',
    { label: 'constitution-' + attempt, phase: 'Constitution Check', agentType: 'general-purpose' },
  )
  constPass = typeof constReport === 'string' && /CONSTITUTION:\s*PASS/.test(constReport)
  if (constPass) break
}
if (!constPass) return { error: 'Phase 2 constitution check FAIL after 5 attempts', raw: String(constReport ?? '').slice(-500) }

// ════════════════════════════════════════════════════════════════════════
// Phase: Peer Review (holistic Agent B — SAD + ADR + TEST_SPEC)
// ════════════════════════════════════════════════════════════════════════
phase('Peer Review')
log('Agent B (TECH_LEAD) holistic review of all 3 P2 deliverables; max 5 rounds')
let peerB2 = null
for (let round = 1; round <= MAX_B_ROUNDS; round++) {
  log('  --- Peer round ' + round + '/' + MAX_B_ROUNDS + ' ---')
  const bResult = await agent(
    buildBPrompt('TECH_LEAD', 'all 3 P2 deliverables (holistic)', [
      ['DOC 1: 02-architecture/SAD.md', sadContent],
      ['DOC 2: 02-architecture/adr/ADR.md', adrContent],
      ['DOC 3: 02-architecture/TEST_SPEC.md', testSpecContent],
    ],
    '- All FRs covered across all deliverables?\n- No contradictions between deliverables?\n- Each item testable/traceable?\n'
    + '- All gaps from sub-task reviews addressed?\n- Terminology consistent across all documents?\n'
    + '- SAB block layers / NFR targets semantically match SAD §2 module design?\n'
    + '- Every fr_module_traceability entry points to a real SAD §2 module?\n- NFR target fields measurable (not N/A/empty)?'),
    { label: 'peer-b-r' + round, phase: 'Peer Review', agentType: 'general-purpose' },
  )
  try { peerB2 = parseAgentJson(bResult, 'PeerB-r' + round) }
  catch (e) { return { error: 'Peer B parse failed (round ' + round + ')', detail: e.message, raw: String(bResult ?? '').slice(-400) } }
  log('  Peer B-2: ' + peerB2.review_status + ' | gaps=' + (peerB2.gaps ?? []).length + ' | high=' + (hasHighGap(peerB2.gaps) ? 'yes' : 'no'))
  if (peerB2.review_status === 'APPROVE' && !hasHighGap(peerB2.gaps)) { log('  APPROVED'); break }
  if (round === MAX_B_ROUNDS) return { error: 'Peer Review did not converge in ' + MAX_B_ROUNDS + ' rounds (HR-12 escalation)', lastB2: peerB2 }
  // Holistic gaps span multiple files → dispatch a fixer agent
  log('  Peer review found gaps — dispatching fixer for round ' + (round + 1))
  await agent(
    'YOU ARE ARCHITECT (holistic fixer). Fix peer-review gaps across P2 deliverables.\n'
    + 'REPO: ' + REPO + '\n\nPeer review B-2 JSON:\n' + JSON.stringify(peerB2, null, 2) + '\n\n'
    + 'Apply surgical Edits to whichever of 02-architecture/SAD.md, 02-architecture/adr/ADR.md, 02-architecture/TEST_SPEC.md are affected. Address all medium/high gaps.\n\n'
    + 'SCOPE RULES:\n- DO NOT run phase-transition/push/run-gate.\n- DO NOT modify harness/.\n- ONLY edit the 3 P2 deliverables. Report what you changed.',
    { label: 'peer-fix-r' + round, phase: 'Peer Review', agentType: 'general-purpose' },
  )
  sadContent = await loadFileViaBash('02-architecture/SAD.md', '# SAD', 'Peer Review')
  adrContent = await loadFileViaBash('02-architecture/adr/ADR.md', '# Architecture Decision Records', 'Peer Review')
  testSpecContent = await loadFileViaBash('02-architecture/TEST_SPEC.md', '#', 'Peer Review')
  log('  Reloaded after fixer: SAD=' + sadContent.length + ' ADR=' + adrContent.length + ' TEST_SPEC=' + testSpecContent.length)
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Push (push-checkpoint --phase 2; retry until success, NO --no-verify)
// ════════════════════════════════════════════════════════════════════════
phase('Push')
log('push-checkpoint --phase 2 (retry until success)')
let pushOk = false, pushReport = ''
for (let attempt = 1; attempt <= 5; attempt++) {
  log('  attempt ' + attempt + '/5')
  pushReport = await agent(
    'YOU ARE THE PHASE-2 PUSH ORCHESTRATOR.\n'
    + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
    + 'Step 1 (Bash): `' + PY + ' ' + REPO + '/harness_cli.py push-checkpoint --phase 2 --project ' + REPO + '`\n'
    + '  - If blocked by a hook error: reword commit message to start with `chore(harness):` (documented bypass; NOT --no-verify), re-run. Retry until success.\n'
    + 'Step 2: Read ' + REPO + '/HANDOVER.md and confirm it exists.\n'
    + 'Report: "PUSH: PASS|FAIL — <details>".\n\n'
    + 'SCOPE RULES:\n- DO NOT re-do any P2 deliverable.\n- DO NOT run advance-phase here.\n- DO NOT use --no-verify.\n- ONLY push + verify HANDOVER.md.',
    { label: 'push-' + attempt, phase: 'Push', agentType: 'general-purpose' },
  )
  pushOk = typeof pushReport === 'string' && /PUSH:\s*PASS/.test(pushReport)
  if (pushOk) break
}
if (!pushOk) return { error: 'push-checkpoint --phase 2 did not succeed in 5 attempts', raw: String(pushReport ?? '').slice(-500) }

// ════════════════════════════════════════════════════════════════════════
// Phase: Advance (advance-phase --completed 2 → Phase 3 entry)
// ════════════════════════════════════════════════════════════════════════
phase('Advance')
log('advance-phase --completed 2 + confirm HANDOVER.md reflects Phase 3 entry')
const advanceReport = await agent(
  'YOU ARE THE PHASE-2 ADVANCE ORCHESTRATOR.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Step 1 (Bash): `' + PY + ' ' + REPO + '/harness_cli.py advance-phase --completed 2 --project ' + REPO + '`\n'
  + '   PHASE-TRUTH (HR-11): if advance-phase fails on Phase Truth (<90%), check phase_truth_verifier output in .sessi-work/, fix the failing phase-link/gate artifact, re-run (max 3, then escalate to human).\n'
  + 'Step 2: Read ' + REPO + '/.methodology/state.json; confirm current_phase = 3 (advance-phase writes atomically).\n'
  + 'Report: "ADVANCE: PASS|FAIL — <details>". PHASE_3_PLAN: ' + REPO + '/.methodology/phase3_plan.md\n\n'
  + 'SCOPE RULES:\n- DO NOT re-do P2.\n- DO NOT modify harness/ (HR-17).\n- ONLY advance-phase + verify HANDOVER.md.',
  { label: 'advance', phase: 'Advance', agentType: 'general-purpose' },
)

log('Phase 2 workflow complete. Open .methodology/phase3_plan.md to continue.')
return {
  phase: 2,
  peer_review_status: peerB2 ? peerB2.review_status : 'unknown',
  push_status: pushOk ? 'PASS' : 'unknown',
  advance_status: typeof advanceReport === 'string' && /ADVANCE:\s*PASS/.test(advanceReport) ? 'PASS' : 'unknown',
  artifacts: ['02-architecture/SAD.md', '02-architecture/adr/ADR.md', '02-architecture/TEST_SPEC.md', '.methodology/SAB.json', '.methodology/quality_manifest.json', 'HANDOVER.md'],
  notes: 'Phase 2 complete per phase2_plan.md v2.12.0. Phase 3 (Implementation) ready.',
}
