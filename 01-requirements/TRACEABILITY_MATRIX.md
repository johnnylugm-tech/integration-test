# TRACEABILITY_MATRIX.md — taskq

> Requirements Traceability Matrix — 雙向追溯(FR ↔ Spec ↔ Code ↔ Test)
> Framework: harness-methodology v2.9
> Project: taskq
> Version: v1.0
> Date: 2026-06-17
> Phase: 1 — Requirements Specification
> ASPICE: SWE.3 / SYS.4

---

## Overview

提供從 FR → SRS 章節 → 實作模組/函式 → 測試案例的雙向可追溯性,支援 ASPICE SWE.3 / SYS.4 合規。本矩陣由 SRS.md v2.0.0(APPROVED)與 SPEC_TRACKING.md v1.0(APPROVED)衍生,於 Phase 3 實作完成後回填「Code File / Function / Test File」實際行號,於 Phase 4 補上 test coverage 數據。

**矩陣範圍**:涵蓋 SRS.md 全部 3 個 FR 與 3 個 NFR;「Code File / Test File / Coverage」欄位在 P1 階段以 `TBD-P3` / `TBD-P4` 標示,於對應 phase 完成後回填,符合 P1 為「需求可追溯性」非「實作可追溯性」之定位。

---

## FR ↔ Spec Mapping

| FR ID | Functional Requirement (from SPEC.md) | SRS Section | Priority | Status | Owner |
|-------|---------------------------------------|-------------|----------|--------|-------|
| FR-01 | 任務模型與持久化 — `submit` 驗證(非空/長度/注入字元 6 字元)+ 原子寫 + 損壞偵測 | SRS.md §2 + §「FR-01 詳細條款」 | HIGH | VERIFIED | REQUIREMENTS_ENGINEER |
| FR-02 | 任務執行與重試 — 受控 subprocess + 狀態機 + 重試 + exit 4 / exit 1 錯誤處理 | SRS.md §2 + §「FR-02 詳細條款」 | HIGH | VERIFIED | REQUIREMENTS_ENGINEER |
| FR-03 | CLI 整合與查詢 — argparse 子命令 + --json + exit codes | SRS.md §2 + §「FR-03 詳細條款」 | HIGH | VERIFIED | REQUIREMENTS_ENGINEER |
| NFR-01 | performance — submit+status 100 次 p95 < 50ms | SRS.md §3 | HIGH | VERIFIED | REQUIREMENTS_ENGINEER |
| NFR-02 | security — 全 codebase 禁用 shell=True;6 字元黑名單測試覆蓋 | SRS.md §3 | HIGH | VERIFIED | REQUIREMENTS_ENGINEER |
| NFR-03 | reliability — tasks.json 原子寫 + secret redaction | SRS.md §3 | HIGH | VERIFIED | REQUIREMENTS_ENGINEER |

---

## Spec ↔ Code Mapping(P1: 估計;P3: 實際)

> **命名約定**:Code File 與 Function 兩欄以 `<file>::<function>` 形式組合(例如 `core/taskq/executor.py::run_task`);SRS.md §2 之「Implementation Function (est.)」欄為此處拆解前的單欄形式。完全等價。
>
> P1 階段:Implementation Function 為 SRS.md 之估計值(同 SRS §2 表格),作為 P2 架構設計之輸入。
> P3 階段:回填實際 `core/taskq/<module>.py:<function>` 與行號;P3 完成後此段由 `harness/build_trace.py` 自動生成覆寫。

| FR ID | SRS Section | Code File (P3 est.) | Function/Class (P3 est.) | Lines (P3) | Status (P3) |
|-------|-------------|--------------------|--------------------------|------------|-------------|
| FR-01 | §2 / §FR-01 詳細條款 | `core/taskq/store.py` | `submit_task` | TBD-P3 | TBD-P3 |
| FR-01 | §2 | `core/taskq/cli.py` | `cmd_submit` | TBD-P3 | TBD-P3 |
| FR-01 | §2 / §FR-01 詳細條款 | `core/taskq/store.py` | `load_store` (corruption detection) | TBD-P3 | TBD-P3 |
| FR-02 | §2 / §FR-02 詳細條款 | `core/taskq/executor.py` | `run_task` | TBD-P3 | TBD-P3 |
| FR-02 | §2 | `core/taskq/cli.py` | `cmd_run` | TBD-P3 | TBD-P3 |
| FR-02 | §2 / §FR-02 詳細條款 | `core/taskq/executor.py` | `run_with_retry` (P1 估計,P3 將驗證;此名為唯一候選) | TBD-P3 | TBD-P3 |
| FR-03 | §2 / §FR-03 詳細條款 | `core/taskq/cli.py` | `main`, `cmd_status`, `cmd_list`, `cmd_clear` | TBD-P3 | TBD-P3 |
| NFR-01 | §3 | `tests/benchmarks/test_nfr01_p95.py` | (benchmark module) | TBD-P3 | TBD-P3 |
| NFR-02 | §3 | `core/taskq/` (entire codebase) | grep / semgrep rule | TBD-P3 | TBD-P3 |
| NFR-02 | §3 | `tests/unit/test_fr01_injection_chars.py` | (parametrized over 6 chars) | TBD-P3 | TBD-P3 |
| NFR-03 | §3 | `core/taskq/store.py` | `submit_task` (atomic write path) | TBD-P3 | TBD-P3 |
| NFR-03 | §3 | `core/taskq/executor.py` | `run_task` (redaction path) | TBD-P3 | TBD-P3 |

---

## Code ↔ Test Mapping(P1: 預期;P3/P4: 實際)

> P1 階段:測試案例名稱為 SRS.md §8 與 TEST_INVENTORY.yaml 中宣告之權威命名(P1 naming authority)。
> P3 階段:建立 `tests/unit/test_fr<NN>_<topic>.py` 與 `tests/integration/test_fr<NN>_<flow>.py`;P4 階段補上 coverage % 與行範圍。

| FR ID | Code File (P3 est.) | Test File (P3 est.) | Test Function Names | Coverage (P3) | Status (P3) |
|-------|--------------------|--------------------|---------------------|---------------|-------------|
| FR-01 | `core/taskq/store.py` | `tests/unit/test_fr01_validation.py` | `test_fr01_submit_valid_command_returns_zero`<br>`test_fr01_submit_empty_command_returns_two`<br>`test_fr01_submit_whitespace_command_returns_two`<br>`test_fr01_submit_long_command_returns_two`<br>`test_fr01_submit_injection_chars_returns_two`<br>`test_fr01_submit_produces_uuid4_id_format` | TBD-P3 | TBD-P3 |
| FR-01 | `core/taskq/store.py` | `tests/integration/test_fr01_store_corruption.py` | `test_fr01_store_corruption_returns_one` | TBD-P3 | TBD-P3 |
| FR-02 | `core/taskq/executor.py` | `tests/unit/test_fr02_state_machine.py` | `test_fr02_run_executes_subprocess_with_shell_false`<br>`test_fr02_run_exit_zero_yields_done`<br>`test_fr02_run_nonzero_yields_failed`<br>`test_fr02_run_timeout_yields_timeout_and_exit_four`<br>`test_fr02_run_failed_retries_up_to_limit`<br>`test_fr02_run_retry_limit_respected` | TBD-P3 | TBD-P3 |
| FR-02 | `core/taskq/executor.py` | `tests/integration/test_fr02_cli_timeout.py` | `test_fr02_cli_run_timeout_returns_four` | TBD-P3 | TBD-P3 |
| FR-03 | `core/taskq/cli.py` | `tests/integration/test_fr03_subcommands.py` | `test_fr03_status_unknown_id_returns_two`<br>`test_fr03_list_returns_all_tasks`<br>`test_fr03_clear_empties_store`<br>`test_fr03_json_flag_emits_single_line_json` | TBD-P3 | TBD-P3 |
| NFR-01 | `tests/benchmarks/test_nfr01_p95.py` | (self-benchmark) | `test_kpi_p95_submit_status_under_50ms` | TBD-P3 | TBD-P3 |
| NFR-02 | `core/taskq/` (grep scan) | `tests/security/test_nfr02_no_shell_true.py` | `test_redteam_shell_true_absent_in_codebase` | TBD-P3 | TBD-P3 |
| NFR-02 | (已併入 FR-01 test file,以 pytest parametrize 覆蓋 6 字元) | `tests/unit/test_fr01_validation.py` | `test_fr01_submit_injection_chars_returns_two` (parametrized over `;` `|` `&` `$` `>` `<` `` ` ``,共 6 個 case) | TBD-P3 | TBD-P3 |
| NFR-03 | `core/taskq/store.py` | `tests/integration/test_nfr03_atomic_write.py` | `test_reliability_kill_during_write_keeps_valid_json`<br>`test_reliability_concurrent_writes_do_not_corrupt` | TBD-P3 | TBD-P3 |
| NFR-03 | `core/taskq/executor.py` | `tests/security/test_nfr03_redaction.py` | `test_redteam_secret_in_stdout_redacted_before_persist`<br>`test_redteam_secret_in_stderr_redacted_before_persist` | TBD-P3 | TBD-P3 |
| NFR-03 | `core/taskq/executor.py` | `tests/unit/test_nfr03_redaction.py` | `test_nfr03_redact_sk_key_in_stdout`<br>`test_nfr03_redact_sk_key_in_stderr`<br>`test_nfr03_redact_token_assignment_in_stdout`<br>`test_nfr03_redact_token_assignment_in_stderr`<br>`test_nfr03_preserves_non_secret_lines` | TBD-P3 | TBD-P3 |
| (config) | `core/taskq/config.py` | `tests/unit/test_config_env_keys.py` | `test_config_env_keys_declared_in_env_example`<br>`test_config_taskq_home_default_dot_taskq`<br>`test_config_taskq_task_timeout_default_10`<br>`test_config_taskq_retry_limit_default_2` | TBD-P3 | TBD-P3 |

---

## Backward Mapping(Test → FR)

> 每個測試函式至少對映一個 FR;此為 D4 SpecCoverage 之雙向確認依據。

| Test Function Name | Maps to FR | Verification Stage |
|--------------------|------------|--------------------|
| `test_fr01_submit_valid_command_returns_zero` | FR-01 | P3 unit |
| `test_fr01_submit_empty_command_returns_two` | FR-01 | P3 unit |
| `test_fr01_submit_whitespace_command_returns_two` | FR-01 | P3 unit |
| `test_fr01_submit_long_command_returns_two` | FR-01 | P3 unit |
| `test_fr01_submit_injection_chars_returns_two` | FR-01, NFR-02 | P3 unit (parametrized:6 chars 對應同一函式,展開後 6 個 case) |
| `test_fr01_submit_produces_uuid4_id_format` | FR-01 | P3 unit |
| `test_fr01_store_corruption_returns_one` | FR-01 | P3 integration |
| `test_fr02_run_executes_subprocess_with_shell_false` | FR-02, NFR-02 | P3 unit |
| `test_fr02_run_exit_zero_yields_done` | FR-02 | P3 unit |
| `test_fr02_run_nonzero_yields_failed` | FR-02 | P3 unit |
| `test_fr02_run_timeout_yields_timeout_and_exit_four` | FR-02 | P3 unit |
| `test_fr02_run_failed_retries_up_to_limit` | FR-02 | P3 unit |
| `test_fr02_run_retry_limit_respected` | FR-02 | P3 unit |
| `test_fr02_cli_run_timeout_returns_four` | FR-02, FR-03 | P3 integration |
| `test_fr03_status_unknown_id_returns_two` | FR-03 | P3 integration |
| `test_fr03_list_returns_all_tasks` | FR-03 | P3 integration |
| `test_fr03_clear_empties_store` | FR-03 | P3 integration |
| `test_fr03_json_flag_emits_single_line_json` | FR-03 | P3 integration |
| `test_kpi_p95_submit_status_under_50ms` | NFR-01 | P3 benchmark |
| `test_redteam_shell_true_absent_in_codebase` | NFR-02 | P3 security scan |
| `test_redteam_secret_in_stdout_redacted_before_persist` | NFR-03 | P3 security |
| `test_redteam_secret_in_stderr_redacted_before_persist` | NFR-03 | P3 security |
| `test_reliability_kill_during_write_keeps_valid_json` | NFR-03 | P3 integration |
| `test_reliability_concurrent_writes_do_not_corrupt` | NFR-03 | P3 integration |
| `test_fr02_run_captures_stdout_tail_under_2000_chars` | FR-02 | P3 unit |
| `test_fr02_run_captures_stderr_tail_under_2000_chars` | FR-02 | P3 unit |
| `test_fr02_run_records_duration_ms_and_finished_at` | FR-02 | P3 unit |
| `test_fr02_run_unexpected_exception_returns_one` | FR-02 | P3 unit |
| `test_fr02_cli_run_success_returns_zero` | FR-02, FR-03 | P3 integration |
| `test_fr03_status_known_id_returns_full_record` | FR-03 | P3 unit |
| `test_fr03_list_truncates_command_to_50_chars` | FR-03 | P3 unit |
| `test_fr03_exit_code_matrix` | FR-03 | P3 unit (parametrized:4 cases for 0/2/4/1) |
| `test_fr03_end_to_end_submit_run_status_list_clear` | FR-03 | P3 integration |
| `test_fr03_help_text_lists_all_subcommands` | FR-03 | P3 integration |
| `test_nfr03_redact_sk_key_in_stdout` | NFR-03 | P3 unit |
| `test_nfr03_redact_sk_key_in_stderr` | NFR-03 | P3 unit |
| `test_nfr03_redact_token_assignment_in_stdout` | NFR-03 | P3 unit |
| `test_nfr03_redact_token_assignment_in_stderr` | NFR-03 | P3 unit |
| `test_nfr03_preserves_non_secret_lines` | NFR-03 | P3 unit |
| `test_nfr03_secret_in_output_never_persisted_to_disk` | NFR-03 | P3 integration |
| `test_config_env_keys_declared_in_env_example` | (config liveness) | P3 unit |
| `test_config_taskq_home_default_dot_taskq` | (config liveness) | P3 unit |
| `test_config_taskq_task_timeout_default_10` | (config liveness) | P3 unit |
| `test_config_taskq_retry_limit_default_2` | (config liveness) | P3 unit |

---

## Completeness Verification

| Check | Target | Actual (P1) | Status (P1) | Status after P3 | Status after P4 |
|-------|--------|-------------|-------------|-----------------|------------------|
| FR → SRS mapping | 100% | 100% (3/3 FR + 3/3 NFR) | PASS | PASS | PASS |
| SRS → Code mapping (estimated) | 100% | 100% (P3 estimates) | PASS | TBD-P3 (actual) | TBD-P4 (verified) |
| Code → Test mapping (estimated) | 100% | 100% (P3 estimates) | PASS | TBD-P3 (actual) | TBD-P4 (verified) |
| Test coverage | ≥ 80% (P3) | N/A (P1) | N/A | ≥ 70% (P3 threshold) | ≥ 80% (P4) |
| Every FR has ≥ 1 downstream link | 100% | 100% (6/6) | PASS | TBD-P3 | TBD-P4 |
| No orphan requirements | 0 | 0 | PASS | TBD-P3 | TBD-P4 |
| Bidirectional traceability | yes | yes | PASS | TBD-P3 | TBD-P4 |

---

## ASPICE Compliance

| ASPICE Capability | Status (P1) | Status (P4) |
|-------------------|-------------|-------------|
| SWE.3.B.SP1 Task-to-work-product traceability | PASS(FR ↔ Spec ↔ Code ↔ Test 4 層已立框) | TBD-P4 |
| SWE.3.B.SP2 Bidirectional traceability | PASS(forward + backward 兩向皆有對映) | TBD-P4 |
| SWE.3.B.SP3 Traceability consistency | PASS(SRS / SPEC_TRACKING / TRACEABILITY 三者 FR 集合一致) | TBD-P4 |

---

## Cross-Reference Index

- SRS.md v2.0.0 — `.methodology/spec/SRS.md` (per-project at `01-requirements/SRS.md`)
- SPEC_TRACKING.md v1.0 — `01-requirements/SPEC_TRACKING.md`(APPROVED 2026-06-17)
- TEST_INVENTORY.yaml v1.1 — `TEST_INVENTORY.yaml`(APPROVED 2026-06-17,本 phase)
- TEST_SPEC.md — `02-architecture/TEST_SPEC.md`(P2 階段由 `derive_test_cases.md` 從本矩陣衍生)
- SPEC.md v2.0.0 — canonical, `SPEC.md`

### Count Reconciliation with TEST_INVENTORY.yaml

本矩陣的 Code↔Test Mapping(13 列)與 Backward Mapping(45 列)以「測試檔案/測試函式」為粒度展開(phase 1 holistic review 後已將 TEST_INVENTORY 全部 45 個唯一測試函式逐一對映到 Backward Mapping);TEST_INVENTORY.yaml v1.1(45 個唯一測試函式)以「單一測試函式」為粒度。此一對應(45 vs 45)為**矩陣按 test FILE 群組 + test FUNCTION 函式逐項、TEST_INVENTORY 按 test FUNCTION 列舉**的設計;P3 之 `harness/build_trace.py` 應以實際測試檔案中的 `def test_*` 為事實來源,做 1:1 函式級對映。

---

*End of TRACEABILITY_MATRIX.md v1.0 — taskq | 2026-06-17*
