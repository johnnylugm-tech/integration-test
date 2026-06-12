// Workflow: harness-e2e — full Phase 1→8 pipeline validation of harness-methodology.
//
// PURPOSE: run the complete 8-phase development pipeline on the taskq SPEC
// (SPEC.md, repo root) against a pinned harness-methodology submodule, to
// validate framework health end-to-end. Any framework bug stops the run
// (FRAMEWORK_BUG protocol below); fixes land in the submodule and are pushed
// upstream after Phase 8.
//
// BASELINE CONTRACT: the git baseline (tag `baseline`) contains exactly two
// files — SPEC.md + harness-e2e.js. Every validation round starts by
// reverting to it:
//   git fetch origin && git checkout main && git reset --hard baseline
//   git submodule deinit --all -f ; git clean -ffdx
//   git push --force origin main
//
// Usage:
//   Workflow({ scriptPath: 'harness-e2e.js',
//              args: { repo: '/Users/johnny/projects/integration-test',
//                      startPhase: 0,       // resume point (0 = bootstrap)
//                      model: 'claude-haiku-4-5-20251001' } })
//
// MODEL POLICY (boss decision 2026-06-12): ALL e2e executions — phase
// orchestrators AND their nested dispatch/hunter children — run on Haiku 4.5
// (default of args.model). Children inherit it via ANTHROPIC_MODEL env.
//
// Equivalent manual driving (no Workflow runtime): for each phase, spawn the
// orchestrator prompt below via headless `claude -p` with flags
//   --output-format json --max-turns 300 --permission-mode bypassPermissions
//   --no-session-persistence
// then run the same postcondition checks.

export const meta = {
  name: 'harness-e2e',
  description: 'Full P1→P8 harness-methodology pipeline validation on the taskq SPEC',
  phases: [
    { title: 'Bootstrap' },
    { title: 'Phase 1 — Requirements' },
    { title: 'Phase 2 — Architecture' },
    { title: 'Phase 3 — Implementation' },
    { title: 'Phase 4 — Testing' },
    { title: 'Phase 5 — Verification' },
    { title: 'Phase 6 — Quality' },
    { title: 'Phase 7 — Risk' },
    { title: 'Phase 8 — Configuration' },
    { title: 'Wrap-up' },
  ],
}

const REPO = (args && args.repo) || process.cwd()
const START = (args && args.startPhase) || 0
const MODEL = (args && args.model) || 'claude-haiku-4-5-20251001'
process.env.ANTHROPIC_MODEL = MODEL // nested dispatch/hunter children inherit
const HARNESS_REMOTE = 'https://github.com/johnnylugm-tech/harness-methodology'
const PY = '/opt/homebrew/bin/python3.11'
const VENV_PY = `${REPO}/.venv/bin/python`

const fs = await import('node:fs')
const { execSync } = await import('node:child_process')
const sh = (cmd, opts) =>
  execSync(cmd, { cwd: REPO, encoding: 'utf-8', stdio: 'pipe', ...opts }).trim()

// === PROJECT_BRIEF.md — seed input for Phase 1 (derived from SPEC.md §1-§5).
// canonical_spec marker → P1 Agent A runs in INGESTION mode (100% transcription).
const PROJECT_BRIEF = `# PROJECT_BRIEF — taskq

> Authored by orchestrator (bootstrap) from \`SPEC.md\`. Seed input for Phase 1;
> Agent B (BUSINESS_ANALYST) embeds it as DOC 1 in every B-1 review prompt.

canonical_spec: SPEC.md

## 1. Project name & purpose

- **Project name**: \`taskq\` (project root: ${REPO})
- **Purpose**: 本地任務佇列 CLI — 提交 shell 命令為任務,受控執行(timeout/重試/斷路器/快取),狀態可查詢。
- **Language**: Python 3.11, runtime 零外部依賴(stdlib only)
- **Experiment role**: harness-methodology v2.9 整合驗證標的 — 框架在本專案完整行使 P1-P8;框架本身的修改 out of scope(框架 bug 由 e2e 監督者處理,不在本專案內 workaround)。

## 2. Stakeholders

- **Primary user**: 需要批次執行/重試本地命令的開發者(Johnny)
- **Methodology reviewers**: harness-methodology 維護者 — 以本專案的 P1-P8 工件評估框架健康度
- **Project owner**: Johnny (repo: https://github.com/johnnylugm-tech/integration-test)

## 3. Business goals

- 任務提交驗證(注入字元拒絕,FR-01)、受控 subprocess 執行(timeout,FR-02)
- 失敗自動重試 + 全域斷路器(FR-03)、結果 TTL 快取(FR-04)、完整 CLI(FR-05)
- 可靠性:原子寫存儲、執行緒安全並發(NFR-03);安全:禁 shell=True、secret redaction(NFR-02/04)
- 部署:全參數 env-var 化 + .env.example 宣告(NFR-06)

## 4. Key constraints

- **5 functional requirements are pre-defined and immutable** (FR-01..FR-05, SPEC.md §3). Do not invent new FRs.
- **Tech stack locked**: Python 3.11 stdlib only(runtime)。No external runtime deps.
- **Configuration values fixed** (SPEC.md §5.1): 8 個 TASKQ_* 環境變數與預設值。
- **Single source of truth**: SPEC.md is canonical. No overlay document may amend it.

## 5. Out of scope

- Daemon/服務化、遠端執行、非 JSON 持久化後端
- 修改 harness-methodology 框架(submodule 唯讀,HR-17)
`

// === Orchestrator prompt (one per phase) ===
const orchestratorPrompt = (n) => `You are the ORCHESTRATOR for Phase ${n} of the harness-methodology pipeline.

PROJECT ROOT: ${REPO}
Everything you do MUST stay inside this directory. Work from it as cwd.

CONTRACT (SKILL.md §0 — read ${REPO}/harness/SKILL.md §0-§2 first):
1. The single authority for tasks is ${REPO}/.methodology/phase${n}_plan.md — execute it top-to-bottom. Do not re-derive work from SKILL.md mid-phase.
2. Run \`${VENV_PY} harness_cli.py load-context --phase ${n} --project . --json > .sessi-work/phase${n}_ctx.json\` before starting (create .sessi-work/ if missing).
3. ALL harness CLI invocations use ${VENV_PY} harness_cli.py <cmd> (the venv interpreter — system python3 is 3.9 and unsupported).
4. Agent A/B work is dispatched as SEPARATE sub-agent sessions via \`${VENV_PY} harness_cli.py dispatch --role <developer|reviewer> ... --project .\` — NEVER role-play A or B yourself (HR-01). Stateless reviewers: embed full document content in prompts, never file paths.
5. Gates: \`run-gate\` → evaluate inline per the printed prompt → \`finalize-gate\`. On FAIL: fix the failing dimensions in taskq code/tests, re-run (max 3 rounds). NEVER advance past a failing gate (HR-08).
6. Phase complete: run the phase-exit checklist in the plan, then \`advance-phase\` exactly as the plan instructs, push checkpoints/milestones as the plan instructs.

FRAMEWORK BUG PROTOCOL (validation run — this overrides everything):
If a harness CLI command crashes (traceback inside harness/*), a gate/preflight verdict is provably wrong, or any framework behavior contradicts its own docs/plan:
- STOP immediately. Do NOT work around it. Do NOT modify anything under harness/ (HR-17).
- Print on its own line: ===FRAMEWORK_BUG===
  then a JSON object: {"phase": ${n}, "step": "<plan step id>", "symptom": "<1-2 sentences>", "repro_cmd": "<exact command>", "traceback_head": "<first 5 lines>", "suspected_file": "harness/<path>"}
- Then exit. The supervisor fixes the framework and resumes this phase.

MODEL POLICY (boss decision): every sub-agent you spawn (harness dispatch, claude -p hunters/verifiers) must run with env ANTHROPIC_MODEL=${MODEL} — it is already exported in your environment; do not unset or override it.

AUTONOMY: you run headless — no human can answer you in this session. The project owner has ALREADY confirmed execution of the full plan (SKILL.md §0.1 step 3 is satisfied for every phase). All plan-internal work is pre-authorized: gap fixes from Agent B reviews, constitution checks, commits, checkpoint/milestone pushes, advance-phase. NEVER pause to ask for authorization and NEVER end your session with a question — ending without ===PHASE_DONE=== or ===FRAMEWORK_BUG=== is a failure. The ONLY reason to stop early is the FRAMEWORK BUG PROTOCOL above.

PROJECT-SIDE issues (taskq code/test bugs, failing gates due to real quality gaps) are YOURS to fix normally — they are not framework bugs.
${n === 4 ? `
PHASE 4 EXTRA — Adversarial Bug Hunt (before Gate 3, per plan Step 4b):
- \`${VENV_PY} harness_cli.py bug-hunt-targets --project .\`
- Execute the hunt per ${REPO}/harness/harness/ssi/prompts/hunt_bugs.md (4 phases: scout → lens hunters → adversarial verify → synthesize). Spawn hunters/verifiers as headless sub-agents (claude -p) or dispatch; do not hunt single-handedly.
- Write .methodology/bug_hunt_report.json (schema: harness/schemas/bug_hunt_report.schema.json) + human markdown under 03-development/.audit/.
- Every confirmed critical/high finding: resolution.status = resolved (RED repro test → fix → GREEN, with fix_commit/repro_test) or refuted (with refute_evidence). Only then run Gate 3.
` : ''}
WHEN THE PHASE IS FULLY DONE, print on its own line: ===PHASE_DONE===
then JSON: {"phase": ${n}, "gates": {...}, "artifacts": [...], "notes": "<anything the supervisor should know>"}.
Be honest: if a step was skipped or a gate not passed, that is NOT done — keep working or report the bug.`

// === Postconditions (objective, machine-checkable) ===
const exists = (rel) => fs.existsSync(`${REPO}/${rel}`)
const readJson = (rel) => JSON.parse(fs.readFileSync(`${REPO}/${rel}`, 'utf-8'))
const gateScore = (rel) => { const g = readJson(rel); return g.overall_score ?? g.composite_score ?? 0 }

const POSTCONDITIONS = {
  1: () => {
    if (!exists('01-requirements/SRS.md') && !exists('SRS.md')) throw new Error('P1: SRS.md missing')
    if (readJson('.methodology/state.json').current_phase < 2) throw new Error('P1: state not advanced')
  },
  2: () => {
    for (const f of ['SAD.md', 'ADR.md', 'TEST_SPEC.md']) {
      if (!exists(`02-architecture/${f}`) && !exists(f) && !exists(`02-architecture/adr/${f}`)) throw new Error(`P2: ${f} missing`)
    }
    if (!exists('.methodology/quality_manifest.json')) throw new Error('P2: quality_manifest missing')
    if (readJson('.methodology/state.json').current_phase < 3) throw new Error('P2: state not advanced')
  },
  3: () => {
    if (gateScore('.methodology/gate2_result.json') < 75) throw new Error('P3: Gate 2 < 75')
    if (readJson('.methodology/state.json').current_phase < 4) throw new Error('P3: state not advanced')
  },
  4: () => {
    if (!exists('.methodology/bug_hunt_report.json')) throw new Error('P4: bug_hunt_report missing')
    const open = readJson('.methodology/bug_hunt_report.json').findings.filter(
      (f) => f.confirmed && ['critical', 'high'].includes(f.severity) && f.resolution.status === 'open')
    if (open.length) throw new Error(`P4: ${open.length} open critical/high finding(s)`)
    if (gateScore('.methodology/gate3_result.json') < 80) throw new Error('P4: Gate 3 < 80')
    if (readJson('.methodology/state.json').current_phase < 5) throw new Error('P4: state not advanced')
  },
  5: () => {
    if (!exists('05-verification/BASELINE.md') && !exists('BASELINE.md')) throw new Error('P5: BASELINE.md missing')
    if (readJson('.methodology/state.json').current_phase < 6) throw new Error('P5: state not advanced')
  },
  6: () => {
    if (gateScore('.methodology/gate4_result.json') < 85) throw new Error('P6: Gate 4 < 85')
    if (!exists('06-quality/QUALITY_REPORT.md') && !exists('QUALITY_REPORT.md')) throw new Error('P6: QUALITY_REPORT missing')
    if (readJson('.methodology/state.json').current_phase < 7) throw new Error('P6: state not advanced')
  },
  7: () => {
    if (!exists('07-risk/RISK_REGISTER.md') && !exists('RISK_REGISTER.md')) throw new Error('P7: RISK_REGISTER missing')
    if (readJson('.methodology/state.json').current_phase < 8) throw new Error('P7: state not advanced')
  },
  8: () => {
    if (!exists('08-config/CONFIG_RECORDS.md') && !exists('CONFIG_RECORDS.md')) throw new Error('P8: CONFIG_RECORDS missing')
    if (!exists('FINAL_SIGN_OFF.md')) throw new Error('P8: FINAL_SIGN_OFF missing')
    const st = readJson('.methodology/state.json')
    if (!(st.pipeline_complete === true || st.state === 'COMPLETE')) throw new Error('P8: pipeline not COMPLETE')
  },
}

// === Phase 0: Bootstrap (deterministic, no agents) ===
if (START <= 0) {
  phase('Bootstrap')

  // Guard: must start from the 2-file baseline.
  if (sh('git status --porcelain') !== '') throw new Error('bootstrap: working tree not clean — revert to baseline first')
  const files = sh('git ls-files').split('\n').sort()
  if (JSON.stringify(files) !== JSON.stringify(['SPEC.md', 'harness-e2e.js']))
    throw new Error(`bootstrap: baseline must contain exactly SPEC.md + harness-e2e.js, got: ${files.join(', ')}`)

  log('Adding harness submodule…')
  sh(`git submodule add ${HARNESS_REMOTE} harness`)

  log('Writing PROJECT_BRIEF.md…')
  fs.writeFileSync(`${REPO}/PROJECT_BRIEF.md`, PROJECT_BRIEF)

  log('Creating venv + installing harness toolchain (this takes a few minutes)…')
  sh(`${PY} -m venv .venv`)
  sh(`${REPO}/.venv/bin/pip install -q --upgrade pip`, { timeout: 300000 })
  sh(`${REPO}/.venv/bin/pip install -q -r harness/requirements.txt`, { timeout: 900000 })

  log('init-project + plan-all…')
  sh(`${VENV_PY} harness/harness_cli.py init-project --phase 1 --project . --language python`)
  sh(`${VENV_PY} harness_cli.py plan-all --project .`)

  sh('git add -A')
  sh('git commit -m "chore(bootstrap): harness submodule + venv wiring + 8 phase plans"')
  sh('git push origin main')
  log('Bootstrap complete.')
}

// === Phases 1..8 ===
const summary = []
for (let n = 1; n <= 8; n++) {
  if (n < START) continue
  phase(meta.phases[n].title)

  const out = await agent(orchestratorPrompt(n), {
    label: `phase-${n}-orchestrator`,
    phase: meta.phases[n].title,
    agentType: 'general-purpose',
    model: MODEL,
  })

  if (String(out).includes('===FRAMEWORK_BUG===')) {
    log(`FRAMEWORK BUG reported in Phase ${n} — stopping for supervisor fix. Resume with args.startPhase=${n}.`)
    return { stoppedAt: n, frameworkBug: true, report: String(out) }
  }
  if (!String(out).includes('===PHASE_DONE===')) {
    throw new Error(`Phase ${n}: orchestrator ended without PHASE_DONE or FRAMEWORK_BUG marker`)
  }
  POSTCONDITIONS[n]()
  log(`Phase ${n} postconditions OK`)
  summary.push({ phase: n, ok: true })
}

// === Wrap-up ===
phase('Wrap-up')
const finalState = readJson('.methodology/state.json')
log(`Pipeline state: ${JSON.stringify(finalState)}`)
return {
  complete: true,
  phases: summary,
  state: finalState,
  gates: {
    gate2: gateScore('.methodology/gate2_result.json'),
    gate3: gateScore('.methodology/gate3_result.json'),
    gate4: gateScore('.methodology/gate4_result.json'),
  },
}
