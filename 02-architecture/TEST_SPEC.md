# TEST_SPEC.md — taskq Test Specification Catalog

> Project: `taskq` — local task-queue CLI
> SPEC version: v4.1.0 (5 FR / 10 NFR / 8 env, 2026-07-12)
> Phase: 2 — Architecture
> Companion artifacts: `SPEC.md` (single source of truth), `SRS.md` (requirements), `SAD.md` (architecture baseline), `TEST_INVENTORY.yaml` (P1 baseline; names tagged `SAD:` in the Derivation column are Step 1b architecture-derived additions beyond the P1 inventory).
> Generated via: `derive_test_cases.md` skill v1.1 (harness-methodology v2.9.1)

---

## NFR Pattern Activation Table

Patterns activated by Step 1 (SRS keyword scan) and Step 1b (SAD architecture-risk scan).

| Pattern ID | Trigger source | Activating trait | Applies to FR(s) |
|---|---|---|---|
| NP-04 | SRS: validation / input | FR-01 validation rules (non-empty, length, injection chars, duplicate name) | FR-01, FR-02, FR-05 |
| NP-06 | SRS: performance / latency | p95 latency SLA (NFR-01 submit+status < 50ms, NFR-09 1000-task < 100ms) | FR-01, FR-02, FR-05 |
| NP-07 | SAD: `storage.cache` (Step 1b) | cache / optional dependency — dead-cache-path guard | FR-04 |
| NP-08 | SRS: security / injection | FR-01 injection blacklist + NFR-02 `shell=True` ban | FR-01, FR-02 |
| NP-10 | SRS: data integrity / persist / round-trip | NFR-03 atomic writes + NFR-07 fault injection | FR-01, FR-02, FR-03, FR-04 |
| NP-11 | SRS: version / migration | NFR-10 schema migration | FR-01, FR-02, FR-03, FR-04 |
| NP-13 | SAD: `storage.store` (Step 1b) | shared mutable state + threads/processes — concurrent-load isolation | FR-01, FR-02, FR-03, FR-04 |
| NP-15 | SAD: `runtime.executor` (Step 1b) | external process (subprocess) — timeout enforcement + orphan cleanup | FR-02 |

**Step 1b forced integration variants** (all under `tests/integration/`, tagged `SAD:`):

| Module | Risk trait | Forced pattern | Required integration test |
|---|---|---|---|
| `storage.store` | shared mutable state + Lock/flock | NP-13 | `test_fr02_06_run_all_thread_safety` (existing) |
| `runtime.executor` | external process (subprocess) | NP-15 | `test_fr02_03_timeout_run` (existing), `test_fr02_09_subprocess_orphan_cleanup` |
| `storage.cache` | cache / optional dependency | NP-07 | `test_fr04_07_cache_unavailable_fallback`, `test_fr04_08_cache_recovers_after_transient_outage`, `test_fr04_09_cache_actually_used_on_hit` |

---

## Per-FR Test Specification Catalog

> **SAD: tag convention**: Test function names whose Derivation column ends with `SAD:` are Step 1b architecture-risk derivations (forced by SAD module traits). These extend beyond the P1 TEST_INVENTORY.yaml baseline and are not yet registered in that inventory. All other names match inventory exactly.

### FR-01: 任務提交與驗證

**Classification**: DATA_ENTITY | SECURITY_CONTROL
**Active Patterns**: NP-04, NP-08, NP-10, NP-11, NP-13

| # | Test Function | Inputs | Type | Derivation |
|---|---|---|---|---|
| 1 | `test_fr01_01_happy_submit_echo_hi` | command="echo hi" | happy_path | Q1 |
| 2 | `test_fr01_02_submit_json_output` | command="echo hi"; json="true" | happy_path | Q1/Step 2.5 |
| 3 | `test_fr01_03_submit_empty_command` | command="" | validation | Q2 |
| 4 | `test_fr01_04_submit_whitespace_only` | command="   " | validation | Q2 |
| 5 | `test_fr01_05_submit_too_long` | command="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaab" | validation | Q2/Q3 |
| 6 | `test_fr01_06_submit_injection_semicolon` | command="echo hi; rm x" | validation | Q2/Q8 |
| 7 | `test_fr01_07_submit_injection_chars` | command="echo hi & cat" | validation | Q2/Q8/NP-08 |
| 8 | `test_fr01_08_submit_name_duplicate` | command="echo hi"; name="mytask" | validation | Q2 |
| 9 | `test_fr01_09_submit_atomic_write` | command="echo hi"; fault="oserror-mid-write" | fault_injection | Q5/NP-10 |

**Sub-assertions** (predicate over a case's Inputs / the production `result`):

| rule_id | predicate | applies_to |
|---|---|---|
| FR01-happy-cmd-nonempty | `len(command) > 0` | 1, 2, 8, 9 |
| FR01-happy-cmd-no-injection | `";" not in command and "&" not in command` | 1, 2, 8, 9 |
| FR01-empty-length-zero | `len(command) == 0` | 3 |
| FR01-whitespace-stripped-empty | `command.strip() == ""` | 4 |
| FR01-whitespace-raw-nonempty | `len(command) > 0` | 4 |
| FR01-too-long-gt-1000 | `len(command) > 1000` | 5 |
| FR01-semicolon-present | `";" in command` | 6 |
| FR01-ampersand-present | `"&" in command` | 7 |
| FR01-name-present | `name == "mytask"` | 8 |
| FR01-json-flag-set | `json == "true"` | 2 |

### FR-02: 任務執行器

**Classification**: INTEGRATION | STATE_MACHINE
**Active Patterns**: NP-10, NP-11, NP-13, NP-15

| # | Test Function | Inputs | Type | Derivation |
|---|---|---|---|---|
| 1 | `test_fr02_01_happy_single_run` | command="echo hi" | happy_path | Q1 |
| 2 | `test_fr02_02_failed_run` | command="false" | failure | Q2 |
| 3 | `test_fr02_03_timeout_run` | command="sleep 5"; timeout="1.0" | failure | Q2/NP-15 |
| 4 | `test_fr02_04_stdout_tail_2000_chars` | command="printf '%2048s' ''" | boundary | Q3 |
| 5 | `test_fr02_05_run_all_3_tasks` | command_batch="echo a; echo b; echo c" | happy_path | Q1 |
| 6 | `test_fr02_06_run_all_thread_safety` | command_batch="echo 1; echo 2; echo 3; echo 4; echo 5; echo 6; echo 7; echo 8; echo 9; echo 10" | nfr_pattern | Q6/1b/NP-13 |
| 7 | `test_fr02_07_shell_true_absent` | src_dir="src/taskq" | negative_constraint | Q8/NP-08 |
| 8 | `test_fr02_08_duration_and_finished_at` | command="echo hi" | happy_path | Q1 |
| 9 | `test_fr02_09_subprocess_orphan_cleanup` | command="sleep 100"; timeout="0.1" | fault_injection | Q6/NP-15/SAD: |

**Sub-assertions** (predicate over a case's Inputs / the production `result`):

| rule_id | predicate | applies_to |
|---|---|---|
| FR02-happy-cmd-executable | `len(command) > 0` | 1, 8 |
| FR02-happy-cmd-no-shell-meta | `";" not in command` | 1, 8 |
| FR02-failed-exit-nonzero | `command == "false"` | 2 |
| FR02-timeout-cmd-long | `"sleep" in command` | 3 |
| FR02-timeout-val-low | `timeout == "1.0"` | 3 |
| FR02-tail-cmd-long | `"printf" in command` | 4 |
| FR02-batch-multi | `";" in command_batch` | 5, 6 |
| FR02-shell-true-src-dir | `"taskq" in src_dir` | 7 |
| FR02-orphan-cmd-long | `"sleep" in command and "100" in command` | 9 |

### FR-03: 重試與斷路器

**Classification**: STATE_MACHINE | INTEGRATION
**Active Patterns**: NP-10, NP-11, NP-13

| # | Test Function | Inputs | Type | Derivation |
|---|---|---|---|---|
| 1 | `test_fr03_01_retry_on_failed` | command="false"; retry_limit="2" | happy_path | Q1/Q4 |
| 2 | `test_fr03_02_retry_on_timeout` | command="sleep 5"; timeout="1.0"; retry_limit="2" | happy_path | Q1/Q4 |
| 3 | `test_fr03_03_backoff_sequence` | command="false"; backoff_base="0.1"; retry_limit="2" | happy_path | Q1 |
| 4 | `test_fr03_04_breaker_open` | command="false"; threshold="3" | failure | Q2/Q4 |
| 5 | `test_fr03_05_breaker_half_open_success` | command="echo hi"; cooldown="5.0" | state_transition | Q4 |
| 6 | `test_fr03_06_breaker_half_open_failure` | command="false"; cooldown="5.0" | state_transition | Q4 |
| 7 | `test_fr03_07_breaker_persistence` | command="false"; threshold="3" | integration | Q7/FR-02 |
| 8 | `test_fr03_08_recovery_time` | command="echo hi"; cooldown="5.0" | nfr_pattern | Q6/NP-10 |
| 9 | `test_fr03_09_breaker_open_rejects_no_subprocess` | command="echo hi"; breaker_state="OPEN" | negative_constraint | Q8/NP-13/SAD: |

**Sub-assertions** (predicate over a case's Inputs / the production `result`):

| rule_id | predicate | applies_to |
|---|---|---|
| FR03-retry-failed-cmd | `command == "false"` | 1, 4, 6 |
| FR03-retry-timeout-cmd | `"sleep" in command` | 2 |
| FR03-backoff-base-set | `"0.1" in backoff_base` | 3 |
| FR03-threshold-reached | `threshold == "3"` | 4, 7 |
| FR03-cooldown-set | `"5.0" in cooldown` | 5, 6, 8 |
| FR03-brkr-open-noexec | `breaker_state == "OPEN"` | 9 |

### FR-04: 結果 TTL 快取

**Classification**: DATA_ENTITY
**Active Patterns**: NP-07, NP-10, NP-11, NP-13

| # | Test Function | Inputs | Type | Derivation |
|---|---|---|---|---|
| 1 | `test_fr04_01_cache_hit_fresh` | command="echo hi"; ttl="3600"; cached="true" | happy_path | Q1 |
| 2 | `test_fr04_02_cache_miss_expired` | command="echo hi"; ttl="0" | failure | Q2/Q3 |
| 3 | `test_fr04_03_cache_signature` | command_a="echo hi"; command_b="echo bye" | happy_path | Q1 |
| 4 | `test_fr04_04_only_done_cached` | command="false"; cached="false" | validation | Q2 |
| 5 | `test_fr04_05_cache_atomic_write` | command="echo hi"; fault="oserror-mid-write" | fault_injection | Q5/NP-10 |
| 6 | `test_fr04_06_cache_thread_safety` | command_batch="echo 1; echo 2; echo 3; echo 4; echo 5" | nfr_pattern | Q6/1b/NP-13 |
| 7 | `test_fr04_07_cache_unavailable_fallback` | command="echo hi"; cache_corrupted="true" | fault_injection | Q6/NP-07/SAD: |
| 8 | `test_fr04_08_cache_recovers_after_transient_outage` | command="echo hi"; outage_duration="1.0" | fault_injection | Q6/NP-07/SAD: |
| 9 | `test_fr04_09_cache_actually_used_on_hit` | command="echo hi"; ttl="3600"; cached="true" | fault_injection | Q6/NP-07/SAD: |

**Sub-assertions** (predicate over a case's Inputs / the production `result`):

| rule_id | predicate | applies_to |
|---|---|---|
| FR04-cache-hit-fresh-ttl | `ttl == "3600"` | 1, 9 |
| FR04-cache-hit-cached-flag | `cached == "true"` | 1, 9 |
| FR04-cache-miss-expired-ttl | `ttl == "0"` | 2 |
| FR04-cache-sig-different | `command_a != command_b` | 3 |
| FR04-no-cache-for-failed | `command == "false"` | 4 |
| FR04-no-cache-flag-failed | `cached == "false"` | 4 |
| FR04-fault-at-write | `"oserror" in fault` | 5 |
| FR04-batch-multi | `";" in command_batch` | 6 |
| FR04-cache-corrupted-flag | `cache_corrupted == "true"` | 7 |
| FR04-outage-duration-set | `outage_duration == "1.0"` | 8 |

### FR-05: CLI 整合

**Classification**: INFRASTRUCTURE | INTEGRATION
**Active Patterns**: NP-04, NP-06

| # | Test Function | Inputs | Type | Derivation |
|---|---|---|---|---|
| 1 | `test_fr05_01_status_all_fields` | command="echo hi"; subcommand="status" | happy_path | Q1/Step 2.5 |
| 2 | `test_fr05_02_status_json` | command="echo hi"; subcommand="status"; json="true" | interface_contract | Step 2.5 |
| 3 | `test_fr05_03_list_happy` | command_batch="echo a; echo b; echo c"; subcommand="list" | happy_path | Q1/Step 2.5 |
| 4 | `test_fr05_04_list_filter_done` | command_batch="echo a; echo b; echo c; echo d; echo e"; subcommand="list"; filter_status="done" | happy_path | Q1 |
| 5 | `test_fr05_05_clear` | command="echo hi"; subcommand="clear" | happy_path | Q1/Step 2.5 |
| 6 | `test_fr05_06_unknown_task_id` | task_id="deadbeef"; subcommand="status" | validation | Q2 |
| 7 | `test_fr05_07_exit_code_map` | command="echo hi"; subcommand="run" | integration | Q7/FR-01..04 |

**Sub-assertions** (predicate over a case's Inputs / the production `result`):

| rule_id | predicate | applies_to |
|---|---|---|
| FR05-status-subcommand | `subcommand == "status"` | 1, 2, 6 |
| FR05-list-subcommand | `subcommand == "list"` | 3, 4 |
| FR05-clear-subcommand | `subcommand == "clear"` | 5 |
| FR05-run-subcommand | `subcommand == "run"` | 7 |
| FR05-json-flag-set | `json == "true"` | 2 |
| FR05-unknown-id-hex | `len(task_id) == 8` | 6 |
| FR05-filter-status-done | `filter_status == "done"` | 4 |

---

## Cross-Cutting Test Cases

> **Architecture-derived**: The C1-C3 and D1-D2 test names below are architecture-derived integration/smoke cases not present in the P1 TEST_INVENTORY.yaml baseline (`cross_cutting: {}`). They verify end-to-end CLI wiring and import/help contracts that emerge from the SAD module graph. D3 name matches the NFR-06 inventory entry (`test_nfr06_01_env_example_all_eight_vars`).

### Infrastructure and Middleware Integration

The following tests verify that infrastructure components are physically wired through the CLI entry point (`python -m taskq`), not only in isolation.

| # | Test Function | Inputs | Type | Derivation |
|---|---|---|---|---|
| C1 | `test_cli_submit_run_status_pipeline` | command="echo pipeline-test" | integration | Q7/FR-01+02+05 |
| C2 | `test_cli_clear_then_submit` | command="echo after-clear" | integration | Q7/FR-01+05 |
| C3 | `test_cli_run_all_with_cache` | command_batch="echo a; echo b; echo c"; cached="true" | integration | Q7/FR-02+04+05 |

**Sub-assertions** (predicate over a case's Inputs / the production `result`):

| rule_id | predicate | applies_to |
|---|---|---|
| CC-pipeline-cmd | `len(command) > 0` | C1, C2 |
| CC-cache-batch-multi | `";" in command_batch` | C3 |
| CC-cache-flag-set | `cached == "true"` | C3 |

### NFR Integration (System-Level)

The 8 tests below cover 8 of the 10 NFRs with a runtime integration surface. NFR-05 (docstring `[FR-XX]` convention) is a static lint check enforced in Gate 1 — it has no runtime integration surface and therefore no system-level test entry in this section; its two test cases (`test_nfr05_01_docstring_full_coverage`, `test_nfr05_02_docstring_cites_upstream`) are enumerated in the Deferred NFR Test Cases section below. NFR-06 (deployability; centralized env reading) is covered via D3 (`test_nfr06_01_env_example_all_eight_vars`) in the Deployment Smoke section below; its remaining unit test (`test_nfr06_02_config_centralized_read`) is deferred.

| # | Test Function | Inputs | Type | Derivation |
|---|---|---|---|---|
| N1 | `test_nfr01_01_submit_status_p95_under_50ms` | command="echo perf-test"; iterations="100" | nfr_pattern | Q6/NP-06 |
| N2 | `test_nfr02_02_injection_chars_blacklist` | char_list=";\|&$><`" | nfr_pattern | Q6/NP-08 |
| N3 | `test_nfr03_01_three_files_atomic_write` | fault="oserror-mid-write"; files="tasks.json;breaker.json;cache.json" | nfr_pattern | Q6/NP-10 |
| N4 | `test_nfr04_01_redact_sk_pattern` | secret_line="sk-abcdef1234567890" | nfr_pattern | Q6/NP-08 |
| N5 | `test_nfr07_01_fault_corrupt_mid_write` | fault="corrupt-mid-write"; file="tasks.json" | nfr_pattern | Q6/NP-07 |
| N6 | `test_nfr08_01_four_process_concurrent` | process_count="4"; command="echo concurrent" | nfr_pattern | Q6/NP-13 |
| N7 | `test_nfr09_01_thousand_tasks_p95` | command="echo scale-test"; iterations="1000" | nfr_pattern | Q6/NP-06 |
| N8 | `test_nfr10_01_version_field_present` | file="tasks.json"; version="1" | nfr_pattern | Q6/NP-11 |

**Sub-assertions** (predicate over a case's Inputs / the production `result`):

| rule_id | predicate | applies_to |
|---|---|---|
| CC-nfr-perf-iter | `iterations == "100"` | N1 |
| CC-nfr-injection-chars | `";" in char_list` | N2 |
| CC-nfr-fault-files | `";" in files` | N3 |
| CC-nfr-secret-sk | `"sk-" in secret_line` | N4 |
| CC-nfr-corrupt-fault | `"corrupt" in fault` | N5 |
| CC-nfr-concurrent-count | `process_count == "4"` | N6 |
| CC-nfr-scale-iter | `iterations == "1000"` | N7 |
| CC-nfr-version-field | `version == "1"` | N8 |

### Deployment Smoke

| # | Test Function | Inputs | Type | Derivation |
|---|---|---|---|---|
| D1 | `test_app_module_imports` | module_name="taskq" | interface_contract | Step 2.5 |
| D2 | `test_cli_help_output` | argv="--help" | interface_contract | Step 2.5 |
| D3 | `test_nfr06_01_env_example_all_eight_vars` | env_file=".env.example"; var_count="8" | interface_contract | Step 2.5/NP-11 |

**Sub-assertions** (predicate over a case's Inputs / the production `result`):

| rule_id | predicate | applies_to |
|---|---|---|
| CC-smoke-module | `module_name == "taskq"` | D1 |
| CC-smoke-help | `argv == "--help"` | D2 |
| CC-smoke-env-count | `var_count == "8"` | D3 |

### NFR Test Cases (Deferred to Downstream Phases)

The 22 test cases below constitute the remainder of the 31 NFR inventory tests (TEST_INVENTORY.yaml `by_nfr` total). They are deferred to Phase 3+ for implementation but are enumerated here at title level so that Phase 3/4 do not need to independently rediscover them from TEST_INVENTORY.yaml. The 8 system-level NFR tests listed in the NFR Integration section above and D3 (NFR-06 in Deployment Smoke) account for the other 9.

| # | NFR | Test Function | Layer | Title |
|---|---|---|---|---|
| D-N2a | NFR-02 | `test_nfr02_01_no_shell_true_codebase` | static | grep `shell=True` across entire codebase |
| D-N2b | NFR-02 | `test_nfr02_03_ci_gate_blocks_shell_true` | static | CI gate blocks `shell=True` regression |
| D-N3a | NFR-03 | `test_nfr03_02_recovery_within_cooldown` | integration | OPEN to CLOSED recovery <= cooldown + 1s |
| D-N3b | NFR-03 | `test_nfr03_03_tasks_corruption_detected` | unit | tasks.json corruption detected; no silent rebuild |
| D-N4a | NFR-04 | `test_nfr04_02_redact_token_pattern` | unit | stdout line with `token=...` replaced with `[REDACTED]` |
| D-N4b | NFR-04 | `test_nfr04_03_non_matching_unchanged` | unit | non-matching lines remain unchanged |
| D-N4c | NFR-04 | `test_nfr04_04_redaction_before_disk_write` | unit | redaction happens before disk write (content check) |
| D-N5a | NFR-05 | `test_nfr05_01_docstring_full_coverage` | static | 100% public-symbol docstring coverage |
| D-N5b | NFR-05 | `test_nfr05_02_docstring_cites_upstream` | static | each docstring contains >= 1 `[FR-XX]` or `[NFR-XX]` ref |
| D-N6 | NFR-06 | `test_nfr06_02_config_centralized_read` | unit | config.py centralized read + per-var default |
| D-N7a | NFR-07 | `test_nfr07_02_fault_oserror_on_write` | unit | `--inject-fault=oserror-on-write` recover or fail-fast |
| D-N7b | NFR-07 | `test_nfr07_03_fault_disk_full` | unit | `--inject-fault=disk-full` recover or fail-fast |
| D-N7c | NFR-07 | `test_nfr07_04_fault_kill_mid_write` | unit | `--inject-fault=kill-mid-write` recover or fail-fast |
| D-N7d | NFR-07 | `test_nfr07_05_production_no_fault_injection` | static | production path disables fault injection (0% silent) |
| D-N8a | NFR-08 | `test_nfr08_02_fcntl_msvcrt_platform_lock` | static | POSIX `fcntl.flock` / Windows `msvcrt.locking` |
| D-N8b | NFR-08 | `test_nfr08_03_nfs_network_fs_degrade` | unit | NFS/network FS detect -> degrade + WARNING |
| D-N9a | NFR-09 | `test_nfr09_02_run_all_hundred_tasks` | integration | `run --all` 100 tasks; 100% valid, no loss |
| D-N9b | NFR-09 | `test_nfr09_03_memory_peak_under_100mb` | unit | memory peak < 100MB (tracemalloc, streaming iterator) |
| D-N10a | NFR-10 | `test_nfr10_02_v0_auto_migrate` | unit | version 0 -> auto-migrate v1 + `<file>.v0.bak` |
| D-N10b | NFR-10 | `test_nfr10_03_v2_refuse_with_upgrade_prompt` | unit | version 2 -> refuse + upgrade prompt + exit 1 |
| D-N10c | NFR-10 | `test_nfr10_04_migrate_failure_keeps_backup` | unit | migrate failure keeps `<file>.v<n>.bak` + exit 1 |
| D-N10d | NFR-10 | `test_nfr10_05_pytest_fixture_v0_to_v1` | unit | pytest fixture v0 -> v1 100% + backup + readable |

---

## Summary

| Metric | Count |
|---|---|
| FRs covered | 5 |
| FR test cases (P1 inventory baseline) | 38 |
| FR test cases (Step 1b SAD-derived additions, tagged SAD:) | 5 |
| Total FR test cases (combined) | 43 |
| NFR test cases (system-level subset listed in NFR Integration section; 8 of 31 inventory NFR tests) | 8 |
| NFR test cases (deferred to downstream phases; enumerated at title level in the Deferred NFR Test Cases section above; implementation deferred to Phase 3+) | 22 |
| Cross-cutting cases (architecture-derived, not in P1 inventory) | 3 |
| Deployment smoke cases (D1-D2 architecture-derived; D3 = inventory NFR-06) | 3 |
| Total all cases (inventory 69 + architecture-derived 10) | 79 |
| By type: happy_path | 14 |
| By type: validation | 8 |
| By type: failure | 4 |
| By type: boundary | 1 |
| By type: state_transition | 2 |
| By type: fault_injection | 6 |
| By type: nfr_pattern | 11 |
| By type: integration | 5 |
| By type: negative_constraint | 2 |
| By type: interface_contract | 4 |
| Active NFR patterns applied | NP-04, NP-06, NP-07, NP-08, NP-10, NP-11, NP-13, NP-15 |
| Step 1b SAD-triggered patterns | NP-07 (cache.py), NP-13 (store.py), NP-15 (executor.py) |
| Integration variants from Step 1b | 6 (test_fr02_06_run_all_thread_safety, test_fr02_09_subprocess_orphan_cleanup, test_fr04_06_cache_thread_safety, test_fr04_07_cache_unavailable_fallback, test_fr04_08_cache_recovers_after_transient_outage, test_fr04_09_cache_actually_used_on_hit) |

---

*Author: Architect Agent A (Sub-Task 3/3 TEST_SPEC.md, Round 1) | Phase 2 | 2026-07-12*
*Refers: `SPEC.md` v4.1.0 (2026-07-12) §3-§5, `SRS.md` (5 FR / 10 NFR), `SAD.md` §2-§4, `TEST_INVENTORY.yaml` (69 test names, P1 baseline; 5 SAD:-tagged per-FR additions + 5 cross-cutting/smoke = 79 total cases specified).*
