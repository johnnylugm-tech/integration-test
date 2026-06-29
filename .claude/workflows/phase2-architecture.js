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
// P-01 mirror: peer review is a quality advisory, not a functional gate.
// Round 3 REJECT → PEER_REVIEW_ADVISORY (non-blocking) instead of HR-12.
const MAX_PEER_ROUNDS = 3
// v28: retry at orchestrator level, not inside one outer agent call. Single-prompt
// write+verify via mcp__filesystem__. See persistApproval.
const MAX_OUTER_ATTEMPTS = 3
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

// ---- B prompt builder (plan-faithful revision; mirrors phase1-requirements v12) ----
// Plan §B-1 originally said "STATELESS sandbox: ZERO file access". That
// assumption is OBSOLETE — Agent B is general-purpose with full Bash/Read
// tool access. Verbatim-DOC-embedding for all 3 P2 deliverables + upstream
// SRS.md pushes B's prompt past 60k tokens, dispersing attention so badly
// that B can hallucinate the deliverable's identity in late rounds (R5).
//
// Fix: prompt B to USE Bash/Read for fresh disk view. Embedded docs become
// a SUMMARY (headings + counts) for orientation, NOT the sole source of
// truth. prevB2 is filtered to drop `reason` (only `gaps` survives —
// structured, machine-readable, hard to confabulate).
function buildBPrompt(role, deliverable, docs, checklist) {
  let p = 'You are ' + role + '. Your task: review the following deliverable (' + deliverable + ').\n'
    + 'You have FULL access to Bash and Read tools — USE THEM to cat/Read the\n'
    + 'freshest version of every file you cite. The DOC blocks below are a SUMMARY\n'
    + 'snapshot for orientation; for any citation file:line, you MUST re-read that\n'
    + 'file via Read/Bash first. Do NOT extend any prior round\'s `reason` verbatim\n'
    + 'into your own reasoning — read disk, then judge.\n\n'
  for (let i = 0; i < docs.length; i++) p += '=== [' + docs[i][0] + '] ===\n' + docs[i][1] + '\n\n'
  p += 'Review checklist:\n' + checklist + '\n\n'
    + 'SCHEMA REQUIREMENTS (advance-phase `harness_cli.py _verify_agent_b_approvals_core` REJECTS the approval if any of these fail — observed 2026-06-29 wf_3a9377cb):\n'
    + '  - `reason`: ≥ 100 characters of substantive justification. NOT "APPROVE", "OK", or other one-word response.\n'
    + '  - `citations`: array of "file:line" strings. Must contain ≥ 1 entry that cites a SPECIFIC line you verified via Read/Bash.\n'
    + '  - `docs_embedded`: array of file paths/identifiers you actually read during this review. CRITICAL — the harness basename-matcher (advance-phase `_norm()`) looks for PURE basenames like "SAD.md", "ADR.md", "TEST_SPEC.md", NOT descriptive strings. Use bare basenames only.\n\n'
    + 'Return JSON only (no markdown fences, no commentary). Schema:\n'
    + '{"review_status":"APPROVE"|"REJECT","reason":"<concise>","citations":["file:line"],"docs_embedded":["..."],"gaps":[{"severity":"low|medium|high","message":"...","fr_id":"<FR-XX or null>"}]}\n\n'
    + 'IMPORTANT: Return ONLY the JSON object as your final message. No prose before or after.'
  return p
}

// ---- safePrevB2: strip prev-round `reason` to defeat premise persistence ----
function safePrevB2(prevB2) {
  if (!prevB2) return null
  return {
    review_status: prevB2.review_status,
    gaps: Array.isArray(prevB2.gaps) ? prevB2.gaps : [],
  }
}

// ---- makeDocSummary: collapse full content → headings + counts ----
// Used for APPROVED upstream docs (B does not re-review them; they're context
// for the deliverable under review). Trims ~95% of token volume while
// preserving the structural skeleton B needs to orient.
function makeDocSummary(content, opts) {
  opts = opts || {}
  const lines = content.split('\n')
  const headings = []
  for (const ln of lines) {
    const m = ln.match(/^(#{1,6})\s+(.+?)\s*$/)
    if (m) headings.push(m[2].slice(0, 80))
  }
  const summary = {
    line_count: lines.length,
    char_count: content.length,
    headings: headings.slice(0, 40),
  }
  if (opts.includeFirstLines) {
    summary.first_3_lines = lines.slice(0, 3).map(l => l.slice(0, 120))
  }
  return JSON.stringify(summary, null, 2)
}

// ---- runBSelfVerify (mirrors phase1 §B-2.5 X1 mitigation) ----
// Dispatch B (fresh STATELESS context) to verify its OWN citations and
// atomic claims via Bash (sed/grep). Returns verify metadata attached to
// b2.verify. Does NOT change review_status — purely observability.
async function runBSelfVerify(cfg, b2, round) {
  const prompt =
    'YOU ARE B SELF-VERIFIER for ' + cfg.deliverable + ' (round ' + round + ').\n'
    + 'Your task: verify that the previous B review\'s citations and claims '
    + 'have actual evidence on disk. You are NOT asked to re-review the '
    + 'deliverable — only to check that what B claimed is true.\n\n'
    + 'Previous B review JSON:\n' + JSON.stringify(b2, null, 2) + '\n\n'
    + 'DELIVERABLE: ' + REPO + '/' + cfg.diskPath + '\n\n'
    + 'Steps (MAX 6 Bash calls total — stop and return what you have if you reach 6):\n'
    + '1. Read the deliverable ONCE: Bash `cat ' + REPO + '/' + cfg.diskPath + '`.\n'
    + '2. For ALL gap.citations: check against the content you already read — '
    + 'no additional file reads per citation. Set verified:true if the cited text supports gap.message.\n'
    + '3. For REJECT.reason claims: identify the 1-3 most specific noun/verb keywords\n'
    + '   from each claim, then run ONE combined Bash grep:\n'
    + '   grep -n "<keyword_1>\\|<keyword_2>" ' + REPO + '/' + cfg.diskPath + '\n'
    + '   (Replace <keyword_N> with actual words from the claims. 1 Bash call max.\n'
    + '    If no reason claims exist, skip this step.)\n'
    + '4. Return compact JSON ONLY (no markdown, no commentary):\n'
    + '{"verified_gaps":[{"message":"<short>","citation":"<short>","verified":true|false,"evidence":"<1-line or empty>"}],'
    + '"unverified_reason_claims":["<short fragment>"],'
    + '"recalibrated_review":"APPROVE"|"REJECT",'
    + '"confidence":"high|medium|low"}\n'
  const res = await agent(prompt, {
    label: 'verify-b-' + cfg.key + '-r' + round,
    phase: cfg.phaseName,
    agentType: 'general-purpose',
  })
  try { return parseAgentJson(res, 'verify-' + cfg.key + '-r' + round) }
  catch (e) { log('  X1 verify parse failed: ' + e.message.slice(0, 80)); return null }
}

function summarizeVerify(b2, verify) {
  if (!verify) return 'verify=skipped'
  const gaps = b2.gaps ?? []
  const total = gaps.length
  const verified = (verify.verified_gaps ?? []).filter(function (g) { return g.verified }).length
  const unverifiedClaims = (verify.unverified_reason_claims ?? []).length
  const ratio = total > 0 ? verified / total : 1
  const flag = ratio < 0.5 ? ' [X1: B UNSTABLE — majority unverified]' : ''
  return 'verify=' + verified + '/' + total + ' gaps_verified' + (unverifiedClaims > 0 ? ' | ' + unverifiedClaims + ' unverified_reason_claims' : '') + flag
}

// ---- Generic A/B loop (returns {ok,content,b2} or {error,...} — caller propagates) ----
// cfg: { phaseName, key, deliverable, bRole, buildAPrompt(round,prevB2), buildBDocs(content), checklist }
async function abLoop(cfg) {
  phase(cfg.phaseName)
  log(cfg.deliverable + ': A/B loop (max ' + MAX_B_ROUNDS + ' rounds)')
  let content = '', b2 = null
  for (let round = 1; round <= MAX_B_ROUNDS; round++) {
    log('  --- ' + cfg.deliverable + ' round ' + round + '/' + MAX_B_ROUNDS + ' ---')
    // v15: budget guard (Bug #3 mitigation)
    if (typeof budget !== 'undefined' && budget.remaining && budget.remaining() < 50000) {
      const rem = Math.round((budget.remaining() || 0) / 1000)
      log('  BUDGET LOW (' + rem + 'k) -- exiting ' + cfg.deliverable)
      if (b2 && b2.review_status === 'APPROVE') return { ok: true, content, b2, budget_exhausted: true }
      if (b2) return { ok: false, content, b2, budget_exhausted: true }
      return { error: 'Budget exhausted during ' + cfg.deliverable, budget_exhausted: true }
    }
    // v15: wrap agent() in try/catch (Bug #2 mitigation)
    let aResult
    try { aResult = await agent(cfg.buildAPrompt(round, b2), {
      label: 'a-' + cfg.key + '-r' + round, phase: cfg.phaseName, agentType: 'general-purpose',
    }) } catch (e) {
      if (round === MAX_B_ROUNDS) return { error: cfg.deliverable + ' A agent failed at max rounds', detail: String(e.message ?? e).slice(0, 200) }
      log('  A agent failed: ' + String(e.message ?? e).slice(0, 80) + ' -- retrying'); continue
    }
    let a
    try { a = parseAgentJson(aResult, 'A-' + cfg.key + '-r' + round) }
    catch (e) { log('  A JSON parse fail (likely truncated): ' + e.message.slice(0, 80)); a = null }
    content = await loadFileViaPython(cfg.diskPath, cfg.diskPrefix || '', cfg.phaseName)
    if (content.startsWith('ERROR:') || content.length < 50) {
      return { error: cfg.deliverable + ' not found on disk after A (round ' + round + ')', loader_preview: content.slice(0, 200) }
    }
    log('  A status=' + (a && a.status ? a.status : 'assumed-OK') + ' | disk loaded: ' + content.length + ' chars, confidence=' + (a && a.confidence ? a.confidence : '?'))

    // v15: wrap agent() in try/catch (Bug #2 mitigation)
    let bResult
    try { bResult = await agent(buildBPrompt(cfg.bRole, cfg.deliverable, cfg.buildBDocs(content), cfg.checklist), {
      label: 'b-' + cfg.key + '-r' + round, phase: cfg.phaseName, agentType: 'general-purpose',
    }) } catch (e) {
      if (round === MAX_B_ROUNDS) return { error: cfg.deliverable + ' B agent failed at max rounds', detail: String(e.message ?? e).slice(0, 200) }
      log('  B agent failed: ' + String(e.message ?? e).slice(0, 80) + ' -- retrying'); continue
    }
    try { b2 = parseAgentJson(bResult, 'B-' + cfg.key + '-r' + round) }
    catch (e) {
      if (round === MAX_B_ROUNDS) return { error: cfg.deliverable + ' B parse failed at max rounds', detail: e.message }
      log('  B parse failed: ' + e.message + ' — retrying'); continue
    }
    log('  B-2: ' + b2.review_status + ' | gaps=' + (b2.gaps ?? []).length + ' | high=' + (hasHighGap(b2.gaps) ? 'yes' : 'no'))

    // X1 self-verify (mirrors phase1 §B-2.5; observability, NOT veto)
    b2.verify = await runBSelfVerify(cfg, b2, round)
    log('  ' + summarizeVerify(b2, b2.verify))
    if (b2.review_status === 'APPROVE' && !hasHighGap(b2.gaps)) {
      log('  APPROVED')
      // Persist Agent B approval JSON (harness _verify_agent_b_approvals_core contract).
      // approval filename = "<did>.json" where did IS the full _PHASE_DELIVERABLES[N]
      // entry (e.g. "SAD.md" → "SAD.md.json"). DO NOT strip the extension — harness
      // matches the file via `approvals_dir / f"{did}.json"`.
      const approvalId = cfg.deliverable
      await persistApproval(approvalId, b2)
      return { ok: true, content, b2 }
    }
    if (round === MAX_B_ROUNDS) return { error: cfg.deliverable + ': B did not converge in ' + MAX_B_ROUNDS + ' rounds (HR-12 escalation)', lastB2: b2 }
    // APPROVE+high OR REJECT → A fixes next round
  }
  return { error: cfg.deliverable + ' loop exhausted unexpectedly' }
}

// ---- persistApproval: write .methodology/agent_b_approvals/<id>.json — v30 strategy ----
//
// Mirror of phase1-requirements.js v30 persistApproval. v22 single-line Bash +
// harness_cli.py write-approval (proven 6/6 advance-phase PASS) + workflow JS
// outer-level try/catch retry. See phase1-requirements.js for full v17/v22/v27/
// v28/v30 history.
async function persistApproval(deliverableId, b2) {
  const approvalPayload = JSON.stringify({
    fr: deliverableId,
    review_status: b2.review_status ?? 'APPROVE',
    reason: (b2.reason ?? ('Approved ' + deliverableId + ' (reason omitted)')).slice(0, 800),
    citations: Array.isArray(b2.citations) ? b2.citations.slice(0, 20) : [],
    docs_embedded: Array.isArray(b2.docs_embedded) ? b2.docs_embedded : [],
    confidence: typeof b2.confidence === 'number' ? b2.confidence : 0.9,
  }, null, 2)
  const cliPath = REPO + '/harness/harness_cli.py'
  const cmd = PY + ' ' + cliPath + ' write-approval --fr-id ' +
    JSON.stringify(deliverableId) + ' --json ' + JSON.stringify(approvalPayload)

  let lastErr = null
  for (let attempt = 1; attempt <= MAX_OUTER_ATTEMPTS; attempt++) {
    let res
    try {
      res = await agent(
        'You are a SHELL WRAPPER AGENT. Run EXACTLY this Bash command and emit stdout + exit code verbatim:\n\n' + cmd + '\n\nNo commentary, no preamble, no other tool calls.',
        { label: 'persist-' + deliverableId + '-try' + attempt, phase: 'Persist Approval', agentType: 'general-purpose' },
      )
    } catch (e) {
      lastErr = 'agent() threw: ' + (e && e.message ? e.message : String(e))
      log('  persistApproval ' + deliverableId + ' attempt ' + attempt + '/' + MAX_OUTER_ATTEMPTS + ': ' + lastErr.slice(0, 200))
      continue
    }
    if (typeof res === 'string' && /\[write-approval\]\s*OK/.test(res)) {
      log('  persisted approval: ' + deliverableId + ' (attempt ' + attempt + '/' + MAX_OUTER_ATTEMPTS + ')')
      return
    }
    lastErr = 'CLI did not return OK; got: ' + String(res).slice(0, 400)
    log('  persistApproval ' + deliverableId + ' attempt ' + attempt + '/' + MAX_OUTER_ATTEMPTS + ': ' + lastErr)
  }
  throw new Error('persistApproval FAILED for ' + deliverableId + ' after ' + MAX_OUTER_ATTEMPTS + ' attempts. Last error: ' + lastErr)
}

// ---- loadFileViaPython: mcp__filesystem__read_file + v16 fallback (v30) ----
//
// Mirror of phase1-requirements.js v30 loadFileViaPython. v29 mcp primary +
// v16 single-line Bash + harness_cli.py read-file fallback. See phase1 for full
// v17/v22/v29/v30 history.
async function loadFileViaPython(relPath, expectPrefix, phaseName, opts) {
  opts = opts || {}
  const maxAttempts = opts.maxAttempts || 3
  const filePath = REPO + '/' + relPath
  const prompt = [
    'Read a file using ONLY the mcp__filesystem__* tools (NO Bash, NO Read, NO cat, NO python).',
    '',
    'STEP 1 — mcp__filesystem__read_file with EXACTLY: file = ' + filePath,
    '',
    'STEP 2 — Reply with the EXACT verbatim text content returned by read_file.',
    '   - NO preamble, NO acknowledgement, NO explanation.',
    '   - DO NOT echo the tool name or any instruction text.',
    '   - DO NOT add markdown fences, headers, or summary wrappers.',
    '   - Your final message body = the raw text bytes of the file.',
    '   - If the file is missing or any tool error occurs: reply EXACTLY: ERROR_LOAD_FAILED: ' + filePath,
  ].join('\n')

  let lastReason = ''
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const res = await agent(prompt, {
      label: 'loadpy-' + relPath.replace(/[\/.]/g, '-') + '-a' + attempt,
      phase: phaseName,
      agentType: 'general-purpose',
    })
    const text = (typeof res === 'string' ? res : String(res ?? '')).trim()
    if (text.startsWith('ERROR_LOAD_FAILED')) { lastReason = 'mcp-error'; break }
    if (text.length < 50) {
      lastReason = 'too-short(len=' + text.length + ')'
      log('  [' + relPath + '] attempt ' + attempt + '/' + maxAttempts + ' ' + lastReason)
      continue
    }
    if (expectPrefix) {
      const head = text.slice(0, 500)
      const stripped = expectPrefix.replace(/^#\s*/, '')
      const escaped = stripped.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const anchorRe = new RegExp('^#\\s+[^\\n]*' + escaped, 'm')
      if (!anchorRe.test(head)) {
        lastReason = 'prefix-mismatch'
        log('  [' + relPath + '] attempt ' + attempt + '/' + maxAttempts + ' ' + lastReason + ' (expected "' + expectPrefix + '", got: ' + text.slice(0, 80) + ')')
        continue
      }
    }
    return text
  }

  // v30 fallback: harness_cli.py read-file (v16 pattern; deterministic Python).
  log('  [' + relPath + '] mcp attempts exhausted (reason=' + lastReason + '); falling back to harness_cli.py read-file (v16)')
  const cliPath = REPO + '/harness/harness_cli.py'
  const cmd = PY + ' ' + cliPath + ' read-file --file ' + JSON.stringify(filePath) + ' --content-out'
  const fbRes = await agent(
    'You are a SHELL WRAPPER AGENT. Run EXACTLY this Bash command and emit stdout + exit code verbatim:\n\n' + cmd + '\n\nNo commentary, no preamble, no other tool calls.',
    { label: 'loadpy-fallback-' + relPath.replace(/[\/.]/g, '-'), phase: phaseName, agentType: 'general-purpose' },
  )
  const fbText = (typeof fbRes === 'string' ? fbRes : String(fbRes ?? ''))
  const m = fbText.match(/\[read-file\]\s*OK[\s\S]*?\n([\s\S]*)$/)
  const content = (m ? m[1] : fbText).trim()
  if (content.length >= 50) {
    if (expectPrefix) {
      const head = content.slice(0, 500)
      const stripped = expectPrefix.replace(/^#\s*/, '')
      const escaped = stripped.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const anchorRe = new RegExp('^#\\s+[^\\n]*' + escaped, 'm')
      if (anchorRe.test(head)) return content
    } else {
      return content
    }
  }
  return 'ERROR: LOADER_FAILED_AFTER_' + maxAttempts + '_ATTEMPTS + FALLBACK: ' + relPath
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Entry & Preflight
// ════════════════════════════════════════════════════════════════════════

phase('Entry & Preflight')
log('ENTRY-CHECK + P1-ARTIFACTS + run-phase 2 + validate-handoff + CI + load-context')

const MAX_PREFLIGHT_ATTEMPTS = 3
let preflightPass = false, preflightReport = ''
for (let attempt = 1; attempt <= MAX_PREFLIGHT_ATTEMPTS; attempt++) {
  log('  preflight attempt ' + attempt + '/' + MAX_PREFLIGHT_ATTEMPTS)
  preflightReport = await agent(
    'YOU ARE THE PHASE-2 PREFLIGHT ORCHESTRATOR. Run bash commands in order; report final status.\n'
    + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
    + 'Steps:\n'
    + '1. ENTRY-CHECK (P1 review-complete): `git -C ' + REPO + ' log --oneline --grep="phase1(review-complete)" -1` OR confirm all 4 P1 files exist.\n'
    + '2. P1-ARTIFACTS: `ls ' + REPO + '/01-requirements/SRS.md ' + REPO + '/01-requirements/SPEC_TRACKING.md ' + REPO + '/01-requirements/TRACEABILITY_MATRIX.md ' + REPO + '/TEST_INVENTORY.yaml`. ALL 4 must exist — if any missing, report FAIL (return to Phase 1).\n'
    + '3. PREFLIGHT: `' + PY + ' ' + REPO + '/harness_cli.py run-phase --phase 2 --project ' + REPO + '`. If FAIL: fix FSM/Constitution/Drift, re-run.\n'
    + '4. HANDOFF: `' + PY + ' ' + REPO + '/harness_cli.py validate-handoff --from-phase 1 --project ' + REPO + '`. Must exit 0; if exit 1, read errors, fix upstream P1 deliverable, re-run.\n'
    + '5. PREFLIGHT-CI: confirm `' + REPO + '/.github/workflows/harness_quality_gate.yml` + `' + REPO + '/.git/hooks/prepare-commit-msg` exist; confirm state.json current_phase=2. If stale: `' + PY + ' ' + REPO + '/harness_cli.py init-project --phase 2 --project ' + REPO + ' --overwrite`.\n'
    + '6. LOAD-CONTEXT: `mkdir -p ' + REPO + '/.sessi-work && ' + PY + ' ' + REPO + '/harness_cli.py load-context --phase 2 --project ' + REPO + ' --json > ' + REPO + '/.sessi-work/phase2_ctx.json`.\n\n'
    + 'Report plain text: "PREFLIGHT: PASS" or "PREFLIGHT: FAIL — <one-line reason>".\n\n'
    + 'SCOPE RULES:\n'
    + '- DO NOT write any P2 deliverable (SAD/ADR/TEST_SPEC).\n'
    + '- DO NOT run advance-phase, push-checkpoint, run-gate.\n'
    + '- DO NOT modify files inside harness/ (HR-17).\n'
    + '- ONLY run the commands above, fix preflight issues, and report.',
    { label: 'preflight-' + attempt, phase: 'Entry & Preflight', agentType: 'general-purpose' },
  )
  preflightPass = typeof preflightReport === 'string' && /PREFLIGHT:\s*PASS/.test(preflightReport)
  if (preflightPass) break
}
if (!preflightPass) return { error: 'Phase 2 preflight did not PASS after ' + MAX_PREFLIGHT_ATTEMPTS + ' attempts', raw: String(preflightReport ?? '').slice(-600) }

// ════════════════════════════════════════════════════════════════════════
// Phase: Load Upstream (SRS.md — needed verbatim for stateless B reviews)
// ════════════════════════════════════════════════════════════════════════
phase('Load Upstream')
log('cat SRS.md + harness templates for embedding into stateless Agent B prompts')
const srsContent = await loadFileViaPython('01-requirements/SRS.md', '#', 'Load Upstream')
if (srsContent.startsWith('ERROR:') || srsContent.length < 50) {
  return { error: 'Failed to load SRS.md for upstream context', loaded_preview: srsContent.slice(0, 200) }
}
log('  SRS.md loaded: ' + srsContent.length + ' chars')
const sadTemplateContent = await loadFileViaPython('harness/templates/SAD.md', '#', 'Load Upstream')
log('  harness/templates/SAD.md loaded: ' + sadTemplateContent.length + ' chars')
const adrTemplateContent = await loadFileViaPython('harness/templates/ADR.md', '#', 'Load Upstream')
log('  harness/templates/ADR.md loaded: ' + adrTemplateContent.length + ' chars')

// ════════════════════════════════════════════════════════════════════════
// Sub-Task 1/3: SAD.md
// ════════════════════════════════════════════════════════════════════════
phase('Sub-Task 1/3 — SAD.md')
log('abLoop: SAD authoring (ARCHITECT A + TECH_LEAD B; max 5 rounds; HR-12 escalate)')
const sad = await abLoop({
  phaseName: 'Sub-Task 1/3 — SAD.md', key: 'sad', deliverable: 'SAD.md', bRole: 'TECH_LEAD', diskPath: '02-architecture/SAD.md', diskPrefix: '# SAD',
  buildAPrompt: (round, prevB2) =>
    'YOU ARE ARCHITECT (Agent A for Sub-Task 1/3 SAD.md). ROUND ' + round + '.\n'
    + 'REPO: ' + REPO + '\nYour SINGLE deliverable: ' + REPO + '/02-architecture/SAD.md\n\n'
    + 'Steps:\n'
    + '1. Self-check (Bash): `test -f ' + REPO + '/02-architecture/SAD.md`. If EXISTS, Read it (current state).\n'
    + '2. Author Software Architecture Document. REQUIRED:\n'
    + '   - §1 Overview. §2 Module design: every FR (enumerate from SPEC.md ### FR-XX: headings) maps to ≥1 module; follow SPEC.md §6 directory structure (read SPEC §6 for the project-specific module tree — do not assume a fixed module set). ≤15 files/dir, no god-module.\n'
    + '   - §3 Interfaces & data flows (consistent diagrams). §4 NFR handling (latency/security/cost per all NFRs enumerated from SPEC.md ### NFR-XX: headings).\n'
    + '   - §5 SAB block placeholder: include the literal marker `<!-- SAB:START -->` (real YAML filled in SAB Generation phase later).\n'
    + '   - No circular dependencies.\n'
    + '3. Re-read file (Read) for FINAL state. Create dir ' + REPO + '/02-architecture if missing (Write tool).\n'
    + (round > 1 ? '4. Apply HIGH-severity gap fixes from previous B-2 (DOC below) via Edit (surgical, do NOT rewrite whole file).\n' : '')
    + 'Return ONLY this compact JSON — do NOT embed file content (content is read from disk separately):\n'
    + '{"status":"OK","files":["02-architecture/SAD.md"],"confidence":"high|medium|low","citations":["SRS.md FR-01","..."],"summary":"<1-2 lines>"}\n\n'
    + 'SCOPE RULES:\n- DO NOT write ADR.md or TEST_SPEC.md.\n- DO NOT run phase-transition / quality-gate / generate_sab commands.\n- DO NOT modify harness/ (HR-17).\n- ONLY author SAD.md and return JSON.'
    + (round > 1 && prevB2 ? '\n\n=== [DOC: Previous B-2 review JSON — SAD.md] ===\n' + JSON.stringify(prevB2, null, 2) : ''),
  buildBDocs: (content) => [
    ['DOC 1: 01-requirements/SRS.md (APPROVED — heading summary; USE Bash to Read full content if needed)', makeDocSummary(srsContent, { includeFirstLines: true })],
    ['DOC 2: draft 02-architecture/SAD.md (full content — this IS the deliverable under review)', content],
    ['DOC 3: harness/templates/SAD.md §2.1 — Directory Structure Design Principles (heading summary)', makeDocSummary(sadTemplateContent)],
  ],
  checklist:
    '- Every FR maps to ≥1 module?\n- NFRs addressed (latency/security/cost)?\n- No circular dependencies?\n- Data flow diagrams consistent?\n'
    + '- SAB block present in §5 (<!-- SAB:START --> marker exists)?\n- `phase` is a bare int (not quoted string)? e.g. `phase: 2` not `phase: "2"`\n- All NFR `type` values from legal values (performance/security/maintainability/reliability/testability/deployability/scalability/usability)?\n'
    + '- Directory structure follows CRG cohesion principles (SAD.md §2.1)? See embedded DOC 3\n- ≤15 files/dir, no god-module, no flat dump?',
})
if (!sad.ok) return sad
let sadContent = sad.content, sadB2 = sad.b2

// ════════════════════════════════════════════════════════════════════════
// Sub-Task 2/3: ADR.md
// ════════════════════════════════════════════════════════════════════════
phase('Sub-Task 2/3 — ADR.md')
log('abLoop: ADR authoring (extract decisions from APPROVED SAD.md; downstream ADR-Constitution gate)')
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
    + '{"status":"OK","files":["02-architecture/adr/ADR.md"],"confidence":"high|medium|low","citations":["..."],"summary":"..."}\n\n'
    + 'SCOPE RULES:\n- DO NOT write SAD.md or TEST_SPEC.md.\n- DO NOT run phase-transition / quality-gate commands.\n- ONLY author ADR.md.'
    + (round > 1 && prevB2 ? '\n\n=== [DOC: Previous B-2 review JSON — ADR.md] ===\n' + JSON.stringify(prevB2, null, 2) : ''),
  buildBDocs: (content) => [
    ['DOC 1: Previous Sub-Task B-2 review JSON — SAD.md (gaps-only; reason stripped)', JSON.stringify(safePrevB2(sadB2), null, 2)],
    ['DOC 2: 02-architecture/SAD.md (APPROVED — heading summary; USE Bash to Read full content if needed)', makeDocSummary(sadContent, { includeFirstLines: true })],
    ['DOC 3: draft 02-architecture/adr/ADR.md (full content — this IS the deliverable under review)', content],
    ['DOC 4: harness/templates/ADR.md (template format — heading summary)', makeDocSummary(adrTemplateContent)],
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
phase('Sub-Task 3/3 — TEST_SPEC.md')
log('abLoop: TEST_SPEC authoring (per-FR test catalog; v2.9.1 B.3 table-row shape; check-test-spec-consistency)')
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
    + '{"status":"OK","files":["02-architecture/TEST_SPEC.md"],"confidence":"high|medium|low","citations":["..."],"summary":"..."}\n\n'
    + 'SCOPE RULES:\n- DO NOT write SAD/ADR.\n- DO NOT run phase-transition / run-gate commands.\n- DO NOT modify harness/.\n- ONLY author TEST_SPEC.md (check-test-spec-consistency is allowed).'
    + (round > 1 && prevB2 ? '\n\n=== [DOC: Previous B-2 review JSON — TEST_SPEC.md] ===\n' + JSON.stringify(prevB2, null, 2) : ''),
  buildBDocs: (content) => [
    ['DOC 1: Previous Sub-Task B-2 review JSON — ADR.md (gaps-only; reason stripped)', JSON.stringify(safePrevB2(adrB2), null, 2)],
    ['DOC 2: 01-requirements/SRS.md (APPROVED — heading summary; USE Bash to Read full content if needed)', makeDocSummary(srsContent, { includeFirstLines: true })],
    ['DOC 3: 02-architecture/SAD.md (APPROVED — heading summary; USE Bash to Read full content if needed)', makeDocSummary(sadContent, { includeFirstLines: true })],
    ['DOC 4: 02-architecture/adr/ADR.md (APPROVED — heading summary; USE Bash to Read full content if needed)', makeDocSummary(adrContent)],
    ['DOC 5: draft 02-architecture/TEST_SPEC.md (full content — this IS the deliverable under review)', content],
  ],
  checklist:
    '- Upstream ADR review caveats addressed?\n- Every FR has ≥1 named test case (happy_path + validation mandatory)?\n'
    + '- 8-Question Protocol applied per FR?\n- Classification assigned per FR?\n- NFR Pattern Activation table filled?\n'
    + '- Architecture-risk triggers applied (NP-13/NP-15/NP-07 forced where SAD warrants)?\n'
    + '- Concrete Inputs in TRUE form (key="value"), not pytest-id form?\n- Sub-assertions table per FR (rule_id + predicate + applies_to)?\n'
    + '- Each `### FR-XX:` header followed by TABLE ROWS (not prose-only)?\n- Summary table populated with counts per type?\n'
    + '- Self-consistency gate passes? (`check-test-spec-consistency`)?\n- Cross-cutting sections complete (NFR Integration + Deployment Smoke + Backward Compatibility if multi-phase)?\n'
    + '- All upstream deliverables consistent with each other? No contradictory decisions?',
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
log('Agent B (TECH_LEAD) holistic review of all 3 P2 deliverables; max 3 rounds (P-01 advisory, not HR-12)')
let peerB2 = null
let peerReviewAdvisory = null
for (let round = 1; round <= MAX_PEER_ROUNDS; round++) {
  log('  --- Peer round ' + round + '/' + MAX_PEER_ROUNDS + ' ---')
  // v15: budget guard — gracefully exit if running low (Bug #3 mitigation)
  if (typeof budget !== 'undefined' && budget.remaining && budget.remaining() < 100000) {
    log('  Peer Review budget low (' + Math.round((budget.remaining() || 0) / 1000) + 'k remaining) — exiting gracefully')
    if (peerB2 && peerB2.review_status === 'APPROVE') { log('  exiting with prior APPROVE'); break }
    if (peerB2) return { ok: false, peerB2, budget_exhausted: true }
    return { error: 'Budget exhausted before Peer Review completed', budget_exhausted: true }
  }
  // v15: wrap agent() in try/catch — API errors (429/network) must not crash workflow (Bug #2)
  let bResult
  try { bResult = await agent(
    buildBPrompt('TECH_LEAD', 'all 3 P2 deliverables (holistic)', [
      ['DOC 1: 02-architecture/SAD.md (heading summary; USE Bash to Read full content if needed)', makeDocSummary(sadContent, { includeFirstLines: true })],
      ['DOC 2: 02-architecture/adr/ADR.md (heading summary; USE Bash to Read full content if needed)', makeDocSummary(adrContent, { includeFirstLines: true })],
      ['DOC 3: 02-architecture/TEST_SPEC.md (heading summary; USE Bash to Read full content if needed)', makeDocSummary(testSpecContent, { includeFirstLines: true })],
    ],
    '- All FRs covered across all deliverables?\n- No contradictions between deliverables?\n- Each item testable/traceable?\n'
    + '- All gaps from sub-task reviews addressed?\n- Terminology consistent across all documents?\n'
    + '- SAB block layers / NFR targets semantically match SAD §2 module design?\n'
    + '- Every fr_module_traceability entry points to a real SAD §2 module?\n- NFR target fields measurable (not N/A/empty)?'),
    { label: 'peer-b-r' + round, phase: 'Peer Review', agentType: 'general-purpose' },
  ) } catch (e) {
    if (round === MAX_PEER_ROUNDS) {
      peerReviewAdvisory = { status: 'advisory', round, reason: 'Peer B agent failed at max rounds: ' + String(e.message ?? e).slice(0, 200), gaps: [] }
      log('  PEER_REVIEW_ADVISORY: B agent failed at round ' + round + ' — continuing (non-blocking)')
      break
    }
    log('  Peer B agent failed: ' + String(e.message ?? e).slice(0, 80) + ' — retrying'); continue
  }
  try { peerB2 = parseAgentJson(bResult, 'PeerB-r' + round) }
  catch (e) {
    if (round === MAX_PEER_ROUNDS) {
      peerReviewAdvisory = { status: 'advisory', round, reason: 'Peer B parse failed at max rounds: ' + e.message, gaps: [] }
      log('  PEER_REVIEW_ADVISORY: B parse failed at round ' + round + ' — continuing (non-blocking)')
      break
    }
    log('  Peer B parse failed: ' + e.message.slice(0, 80) + ' — retrying'); continue
  }
  log('  Peer B-2: ' + peerB2.review_status + ' | gaps=' + (peerB2.gaps ?? []).length + ' | high=' + (hasHighGap(peerB2.gaps) ? 'yes' : 'no'))

  // X1 self-verify (observability layer; mirrors phase1 §B-2.5)
  peerB2.verify = await runBSelfVerify({ key: 'peer', deliverable: 'P2 deliverables (holistic)', phaseName: 'Peer Review' }, peerB2, round)
  log('  ' + summarizeVerify(peerB2, peerB2.verify))

  if (peerB2.review_status === 'APPROVE' && !hasHighGap(peerB2.gaps)) { log('  APPROVED'); break }
  // P-01: round MAX_PEER_ROUNDS REJECT → emit PEER_REVIEW_ADVISORY (non-blocking), continue to Push.
  if (round === MAX_PEER_ROUNDS) {
    peerReviewAdvisory = { status: 'advisory', round, reason: peerB2.reason ?? 'Peer review did not converge', gaps: peerB2.gaps ?? [] }
    log('  PEER_REVIEW_ADVISORY: round ' + round + ' REJECT with ' + (peerB2.gaps ?? []).length + ' gaps — continuing to Push (non-blocking)')
    break
  }
  // Holistic gaps span multiple files → dispatch a fixer agent
  log('  Peer review found gaps — dispatching fixer for round ' + (round + 1))
  // v15: wrap fixer agent() in try/catch — fixer failures should not crash workflow (Bug #2)
  try {
    await agent(
      'YOU ARE ARCHITECT (holistic fixer). Fix peer-review gaps across P2 deliverables.\n'
      + 'REPO: ' + REPO + '\n\nPeer review B-2 JSON:\n' + JSON.stringify(peerB2, null, 2) + '\n\n'
      + 'Apply surgical Edits to whichever of 02-architecture/SAD.md, 02-architecture/adr/ADR.md, 02-architecture/TEST_SPEC.md are affected. Address all medium/high gaps.\n\n'
      + 'SCOPE RULES:\n- DO NOT run phase-transition/push/run-gate.\n- DO NOT modify harness/.\n- ONLY edit the 3 P2 deliverables. Report what you changed.',
      { label: 'peer-fix-r' + round, phase: 'Peer Review', agentType: 'general-purpose' },
    )
  } catch (e) {
    log('  Peer fixer agent failed: ' + String(e.message ?? e).slice(0, 80) + ' — continuing without fix')
  }
  sadContent = await loadFileViaPython('02-architecture/SAD.md', '# SAD', 'Peer Review')
  adrContent = await loadFileViaPython('02-architecture/adr/ADR.md', '# Architecture Decision Records', 'Peer Review')
  testSpecContent = await loadFileViaPython('02-architecture/TEST_SPEC.md', '#', 'Peer Review')
  log('  Reloaded after fixer: SAD=' + sadContent.length + ' ADR=' + adrContent.length + ' TEST_SPEC=' + testSpecContent.length)
}
if (peerReviewAdvisory) log('  → Peer Review ended with advisory: ' + peerReviewAdvisory.reason.slice(0, 100))

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
// Approval JSONs (SAD.md/ADR.md/TEST_SPEC.md) are now persisted by abLoop exit
// (persistApproval helper) — not here. See bc913a0 / pending P2 parity commit.
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
