# TEST_SPEC.md — taskq Test Specification Catalog (P2 Single Source of Truth)

> **Phase 2 deliverable.** Authored by Agent A (ARCHITECT, Sub-Task 3/3, Round 2) per `derive_test_cases.md` v1.1, harness-methodology v2.13.0.
> Test names from `TEST_INVENTORY.yaml` (validated 2026-07-11) are preserved verbatim where specified; case rows are derived from `01-requirements/TRACEABILITY_MATRIX.md` §2.1 (FR per-AC) and §3.1 (NFR per-AC). This is the SINGLE SOURCE OF TRUTH for all test traceability checks at Gates 1-4.

**Project**: `taskq` (local task queue CLI, Python 3.11 stdlib only)
**SRS source**: `01-requirements/SRS.md` (v4.0.0, 2026-07-11, locked)
**SAD source**: `02-architecture/SAD.md` (Round 1)
**TEST_INVENTORY.yaml version**: v4.0.0 (2026-07-11, 69 cases)
**Active NFR Patterns** (per Step 1 / 1b / 1c activation below): NP-04, NP-06, NP-07, NP-08, NP-10, NP-13, NP-15

---

## NFR Pattern Activation (Step 1 / 1b / 1c Output)

| Pattern | Trigger (SRS keyword / SAD module / SEC threat) | Activated |
|---------|---------------------------------------------------|-----------|
| NP-01 (auth 401) | not found | ❌ |
| NP-02 (authz 403) | not found | ❌ |
| NP-03 (rate limit 429) | not found | ❌ |
| NP-04 (validation 422) | SRS: "input validation" (FR-01 blacklist); SRS: "reject" | ✅ |
| NP-05 (idempotency) | not found | ❌ |
| NP-06 (latency SLA) | SRS: "p95" (NFR-01 / NFR-09) | ✅ |
| NP-07 (dependency fault) | SAD: cache (`cache.py` shared mutable state) | ✅ |
| NP-08 (security attack) | SRS: "injection character blacklist" (NFR-02) | ✅ |
| NP-09 (audit log) | not found | ❌ |
| NP-10 (data round-trip) | SRS: "cache hit replay" (FR-04 TTL round-trip) | ✅ |
| NP-11 (backward compat) | not found | ❌ |
| NP-12 (pagination) | not found (no list paging — full in-memory dump) | ❌ |
| NP-13 (concurrency) | SAD: `store.py` (high-risk, shared `threading.Lock` + `fcntl.flock`); `breaker.py` (cross-process state); `cache.py` (shared mutable state) | ✅ |
| NP-14 (encryption) | not found | ❌ |
| NP-15 (timeout) | SAD: `executor.py` (external subprocess `subprocess.run(timeout=…)`) | ✅ |

**Architecture-risk triggers (Step 1b)**:
- `store.py` shared mutable state → forces NP-13 (FR-02 / FR-04 / NFR-08 integration cases)
- `executor.py` external process → forces NP-15 (FR-02 timeout case)
- `cache.py` cache + atomic write → forces NP-07 + NP-10 (FR-04 cases; integration variants under `tests/integration/`)
- `breaker.py` cross-process state machine → forces NP-13 (FR-03 integration cases)

**STRIDE / threat triggers (Step 1c)**: SAD.md §6 does not identify a verified-by test case; FR-01 injection-blacklist + FR-02 redaction together implement the threat-model mitigations (NP-04 + NP-08). No additional case authored.

---

## Functional Requirement Test Cases

### FR-01: 任務提交與驗證 (`taskq submit`)

**Classification**: API_ENDPOINT
**Active Patterns**: NP-04 (validation); NP-08 (injection blacklist)
**Anchoring NFRs**: NFR-02, NFR-03
**Step 8-Q**: Q1 happy + Q2 validation (4 distinct rejects) + Q3 boundary (length 1000) + Q7 integration (atomic write). **9 canonical test functions** (matching `TEST_INVENTORY.yaml` `fr_tests.FR-01`) rendered as **14 case rows**: `test_fr01_07_submit_injection_chars` is parametrized over 6 blacklist-char sub_cases (rows 7-12), so the 9 functions expand to 14 parametrize rows.

| # | Test Function | Inputs | Type | Derivation |
|---|---------------|--------|------|------------|
| 1 | `test_fr01_01_happy_submit_echo_hi` | command="echo hi"; name="" | happy_path | Q1 |
| 2 | `test_fr01_02_submit_json_output` | command="echo hi"; json_flag="true" | happy_path | Q1 |
| 3 | `test_fr01_03_submit_empty_command` | command=""; name="" | validation | Q2 |
| 4 | `test_fr01_04_submit_whitespace_only` | command="   "; name="" | validation | Q2 |
| 5 | `test_fr01_05_submit_too_long` | command_len="1001"; char_basis="x"; name="" | boundary | Q3 |
| 6 | `test_fr01_06_submit_injection_semicolon` | command="echo hi; rm x"; name="" | validation | Q2 |
| 7 | `test_fr01_07_submit_injection_chars` | command="echo hi \| wc"; name="" | validation | Q2 (sub_case pipe) |
| 8 | `test_fr01_07_submit_injection_chars` | command="echo hi &"; name="" | validation | Q2 (sub_case ampersand) |
| 9 | `test_fr01_07_submit_injection_chars` | command="$USER hi"; name="" | validation | Q2 (sub_case dollar) |
| 10 | `test_fr01_07_submit_injection_chars` | command="echo hi > f"; name="" | validation | Q2 (sub_case redirect_gt) |
| 11 | `test_fr01_07_submit_injection_chars` | command="echo hi < f"; name="" | validation | Q2 (sub_case redirect_lt) |
| 12 | `test_fr01_07_submit_injection_chars` | command="echo `id` hi"; name="" | validation | Q2 (sub_case backtick) |
| 13 | `test_fr01_08_submit_name_duplicate` | name="dup-name-1"; duplicate_present="true"; prior_id="abcdef01" | validation | Q2 |
| 14 | `test_fr01_09_submit_atomic_write` | command="echo hi"; name=""; mid_write_error="oserror"; state_mode="isolate_per_test" | integration | Q7 |

> **Multi-scenario expansion** (v2.13.0 rule 1 + TEST_INVENTORY `sub_cases`): AC-FR01-07's 6 blacklist chars are 6 distinct parametrize rows (cases 7-12), ALL under the single canonical function `test_fr01_07_submit_injection_chars` (TEST_INVENTORY declares `sub_cases: [pipe, ampersand, dollar, redirect_gt, redirect_lt, backtick]`). The Test Function column repeats that one name — no per-char function name is invented — so P3 Gate-1 spec-coverage matches the P1 naming authority exactly; each sub-row keeps its own `command` input + predicate. The `--name duplicate` case (case 13) declares `precondition: <prior pending task with name="dup-name-1" exists in $TASKQ_HOME/tasks.json>` explicitly; the `atomic_write` case (case 14) declares `state_mode: isolate_per_test` to mandate function-scoped fixtures so monkeypatched `OSError` cannot leak across tests.

**Sub-assertions**:

| rule_id | predicate (over Inputs) | applies_to (case #) |
|---------|--------------------------|---------------------|
| FR01-non-empty | `len(command) > 0` | 1, 2, 6, 7, 8, 9, 10, 11, 12 |
| FR01-strip-empty | `command.strip() == ""` | 3, 4 |
| FR01-strip-not-empty | `len(command.strip()) > 0` | 1, 2, 5, 6, 7, 8, 9, 10, 11, 12 |
| FR01-length-boundary-ok | `command_len == "1001" and int(command_len) > 1000` | 5 |
| FR01-injection-semicolon | chr(59) in command | 6 |
| FR01-injection-pipe      | chr(124) in command | 7 |
| FR01-injection-ampersand | chr(38) in command | 8 |
| FR01-injection-dollar    | chr(36) in command | 9 |
| FR01-injection-redirect-gt | chr(62) in command | 10 |
| FR01-injection-redirect-lt | chr(60) in command | 11 |
| FR01-injection-backtick  | chr(96) in command | 12 |
| FR01-name-required-for-duplicate | `name == "dup-name-1" and duplicate_present == "true"` | 13 |
| FR01-atomic-mid-write-recovers | `mid_write_error == "oserror"` | 14 |

> **Naming safety (v2.13.0 rule 4)**: predicate LHS `len` is whitelisted (`_ALLOWED_BUILTINS`); `command`, `command_len`, `name`, `duplicate_present`, `mid_write_error` are case Inputs (free variables) and are NOT in `RESERVED_NAMES`. The shell-injection-predicates use string-char LHS literals (`"<char>" in command`) — never identifier names — so no shadowing risk.

---

### FR-02: 任務執行器 (`taskq run <id>` / `run --all`)

**Classification**: INTEGRATION (subprocess + shared store lock)
**Active Patterns**: NP-13 (shared mutable `tasks.json`); NP-15 (subprocess timeout)
**Anchoring NFRs**: NFR-02, NFR-03, NFR-04, NFR-08
**Step 8-Q**: Q1 happy + Q2 failure-mode (failed / timeout) + Q3 boundary (stdout tail 2000) + Q4 state-transition (pending→running→done/failed/timeout) + Q5 fault-injection (concurrent --all partial-write protection) + Q7 integration. 8 cases below.

| # | Test Function | Inputs | Type | Derivation |
|---|---------------|--------|------|------------|
| 1 | `test_fr02_01_happy_single_run` | command="echo hi"; task_id="abcdef01"; state_mode="isolate_per_test" | happy_path | Q1 |
| 2 | `test_fr02_02_failed_run` | command="false"; task_id="abcdef02"; state_mode="isolate_per_test" | validation | Q2 |
| 3 | `test_fr02_03_timeout_run` | command="sleep 5"; task_id="abcdef03"; timeout_env="1"; state_mode="isolate_per_test" | boundary | Q3 |
| 4 | `test_fr02_04_stdout_tail_2000_chars` | command="printf '%2048s' x"; stdout_total_len="2049"; state_mode="isolate_per_test" | boundary | Q3 |
| 5 | `test_fr02_05_run_all_3_tasks` | command_a="true"; command_b="true"; command_c="true"; task_count="3"; state_mode="isolate_per_test" | integration | Q7 |
| 6 | `test_fr02_06_run_all_thread_safety` | command_x="echo x"; task_count="10"; state_mode="isolate_per_test" | integration | Q7 |
| 7 | `test_fr02_07_shell_true_absent` | scan_path="src/taskq/" | static | Q7 |
| 8 | `test_fr02_08_duration_and_finished_at` | command="echo hi"; task_id="abcdef08"; state_mode="isolate_per_test" | integration | Q1 |

> **Stateful isolation (v2.13.0 rule 2)**: every FR-02 case declares `state_mode: isolate_per_test` to mandate function-scoped fixtures (no module-scope `tasks.json`). Each case creates a fresh `$TASKQ_HOME` via tmp_path, populates, executes, and asserts — concurrency case 6 additionally uses `ThreadPoolExecutor` directly (no module-scope state shared between sub-tests).
>
> **Subprocess mode (v2.13.0 rule 3)**: all 8 cases use `subprocess_mode: in_process` (monkeypatched `subprocess.run` for AC-FR02-03 / AC-FR02-04 / AC-FR02-06 deterministic timing; the real subprocess is not exercised from TEST_SPEC — implementation choice). No `out_of_process` case is declared; NFR-08 cross-process integration lives in the NFR-08 table.

**Sub-assertions**:

| rule_id | predicate (over Inputs) | applies_to (case #) |
|---------|--------------------------|---------------------|
| FR02-exit-0-ok | `command == "echo hi"` | 1, 8 |
| FR02-exit-1-fail | `command == "false"` | 2 |
| FR02-timeout-config | `command == "sleep 5" and timeout_env == "1"` | 3 |
| FR02-stdout-tail-truncation | `stdout_total_len == "2049" and int(stdout_total_len) > 2000` | 4 |
| FR02-concurrent-task-count | `task_count == "10" and int(task_count) >= 2` | 5, 6 |
| FR02-three-task-happy | `task_count == "3" and int(task_count) == 3` | 5 |
| FR02-shell-true-scan-path | `scan_path == "src/taskq/"` | 7 |

---

### FR-03: 重試與斷路器 (`run` 自動重試 + 跨進程斷路器)

**Classification**: STATE_MACHINE (斷路器三態 CLOSED → OPEN → HALF_OPEN)
**Active Patterns**: NP-13 (breaker shared state across runs)
**Anchoring NFRs**: NFR-03
**Step 8-Q**: Q1 retry happy (failed / timeout) + Q2 retry termination + Q3 backoff sequence (injected sleep) + Q4 state-transition (3 consecutive failures → OPEN) + Q5 breaker recovery (CLOSED via HALF_OPEN) + Q7 integration (cross-process persistence, recovery time).

| # | Test Function | Inputs | Type | Derivation |
|---|---------------|--------|------|------------|
| 1 | `test_fr03_01_retry_on_failed` | command="false"; retry_limit_env="2"; sleep_injected="true"; state_mode="isolate_per_test" | happy_path | Q1 |
| 2 | `test_fr03_02_retry_on_timeout` | command="sleep 5"; timeout_env="1"; retry_limit_env="2"; sleep_injected="true"; state_mode="isolate_per_test" | happy_path | Q1 |
| 3 | `test_fr03_03_backoff_sequence` | backoff_base_env="0.1"; expected_n_value="3"; sleep_injected="true"; state_mode="isolate_per_test" | boundary | Q3 |
| 4 | `test_fr03_04_breaker_open` | command="false"; threshold_env="3"; consecutive_failures="3"; state_mode="isolate_per_test"; shared_TASKQ_HOME="false" | integration | Q4 |
| 5 | `test_fr03_05_breaker_half_open_success` | cooldown_env="5.0"; probe_command="echo hi"; state_mode="isolate_per_test" | integration | Q4 |
| 6 | `test_fr03_06_breaker_half_open_failure` | cooldown_env="5.0"; probe_command="false"; state_mode="isolate_per_test" | integration | Q4 |
| 7 | `test_fr03_07_breaker_persistence` | command="false"; threshold_env="3"; consecutive_failures="3"; subprocess_mode="out_of_process"; shared_TASKQ_HOME="true" | integration | Q7 |
| 8 | `test_fr03_08_recovery_time` | cooldown_env="5.0"; probe_command="echo hi"; state_mode="isolate_per_test" | integration | Q7 |

> **Stateful isolation (v2.13.0 rule 2)**: cases 1-6, 8 use `state_mode: isolate_per_test`; case 4 explicitly declares `shared_TASKQ_HOME="false"` (each sub-test writes its own `$TASKQ_HOME`); case 7 declares `shared_TASKQ_HOME="true"` + `subprocess_mode: out_of_process` — the cross-process restart must use the SAME TASKQ_HOME via `PYTHONPATH` propagation to the child env (pytest `pythonpath` config does NOT inherit by default, implementation owner must set `env=PYTHONPATH=...` explicitly).
>
> **Multi-scenario expansion (v2.13.0 rule 1)**: the breaker HALF_OPEN path (AC-FR03-05/06) and the persistence path (AC-FR03-07/08) are written as separate rows with their own `Inputs` columns rather than collapsed — case 5 expects success, case 6 expects failure, case 7/8 target different assertion surfaces.

**Sub-assertions**:

| rule_id | predicate (over Inputs) | applies_to (case #) |
|---------|--------------------------|---------------------|
| FR03-failed-auto-retry | `command == "false" and retry_limit_env == "2"` | 1 |
| FR03-timeout-auto-retry | `command == "sleep 5" and timeout_env == "1" and retry_limit_env == "2"` | 2 |
| FR03-backoff-n-declared | `expected_n_value == "3" and int(expected_n_value) >= 1` | 3 |
| FR03-threshold-triple | `consecutive_failures == "3" and threshold_env == "3"` | 4, 7 |
| FR03-half-open-success-probe | `probe_command == "echo hi"` | 5 |
| FR03-half-open-failure-probe | `probe_command == "false"` | 6 |
| FR03-cooldown-window | `cooldown_env == "5.0"` | 5, 6, 8 |
| FR03-recovery-time-window | `cooldown_env == "5.0"` | 8 |
| FR03-cross-process-propagation | `subprocess_mode_flag == "out_of_process"` | 7 |

> **Naming safety (v2.13.0 rule 4)**: predicate LHS `command`, `cooldown_env`, `probe_command`, `consecutive_failures`, `threshold_env`, `retry_limit_env`, `timeout_env`, `backoff_base_env`, `expected_n_value`, `subprocess_mode_flag` — all free variables from `Inputs`. None collide with `RESERVED_NAMES`. Note: the canonical BREAKER state-machine CLOSED/OPEN/HALF_OPEN transitions are tested via *outputs* (the test asserts the new state value); the predicate here is a precondition anchor ensuring the test ran in the right configuration.

---

### FR-04: 結果 TTL 快取 (`run <id> --cached`)

**Classification**: INTEGRATION (cache + store + subprocess interaction)
**Active Patterns**: NP-07 (cache fault); NP-10 (cache round-trip)
**Anchoring NFRs**: NFR-03, NFR-08
**Step 8-Q**: Q1 happy (cache hit replay) + Q2 cache miss (expired) + Q4 state-like (TTL boundary) + Q5 fault-injection (atomic write, thread-safety) + Q7 integration.

| # | Test Function | Inputs | Type | Derivation |
|---|---------------|--------|------|------------|
| 1 | `test_fr04_01_cache_hit_fresh` | command="echo hi"; ttl_env="3600"; cached_flag="true"; state_mode="isolate_per_test" | happy_path | Q1 |
| 2 | `test_fr04_02_cache_miss_expired` | command="echo hi"; ttl_env="1"; elapsed_secs="5"; cached_flag="true"; state_mode="isolate_per_test" | boundary | Q3 |
| 3 | `test_fr04_03_cache_signature` | command_a="echo hi"; command_b="echo hi2"; cached_flag="true"; state_mode="isolate_per_test" | happy_path | Q1 |
| 4 | `test_fr04_04_only_done_cached` | command="false"; outcome="failed"; cached_flag="true"; state_mode="isolate_per_test" | validation | Q2 |
| 5 | `test_fr04_05_cache_atomic_write` | command="echo hi"; mid_write_error="oserror"; state_mode="isolate_per_test" | integration | Q7 |
| 6 | `test_fr04_06_cache_thread_safety` | command_x="echo x"; task_count="10"; cached_flag="true"; state_mode="isolate_per_test" | integration | Q7 |

> **Stateful isolation (v2.13.0 rule 2)**: every FR-04 case declares `state_mode: isolate_per_test`. Cases 2 and 5 each pin a single distinct config (`ttl_env="1"` vs `mid_write_error="oserror"`) so a failure in one does NOT silently lose the other's case row. Case 6 (`run --all` concurrent) and case 5 (`mid_write OSError`) both manipulate `cache.json`; per-test isolation prevents one monkeypatched `OSError` from leaking across the other.

**Sub-assertions**:

| rule_id | predicate (over Inputs) | applies_to (case #) |
|---------|--------------------------|---------------------|
| FR04-ttl-fresh-hit | `ttl_env == "3600" and cached_flag == "true"` | 1 |
| FR04-ttl-expired | `ttl_env == "1" and int(elapsed_secs) > int(ttl_env)` | 2 |
| FR04-different-signatures | `command_a == "echo hi" and command_b == "echo hi2"` | 3 |
| FR04-failed-not-cached | `outcome == "failed"` | 4 |
| FR04-atomic-mid-write | `mid_write_error == "oserror"` | 5 |
| FR04-concurrent-cache | `task_count == "10"` | 6 |

> **Naming safety (v2.13.0 rule 4)**: predicate LHS strings `command` / `command_a` / `command_b` / `ttl_env` / `cached_flag` / `elapsed_secs` / `outcome` / `mid_write_error` / `task_count` are case-input free variables; none match `RESERVED_NAMES`. No attribute-style or module-style shadow risk.

---

### FR-05: CLI 整合 (argparse + exit codes)

**Classification**: API_ENDPOINT
**Active Patterns**: NP-04 (validation → exit 2 / unknown id)
**Anchoring NFRs**: (integrates all FRs; no additional NFR)
**Step 8-Q**: Q1 happy (status / list / clear) + Q2 validation (unknown-id → exit 2) + Q4 exit-code map (5 sub-scenarios).

| # | Test Function | Inputs | Type | Derivation |
|---|---------------|--------|------|------------|
| 1 | `test_fr05_01_status_all_fields` | command="echo hi"; task_id="abcdef01"; state_mode="isolate_per_test" | happy_path | Q1 |
| 2 | `test_fr05_02_status_json` | command="echo hi"; task_id="abcdef02"; json_flag="true"; state_mode="isolate_per_test" | happy_path | Q1 |
| 3 | `test_fr05_03_list_happy` | command_a="echo a"; command_b="echo b"; command_c="echo c"; task_count="3"; state_mode="isolate_per_test" | happy_path | Q1 |
| 4 | `test_fr05_04_list_filter_done` | task_total="5"; task_done="3"; status_filter="done"; state_mode="isolate_per_test" | happy_path | Q1 |
| 5 | `test_fr05_05_clear` | command="echo hi"; state_mode="isolate_per_test" | happy_path | Q1 |
| 6 | `test_fr05_06_unknown_task_id` | unknown_id="deadbeef"; state_mode="isolate_per_test" | validation | Q2 |
| 7 | `test_fr05_07_exit_code_map` | command="echo hi"; state_mode="isolate_per_test" | integration | Q4 (exit 0 happy) |
| 8 | `test_fr05_07_exit_code_map` | fault_target="tasks.json"; corruption_kind="invalid_json"; state_mode="isolate_per_test" | integration | Q4 (exit 1 internal) |
| 9 | `test_fr05_07_exit_code_map` | command=""; state_mode="isolate_per_test" | integration | Q4 (exit 2 validation) |
| 10 | `test_fr05_07_exit_code_map` | threshold_env="3"; consecutive_failures="3"; state_mode="isolate_per_test"; shared_TASKQ_HOME="false" | integration | Q4 (exit 3 breaker) |
| 11 | `test_fr05_07_exit_code_map` | command="sleep 5"; timeout_env="1"; state_mode="isolate_per_test" | integration | Q4 (exit 4 timeout) |

> **Multi-scenario expansion (v2.13.0 rule 1)**: AC-FR05-07's five exit codes (0/1/2/3/4) are 5 distinct parametrize rows (cases 7-11, sequentially numbered after the 6 standalone FR-05 cases), ALL under the single canonical function `test_fr05_07_exit_code_map` (TEST_INVENTORY P1 naming authority, `layer: integration`) — each row has its own `Inputs` set, `state_mode`, and monkeypatch strategy. The Test Function column repeats that one canonical name — no `test_fr05_07_exit_code_N_*` per-scenario name is invented — so P3 Gate-1 spec-coverage matches the P1 naming authority. Collapsing the five into a single Inputs row would FAIL the v2.13.0 shape rules; the rows match the 5 SPEC §7 exit-code rows verbatim.
>
> **Stateful isolation (v2.13.0 rule 2)**: every FR-05 case declares `state_mode: isolate_per_test`; case 12 is the `tasks.json` corruption-detected-on-startup path — it requires monkeypatch of `open(...)` BEFORE `cli.main()` dispatches, so the test must run with a fresh tmp_path and a pre-corrupted copy of the file.

**Sub-assertions**:

| rule_id | predicate (over Inputs) | applies_to (case #) |
|---------|--------------------------|---------------------|
| FR05-status-happy | `command == "echo hi" and task_id == "abcdef01"` | 1 |
| FR05-status-json-flag | `json_flag == "true"` | 2 |
| FR05-list-three-rows | `task_count == "3" and int(task_count) == 3` | 3 |
| FR05-list-filter-done | `status_filter == "done" and task_done == "3" and task_total == "5" and int(task_done) <= int(task_total)` | 4 |
| FR05-clear-clears | `command == "echo hi"` | 5 |
| FR05-unknown-id-format | `len(unknown_id) == 8 and unknown_id == "deadbeef"` | 6 |
| FR05-exit-0-command | `command == "echo hi"` | 7 |
| FR05-exit-1-corruption | `corruption_kind == "invalid_json" and fault_target == "tasks.json"` | 8 |
| FR05-exit-2-empty-command | `command == "" and len(command) == 0` | 9 |
| FR05-exit-3-breaker-threshold | `threshold_env == "3" and consecutive_failures == "3"` | 10 |
| FR05-exit-4-timeout-env | `command == "sleep 5" and timeout_env == "1"` | 11 |

> **Naming safety (v2.13.0 rule 4)**: predicate LHS strings `command` / `task_id` / `json_flag` / `task_count` / `task_total` / `task_done` / `status_filter` / `unknown_id` / `fault_target` / `corruption_kind` / `threshold_env` / `consecutive_failures` / `timeout_env` are all case-input free variables. None collide with `RESERVED_NAMES`. The substring test `'len(unknown_id) == 8'` uses the whitelisted builtin `len` (not in `RESERVED_NAMES`).

---

## Cross-Cutting Test Cases

### NFR Integration (Integration-tier NFR cases only)

Per v2.13.0 rule 6: only NFR cases with `layer == integration` (or comparable cross-process / cross-module behavior) carry concrete `Inputs` and `Sub-assertions` tables below. All `unit` / `static` NFR cases are isolated in the `Deferred to Downstream Phases` table further down.

#### NFR-03 (recovery time, integration)

| # | Test Function | Inputs | Type | Derivation |
|---|---------------|--------|------|------------|
| 1 | `test_nfr03_02_recovery_within_cooldown` | cooldown_env="5.0"; probe_command="echo hi"; state_mode="isolate_per_test" | integration | Q7 |

**Sub-assertions**:

| rule_id | predicate (over Inputs) | applies_to (case #) |
|---------|--------------------------|---------------------|
| NFR03-recovery-cooldown | `cooldown_env == "5.0"` | 1 |

#### NFR-08 (cross-process concurrency, integration)

| # | Test Function | Inputs | Type | Derivation |
|---|---------------|--------|------|------------|
| 1 | `test_nfr08_01_four_process_concurrent` | process_count="4"; ops_mix="submit+run+clear"; subprocess_mode="out_of_process"; shared_TASKQ_HOME="true"; state_mode="isolate_per_test" | integration | Q7 |

> **Subprocess mode (v2.13.0 rule 3)**: case 1 declares `subprocess_mode: out_of_process` + `shared_TASKQ_HOME: true` — implementation must propagate `PYTHONPATH` to child env via `env={**os.environ, "PYTHONPATH": ...}` because pytest `pythonpath` config does NOT inherit. Implementation owner must NOT silently rely on pytest config to thread PYTHONPATH into the 4 spawned children.

**Sub-assertions**:

| rule_id | predicate (over Inputs) | applies_to (case #) |
|---------|--------------------------|---------------------|
| NFR08-cross-process-count | `process_count == "4" and int(process_count) >= 2` | 1 |
| NFR08-cross-process-ops   | `ops_mix == "submit+run+clear"` | 1 |

#### NFR-09 (run --all 100-task scale, integration)

| # | Test Function | Inputs | Type | Derivation |
|---|---------------|--------|------|------------|
| 1 | `test_nfr09_02_run_all_hundred_tasks` | command_x="echo x"; task_count="100"; state_mode="isolate_per_test" | integration | Q7 |

**Sub-assertions**:

| rule_id | predicate (over Inputs) | applies_to (case #) |
|---------|--------------------------|---------------------|
| NFR09-hundred-run-all | `task_count == "100" and int(task_count) == 100` | 1 |

### Backward Compatibility

Not applicable (single-phase project).

### Deployment Smoke

| # | Test Function | Type | Derivation |
|---|---------------|------|------------|
| 1 | `test_cli_help_prints_subcommands` | smoke | deployment |
| 2 | `test_python_dash_m_taskq_runs` | smoke | deployment |

---

## Deferred to Downstream Phases (Unit / Static / Bench NFRs)
Function names referenced (deferred to unit / static / bench layer test files in P3): test_nfr01_01_submit_status_p95_under_50ms test_nfr02_01_no_shell_true_codebase test_nfr02_02_injection_chars_blacklist test_nfr02_03_ci_gate_blocks_shell_true test_nfr03_01_three_files_atomic_write test_nfr03_03_tasks_corruption_detected test_nfr04_01_redact_sk_pattern test_nfr04_02_redact_token_pattern test_nfr04_03_non_matching_unchanged test_nfr04_04_redaction_before_disk_write test_nfr05_01_docstring_full_coverage test_nfr05_02_docstring_cites_upstream test_nfr06_01_env_example_all_eight_vars test_nfr06_02_config_centralized_read test_nfr07_01_fault_corrupt_mid_write test_nfr07_02_fault_oserror_on_write test_nfr07_03_fault_disk_full test_nfr07_04_fault_kill_mid_write test_nfr07_05_production_no_fault_injection test_nfr08_02_fcntl_msvcrt_platform_lock test_nfr08_03_nfs_network_fs_degrade test_nfr09_01_thousand_tasks_p95 test_nfr09_03_memory_peak_under_100mb test_nfr10_01_version_field_present test_nfr10_02_v0_auto_migrate test_nfr10_03_v2_refuse_with_upgrade_prompt test_nfr10_04_migrate_failure_keeps_backup test_nfr10_05_pytest_fixture_v0_to_v1

| # | NFR | Test Function | Layer | Title |
|---|-----|---------------|-------|-------|
| 1 | NFR-01 | `test_nfr01_01_submit_status_p95_under_50ms` | bench | `submit` + `status` 100 iter p95 < 50ms (pytest-benchmark) |
| 2 | NFR-02 | `test_nfr02_01_no_shell_true_codebase` | static | grep `shell=True` in `src/taskq/` -> 0 hits |
| 3 | NFR-02 | `test_nfr02_02_injection_chars_blacklist` | unit | 6 blacklist chars each 1 pytest case (referenced as `test_fr01_06_*` / `test_fr01_07_*` rows in FR-01 case table) |
| 4 | NFR-02 | `test_nfr02_03_ci_gate_blocks_shell_true` | static | CI gate blocks `shell=True` regression |
| 5 | NFR-03 | `test_nfr03_01_three_files_atomic_write` | unit | 3 data files tmp + `os.replace`; mid-write sim -> valid JSON |
| 6 | NFR-03 | `test_nfr03_03_tasks_corruption_detected` | unit | `tasks.json` corruption -> exit 1 + `store corrupted`, no silent rebuild |
| 7 | NFR-04 | `test_nfr04_01_redact_sk_pattern` | unit | `stdout_tail` with `sk-...` -> that line replaced with `[REDACTED]` |
| 8 | NFR-04 | `test_nfr04_02_redact_token_pattern` | unit | `stdout_tail` with `token=...` -> that line replaced with `[REDACTED]` |
| 9 | NFR-04 | `test_nfr04_03_non_matching_unchanged` | unit | non-matching lines unchanged |
| 10 | NFR-04 | `test_nfr04_04_redaction_before_disk_write` | unit | redaction happens before disk write (content check) |
| 11 | NFR-05 | `test_nfr05_01_docstring_full_coverage` | static | 100% public-symbol docstring coverage |
| 12 | NFR-05 | `test_nfr05_02_docstring_cites_upstream` | static | every docstring cites `[FR-XX]` or `[NFR-XX]` |
| 13 | NFR-06 | `test_nfr06_01_env_example_all_eight_vars` | static | `.env.example` declares 8 `TASKQ_*` vars + comments |
| 14 | NFR-06 | `test_nfr06_02_config_centralized_read` | unit | `config.py` centralized read + per-var default |
| 15 | NFR-07 | `test_nfr07_01_fault_corrupt_mid_write` | unit | precondition: TASKQ_ENV∈{dev,test}; `--inject-fault=corrupt-mid-write` -> recover or fail-fast (per ADR-014 TASKQ_ENV gate) |
| 16 | NFR-07 | `test_nfr07_02_fault_oserror_on_write` | unit | precondition: TASKQ_ENV∈{dev,test}; `--inject-fault=oserror-on-write` -> recover or fail-fast (per ADR-014) |
| 17 | NFR-07 | `test_nfr07_03_fault_disk_full` | unit | precondition: TASKQ_ENV∈{dev,test}; `--inject-fault=disk-full` -> recover or fail-fast (per ADR-014) |
| 18 | NFR-07 | `test_nfr07_04_fault_kill_mid_write` | unit | precondition: TASKQ_ENV∈{dev,test}; `--inject-fault=kill-mid-write` -> recover or fail-fast (per ADR-014) |
| 19 | NFR-07 | `test_nfr07_05_production_no_fault_injection` | static | precondition: covers BOTH branches per SAD §6 T-07: (a) `--inject-fault` absent (any TASKQ_ENV) -> fault injection never triggers; (b) `--inject-fault` present + TASKQ_ENV unset or `prod` -> exit code 2 + stderr BEFORE any other work (per ADR-014 line 552 + SAD §6 T-07 mitigation); (c) `--inject-fault` present + TASKQ_ENV∈{dev,test} -> flag accepted, fault surfaces via cases 15-18 |
| 20 | NFR-08 | `test_nfr08_02_fcntl_msvcrt_platform_lock` | static | POSIX `fcntl.flock` / Windows `msvcrt.locking` |
| 21 | NFR-08 | `test_nfr08_03_nfs_network_fs_degrade` | unit | NFS / network fs detect -> degrade + WARNING |
| 22 | NFR-09 | `test_nfr09_01_thousand_tasks_p95` | bench | 1000-task scale `submit`+`status` p95 < 100ms (pytest-benchmark scaled) |
| 23 | NFR-09 | `test_nfr09_03_memory_peak_under_100mb` | unit | memory peak < 100MB (tracemalloc, streaming iterator) |
| 24 | NFR-10 | `test_nfr10_01_version_field_present` | unit | 3 data files root `version: 1` |
| 25 | NFR-10 | `test_nfr10_02_v0_auto_migrate` | unit | `version: 0` -> auto-migrate v1 + `<file>.v0.bak` |
| 26 | NFR-10 | `test_nfr10_03_v2_refuse_with_upgrade_prompt` | unit | `version: 2` -> refuse + upgrade prompt + exit 1 |
| 27 | NFR-10 | `test_nfr10_04_migrate_failure_keeps_backup` | unit | migrate failure -> keep backup + exit 1 |
| 28 | NFR-10 | `test_nfr10_05_pytest_fixture_v0_to_v1` | unit | pytest fixture `v0 -> v1` 100% + backup + readable |

> **Note**: NFRs with `layer in {unit, static, bench}` are isolated above, NOT in the Integration tables. Implementation owner (P3 Agent A) creates the `tests/unit/test_nfrXX_*.py` (and benchmark) files; this catalog records the test-function names so check-test-spec-consistency can validate completeness.

---
---

## Summary

**Canonical test functions** (= `TEST_INVENTORY.yaml`, the P1 naming authority):

| Metric | Count |
|--------|-------|
| FRs covered | 5 (FR-01 .. FR-05) |
| NFRs covered | 10 (NFR-01 .. NFR-10) |
| Canonical FR test functions | 38 (FR-01:9, FR-02:8, FR-03:8, FR-04:6, FR-05:7) |
| Canonical NFR test functions | 31 (integration 3, unit 19, static 7, bench 2) |
| Total canonical functions (`TEST_INVENTORY.yaml` `total_test_cases`) | 69 |

**Case rows in this catalog** (parametrize sub_cases expanded into distinct rows):

| Metric | Count |
|--------|-------|
| FR case rows | 47 (`test_fr01_07_submit_injection_chars` → 6 rows; `test_fr05_07_exit_code_map` → 5 rows) |
| NFR Integration case rows authored here | 3 (NFR-03-02, NFR-08-01, NFR-09-02) |
| NFR Deferred rows (unit/static/bench) | 28 |
| Deployment smoke rows (P2-added, not in `TEST_INVENTORY.yaml`) | 2 |
| Total case rows | 80 |

**By type** (disjoint partition of the 80 case rows):

| Type | Count |
|------|-------|
| happy_path | 12 |
| validation/failure | 13 |
| boundary | 5 |
| integration | 19 (16 FR + 3 NFR) |
| unit (deferred) | 19 |
| static | 8 (1 FR + 7 NFR) |
| bench (deferred) | 2 |
| smoke | 2 |
| **Total** | **80** |

**Active NFR patterns applied**: NP-04, NP-06, NP-07, NP-08, NP-10, NP-13, NP-15

> **Arithmetic reconciliation**: canonical-function count = 38 FR + 31 NFR = **69**, matching `TEST_INVENTORY.yaml` `total_test_cases: 69` (NFR split = 3 integration + 19 unit + 7 static + 2 bench = 31). Case rows total **80** because (a) AC-FR01-07 (6 sub_cases) and AC-FR05-07 (5 exit-code scenarios) each expand to multiple parametrize rows under ONE canonical function (+5 and +4 rows = +9), and (b) 2 deployment-smoke rows are P2-added and not tracked in `TEST_INVENTORY.yaml`. Removing the 9 expansion rows and 2 smoke rows: 80 − 9 − 2 = **69** = `TEST_INVENTORY.yaml` total. The NP-XX patterns are cross-cutting activation markers (see the NFR Pattern Activation table), NOT a disjoint case-type, so they are excluded from the By-type partition to avoid double-counting.

> **Cross-document reconciliation note (P2 Agent A Round 2 → B-2 review gap)**: `02-architecture/SAD.md` §6 threat-model `verified_by` field references test names that DIVERGE from the canonical `TEST_INVENTORY.yaml` naming locked at P1 (e.g. SAD T-01 `test_submit_rejects_injection_chars` vs canonical `test_fr01_07_submit_injection_chars`; T-03 `test_redact_secret_in_output` has no exact TEST_SPEC analogue; T-06 `test_task_records_timestamps` vs FR-02 case 8 `test_fr02_08_duration_and_finished_at` which checks only `duration_ms` + `finished_at` not `created_at` audit trail; T-07 `test_inject_fault_rejected_in_production` vs canonical `test_nfr07_05_production_no_fault_injection` now expanded above to cover BOTH flag-absent and flag-present+production-rejection branches per ADR-014). **TEST_INVENTORY.yaml is the P1-locked naming authority**; this TEST_SPEC canonicalizes test-function names against it. The SAD-side `verified_by` field is an out-of-scope edit for this Sub-Task 3/3 deliverable (Agent A is constrained to TEST_SPEC.md only) — the SAD update is deferred to a follow-up review cycle. Downstream Gate-1 spec-coverage uses `TEST_SPEC.md` + `TEST_INVENTORY.yaml` as the parity source; the SAD §6 names are documentation-only and do not gate P3 implementations.

---

*Generated by: derive_test_cases.md v1.1 | harness-methodology v2.13.0 | P2 Agent A (ARCHITECT) Sub-Task 3/3 Round 2 — 2026-07-17*
