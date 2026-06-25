# Release Checklist

> **Project**: integration-test (taskq)
> **Version**: 1.0.0
> **Generated**: 2026-06-25
> **Phase**: 8 — Configuration Author
> **Cross-references**: `08-config/CONFIG_RECORDS.md`, `FINAL_SIGN_OFF.md`, `RELEASE_NOTES.md`, `07-risk/RISK_REGISTER.md`, `05-verification/VERIFICATION_REPORT.md`, `.sessi-work/gate4_result.json`

---

## 1. Purpose

Operational checklist for releasing `taskq` v1.0.0. Organised in three phases — **Pre-release** (gate-readiness), **Deployment** (install + smoke), **Post-release** (monitor + rollback). Every step is verifiable; failures block the next phase.

**Release status (entry):** CERTIFIED — `FINAL_SIGN_OFF.md` §5. Gate 4 composite **91.92 / 100** ≥ 85 threshold.

---

## 2. Pre-Release (BLOCKING — must all PASS before deploying)

### 2.1 Gate Status

| Check | Required | Current | Source | Status |
|-------|----------|---------|--------|--------|
| Gate 1 (per-FR TDD) | 5/5 FRs PASS, score ≥ 85 each | 5/5 PASS (96.94 / 94.22 / 99.66 / 99.36 / 95.92) | `.methodology/fr_progress.json` | PASS |
| Gate 2 (phase exit) | composite ≥ 85 | 95.7 | `.methodology/gate2_result.json` | PASS |
| Gate 3 (testing) | composite ≥ 85, coverage ≥ 95% src | 100.0 (100% src / 94% combined) | `.methodology/gate3_result.json` | PASS |
| Gate 4 (final quality) | composite ≥ 85 | **91.92** | `.sessi-work/gate4_result.json` | PASS |

### 2.2 Open Defects

| Severity | Required | Current | Source |
|----------|----------|---------|--------|
| Critical | 0 | 0 | `06-quality/QUALITY_REPORT.md` §Defect Summary |
| High | 0 | 0 | same |
| Medium | 0 | 0 | same |
| Low | informational only | 1 (bandit B404/B603 subprocess advisory) | `.sessi-work/gate4_result.json::scores.security` |

**No critical/high/medium open.** Low advisory is documented as intentional (`shell=False` enforced, NFR-02 satisfied via `injection_guard`).

### 2.3 Security

| Check | Required | Status |
|-------|----------|--------|
| `bandit -r 03-development/src/ -ll` | 0 high, 0 medium | 0 high, 0 medium, 2 low (informational) — PASS |
| `gitleaks detect --source .` | no leaks | clean — PASS |
| `grep -r "shell=True" 03-development/src/` | 0 hits | 0 hits (architecture constraint `no_shell_true`) — PASS |
| Injection-character blacklist (7 chars: `;&|`$`<>(){}!*?~\n\r\t\\`) | covered | TC-FR01-08..14 + TC-NFR02-02 — PASS |
| Secret redaction (`sk-*` / `token=*`) | covered | TC-NFR04 — PASS |
| `.secrets.baseline` committed | yes | yes — PASS |

### 2.4 Test Suite

| Check | Required | Current | Status |
|-------|----------|---------|--------|
| pytest pass count | 175 / 175 | 175 / 175 (11.03 s) | PASS |
| Source coverage | ≥ 95% | 100% (496/496) | PASS |
| Combined coverage | ≥ 90% | 94% (2544 stmts; 143 missed in test files) | PASS |
| High-risk module coverage | 100% | 100% (`executor`, `breaker`, `store`) | PASS |
| Bug-hunt regression tests | all pass | 5/5 (`test_bughunt_regressions.py`) | PASS |

### 2.5 Documentation & Traceability

| Check | Required | Status |
|-------|----------|--------|
| `RELEASE_NOTES.md` v1.0.0 present | yes | yes — PASS |
| `FINAL_SIGN_OFF.md` signed off | yes | yes (P6 Release Author) — PASS |
| Per-FR `[FR-XX]` tags on public symbols | 30/30 | 30/30 (100% documentation score) — PASS |
| `BASELINE.md` + `VERIFICATION_REPORT.md` present | yes | yes (Phase 5 deliverables) — PASS |
| `RISK_REGISTER.md` + `RISK_MITIGATION_PLANS.md` + `RISK_STATUS_REPORT.md` | yes | yes (Phase 7 deliverables) — PASS |
| `CONFIG_RECORDS.md` (this phase) | yes | yes — PASS |
| `SPEC.md` v1.0.0 single source of truth | yes | yes — PASS |

### 2.6 Architecture Constraints

| Constraint | Required | Status |
|------------|----------|--------|
| `no_circular_dependencies` | enforced | enforced — PASS |
| `no_shell_true` | enforced | enforced (0 hits) — PASS |
| `atomic_writes_only` (3 state files) | enforced | enforced (tmp + `os.replace`) — PASS |

### 2.7 Configuration Inventory

Per `08-config/CONFIG_RECORDS.md`:
- 8 `TASKQ_*` env vars declared in `.env.example` and `Config` dataclass — PASS
- NFR-06 sole-reader invariant (only `taskq.config` reads `os.environ`) — PASS
- No external secrets, API keys, feature flags — PASS (zero third-party deps)
- 3 atomic state files in `$TASKQ_HOME` — PASS

### 2.8 Pre-Release Gate Decision

**All 2.1–2.7 checks PASS.** Release is cleared to enter Deployment phase.

---

## 3. Deployment

### 3.1 Environment Preparation

| Step | Command / Action | Verification |
|------|------------------|--------------|
| D1. Verify Python runtime | `python --version` → 3.14.6 (or 3.11+) | matches SPEC §1 minimum |
| D2. Clone / pull repo | `git clone <repo> && cd integration-test` | on branch `main`, latest commit `0c66222` or newer |
| D3. Create venv | `python -m venv .venv` then `.venv/bin/pip install -e .` (no third-party deps; smoke tests the install path) | `pip check` returns no conflicts |
| D4. Verify zero-dep install | `.venv/bin/python -c "import taskq; print(taskq.__name__)"` → `taskq` | importable |
| D5. Prepare `$TASKQ_HOME` directory | set `TASKQ_HOME=/var/lib/taskq/prod` (absolute, non-default) | `ls -ld $TASKQ_HOME` shows writable dir |
| D6. Copy `.env.example` → `.env` | `cp .env.example .env` and adjust per env matrix in `08-config/CONFIG_RECORDS.md` §6 | `.env` present at repo root |

### 3.2 Environment Variables (all 8 must be set per environment)

| Variable | dev | staging | prod |
|----------|-----|---------|------|
| `TASKQ_HOME` | `.taskq` | `/var/lib/taskq/staging` | `/var/lib/taskq/prod` |
| `TASKQ_MAX_WORKERS` | `4` | `8` | (host-CPU tuned) |
| `TASKQ_TASK_TIMEOUT` | `10.0` | `10.0` | `10.0` |
| `TASKQ_RETRY_LIMIT` | `2` | `2` | `3` |
| `TASKQ_BACKOFF_BASE` | `0.1` | `0.1` | `0.1` |
| `TASKQ_BREAKER_THRESHOLD` | `3` | `3` | `5` |
| `TASKQ_BREAKER_COOLDOWN` | `5.0` | `5.0` | `30.0` |
| `TASKQ_CACHE_TTL` | `3600` | `600` | `3600` |

> Rationale for prod tuning: see `08-config/CONFIG_RECORDS.md` §6.

### 3.3 Secrets Rotation

**No external secrets exist** for this release (zero third-party deps — `R19` in `07-risk/RISK_REGISTER.md`). The only secret-adjacent code path is **outbound** (`store._redact` NFR-04). Therefore there is no secret to rotate.

If future releases add external integrations, this section MUST be updated to include the rotation procedure before deployment.

### 3.4 Smoke Tests (run on deployment host)

| # | Command | Expected | Exit |
|---|---------|----------|------|
| S1 | `.venv/bin/python -m taskq --help` | usage text printed | 0 |
| S2 | `.venv/bin/python -m taskq submit "echo smoke-$RANDOM"` | 8-hex task id printed | 0 |
| S3 | `.venv/bin/python -m taskq list` | shows the submitted task with status `pending` | 0 |
| S4 | `.venv/bin/python -m taskq run --all --json` | JSON line per task, exit 0 (success) | 0 |
| S5 | `.venv/bin/python -m taskq status <id-from-S2> --json` | JSON with `status=done`, `cached=False`, `exit_code=0` | 0 |
| S6 | `.venv/bin/python -m taskq submit "sleep 30" --name slow-task` then `run <id>` | exits with code 4 (timeout) after `TASKQ_TASK_TIMEOUT` seconds | 4 |
| S7 | `.venv/bin/python -m taskq run --all --cached` | replayed results with `cached=true` flag | 0 |
| S8 | `.venv/bin/python -m taskq clear` then `list` | empty list | 0 |
| S9 | `python -m pytest 03-development/tests/ -q` | `175 passed` | 0 |
| S10 | `bandit -r 03-development/src/ -ll` | 0 high / 0 medium (only known LOW advisories) | 0 |
| S11 | `gitleaks detect --source .` | no leaks found | 0 |
| S12 | `grep -r "shell=True" 03-development/src/` | 0 hits | 1 (grep "no match") |

**All 12 smoke tests must pass before declaring deployment successful.**

---

## 4. Post-Release

### 4.1 Monitoring

| Metric | Source | Threshold / Action |
|--------|--------|--------------------|
| Breaker state | `$TASKQ_HOME/breaker.json` (poll via `python -m taskq run <id>` outcome or direct read) | If OPEN more than 1×/hour, page on-call |
| Cache hit ratio | `len(cache.json)` entries vs `len(tasks.json)` new runs | Track weekly; `TASKQ_CACHE_TTL` adjustment if stale-heavy |
| Task timeout rate | tail `tasks.json` for `status=timeout` | > 5% of runs → investigate `TASKQ_TASK_TIMEOUT` |
| Disk usage of `$TASKQ_HOME` | `du -sh $TASKQ_HOME` | Alert at 80% of quota |
| Process / subprocess orphans | `ps -ef | grep python -m taskq` after deploy | Should be 0 between requests; presence indicates hung worker (R2) |
| Secret-leak false negatives | review `.secrets.baseline` drift | Any new baseline entry → investigate |

### 4.2 Rollback Plan

| Scenario | Detection | Action |
|----------|-----------|--------|
| Smoke test (S1–S12) failure | Immediate post-deploy | `git revert <release-commit>`; re-deploy previous tag |
| Critical defect discovered in first 24 h | PagerDuty / issue tracker | `git revert`; re-run Gate 4 on revert; redeploy |
| Breaker false-open (R3) | Breaker OPEN > 1 hour with healthy subprocesses | Set `TASKQ_BREAKER_THRESHOLD` higher; restart |
| `$TASKQ_HOME` corruption | `tasks.json` `JSONDecodeError` on read (`store.load_tasks` → "store corrupted" stderr + exit 1) | Restore from backup; **do not** edit manually (R12) |
| Cache poisoning (R4) | A task returns stale data with mismatched TTL semantics | `python -m taskq clear` (clears cache.json + tasks.json + breaker.json) |

**Rollback command (canonical):**
```bash
git checkout v1.0.0-previous    # or known-good tag
.venv/bin/pip install -e .
# env vars unchanged; $TASKQ_HOME preserved
```

> `$TASKQ_HOME` is **preserved** during rollback to keep in-flight task records. Only the binary is swapped.

### 4.3 Post-Release Verification (within 24 h)

- [ ] All S1–S12 smoke tests still passing on the deployed host.
- [ ] `python -m pytest 03-development/tests/ -q` → 175/175 PASS in deployed env.
- [ ] First 10 real user submissions complete with `status=done` (no `failed` / `timeout` regression).
- [ ] gitleaks scan still clean on the live `main` branch.
- [ ] No orphan processes from prior `python -m taskq run` invocations.

### 4.4 Known Limitations Carried Forward

From `RELEASE_NOTES.md` §8:
1. `architecture` dimension at 60/100 (da_waiver — orchestrator pattern; documented, not a release blocker).
2. `executor.run_task` CC(14) — within SAB max 15; deferred.
3. `breaker.py` MI 66.92 — slightly below project avg; no extraction warranted at this release.
4. No `pytest-benchmark` suite — `performance` dim returns `tool_score=null`; NFR-01 enforced via `test_nfr.py`.
5. Mutation testing disabled (`harness_config.json::features.mutation_testing=false`).
6. Legacy `.bak` files in `03-development/src/taskq/` — not imported, no runtime impact; housekeeping deferred.

---

## 5. Sign-Off Matrix

| Phase | Owner | Verifies | Date |
|-------|-------|----------|------|
| Pre-Release | P6 Release Author + P8 Config Author | §2 all checks PASS | 2026-06-25 |
| Deployment | Release Engineering | §3.4 S1–S12 PASS | (deployment-time) |
| Post-Release | Release Engineering + on-call | §4.3 all checkboxes ticked within 24 h | (post-deployment) |

---

## 6. Cross-References

| Artefact | Path |
|----------|------|
| Sign-off | `FINAL_SIGN_OFF.md` |
| Release notes | `RELEASE_NOTES.md` |
| Configuration inventory | `08-config/CONFIG_RECORDS.md` |
| Risk register | `07-risk/RISK_REGISTER.md` |
| Mitigation plans | `07-risk/RISK_MITIGATION_PLANS.md` |
| Verification provenance | `05-verification/VERIFICATION_REPORT.md`, `05-verification/BASELINE.md` |
| Quality report | `06-quality/QUALITY_REPORT.md` |
| Gate 4 raw | `.sessi-work/gate4_result.json` |
| Env var source of truth | `.env.example` |

---

_Generated by P8 Configuration Author · 2026-06-25_
