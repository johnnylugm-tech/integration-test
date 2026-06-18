#!/usr/bin/env node
// /tmp/run-e2e.mjs — node-native E2E driver for harness-e2e.js
//
// LIVES OUTSIDE THE REPO on purpose. The harness-e2e.js:9-14 baseline
// contract mandates exactly 2 tracked files (SPEC.md + harness-e2e.js).
// The driver is invoked as `node /tmp/run-e2e.mjs` from REPO.
//
// PURPOSE
//   Run the full P0→P8 harness-methodology validation pipeline without
//   depending on Claude Code's Workflow runtime. This is the official
//   "manual driving" path documented in harness-e2e.js:26-30 — each phase
//   is spawned as a headless `claude -p` sub-agent and postcondition checks
//   run natively in Node.
//
// SOURCE OF TRUTH
//   /Users/johnny/projects/integration-test/harness-e2e.js
//   The driver reuses `orchestratorPrompt(n)` and `POSTCONDITIONS[n]()` from
//   the source by extracting the `const` blocks at startup and `eval()`-ing
//   them in driver scope. Closures inside those blocks capture driver-scope
//   bindings (REPO, VENV_PY, sh, log, etc.), so no rewriting is needed.
//
// WHY NOT dynamic import
//   `harness-e2e.js` has top-level `return` at line 797 + 867. Node treats
//   this as a parse-time `SyntaxError: Illegal return statement` for any
//   `.mjs` / dynamic-import path. vm.SourceTextModule hits the same error.
//   Eval-extraction sidesteps it because we never run the source as a
//   module — we just lift the const declarations.

import fs from 'node:fs'
import path from 'node:path'
import { execSync, spawnSync } from 'node:child_process'
import crypto from 'node:crypto'

// === Config ===
const REPO = '/Users/johnny/projects/integration-test'
const HARNESS_E2E = path.join(REPO, 'harness-e2e.js')
const PY = '/opt/homebrew/bin/python3.11'
const VENV_PY = path.join(REPO, '.venv/bin/python')
const HARNESS_REMOTE = 'https://github.com/johnnylugm-tech/harness-methodology'
const START = Number(process.env.START ?? 0)
const MODEL = process.env.MODEL ?? 'claude-haiku-4-5-20251001'

// === Driver-scope utilities (closures from extracted blocks bind these) ===
const sh = (cmd, opts = {}) => {
  try {
    return execSync(cmd, { cwd: REPO, encoding: 'utf-8', stdio: 'pipe', ...opts }).trim()
  } catch (e) {
    const msg = e.stderr || e.stdout || e.message
    e.displayMessage = msg
    throw e
  }
}
const log = (msg) => {
  const ts = new Date().toISOString().slice(11, 19)
  console.log(`[${ts}] ${msg}`)
}
const exists = (rel) => fs.existsSync(path.join(REPO, rel))
const readJson = (rel) => JSON.parse(fs.readFileSync(path.join(REPO, rel), 'utf-8'))
const gateScore = (rel) => { const g = readJson(rel); return g.overall_score ?? g.composite_score ?? 0 }
const detect429 = (out) => {
  if (!out) return true
  return /rate.limit|429|session.*quota|usage.*exceeded|too many requests/i.test(String(out))
}

// === Checkpoint ===
const checkpointPath = path.join(REPO, '.sessi-work/e2e_checkpoint.json')
const saveCheckpoint = (n, detail) => {
  fs.mkdirSync(path.join(REPO, '.sessi-work'), { recursive: true })
  fs.writeFileSync(checkpointPath, JSON.stringify({ phase: n, detail, ts: new Date().toISOString() }, null, 2))
}

// === Extract const block from harness-e2e.js ===
// Each top-level const block is followed by a `// === ... ===` section
// comment. We use that as the only boundary marker to avoid matching
// nested `const` inside function bodies.
function extractConstBlock(src, name) {
  const startRe = new RegExp(`^const ${name} = `, 'm')
  const m = src.match(startRe)
  if (!m) throw new Error(`extractConstBlock: cannot find 'const ${name} = ' in harness-e2e.js`)
  const start = m.index
  const after = src.slice(start + m[0].length)
  // Strictly top-level section delimiter: `\n// ===`
  const boundaryRe = /\n\/\/ ===/
  const next = after.match(boundaryRe)
  const end = next ? start + m[0].length + next.index : src.length
  return src.slice(start, end)
}

// === Extract harness helpers via eval ===
function loadHarnessHelpers() {
  const src = fs.readFileSync(HARNESS_E2E, 'utf-8')
  const sourceHash = crypto.createHash('sha256').update(src).digest('hex').slice(0, 16)
  log(`harness-e2e.js source hash: ${sourceHash}`)

  const helpers = [
    'orchestratorPrompt',
    'POSTCONDITIONS',
    'validateHandoff',
    'verifySubmoduleSource',
    'verifyHarnessBundle',
    'verifyManifestJSON',
    'verifyP3PostGate2Structural',
    'verifyP3Sentinels',
    'verifyBugHuntResolutionSchema',
    'testSpecHasTableRows',
  ]
  let evalSrc = ''
  for (const name of helpers) {
    const block = extractConstBlock(src, name)
    const rewritten = block.replace(new RegExp(`^const ${name} = `), `var ${name} = `)
    evalSrc += rewritten + '\n\n'
  }
  let exposeSrc = ''
  for (const name of helpers) exposeSrc += `globalThis.__harness_${name} = ${name};\n`
  // eslint-disable-next-line no-eval
  eval(evalSrc + exposeSrc)

  const out = {}
  for (const name of helpers) {
    const v = globalThis[`__harness_${name}`]
    if (v === undefined) throw new Error(`helper ${name} not loaded`)
    out[name] = v
  }
  return out
}

// === Bootstrap phase (deterministic, mirrors harness-e2e.js:619-695) ===
function runBootstrap() {
  log('=== Bootstrap ===')

  log('Idempotency prep: removing prior Bootstrap artifacts…')
  for (const cmd of [
    'git submodule deinit --all -f',
    'rm -rf .git/modules/harness',
    'rm -rf harness .venv .harness .methodology 03-development .coverage',
    'rm -f PROJECT_BRIEF.md .gitmodules',
  ]) {
    try { sh(cmd) } catch { /* artifact may not exist */ }
  }

  const status = sh('git status --porcelain')
  if (status !== '') throw new Error(`bootstrap: working tree not clean — revert to baseline first\n${status}`)
  const files = sh('git ls-files').split('\n').sort()
  if (JSON.stringify(files) !== JSON.stringify(['SPEC.md', 'harness-e2e.js'])) {
    throw new Error(`bootstrap: baseline must contain exactly SPEC.md + harness-e2e.js, got: ${files.join(', ')}`)
  }
  log('Working tree is clean 2-file baseline.')

  log('Adding harness submodule…')
  sh(`git submodule add ${HARNESS_REMOTE} harness`)

  log('Creating venv + installing harness toolchain…')
  sh(`${PY} -m venv .venv`)
  sh(`${path.join(REPO, '.venv/bin/pip')} install -q --upgrade pip`, { timeout: 300_000 })
  sh(`${path.join(REPO, '.venv/bin/pip')} install -q -r harness/requirements.txt`, { timeout: 900_000 })

  log('init-project + plan-all…')
  sh(`${VENV_PY} harness/harness_cli.py init-project --phase 1 --project . --language python`)
  sh(`${VENV_PY} harness_cli.py plan-all --project .`)

  sh('git add -A')
  sh('git commit -m "chore(bootstrap): harness submodule + venv wiring + 8 phase plans"')
  sh('git push origin main')

  const head = sh('git rev-parse HEAD')
  const diff = sh(`git diff-tree --no-commit-id --name-only -r ${head}`)
  if (!diff.split('\n').includes('harness')) {
    throw new Error('bootstrap: superproject HEAD contains no harness/ change — submodule bump missing')
  }
  log('Bootstrap: submodule pointer bump verified in HEAD.')

  const harnessHead = sh('git -C harness rev-parse HEAD')
  const probes = [
    { name: 'B.1 validate-handoff', cmd: 'git -C harness grep -q "validate-handoff"' },
    { name: 'B.2 p3-post-gate2',    cmd: 'git -C harness grep -q "p3-post-gate2"' },
    { name: 'B.3 TEST_SPEC table',  cmd: 'git -C harness grep -q "TEST_SPEC"' },
  ]
  const missing = []
  for (const p of probes) {
    try { sh(p.cmd) } catch { missing.push(p.name) }
  }
  if (missing.length) {
    throw new Error(`harness ${harnessHead.slice(0,8)} missing B-bundle markers: ${missing.join(', ')}`)
  }
  log(`Bootstrap: harness @ ${harnessHead.slice(0,8)} contains B-bundle markers.`)

  log('Bootstrap complete.')
}

// === Phase orchestrator spawn (claude -p headless) ===
function spawnOrchestrator(n, prompt) {
  const args = [
    '-p', prompt,
    '--output-format', 'json',
    '--max-turns', '300',
    '--permission-mode', 'bypassPermissions',
    '--no-session-persistence',
    '--model', MODEL,
  ]
  log(`Spawning claude -p for phase ${n} (model=${MODEL})…`)
  const result = spawnSync('claude', args, {
    cwd: REPO,
    encoding: 'utf-8',
    stdio: 'pipe',
    env: { ...process.env, ANTHROPIC_MODEL: MODEL },
    timeout: 5400_000,
  })
  if (result.error) throw result.error
  const stdout = result.stdout ?? ''
  const stderr = result.stderr ?? ''
  return { exitCode: result.status, signal: result.signal, stdout, stderr, combined: stdout + '\n' + stderr }
}

function parsePhaseResult(spawnOut) {
  const text = spawnOut.combined
  const bugMatch = text.match(/^===FRAMEWORK_BUG===\s*(\{[\s\S]*?\})\s*$/m)
  if (bugMatch) return { kind: 'frameworkBug', report: bugMatch[1] }
  const doneMatch = text.match(/^===PHASE_DONE===\s*(\{[\s\S]*?\})\s*$/m)
  if (doneMatch) return { kind: 'phaseDone', report: doneMatch[1] }
  return { kind: 'incomplete', exitCode: spawnOut.exitCode, tail: text.slice(-2000) }
}

// === Main loop ===
async function main() {
  log(`/tmp/run-e2e.mjs starting`)
  log(`  REPO    = ${REPO}`)
  log(`  HARNESS_E2E = ${HARNESS_E2E}`)
  log(`  START   = ${START}`)
  log(`  MODEL   = ${MODEL}`)

  if (START <= 0) {
    runBootstrap()
  }

  log('Loading harness-e2e.js helpers (eval-extract)…')
  const harness = loadHarnessHelpers()
  if (typeof harness.orchestratorPrompt !== 'function') {
    throw new Error('harness.orchestratorPrompt not loaded')
  }
  if (typeof harness.POSTCONDITIONS !== 'object' || harness.POSTCONDITIONS === null) {
    throw new Error('harness.POSTCONDITIONS not loaded')
  }
  log('harness helpers loaded.')

  const summary = []
  for (let n = 1; n <= 8; n++) {
    if (n < START) continue
    log(`=== Phase ${n} ===`)

    try {
      harness.validateHandoff(n)
      log(`Phase ${n} preflight: handoff OK`)
    } catch (e) {
      log(`BLOCKED: ${e.message}`)
      saveCheckpoint(n, `handoff P${n-1}→P${n} failed`)
      return { stoppedAt: n, handoffBlocked: true, reason: e.message }
    }
    saveCheckpoint(n, 'orchestrator launching')

    const MAX_RETRIES = 3
    const BACKOFF_MS = [30_000, 60_000, 120_000]
    let spawnOut = null
    let parsed = null
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      if (attempt > 0) {
        const delay = BACKOFF_MS[attempt - 1] ?? 120_000
        log(`Retry ${attempt}/${MAX_RETRIES} after ${delay / 1000}s backoff (HTTP 429 / session quota)…`)
        await new Promise(r => setTimeout(r, delay))
        saveCheckpoint(n, `retry ${attempt}`)
      }
      spawnOut = spawnOrchestrator(n, harness.orchestratorPrompt(n))
      parsed = parsePhaseResult(spawnOut)
      if (parsed.kind !== 'incomplete' || spawnOut.exitCode === 0) break
      if (detect429(spawnOut.combined)) {
        log(`Phase ${n}: HTTP 429 / session quota detected — will retry`)
        continue
      }
      log(`Phase ${n}: orchestrator exited ${spawnOut.exitCode} (non-429) — stopping.`)
      saveCheckpoint(n, 'agent threw non-429')
      return { stoppedAt: n, agentError: true, error: spawnOut.stderr.slice(0, 2000) }
    }

    if (parsed.kind === 'frameworkBug') {
      log(`FRAMEWORK BUG reported in Phase ${n} — stopping for supervisor fix.`)
      saveCheckpoint(n, 'framework bug')
      return { stoppedAt: n, frameworkBug: true, report: parsed.report }
    }
    if (parsed.kind === 'phaseDone') {
      log(`Phase ${n} orchestrator reported ===PHASE_DONE===`)
    } else {
      log(`Phase ${n}: orchestrator did NOT print ===PHASE_DONE=== (exit=${spawnOut.exitCode}) — relying on postconditions`)
    }

    try {
      if (typeof harness.POSTCONDITIONS[n] !== 'function') {
        throw new Error(`POSTCONDITIONS[${n}] not defined`)
      }
      harness.POSTCONDITIONS[n]()
      log(`Phase ${n} postconditions OK`)
      summary.push({ phase: n, ok: true })
    } catch (e) {
      log(`Phase ${n} postcondition FAILED: ${e.message}`)
      saveCheckpoint(n, 'postcondition failed')
      return { stoppedAt: n, postconditionFailed: true, error: e.message }
    }
  }

  log('=== Wrap-up ===')
  let finalState = null
  try { finalState = readJson('.methodology/state.json') } catch { /* missing is fine */ }
  log(`Pipeline state: ${JSON.stringify(finalState)}`)
  return { complete: true, phases: summary, state: finalState }
}

main().then(
  (result) => {
    log(`Result: ${JSON.stringify(result, null, 2)}`)
    process.exit(result.complete ? 0 : 1)
  },
  (err) => {
    console.error('FATAL:', err.stack || err.message)
    process.exit(2)
  }
)
