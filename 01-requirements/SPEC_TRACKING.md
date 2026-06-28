# Specification Tracking Matrix — taskq

> Source of truth: `/Users/johnny/projects/integration-test/01-requirements/SRS.md` (v1.0.0, 2026-06-29)
> Project role: integration-test target for harness-methodology v2.9 pipeline validation
> Phase: 1 — Requirements | Sub-Task: 2/4 (SPEC_TRACKING.md)
> Status legend: `DRAFT` → `APPROVED` → `IN-IMPLEMENTATION` → `IMPLEMENTED` → `VERIFIED`
> Owner legend: IMPLEMENTER = phase owner; REVIEWER = peer-reviewer (P6); OWNER = primary engineering lead.

## 1. Document Metadata

| Field | Value |
|-------|-------|
| Document ID | SPEC_TRACKING.md |
| Created | 2026-06-29 |
| Author Role | REQUIREMENTS_ENGINEER (Agent A) |
| Source Spec | SRS.md v1.0.0 (INGESTION MODE from SPEC.md v2.0.0) |
| Project Codename | taskq |
| Language | Python 3.11 (stdlib only) |
| Total FRs | 3 (FR-01, FR-02, FR-03) |
| Total NFRs | 3 (NFR-01, NFR-02, NFR-03) |
| Total Constraints | 7 (C-01 ~ C-07) |
| Total Config Vars | 3 (TASKQ_HOME, TASKQ_TASK_TIMEOUT, TASKQ_RETRY_LIMIT) |

## 2. FR Tracking Matrix

| FR ID | Title | Status | Owner | Priority | Spec Section | AC Count | Verification Phase | Implementation Phase | Test Phase | Risk Tags | Notes |
|-------|-------|--------|-------|----------|--------------|----------|-------------------|---------------------|-----------|-----------|-------|
| FR-01 | 任務模型與持久化 (Task Model and Persistence) | APPROVED | taskq-team/IMPLEMENTER | P0 | SRS §3.1.1, §3.1.2 | 7 | P5 | P3 | P4 | R1 (atomic write), NFR-02 (injection chars) | Validation: empty/length/injection chars; Pass: uuid8 + pending + atomic write + corruption-detect |
| FR-02 | 任務執行與重試 (Task Execution and Retry) | APPROVED | taskq-team/IMPLEMENTER | P0 | SRS §3.2.1, §3.2.2, §3.2.3, §3.2.4, §3.2.5 | 6 | P5 | P3 | P4 | R2 (subprocess hang), NFR-02 (no shell=True) | DERIVED: subprocess.run kwargs; State machine pending→running→{done,failed,timeout}; Retry up to TASKQ_RETRY_LIMIT |
| FR-03 | CLI 整合與查詢 (CLI Integration and Query) | APPROVED | taskq-team/IMPLEMENTER | P1 | SRS §3.3, §3.3.1, §3.3.2 | 6 | P5 | P3 | P4 | — | argparse subcommands; --json flag; exit code table (0/2/4/1) |

## 3. NFR Tracking Matrix

| NFR ID | Title | Status | Owner | Priority | Spec Section | AC Count | Verification Phase | Test Mechanism | Risk Tags | Notes |
|--------|-------|--------|-------|----------|--------------|----------|-------------------|---------------|-----------|-------|
| NFR-01 | Performance | APPROVED | taskq-team/IMPLEMENTER | P1 | SRS §4 | 1 | P5 | benchmark (p95 < 50ms over 100 submit+status iters) | — | DERIVED: p95 algorithm delegated to harness |
| NFR-02 | Security | APPROVED | taskq-team/SECURITY-LEAD | P0 | SRS §4 | 2 | P5 | grep zero shell=True + per-char blacklist unit tests | NFR-99 (coverage unit per-char) | shell=True forbidden codebase-wide; FR-01 blacklist 7 chars tested per-char |
| NFR-03 | Reliability | APPROVED | taskq-team/IMPLEMENTER | P0 | SRS §4 | 2 | P5 | kill-signal sim + redaction pattern match | R1 (atomic write), R3 (secret leak) | atomic write (tmp + os.replace); redaction `sk-[A-Za-z0-9_-]{8,}\|`token=\S+` → `[REDACTED]` |

## 4. Constraint Tracking

| C ID | Constraint | Status | Owner | Source | Verification |
|------|------------|--------|-------|--------|--------------|
| C-01 | Python 3.11 stdlib only | APPROVED | taskq-team/IMPLEMENTER | SPEC §1 | P3 — no requirements.txt runtime deps |
| C-02 | `python -m taskq` CLI entry point | APPROVED | taskq-team/IMPLEMENTER | SPEC §1 | P4 — argparse entry |
| C-03 | `shell=True` forbidden everywhere | APPROVED | taskq-team/SECURITY-LEAD | SPEC §2 / NFR-02 | P5 — codebase grep |
| C-04 | `tasks.json` atomic write (tmp + os.replace) | APPROVED | taskq-team/IMPLEMENTER | SPEC §2 / NFR-03 | P5 — kill-signal sim |
| C-05 | Configuration via `TASKQ_*` env vars (config.py) | APPROVED | taskq-team/IMPLEMENTER | SPEC §2 | P3 — config.py module |
| C-06 | `shlex.split` for command tokenization | APPROVED | taskq-team/IMPLEMENTER | SPEC §2 | P3 — code review |
| C-07 | Runtime zero external dependencies | APPROVED | taskq-team/IMPLEMENTER | PROJECT_BRIEF | P3 — no third-party packages |

## 5. Configuration Tracking

| Var | Default | Status | Owner | Spec Section | AC |
|-----|---------|--------|-------|--------------|-----|
| TASKQ_HOME | `.taskq` | APPROVED | taskq-team/IMPLEMENTER | SRS §5 | default applied when env unset |
| TASKQ_TASK_TIMEOUT | `10.0` | APPROVED | taskq-team/IMPLEMENTER | SRS §5 | default applied when env unset; used by FR-02 |
| TASKQ_RETRY_LIMIT | `2` | APPROVED | taskq-team/IMPLEMENTER | SRS §5 | default applied when env unset; used by FR-02 §3.2.4 |

## 6. Cross-Reference Index

| FR/NFR | Constraints | Config Vars | Risks | Open Issues |
|--------|-------------|-------------|-------|-------------|
| FR-01 | C-04, C-05, C-06 | TASKQ_HOME | R1 | — |
| FR-02 | C-03, C-06 | TASKQ_TASK_TIMEOUT, TASKQ_RETRY_LIMIT | R2 | NFR-99 (stdout_tail char-count ambiguity), NFR-99 (subprocess kwargs completeness) |
| FR-03 | C-02 | — | — | — |
| NFR-01 | — | — | — | NFR-99 (p95 algorithm ownership) |
| NFR-02 | C-03 | — | — | NFR-99 (coverage unit per-char) |
| NFR-03 | C-04 | — | R1, R3 | NFR-99 (line-vs-partial-line redaction semantics) |

## 7. Status Snapshot

| Layer | Total | DRAFT | APPROVED | IN-IMPLEMENTATION | IMPLEMENTED | VERIFIED |
|-------|-------|-------|----------|-------------------|-------------|----------|
| FR | 3 | 0 | 3 | 0 | 0 | 0 |
| NFR | 3 | 0 | 3 | 0 | 0 | 0 |
| Constraint | 7 | 0 | 7 | 0 | 0 | 0 |
| Config | 3 | 0 | 3 | 0 | 0 | 0 |

## 8. Completeness Validation

| Check | Result | Evidence |
|-------|--------|----------|
| All FRs from SRS.md enumerated? | PASS | FR-01, FR-02, FR-03 listed (SRS §3) |
| All NFRs from SRS.md enumerated? | PASS | NFR-01, NFR-02, NFR-03 listed (SRS §4) |
| All Constraints from SRS.md enumerated? | PASS | C-01 ~ C-07 listed (SRS §2) |
| All Config vars from SRS.md enumerated? | PASS | TASKQ_HOME, TASKQ_TASK_TIMEOUT, TASKQ_RETRY_LIMIT (SRS §5) |
| Owner assigned per FR? | PASS | IMPLEMENTER / SECURITY-LEAD owners per row |
| Owner assigned per NFR? | PASS | IMPLEMENTER / SECURITY-LEAD owners per row |
| Status populated per item? | PASS | All rows show `APPROVED` (Phase 1 gate state) |
| Orphan requirements (in SRS but not tracked)? | NONE | FR count matches SRS §3; NFR count matches SRS §4 |
| Risks cross-referenced? | PASS | R1/R2/R3 mapped (SRS §9) |
| Open issues cross-referenced? | PASS | NFR-99 entries mapped (SRS §8) |

## 9. Phase Hand-off

| Hand-off Target | Items to Carry |
|-----------------|---------------|
| Sub-Task 3/4 (TRACEABILITY_MATRIX.md) | FR list §2, NFR list §3, AC counts per row |
| Sub-Task 4/4 (TEST_INVENTORY.yaml) | FR list §2, NFR list §3, per-item AC counts as 1:1 sub-case input |
| Phase 3 (Implementation) | Approved FR/NFR rows, ownership table, constraint list |
| Phase 5 (Verification) | AC count per FR/NFR row, risk tags |
| Phase 6 (Quality / Peer Review) | Owner column for review-attribution |

## 10. Open Items

| ID | Description | Source | Tracking |
|----|-------------|--------|----------|
| NFR-99 / FR-02 | stdout_tail "末 2000 字元" byte-vs-char ambiguity | SRS §8 | Carried forward to P3/P5 for harness resolution |
| NFR-99 / FR-02 | subprocess.run kwargs completeness | SRS §8 | Carried forward to P3 |
| NFR-99 / NFR-01 | p95 algorithm ownership (sort-index vs quantile) | SRS §8 | Carried forward to P5 benchmark design |
| NFR-99 / NFR-02 | redaction line-vs-partial-line semantics | SRS §8 | Carried forward to P5 |

---

*Document version: SPEC_TRACKING v1.0.0 | Authored: 2026-06-29 | Phase: 1 — Requirements | Status: APPROVED-pending-B-review*
