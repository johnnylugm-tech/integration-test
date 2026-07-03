# RISK_MITIGATION_PLANS.md — integration-test (taskq)

> Phase 7 — Risk Management
> Generated: 2026-07-04
> Scope: HIGH risks only (Likelihood × Impact ≥ 9). Lower-tier risks are summarized at the end.

## HIGH Risks — Formal Mitigation Plans

Each plan ships: trigger, owner, deadline (calendar date), exit criteria, and rollback note.

---

### H1 — R-05: Retry-stale running snapshot persists prior terminal fields

**Source**: bug_hunt_report.json taskq#1 (medium, confirmed, open)
**Likelihood × Impact**: 3 × 3 = 9 (HIGH)
**Module**: `03-development/src/taskq/executor.py` lines 211–213 + 248–249

**Trigger**: `TASKQ_RETRY_LIMIT > 0` AND first attempt fails/times-out AND a concurrent observer reads `tasks.json` between the inner-loop `running`-save (line 213) and the next attempt's terminal save (line 248/249).

**Why HIGH**: Data consistency is a user-visible contract violation (a task in `running` state should not have a non-null `finished_at`). Concurrent observers are uncommon but the project has zero tests for it, so a future code change could easily widen the window.

**Mitigation Plan**:

| Step | Action | Owner | Deadline | Exit Criteria |
|------|--------|-------|----------|---------------|
| 1 | Add regression test `test_retry_running_snapshot_resets_terminal_fields` in `03-development/tests/test_fr02.py`: simulate fail-then-succeed, assert that after attempt 1 saves `running` the record has `finished_at is None` and `duration_ms is None`. | taskq.executor maintainer | 2026-07-11 (1 gate cycle) | New test passes; existing retry tests stay green. |
| 2 | Edit executor.py:211–213 to `target["finished_at"] = None; target["duration_ms"] = None` before `_save_task` on the running-snapshot branch. | taskq.executor maintainer | 2026-07-11 | Code diff < 5 LOC, no new imports. |
| 3 | Update docstring on `run_task` to state the retry-snapshot invariant. | taskq.executor maintainer | 2026-07-11 | Docstring gains one sentence on retry-window observability. |
| 4 | Re-run Gate 1 (FR-02) delta; score must remain 100.0. | harness | 2026-07-11 | Gate 1 PASS for FR-02 in quality_manifest. |

**Rollback**: If any test regresses, revert executor.py:211–213 changes only — the new test stays as a future-marker (xfail).

---

### H2 — R-09: Readability (MI) buffer is 2.2 points over threshold

**Source**: Gate-4 readability finding + .methodology/gate4_result.json
**Likelihood × Impact**: 3 × 3 = 9 (HIGH)
**Modules**: `03-development/src/taskq/executor.py` (99 lines), `03-development/src/taskq/cli.py` (305 lines)

**Trigger**: Any future PR that adds a single responsibility to `run_task` (currently 99L) or stacks a new `cmd_*` handler without extracting helpers pushes MI under threshold 80.

**Why HIGH**: A single 5-line function could drop MI to ~77 and block the next gate. The proxy (Halstead) is unforgiving on size, not complexity.

**Mitigation Plan**:

| Step | Action | Owner | Deadline | Exit Criteria |
|------|--------|-------|----------|---------------|
| 1 | Pre-commit hook: if either `executor.py` or `cli.py` grows by ≥ 5 LOC, run `radon mi -j` and fail if either file drops below MI = 80. | tooling | 2026-07-18 (next gate cycle) | Hook active in `.git/hooks/pre-commit`; sample PR verified to block. |
| 2 | Refactor trigger documented: if `run_task` ever exceeds 99 LOC, the function MUST be split into `_run_with_retry` + `_emit_terminal_result` BEFORE the next gate. (Already exists as comment in phase plan.) | taskq.executor maintainer | ongoing | Comment exists in `harness/CLAUDE.md` or code-adjacent doc. |
| 3 | Captured radicals (B403/B603/# noqa) preserved: don't suppress bandit findings to lift MI (would create a different risk). | Johnny | ongoing | No `# noqa` added without SPEC justification. |

**Rollback**: Removing the hook is benign; the underlying MI score remains. Refactor is additive, never reverts.

---

### H3 — R-10: Architecture `community_cohesion` low (waiver-dependent at every gate)

**Source**: Gate-4 architecture score 0 (framework-owned); Gate-4 da_waiver `["architecture"]` approved; quality_manifest `da_waiver_needs_human_review: true`.
**Likelihood × Impact**: 4 × 3 = 12 (HIGH)
**Modules**: orchestrator surface — `03-development/src/taskq/__main__.py` + .claude/workflows/*

**Trigger**: Each gate run that finalizes via harness CRG without the da_waiver flow, or a future CRG toolchain upgrade that tightens the cohesion metric.

**Why HIGH**: Without the waiver, the gate scores 0 in architecture → composite fails threshold 80. The waiver is human-review-bound; if Johnny is unavailable, the pipeline stalls.

**Mitigation Plan**:

| Step | Action | Owner | Deadline | Exit Criteria |
|------|--------|-------|----------|---------------|
| 1 | Encode the waiver justification verbatim into the evaluate_dimension.md reference: orchestrator-hub star topology with imports from 6 sub-modules is intentional, not architectural debt. | CRG / harness | 2026-07-11 | Justification present in `.methodology/...` or harness commit. |
| 2 | Reduce hub import count in `__main__.py` by extracting a `cli_dispatch.py` layer (wraps argparse + dispatch only) and `_persist.py` layer (wraps _save_task calls only). The goal is to make `__main__.py` ≈ 1/3 of its current line count so the hub fans into 2 measurable hubs. | taskq maintainer | 2026-08-01 (next phase window) | CRG reports cohesion ≥ 0.3 for any of the new communities; still passes without waiver. |
| 3 | Even after refactor: keep da_waiver as backstop. Gate can still pass on waiver if Cohesion stays below 0.3 for the orchestrator hub. | Johnny | ongoing | da_waiver re-requested each gate; recorded in gate4_result.json `da_waiver_applied`. |
| 4 | Add a CRG smoke run to `.sessi-work/` after the refactor: `python3 harness_cli.py crg --phase 8 --project .` BEFORE opening Phase 8, so any regression surfaces immediately. | Johnny + workflow | 2026-07-25 (within Phase 7 exit) | crg_baseline_p7.json exists; sanity check. |

**Rollback**: No production rollback target — the refactor is layout-only. If cohesion drops further, revert the dispatch extraction and rely on waiver again.

---

### H4 — R-15: Workflow JS regression risk (history of #126/#134/#135/#136)

**Source**: MEMORY.md — e2e-round records 2026-06-18 / 2026-06-27 / 2026-06-28; harness commits `17d6d53`, `edcbefd`, `ffce7a0`.
**Likelihood × Impact**: 3 × 4 = 12 (HIGH)
**Modules**: `.claude/workflows/phase{1..8}-*.js`, `harness-e2e.js`, `phase1-workflow.mjs`, `run-e2e.mjs`

**Trigger**: New env-check or sentinel-check logic in workflow JS without an E2E test cycle; JS-comment collision in jq expressions; one-sided awk pipelines; partial-write regex.

**Why HIGH**: Workflows gate the entire pipeline (`run-phase --phase N`). A silent regression can pass tests but fail at the next phase, with no obvious signal until a higher-phase block surfaces.

**Mitigation Plan**:

| Step | Action | Owner | Deadline | Exit Criteria |
|------|--------|-------|----------|---------------|
| 1 | Per workflow-dev-playbook.md: every new workflow JS line MUST have a test E2E cycle (sandbox has no I/O → cannot trust agents to verify their own outputs). Already enforced; ensure HR-04 hybrid workflow (Agent A author + Agent B reviewer) is signed off in every phase. | workflow maintainer | ongoing | All new workflow lines cross-referenced to an E2E test in `harness-e2e.js`. |
| 2 | After every Phase 6 quality gate, capture a fresh `harness-e2e.js` run and store the diff in `.sessi-work/e2e-{date}/`. | Johnny | 2026-07-11 (immediate) | Directory `.sessi-work/e2e-2026-07-04/` exists with harness-e2e.js full log. |
| 3 | Add a `workflow-js-lint` script: scan all `.claude/workflows/*.js` for known-bad patterns (`wc -c | awk` after truncation; JS-comment in JSON-parsed output; FILE_OK_ regex literal; bare process.exit in non-env-check). | tooling | 2026-07-18 | Script runnable via `node harness/scripts/workflow-lint.js`; logs to `.sessi-work/workflow-lint.log`. |
| 4 | Pin workflow JS to known-good SHA `70ab69c`; do not edit JS during Phase 7/8 unless E2E cycle can run. | Johnny | 2026-07-04 (immediate) | Git status shows no `.claude/workflows/*.js` modifications during Phase 7. |

**Rollback**: If a regression ships, revert to the most-recent E2E-pass SHA (`70ab69c`) and re-run `harness-e2e.js`.

---

## Lower-Tier Risks (summary only)

The following MED/LOW risks do not require a formal plan with deadline, but are tracked in `RISK_REGISTER.md` and `RISK_STATUS_REPORT.md`:

- **R-01** (storage atomic write) — MITIGATED; trust mitigation, no further work.
- **R-02** (subprocess hang) — MITIGATED; preflight lint enforces `timeout=`.
- **R-03** (secret leak) — MITIGATED; redaction at persist boundary.
- **R-04** (stale cache) — NOT-PRESENT; design precludes.
- **R-06** (concurrent run race) — REFUTED on SPEC scope; documentation only.
- **R-07** (bandit LOW) — ACCEPTED; add `# nosec` comment (5 min task).
- **R-08** (pyright info) — ACCEPTED; switch to raw strings (optional).
- **R-11** (1-line coverage gap) — ACCEPTED; non-blocking.
- **R-12** (dead `_error` field) — OPEN; 1-line cleanup, defer to next executor refactor (likely packed with R-05 fix).
- **R-13** (gate verdict authority) — MITIGATED via workflow patches; regression-testing cadence per R-15 plan.
- **R-14** (harness submodule drift) — MONITORED; pin-sha discipline.
- **R-16** (mutation testing disabled) — DEFERRED; review at next gate.
- **R-17** (gap-report ORPHANED) — ACCEPTED; tool-limit heuristic.

---

## Cross-Cutting Decisions

- **No production code changes are gated by these plans.** All H1–H4 work happens inside the existing dev/test surface; HR-17 (no harness edits) still applies to H4 if any tooling lands under `harness/`.
- **Committed R-05 + R-12 can ship together** in a single `chore(taskq): retry-snapshot terminal-field reset + drop dead _error key` PR (≈ 6 LOC + 1 test). Recommended not to delay R-12 waiting for R-09 refactor trigger.
- **All deadlines are 1–4 weeks.** Anything slipping beyond 2026-08-01 should be re-scoped at Phase 8 entry review.
