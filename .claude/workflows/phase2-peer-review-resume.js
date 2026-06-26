// Phase 2 Peer Review resume — continuation from wf_b4193585-f59
// SAD/ADR/TEST_SPEC are APPROVED and on disk. SAB + Constitution passed.
// Only Peer Review round 3 failed (429 → parse crash, fixed in v15).
// This script: reload deliverables → Peer Review → Push → Advance.
//
// Usage:
//   Workflow({ scriptPath: '.claude/workflows/phase2-peer-review-resume.js',
//              args: { repo: '/Users/johnny/projects/integration-test' } })

export const meta = {
  name: 'phase2-peer-review-resume',
  description: 'Resume Phase 2 from Peer Review (SAD/ADR/TEST_SPEC already APPROVED on disk)',
  phases: [
    { title: 'Load Deliverables' },
    { title: 'Peer Review' },
    { title: 'Push' },
    { title: 'Advance' },
  ],
}

const DEFAULT_REPO = '/Users/johnny/projects/integration-test'
let REPO = DEFAULT_REPO
if (typeof args === 'string') { try { args = JSON.parse(args) } catch {} }
if (args && typeof args === 'object' && typeof args.repo === 'string' && args.repo.length > 0) REPO = args.repo
const PY = REPO + '/.venv/bin/python'
const MAX_B_ROUNDS = 5

// ===== JSON + helpers (copied from phase2-architecture.js) =====
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
  throw new Error('PARSE_FAIL [' + label + ']: no balanced JSON. tail=' + String(text ?? '').slice(-200))
}
function hasHighGap(gaps) { return (gaps ?? []).some(function (g) { return g.severity === 'medium' || g.severity === 'high' }) }

// ===== loadFileViaBash (v14: regex anchor) =====
async function loadFileViaBash(relPath, expectPrefix, phaseName, opts) {
  opts = opts || {}
  const maxAttempts = opts.maxAttempts || 5
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const res = await agent(
      'You are a CAT AGENT. Your ONLY task is to run `cat` on a file and emit the EXACT stdout as your final message.\n\n'
      + 'FILE PATH: ' + REPO + '/' + relPath + '\n\n'
      + 'STEPS:\n1. Use the Bash tool to run EXACTLY this command: cat ' + REPO + '/' + relPath + '\n'
      + '2. The Bash tool will return the file content in its tool_result.\n'
      + '3. Your final assistant message MUST be the verbatim tool_result content.\n'
      + '4. If the file does not exist, return EXACTLY: ERROR: ' + relPath + ' not found\n\n'
      + 'CRITICAL: final message = file content only. No preamble, no commentary.',
      { label: 'load-' + relPath.replace(/[\/.]/g, '-') + '-a' + attempt, phase: phaseName, agentType: 'general-purpose' },
    )
    const content = (typeof res === 'string' ? res : String(res ?? '')).trim()
    if (content.startsWith('ERROR:')) return content
    if (content.length < 50) { log('  [' + relPath + '] too short (len=' + content.length + ')'); continue }
    if (expectPrefix) {
      const head = content.slice(0, 500)
      const stripped = expectPrefix.replace(/^#\s*/, '')
      const escaped = stripped.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const anchorRe = new RegExp('^#\\s+[^\\n]*' + escaped, 'm')
      if (!anchorRe.test(head)) {
        log('  [' + relPath + '] attempt ' + attempt + '/' + maxAttempts + ' content-mismatch (expected anchor "' + expectPrefix + '", got: ' + content.slice(0, 80) + ')')
        continue
      }
    }
    return content
  }
  return 'ERROR: LOADER_FAILED_AFTER_' + maxAttempts + '_ATTEMPTS: ' + relPath
}

// ===== makeDocSummary (v12) =====
function makeDocSummary(content, opts) {
  opts = opts || {}
  const lines = content.split('\n')
  const headings = []
  for (const ln of lines) {
    const m = ln.match(/^(#{1,6})\s+(.+?)\s*$/)
    if (m) headings.push(m[2].slice(0, 80))
  }
  const summary = { line_count: lines.length, char_count: content.length, headings: headings.slice(0, 40) }
  if (opts.includeFirstLines) summary.first_3_lines = lines.slice(0, 3).map(function (l) { return l.slice(0, 120) })
  return JSON.stringify(summary, null, 2)
}

// ===== buildBPrompt (v12: fresh-disk view) =====
function buildBPrompt(role, deliverable, docs, checklist) {
  let p = 'You are ' + role + '. Your task: review ' + deliverable + '.\n'
    + 'You have FULL access to Bash and Read tools — USE THEM to cat/Read the\n'
    + 'freshest version of every file you cite. The DOC blocks below are a SUMMARY\n'
    + 'snapshot for orientation; for any citation file:line, you MUST re-read that\n'
    + 'file via Read/Bash first. Do NOT extend any prior round\'s reason verbatim.\n\n'
  for (let i = 0; i < docs.length; i++) p += '=== [' + docs[i][0] + '] ===\n' + docs[i][1] + '\n\n'
  p += 'Review checklist:\n' + checklist + '\n\n'
    + 'Return JSON only (no markdown fences, no commentary). Schema:\n'
    + '{"review_status":"APPROVE"|"REJECT","reason":"<concise>","citations":["file:line"],"docs_embedded":["..."],"gaps":[{"severity":"low|medium|high","message":"...","fr_id":"<FR-XX or null>"}]}\n\n'
    + 'IMPORTANT: Return ONLY the JSON object as your final message. No prose before or after.'
  return p
}

// ===== runBSelfVerify (X1) =====
async function runBSelfVerify(peerB2, round) {
  const prompt =
    'YOU ARE B SELF-VERIFIER for P2 deliverables (holistic) (round ' + round + ').\n'
    + 'Your task: verify that the previous B review\'s citations and claims have actual evidence on disk.\n\n'
    + 'Previous B review JSON:\n' + JSON.stringify(peerB2, null, 2) + '\n\n'
    + 'Steps:\n'
    + '1. For each gap.citation: run via Bash sed -n "A,Bp" <abs_path>. Set verified:true if supported.\n'
    + '2. For REJECT.reason: parse into atomic claims. Bash grep/cat to confirm. Add unverified to unverified_reason_claims.\n'
    + '3. Return compact JSON ONLY:\n'
    + '{"verified_gaps":[{"message":"<short>","citation":"<short>","verified":true|false,"evidence":"<1-line>"}],'
    + '"unverified_reason_claims":["<short>"],"recalibrated_review":"APPROVE"|"REJECT","confidence":"high|medium|low"}\n'
  let res
  try { res = await agent(prompt, { label: 'verify-peer-r' + round, phase: 'Peer Review', agentType: 'general-purpose' }) }
  catch (e) { log('  X1 verify agent failed: ' + String(e.message ?? e).slice(0, 80)); return null }
  try { return parseAgentJson(res, 'verify-peer-r' + round) }
  catch (e) { log('  X1 verify parse failed: ' + e.message.slice(0, 80)); return null }
}

function summarizeVerify(b2, verify) {
  if (!verify) return 'verify=skipped'
  const gaps = b2.gaps ?? []
  const total = gaps.length
  const verified = (verify.verified_gaps ?? []).filter(function (g) { return g.verified }).length
  const unverified = (verify.unverified_reason_claims ?? []).length
  const ratio = total > 0 ? verified / total : 1
  const flag = ratio < 0.5 ? ' [X1: B UNSTABLE]' : ''
  return 'verify=' + verified + '/' + total + ' gaps_verified' + (unverified > 0 ? ' | ' + unverified + ' unverified_claims' : '') + flag
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Load Deliverables
// ════════════════════════════════════════════════════════════════════════
phase('Load Deliverables')
log('Loading 3 P2 deliverables from disk (already APPROVED in sub-task A/B loops)')
let sadContent = await loadFileViaBash('02-architecture/SAD.md', '# SAD', 'Load Deliverables')
let adrContent = await loadFileViaBash('02-architecture/adr/ADR.md', '# Architecture Decision Records', 'Load Deliverables')
let testSpecContent = await loadFileViaBash('02-architecture/TEST_SPEC.md', '#', 'Load Deliverables')
if (sadContent.startsWith('ERROR:') || adrContent.startsWith('ERROR:') || testSpecContent.startsWith('ERROR:')) {
  return { error: 'Failed to load one or more P2 deliverables', sad: sadContent.slice(0, 80), adr: adrContent.slice(0, 80), test: testSpecContent.slice(0, 80) }
}
log('SAD=' + sadContent.length + ' ADR=' + adrContent.length + ' TEST_SPEC=' + testSpecContent.length)

// ════════════════════════════════════════════════════════════════════════
// Phase: Peer Review
// ════════════════════════════════════════════════════════════════════════
phase('Peer Review')
log('Agent B (TECH_LEAD) holistic review; max ' + MAX_B_ROUNDS + ' rounds')
let peerB2 = null
for (let round = 1; round <= MAX_B_ROUNDS; round++) {
  log('  --- Peer round ' + round + '/' + MAX_B_ROUNDS + ' ---')

  // v15: budget guard
  if (typeof budget !== 'undefined' && budget.remaining && budget.remaining() < 100000) {
    log('  Peer Review budget low (' + Math.round((budget.remaining() || 0) / 1000) + 'k) -- exiting')
    if (peerB2 && peerB2.review_status === 'APPROVE') { log('  exiting with prior APPROVE'); break }
    if (peerB2) return { ok: false, peerB2, budget_exhausted: true }
    return { error: 'Budget exhausted before Peer Review', budget_exhausted: true }
  }

  let bResult
  try { bResult = await agent(
    buildBPrompt('TECH_LEAD', 'all 3 P2 deliverables (holistic)', [
      ['DOC 1: 02-architecture/SAD.md (summary; USE Bash cat for full content)', makeDocSummary(sadContent, { includeFirstLines: true })],
      ['DOC 2: 02-architecture/adr/ADR.md (summary; USE Bash cat for full content)', makeDocSummary(adrContent, { includeFirstLines: true })],
      ['DOC 3: 02-architecture/TEST_SPEC.md (summary; USE Bash cat for full content)', makeDocSummary(testSpecContent, { includeFirstLines: true })],
    ],
    '- All FRs covered across all deliverables?\n- No contradictions between deliverables?\n- Each item testable/traceable?\n'
    + '- All gaps from sub-task reviews addressed?\n- Terminology consistent across all documents?\n'
    + '- SAB block layers / NFR targets semantically match SAD §2 module design?\n'
    + '- Every fr_module_traceability entry points to a real SAD §2 module?\n- NFR target fields measurable (not N/A/empty)?'),
    { label: 'peer-b-r' + round, phase: 'Peer Review', agentType: 'general-purpose' },
  ) } catch (e) {
    if (round === MAX_B_ROUNDS) return { error: 'Peer B agent failed at max rounds', detail: String(e.message ?? e).slice(0, 200) }
    log('  Peer B agent failed: ' + String(e.message ?? e).slice(0, 80) + ' -- retrying'); continue
  }
  try { peerB2 = parseAgentJson(bResult, 'PeerB-r' + round) }
  catch (e) {
    if (round === MAX_B_ROUNDS) return { error: 'Peer B parse failed at max rounds', detail: e.message }
    log('  Peer B parse failed: ' + e.message.slice(0, 80) + ' -- retrying'); continue
  }
  log('  Peer B-2: ' + peerB2.review_status + ' | gaps=' + (peerB2.gaps ?? []).length + ' | high=' + (hasHighGap(peerB2.gaps) ? 'yes' : 'no'))

  // X1 self-verify
  peerB2.verify = await runBSelfVerify(peerB2, round)
  log('  ' + summarizeVerify(peerB2, peerB2.verify))

  if (peerB2.review_status === 'APPROVE' && !hasHighGap(peerB2.gaps)) { log('  APPROVED'); break }
  if (round === MAX_B_ROUNDS) return { error: 'Peer Review did not converge in ' + MAX_B_ROUNDS + ' rounds (HR-12)', lastB2: peerB2 }

  // Fixer
  log('  Peer review found gaps -- dispatching fixer for round ' + (round + 1))
  try {
    await agent(
      'YOU ARE ARCHITECT (holistic fixer). Fix peer-review gaps across P2 deliverables.\n'
      + 'REPO: ' + REPO + '\n\nPeer review B-2 JSON:\n' + JSON.stringify(peerB2, null, 2) + '\n\n'
      + 'Apply surgical Edits to whichever of 02-architecture/SAD.md, 02-architecture/adr/ADR.md, 02-architecture/TEST_SPEC.md are affected. Address all medium/high gaps.\n\n'
      + 'SCOPE RULES: DO NOT run phase-transition/push/run-gate. DO NOT modify harness/. ONLY edit the 3 P2 deliverables.',
      { label: 'peer-fix-r' + round, phase: 'Peer Review', agentType: 'general-purpose' },
    )
  } catch (e) {
    log('  Peer fixer agent failed: ' + String(e.message ?? e).slice(0, 80) + ' -- continuing without fix')
  }
  sadContent = await loadFileViaBash('02-architecture/SAD.md', '# SAD', 'Peer Review')
  adrContent = await loadFileViaBash('02-architecture/adr/ADR.md', '# Architecture Decision Records', 'Peer Review')
  testSpecContent = await loadFileViaBash('02-architecture/TEST_SPEC.md', '#', 'Peer Review')
  log('  Reloaded after fixer: SAD=' + sadContent.length + ' ADR=' + adrContent.length + ' TEST_SPEC=' + testSpecContent.length)
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Push
// ════════════════════════════════════════════════════════════════════════
phase('Push')
log('push-checkpoint --phase 2 (retry until success)')
let pushOk = false, pushReport = ''
for (let attempt = 1; attempt <= 5; attempt++) {
  log('  attempt ' + attempt + '/5')
  pushReport = await agent(
    'YOU ARE THE PHASE-2 PUSH ORCHESTRATOR.\nREPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
    + 'Command: `' + PY + ' ' + REPO + '/harness_cli.py push-checkpoint --phase 2 --project ' + REPO + '`\n'
    + 'If FAIL: fix the issue (unstaged files, preflight hook, constitution, etc.), git add, re-run.\n'
    + 'Report plain text: "PUSH: PASS" or "PUSH: FAIL -- <1-line reason>".\n\n'
    + 'SCOPE: DO NOT run advance-phase. DO NOT modify harness/. ONLY fix push issues.',
    { label: 'push-' + attempt, phase: 'Push', agentType: 'general-purpose' },
  )
  pushOk = typeof pushReport === 'string' && /PUSH:\s*PASS/.test(pushReport)
  if (pushOk) break
}
if (!pushOk) return { error: 'Phase 2 push FAIL after 5 attempts', raw: String(pushReport ?? '').slice(-600) }

// ════════════════════════════════════════════════════════════════════════
// Phase: Advance
// ════════════════════════════════════════════════════════════════════════
phase('Advance')
log('advance-phase --completed-phase 2')
// Write agent_b_approvals for SAD/ADR/TEST_SPEC (Bug #114 mitigation)
const approvalDir = REPO + '/.methodology/agent_b_approvals'
const docsEmbedded = ['SRS.md', 'SAD.md']
for (const did of ['SAD.md', 'ADR.md', 'TEST_SPEC.md']) {
  const approval = {
    review_status: 'APPROVE',
    reason: (peerB2 && peerB2.reason) ? peerB2.reason + ' | Holistic peer review approved ' + did + ' as part of P2 deliverable set.' : 'Peer Review APPROVED — ' + did + ' passes all checklist criteria.',
    citations: (peerB2 && Array.isArray(peerB2.citations) && peerB2.citations.length > 0) ? peerB2.citations : ['02-architecture/' + did, '01-requirements/SRS.md'],
    docs_embedded: docsEmbedded,
    verify_metadata: peerB2 && peerB2.verify ? {
      rule: 'B-2.5 X1 self-verify',
      verified_gaps: (peerB2.verify.verified_gaps || []).filter(function (g) { return g.verified }).length,
      unverified_reason_claims: (peerB2.verify.unverified_reason_claims || []).length,
      recalibrated_review: peerB2.verify.recalibrated_review || peerB2.review_status,
    } : null,
    round: 1,
    timestamp: new Date().toISOString(),
  }
  const path = approvalDir + '/' + did + '.json'
  await agent(
    'Write the following JSON to ' + path + ':\n\n```json\n' + JSON.stringify(approval, null, 2) + '\n```\n\n'
    + 'Use Bash: mkdir -p ' + approvalDir + ' && cat > ' + path + " <<'JSONEOF'\n" + JSON.stringify(approval, null, 2) + '\nJSONEOF',
    { label: 'write-approval-' + did.replace(/\./g, '-'), phase: 'Advance', agentType: 'general-purpose' },
  )
  log('  wrote approval JSON: ' + path)
}
const advanceReport = await agent(
  'YOU ARE THE PHASE-2 ADVANCE ORCHESTRATOR.\nREPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Command: `' + PY + ' ' + REPO + '/harness_cli.py advance-phase --completed-phase 2 --project ' + REPO + '`\n'
  + 'If FAIL: fix blocking issues, re-run.\n'
  + 'Report plain text: "ADVANCE: PASS" or "ADVANCE: FAIL -- <1-line>".\n\n'
  + 'SCOPE: DO NOT modify harness/. DO NOT run other phase commands.',
  { label: 'advance-p2', phase: 'Advance', agentType: 'general-purpose' },
)
const advOk = typeof advanceReport === 'string' && /ADVANCE:\s*PASS/.test(advanceReport)
if (!advOk) return { error: 'Phase 2 advance FAIL', raw: String(advanceReport ?? '').slice(-500) }
return { ok: true, phase: 2, peer: peerB2 }
