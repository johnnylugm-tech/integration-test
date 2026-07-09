# Traceability Matrix — taskq

> Bidirectional trace: `SRS.md` FR/NFR → Acceptance Criteria → owning
> design element (module, per `SPEC_TRACKING.md` §5 ownership — Phase 2
> has not yet produced `SAD.md`/`ADR.md`, so the design-element column
> is the SRS.md §2 module layout) → test case (proposed ID, to be
> materialized in the sibling `TEST_INVENTORY.yaml`). `SRS.md` and
> `SPEC_TRACKING.md` are APPROVED and not modified by this document.

---

## 1. Purpose

Answer, per acceptance criterion: *which module implements it, and
which test case verifies it.* This closes the loop AC → design → test
so Phase 2 (`TEST_SPEC.md`) and Phase 4 (`TEST_PLAN.md`) have a single
source to derive from, and so coverage gaps (an AC with no test case)
are visible before design begins.

Test case IDs below are **proposed** (`TC-<FR/NFR-ID>-<seq>`) — no
test code exists yet at this phase. The bracketed pytest-style name is
a naming suggestion for the eventual `TEST_INVENTORY.yaml` entry and
Phase 3 implementation, consistent with `test_fr01_...` / cross-cutting
naming.

---

## 2. FR Traceability Matrix

| AC ID | Requirement (summary) | Design Element (module) | Test Case ID | Exit Code | Data File |
|---|---|---|---|---|---|
| AC-FR-01-1 | Empty/whitespace command → reject, no write | `store.py`, `cli.py` | TC-FR-01-1 `test_fr01_empty_command_exit2` | 2 | tasks.json |
| AC-FR-01-2 | Command > 1000 chars → reject | `store.py`, `cli.py` | TC-FR-01-2 `test_fr01_command_too_long_exit2` | 2 | tasks.json |
| AC-FR-01-3 | Injection char (`;\|&$><`` ` ``) → reject | `store.py`, `cli.py` | TC-FR-01-3 `test_fr01_injection_char_exit2` | 2 | tasks.json |
| AC-FR-01-4 | `--name` collides with pending/running → reject | `store.py`, `cli.py` | TC-FR-01-4 `test_fr01_duplicate_name_exit2` | 2 | tasks.json |
| AC-FR-01-5 | Valid submit → exit 0, 8-hex id, status pending | `store.py`, `cli.py` | TC-FR-01-5 `test_fr01_valid_submit_pending` | 0 | tasks.json |
| AC-FR-01-6 | `--json` → single-line JSON | `cli.py` | TC-FR-01-6 `test_fr01_json_output_single_line` | 0 | tasks.json |
| AC-FR-02-1 | `subprocess.run` + `shlex.split`, never `shell=True` | `executor.py` | TC-FR-02-1 `test_fr02_no_shell_true` | — | — |
| AC-FR-02-2 | exit0→done, non-0→failed, `TimeoutExpired`→timeout | `executor.py` | TC-FR-02-2 `test_fr02_status_transitions` | 0/4 | tasks.json |
| AC-FR-02-3 | Result fields: exit_code/stdout_tail/stderr_tail/duration_ms/finished_at | `executor.py` | TC-FR-02-3 `test_fr02_result_fields_present` | 0 | tasks.json |
| AC-FR-02-4 | `run --all` concurrent, Lock-protected write (see AC-NFR-03-1) | `executor.py`, `store.py` (high-risk) | TC-FR-02-4 `test_fr02_run_all_concurrent_lock` | 0 | tasks.json |
| AC-FR-02-5 | Single-task timeout → exit 4 | `executor.py` | TC-FR-02-5 `test_fr02_single_timeout_exit4` | 4 | tasks.json |
| AC-FR-03-1 | Auto-retry failed/timeout up to `TASKQ_RETRY_LIMIT`, injectable backoff | `executor.py` (high-risk), `breaker.py` | TC-FR-03-1 `test_fr03_retry_up_to_limit` | — | — |
| AC-FR-03-2 | Consecutive final failures ≥ `TASKQ_BREAKER_THRESHOLD` → OPEN | `breaker.py` | TC-FR-03-2 `test_fr03_breaker_opens_at_threshold` | — | breaker.json |
| AC-FR-03-3 | OPEN → run exit 3, stderr `breaker open`, no subprocess | `breaker.py`, `executor.py` | TC-FR-03-3 `test_fr03_open_rejects_exit3` | 3 | breaker.json |
| AC-FR-03-4 | Cooldown → HALF_OPEN; success→CLOSED, failure→OPEN | `breaker.py` | TC-FR-03-4 `test_fr03_half_open_recovery` | — | breaker.json |
| AC-FR-03-5 | Breaker state atomic write | `breaker.py` | TC-FR-03-5 `test_fr03_breaker_atomic_write` | — | breaker.json |
| AC-FR-04-1 | Cache signature = `sha256(command)` | `cache.py` | TC-FR-04-1 `test_fr04_cache_signature_sha256` | — | cache.json |
| AC-FR-04-2 | TTL-valid `done` replay, no subprocess, `cached: true` | `cache.py`, `executor.py` | TC-FR-04-2 `test_fr04_cache_replay_no_subprocess` | 0 | cache.json |
| AC-FR-04-3 | Expired/absent cache → normal execution, write on success | `cache.py` | TC-FR-04-3 `test_fr04_cache_miss_writes_on_success` | 0 | cache.json |
| AC-FR-04-4 | cache.json atomic + thread-safe | `cache.py` | TC-FR-04-4 `test_fr04_cache_atomic_thread_safe` | — | cache.json |
| AC-FR-05-1 | submit/run/status/list/clear as argparse subcommands | `cli.py` | TC-FR-05-1 `test_fr05_subcommands_registered` | — | — |
| AC-FR-05-2 | `status <id>` outputs all fields | `cli.py` | TC-FR-05-2 `test_fr05_status_all_fields` | 0 | tasks.json |
| AC-FR-05-3 | `list [--status S]` filters | `cli.py` | TC-FR-05-3 `test_fr05_list_filter_by_status` | 0 | tasks.json |
| AC-FR-05-4 | `clear` empties all data files | `cli.py` | TC-FR-05-4 `test_fr05_clear_all_data_files` | 0 | tasks.json, breaker.json, cache.json |
| AC-FR-05-5 | `--json` → single-line JSON (global flag) | `cli.py` | TC-FR-05-5 `test_fr05_global_json_flag` | 0 | — |
| AC-FR-05-6 | Exit codes 0/2/3/4/1 map precisely | `cli.py` | TC-FR-05-6 `test_fr05_exit_code_matrix` | 0,1,2,3,4 | — |
| AC-FR-05-7 | Unknown task id → exit 2 | `cli.py` | TC-FR-05-7 `test_fr05_unknown_id_exit2` | 2 | tasks.json |

---

## 3. NFR Traceability Matrix

| AC ID | Requirement (summary) | Design Element (module) | Test Case ID | Measurement |
|---|---|---|---|---|
| AC-NFR-01-1 | `submit`+`status` p95 < 50ms / 100 iter | `store.py`, `cli.py` | TC-NFR-01-1 `test_nfr01_submit_status_p95_latency` | pytest-benchmark |
| AC-NFR-02-1 | `shell=True` usage = 0 (whole codebase) | `executor.py` | TC-NFR-02-1 `test_nfr02_no_shell_true_grep` | CI gate / grep |
| AC-NFR-02-2 | Injection blacklist test coverage | `executor.py` | TC-NFR-02-2 `test_nfr02_injection_blacklist_covered` | unit test |
| AC-NFR-03-1 | Atomic write; valid JSON post-crash | `store.py`, `breaker.py`, `cache.py` | TC-NFR-03-1 `test_nfr03_atomic_write_fault_injection` | fault-injection + json.load |
| AC-NFR-03-2 | Breaker recovery time ≤ cooldown + 1s | `breaker.py` | TC-NFR-03-2 `test_nfr03_breaker_recovery_time` | integration test |
| AC-NFR-04-1 | Secret redaction 100% hit rate | `executor.py` | TC-NFR-04-1 `test_nfr04_secret_redaction_hit_rate` | unit test on stdout_tail |
| AC-NFR-05-1 | Docstring `[FR-XX]` coverage 100% (public) | all `src/taskq/*` | TC-NFR-05-1 `test_nfr05_docstring_fr_ref_coverage` | Gate 1 inspect |
| AC-NFR-06-1 | 8 `TASKQ_*` vars read from env, with defaults | `config.py` | TC-NFR-06-1 `test_nfr06_env_vars_have_defaults` | unit test |
| AC-NFR-06-2 | `.env.example` declares all 8, with comments | `config.py` | TC-NFR-06-2 `test_nfr06_env_example_completeness` | file inspection |

---

## 4. Reverse Trace — Module → Requirements → Tests

| Module | FR/NFR Owned | Test Case IDs |
|---|---|---|
| `store.py` (high-risk) | FR-01, FR-02, NFR-01, NFR-03 | TC-FR-01-1..6, TC-FR-02-4, TC-NFR-01-1, TC-NFR-03-1 |
| `executor.py` (high-risk) | FR-02, FR-03, NFR-02, NFR-04 | TC-FR-02-1..5, TC-FR-03-1/3, TC-NFR-02-1..2, TC-NFR-04-1 |
| `breaker.py` | FR-03, NFR-03 | TC-FR-03-2..5, TC-NFR-03-1, TC-NFR-03-2 |
| `cache.py` | FR-04, NFR-03 | TC-FR-04-1..4, TC-NFR-03-1 |
| `cli.py` | FR-01, FR-05, NFR-01 | TC-FR-01-1/2/3/4/6, TC-FR-05-1..7, TC-NFR-01-1 |
| `config.py` | NFR-06 | TC-NFR-06-1..2 |
| `models.py` | NFR-05 | TC-NFR-05-1 |
| `__main__.py` | NFR-05 | TC-NFR-05-1 |

---

## 5. Coverage Validation

- **AC count**: 27 FR ACs (6+5+5+4+7 per `SRS.md` §5) + 9 NFR ACs
  (1+2+2+1+1+2) = **36 total ACs**.
- **Test case rows produced**: 27 FR + 9 NFR = **36**, one proposed
  test case ID per AC — 1:1 coverage, no AC left untraced.
- **Orphan check**: every module listed in `SPEC_TRACKING.md` §5
  (`store.py`, `executor.py`, `breaker.py`, `cache.py`, `cli.py`,
  `config.py`, `models.py`, `__main__.py`) appears in §4 above; no
  module is untraced to an FR/NFR.
- **High-risk module double-check**: `executor.py` and `store.py`
  (SRS.md §2 "high-risk") each carry ≥ 4 test case IDs, consistent
  with the per-module TDD requirement (SRS.md §2, canonical §6/§10).

---

## 6. Status

This matrix is produced at Phase 1 (Requirements) before design or
test code exist — all test case IDs are **proposed, not yet
implemented**. Actual test files, fixtures, and pass/fail status are
recorded in Phase 2's `TEST_SPEC.md` (design-time case derivation) and
Phase 4's `TEST_PLAN.md` / `TEST_RESULTS.md` (execution-time results).
`SPEC_TRACKING.md` §6 records this document as consumed alongside
`TEST_INVENTORY.yaml` (sibling sub-task, same stage).

---

## 7. Open Items

- No gaps found: 36/36 ACs have a corresponding design element and
  proposed test case ID (§5).
- Downstream phases (`SAD.md`, `ADR.md`, `TEST_SPEC.md`) may refine
  the module-to-AC mapping once component boundaries are finalized;
  this matrix reflects the SRS.md §2 module layout only.

---

*Source: `SRS.md` (approved), `SPEC_TRACKING.md` (approved). Agent A,
Sub-Task 3/4, Round 1.*
