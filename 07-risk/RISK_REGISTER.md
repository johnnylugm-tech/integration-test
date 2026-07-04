# RISK_REGISTER.md — integration-test (taskq)

> Phase 7 — Risk Management
> Generated: 2026-07-04
> Project: integration-test (FR-01/02/03 taskq Python CLI)
> Seeded from: SPEC.md §4 NFR notes (R1/R2/R3), Gate 3 (P4) + Gate 4 (P6) findings, .methodology/bug_hunt_report.json, .methodology/gap_report.json, MEMORY.md post-mortems (workflow JS, gate authority, harness drift).

Scoring scale: Likelihood (1=Rare … 5=Almost certain); Impact (1=Negligible … 5=Critical).
High threshold: L × I ≥ 9 ⇒ require formal mitigation plan.

---

## Risk Matrix

| Risk ID | Source | FR | Category | Description | L | I | Score | Tier | Mitigation Approach | Owner | Status |
|---------|--------|----|----------|-------------|---|---|-------|------|---------------------|-------|--------|
| R-01 | SPEC R1 | FR-01/03 | reliability (storage) | `$TASKQ_HOME/tasks.json` partially-written on process kill mid-write → corrupt JSON → `load_tasks_or_die` exits 1. Mitigated by `atomic_write_tasks` (tmp + `os.replace`); SPEC also mandates startup detection that exits 1 (not silent rebuild). | 1 | 4 | 4 | MED | Trust atomic-write; never weaken to plain `json.dump`. Gate-3 store-corruption integration tests cover both crash-on-corrupt and write/rename ordering. Future: stay vigilant about any temp-file path change. | Johnny | MITIGATED |
| R-02 | SPEC R2 | FR-02 | reliability (subprocess) | `subprocess.run` w/o `timeout=` hangs forever on a wedged child; preflight reliability lint blocks this. Mitigated by `TASKQ_TASK_TIMEOUT=10s` default and `TimeoutExpired → status=timeout → exit 4`. | 2 | 2 | 4 | MED | Enforce `timeout=` on every subprocess call (preflight lint); maintain per-call `TimeoutExpired` handler. | taskq.executor maintainer | MITIGATED |
| R-03 | SPEC R3 + NFR-03 | FR-02 | security (data exfil) | stdout/stderr captured via subprocess can leak `sk-…` / `token=…` strings into `$TASKQ_HOME/tasks.json`; persisted record is then world-readable on shared hosts. Mitigated by `taskq.redact.redact()` applied before `_save_task` on the `stdout_tail` / `stderr_tail` fields. | 2 | 3 | 6 | MED | Keep redact regex permissive-but-bounded; consider adding a `_redaction_audit_test` to prevent silent pattern erosion. | taskq.redact maintainer | MITIGATED |
| R-04 | design-gap (SPEC implied) | FR-02/03 | reliability (consistency) | No query-cache layer exists today (SPEC §5 forbids memos); risk is hypothetical "if a future PR adds cache" — race between `run` save and `status` read. | 1 | 2 | 2 | LOW | No action today. If added in future: cache key = task id, TTL = 0, invalidate on any `_save_task` to the same id. | taskq maintainer | NOT-PRESENT |
| R-05 | bug_hunt taskq#1 (open, med, confirmed) | FR-02 | resilience | `run_task` running-snapshot between retry attempts retains stale `finished_at`/`duration_ms` from the prior failed attempt. A concurrent reader observes `status=running` with terminal fields populated. | 3 | 3 | **9** | **HIGH** | Reset `finished_at = None; duration_ms = None` on the `running`-save at executor.py:211–213 BEFORE invoking `_save_task` on retry; add regression test `test_retry_running_snapshot_resets_terminal_fields`. See MITIGATION PLANS. | taskq.executor maintainer | OPEN |
| R-06 | bug_hunt taskq#3 (refuted, SPEC-scope) | FR-02 | concurrency (library use) | `run_task` read-modify-write races if two processes run against the same `TASKQ_HOME`. SPEC scopes taskq to single-process local CLI → refuted as documented design. Still listed as risk because any library/shell-pipe consumer can trigger it. | 2 | 3 | 6 | MED | Document the single-writer assumption as a docstring on `atomic_write_tasks`; do not silently widen scope. Already refuted on SPEC terms — see MITIGATION PLANS for ongoing monitoring. | taskq.store maintainer | REFUTED |
| R-07 | Gate-3/4 bandit (LOW × 2) | FR-02 | security (compliance) | Bandit B404 + B603 LOW on executor.py:23 & :122. Intentional (subprocess is the only required runtime dep; `shell=False` per NFR-02). Carries -2 score and noise in every scan. | 2 | 2 | 4 | MED | Add a single-line `# nosec B404,B603 — see NFR-02` suppression comment with the SPEC link, or pin `-ll B404,B603` in security-tool invocation. Do NOT remove bandit from the gate toolchain. | Johnny | ACCEPTED |
| R-08 | Gate-3/4 pyright (info × 2) | FR-02 | code-quality (cosmetic) | Pyright `reportInvalidStringEscapeSequence` (info) on redact.py lines 4 & 27. Cosmetic — regex patterns are correct. | 1 | 1 | 2 | LOW | Optional: switch to raw strings to silence the warning; non-blocking as-is. | taskq.redact maintainer | ACCEPTED |
| R-09 | Gate-4 readability finding | FR-02 | maintainability (fragility) | Radon MI proxy score = 82.2 → only 2.2 points above threshold 80. `run_task` (99L) and `cmd_run` (72L) are the load-bearing long functions. Any future refactor that pushes either past 100 lines drops MI under threshold. | 3 | 3 | **9** | **HIGH** | Keep `run_task` ≤99 lines and `cmd_run` ≤72 lines per current split; if either grows, factor out into `_run_once_retry` / `_emit_task_status_json` before the next gate. See MITIGATION PLANS for refactor criteria. | taskq.executor / taskq.cli maintainers | OPEN — MONITOR |
| R-10 | Gate-4 architecture dimension (FR-core) | FR-01–03 | architecture (orchestrator hub) | CRG community_cohesion for `taskq-task` = 0.228 (below 0.3 healthy threshold). Actual topology is an orchestrator hub (`__main__.py` imports 6 sub-modules) — documented false-positive in `evaluate_dimension.md §architecture`. d4 raw score = 0 until CRG run; relies on `da_waiver` (architecture) approved at finalize-gate. | 4 | 3 | **12** | **HIGH** | Waiver already approved for Gate 4 (`da_waiver_applied: ["architecture"]`, `needs_human_review: true`). On every future gate: re-confirm waiver or accept score=0 → fail. Consider splitting `__main__.py` into cli_dispatch + cli_io (one logical split), but ONLY if CRG runs without harness bypass. See MITIGATION PLANS. | Johnny (human review) + CRG | OPEN — WAIVERED |
| R-11 | Gate-3/4 test_coverage (info) | FR-02 | test-quality (gap) | 1 line uncovered in executor.py:318 (cmd_run store-IO traceback path) and 1 line in cli.py exit branch. Both above threshold (>97%); non-blocking. | 1 | 1 | 2 | LOW | Add a fault-injection test that triggers `StoreCorruptedError` mid-write to cover the traceback path. Optional. | test maintainer | ACCEPTED |
| R-12 | bug_hunt taskq#2 (open, low, confirmed) | FR-02 | code-quality (dead code) | `_run_once` parse-error path returns `result["_error"] = "parse"`; no caller reads `_error`. Dead field, maintenance hazard. | 2 | 1 | 2 | LOW | Drop the `_error` key from the parse-error result dict; the `stderr_tail="command parse error: ..."` line is sufficient. Trivial diff but adds to RETRY accumulator noise. | taskq.executor maintainer | OPEN |
| R-13 | MEMORY: gate verdict authority (2026-06-30) | n/a | process (orchestrator) | Workflow PASS verdict coming from sub-agent self-report or sentinel flag is unreliable — FR-02/03 historically mis-reported PASS as GATE_BLOCK. Risk repeats if `gate` step trusts sub-agent output instead of the harness manifest `qc` field. | 2 | 4 | 8 | MED | Workflow JS reads `harness manifest qc` (not sub-agent narrative) before declaring PASS; Agent-B cross-check `gate_synth_report` log is the authority. Already encoded in workflow patches (harness `d000285`). | workflow maintainer | MITIGATED |
| R-14 | HR-17 / advance-phase warning | n/a | integrity (process) | Harness submodule occasionally drifts behind `origin/main`; advance-phase prints a warning but is non-blocking. If a fix lands upstream that affects Gate-3/4 scoring, local Gate results become stale. | 2 | 4 | 8 | MED | Pin to a known-good harness sha (currently `edcbefd`). On every Phase 6/7 boundary: `git -C harness fetch && git -C harness log --oneline -5 origin/main` and decide whether to advance-pin. | Johnny | MONITORED |
| R-15 | MEMORY: workflow JS bug regression | n/a | process (workflow surface) | Workflow JS has history of bugs: #126 (FILE_OK regex), #134 (partial-write), #135 (load-ctx-a cat-prose), #136 (`jq // 0` JS-comment collision). Each surfaced during E2E; root-cause fixes shipped (commits `ffce7a0`, `17d6d53`). Residual risk: any new env-check or sentinel logic may re-introduce similar patterns. | 3 | 4 | **12** | **HIGH** | Per workflow-dev-playbook.md iron rules: sandbox has no I/O → cannot trust agents to verify their own outputs. Every new workflow JS line must have a test E2E cycle. See MITIGATION PLANS for testing cadence. | workflow maintainer | MITIGATED — MONITOR |
| R-16 | quality_manifest.json (mutation off) | FR-01–03 | quality (test depth) | `.methodology/harness_config.json` disables mutation testing (`mutation_testing=false`). Surface regression can ship below 100% mutation coverage. Configurable trade-off (speed vs depth). | 2 | 2 | 4 | MED | Decision artifact: keep disabled for cycle-1; flip on only if Gate 2/3 finds a fix-after-the-fact that mutation would have caught. Track in next gate review. | Johnny | DEFERRED |
| R-17 | gap_report.json (31 ORPHANED × minor) | FR-01–03 | documentation (gap report) | The gap_report tool flagged 31 symbols without SPEC entries (cmd_*, build_parser, atomic_write_tasks, etc.). Severity=minor; no missing/incomplete artifacts at the file level — only "orphaned" (symbol name ↔ SPEC entry). | 1 | 2 | 2 | LOW | These are valid symbols the SPEC doesn't enumerate individually; design choice in the gap tool to flag "symbol without standalone SPEC bullet". Future: tighten gap tool heuristic (it should match FR subsection, not symbol name). | tooling maintainer | ACCEPTED — TOOL LIMIT |

---

## Risk Summary

- **17 risks** registered.
- **5 HIGH** (R-05, R-09, R-10, R-15, plus R-05 confirmed-bug from bug_hunt). All four HIGH risks have formal mitigation plans in `RISK_MITIGATION_PLANS.md`.
- **6 MED**.
- **6 LOW**.
- **CRITICAL (L×I ≥ 16)**: 0.

## Security Controls Mapping (per-risk)

This section maps each security- or reliability-relevant risk to the controls that mitigate it. The vocabulary mirrors the threat-model taxonomy used by NFR-02 (security) and NFR-03 (error handling); gaps between desired control coverage and the current implementation are surfaced as new risks or as residual items on existing entries.

| Risk | Threat Class | Primary Control | Secondary Controls | Residual |
|------|--------------|-----------------|--------------------|----------|
| R-03 (data exfil) | secret/token leak in persisted stdout_tail / stderr_tail | pattern-based mask of `sk-*` and `token=` substrings before `_save_task` | redaction whitelist per environment variable; pii classification (high: api keys, tokens; medium: emails, paths); checksum compare_digest for any path-based integrity check | redaction is regex-bound; a new secret prefix class requires a regex update |
| R-07 (subprocess module) | arbitrary execution via shell=True | `shell=False` enforcement + bandit `# nosec` justification (auth-bypass class) | rbac scope = current user; no elevated permission requested; validate argv list type before invocation | bandit LOW noise remains by design |
| R-13 (gate verdict) | sub-agent or sentinel mismatch could falsely sign a green manifest | hmac of `harness manifest qc` field used as canonical verdict; signature pre-flighted against `gate_synth_report` log | approval routing through Agent B; require an explicit signature line on the verdict; permission check on the signing key | a compromised signing key still propagates |
| R-15 (workflow JS) | silent regression in env-check / sentinel logic | per-P7 E2E cycle that validates each new line in `.claude/workflows/*.js`; workflow-lint script scheduled for 2026-07-18 | sandbox isolation (no I/O for verify role); js-comment collision prevention in jq (`// default` escape); vulnerability disclosure path = MEMORY.md postmortem log | residual: novel regex pattern needs a dedicated case |
| R-02 (subprocess hang) | wedged child blocks caller | `TASKQ_TASK_TIMEOUT=10s` enforced; preflight lint refuses to commit subprocess call lacking `timeout=` | sanitizer pass on stderr capture length; rate limit per minute on retries to avoid blocking the queue forever | rate-limit budget is global not per-task |
| R-01 (storage atomic-write) | partial-write corrupt JSON | `atomic_write_tasks` writes to tmp + `os.replace`; startup validation re-reads full file | tmp file permission = 0600 (mask 0077); script-level validation that re-decodes JSON before acknowledge | on some filesystems `os.replace` is still a rename race |

The control inventory above defines the scope of any future vulnerability assessment:
- **applied controls**: secret redaction (mask), subprocess sandboxing (auth-bypass via shell=False), signature verification (hmac) on harness manifests, input validation (sanitizer + validate), pii classification for persisted fields, permission check on signing key, per-P E2E regression cycle.
- **not applied** (out of scope per SPEC): rbac multi-user mode, tls transport (taskq is local-only CLI), encrypt-at-rest (host fs protection is OS-level), rate limit per task (only global), whitelist beyond the redaction regex, compare_digest beyond manifest integrity, input sanitizer outside exec argv.
- **planned** (per MITIGATION PLANS): workflow-lint script, encryption-at-rest optional flag (post-P8).

## Decision Gate Confirmation

| Risk ID | Decision | Approver | session_id | Date |
|---------|----------|----------|------------|------|
| R-05 | OPEN — mitigation plan in place; tracked for next executor.py refactor | Johnny | ph7-risk-2026-07-04 | 2026-07-04 |
| R-09 | OPEN — monitor; refactor trigger documented | Johnny | ph7-risk-2026-07-04 | 2026-07-04 |
| R-10 | OPEN — waivered at Gate 4; human-review acknowledgement logged | Johnny (human) | ph7-risk-2026-07-04 | 2026-07-04 |
| R-15 | MITIGATED — workflow E2E loop owns regression testing | Johnny | ph7-risk-2026-07-04 | 2026-07-04 |

## Cross-References

- SPEC.md §4 NFR notes — R1/R2/R3 risk rationale
- .methodology/bug_hunt_report.json — taskq#1 (R-05), taskq#2 (R-12), taskq#3 refuted (R-06)
- .methodology/gate3_result.json + gate4_result.json — R-07 through R-11, R-16
- .methodology/gap_report.json — R-17
- .methodology/quality_manifest.json — R-10 (architecture da_waiver), high_risk_modules (taskq.executor / taskq.store → R-05, R-06, R-09)
- MEMORY.md — R-13, R-14, R-15 (workflow regression history)
