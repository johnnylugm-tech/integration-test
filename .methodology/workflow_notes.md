# Workflow Notes (cross-phase)

> Cross-phase notes for `.claude/workflows/*.js`. **Not regenerated** by
> `harness_cli.py plan-all` — use this file for content that must persist
> across plan regenerations.

---

## Retry & Stall Mechanism (workflow JS)

Phase 6 orchestrator (`.claude/workflows/phase6-quality.js`) includes session-limit / stall detection
in Gate 4 retry loops. When an LLM agent stalls (no progress > 600s) or returns null/empty
(session limit / rate limit), the workflow aborts retries and returns `session_limit_blocked`
instead of wasting further turns. Resume after quota reset — GUARD checks (advance-phase) skip
already-completed FRs.

**Observed during integration-test run 2026-06-25**: Gate 4 R2 stalled at 868s, retried
automatically, succeeded on first retry. No operator intervention required.

**Operator guidance**:
- If workflow reports `session_limit_blocked: true`, wait for quota reset and re-run phase6-quality.js.
- Do NOT increase retry count above 3 — stall usually indicates quota exhaustion, not transient failure.
- Each retry consumes ~50–100k tokens; budget accordingly when running other workflows in parallel.

---

## Phase Source-of-Truth

`.methodology/state.json` `.current_phase` is the authoritative phase indicator. All workflow JS
GUARDs (phase 1–7 advance steps) read state.json via `jq` instead of grepping HANDOVER.md for
`resume_phase` / `PN-entry` markers. `harness_cli._advance_fsm()` writes state.json atomically
when advance-phase completes; HANDOVER.md is regenerated from state.json for human readability.

---

## Submodule Drift Advisory

`harness_cli._advance_prechecks()` (postflight) fetches the `harness/` submodule origin and
compares HEAD to `origin/main`. If behind, prints `[WARN] harness/ submodule is N commit(s)
behind origin/main. CI may have applied test-fix commits.` with actionable pull-and-bump
commands. Non-blocking — silent skip on offline / no origin access.

When you see this warning:

```bash
git -C harness pull --ff-only origin main
git add harness && git commit -m 'chore(harness): bump submodule to latest'
```
