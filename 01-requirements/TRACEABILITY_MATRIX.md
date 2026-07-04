# Traceability Matrix — taskq

> Requirements ↔ Design ↔ Code ↔ Test **bidirectional** traceability matrix.
>
> - **Project**: `taskq` (local task queue CLI; Python 3.11 stdlib-only at runtime)
> - **Framework**: harness-methodology v2.9 (ASPICE SWE.3 / SYS.4 alignment)
> - **Source of Truth**: `01-requirements/SRS.md` (APPROVED, INGESTION MODE from `SPEC.md` v3.0.0 2026-07-04)
> - **Companion matrix**: `01-requirements/SPEC_TRACKING.md` (per-row status / owner / Decision Framework — APPROVED for Round 1)
> - **Matrix version**: 1.0 (Round 1, 2026-07-04)
> - **Owner**: Requirements Engineer (Agent A) for Phase 1; downstream Phase 2–8 agents re-render rows as they promote `APPROVED → DESIGNED → IMPLEMENTED → TESTED → VERIFIED → ACCEPTED`.

---

## 0. Matrix Scope and Conventions

### 0.1 Scope (Round 1)

This Round 1 matrix covers the **planned** traceability for Phase 1 — `src/` and `tests/` directories do not yet exist on disk (this project is at Phase 1 Requirements; no P3 implementation has landed). All `Code File` / `Test File` cells are therefore **planned** locations derived from:

- `SPEC.md` §6 Module Layout
- `01-requirements/SRS.md` §2.7 Module Layout (verbatim from SPEC.md §6)
- `01-requirements/SPEC_TRACKING.md` per-FR Owner column
- `01-requirements/SRS.md` Appendix A FR Block (machine-readable)
- `TEST_INVENTORY.yaml` naming authority

Downstream Phase 2 (architecture), Phase 3 (implementation), and Phase 4 (testing) agents will **re-render** the planned rows with concrete paths once files land on disk and tests pass.

### 0.2 Conventions

| Convention | Meaning |
|------------|---------|
| **Link direction** | Bidirectional: FR ↔ Spec ↔ Code ↔ Test. Each row carries the forward link (`→`) and a back-reference column (`←`) so any row can be traced in either direction. |
| **Status legend** | `PLANNED` (Phase 1, this matrix) → `DESIGNED` (P2) → `IMPLEMENTED` (P3) → `TESTED` (P4) → `VERIFIED` (P5) → `ACCEPTED` (Gate 1 close). |
| **Priority** | `HIGH` / `MEDIUM` / `LOW` — carries forward from `SPEC_TRACKING.md` and `PROJECT_BRIEF.md`. |
| **High-risk module flag** | `executor` and `store` are framework-classified high-risk per `SPEC.md` §10 + `harness/CLAUDE.md`; rows anchored to them get the `[HIGH-RISK]` marker. |
| **Cross-cutting NFR** | NFR-02 / NFR-03 / NFR-05 / NFR-06 cross-cut multiple FRs; each cross-cut is enumerated as a separate row in §3 / §4 below (not collapsed) so the bidirectional link is auditable. |
| **Open issues** | NFR-99-a and NFR-99-b are unresolved ambiguity issues carried over from `SPEC_TRACKING.md` §Open Issues — flagged inline at the affected rows. |
| **Status scope reconciliation** | `SPEC_TRACKING.md` rows start at `APPROVED` (the canonical requirement text is already approved at SRS ratification). This matrix's rows and `TEST_INVENTORY.yaml` rows start at `PLANNED` (the code and test artefacts do not yet exist on disk at Phase 1). Both legends converge on the same `DESIGNED → IMPLEMENTED → TESTED → VERIFIED → ACCEPTED` downstream ladder once P2+ phases begin. The two starting points are not a contradiction — they track different artefacts (approved requirement text vs planned code/test trace). |

### 0.3 Completeness Targets

| Check | Target | Round 1 Actual | Status |
|-------|--------|----------------|--------|
| FR ↔ SRS mapping coverage | 100% (5/5 FRs) | 5/5 | OK |
| NFR ↔ SRS mapping coverage | 100% (6/6 NFRs) | 6/6 | OK |
| FR ↔ planned code mapping | 100% (5/5 FRs have ≥1 owner module) | 5/5 | OK |
| FR ↔ planned test mapping | 100% (5/5 FRs have Decision Framework entry) | 5/5 | OK |
| AC ↔ test mapping coverage | 100% (30 ACs total: 5+5+5+4+3=22 FR ACs + 1+2+2+1+1+1=8 NFR ACs = 30) | 30/30 | OK |
| Acceptance Items (10/10) ↔ FR/NFR | 100% | 10/10 | OK |
| Risks (5/5) ↔ FR/NFR | 100% | 5/5 | OK |
| Open Issues (2/2) carried forward | 100% | 2/2 | OK |
| High-risk modules flagged in code rows | 100% (executor + store) | 2/2 | OK |
| H1 anchor matches loader phrase | `Traceability Matrix` | yes | OK |

---

## 1. Functional Requirement ↔ Spec Mapping

> **Forward** link: each FR anchors to one §3 subsection in `SRS.md` (verbatim from `SPEC.md` §3) and to its Acceptance Criteria.
> **Back-reference** (`←` column) shows where the same FR is cited by downstream artifacts (CLI exit-code table, AC items, risk rows).

| FR ID | Functional Requirement (verbatim title) | SRS § | ACs | Priority | High-risk Module | Status | ← Back-references |
|-------|------------------------------------------|-------|-----|----------|------------------|--------|-------------------|
| FR-01 | 任務提交與驗證 (`taskq submit "<cmd>"` with empty/length/injection/name-unique validation; uuid4-first-8 task id; atomic write; exit 2 on validation fail) | §3 FR-01 | AC-FR-01-01..05 | HIGH | `store.py` [HIGH-RISK] | PLANNED | SRS §2.6; §3 FR-01; §5 AC #2/#3/#4; §8 R1; SPEC_TRACKING §FR-01; SPEC.md §3 FR-01 + §7 + §10; PROJECT_BRIEF FR-01 |
| FR-02 | 任務執行器 (`taskq run <id>` / `run --all` via `subprocess.run(shlex.split, …, timeout=TASKQ_TASK_TIMEOUT)`; status machine `pending → running → done/failed/timeout`; tail-2000 stdout/stderr; `ThreadPoolExecutor`; single-task timeout → exit 4) | §3 FR-02 | AC-FR-02-01..05 | HIGH | `executor.py` [HIGH-RISK] | PLANNED | SRS §2.6; §3 FR-02; §5 AC #2/#5/#9; §8 R2; SPEC_TRACKING §FR-02; SPEC.md §3 FR-02 + §7 + §10 |
| FR-03 | 重試與斷路器 (exponential backoff `TASKQ_BACKOFF_BASE × 2^n`, cap `TASKQ_RETRY_LIMIT`, injectable sleep; circuit breaker `CLOSED/OPEN/HALF_OPEN`; threshold `TASKQ_BREAKER_THRESHOLD`; cooldown `TASKQ_BREAKER_COOLDOWN`; persisted to `$TASKQ_HOME/breaker.json`; OPEN → exit 3 + `breaker open`, no subprocess) | §3 FR-03 | AC-FR-03-01..05 | HIGH | `executor.py` + `breaker.py` [HIGH-RISK partial] | PLANNED | SRS §3 FR-03; §5 AC #6; §7 NFR-99-b (open issue anchor); §8 R3; SPEC_TRACKING §FR-03 |
| FR-04 | 結果 TTL 快取 (signature = `sha256(command)`; `run <id> --cached` replays `done` result within `TASKQ_CACHE_TTL` — no subprocess; expired/missing → normal execution + cache write; atomic + thread-safe read/write) | §3 FR-04 | AC-FR-04-01..04 | HIGH | `cache.py` | PLANNED | SRS §3 FR-04; §5 AC #7; §8 R4; SPEC_TRACKING §FR-04; SPEC.md §5.2 |
| FR-05 | CLI 整合 (argparse subcommands `submit`/`run`/`status`/`list`/`clear`; global `--json`; 5 exit codes `0/1/2/3/4`) | §3 FR-05 | AC-FR-05-01..03 | HIGH | `cli.py` + `__main__.py` | PLANNED | SRS §3 FR-05; §5 AC #1/#2/#3/#5; SPEC_TRACKING §FR-05; SPEC.md §7 Exit Code Map |

---

## 2. Non-Functional Requirement ↔ Spec Mapping

> **Forward** link: each NFR anchors to one row in `SRS.md` §4 (verbatim from `SPEC.md` §4) and its Acceptance Criteria.
> **Back-reference** column lists every FR that depends on or cross-cuts this NFR.

| NFR ID | Non-Functional Requirement (verbatim title) | SRS § | ACs | Priority | Verification Method (Decision Framework) | Status | ← Back-references (cross-cutting FRs) |
|--------|---------------------------------------------|-------|-----|----------|-------------------------------------------|--------|---------------------------------------|
| NFR-01 | Performance: `submit` + `status` combined (no subprocess) p95 < 50ms over 100 iterations (pytest-benchmark) | §4 NFR-01 | AC-NFR-01-01 | HIGH | pytest-benchmark suite (`tests/bench/test_bench_submit_status.py`); 100 iterations; report p95 | PLANNED | FR-01 (submit), FR-05 (status); cross-cuts via CLI exit path. **Open issue NFR-99-a** anchors here (50ms budget boundary ambiguity). |
| NFR-02 | Security (shell + injection): `shell=True` forbidden codebase-wide; FR-01 injection character blacklist must have test coverage | §4 NFR-02 | AC-NFR-02-01, AC-NFR-02-02 | HIGH | CI grep-gate (`grep -rn 'shell=True' src/ tests/` must return zero hits) + unit tests on blacklist characters | PLANNED | FR-01 (validation rules), FR-02 (subprocess invocation), FR-05 (CLI entry). Cross-cuts all subprocess paths. |
| NFR-03 | Reliability (atomic write + breaker recovery): all 3 data files written atomically (tmp + `os.replace`); breaker `OPEN → CLOSED` recovery ≤ `TASKQ_BREAKER_COOLDOWN` + 1s | §4 NFR-03 | AC-NFR-03-01, AC-NFR-03-02 | HIGH | Fault-injection crash test (kill -9 mid-write, validate JSON parse on restart) + breaker recovery timing test | PLANNED | FR-01 (atomic submit), FR-02 (concurrent `--all`), FR-03 (breaker JSON persistence), FR-04 (cache JSON). Cross-cuts all persistence paths. **Open issue NFR-99-b** anchors here. |
| NFR-04 | Security (secret redaction): `stdout_tail` / `stderr_tail` lines matching `(sk-[A-Za-z0-9_-]{8,}\|token=\S+)` replaced whole-line with `[REDACTED]` before persistence | §4 NFR-04 | AC-NFR-04-01 | HIGH | Unit tests on stdout/stderr redaction (positive + negative cases for both regex branches) | PLANNED | FR-02 (executor captures stdout/stderr), FR-04 (cache writes stdout). Cross-cuts persistence path. |
| NFR-05 | Maintainability (docstring FR-cross-ref): every public function/class in `src/taskq/` has docstring containing `[FR-XX]` reference | §4 NFR-05 | AC-NFR-05-01 | MEDIUM | Gate 1 inspect (AST scan of `src/taskq/`; assert every public symbol has docstring + matches `/\[FR-\d{2}\]/`) | PLANNED | All FRs (each public symbol cites ≥1 FR). Coverage target 100% public symbols. |
| NFR-06 | Deployability (env vars): all 8 `TASKQ_*` parameters read from env (centralized in `config.py`, with defaults); `.env.example` declares all 8 with annotations | §4 NFR-06 | AC-NFR-06-01 | MEDIUM | Env-var loading test (set/unset each var, assert default fallback) + `.env.example` lint (8 lines, each var annotated) | PLANNED | FR-02 (timeout/workers/retry/backoff), FR-03 (breaker threshold/cooldown), FR-04 (TTL). 8 vars centralized. |

---

## 3. Spec ↔ Code Mapping (PLANNED — Phase 1)

> **Forward** link: each `SRS.md` FR / NFR / AC anchors to the planned module file(s) in `src/taskq/` (per `SPEC.md` §6 module layout + `SRS.md` §2.7 + Appendix A FR Block).
> **Back-reference** column: list of FR / NFR IDs whose semantics this code element implements.

### 3.1 Per-Module Code Ownership (planned)

| SRS Anchor | Planned Code File | Symbols (planned) | Back-refs (FR/NFR) | Status | Lines | Notes |
|------------|-------------------|-------------------|--------------------|--------|-------|-------|
| §3 FR-01 + §4 NFR-03 (atomic write) | `src/taskq/store.py` **[HIGH-RISK]** | `class TaskStore`, `add_task`, `get_task`, `list_tasks`, `atomic_write_json`, `_lock` (`threading.Lock`) | FR-01, FR-02, NFR-03, R1 | PLANNED | tbd | High-risk per SPEC.md §10; per-module TDD coverage required at Gate 2 / Gate 4. Concurrent write → corruption mitigant (R1). |
| §3 FR-01 / FR-02 (data model) | `src/taskq/models.py` | `class Task`, `class TaskStatus` (enum: pending/running/done/failed/timeout), `class TaskResult` | FR-01, FR-02, FR-04 (cached marker) | PLANNED | tbd | Pure dataclasses; no I/O. |
| §3 FR-02 + FR-03 (subprocess + retry) | `src/taskq/executor.py` **[HIGH-RISK]** | `run_task`, `run_all`, `_execute_subprocess`, `_retry_loop`, `inject_sleep` | FR-02, FR-03, NFR-02 (no shell=True), R2 | PLANNED | tbd | High-risk per SPEC.md §10; sleep injection mandatory for testability (FR-03). |
| §3 FR-03 (breaker state machine) | `src/taskq/breaker.py` | `class CircuitBreaker`, `record_failure`, `record_success`, `allow_request`, `state` (CLOSED/OPEN/HALF_OPEN) | FR-03, NFR-03, R3 | PLANNED | tbd | Persists to `breaker.json`. NFR-99-b anchors here (HALF_OPEN observation). |
| §3 FR-04 (TTL cache) | `src/taskq/cache.py` | `class TTLCache`, `get`, `put`, `_signature` (sha256), `_atomic_write` | FR-04, NFR-03, R4 | PLANNED | tbd | Atomic + thread-safe write. R4 (stale replay) mitigant via TTL. |
| §4 NFR-04 (secret redaction) | `src/taskq/executor.py` (in `_execute_subprocess`) | `REDACT_PATTERN`, `redact_line` | NFR-04, R5 | PLANNED | tbd | Redaction happens before persistence (not just before display). |
| §4 NFR-06 (env var loading) | `src/taskq/config.py` | `TASKQ_HOME`, `TASKQ_MAX_WORKERS`, `TASKQ_TASK_TIMEOUT`, `TASKQ_RETRY_LIMIT`, `TASKQ_BACKOFF_BASE`, `TASKQ_BREAKER_THRESHOLD`, `TASKQ_BREAKER_COOLDOWN`, `TASKQ_CACHE_TTL` (8 module-level constants read from env, with defaults) | NFR-06 (8 vars), FR-02/03/04 (consumer) | PLANNED | tbd | Centralized per SPEC.md §2. |
| §3 FR-05 (CLI) | `src/taskq/cli.py` + `src/taskq/__main__.py` | `main`, arg-parsers for `submit`/`run`/`status`/`list`/`clear`, `_exit_code` (0/1/2/3/4), `_emit_json` | FR-05, NFR-02 (argparse injection still validated), NFR-01 (no-subprocess fast-path) | PLANNED | tbd | 5 exit codes per SPEC.md §7. |
| §3 FR-04 + NFR-04 (cache secret redaction) | `src/taskq/cache.py` (`put` calls `redact_line` on stdout_tail before persisting) | `redact_line` (imported from `executor.py` or factored to shared util) | FR-04, NFR-04, R5 | PLANNED | tbd | Cross-module dependency: `cache` imports redaction helper. |

### 3.2 Architecture Constraint Verification

| Constraint (SPEC.md §10) | Planned Enforcement | Status |
|--------------------------|--------------------|--------|
| `no_circular_dependencies` among 8 modules | Dependency DAG: `cli → executor → breaker / cache / store; cli → store; models` (no upward cycles) | PLANNED (Phase 2 will validate via `pyright` / `ruff --noqa` import-graph check) |
| High-risk module `taskq.executor` | Gate 1 + Gate 2 + Gate 4 per-module TDD coverage requirement | PLANNED |
| High-risk module `taskq.store` | Gate 1 + Gate 2 + Gate 4 per-module TDD coverage requirement | PLANNED |

---

## 4. Code ↔ Test Mapping (PLANNED — Phase 1)

> **Forward** link: each planned module maps to its planned test files (per `TEST_INVENTORY.yaml` naming authority + `SPEC_TRACKING.md` Decision Framework column + `SPEC.md` §10 framework alignment).
> **Back-reference** column: list of FR / NFR IDs verified by that test file.

### 4.1 Per-Module Planned Test Coverage

| Planned Code File | Planned Test File(s) | Test Function Names (planned) | FR/NFR Verified | Status | Coverage Target |
|-------------------|----------------------|------------------------------|------------------|--------|-----------------|
| `src/taskq/store.py` [HIGH-RISK] | `tests/test_store.py` | `test_fr01_add_task_empty_rejected` (AC-FR-01-01), `test_fr01_add_task_too_long_rejected` (AC-FR-01-02), `test_fr01_add_task_injection_chars_rejected` (AC-FR-01-03 + AC-NFR-02-02), `test_fr01_add_task_name_conflict_rejected` (AC-FR-01-04), `test_fr01_add_task_success_atomic_write` (AC-FR-01-05), `test_nfr03_atomic_write_kill9_recovery` (AC-NFR-03-01), `test_fr02_concurrent_run_all_no_loss` (AC-FR-02-04 + AC #9) | FR-01, FR-02, NFR-03 | PLANNED | ≥90% line + branch (high-risk module) |
| `src/taskq/executor.py` [HIGH-RISK] | `tests/test_executor.py` | `test_fr02_subprocess_shlex_split_no_shell_true` (AC-FR-02-01 + AC-NFR-02-01), `test_fr02_status_machine_done_failed_timeout` (AC-FR-02-02), `test_fr02_result_fields_tail_2000` (AC-FR-02-03), `test_fr02_concurrent_threadpool` (AC-FR-02-04), `test_fr02_timeout_exit_code_4` (AC-FR-02-05 + AC #5) | FR-02, NFR-02 | PLANNED | ≥90% line + branch (high-risk module) |
| `src/taskq/executor.py` (retry path) | `tests/test_retry.py` | `test_fr03_exponential_backoff_injectable_sleep` (AC-FR-03-01), `test_fr03_retry_limit_cap` (AC-FR-03-01), `test_fr03_timeout_triggers_retry` (AC-FR-03-01) | FR-03 | PLANNED | ≥85% |
| `src/taskq/breaker.py` | `tests/test_breaker.py` | `test_fr03_threshold_opens_breaker` (AC-FR-03-02), `test_fr03_open_refuses_with_exit_3` (AC-FR-03-03 + AC #6), `test_fr03_half_open_probe_success_closes` (AC-FR-03-04 — **NFR-99-b ambiguity anchors here**), `test_fr03_half_open_probe_failure_reopens` (AC-FR-03-04), `test_fr03_state_persisted_atomically` (AC-FR-03-05 + AC-NFR-03-02), `test_nfr03_open_to_closed_within_cooldown_plus_1s` (AC-NFR-03-02) | FR-03, NFR-03 | PLANNED | ≥85% |
| `src/taskq/cache.py` | `tests/test_cache.py` | `test_fr04_signature_sha256` (AC-FR-04-01), `test_fr04_cached_replay_no_subprocess` (AC-FR-04-02 + AC #7), `test_fr04_expiry_normal_execution` (AC-FR-04-03), `test_fr04_atomic_thread_safe_write` (AC-FR-04-04 + AC-NFR-03-01) | FR-04, NFR-03 | PLANNED | ≥85% |
| `src/taskq/executor.py` (redaction) | `tests/test_redaction.py` | `test_nfr04_sk_pattern_redacted` (AC-NFR-04-01), `test_nfr04_token_pattern_redacted` (AC-NFR-04-01), `test_nfr04_negative_no_match_unchanged` (AC-NFR-04-01), `test_nfr04_redaction_before_persistence` (AC-NFR-04-01 + R5) | NFR-04 | PLANNED | ≥85% |
| `src/taskq/cli.py` + `src/taskq/__main__.py` | `tests/test_cli.py` + `tests/test_exit_codes.py` | `test_fr05_argparse_subcommands` (AC-FR-05-01), `test_fr05_json_flag_round_trip` (AC-FR-05-02), `test_fr05_exit_code_matrix` (AC-FR-05-03 + AC #3/#4/#5/#6), `test_fr05_unknown_task_id_exit_2` (AC-FR-05-03) | FR-05, NFR-02 | PLANNED | ≥85% |
| `src/taskq/config.py` | `tests/test_config.py` | `test_nfr06_env_var_defaults`, `test_nfr06_env_var_override` (AC-NFR-06-01), `test_env_example_complete` (AC-NFR-06-01 + AC #8 — lints `.env.example` for 8 vars) | NFR-06 | PLANNED | ≥80% |
| `src/taskq/*` (all public symbols) | `tests/test_docstring_fr_refs.py` (Gate 1 inspect) | `test_nfr05_every_public_symbol_has_fr_ref` (AC-NFR-05-01 + AC #10) | NFR-05 | PLANNED | 100% public symbol coverage |
| (perf gate) | `tests/bench/test_bench_submit_status.py` | `test_nfr01_submit_status_p95_under_50ms` (AC-NFR-01-01 — **NFR-99-a ambiguity anchors here**) | NFR-01 | PLANNED | p95 < 50ms × 100 iter |
| (security gate) | `tests/test_security.py` (CI grep-gate) | `test_nfr02_no_shell_true_in_codebase` (AC-NFR-02-01 — runs `grep -rn 'shell=True' src/ tests/`; expects 0 hits in production paths) | NFR-02 | PLANNED | grep exit 0 |

### 4.2 Test Naming Authority

All test function names follow the pattern `test_fr{NN}_...` (FR-anchored) or `test_nfr{NN}_...` (NFR-anchored), per `01-requirements/SPEC_TRACKING.md` §Language and `TEST_INVENTORY.yaml` (currently a stub — Round 1 leaves the planned names above; P3 implementation agent fills in the canonical `TEST_SPEC.md` registry).

---

## 5. Acceptance Criteria ↔ Test Mapping (Bidirectional)

> **Forward** link: each AC anchors to one planned test function (verified by the test function name in §4.1).
> **Back-reference**: which FR / NFR row in §1 / §2 the AC belongs to.

| AC ID | AC Description (verbatim from SRS §3 / §4) | FR/NFR Anchor | Planned Test Function | SRS § | Status |
|-------|--------------------------------------------|---------------|------------------------|-------|--------|
| AC-FR-01-01 | 命令為空或全空白 → 拒絕 | FR-01 | `test_fr01_add_task_empty_rejected` | §3 FR-01 | PLANNED |
| AC-FR-01-02 | 命令 > 1000 字元 → 拒絕 | FR-01 | `test_fr01_add_task_too_long_rejected` | §3 FR-01 | PLANNED |
| AC-FR-01-03 | 命令含 `;` `|` `&` `$` `>` `<` `` ` `` 任一 → 拒絕 | FR-01 / NFR-02 | `test_fr01_add_task_injection_chars_rejected` | §3 FR-01 | PLANNED |
| AC-FR-01-04 | `--name` 與既有 pending/running 任務重複 → 拒絕 | FR-01 | `test_fr01_add_task_name_conflict_rejected` | §3 FR-01 | PLANNED |
| AC-FR-01-05 | 產生 task id; `pending` 狀態; 原子寫入; stdout 輸出 id (`--json` JSON) | FR-01 | `test_fr01_add_task_success_atomic_write` | §3 FR-01 | PLANNED |
| AC-FR-02-01 | `subprocess.run(shlex.split(...), capture_output, text, timeout=TASKQ_TASK_TIMEOUT)`; 任何路徑禁用 `shell=True` | FR-02 / NFR-02 | `test_fr02_subprocess_shlex_split_no_shell_true` | §3 FR-02 | PLANNED |
| AC-FR-02-02 | 狀態機 `pending → running → done / failed / timeout` | FR-02 | `test_fr02_status_machine_done_failed_timeout` | §3 FR-02 | PLANNED |
| AC-FR-02-03 | 結果欄位 `exit_code` / `stdout_tail` / `stderr_tail`(末 2000) / `duration_ms` / `finished_at` | FR-02 | `test_fr02_result_fields_tail_2000` | §3 FR-02 | PLANNED |
| AC-FR-02-04 | `--all` 並發; 共享 Lock | FR-02 | `test_fr02_concurrent_threadpool` + `test_fr02_concurrent_run_all_no_loss` | §3 FR-02 | PLANNED |
| AC-FR-02-05 | 單一任務 timeout → exit 4 | FR-02 / FR-05 | `test_fr02_timeout_exit_code_4` | §3 FR-02 | PLANNED |
| AC-FR-03-01 | 自動重試 + exponential backoff + 注入 sleep | FR-03 | `test_fr03_exponential_backoff_injectable_sleep`, `test_fr03_retry_limit_cap`, `test_fr03_timeout_triggers_retry` | §3 FR-03 | PLANNED |
| AC-FR-03-02 | 連續最終失敗計數 ≥ `TASKQ_BREAKER_THRESHOLD` → `OPEN` | FR-03 | `test_fr03_threshold_opens_breaker` | §3 FR-03 | PLANNED |
| AC-FR-03-03 | `OPEN` 期間拒絕 + exit 3 + stderr `breaker open`, 不執行 subprocess | FR-03 / FR-05 | `test_fr03_open_refuses_with_exit_3` | §3 FR-03 | PLANNED |
| AC-FR-03-04 | cooldown 後 `HALF_OPEN` 探針成功→`CLOSED`, 失敗→重新 `OPEN` | FR-03 | `test_fr03_half_open_probe_success_closes`, `test_fr03_half_open_probe_failure_reopens` | §3 FR-03 | PLANNED |
| AC-FR-03-05 | 狀態持久化於 `$TASKQ_HOME/breaker.json` (原子寫) | FR-03 / NFR-03 | `test_fr03_state_persisted_atomically` | §3 FR-03 | PLANNED |
| AC-FR-04-01 | 快取簽名 = `sha256(command)` | FR-04 | `test_fr04_signature_sha256` | §3 FR-04 | PLANNED |
| AC-FR-04-02 | `run <id> --cached` TTL 內回放 `done`; 不執行 subprocess; `cached: true` | FR-04 | `test_fr04_cached_replay_no_subprocess` | §3 FR-04 | PLANNED |
| AC-FR-04-03 | 過期/不存在 → 正常執行, 成功後寫入 `cache.json` | FR-04 | `test_fr04_expiry_normal_execution` | §3 FR-04 | PLANNED |
| AC-FR-04-04 | 快取讀寫: 原子 + 執行緒安全 | FR-04 / NFR-03 | `test_fr04_atomic_thread_safe_write` | §3 FR-04 | PLANNED |
| AC-FR-05-01 | argparse 子命令: `submit`/`run`/`status`/`list`/`clear` | FR-05 | `test_fr05_argparse_subcommands` | §3 FR-05 | PLANNED |
| AC-FR-05-02 | 全域 `--json` 旗標 | FR-05 | `test_fr05_json_flag_round_trip` | §3 FR-05 | PLANNED |
| AC-FR-05-03 | Exit codes: 0/2/3/4/1 | FR-05 | `test_fr05_exit_code_matrix` | §3 FR-05 | PLANNED |
| AC-NFR-01-01 | `submit` + `status` 100 次 p95 < 50ms | NFR-01 | `test_nfr01_submit_status_p95_under_50ms` | §4 NFR-01 | PLANNED (NFR-99-a anchor) |
| AC-NFR-02-01 | 全 codebase 禁用 `shell=True` | NFR-02 | `test_nfr02_no_shell_true_in_codebase` (CI grep-gate) | §4 NFR-02 | PLANNED |
| AC-NFR-02-02 | FR-01 注入黑名單測試覆蓋 | NFR-02 / FR-01 | `test_fr01_add_task_injection_chars_rejected` (covered above) | §4 NFR-02 | PLANNED |
| AC-NFR-03-01 | 三資料檔原子寫; 進程中斷後仍合法 JSON | NFR-03 | `test_nfr03_atomic_write_kill9_recovery` | §4 NFR-03 | PLANNED |
| AC-NFR-03-02 | breaker `OPEN → CLOSED` 恢復時間 ≤ `TASKQ_BREAKER_COOLDOWN` + 1s | NFR-03 / FR-03 | `test_nfr03_open_to_closed_within_cooldown_plus_1s` | §4 NFR-03 | PLANNED (NFR-99-b anchor) |
| AC-NFR-04-01 | stdout_tail/stderr_tail 落盤前 redact 敏感行 | NFR-04 | `test_nfr04_sk_pattern_redacted`, `test_nfr04_token_pattern_redacted`, `test_nfr04_negative_no_match_unchanged`, `test_nfr04_redaction_before_persistence` | §4 NFR-04 | PLANNED |
| AC-NFR-05-01 | 公開函式/類別 docstring 含 `[FR-XX]` 引用 | NFR-05 | `test_nfr05_every_public_symbol_has_fr_ref` | §4 NFR-05 | PLANNED |
| AC-NFR-06-01 | 8 個 `TASKQ_*` 環境變數 + `.env.example` 完整宣告 | NFR-06 | `test_nfr06_env_var_defaults`, `test_nfr06_env_var_override`, `test_env_example_complete` | §4 NFR-06 | PLANNED |

**Coverage summary**: 30 ACs total (22 FR ACs + 8 NFR ACs, verified by `grep -c '^| AC-FR-'` = 22 and `grep -c '^| AC-NFR-'` = 8); all 30 anchored to ≥1 planned test function. Breakdown: AC-FR-01-01..05 (5) + AC-FR-02-01..05 (5) + AC-FR-03-01..05 (5) + AC-FR-04-01..04 (4) + AC-FR-05-01..03 (3) = 22 FR ACs; AC-NFR-01-01 (1) + AC-NFR-02-01..02 (2) + AC-NFR-03-01..02 (2) + AC-NFR-04-01 (1) + AC-NFR-05-01 (1) + AC-NFR-06-01 (1) = 8 NFR ACs. (Matches §0.3 target = 30.)

> Reconciliation note: SPEC.md §8 lists 10 acceptance items; SPEC_TRACKING.md §Acceptance Items also lists 10. Both reconcile — the 10 items are **integration-level** end-to-end behaviors (each combines multiple ACs); see §6 below for the AC-item cross-walk.

---

## 6. Acceptance Items ↔ FR/NFR Cross-Walk (10/10)

> Cross-walks the 10 SPEC.md §8 acceptance items (also reproduced in SRS.md §5) to the FR / NFR / AC rows that collectively implement them.

| # | Acceptance Item (SPEC.md §8) | FR Anchor | NFR Anchor | ACs Touched | Test Files (planned) |
|---|-------------------------------|-----------|------------|-------------|---------------------|
| 1 | `pytest tests/ -q` 全綠 | cross-cutting | NFR-05 (docstring gate) | AC-NFR-05-01 + all FR ACs | all `tests/test_*.py` |
| 2 | `submit "echo hi"` → 8-hex id; `run <id>` → `done`; `status` → `exit_code: 0` | FR-01, FR-02, FR-05 | NFR-01 | AC-FR-01-05, AC-FR-02-02, AC-FR-02-03, AC-FR-05-01, AC-NFR-01-01 | `tests/test_store.py`, `tests/test_executor.py`, `tests/test_cli.py`, `tests/bench/test_bench_submit_status.py` |
| 3 | `submit ""` → exit 2 | FR-01, FR-05 | NFR-02 | AC-FR-01-01, AC-FR-05-03, AC-NFR-02-02 | `tests/test_store.py`, `tests/test_cli.py` |
| 4 | `submit "echo hi; rm x"` → exit 2 (注入字元) | FR-01, FR-05 | NFR-02 | AC-FR-01-03, AC-FR-05-03, AC-NFR-02-02 | `tests/test_store.py`, `tests/test_cli.py` |
| 5 | `TASKQ_TASK_TIMEOUT=1` + `sleep 5` → `timeout`, exit 4 | FR-02, FR-05 | — | AC-FR-02-05, AC-FR-05-03 | `tests/test_executor.py`, `tests/test_cli.py` |
| 6 | 3 連續失敗 → 第 4 次 `run` → exit 3; cooldown 後恢復 | FR-03, FR-05 | NFR-03 | AC-FR-03-02, AC-FR-03-03, AC-FR-03-04, AC-FR-03-05, AC-FR-05-03, AC-NFR-03-02 | `tests/test_breaker.py`, `tests/test_cli.py` |
| 7 | TTL 內 `run <id> --cached` → 回放, `cached: true`, 無 subprocess | FR-04 | — | AC-FR-04-02 | `tests/test_cache.py` |
| 8 | `.env.example` 宣告全部 8 個 `TASKQ_*` 變數 | — | NFR-06 | AC-NFR-06-01 | `tests/test_config.py` |
| 9 | `run --all` 並發後 `tasks.json` 合法 JSON, 無任務遺失 | FR-02 | NFR-03 | AC-FR-02-04, AC-NFR-03-01 | `tests/test_store.py`, `tests/test_executor.py` |
| 10 | 公開函式 docstring 含 `[FR-XX]` 引用 | — | NFR-05 | AC-NFR-05-01 | `tests/test_docstring_fr_refs.py` |

---

## 7. Risk ↔ FR/NFR Mapping (5/5)

> Maps each risk in SPEC.md §9 / SRS.md §8 to the FR / NFR rows that mitigate it and the planned tests that prove the mitigation.

| Risk ID | Risk Description | Mitigating FR | Mitigating NFR | Planned Test Function(s) |
|---------|-----------------|---------------|----------------|--------------------------|
| R1 | 並發寫入損壞 `tasks.json` | FR-01, FR-02 | NFR-03 | `test_fr02_concurrent_run_all_no_loss`, `test_nfr03_atomic_write_kill9_recovery` |
| R2 | subprocess 懸掛/殭屍 | FR-02 | — | `test_fr02_timeout_exit_code_4` |
| R3 | breaker 誤鎖死 | FR-03 | NFR-03 | `test_fr03_open_refuses_with_exit_3`, `test_fr03_half_open_probe_success_closes`, `test_nfr03_open_to_closed_within_cooldown_plus_1s` |
| R4 | 快取回放陳舊結果 | FR-04 | — | `test_fr04_expiry_normal_execution` |
| R5 | secret 落盤洩漏 | — | NFR-04 | `test_nfr04_redaction_before_persistence` |

---

## 8. Open Issues ↔ FR/NFR Anchor (carry-forward)

> Open issues carry forward from `SPEC_TRACKING.md` §Open Issues and `SRS.md` §7.1. Both must be resolved before P5 verification lands VERIFIED status on the anchored rows.

| Open Issue | Type | Anchored FR/NFR / AC | Resolution Owner | Status |
|------------|------|----------------------|-------------------|--------|
| NFR-99-a — AC-NFR-01-02 ambiguity boundary | ambiguity | NFR-01 / AC-NFR-01-01 (and AC #2 indirectly) | Agent-PERF (P5 verification) | OPEN — p95 50ms boundary (含/不含 subprocess) needs stakeholder confirmation |
| NFR-99-b — AC-NFR-03-03 measurement scope | ambiguity | FR-03 / NFR-03 / AC-NFR-03-02 (and AC #6 indirectly) | Agent-REL (P5 verification) | OPEN — breaker OPEN → CLOSED observation moment (HALF_OPEN probe success vs explicit reset) needs stakeholder confirmation |

---

## 9. Completeness Verification (Round 1)

| Check | Target | Actual | Status |
|-------|--------|--------|--------|
| FR ↔ SRS mapping | 100% (5/5) | 5/5 | PASS |
| NFR ↔ SRS mapping | 100% (6/6) | 6/6 | PASS |
| SRS ↔ planned code mapping | ≥1 module per FR | 5/5 FRs have ≥1 owner module | PASS |
| SRS ↔ planned test mapping | ≥1 test per AC | 30/30 ACs have ≥1 planned test | PASS |
| FR-NFR cross-cutting links documented | 100% | 4 cross-cuts (NFR-02 / NFR-03 / NFR-04 / NFR-05) enumerated | PASS |
| Acceptance Items (10/10) ↔ FR/NFR | 100% | 10/10 | PASS |
| Risks (5/5) ↔ FR/NFR | 100% | 5/5 | PASS |
| Open Issues (2/2) carry forward | 100% | 2/2 | PASS |
| High-risk modules flagged | `executor` + `store` | 2/2 flagged [HIGH-RISK] | PASS |
| H1 anchor matches loader phrase | `Traceability Matrix` | yes — `# Traceability Matrix — taskq` | PASS |
| Bidirectional link audit (every row has `←` back-reference) | 100% | yes | PASS |
| Architecture constraint `no_circular_dependencies` documented | yes | yes (§3.2) | PASS |
| Framework alignment (SPEC.md §10) reflected | yes | yes (§3.1 + §4.1 high-risk tags) | PASS |
| ASPICE SWE.3 / SYS.4 base practices mapped | yes | see §10 | PASS |

---

## 10. ASPICE Compliance (SWE.3 / SYS.4 Base Practices)

> Reference: ASPICE 4.0 process reference model SWE.3 (Software Detailed Design and Unit Construction) and SYS.4 (System Integration and Integration Test). Bidirectional traceability is the SWE.3.B.SP2 base practice.

| ASPICE Capability / Base Practice | How This Matrix Satisfies It | Status |
|----------------------------------|------------------------------|--------|
| **SWE.3.B.SP1** — Task-to-work-product traceability (each requirement traces to design + code + test) | §1 (FR↔Spec), §3 (Spec↔Code), §4 (Code↔Test), §5 (AC↔Test) | PLANNED — every FR has downstream chain to planned test |
| **SWE.3.B.SP2** — Bidirectional traceability (forward + backward) | Every row in §1 / §2 / §3 / §4 carries `← Back-references` column | PLANNED |
| **SWE.3.B.SP3** — Traceability consistency (no orphan / dangling rows; coverage targets met) | §0.3 completeness table + §9 verification table; orphan detection = any row whose back-ref is empty | PLANNED — Round 1: 0 orphans (all back-refs populated) |
| **SWE.3.B.SP4** — Traceability maintenance (status lifecycle: PLANNED → ACCEPTED) | Status column on every row + SPEC_TRACKING.md status lifecycle | PLANNED — Round 1 = all PLANNED |
| **SYS.4.B.SP1** — Integration test traceability (each integration test anchored to ≥1 FR / AC) | §4.1 (planned integration tests in `tests/test_store.py` `tests/test_executor.py` `tests/test_cli.py`) + §6 (Acceptance Items) | PLANNED |
| **SYS.4.B.SP3** — Test coverage measurement (line / branch / AC coverage) | §4.1 per-module coverage targets; AC-level coverage in §5 | PLANNED — targets: high-risk ≥90%, normal ≥85%, perf / security gates as AC-anchored |

---

## 11. Downstream-Phase Re-render Contract

> This matrix is a **Phase 1 deliverable** and is re-rendered by every downstream phase. The re-render contract below specifies what each phase must update when it touches the matrix.

| Phase | Trigger | Update Pattern |
|-------|---------|----------------|
| P2 (Architecture) | Architecture plan ratified in `02-architecture/` | Promote each row's Status → `DESIGNED`; resolve architecture constraint `no_circular_dependencies` in §3.2; add concrete file paths once `02-architecture/MODULE_GRAPH.md` lands. |
| P3 (Implementation) | `pytest tests/ -q` green for the row's module (per `tests/test_<module>.py`) | Promote row → `IMPLEMENTED`; replace "Lines = tbd" with actual line counts; replace "Symbols (planned)" with concrete function/class names. |
| P4 (Testing) | All ACs in the row have passing tests (per §5 mapping) | Promote row → `TESTED`; record actual coverage % against target; resolve any failed ACs back to `IMPLEMENTED`. |
| P5 (Verification) | Decision Framework gate green (benchmark / grep / fault-injection / etc.) | Promote row → `VERIFIED`; close any open issues (NFR-99-a, NFR-99-b) anchored to that row. |
| P6 / Gate 1 | Per-FR TDD + implementation quality closed (cross-check with `06-quality/`) | Promote row → `ACCEPTED`; matrix reaches `Gate 1` closure. |

**Round 1 conclusion** (2026-07-04): every row currently `PLANNED`. No row has been `DESIGNED` / `IMPLEMENTED` / `TESTED` / `VERIFIED` / `ACCEPTED` yet — those promotions are the explicit hand-off to downstream phase agents. No code or test files exist on disk yet (`src/` and `tests/` directories not yet created) — this matrix is the **planned** trace that P3 / P4 agents will fulfill.

---

## 12. Self-Review (Mandatory)

### 12.1 Possible Errors

1. **Planned-vs-actual drift after P3 implementation lands.** The current "Planned Code File" / "Planned Test Function" columns are Phase 1 projections. If P3 implementation diverges (renames, splits modules, drops a test), §3.1 / §4.1 / §5 must be re-rendered — otherwise the matrix becomes stale and ASPICE SWE.3.B.SP3 (consistency) fails. **Mitigation**: P3 + P4 agents MUST update §3.1 / §4.1 / §5 in lockstep with code/test commits.
2. **NFR-99-a / NFR-99-b resolution may retroactively invalidate NFR-01 / NFR-03 ACs.** If stakeholder confirms the 50ms budget includes subprocess overhead (NFR-99-a) or that HALF_OPEN probe IS the OPEN→CLOSED observation point (NFR-99-b), the corresponding test functions (`test_nfr01_submit_status_p95_under_50ms` / `test_nfr03_open_to_closed_within_cooldown_plus_1s`) may need re-scoping. **Mitigation**: P5 verification agents flag resolution before locking VERIFIED status.

### 12.2 Unverified Assumptions

- **Assumption**: The 8-module layout in `SPEC.md` §6 / `SRS.md` §2.7 is canonical for P3 scaffolding (no module is added / split / merged). **Verification needed**: P2 architecture plan ratification.
- **Assumption**: `TEST_INVENTORY.yaml` is the canonical test naming authority and (as of Round 1) already enumerates 39 fully-named test functions across all 30 ACs (with sub-case letter splits where one AC maps to multiple tests, e.g. `TC-FR03-01a/b/c`). P3 agents regenerate `TEST_SPEC.md` against this registry rather than authoring new test names from scratch. **Verification needed**: P3 `TEST_SPEC.md` regeneration must use `TEST_INVENTORY.yaml` `tests[].test_function` as the source of truth, not invent new names.
- **Assumption**: `src/taskq/` and `tests/` directories will be created at Phase 3 entry with the paths assumed in §3.1 / §4.1. **Verification needed**: P3 directory scaffold command.
- **Assumption**: ASPICE SWE.3 / SYS.4 base practices listed in §10 are the correct interpretation of the harness-methodology v2.9 alignment (no SWE.4 / SWE.5 / SWE.6 base practices apply at this scope). **Verification needed**: harness/CLAUDE.md re-read at Gate 4 closure.

### 12.3 Confidence

- **Overall confidence**: **Medium-High** — every FR / NFR / AC has a complete chain to ≥1 planned test; completeness table in §9 confirms 100% row coverage. Two ambiguities (NFR-99-a, NFR-99-b) are explicitly carried forward as open issues rather than silently resolved.

### 12.4 Counter-Example Audit

- "What if a Phase 3 implementation renames `src/taskq/store.py` to `src/taskq/persistence.py`?" → §3.1 row's `Planned Code File` column would be stale; downstream agents re-render per §11 contract.
- "What if an AC is silently dropped?" → §5 row count (30) would drop below 30 and §9 verification table would flag it; SPEC_TRACKING.md §Completeness Validation would also fail.
- "What if a new NFR is added at Gate 4?" → §2 + §3.1 + §4.1 + §5 all need a new row; the matrix is append-only (no overwrite of existing rows); Gate 1 close would re-validate §0.3 completeness.

---

## 13. Cross-References

| Artifact | Path | Anchor in this matrix |
|----------|------|-----------------------|
| Source of truth (canonical spec) | `SPEC.md` (v3.0.0, 2026-07-04) | §1, §2, §3.1, §6, §7 |
| Approved SRS (INGESTION MODE) | `01-requirements/SRS.md` | §1, §2, §5, §7 (open issues) |
| Per-FR status / owner / Decision Framework | `01-requirements/SPEC_TRACKING.md` | §1, §2, §3.1, §4.1, §8 |
| Project metadata / FR-NFR-env inventory | `PROJECT_BRIEF.md` | §1, §2, §7 |
| Test naming authority (canonical) | `TEST_INVENTORY.yaml` | §4.1, §4.2 |
| Framework classification (high-risk modules) | `harness/CLAUDE.md` + `SPEC.md` §10 | §3.1 [HIGH-RISK] flags, §3.2 |
| Machine-readable FR block | `01-requirements/SRS.md` Appendix A | §3.1, §4.1 |

---

*Matrix version: 1.0 (Round 1, 2026-07-04). Owner: Requirements Engineer (Agent A). Re-rendered by Phase 2-8 agents per §11 contract. Source of truth: `01-requirements/SRS.md` (APPROVED) + `01-requirements/SPEC_TRACKING.md` (APPROVED) + `SPEC.md` v3.0.0 (canonical).*