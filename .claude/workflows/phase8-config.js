// Phase 8 — Configuration Management (faithful to .methodology/phase8_plan.md v2.12.0)
//
// Structure: FR-loop型 + FINAL phase (NO advance-phase — pipeline ends here).
// Per-FR GATE1-DELTA re-eval, then REVIEW+APPEND the config baseline (the
// framework deterministically generated CONFIG_RECORDS.md + RELEASE_CHECKLIST.md
// via `scripts/phase8_doc_gen.py` during P7→P8 advance-phase per harness_cli.py
// :6016-6030, harness commits 4738542 + 3f1fd73), create .methodology-archive/
// (cp -r .methodology/ — NOT .sessi-work/, per harness commit 3f1fd73), verify
// no Phase 9 refs, p8 push.
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
log('run-env-check (root-cause fix: CLI exit code reflects ready flag)')
// Bug #127 root-cause fix (2026-06-27): `cmd_run_env_check` now returns
// exit 0 when ready=true and 1 when ready=false (previously always 0).
// Workflows check `$?` directly with no LLM orchestrator agent in the loop.
const envReport = await agent(
  'You MUST use the Bash tool. Run exactly:\n'
  + PY + ' ' + REPO + '/harness_cli.py run-env-check --phase 8 --project ' + REPO + '\n'
  + 'echo "ENV_CHECK_RC=$?"\n'
  + 'Return the raw stdout verbatim. Do not paraphrase.',
  { label: 'env-check', phase: 'Env Check', agentType: 'general-purpose' },
)
if (!(typeof envReport === 'string' && /ENV_CHECK_RC=0\b/.test(envReport))) {
  return { error: 'Phase 8 env-check did not PASS', raw: String(envReport ?? '').slice(-500) }
}

// ════════════════════════════════════════════════════════════════════════
// Phase: Load FRs
// ════════════════════════════════════════════════════════════════════════
phase('Load FRs')
log('load-context --phase 8 → fr_ids')
// v15: retry loop — agent() + parseAgentJson both wrapped (Bug #2)
// v2.13.1: hardened against agent hallucination (Bug #122).
let ctx = null
const ctxFile = REPO + '/.sessi-work/phase8_ctx.json'
for (let attempt = 1; attempt <= 3; attempt++) {
  try {
    // Bug #126 fix (2026-06-27): `wc -c` defaults to fixed-width right-padded
    // output (`     789`), so `FILE_OK_$(wc -c ...)` actually produces
    // `FILE_OK_     789` — the strict regex `/FILE_OK_\d+/` never matched.
    // Root-cause fix: control the OUTPUT side via `awk '{print $1}'`.
    const existsRaw = await agent(
      'You MUST use the Bash tool. Run exactly:\n'
      + 'test -s ' + ctxFile + ' && echo "FILE_OK_$(wc -c < ' + ctxFile + ' | awk \'{print $1}\')" || echo "FILE_MISSING"\n'
      + 'Return the raw stdout as your final message.',
      { label: 'ctx-check-' + attempt, phase: 'Load FRs', agentType: 'general-purpose' },
    )
    if (!/FILE_OK_\d+/.test(String(existsRaw ?? ''))) {
      log('  ctx file missing/empty (attempt ' + attempt + ') — regenerating')
      await agent(
        'You MUST use the Bash tool. Run exactly:\n'
        + PY + ' ' + REPO + '/harness_cli.py load-context --phase 8 --project ' + REPO + ' --json > ' + ctxFile + ' && echo "REGEN_OK_$(wc -c < ' + ctxFile + ' | awk \'{print $1}\')"\n'
        + 'Return the raw stdout as your final message.',
        { label: 'ctx-regen-' + attempt, phase: 'Load FRs', agentType: 'general-purpose' },
      )
      continue
    }
  } catch (e) { log('  ctx-check agent failed: ' + String(e.message ?? e).slice(0, 80)); continue }

  let ctxResult = ''
  try {
    ctxResult = await agent(
      'You MUST use the Bash tool. Run exactly:\n'
      + 'cat ' + ctxFile + '\n'
      + 'Return the EXACT stdout as your final message. No commentary, no markdown fences.',
      { label: 'load-ctx-a' + attempt, phase: 'Load FRs', agentType: 'general-purpose' },
    )
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
// Phase: Config Docs (REVIEW + APPEND CONFIG_RECORDS + RELEASE_CHECKLIST)
// ════════════════════════════════════════════════════════════════════════
// Per phase8_plan.md + harness commit 4738542: CONFIG_RECORDS.md and
// RELEASE_CHECKLIST.md are DETERMINISTICALLY generated by scripts/phase8_doc_gen.py
// during P7→P8 advance-phase (harness_cli.py:6016-6030). P8 work is therefore
// REVIEW + APPEND human-only context, NOT regenerate from scratch. Do NOT
// overwrite the deterministic baseline (it breaks byte-equality for downstream
// consumers); use Edit/append to add the human-only sections.
phase('Config Docs')
log('Review deterministic baseline (phase8_doc_gen.py output) + append human-only context')
const docsReport = await agent(
  'YOU ARE THE P8 CONFIG REVIEWER. The framework has ALREADY deterministically generated\n'
  + 'the config baseline during P7→P8 advance-phase. Your job: REVIEW + APPEND.\n'
  + 'REPO: ' + REPO + '\nPYTHON: ' + PY + '\n\n'
  + 'Steps (Bash for read-only checks; Edit for human-only append):\n'
  + '0. VERIFY BASELINE EXISTS: `test -f ' + REPO + '/08-config/CONFIG_RECORDS.md && test -f ' + REPO + '/08-config/RELEASE_CHECKLIST.md && echo BASELINE_OK || echo BASELINE_MISSING`. If MISSING, regenerate via `' + PY + ' ' + REPO + '/harness/scripts/phase8_doc_gen.py --project ' + REPO + '` (fallback per harness advance-phase behavior; should not normally fire).\n'
  + '1. CONFIG_RECORDS APPEND: Edit ' + REPO + '/08-config/CONFIG_RECORDS.md and APPEND a `## Human Context (P8 append)` section with: ownership per config item, secret rotation cadence, access audit log reference. KEEP all existing framework-generated sections (env var inventory, source-of-truth module refs, feature flags) intact. Do NOT overwrite the framework version.\n'
  + '2. RELEASE_CHECKLIST APPEND: Edit ' + REPO + '/08-config/RELEASE_CHECKLIST.md and APPEND a `## Human Context (P8 append)` section with: deployment runbook URL, rollback owner + on-call, post-release monitoring dashboard, customer comms template. KEEP the framework-generated Gate 4 PASS proof, quality_manifest composite_score, FR coverage, git tag/hash intact.\n'
  + '3. SANITY: `grep -c "^## " ' + REPO + '/08-config/CONFIG_RECORDS.md && grep -c "^## " ' + REPO + '/08-config/RELEASE_CHECKLIST.md` — confirm both files still have the framework sections (count >= baseline).\n\n'
  + 'Report: "CONFIG-DOCS: PASS — baseline verified + human context appended" or "CONFIG-DOCS: FAIL — <reason>".\n\n'
  + 'SCOPE RULES:\n- DO NOT regenerate CONFIG_RECORDS.md / RELEASE_CHECKLIST.md from scratch.\n- DO NOT use Write tool to overwrite either file — Edit/append only.\n- DO NOT run push-milestone / create archive (next phases do that).\n- DO NOT modify harness/.\n- DO NOT re-implement FRs.\n- ONLY verify baseline + append human context.',
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
  + '1. P8-ARCHIVE: `mkdir -p ' + REPO + '/.methodology-archive && cp -r ' + REPO + '/.methodology/ ' + REPO + '/.methodology-archive/`. (push-milestone _validate_p8_completion + CI p8-archive-check both verify this dir. Source MUST be `.methodology/` — NOT `.sessi-work/` per harness commit 3f1fd73 which fixed the wrong-source silent bug.)\n'
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
  + '0. GUARD: `git -C ' + REPO + ' log --oneline --grep="p8" -1`. If exists, report "P8-PUSH: PASS (already pushed)" and stop.\n'
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
