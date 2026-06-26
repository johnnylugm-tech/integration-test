# SPEC_TRACKING — taskq Requirements Tracking Matrix

> **Project**: taskq v2.0.0
> **Source of truth**: `01-requirements/SRS.md` (APPROVED, INGESTION MODE from SPEC.md v2.0.0)
> **Author**: Requirements_Engineer (Agent A — Sub-Task 2/4)
> **Round**: 1
> **Date**: 2026-06-26

This document tracks every FR and NFR from the approved SRS, their decomposition
into testable acceptance criteria, ownership across downstream sub-tasks, and
status through the harness phases. It is the canonical hand-off matrix between
Phase 1 (Requirements) and downstream phases (P2 Architecture, P3 Implementation,
P4 Testing, P5 Verification).

---

## 1. FR Tracking Matrix

| FR ID | Title | Command | Source SPEC.md § | AC Count | Owner Phase | Status | Notes |
|-------|-------|---------|------------------|----------|-------------|--------|-------|
| FR-01 | Task Model and Persistence | `taskq submit "<cmd>"` | §3 FR-01 | 9 (AC-FR01-01..09) | P3 (Implementation) | NOT_STARTED | Validates input, generates id (uuid4 prefix 8 hex), atomic write to `$TASKQ_HOME/tasks.json`; corrupted store → exit 1, no silent rebuild |
| FR-02 | Task Execution and Retry | `taskq run <id>` | §3 FR-02 | 10 (AC-FR02-01..10) | P3 (Implementation) | NOT_STARTED | State machine `pending→running→{done|failed|timeout}`; `subprocess.run(shlex.split(...))`; no `shell=True`; auto-retry up to `TASKQ_RETRY_LIMIT` (default 2); timeout → exit 4 |
| FR-03 | CLI Integration and Query | `python -m taskq` | §3 FR-03 | 8 (AC-FR03-01..08) | P3 (Implementation) | NOT_STARTED | argparse subcommands: `submit`/`run`/`status`/`list`/`clear`; `--json` global flag; exit codes 0/1/2/4 |

**FR total**: 3 FRs / 27 ACs.

---

## 2. NFR Tracking Matrix

| NFR ID | Title | Category | Source SPEC.md § | AC Count | Owner Phase | Status | Notes |
|--------|-------|----------|------------------|----------|-------------|--------|-------|
| NFR-01 | Performance | performance | §4 NFR-01 | 2 (AC-NFR01-01..02) | P4 (Testing) + P5 (Verification) | NOT_STARTED | `submit`+`status` 100 iter, p95 < 50ms (excludes subprocess exec); reproducible benchmark required |
| NFR-02 | Security | security | §4 NFR-02 | 3 (AC-NFR02-01..03) | P3 (Implementation) + P4 (Testing) | NOT_STARTED | No `shell=True` anywhere in `taskq/`; blacklist coverage `; \| & $ > < \`` (7 chars) |
| NFR-03 | Reliability | reliability | §4 NFR-03 | 5 (AC-NFR03-01..05) | P3 (Implementation) + P4 (Testing) | NOT_STARTED | Atomic write (tmp + os.replace); secret redaction `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` → `[REDACTED]`; no silent rebuild of corrupted store |

**NFR total**: 3 NFRs / 10 ACs.

---

## 3. Environment Variable Tracking

| Variable | Default | Owner | Cross-ref | Status |
|----------|---------|-------|-----------|--------|
| `TASKQ_HOME` | `.taskq` | P3 (`taskq.config`) | FR-01 (AC-FR01-08) | NOT_STARTED |
| `TASKQ_TASK_TIMEOUT` | `10.0` | P3 (`taskq.config`) | FR-02 (AC-FR02-03) | NOT_STARTED |
| `TASKQ_RETRY_LIMIT` | `2` | P3 (`taskq.config`) | FR-02 (AC-FR02-07, AC-FR02-08) | NOT_STARTED |

`.env.example` must declare all three (cross-ref NFR-02 config scope).

---

## 4. Acceptance Criteria Coverage Matrix

| AC ID | FR/NFR Parent | Testable From | Required Test File | Status |
|-------|---------------|---------------|--------------------|--------|
| AC-FR01-01 | FR-01 | CLI (submit empty) | `tests/test_fr01_validation.py` | NOT_STARTED |
| AC-FR01-02 | FR-01 | CLI (submit whitespace) | `tests/test_fr01_validation.py` | NOT_STARTED |
| AC-FR01-03 | FR-01 | CLI (boundary 1000 chars accepted) | `tests/test_fr01_validation.py` | NOT_STARTED |
| AC-FR01-04 | FR-01 | CLI (boundary 1001 chars rejected) | `tests/test_fr01_validation.py` | NOT_STARTED |
| AC-FR01-05 | FR-01 | CLI (7 blacklist chars — 7 sub-cases) | `tests/test_fr01_validation.py` | NOT_STARTED |
| AC-FR01-06 | FR-01 | Unit (id format = 8 lowercase hex) | `tests/test_fr01_id.py` | NOT_STARTED |
| AC-FR01-07 | FR-01 | Unit (record fields present) | `tests/test_fr01_record.py` | NOT_STARTED |
| AC-FR01-08 | FR-01 | Integration (tmp + os.replace) | `tests/test_fr01_atomic.py` | NOT_STARTED |
| AC-FR01-09 | FR-01 | Integration (corrupted store exit 1) | `tests/test_fr01_corruption.py` | NOT_STARTED |
| AC-FR02-01 | FR-02 | Integration (exit 0 → done) | `tests/test_fr02_state.py` | NOT_STARTED |
| AC-FR02-02 | FR-02 | Integration (non-zero → failed) | `tests/test_fr02_state.py` | NOT_STARTED |
| AC-FR02-03 | FR-02 | Integration (timeout → exit 4) | `tests/test_fr02_timeout.py` | NOT_STARTED |
| AC-FR02-04 | FR-02 | Unit (tail truncation 2000 chars) | `tests/test_fr02_tail.py` | NOT_STARTED |
| AC-FR02-05 | FR-02 | Unit (duration_ms non-negative int) | `tests/test_fr02_result.py` | NOT_STARTED |
| AC-FR02-06 | FR-02 | Unit (finished_at recorded) | `tests/test_fr02_result.py` | NOT_STARTED |
| AC-FR02-07 | FR-02 | Integration (failed retry) | `tests/test_fr02_retry.py` | NOT_STARTED |
| AC-FR02-08 | FR-02 | Integration (timeout retry) | `tests/test_fr02_retry.py` | NOT_STARTED |
| AC-FR02-09 | FR-02 | Unit (no bare except, exit 1) | `tests/test_fr02_exception.py` | NOT_STARTED |
| AC-FR02-10 | FR-02 / NFR-02 | Static grep (no shell=True) | `tests/test_nfr02_no_shell.py` | NOT_STARTED |
| AC-FR03-01 | FR-03 | CLI round-trip | `tests/test_fr03_submit.py` | NOT_STARTED |
| AC-FR03-02 | FR-03 | CLI status valid | `tests/test_fr03_status.py` | NOT_STARTED |
| AC-FR03-03 | FR-03 | CLI status unknown → exit 2 | `tests/test_fr03_status.py` | NOT_STARTED |
| AC-FR03-04 | FR-03 | CLI list format | `tests/test_fr03_list.py` | NOT_STARTED |
| AC-FR03-05 | FR-03 | CLI list empty store | `tests/test_fr03_list.py` | NOT_STARTED |
| AC-FR03-06 | FR-03 | CLI clear empties store | `tests/test_fr03_clear.py` | NOT_STARTED |
| AC-FR03-07 | FR-03 | CLI --json single-line | `tests/test_fr03_json.py` | NOT_STARTED |
| AC-FR03-08 | FR-03 | CLI exit code table | `tests/test_fr03_exit_codes.py` | NOT_STARTED |
| AC-NFR01-01 | NFR-01 | Benchmark (p95 < 50ms) | `tests/bench/test_nfr01_perf.py` | NOT_STARTED |
| AC-NFR01-02 | NFR-01 | Benchmark (reproducible script) | `tests/bench/benchmark_subprocess.py` | NOT_STARTED |
| AC-NFR02-01 | NFR-02 | Codebase grep | `tests/test_nfr02_no_shell.py` | NOT_STARTED |
| AC-NFR02-02 | NFR-02 | Unit (7 blacklist test cases) | `tests/test_nfr02_blacklist.py` | NOT_STARTED |
| AC-NFR02-03 | NFR-02 | Static analysis / architecture | `tests/test_nfr02_no_shell.py` | NOT_STARTED |
| AC-NFR03-01 | NFR-03 | Integration (atomic write) | `tests/test_nfr03_atomic.py` | NOT_STARTED |
| AC-NFR03-02 | NFR-03 | Unit (sk- redaction) | `tests/test_nfr03_redact.py` | NOT_STARTED |
| AC-NFR03-03 | NFR-03 | Unit (token= redaction) | `tests/test_nfr03_redact.py` | NOT_STARTED |
| AC-NFR03-04 | NFR-03 | Unit (non-matching preserved) | `tests/test_nfr03_redact.py` | NOT_STARTED |
| AC-NFR03-05 | NFR-03 | Integration (no silent rebuild) | `tests/test_fr01_corruption.py` | NOT_STARTED |

**AC total**: 36 testable acceptance criteria (AC-FR01: 9; AC-FR02: 10; AC-FR03: 8; AC-NFR01: 2; AC-NFR02: 3; AC-NFR03: 5).

---

## 5. Architecture Constraint Tracking

| Constraint ID | Source | Enforced By | Status |
|---------------|--------|-------------|--------|
| `no_shell_true` | project CLAUDE.md | NFR-02 (AC-NFR02-01, AC-NFR02-03); FR-02 (AC-FR02-10) | NOT_STARTED |
| `atomic_writes_only` | project CLAUDE.md | FR-01 (AC-FR01-08); NFR-03 (AC-NFR03-01, AC-NFR03-05) | NOT_STARTED |

---

## 6. High-Risk Module Tracking

| Module | Risk Class | Owner Phase | Defenses Required |
|--------|------------|-------------|-------------------|
| `taskq.executor` | HIGH | P3 | FR-02 execution path; no `shell=True`; subprocess timeout; auto-retry; tail truncation |
| `taskq.store` | HIGH | P3 | FR-01 + NFR-03 atomic write; corruption detection; secret redaction |

---

## 7. Cross-Reference Map

```
FR-01 ──► AC-FR01-01..09
   └─► AC-NFR02-02 (blacklist coverage)
   └─► AC-FR01-09 ──► AC-NFR03-05 (no silent rebuild)
FR-02 ──► AC-FR02-01..10
   └─► AC-FR02-10 ──► AC-NFR02-01/03 (no shell=True)
FR-03 ──► AC-FR03-01..08
NFR-01 ──► AC-NFR01-01..02
NFR-02 ──► AC-NFR02-01..03
   └─► AC-NFR02-02 ──► AC-FR01-05 (blacklist enforcement)
NFR-03 ──► AC-NFR03-01..05
   └─► AC-NFR03-05 ──► AC-FR01-09 (no silent rebuild)
```

---

## 8. Completeness Validation

| Check | Expected | Actual | Pass |
|-------|----------|--------|------|
| FRs in SRS.md (FR-01..FR-03) tracked | 3 | 3 | YES |
| NFRs in SRS.md (NFR-01..NFR-03) tracked | 3 | 3 | YES |
| Total ACs transcribed | 36 | 36 | YES |
| Env vars tracked | 3 | 3 | YES |
| Architecture constraints tracked | 2 | 2 | YES |
| High-risk modules tracked | 2 | 2 | YES |
| Deferred items (FR-XX-deferred / NFR-99) | 0 | 0 | YES |
| Prompt-injection patterns flagged | 0 | 0 | YES |

**Validation result**: PASS. No gaps detected between SRS.md and this tracking matrix.

---

## 9. Status Legend

| Status | Meaning |
|--------|---------|
| `NOT_STARTED` | Downstream sub-task has not yet begun work on this item |
| `IN_PROGRESS` | Active implementation or test authoring |
| `PASS` | All ACs verified, gate score recorded |
| `FAIL` | One or more ACs failing; requires remediation |
| `BLOCKED` | Dependency on another FR/NFR not yet resolved |
| `DEFERRED` | Explicitly pushed to a future SPEC revision (none in v2.0.0) |

---

## 10. Open Issues Carried Forward

None. SRS.md §7 confirms 0 TBD/TODO markers, 0 NFR-99 slots, 0 FR-XX-deferred slots.

The two interpretation risks recorded in SRS.md §8 (R4 boundary semantics, R5 retry counter visibility) are **resolved by adopted AC** (AC-FR01-03/04 inclusive; AC-FR02-07/08 final-attempt-persisted). No action items outstanding.

---

## 11. Hand-off Summary to Phase 2

- **3 FRs** requiring architecture decomposition → Phase 2 (Architecture)
- **3 NFRs** requiring measurement/monitoring strategy → Phase 2 + Phase 5
- **3 env vars** requiring config module design → Phase 3 (`taskq.config`)
- **36 ACs** requiring test coverage → Phase 3/4
- **2 high-risk modules** (`taskq.executor`, `taskq.store`) requiring security review focus → Phase 6
- **0 deferred items** → no carry-over to future rounds

*End of SPEC_TRACKING — Round 1*