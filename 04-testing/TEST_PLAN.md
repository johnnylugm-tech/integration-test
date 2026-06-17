# Phase 4 — TEST_PLAN

> **Generated**: 2026-06-18
> **Phase**: 4 — Testing
> **Source**: SRS.md (3 FRs + 3 NFRs)

## Overview

Test plan covers FR-01 (task submission), FR-02 (task execution + retry), FR-03 (CLI + queries),
plus NFR-01 (performance), NFR-02 (security), NFR-03 (error handling / reliability).

| FR ID | Title | Module | Existing Tests |
|-------|-------|--------|----------------|
| FR-01 | Task model + persistence | `taskq.store` / `taskq.cli` | `test_fr01.py` (32 tests) |
| FR-02 | Task execution + retry | `taskq.executor` / `taskq.cli` | `test_fr02.py` (43 tests) |
| FR-03 | CLI + queries | `taskq.cli` | `test_fr03.py` (39 tests) |

## Test Categories per FR

### FR-01: Task Submission

**Positive cases:**
- Submit simple command (`echo hi`) → task id is 8 hex chars, status=pending
- Submit long but valid command → accepted, persisted
- Idempotent: same command → different task id (uuid uniqueness)

**Negative cases:**
- Empty command → exit 2
- Whitespace-only command → exit 2
- Command exceeds length limit → exit 2
- Command with injection chars (`; | & $ > < \``) → exit 2 (NFR-02)
- Invalid TASKQ_HOME (parent not writable) → graceful error

**Boundary / Edge:**
- Concurrent submits (no race condition on tasks.json)
- tasks.json corrupted (not parseable JSON) → exit 1 (no silent rebuild, SRS §1.3)

### FR-02: Task Execution

**Positive:**
- Run pending task → status done, exit_code=0, tails populated, duration_ms > 0
- State machine: pending → running → done (verified via transitions)

**Negative:**
- Run unknown task id → exit 2
- Run already-done task → exit 2 (invalid transition)
- Timeout (command sleeps > TASKQ_TIMEOUT) → exit 4, status=timeout, retry

**Retry logic:**
- Failed (non-zero exit): retries up to TASKQ_RETRY_LIMIT times → final status=failed
- Timeout: retries up to TASKQ_RETRY_LIMIT times → final status=timeout
- Retry limit env var (TASKQ_RETRY_LIMIT) overrides default

**Boundary:**
- stdout > 2000 chars → truncated to last 2000 (FR-02 tail invariant)
- stderr > 2000 chars → truncated to last 2000
- Orphan cleanup: pid file removed on success/failure (NFR-15)

### FR-03: CLI + Queries

**Subcommands (happy):**
- `submit` → task id printed, exit 0
- `run` → status printed, exit 0/4
- `status <id>` → status + fields, exit 0/2
- `list` → table of tasks, exit 0
- `clear` → tasks.json reset, exit 0

**JSON mode (`--json`):**
- All subcommands emit parseable JSON in --json mode
- Exit codes consistent (0 success, 2 invalid input, 4 timeout, 1 corruption)

**Redaction (NFR-03):**
- Secret-bearing stdout lines (sk-..., Bearer ...) → redacted before persist
- Secret-bearing stderr lines → redacted before persist
- Secret never reaches tasks.json on disk

### NFR-01: Performance

- `submit + status` 100 cycles → p95 < 50ms
- Excludes subprocess invocation (in-process benchmark)

### NFR-02: Security

- No `shell=True` anywhere in codebase (bandit / semgrep verified)
- Injection chars rejected (FR-01 covers)

### NFR-03: Reliability / Error Handling

- Atomic write (tmp + os.replace) — no partial tasks.json on crash
- Secret redaction before persist (FR-03 covers)
- Concurrent writes don't corrupt tasks.json

## Test Execution Strategy

1. Run pytest per FR (test_fr01.py, test_fr02.py, test_fr03.py)
2. Run mutation testing (already passed at 70.5% in Gate 2)
3. Run coverage (already at 100% in Gate 2)
4. Run adversarial bug-hunt (Step 4b) — framework-owned

## Acceptance

Gate 3 (Phase 4 exit) requires:
- All 16 dimensions ≥ threshold
- composite_score ≥ 80
- bug_hunt_report.json present with all critical/high resolved or refuted
- Gate 3 finalize → advance to Phase 5