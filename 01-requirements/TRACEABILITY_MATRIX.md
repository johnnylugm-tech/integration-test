# Traceability Matrix — taskq

> Source of truth: `01-requirements/SRS.md` v1.0.0 (ingestion-mode transcription of `SPEC.md` v2.0.0, 2026-06-15) and `01-requirements/SPEC_TRACKING.md` v1.0.0 (Round 1 entry, 2026-06-29).
> Companion to: `TEST_INVENTORY.yaml` v5.0.0 (Round 5 — per-FR test function enumeration derived 1:1 from §3 + §4 of this matrix).
> Mode: INGESTION (100% derived from approved `SRS.md` §3-§4 and `SPEC_TRACKING.md` §3; no new requirements, no invented test cases, no scope drift).
> TBD / TODO / `<placeholder>` markers: none present in canonical SPEC.md, SRS.md, or SPEC_TRACKING.md.

---

## 1. Purpose

This Traceability Matrix establishes bidirectional linkage between:
1. **Forward trace** — every Functional / Non-Functional Requirement in `SRS.md` → every Acceptance Criterion (AC) → every Test Case (TC) enumerated in `TEST_INVENTORY.yaml` §3 + §4.
2. **Backward trace** — every Test Case → its verifying AC(s) → its parent FR/NFR → its canonical `SPEC.md` anchor.
3. **Cross-cutting trace** — every cross-binding (e.g. FR-01.AC-3 ↔ NFR-02-AC-2 per-char) signalled explicitly via `cross_ref_*` metadata in `TEST_INVENTORY.yaml`.

The matrix is the single source of truth for **coverage validation**: any AC without a TC, or any TC without an AC, is a coverage gap and MUST be resolved before Gate 3 exit.

---

## 2. Requirement-to-Design Element Mapping

### 2.1 Constraints → Design Elements (from SRS §2)

| Constraint | Design Element (module:function) | Source |
|------------|----------------------------------|--------|
| C-01 (Python 3.11 stdlib only) | `pyproject.toml` — `requires-python = ">=3.11"`, zero runtime deps | `SPEC.md` §1 |
| C-02 (CLI tool; `python -m taskq`) | `taskq/__main__.py` + `taskq/cli/main.py:main()` | `SPEC.md` §1 |
| C-03 (argparse subcommands) | `taskq/cli/build_parser.py:build_parser()` + `taskq/cli/main.py:build_subparsers()` | `SPEC.md` §2 |
| C-04 (`subprocess`; `shell=False`; `shlex.split`) | `taskq/executor.py:run_task()` (single subprocess call site) | `SPEC.md` §2 |
| C-05 (JSON; atomic write: tmp + `os.replace`) | `taskq/store.py:atomic_write_json()` + `taskq/store.py:save_tasks()` | `SPEC.md` §2 |
| C-06 (`TASKQ_*` env vars via `config.py`) | `taskq/config.py:get_home()` + `get_task_timeout()` + `get_retry_limit()` | `SPEC.md` §2 |
| C-07 (injection char blacklist on `submit`) | `taskq/validate.py:check_injection_chars()` + `taskq/cli/submit_cmd.py` (error branch) | `PROJECT_BRIEF.md` |
| C-08 (atomic write survives crash; no silent rebuild; secret-line redaction) | `taskq/store.py:load_tasks()` (parse-fail branch) + `taskq/redact.py:redact_line()` | `PROJECT_BRIEF.md` |
| C-09 (`submit` + `status` p95 < 50ms / 100 iters) | `taskq/store.py:atomic_write_json()` + `taskq/store.py:new_task_id()` + `taskq/cli/submit_cmd.py` + `taskq/cli/status_cmd.py` | `PROJECT_BRIEF.md` |

### 2.2 Module Ownership per FR / NFR

| FR / NFR | Primary Module(s) | Module Functions (verbatim) |
|----------|-------------------|-----------------------------|
| FR-01 | `taskq.validate` + `taskq.cli.submit_cmd` + `taskq.store` | `validate.is_empty`, `validate.check_length`, `validate.check_injection_chars`, `cli.submit_cmd`, `store.new_task_id`, `store.atomic_write_json`, `store.save_tasks`, `store.load_tasks` |
| FR-02 | `taskq.executor` + `taskq.cli.run_cmd` + `taskq.config` | `executor.run_task`, `executor.run_with_retry`, `cli.run_cmd`, `config.get_task_timeout`, `config.get_retry_limit` |
| FR-03 | `taskq.cli.main` + `taskq.cli.{submit_cmd, run_cmd, status_cmd, list_cmd, clear_cmd}` | `cli.main`, `cli.build_parser`, `cli.submit_cmd`, `cli.run_cmd`, `cli.status_cmd`, `cli.list_cmd`, `cli.clear_cmd` |
| NFR-01 | test harness (cross-cutting — `tests/test_nfr01_perf.py`) | end-to-end `submit`+`status` loop with subprocess exec mocked |
| NFR-02 | `taskq.executor.run_task` (static check) + `taskq.validate.check_injection_chars` + `taskq.cli.submit_cmd` (error branch) | static AST/grep scan + per-character blacklist unit tests |
| NFR-03 | `taskq.store.atomic_write_json` + `taskq.executor.run_task` (redaction hook) + `taskq.redact.redact_line` | crash-injection + whole-line redaction pre-persist |

---

## 3. Forward Trace: AC → TC

Every Acceptance Criterion registered in `SRS.md` §5 is mapped 1:1 (or, where `SRS.md` §3 decomposition specifies sub-cases, 1:N) to a Test Case enumerated in `TEST_INVENTORY.yaml` §3. The matrix is the canonical owner of the AC ↔ TC mapping; the YAML is the canonical owner of TC asserts and design-element bindings.

### 3.1 FR-01 — Task Model and Persistence (7 ACs → 5 TCs)

| AC ID | AC Text (verbatim from `SRS.md` §3 FR-01) | TC ID | Verification Locus |
|-------|--------------------------------------------|-------|--------------------|
| AC-FR01-01 | 「命令為空或全空白 → 拒絕」 | `test_tc_fr01_01_reject_empty_or_whitespace` | TDD-RED → TDD-GREEN → GATE1 |
| AC-FR01-02 | 「命令 > 1000 字元 → 拒絕」 | `test_tc_fr01_02_reject_overlong` | TDD-RED → TDD-GREEN → GATE1 |
| AC-FR01-03 | 「命令含 `;` `|` `&` `$` `>` `<` `` ` `` 任一 → 拒絕(NFR-02)」 | `test_tc_fr01_03_reject_injection_chars` (covers all 7 chars) + `test_tc_nfr02_02a..g` (per-char breakdown, cross-ref NFR-02-AC-2) | TDD-RED → TDD-GREEN → GATE1 → GATE4 |
| AC-FR01-04 | 「產生 task id(uuid4 前 8 hex)」 | `test_tc_fr01_04_valid_submit_writes_pending` | TDD-RED → TDD-GREEN → GATE1 → GATE2 |
| AC-FR01-05 | 「狀態 `pending`,記錄 `command`、`created_at`」 | `test_tc_fr01_04_valid_submit_writes_pending` | TDD-RED → TDD-GREEN → GATE1 → GATE2 |
| AC-FR01-06 | 「原子寫入 `$TASKQ_HOME/tasks.json`(tmp + `os.replace`)」 | `test_tc_fr01_04_valid_submit_writes_pending` (success branch) + `test_tc_nfr03_01_atomic_write_crash_recovery` (crash-injection, cross-ref NFR-03-AC-1) | TDD-RED → TDD-GREEN → GATE1 → GATE2 → BASELINE |
| AC-FR01-07 | 「`tasks.json` 損壞(非法 JSON)→ 啟動偵測 → **exit 1**,stderr `store corrupted`(不靜默重建)」 | `test_tc_fr01_05_corrupt_store_exits_one` | TDD-RED → TDD-GREEN → GATE1 → GATE2 |

### 3.2 FR-02 — Task Execution and Retry (6 ACs → 5 TCs)

| AC ID | AC Text (verbatim from `SRS.md` §3 FR-02) | TC ID | Verification Locus |
|-------|--------------------------------------------|-------|--------------------|
| AC-FR02-01 | 「以 `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` 執行;**任何路徑不得使用 `shell=True`**」 | `test_tc_fr02_01_subprocess_no_shell` (unit) + `test_tc_nfr02_01_no_shell_true_grep` (codebase-wide, cross-ref NFR-02-AC-1) | TDD-RED → TDD-GREEN → GATE1 → GATE4 |
| AC-FR02-02 | 「狀態機:`pending → running → done | failed | timeout`;exit 0 → `done`;非 0 → `failed`;`TimeoutExpired` → `timeout`」 | `test_tc_fr02_01_subprocess_no_shell` + `test_tc_fr02_03_retry_on_failed_or_timeout` (final-status assertion) + `test_tc_fr02_04_timeout_exit_4` | TDD-RED → TDD-GREEN → GATE1 → GATE2 |
| AC-FR02-03 | 「結果欄位:`exit_code`、`stdout_tail`(末 2000 字元)、`stderr_tail`(末 2000 字元)、`duration_ms`、`finished_at`」 | `test_tc_fr02_02_result_fields_persisted` | TDD-RED → TDD-GREEN → GATE1 |
| AC-FR02-04 | 「**重試**:`run` 結果為 `failed`/`timeout` 時自動重試,上限 `TASKQ_RETRY_LIMIT` 次(預設 2)」 | `test_tc_fr02_03_retry_on_failed_or_timeout` | TDD-RED → TDD-GREEN → GATE1 → GATE2 |
| AC-FR02-05 | 「單一任務模式下 `timeout` 結果 → **exit 4**」 | `test_tc_fr02_04_timeout_exit_4` | TDD-RED → TDD-GREEN → GATE1 → GATE2 |
| AC-FR02-06 | 「其他未預期例外 → exit 1(不得裸 `except:` 吞噬)」 | `test_tc_fr02_05_unexpected_exception_exit_1` | TDD-RED → TDD-GREEN → GATE1 |

### 3.3 FR-03 — CLI Integration and Query (6 ACs → 6 TCs)

| AC ID | AC Text (verbatim from `SRS.md` §3 FR-03) | TC ID | Verification Locus |
|-------|--------------------------------------------|-------|--------------------|
| AC-FR03-01 | 「argparse 子命令(入口 `python -m taskq`):`submit`/`run`/`status`/`list`/`clear`」 | `test_tc_fr03_01_argparse_subcommands` | TDD-RED → TDD-GREEN → GATE1 |
| AC-FR03-02 | 「`status <id>` 輸出該任務全欄位;unknown id → **exit 2** + `unknown task: <id>`」 | `test_tc_fr03_02_status_outputs_or_unknown` | TDD-RED → TDD-GREEN → GATE1 |
| AC-FR03-03 | 「`list` 列出全部任務(id + status + command 前 50 字元)」 | `test_tc_fr03_03_list_outputs_per_task` | TDD-RED → TDD-GREEN → GATE1 |
| AC-FR03-04 | 「`clear` 清空 `$TASKQ_HOME/tasks.json`」 | `test_tc_fr03_04_clear_empties_store` | TDD-RED → TDD-GREEN → GATE1 |
| AC-FR03-05 | 「全域 flag `--json`:機器可讀輸出(單行 JSON)」 | `test_tc_fr03_05_json_flag_single_line` | TDD-RED → TDD-GREEN → GATE1 → GATE4 |
| AC-FR03-06 | 「**Exit codes**:`0` 成功 / `2` 輸入驗證錯誤(含 unknown task id)/ `4` 任務 timeout / `1` 其他內部錯誤」 | `test_tc_fr03_06_exit_code_matrix` | TDD-RED → TDD-GREEN → GATE1 → GATE2 |

### 3.4 NFR-01 — Performance (1 AC → 1 TC)

| AC ID | AC Text (verbatim from `SRS.md` §4 NFR-01) | TC ID | Verification Locus |
|-------|--------------------------------------------|-------|--------------------|
| AC-NFR01-01 | 「`submit` + `status` 組合操作 100 次 p95 < 50ms(不含 subprocess 執行)」 | `test_tc_nfr01_01_p95_under_50ms` | TDD-RED → TDD-GREEN → GATE1 → BASELINE |

### 3.5 NFR-02 — Security (2 ACs → 8 TCs)

| AC ID | AC Text (verbatim from `SRS.md` §4 NFR-02) | TC ID | Verification Locus |
|-------|--------------------------------------------|-------|--------------------|
| AC-NFR02-01 | 「全 codebase 禁用 `shell=True`」 | `test_tc_nfr02_01_no_shell_true_grep` | TDD-RED → TDD-GREEN → GATE1 → GATE2 → GATE4 |
| AC-NFR02-02 | 「FR-01 注入字元黑名單必須有測試覆蓋」 | `test_tc_nfr02_02a_reject_semicolon` + `test_tc_nfr02_02b_reject_pipe` + `test_tc_nfr02_02c_reject_ampersand` + `test_tc_nfr02_02d_reject_dollar` + `test_tc_nfr02_02e_reject_gt` + `test_tc_nfr02_02f_reject_lt` + `test_tc_nfr02_02g_reject_backtick` (7 sub-cases; cross-ref FR-01.AC-3) | TDD-RED → TDD-GREEN → GATE1 → GATE4 |

### 3.6 NFR-03 — Reliability (2 ACs → 3 TCs)

| AC ID | AC Text (verbatim from `SRS.md` §4 NFR-03) | TC ID | Verification Locus |
|-------|--------------------------------------------|-------|--------------------|
| AC-NFR03-01 | 「`tasks.json` 原子寫(進程中斷後仍為合法 JSON)」 | `test_tc_nfr03_01_atomic_write_crash_recovery` | TDD-RED → TDD-GREEN → GATE1 → GATE2 → BASELINE |
| AC-NFR03-02 | 「`stdout_tail`/`stderr_tail` 落盤前過濾 `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` 整行以 `[REDACTED]` 取代」 | `test_tc_nfr03_02a_redact_sk_line` (regex branch 1) + `test_tc_nfr03_02b_redact_token_line` (regex branch 2; also negative case) — ≥2 sub-entries per `TEST_INVENTORY.yaml` §3.6 L121 | TDD-RED → TDD-GREEN → GATE1 → GATE2 → BASELINE → GATE4 |

---

## 4. Backward Trace: TC → AC → FR/NFR → Canonical Anchor

Every TC in `TEST_INVENTORY.yaml` §3 traces back to a parent FR/NFR and a `SPEC.md` anchor. This view answers the question: "Given a test, what requirement does it verify?"

| TC ID | AC ID | Parent FR/NFR | `SPEC.md` Anchor | Cross-Refs |
|-------|-------|---------------|------------------|------------|
| `test_tc_fr01_01_reject_empty_or_whitespace` | FR-01.AC-1 | FR-01 | `SPEC.md` §3 FR-01 驗證規則 非空 | FR-03.AC-6 |
| `test_tc_fr01_02_reject_overlong` | FR-01.AC-2 | FR-01 | `SPEC.md` §3 FR-01 驗證規則 長度 | FR-03.AC-6 |
| `test_tc_fr01_03_reject_injection_chars` | FR-01.AC-3 | FR-01 | `SPEC.md` §3 FR-01 驗證規則 注入字元 | FR-03.AC-6; NFR-02-AC-2 |
| `test_tc_fr01_04_valid_submit_writes_pending` | FR-01.AC-4 + FR-01.AC-5 + FR-01.AC-6 | FR-01 | `SPEC.md` §3 FR-01 通過驗證 bullets 1-3 | FR-03.AC-6; NFR-01; NFR-03-AC-1 |
| `test_tc_fr01_05_corrupt_store_exits_one` | FR-01.AC-7 | FR-01 | `SPEC.md` §3 FR-01 通過驗證 bullet 4 | FR-03.AC-6; NFR-03-AC-1 |
| `test_tc_fr02_01_subprocess_no_shell` | FR-02.AC-1 + FR-02.AC-2 | FR-02 | `SPEC.md` §3 FR-02 first bullet + state machine bullet | NFR-02-AC-1 |
| `test_tc_fr02_02_result_fields_persisted` | FR-02.AC-3 | FR-02 | `SPEC.md` §3 FR-02 result fields bullet | NFR-03-AC-2 |
| `test_tc_fr02_03_retry_on_failed_or_timeout` | FR-02.AC-2 (final-status branch) + FR-02.AC-4 | FR-02 | `SPEC.md` §3 FR-02 state machine + retry bullets | — |
| `test_tc_fr02_04_timeout_exit_4` | FR-02.AC-5 | FR-02 | `SPEC.md` §3 FR-02 single-task-timeout bullet | FR-03.AC-6 |
| `test_tc_fr02_05_unexpected_exception_exit_1` | FR-02.AC-6 | FR-02 | `SPEC.md` §3 FR-02 exception bullet | FR-03.AC-6 |
| `test_tc_fr03_01_argparse_subcommands` | FR-03.AC-1 | FR-03 | `SPEC.md` §3 FR-03 command table | FR-03.AC-5 |
| `test_tc_fr03_02_status_outputs_or_unknown` | FR-03.AC-2 | FR-03 | `SPEC.md` §3 FR-03 status row | FR-03.AC-6; NFR-01 |
| `test_tc_fr03_03_list_outputs_per_task` | FR-03.AC-3 | FR-03 | `SPEC.md` §3 FR-03 list row | — |
| `test_tc_fr03_04_clear_empties_store` | FR-03.AC-4 | FR-03 | `SPEC.md` §3 FR-03 clear row | NFR-03-AC-1 |
| `test_tc_fr03_05_json_flag_single_line` | FR-03.AC-5 | FR-03 | `SPEC.md` §3 FR-03 --json bullet | — |
| `test_tc_fr03_06_exit_code_matrix` | FR-03.AC-6 | FR-03 | `SPEC.md` §3 FR-03 Exit codes bullet | — |
| `test_tc_nfr01_01_p95_under_50ms` | NFR-01-AC-1 | NFR-01 | `SPEC.md` §4 NFR-01 | FR-01.AC-4; FR-03.AC-1 |
| `test_tc_nfr02_01_no_shell_true_grep` | NFR-02-AC-1 | NFR-02 | `SPEC.md` §4 NFR-02 first clause | FR-02.AC-1 |
| `test_tc_nfr02_02a_reject_semicolon` | NFR-02-AC-2 | NFR-02 | `SPEC.md` §4 NFR-02 second clause | FR-01.AC-3 |
| `test_tc_nfr02_02b_reject_pipe` | NFR-02-AC-2 | NFR-02 | `SPEC.md` §4 NFR-02 second clause | FR-01.AC-3 |
| `test_tc_nfr02_02c_reject_ampersand` | NFR-02-AC-2 | NFR-02 | `SPEC.md` §4 NFR-02 second clause | FR-01.AC-3 |
| `test_tc_nfr02_02d_reject_dollar` | NFR-02-AC-2 | NFR-02 | `SPEC.md` §4 NFR-02 second clause | FR-01.AC-3 |
| `test_tc_nfr02_02e_reject_gt` | NFR-02-AC-2 | NFR-02 | `SPEC.md` §4 NFR-02 second clause | FR-01.AC-3 |
| `test_tc_nfr02_02f_reject_lt` | NFR-02-AC-2 | NFR-02 | `SPEC.md` §4 NFR-02 second clause | FR-01.AC-3 |
| `test_tc_nfr02_02g_reject_backtick` | NFR-02-AC-2 | NFR-02 | `SPEC.md` §4 NFR-02 second clause | FR-01.AC-3 |
| `test_tc_nfr03_01_atomic_write_crash_recovery` | NFR-03-AC-1 | NFR-03 | `SPEC.md` §4 NFR-03 first clause | FR-01.AC-4; FR-01.AC-5 |
| `test_tc_nfr03_02a_redact_sk_line` | NFR-03-AC-2 | NFR-03 | `SPEC.md` §4 NFR-03 second clause (regex branch 1) | FR-02.AC-3 |
| `test_tc_nfr03_02b_redact_token_line` | NFR-03-AC-2 | NFR-03 | `SPEC.md` §4 NFR-03 second clause (regex branch 2) | FR-02.AC-3 |

---

## 5. Cross-Cutting Bindings

Cross-cutting bindings are signalled explicitly in `TEST_INVENTORY.yaml` via `cross_ref_ac_ids` and `cross_ref_nfrs` metadata. The matrix preserves every binding as a row here so reviewers can audit the coupling at a glance.

| Binding | Source AC | Target AC / NFR | TC Pair | Binding Rationale |
|---------|-----------|-----------------|---------|-------------------|
| FR-01.AC-3 ↔ NFR-02-AC-2 (per-char) | FR-01 injection-char reject | NFR-02 injection-char blacklist coverage | `test_tc_fr01_03_reject_injection_chars` (all 7 chars) ↔ `test_tc_nfr02_02a..g` (per-char breakdown) | FR-01 enforces the reject; NFR-02 demands explicit per-char test coverage |
| FR-02.AC-1 ↔ NFR-02-AC-1 | FR-02 subprocess call site | NFR-02 codebase-wide `shell=True` prohibition | `test_tc_fr02_01_subprocess_no_shell` (unit) ↔ `test_tc_nfr02_01_no_shell_true_grep` (AST scan) | FR-02 fixes the call site; NFR-02 audits the entire codebase for regression |
| FR-01.AC-4 ↔ NFR-03-AC-1 | FR-01 valid submit atomic write | NFR-03 atomic-write crash recovery | `test_tc_fr01_04_valid_submit_writes_pending` (happy-path atomicity) ↔ `test_tc_nfr03_01_atomic_write_crash_recovery` (chaos test) | FR-01 asserts atomic write contract; NFR-03 verifies the contract holds under mid-write interruption |
| FR-02.AC-3 ↔ NFR-03-AC-2 | FR-02 result-field capture | NFR-03 secret-line redaction pre-persist | `test_tc_fr02_02_result_fields_persisted` (field shape) ↔ `test_tc_nfr03_02a_redact_sk_line` + `test_tc_nfr03_02b_redact_token_line` (redaction pre-persist) | FR-02 captures raw stdout/stderr; NFR-03 redacts before persist — the redact hook MUST be invoked at the field-capture boundary |
| FR-01.AC-7 ↔ NFR-03-AC-1 | FR-01 corrupt-store detection | NFR-03 atomic-write survives interruption | `test_tc_fr01_05_corrupt_store_exits_one` (detect) ↔ `test_tc_nfr03_01_atomic_write_crash_recovery` (prevent) | FR-01 fails closed on corrupt state; NFR-03 prevents the corruption in the first place |
| FR-02.AC-2 ↔ FR-03.AC-6 (final-status branch) | FR-02 state machine | FR-03 exit-code matrix | `test_tc_fr02_03_retry_on_failed_or_timeout` (state assertions) ↔ `test_tc_fr03_06_exit_code_matrix` (process-exit mapping) | The state machine's final status is the input to the exit-code matrix |
| FR-03.AC-2 ↔ NFR-01 | FR-03 status lookup latency | NFR-01 perf budget includes status | `test_tc_fr03_02_status_outputs_or_unknown` ↔ `test_tc_nfr01_01_p95_under_50ms` | Status is one of the two operations measured by NFR-01's 100-iter cycle |
| FR-01.AC-4 ↔ NFR-01 | FR-01 valid submit latency | NFR-01 perf budget includes submit | `test_tc_fr01_04_valid_submit_writes_pending` ↔ `test_tc_nfr01_01_p95_under_50ms` | Submit is one of the two operations measured by NFR-01's 100-iter cycle |
| FR-03.AC-4 ↔ NFR-03-AC-1 | FR-03 clear empties store | NFR-03 atomic-write survives interruption | `test_tc_fr03_04_clear_empties_store` ↔ `test_tc_nfr03_01_atomic_write_crash_recovery` | Clear MUST use the atomic-write path (not direct overwrite) |

---

## 6. Coverage Validation

### 6.1 Forward Coverage (AC → TC)

Every AC in `SRS.md` §5 (25 ACs) is covered by ≥1 TC in `TEST_INVENTORY.yaml` §3:

| FR / NFR | AC Count | TC Count (enumerated) | Coverage |
|----------|----------|-----------------------|----------|
| FR-01 | 7 | 5 (with sub-cases via NFR-02 per-char cross-ref) | 100% |
| FR-02 | 6 | 5 | 100% (each TC verifies ≥1 AC; FR-02.AC-2 verified across 3 TCs) |
| FR-03 | 6 | 6 | 100% (1:1) |
| NFR-01 | 1 | 1 | 100% (1:1) |
| NFR-02 | 2 | 8 (1 grep + 7 per-char) | 100% (AC-1 → 1 TC; AC-2 → 7 per-char TCs) |
| NFR-03 | 2 | 3 (1 atomic + 2 redaction) | 100% (AC-1 → 1 TC; AC-2 → 2 sub-case TCs) |
| **Total** | **24** | **28** | **100%** (every AC has ≥1 TC; sub-case expansion is documented in §3.5 and §3.6) |

> Note on totals: `SRS.md` §5 reports 25 ACs (24 row-level AC IDs + 1 NFR-01 row-level anchor). The matrix uses the AC-ID-based count of **24**. All 24 AC IDs have ≥1 TC; the +1 in `SRS.md` §5 is the row-level NFR-01 anchor itself (not a separate AC), reconciled per `SPEC_TRACKING.md` §2.1.

### 6.2 Backward Coverage (TC → AC)

Every TC in `TEST_INVENTORY.yaml` §3 (28 TCs) is traceable to ≥1 AC in `SRS.md` §5:

| TC Bucket | TC Count | AC Verification |
|-----------|----------|-----------------|
| FR-01 TCs | 5 | FR-01.AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7 (all 7 covered) |
| FR-02 TCs | 5 | FR-02.AC-1, AC-2, AC-3, AC-4, AC-5, AC-6 (all 6 covered) |
| FR-03 TCs | 6 | FR-03.AC-1, AC-2, AC-3, AC-4, AC-5, AC-6 (all 6 covered, 1:1) |
| NFR-01 TCs | 1 | NFR-01-AC-1 |
| NFR-02 TCs | 8 | NFR-02-AC-1 (grep) + NFR-02-AC-2 (7 per-char) |
| NFR-03 TCs | 3 | NFR-03-AC-1 (atomic) + NFR-03-AC-2 (2 redaction branches) |

### 6.3 No-Gap Validation

| Check | Status | Evidence |
|-------|--------|----------|
| Every AC has ≥1 TC | PASS | §6.1 table |
| Every TC has ≥1 AC | PASS | §6.2 table; no orphan TCs |
| No invented AC IDs | PASS | All AC IDs trace to `SRS.md` §5 verbatim |
| No invented TC IDs | PASS | All TC IDs trace to `TEST_INVENTORY.yaml` §3 verbatim |
| No invented module owners | PASS | All `design_element` fields match `SPEC_TRACKING.md` §2.2 + `TEST_INVENTORY.yaml` §2.2 verbatim |
| Forward + backward symmetric | PASS | §6.1 and §6.2 reconcile to the same 24 AC ↔ 28 TC mapping |
| Cross-cutting signalled (not collapsed) | PASS | §5 binds every cross-cutting AC pair via `cross_ref_*` metadata |

### 6.4 Gate 3 Exit Readiness

Per `SPEC_TRACKING.md` §4, Gate 3 (P4 exit) requires: full phase testing + verification quality. The matrix enables Gate 3 by:
1. Every `verification_locus` column maps a TC to a TDD state-machine + gate sequence (TDD-RED → TDD-GREEN → GATE1 → GATE2 → BASELINE → GATE4).
2. Coverage is 100% at both AC and TC endpoints (no gaps).
3. Cross-cutting bindings are explicit, so a failure in `test_tc_fr01_03_reject_injection_chars` is automatically correlated with the 7 NFR-02 per-char TCs that share the same module (`taskq.validate.check_injection_chars`).

---

## 7. No-Invention Discipline

This matrix introduces:
- **0 new ACs** beyond `SRS.md` §5.
- **0 new TCs** beyond `TEST_INVENTORY.yaml` §3.
- **0 new module owners** beyond `SPEC_TRACKING.md` §2.2.
- **0 new FRs/NFRs** beyond `SPEC.md` §3-§4.

All cross-cutting bindings, verification-locus assignments, and design-element references are derived 1:1 from the approved upstream documents. Any future amendment MUST originate in `SPEC.md` and propagate through `SRS.md` → `SPEC_TRACKING.md` → this matrix → `TEST_INVENTORY.yaml` in that order.

---

## 8. Update Discipline

- This file is updated by **Agent A (Requirements Engineer)** at end of each Phase 1 round.
- AC IDs (`AC-FR**-NN**`, `AC-NFR**-NN**`) and TC IDs (`TC-FR**-NN**`, `TC-NFR**-NN**`) are stable identifiers — never renumbered, never collapsed.
- New ACs require `SPEC.md` amendment; new TCs require matrix §3 first, then YAML enumeration.
- Status transitions are appended to `.harness/traces/agent_trajectory.jsonl`.
- Read-only consumers: Agent B (Architecture), Agent C (Implementation / Phase 3), Agent D (Testing / Phase 4).

---

## 9. AC ↔ TC Coverage Reconciliation (SRS §5 ↔ YAML §3)

This reconciliation table is the **single source of truth** for the AC ↔ TC mapping. It is the binding contract between requirements (Agent A) and implementation (Agent C) / testing (Agent D).

| AC ID (canonical) | SRS §3 / §4 anchor | TC ID (canonical, from YAML §3) | YAML §3 subsection | Cross-Ref TCs |
|-------------------|--------------------|----------------------------------|---------------------|----------------|
| AC-FR01-01 | FR-01 驗證規則 非空 | `test_tc_fr01_01_reject_empty_or_whitespace` | §3.1 FR-01 | FR-03.AC-6 |
| AC-FR01-02 | FR-01 驗證規則 長度 | `test_tc_fr01_02_reject_overlong` | §3.1 FR-01 | FR-03.AC-6 |
| AC-FR01-03 | FR-01 驗證規則 注入字元 | `test_tc_fr01_03_reject_injection_chars` | §3.1 FR-01 | NFR-02-AC-2 (per-char) |
| AC-FR01-04 | FR-01 通過驗證 bullet 1 | `test_tc_fr01_04_valid_submit_writes_pending` | §3.1 FR-01 | FR-03.AC-6; NFR-01; NFR-03-AC-1 |
| AC-FR01-05 | FR-01 通過驗證 bullet 2 | `test_tc_fr01_04_valid_submit_writes_pending` (shared) | §3.1 FR-01 | FR-03.AC-6; NFR-01 |
| AC-FR01-06 | FR-01 通過驗證 bullet 3 | `test_tc_fr01_04_valid_submit_writes_pending` (shared) + `test_tc_nfr03_01_atomic_write_crash_recovery` | §3.1 FR-01 / §3.6 NFR-03 | NFR-03-AC-1 |
| AC-FR01-07 | FR-01 通過驗證 bullet 4 | `test_tc_fr01_05_corrupt_store_exits_one` | §3.1 FR-01 | FR-03.AC-6; NFR-03-AC-1 |
| AC-FR02-01 | FR-02 first bullet | `test_tc_fr02_01_subprocess_no_shell` | §3.2 FR-02 | NFR-02-AC-1 |
| AC-FR02-02 | FR-02 state machine bullet | `test_tc_fr02_01_subprocess_no_shell` (subprocess call) + `test_tc_fr02_03_retry_on_failed_or_timeout` (final-status assertion) + `test_tc_fr02_04_timeout_exit_4` (timeout state) | §3.2 FR-02 | FR-03.AC-6 |
| AC-FR02-03 | FR-02 result fields bullet | `test_tc_fr02_02_result_fields_persisted` | §3.2 FR-02 | NFR-03-AC-2 |
| AC-FR02-04 | FR-02 retry bullet | `test_tc_fr02_03_retry_on_failed_or_timeout` | §3.2 FR-02 | — |
| AC-FR02-05 | FR-02 single-task-timeout bullet | `test_tc_fr02_04_timeout_exit_4` | §3.2 FR-02 | FR-03.AC-6 |
| AC-FR02-06 | FR-02 exception bullet | `test_tc_fr02_05_unexpected_exception_exit_1` | §3.2 FR-02 | FR-03.AC-6 |
| AC-FR03-01 | FR-03 command table | `test_tc_fr03_01_argparse_subcommands` | §3.3 FR-03 | FR-03.AC-5 |
| AC-FR03-02 | FR-03 status row | `test_tc_fr03_02_status_outputs_or_unknown` | §3.3 FR-03 | FR-03.AC-6; NFR-01 |
| AC-FR03-03 | FR-03 list row | `test_tc_fr03_03_list_outputs_per_task` | §3.3 FR-03 | — |
| AC-FR03-04 | FR-03 clear row | `test_tc_fr03_04_clear_empties_store` | §3.3 FR-03 | NFR-03-AC-1 |
| AC-FR03-05 | FR-03 --json bullet | `test_tc_fr03_05_json_flag_single_line` | §3.3 FR-03 | — |
| AC-FR03-06 | FR-03 Exit codes bullet | `test_tc_fr03_06_exit_code_matrix` | §3.3 FR-03 | — |
| AC-NFR01-01 | NFR-01 | `test_tc_nfr01_01_p95_under_50ms` | §3.4 NFR-01 | FR-01.AC-4; FR-03.AC-1 |
| AC-NFR02-01 | NFR-02 first clause | `test_tc_nfr02_01_no_shell_true_grep` | §3.5 NFR-02 | FR-02.AC-1 |
| AC-NFR02-02 | NFR-02 second clause | `test_tc_nfr02_02a..g` (7 sub-cases) | §3.5 NFR-02 | FR-01.AC-3 |
| AC-NFR03-01 | NFR-03 first clause | `test_tc_nfr03_01_atomic_write_crash_recovery` | §3.6 NFR-03 | FR-01.AC-4; FR-01.AC-5 |
| AC-NFR03-02 | NFR-03 second clause | `test_tc_nfr03_02a_redact_sk_line` + `test_tc_nfr03_02b_redact_token_line` | §3.6 NFR-03 | FR-02.AC-3 |

---

## 10. Round Provenance

- **Round 1 entry** (2026-06-29): initial matrix built from approved `SRS.md` v1.0.0 and `SPEC_TRACKING.md` v1.0.0; TC mappings derived from `TEST_INVENTORY.yaml` v5.0.0 (Round 5 B-2 fixes applied).
- **Scope discipline**: 0 invented ACs, 0 invented TCs, 0 invented module owners; every row traces to a canonical `SPEC.md` anchor.

---

*End of Traceability Matrix — taskq v1.0.0 (Round 1 entry, 2026-06-29).*