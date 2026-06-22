# TRACEABILITY_MATRIX.md

> Requirements Traceability Matrix
> Framework: harness-methodology
> Version: v1.0
> Source of Truth: SPEC.md (project root) — INGESTION MODE.

---

## Overview

Provides complete **FR -> SRS -> Code -> Test** bidirectional traceability supporting ASPICE SWE.3/SYS.4 compliance for the `taskq` project. Code paths below are *planned* module references derived from SPEC.md section 6 (folder structure); tests are planned by SPEC.md section 8 acceptance items.

---

## FR <-> Spec Mapping

| FR ID | Functional Requirement | SRS Section | Priority | Status |
|-------|----------------------|-------------|----------|--------|
| FR-01 | Task submission and validation | SRS §2 / SPEC §3 FR-01 | HIGH | DRAFT |
| FR-02 | Task executor (subprocess, state machine, --all concurrency) | SRS §2 / SPEC §3 FR-02 | HIGH | DRAFT |
| FR-03 | Retry + circuit breaker | SRS §2 / SPEC §3 FR-03 | HIGH | DRAFT |
| FR-04 | Result TTL cache | SRS §2 / SPEC §3 FR-04 | MEDIUM | DRAFT |
| FR-05 | CLI integration (subcommands, --json, exit codes) | SRS §2 / SPEC §3 FR-05 | HIGH | DRAFT |
| NFR-01 | Performance: submit+status p95 < 50ms (100 iter) | SRS §3 / SPEC §4 NFR-01 | HIGH | DRAFT |
| NFR-02 | Security: shell=True forbidden; injection-char blacklist tested | SRS §3 / SPEC §4 NFR-02 | HIGH | DRAFT |
| NFR-03 | Reliability: atomic write + JSON-after-interrupt + breaker recovery | SRS §3 / SPEC §4 NFR-03 | HIGH | DRAFT |
| NFR-04 | Security: secret redaction in stdout_tail/stderr_tail | SRS §3 / SPEC §4 NFR-04 | HIGH | DRAFT |
| NFR-05 | Maintainability: docstring + [FR-XX] reference | SRS §3 / SPEC §4 NFR-05 | MEDIUM | DRAFT |
| NFR-06 | Deployability: TASKQ_* env vars + .env.example (8 entries) | SRS §3 / SPEC §4 NFR-06 | MEDIUM | DRAFT |

---

## Spec <-> Code Mapping

> Code modules are derived from SPEC.md section 6 (`src/taskq/` folder structure).
> Status is DRAFT until P2 implementation produces real file paths.

| FR / NFR | Code File | Function/Class | Lines | Status |
|----------|-----------|----------------|-------|--------|
| FR-01 | src/taskq/cli.py | submit_cmd | TBD | DRAFT |
| FR-01 | src/taskq/store.py | add_task | TBD | DRAFT |
| FR-01 | src/taskq/executor.py | _validate_command | TBD | DRAFT |
| FR-01 | src/taskq/models.py | Task, TaskStatus | TBD | DRAFT |
| FR-02 | src/taskq/executor.py | run_task | TBD | DRAFT |
| FR-02 | src/taskq/executor.py | run_all | TBD | DRAFT |
| FR-02 | src/taskq/store.py | add_task (Lock) | TBD | DRAFT |
| FR-03 | src/taskq/breaker.py | Breaker, BreakerState | TBD | DRAFT |
| FR-03 | src/taskq/executor.py | run_task (retry/backoff) | TBD | DRAFT |
| FR-04 | src/taskq/cache.py | signature, get, set | TBD | DRAFT |
| FR-04 | src/taskq/executor.py | run_task (--cached branch) | TBD | DRAFT |
| FR-05 | src/taskq/cli.py | main, submit_cmd, run_cmd, status_cmd, list_cmd, clear_cmd | TBD | DRAFT |
| FR-05 | src/taskq/__main__.py | module entry point (python -m taskq) | TBD | DRAFT |
| NFR-01 | src/taskq/store.py | add_task / get_task | TBD | DRAFT |
| NFR-02 | (audit) | grep guard for `shell=True` | TBD | DRAFT |
| NFR-03 | src/taskq/store.py | atomic_write | TBD | DRAFT |
| NFR-03 | src/taskq/breaker.py | atomic_write (breaker.json) | TBD | DRAFT |
| NFR-04 | src/taskq/executor.py | redact (regex apply) | TBD | DRAFT |
| NFR-05 | src/taskq/*.py | docstring [FR-XX] | TBD | DRAFT |
| NFR-06 | src/taskq/config.py | TASKQ_* reader | TBD | DRAFT |
| NFR-06 | .env.example | 8 env entries | TBD | DRAFT |

---

## Code <-> Test Mapping

> Tests are planned from SPEC.md section 8 acceptance items; files are TBD until P2.

| FR / NFR | Code File | Test File | Coverage | Status |
|----------|-----------|-----------|----------|--------|
| FR-01 | src/taskq/cli.py:submit_cmd | tests/test_submit_validation.py | TBD | DRAFT |
| FR-02 | src/taskq/executor.py:run_task | tests/test_executor_state_machine.py | TBD | DRAFT |
| FR-02 | src/taskq/executor.py:run_all | tests/test_run_all_concurrency.py | TBD | DRAFT |
| FR-03 | src/taskq/breaker.py | tests/test_breaker_fsm.py | TBD | DRAFT |
| FR-03 | src/taskq/executor.py (retry) | tests/test_retry_backoff.py | TBD | DRAFT |
| FR-04 | src/taskq/cache.py | tests/test_cache_ttl.py | TBD | DRAFT |
| FR-05 | src/taskq/cli.py | tests/test_cli_exit_codes.py | TBD | DRAFT |
| NFR-01 | src/taskq/store.py | tests/bench/test_bench_submit_status.py | TBD | DRAFT |
| NFR-02 | (audit) | tests/audit/test_no_shell_true.py | TBD | DRAFT |
| NFR-03 | src/taskq/store.py | tests/test_atomic_write_crash.py | TBD | DRAFT |
| NFR-04 | src/taskq/executor.py:redact | tests/test_redaction.py | TBD | DRAFT |
| NFR-05 | src/taskq/*.py | tests/lint/test_docstring_fr_refs.py | TBD | DRAFT |
| NFR-06 | src/taskq/config.py | tests/test_config_env.py | TBD | DRAFT |
| NFR-06 | .env.example | tests/test_env_example_complete.py | TBD | DRAFT |

---

## Completeness Verification

| Check | Target | Actual | Status |
|-------|--------|--------|--------|
| FR -> SRS mapping | 100% | 11/11 (FR-01..05 + NFR-01..06) | DRAFT |
| SRS -> Code mapping | 100% | 0% (P1 — code paths planned only) | DRAFT |
| Code -> Test mapping | 100% | 0% (P1 — tests planned only) | DRAFT |
| Test coverage | >=80% (P3: >=70%) | TBD | DRAFT |

---

## ASPICE Compliance

| ASPICE Capability | Status |
|-------------------|--------|
| SWE.3.B.SP1 Task-to-work-product traceability | DRAFT (matrix populated; code/test paths planned) |
| SWE.3.B.SP2 Bidirectional traceability | DRAFT (FR <-> Spec + Spec <-> Code + Code <-> Test sections present) |
| SWE.3.B.SP3 Traceability consistency | DRAFT (will be re-verified at P2/P3 handoff) |
