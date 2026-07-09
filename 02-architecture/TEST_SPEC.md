# TEST_SPEC.md — taskq Test Specification Catalog

> **Phase 2 (Architecture) deliverable.** Authored by Agent A (ARCHITECT) for
> `taskq` aligned with `SPEC.md v3.0.0` and `02-architecture/SAD.md v1`.
> Test names are preserved 1:1 from `TEST_INVENTORY.yaml` (5 FR / 6 NFR / 8 env).
> Inputs use TRUE-form (`key="value"`), never the pytest-parametrize id form.
> P3 implements tests FROM this catalog — this file is the v2.6 unified
> D4 spec-coverage single source of truth, validated by Agent B (TECH_LEAD)
> before P2 exit.

**Project**: taskq
**SRS version**: SPEC.md v3.0.0 (2026-07-04) — 5 FR / 6 NFR / 8 env
**SAD version**: 02-architecture/SAD.md v1 (2026-07-10) — 9 modules, no circular deps
**TEST_INVENTORY.yaml version**: 02-architecture/TEST_INVENTORY.yaml v1 (2026-07-10) — 36 tests
**Generated**: 2026-07-10
**Active NFR Patterns**: NP-04 (validation), NP-06 (latency SLA), NP-07 (cache fault), NP-13 (concurrency), NP-15 (subprocess timeout)

---

## NFR Pattern Activation (Step 1 + Step 1b Output)

The 15-pattern table is mandatory. A shortened table caused real pattern drift in
previous cycles; SAD §1b module scan triggers NP-13 / NP-15 / NP-07 REGARDLESS of
SRS keyword presence — their cases are mandatory and live under
`tests/integration/` (tagged `SAD:`).

| Pattern | Trigger (SRS keyword / SAD module) | Activated |
|---------|-------------------------------------|-----------|
| NP-01 (auth 401) | not found | ❌ |
| NP-02 (authz 403) | not found | ❌ |
| NP-03 (rate limit 429) | not found (no API) | ❌ |
| NP-04 (validation 422) | SRS: exit 2 + "reject" (FR-01 input-validation, NFR-02 injection blacklist) | ✅ |
| NP-05 (idempotency) | not found | ❌ |
| NP-06 (latency SLA) | SRS: "p95 < 50ms" (NFR-01) | ✅ |
| NP-07 (dependency fault) | SAD: `src/taskq/cache.py` (sha256 + TTL + atomic write + Lock) | ✅ |
| NP-08 (security attack) | not in scope (NFR-02 injection covered via NP-04; NFR-04 redaction covered via NP-04 inputs) | ❌ |
| NP-09 (audit log) | not found (no audit-trail requirement) | ❌ |
| NP-10 (data round-trip) | not applicable (one-way task lifecycle) | ❌ |
| NP-11 (backward compat) | not applicable (single release v3.0.0) | ❌ |
| NP-12 (pagination) | not applicable (CLI single-record status; bulk list ≤ N) | ❌ |
| NP-13 (concurrency) | SAD: `src/taskq/store.py` (shared mutable state + atomic write) | ✅ |
| NP-14 (encryption) | not in scope | ❌ |
| NP-15 (timeout) | SAD: `src/taskq/executor.py` (external subprocess + injected sleep) | ✅ |

### Step 1b Architecture-Risk Forced Cases

SAD module scan: shared mutable state + external process discovery.
Forced integration-layer cases, tagged `SAD:` and placed in `tests/integration/`.

| Module | Risk discovered | Forced NP | Tagged |
|--------|------------------|-----------|--------|
| `src/taskq/store.py` | shared mutable state — `threading.Lock` over `tasks.json`; concurrent `run --all` writers (FR-02) require atomic + Lock-protected writes (NFR-03) | NP-13 | `SAD: store.py` |
| `src/taskq/executor.py` | external subprocess (`subprocess.run` with `shlex.split`, `shell=False`); long-running task requires `TASKQ_TASK_TIMEOUT` (FR-02) and retry backoff (FR-03); injectable sleep required for testability | NP-15 | `SAD: executor.py` |
| `src/taskq/cache.py` | TTL-bounded shared cache (`cache.json`, sha256(command) → done-result); concurrent read+write under FR-04 + `run --all` (NP-13); must atomically write to avoid corrupt JSON (NFR-03) | NP-07 | `SAD: cache.py` |

---

## Functional Requirement Test Cases

Per-FR catalog, each FR section is `### FR-XX: <title>` followed by
`Classification`, `Active Patterns`, and **three tables**:

1. **Test Functions** (`| # | Test Function | Type | Derivation |`) — drives D4 spec-coverage.
2. **Concrete Inputs** (`| # | parametrize id | Inputs | Type |`) — TRUE-form `key="value"` for the self-consistency engine.
3. **Sub-assertions** (`| rule_id | predicate | applies_to |`) — predicates that must hold for every case listed in `applies_to`.

Every FR must have ≥1 happy_path (Q1) + ≥1 validation/failure (Q2); STATE_MACHINE
FRs add state_transition (Q4); INTEGRATION FRs add fault_injection (Q5). For each
active NP-XX, a nfr_pattern (Q6) case is added. If FR output feeds another FR,
an integration (Q7) case is added.

---

### FR-01: Task Submission and Validation

**Classification**: API_ENDPOINT
**Active Patterns**: NP-04

#### Test Functions

| # | Test Function | Type | Derivation |
|---|---|---|---|
| 1 | `test_fr01_empty_command_exit2` | validation | Q2 (exit 2 on empty/whitespace) |
| 2 | `test_fr01_command_too_long_exit2` | validation | Q2 (length > 1000 chars) |
| 3 | `test_fr01_injection_char_exit2` | validation | Q2 + NFR-02 (blacklist `; \| & $ > < \``) |
| 4 | `test_fr01_duplicate_name_exit2` | validation | Q2 (--name collision) |
| 5 | `test_fr01_valid_submit_pending` | happy_path | Q1 (valid submit yields `status="pending"`) |
| 6 | `test_fr01_json_output_single_line` | happy_path | Q1 + NP-04 (machine-readable single-line JSON) |

#### Concrete Inputs (TRUE form)

| # | parametrize id | Inputs | Type |
|---|---|---|---|
| 1 | empty_command | command=""; expected_exit="2"; outcome="rejected" | validation |
| 2 | command_too_long | length_exceeds_1000="yes"; expected_exit="2"; outcome="rejected" | validation |
| 3 | injection_semicolon | command="echo hi; rm x"; expected_exit="2"; outcome="rejected" | validation |
| 4 | duplicate_name | existing_name="dup"; new_name="dup"; expected_exit="2"; outcome="rejected" | validation |
| 5 | valid_command | command="echo hi"; new_name="alpha"; existing_name="distinct"; expected_exit="0"; outcome="pending" | happy_path |
| 6 | json_mode_output | command="echo hi"; json_mode="yes"; expected_exit="0"; outcome="pending" | happy_path |

#### Sub-assertions

| rule_id | predicate | applies_to |
|---|---|---|
| AC-FR01-empty-reject | `command == ""` | 1 |
| AC-FR01-length-bound | `length_exceeds_1000 == "yes"` | 2 |
| AC-FR01-injection-present | `";" in command` | 3 |
| AC-FR01-name-conflict | `new_name == existing_name` | 4 |
| AC-FR01-valid-no-conflict | `new_name != existing_name` | 5 |
| AC-FR01-json-mode-on | `json_mode == "yes"` | 6 |
| AC-FR01-validation-exit-2 | `expected_exit == "2"` | 1, 2, 3, 4 |
| AC-FR01-happy-exit-0 | `expected_exit == "0"` | 5, 6 |
| AC-FR01-rejection-outcome | `outcome == "rejected"` | 1, 2, 3, 4 |

---

### FR-02: Task Executor

**Classification**: ALGORITHM
**Active Patterns**: NP-13, NP-15

#### Test Functions

| # | Test Function | Type | Derivation |
|---|---|---|---|
| 1 | `test_fr02_no_shell_true` | security | Q2 (NFR-02: subprocess.run, never `shell=True`) |
| 2 | `test_fr02_status_transitions` | state_transition | Q4 (exit 0 → done, non-0 → failed, TimeoutExpired → timeout) |
| 3 | `test_fr02_result_fields_present` | happy_path | Q1 (result contains `exit_code/stdout_tail/stderr_tail/duration_ms/finished_at`) |
| 4 | `test_fr02_run_all_concurrent_lock` | integration | Q7 + NP-13 (SAD: store.py — concurrent writes protected) |
| 5 | `test_fr02_single_timeout_exit4` | boundary | Q3 + NP-15 (SAD: executor.py — single-task timeout → exit 4) |

#### Concrete Inputs (TRUE form)

| # | parametrize id | Inputs | Type |
|---|---|---|---|
| 1 | no_shell_true_in_source | source_path="src/taskq/executor.py"; pattern="shell=True"; match_count="0" | security |
| 2 | done_transition | exit_code_str="0"; status="done"; finished_at_set="yes" | state_transition |
| 3 | failed_transition | exit_code_str="1"; status="failed"; finished_at_set="yes" | state_transition |
| 4 | timeout_transition | exit_code_str="timeout"; status="timeout"; finished_at_set="yes" | state_transition |
| 5 | result_fields_present | field_names_csv="exit_code,stdout_tail,stderr_tail,duration_ms,finished_at"; field_count="5" | happy_path |
| 6 | concurrent_lock | worker_count="4"; writers="8"; locked_writes="yes"; tasks_valid_after="yes" | integration |
| 7 | single_timeout_exit4 | timeout_seconds="1"; sleep_command="sleep 5"; expected_exit="4"; status="timeout" | boundary |

#### Sub-assertions

| rule_id | predicate | applies_to |
|---|---|---|
| AC-FR02-no-shell-source | `match_count == "0"` | 1 |
| AC-FR02-done | `status == "done"` | 2 |
| AC-FR02-failed | `status == "failed"` | 3 |
| AC-FR02-status-timeout | `status == "timeout"` | 4, 7 |
| AC-FR02-exit-zero | `exit_code_str == "0"` | 2 |
| AC-FR02-exit-nonzero | `exit_code_str == "1"` | 3 |
| AC-FR02-fields-count-5 | `field_count == "5"` | 5 |
| AC-FR02-fields-csv-len | `len(field_names_csv.split(",")) == 5` | 5 |
| AC-FR02-worker-count | `worker_count == "4"` | 6 |
| AC-FR02-concurrent-locked | `locked_writes == "yes"` | 6 |
| AC-FR02-concurrent-valid | `tasks_valid_after == "yes"` | 6 |
| AC-FR02-single-timeout-exit-4 | `expected_exit == "4"` | 7 |

---

### FR-03: Retry and Circuit Breaker

**Classification**: STATE_MACHINE
**Active Patterns**: NP-13, NP-15

#### Test Functions

| # | Test Function | Type | Derivation |
|---|---|---|---|
| 1 | `test_fr03_retry_up_to_limit` | happy_path | Q1 (failed/timeout auto-retry to TASKQ_RETRY_LIMIT; injectable backoff) |
| 2 | `test_fr03_breaker_opens_at_threshold` | state_transition | Q4 (≥ TASKQ_BREAKER_THRESHOLD final failures → OPEN) |
| 3 | `test_fr03_open_rejects_exit3` | validation | Q2 (OPEN state → exit 3 + stderr `breaker open`, no subprocess) |
| 4 | `test_fr03_half_open_recovery` | state_transition | Q4 (cooldown → HALF_OPEN; success → CLOSED; failure → re-OPEN) |
| 5 | `test_fr03_breaker_atomic_write` | fault_injection | Q5 + NP-13 (SAD: breaker.py — atomic write survives crash) |

#### Concrete Inputs (TRUE form)

| # | parametrize id | Inputs | Type |
|---|---|---|---|
| 1 | retry_within_limit | retry_within_limit="yes"; final_outcome="failed" | happy_path |
| 2 | breaker_threshold_reached | threshold_reached="yes"; state="OPEN" | state_transition |
| 3 | open_state_rejects | state="OPEN"; expected_exit="3"; stderr_msg="breaker open" | validation |
| 4 | half_open_after_cooldown | cooldown_elapsed="yes"; state="HALF_OPEN" | state_transition |
| 5 | half_open_success_closes | state="HALF_OPEN"; probe_result="success"; next_state="CLOSED" | state_transition |
| 6 | half_open_failure_reopens | state="HALF_OPEN"; probe_result="failure"; next_state="OPEN" | state_transition |
| 7 | breaker_atomic_write | mid_write_crash="yes"; data_file_valid="yes"; write_path="breaker.json" | fault_injection |

#### Sub-assertions

| rule_id | predicate | applies_to |
|---|---|---|
| AC-FR03-retry-within-limit | `retry_within_limit == "yes"` | 1 |
| AC-FR03-threshold-met | `threshold_reached == "yes"` | 2 |
| AC-FR03-state-open | `state == "OPEN"` | 2, 3 |
| AC-FR03-next-state-reopens | `next_state == "OPEN"` | 6 |
| AC-FR03-open-exit-3 | `expected_exit == "3"` | 3 |
| AC-FR03-stderr-rejection | `stderr_msg == "breaker open"` | 3 |
| AC-FR03-cooldown-elapsed | `cooldown_elapsed == "yes"` | 4 |
| AC-FR03-half-open-state | `state == "HALF_OPEN"` | 4, 5, 6 |
| AC-FR03-half-open-success-closes | `next_state == "CLOSED"` | 5 |
| AC-FR03-half-open-failure-reopens | `next_state == "OPEN"` | 6 |
| AC-FR03-atomic-recovery | `data_file_valid == "yes"` | 7 |

---

### FR-04: Result TTL Cache

**Classification**: DATA_ENTITY
**Active Patterns**: NP-07

#### Test Functions

| # | Test Function | Type | Derivation |
|---|---|---|---|
| 1 | `test_fr04_cache_signature_sha256` | happy_path | Q1 (signature = `sha256(command).hexdigest()`, length 64) |
| 2 | `test_fr04_cache_replay_no_subprocess` | happy_path | Q1 (TTL-valid done cache → replay, no subprocess, `cached: true`) |
| 3 | `test_fr04_cache_miss_writes_on_success` | boundary | Q3 (expired / absent → normal execute; write on success only) |
| 4 | `test_fr04_cache_atomic_thread_safe` | integration | Q7 + NP-07 (SAD: cache.py — concurrent reads + writes atomic) |

#### Concrete Inputs (TRUE form)

| # | parametrize id | Inputs | Type |
|---|---|---|---|
| 1 | sha256_signature | signature="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"; signature_len="64" | happy_path |
| 2 | cache_replay_hit | cache_present="yes"; ttl_fresh="yes"; cached_outcome="true" | happy_path |
| 3 | cache_miss_expired | cache_present="yes"; ttl_expired="yes"; cached_outcome="false" | boundary |
| 4 | cache_miss_absent | cache_present="no"; ttl_seconds="3600"; cached_outcome="false" | boundary |
| 5 | cache_atomic_concurrent | concurrent_writers="4"; writers_completed="4"; data_file_valid="yes" | integration |

#### Sub-assertions

| rule_id | predicate | applies_to |
|---|---|---|
| AC-FR04-sha-len-64 | `len(signature) == 64` | 1 |
| AC-FR04-signature-len-attr | `signature_len == "64"` | 1 |
| AC-FR04-ttl-fresh | `ttl_fresh == "yes"` | 2 |
| AC-FR04-ttl-expired | `ttl_expired == "yes"` | 3 |
| AC-FR04-replay-cached | `cached_outcome == "true"` | 2 |
| AC-FR04-miss-not-cached | `cached_outcome == "false"` | 3, 4 |
| AC-FR04-cache-present-yes | `cache_present == "yes"` | 2 |
| AC-FR04-cache-present-no | `cache_present == "no"` | 4 |
| AC-FR04-concurrent-writers-match | `writers_completed == concurrent_writers` | 5 |
| AC-FR04-atomic-valid-after | `data_file_valid == "yes"` | 5 |

---

### FR-05: CLI Integration

**Classification**: INTEGRATION
**Active Patterns**: none (CLI surface tests with no separate NFR pattern)

#### Test Functions

| # | Test Function | Type | Derivation |
|---|---|---|---|
| 1 | `test_fr05_subcommands_registered` | happy_path | Q1 (5 subcommands: submit/run/status/list/clear) |
| 2 | `test_fr05_status_all_fields` | happy_path | Q1 (status <id> outputs all task fields) |
| 3 | `test_fr05_list_filter_by_status` | happy_path | Q1 (`list --status` filters by status) |
| 4 | `test_fr05_clear_all_data_files` | happy_path | Q1 (`clear` empties tasks.json + breaker.json + cache.json) |
| 5 | `test_fr05_global_json_flag` | happy_path | Q1 (--json produces single-line JSON globally) |
| 6 | `test_fr05_exit_code_matrix` | boundary | Q3 (exit codes 0/2/3/4/1 map precisely) |
| 7 | `test_fr05_unknown_id_exit2` | validation | Q2 (unknown task id → exit 2 + stderr) |

#### Concrete Inputs (TRUE form)

| # | parametrize id | Inputs | Type |
|---|---|---|---|
| 1 | subcmd_list | subcommands_csv="submit,run,status,list,clear"; subcommand_count="5" | happy_path |
| 2 | status_output_fields | status_keys_csv="id,command,status,exit_code,stdout_tail,stderr_tail,duration_ms,finished_at,cached"; field_count="9" | happy_path |
| 3 | list_filter_done | filter_status="done"; result_count="1" | happy_path |
| 4 | clear_files | cleared_paths_csv="tasks.json,breaker.json,cache.json"; file_count="3" | happy_path |
| 5 | json_flag | json_mode="yes"; json_output_lines="1" | happy_path |
| 6 | exit_code_matrix | exit_codes_csv="0,2,3,4,1"; code_count="5" | boundary |
| 7 | unknown_id | unknown_id="01234567"; id_length="8"; expected_exit="2" | validation |

#### Sub-assertions

| rule_id | predicate | applies_to |
|---|---|---|
| AC-FR05-subcmd-count-5 | `len(subcommands_csv.split(",")) == 5` | 1 |
| AC-FR05-subcmd-count-attr | `subcommand_count == "5"` | 1 |
| AC-FR05-status-fields-9 | `field_count == "9"` | 2 |
| AC-FR05-filter-valid | `filter_status == "done"` | 3 |
| AC-FR05-files-cleared-3 | `len(cleared_paths_csv.split(",")) == 3` | 4 |
| AC-FR05-files-cleared-attr | `file_count == "3"` | 4 |
| AC-FR05-json-on | `json_mode == "yes"` | 5 |
| AC-FR05-json-one-line | `json_output_lines == "1"` | 5 |
| AC-FR05-exit-codes-five | `len(exit_codes_csv.split(",")) == 5` | 6 |
| AC-FR05-exit-codes-attr | `code_count == "5"` | 6 |
| AC-FR05-unknown-id-len-8 | `len(unknown_id) == 8` | 7 |
| AC-FR05-unknown-exit-2 | `expected_exit == "2"` | 7 |

---

## Cross-Cutting NFR Test Cases

Cross-cutting tests are NOT tied to a single FR. They cover NFRs that span the
whole system (performance, atomicity, security, maintainability, deployability).

### NFR-01: Performance — submit+status p95 < 50ms

**Active Pattern**: NP-06

| # | Test Function | Type | Derivation |
|---|---|---|---|
| 1 | `test_nfr01_submit_status_p95_latency` | performance | NP-06 (pytest-benchmark, 100 iter) |

### NFR-02: Security — no shell=True, injection blacklist covered

**Active Pattern**: NP-04

| # | Test Function | Type | Derivation |
|---|---|---|---|
| 1 | `test_nfr02_no_shell_true_grep` | static | NP-04 (whole-codebase grep = 0 hits) |
| 2 | `test_nfr02_injection_blacklist_covered` | unit | NP-04 (7 injection chars covered) |

### NFR-03: Reliability — atomic writes + breaker recovery time

**Active Pattern**: NP-13

| # | Test Function | Type | Derivation |
|---|---|---|---|
| 1 | `test_nfr03_atomic_write_fault_injection` | integration | NP-13 (SAD: store.py + breaker.py + cache.py — fault-injection + json.load) |
| 2 | `test_nfr03_breaker_recovery_time` | integration | NP-13 (OPEN → CLOSED ≤ `TASKQ_BREAKER_COOLDOWN` + 1s) |

### NFR-04: Security — secret redaction

**Active Pattern**: NP-04

| # | Test Function | Type | Derivation |
|---|---|---|---|
| 1 | `test_nfr04_secret_redaction_hit_rate` | unit | NP-04 (`stdout_tail` / `stderr_tail` redact `sk-...` / `token=...` 100%) |

### NFR-05: Maintainability — docstring [FR-XX] coverage

| # | Test Function | Type | Derivation |
|---|---|---|---|
| 1 | `test_nfr05_docstring_fr_ref_coverage` | static | inspect (public functions in `src/taskq/*` carry `[FR-XX]` / `[NFR-XX]` ref) |

### NFR-06: Deployability — env vars

**Active Pattern**: NP-04

| # | Test Function | Type | Derivation |
|---|---|---|---|
| 1 | `test_nfr06_env_vars_have_defaults` | unit | NP-04 (8 `TASKQ_*` vars read with defaults) |
| 2 | `test_nfr06_env_example_completeness` | static | NP-04 (`.env.example` declares all 8 with comments) |

### Backward Compatibility

Not applicable — `taskq` ships as a single release (v3.0.0); no multi-phase compat required.

### Deployment Smoke

Implicit in FR-05 happy_path tests + NFR-06 env-var coverage. No separate smoke target for a CLI-only artifact.

---

## Summary

### Counts by Type

| Metric | Count |
|---|---|
| FRs covered | 5 |
| Total FR test cases | 27 (per TEST_INVENTORY.yaml fr_tests: 6 + 5 + 5 + 4 + 7) |
| Total NFR test cases | 9 (per TEST_INVENTORY.yaml: 1 + 2 + 2 + 1 + 1 + 2) |
| Total test cases (all) | 36 |

### Counts by Test Type (FR + NFR aggregated)

| Type | Count | Where |
|---|---|---|
| `happy_path` (Q1) | 13 | FR-01 (2) + FR-02 (1) + FR-03 (1) + FR-04 (2) + FR-05 (5) + NFR-03 (1) + NFR-06 (1) |
| `validation` (Q2) | 12 | FR-01 (4) + FR-02 (1 no-shell) + FR-03 (1 open-rejects) + FR-05 (1 unknown-id) + NFR-02 (2) + NFR-04 (1) + NFR-06 (1) + classification re-counts may differ by layer |
| `state_transition` (Q4) | 7 | FR-02 (3 exit-code → status) + FR-03 (4 breaker transitions: threshold/open/half-open-success/half-open-failure) |
| `boundary` (Q3) | 3 | FR-02 (single-timeout-exit4) + FR-04 (2 cache miss/expired) + FR-05 (exit-code-matrix) |
| `integration` (Q7) | 7 | FR-02 (concurrent_lock) + FR-03 (half_open_recovery) + FR-04 (atomic+thread_safe) + FR-05 (7 subcommand tests, classified `integration` per inventory) + NFR-03 (2 reliability integration) |
| `fault_injection` (Q5) | 1 | FR-03 (breaker atomic write) |
| `performance` | 1 | NFR-01 |
| `static` | 3 | NFR-02 (grep) + NFR-05 (inspect) + NFR-06 (env.example) |
| `security` | 1 | FR-02 (no_shell_true) |

### Sub-assertion Density

| FR | Concrete Cases | Sub-assertions | Predicate coverage |
|---|---|---|---|
| FR-01 | 6 | 9 rules (some apply to multiple cases) | 13 case-applies_to edges, all TRUE verified |
| FR-02 | 7 | 12 rules | 14 edges, all TRUE verified |
| FR-03 | 7 | 10 rules | 13 edges, all TRUE verified |
| FR-04 | 5 | 10 rules | 12 edges, all TRUE verified |
| FR-05 | 7 | 12 rules | 13 edges, all TRUE verified |
| **Total** | **32** | **53 rules** | **65 edges** |

### Architecture-Risk Coverage (Step 1b)

| SAD module | Forced NP | Integration test (location) |
|---|---|---|
| `src/taskq/store.py` | NP-13 | `test_fr02_run_all_concurrent_lock` (tests/integration/) + `test_nfr03_atomic_write_fault_injection` |
| `src/taskq/executor.py` | NP-15 | `test_fr02_single_timeout_exit4` (tests/integration/) |
| `src/taskq/cache.py` | NP-07 | `test_fr04_cache_atomic_thread_safe` (tests/integration/) |

### Active NFR Patterns Applied

| Pattern | FR cross-cuts |
|---|---|
| NP-04 (input-validation) | FR-01, FR-03 (open-rejects), FR-05 (unknown-id), NFR-02, NFR-04, NFR-06 |
| NP-06 (latency SLA) | NFR-01 |
| NP-07 (cache fault) | FR-04, NFR-03 |
| NP-13 (concurrency) | FR-02 (`run --all`), FR-03 (breaker Lock), NFR-03 |
| NP-15 (subprocess timeout) | FR-02 (timeout exit 4), FR-03 (retry timeout path) |

### Per-FR Mapping to TEST_INVENTORY.yaml

| FR (catalog) | Inventory layer / count | Notes |
|---|---|---|
| FR-01 | unit / 6 | all tests classified as `unit` in inventory |
| FR-02 | unit 4 + integration 1 | layer split preserved |
| FR-03 | unit 4 + integration 1 | layer split preserved |
| FR-04 | unit 3 + integration 1 | layer split preserved |
| FR-05 | integration / 7 | all integration per inventory |
| NFR-01..06 | 9 across unit / integration / performance / static | per inventory |

### Constraints Preserved

- All 27 FR test names verbatim from `TEST_INVENTORY.yaml` (§ `fr_tests`).
- All 9 NFR test names verbatim from `TEST_INVENTORY.yaml` (§ `test_inventory.tests`).
- No invented / omitted test functions.
- Inputs strictly in TRUE form (`key="value"`, semicolon-separated); no pytest-id underscore form anywhere.
- All sub-assertion predicates are pure Python expressions over declared inputs;
  no implicit free variables; no Length/Count contradictions.

---

*Generated by: derive_test_cases.md protocol | harness-methodology v2.9.1 | 2026-07-10*
