# Traceability Matrix — taskq

> Document version: 1.0.0 | 2026-06-29
> Companion to: `01-requirements/SRS.md` v1.0.0 (APPROVED) and `01-requirements/SPEC_TRACKING.md` v1.0.0 (APPROVED)
> Mode: INGESTION (100% derived from approved SRS.md + SPEC_TRACKING.md; no invention of new FRs/NFRs/ACs/designs/tests)
> Purpose: Provide **bidirectional** traceability across FR/NFR ↔ Design element ↔ Test case so that Phase 2–8 can resolve any artifact from any other artifact without re-reading source documents. This matrix is read in either direction:
> - **Forward (requirements → design → test)**: column 1→2→3 walks a requirement to its design element to its verifying test.
> - **Backward (test → design → requirement)**: column 3→2→1 walks a test back to the requirement it verifies.

---

## 0. Conventions

### 0.1 Scope rule (zero-new-content)
This matrix is **derived** from `SRS.md` (requirements) + `SPEC_TRACKING.md` (per-AC owner/verification locus). No new FR/NFR/AC, no new design element, and no new test case is invented here. Where the SRS or SPEC_TRACKING leaves a placeholder for a design element or test, this matrix marks it as `TBD-by-phase` with the owning phase and never invents a name.

### 0.2 Column glossary

| Column | Meaning | Source of truth |
|--------|---------|-----------------|
| **AC ID** | The unique canonical acceptance criterion identifier from SRS §3/§4. | SRS.md §3, §4 (canonical AC IDs are 30) |
| **Requirement text (verbatim)** | The exact requirement statement the AC implements. | SRS.md §3 FR-0x.<n> or §4 NFR-0x |
| **Owner module** | The taskq module that implements the AC. | SPEC_TRACKING.md §1 + §4 |
| **Design element** | The named design construct (function/class/constant) that implements the AC inside the owner module. Where SPEC.md does not yet name a function/class, the matrix marks `TBD-by-phase-2` (architecture). | SPEC_TRACKING.md §1 + Phase 2 architecture |
| **Verification locus** | Where the AC is first verified: TDD-RED, GATE1, GATE2, GATE3, GATE4, or BASELINE. | SPEC_TRACKING.md §0 |
| **Test case ID** | The named test that verifies the AC. Naming follows JS/TS harness convention `it('test_frNN_xxx')` for project test framework; for taskq (Python pytest) the equivalent is `test_<frNN>_<descriptive>` in `tests/`. Where a test does not yet exist, the matrix marks `TBD-by-phase-3` (per-FR TDD). | Phase 3 per-FR TDD |
| **Bidirectional link notes** | Cross-references: NFR bindings, exit-code routing, retry/timeout ties. | SPEC_TRACKING.md §5 (Cross-Cutting Bindings) |

### 0.3 Status values (inherited from SPEC_TRACKING.md §0)
- `DRAFT` — AC identified, not yet implemented/tested
- `OWNED` — design element assigned in Phase 2
- `TESTED` — test authored and passing
- `VERIFIED` — independent verification (P5 BASELINE / P4 GATE3 / P6 GATE4) confirmed
- `BLOCKED` — owner cannot proceed; `owner_note` explains

### 0.4 Source citation format
`SRS.md §<n>.<m>.<k> — AC-FR-XX.<y>.z` (or `AC-NFR-XX.<y>`) — exact AC anchor from the approved SRS.

---

## 1. Forward Matrix — Requirements → Design → Test (per-AC rows)

This is the canonical forward walk. Read column-by-column left-to-right to trace any AC to its test. The 30 rows correspond to the 30 canonical AC IDs established in SPEC_TRACKING.md §3 (reconciled from SRS §5 narrative "27").

### 1.1 FR-01 — 任務模型與持久化 (Task model and persistence)

#### AC-FR-01.2.a — Non-empty command rejected

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-01.2.a |
| **Requirement (verbatim)** | "命令為空或全空白 → 拒絕" (SRS §3 FR-01.2 — 非空) |
| **Owner module** | `taskq.cli` |
| **Design element** | `taskq.cli:validate_submit_command(command: str) -> None` raises `ValidationError` on empty/whitespace. TBD-by-phase-2 (function name confirmed by Phase 2 architecture). |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | `tests/test_fr01_submit.py::test_fr01_empty_command_rejected` — asserts exit 2, stderr error message, tasks.json unchanged. TBD-by-phase-3. |
| **Bidirectional link notes** | Exit-code 2 routing bound to AC-FR-03.3.b (global exit-code table). |

#### AC-FR-01.2.b — Length > 1000 rejected

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-01.2.b |
| **Requirement (verbatim)** | "命令 > 1000 字元 → 拒絕" (SRS §3 FR-01.2 — 長度) |
| **Owner module** | `taskq.cli` |
| **Design element** | `taskq.cli:validate_submit_command(command: str) -> None` raises `ValidationError` when `len(command) > 1000`. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | `tests/test_fr01_submit.py::test_fr01_length_over_1000_rejected` — boundary tests at exactly 1000 (pass) and 1001 (reject). TBD-by-phase-3. |
| **Bidirectional link notes** | Exit-code 2 routing bound to AC-FR-03.3.b. |

#### AC-FR-01.2.c — Injection character blacklist

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-01.2.c |
| **Requirement (verbatim)** | "命令含 `;` `|` `&` `$` `>` `<` `` ` `` 任一 → 拒絕 (NFR-02)" (SRS §3 FR-01.2 — 注入字元) |
| **Owner module** | `taskq.cli` |
| **Design element** | `taskq.cli:INJECTION_CHARS = {';', '|', '&', '$', '>', '<', '`'}` (module-level constant, all 7 chars verbatim from SRS). TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 → GATE4 |
| **Test case ID** | `tests/test_fr01_submit.py::test_fr01_injection_chars_all_seven_rejected` — parametric test enumerating all 7 chars. TBD-by-phase-3. **Binds to** AC-NFR-02.b (test-coverage requirement). |
| **Bidirectional link notes** | NFR-02 binding; exit-code 2 routing bound to AC-FR-03.3.b. |

#### AC-FR-01.3.a — Task id is first 8 hex of uuid4

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-01.3.a |
| **Requirement (verbatim)** | "產生 task id(uuid4 前 8 hex)" (SRS §3 FR-01.3) |
| **Owner module** | `taskq.cli` |
| **Design element** | `taskq.cli:generate_task_id() -> str` returning `uuid.uuid4().hex[:8]`. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | `tests/test_fr01_submit.py::test_fr01_id_is_eight_lowercase_hex` — asserts regex `^[0-9a-f]{8}$` over 1000 generated ids. TBD-by-phase-3. |
| **Bidirectional link notes** | None cross-cutting. |

#### AC-FR-01.3.b — Initial record fields

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-01.3.b |
| **Requirement (verbatim)** | "狀態 `pending`,記錄 `command`、`created_at`" (SRS §3 FR-01.3) |
| **Owner module** | `taskq.cli` |
| **Design element** | `taskq.cli:new_task_record(command: str, task_id: str) -> dict` returning `{"id": ..., "status": "pending", "command": ..., "created_at": <iso8601>}`. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | `tests/test_fr01_submit.py::test_fr01_initial_record_fields` — asserts exact field set + types. TBD-by-phase-3. |
| **Bidirectional link notes** | `created_at` format bound to ISO-8601 (project-wide convention). |

#### AC-FR-01.3.c — Atomic write of tasks.json

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-01.3.c |
| **Requirement (verbatim)** | "原子寫入 `$TASKQ_HOME/tasks.json` (tmp + `os.replace`)" (SRS §3 FR-01.3) |
| **Owner module** | `taskq.store` |
| **Design element** | `taskq.store:atomic_write_json(path: Path, data: dict) -> None` — writes to `<path>.tmp.<pid>` then `os.replace`. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 → GATE2 |
| **Test case ID** | `tests/test_fr01_store.py::test_fr01_atomic_write_no_partial_observed` — concurrent reader thread polls file during write; never observes partial JSON. TBD-by-phase-3. **Binds to** AC-NFR-03.a (crash-injection resilience). |
| **Bidirectional link notes** | NFR-03.a binding. Path resolution through `taskq.config:resolve_home()`. |

#### AC-FR-01.3.d — Corrupted-store → exit 1, no silent rebuild

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-01.3.d |
| **Requirement (verbatim)** | "`tasks.json` 損壞(非法 JSON)→ 啟動偵測 → exit 1,stderr `store corrupted` (不靜默重建)" (SRS §3 FR-01.3) |
| **Owner module** | `taskq.store` |
| **Design element** | `taskq.store:load_store(path: Path) -> dict` — raises `StoreCorruptedError` on JSON parse failure; `taskq.cli` catches and exits 1 + stderr "store corrupted". TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 → GATE2 |
| **Test case ID** | `tests/test_fr01_store.py::test_fr01_corrupted_store_exits_one_no_rebuild` — pre-seed `tasks.json` with invalid JSON; assert exit 1, stderr contains "store corrupted", file content unchanged. TBD-by-phase-3. |
| **Bidirectional link notes** | Exit-code 1 routing bound to AC-FR-03.3.d (global exit-code table). |

**FR-01 subtotal (forward)**: 7 ACs.

---

### 1.2 FR-02 — 任務執行與重試 (Task execution and retry)

#### AC-FR-02.2.a — subprocess invocation contract

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-02.2.a |
| **Requirement (verbatim)** | "`subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)`" (SRS §3 FR-02.2) |
| **Owner module** | `taskq.executor` |
| **Design element** | `taskq.executor:run_command(command: str, timeout: float) -> subprocess.CompletedProcess` — single canonical call site; kwargs verbatim. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | `tests/test_fr02_executor.py::test_fr02_subprocess_kwargs_verbatim` — monkey-patches `subprocess.run` and asserts kwargs match exactly (no `shell=True`, `shlex.split` first arg, `text=True`, `timeout` from config). TBD-by-phase-3. |
| **Bidirectional link notes** | `timeout` resolution bound to `taskq.config:resolve_task_timeout()` returning `TASKQ_TASK_TIMEOUT` (default 10.0). |

#### AC-FR-02.2.b — No shell=True anywhere under run

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-02.2.b |
| **Requirement (verbatim)** | "任何路徑不得使用 `shell=True`" (SRS §3 FR-02.2) |
| **Owner module** | `taskq.executor` |
| **Design element** | `taskq.executor:run_command` (no `shell=True` kwarg) + codebase-wide absence (test scans AST of all modules under `taskq/`). TBD-by-phase-2 (AST scan helper). |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 → GATE4 |
| **Test case ID** | `tests/test_nfr02_security.py::test_nfr02_no_shell_true_anywhere` — tree-sitter / ast scan asserts zero `shell=True` kwarg in any `subprocess.*` call. TBD-by-phase-3. **Binds to** AC-NFR-02.a (codebase-wide scan). |
| **Bidirectional link notes** | Cross-cutting: same rule, two verification loci (executor unit + codebase scan). |

#### AC-FR-02.3.a — exit 0 → done

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-02.3.a |
| **Requirement (verbatim)** | "exit 0 → `done`" (SRS §3 FR-02.3) |
| **Owner module** | `taskq.executor` |
| **Design element** | `taskq.executor:execute(task: dict) -> dict` returns updated task with `status="done"` on `result.returncode == 0`. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | `tests/test_fr02_executor.py::test_fr02_exit_zero_done` — submit `echo hi`; after `run`, status==`done`. TBD-by-phase-3. |
| **Bidirectional link notes** | None. |

#### AC-FR-02.3.b — non-zero exit → failed

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-02.3.b |
| **Requirement (verbatim)** | "非 0 → `failed`" (SRS §3 FR-02.3) |
| **Owner module** | `taskq.executor` |
| **Design element** | `taskq.executor:execute(task: dict) -> dict` returns updated task with `status="failed"` on `result.returncode != 0`. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | `tests/test_fr02_executor.py::test_fr02_nonzero_exit_failed` — submit `false`; after `run`, status==`failed`. TBD-by-phase-3. |
| **Bidirectional link notes** | Triggers retry per AC-FR-02.5.a. |

#### AC-FR-02.3.c — TimeoutExpired → timeout

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-02.3.c |
| **Requirement (verbatim)** | "`TimeoutExpired` → `timeout`" (SRS §3 FR-02.3) |
| **Owner module** | `taskq.executor` |
| **Design element** | `taskq.executor:execute` catches `subprocess.TimeoutExpired` and sets `status="timeout"`. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | `tests/test_fr02_executor.py::test_fr02_timeout_expired_state` — submit `sleep 5` with `TASKQ_TASK_TIMEOUT=0.1`; status==`timeout`. TBD-by-phase-3. |
| **Bidirectional link notes** | Triggers retry per AC-FR-02.5.a; exit-code 4 routing per AC-FR-02.6.a / AC-FR-03.3.c. |

#### AC-FR-02.4.a — Result fields present

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-02.4.a |
| **Requirement (verbatim)** | "`exit_code`、`stdout_tail` (末 2000 字元)、`stderr_tail` (末 2000 字元)、`duration_ms`、`finished_at`" (SRS §3 FR-02.4) |
| **Owner module** | `taskq.executor` |
| **Design element** | `taskq.executor:build_result_record(result: CompletedProcess, started_at: float) -> dict` returning the 5 canonical fields; tail truncation via `text[-2000:]`. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | `tests/test_fr02_executor.py::test_fr02_result_fields_present` + `::test_fr02_tail_truncation_2000_chars` (separate test for 2000-char truncation). TBD-by-phase-3. |
| **Bidirectional link notes** | Tail fields filtered through `taskq.redaction:redact_line` (AC-NFR-03.b) before persistence. |

#### AC-FR-02.5.a — Auto-retry on failed/timeout

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-02.5.a |
| **Requirement (verbatim)** | "`run` 結果為 `failed`/`timeout` 時自動重試,上限 `TASKQ_RETRY_LIMIT` 次(預設 2)" (SRS §3 FR-02.5) |
| **Owner module** | `taskq.executor` |
| **Design element** | `taskq.executor:execute_with_retry(task: dict, retry_limit: int) -> dict` — retry counter bounded by `TASKQ_RETRY_LIMIT` (default 2); no retry on `done`. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 → GATE2 |
| **Test case ID** | `tests/test_fr02_executor.py::test_fr02_retry_caps_at_limit` (counter == limit) + `::test_fr02_no_retry_on_done` (single attempt) + `::test_fr02_retry_default_two`. TBD-by-phase-3. |
| **Bidirectional link notes** | `retry_limit` resolution bound to `taskq.config:resolve_retry_limit()` (default 2). |

#### AC-FR-02.6.a — Single-task timeout → exit 4

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-02.6.a |
| **Requirement (verbatim)** | "單一任務模式下 `timeout` 結果 → exit 4" (SRS §3 FR-02.6) |
| **Owner module** | `taskq.executor` |
| **Design element** | `taskq.executor:execute_with_retry` returns sentinel that `taskq.cli:cmd_run` translates to `sys.exit(4)`. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 → GATE2 |
| **Test case ID** | `tests/test_fr02_executor.py::test_fr02_single_task_timeout_exits_four` — `run <id>` on permanently-timeout task → process exit 4. TBD-by-phase-3. |
| **Bidirectional link notes** | Exit-code 4 routing bound to AC-FR-03.3.c. |

#### AC-FR-02.6.b — Unexpected exception → exit 1, no bare except

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-02.6.b |
| **Requirement (verbatim)** | "其他未預期例外 → exit 1 (不得裸 `except:` 吞噬)" (SRS §3 FR-02.6) |
| **Owner module** | `taskq.executor` |
| **Design element** | All `except` clauses in `taskq.executor` specify a concrete exception class (lint + AST test enforces). TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 → GATE2 |
| **Test case ID** | `tests/test_fr02_executor.py::test_fr02_unexpected_exception_exits_one` (inject `RuntimeError` in mock) + `tests/test_nfr02_security.py::test_nfr02_no_bare_except` (AST scan). TBD-by-phase-3. |
| **Bidirectional link notes** | Exit-code 1 routing bound to AC-FR-03.3.d. |

**FR-02 subtotal (forward)**: 9 ACs.

---

### 1.3 FR-03 — CLI 整合與查詢 (CLI integration and query)

#### AC-FR-03.1.a — status prints all fields

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-03.1.a |
| **Requirement (verbatim)** | "`status <id>` 輸出該任務全欄位" (SRS §3 FR-03.1) |
| **Owner module** | `taskq.cli` |
| **Design element** | `taskq.cli:cmd_status(args) -> int` prints all present fields (id, status, command, created_at, exit_code, stdout_tail, stderr_tail, duration_ms, finished_at). TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | `tests/test_fr03_cli.py::test_fr03_status_prints_all_fields` — submit+run+status; assert all 9 fields appear in stdout. TBD-by-phase-3. |
| **Bidirectional link notes** | Read path; covered by NFR-01 (p95 < 50ms). |

#### AC-FR-03.1.b — status <unknown_id> → exit 2

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-03.1.b |
| **Requirement (verbatim)** | "unknown id → exit 2 + `unknown task: <id>`" (SRS §3 FR-03.1) |
| **Owner module** | `taskq.cli` |
| **Design element** | `taskq.cli:cmd_status` raises `UnknownTaskError` (caught → exit 2 + stderr `unknown task: <id>`). TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | `tests/test_fr03_cli.py::test_fr03_status_unknown_id_exits_two` + `::test_fr03_status_unknown_id_stderr_message_verbatim`. TBD-by-phase-3. |
| **Bidirectional link notes** | Exit-code 2 routing bound to AC-FR-03.3.b. |

#### AC-FR-03.1.c — list prints every task

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-03.1.c |
| **Requirement (verbatim)** | "`list` 列出全部任務(id + status + command 前 50 字元)" (SRS §3 FR-03.1) |
| **Owner module** | `taskq.cli` |
| **Design element** | `taskq.cli:cmd_list(args) -> int` iterates store, prints `<id>\t<status>\t<command[:50]>` per line. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | `tests/test_fr03_cli.py::test_fr03_list_one_line_per_task` + `::test_fr03_list_command_truncated_to_50_chars`. TBD-by-phase-3. |
| **Bidirectional link notes** | Read path; covered by NFR-01. |

#### AC-FR-03.1.d — clear empties tasks.json

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-03.1.d |
| **Requirement (verbatim)** | "`clear` 清空 `$TASKQ_HOME/tasks.json`" (SRS §3 FR-03.1) |
| **Owner module** | `taskq.cli` |
| **Design element** | `taskq.cli:cmd_clear(args) -> int` calls `taskq.store:atomic_write_json(path, {"tasks": []})`. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | `tests/test_fr03_cli.py::test_fr03_clear_empties_store` — submit 3 tasks, `clear`, reload, assert `{"tasks": []}`. TBD-by-phase-3. |
| **Bidirectional link notes** | Uses atomic write (binds AC-FR-01.3.c / AC-NFR-03.a). Path resolution through `taskq.config:resolve_home()`. |

#### AC-FR-03.2.a — --json emits single-line JSON

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-03.2.a |
| **Requirement (verbatim)** | "全域 flag `--json`:機器可讀輸出(單行 JSON)" (SRS §3 FR-03.2) |
| **Owner module** | `taskq.cli` |
| **Design element** | `taskq.cli:emit_json(data: dict) -> None` prints `json.dumps(data, ensure_ascii=False)` followed by single `\n`. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 → GATE4 |
| **Test case ID** | `tests/test_fr03_cli.py::test_fr03_json_flag_emits_single_line` (no embedded newlines) + `::test_fr03_json_flag_parseable` (`json.loads(stdout)`). TBD-by-phase-3. |
| **Bidirectional link notes** | Applies to all subcommands. |

#### AC-FR-03.3.a — exit 0 on success

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-03.3.a |
| **Requirement (verbatim)** | "0 成功" (SRS §3 FR-03.3) |
| **Owner module** | `taskq.cli` |
| **Design element** | All `cmd_*` functions return `0` on success path. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | Parametric across `tests/test_fr03_cli.py` — every happy-path subcommand test asserts `result.returncode == 0`. TBD-by-phase-3. |
| **Bidirectional link notes** | Default success routing. |

#### AC-FR-03.3.b — exit 2 on validation failure

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-03.3.b |
| **Requirement (verbatim)** | "2 輸入驗證錯誤(含 unknown task id)" (SRS §3 FR-03.3) |
| **Owner module** | `taskq.cli` |
| **Design element** | `taskq.cli:cli_main` catches `ValidationError` and `UnknownTaskError`, exits 2. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | Backing tests: AC-FR-01.2.a/b/c (validation) and AC-FR-03.1.b (unknown id). TBD-by-phase-3. |
| **Bidirectional link notes** | Routing target for AC-FR-01.2.a/b/c and AC-FR-03.1.b. |

#### AC-FR-03.3.c — exit 4 on task timeout

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-03.3.c |
| **Requirement (verbatim)** | "4 任務 timeout" (SRS §3 FR-03.3) |
| **Owner module** | `taskq.executor` (returns timeout sentinel) + `taskq.cli` (translates to exit 4) |
| **Design element** | `taskq.cli:cmd_run` checks timeout sentinel from `taskq.executor:execute_with_retry` and calls `sys.exit(4)`. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 → GATE2 |
| **Test case ID** | Backing test: AC-FR-02.6.a (`test_fr02_single_task_timeout_exits_four`). TBD-by-phase-3. |
| **Bidirectional link notes** | Routing target for AC-FR-02.6.a. |

#### AC-FR-03.3.d — exit 1 on other internal errors

| Field | Value |
|-------|-------|
| **AC ID** | AC-FR-03.3.d |
| **Requirement (verbatim)** | "1 其他內部錯誤" (SRS §3 FR-03.3) |
| **Owner module** | `taskq.cli` |
| **Design element** | `taskq.cli:cli_main` catches `StoreCorruptedError` (from AC-FR-01.3.d), `RuntimeError` (from AC-FR-02.6.b), and uncaught `Exception` (excluding `KeyboardInterrupt`/`SystemExit`); exits 1. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 |
| **Test case ID** | Backing tests: AC-FR-01.3.d (corrupted store), AC-FR-02.6.b (unexpected exception). TBD-by-phase-3. |
| **Bidirectional link notes** | Routing target for AC-FR-01.3.d and AC-FR-02.6.b. |

**FR-03 subtotal (forward)**: 9 ACs.

---

### 1.4 NFR-01 — performance

#### AC-NFR-01.a — submit + status p95 < 50ms

| Field | Value |
|-------|-------|
| **AC ID** | AC-NFR-01.a |
| **Requirement (verbatim)** | "`submit` + `status` 組合操作 100 次 p95 < 50ms(不含 subprocess 執行)" (SRS §4 NFR-01) |
| **Owner module** | `test harness` (cross-cutting) |
| **Design element** | `tests/bench/test_nfr01_p95.py::test_nfr01_submit_status_p95_under_50ms` — benchmark loop: 100 iterations of submit+status, assert p95 < 50ms. TBD-by-phase-3 (per-FR harness test). |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 → BASELINE |
| **Test case ID** | `tests/bench/test_nfr01_p95.py::test_nfr01_submit_status_p95_under_50ms`. TBD-by-phase-3. |
| **Bidirectional link notes** | Binds to AC-FR-01.3.c (write path) + AC-FR-03.1.a (read path); measurement boundary "不含 subprocess 執行" enforced by harness setup (mock executor). |

**NFR-01 subtotal (forward)**: 1 AC.

---

### 1.5 NFR-02 — security

#### AC-NFR-02.a — codebase-wide absence of shell=True

| Field | Value |
|-------|-------|
| **AC ID** | AC-NFR-02.a |
| **Requirement (verbatim)** | "全 codebase 禁用 `shell=True`" (SRS §4 NFR-02) |
| **Owner module** | `test harness` (cross-cutting AST/grep scan) |
| **Design element** | `tests/test_nfr02_security.py::test_nfr02_no_shell_true_codebase_wide` — scans AST of all `taskq/**/*.py` for `shell=True` kwarg in any `subprocess.*` call. TBD-by-phase-3. |
| **Verification locus** | GATE2 → GATE4 |
| **Test case ID** | `tests/test_nfr02_security.py::test_nfr02_no_shell_true_codebase_wide`. TBD-by-phase-3. |
| **Bidirectional link notes** | **Same rule as** AC-FR-02.2.b — two verification loci (executor unit + codebase scan). |

#### AC-NFR-02.b — injection-char blacklist test coverage

| Field | Value |
|-------|-------|
| **AC ID** | AC-NFR-02.b |
| **Requirement (verbatim)** | "FR-01 注入字元黑名單必須有測試覆蓋" (SRS §4 NFR-02) |
| **Owner module** | `taskq.cli` (test exists) + `test harness` (coverage metric) |
| **Design element** | Backed by AC-FR-01.2.c's test (`test_fr01_injection_chars_all_seven_rejected`); coverage metric asserted by `tests/test_nfr02_security.py::test_nfr02_blacklist_coverage` (line coverage on `validate_submit_command` ≥ 100% of blacklist branch). TBD-by-phase-3. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 → GATE4 |
| **Test case ID** | `tests/test_nfr02_security.py::test_nfr02_blacklist_coverage` (coverage metric) + `tests/test_fr01_submit.py::test_fr01_injection_chars_all_seven_rejected` (executor behavior). TBD-by-phase-3. |
| **Bidirectional link notes** | **Same requirement as** AC-FR-01.2.c. |

**NFR-02 subtotal (forward)**: 2 ACs.

---

### 1.6 NFR-03 — reliability

#### AC-NFR-03.a — tasks.json atomic write survives crash

| Field | Value |
|-------|-------|
| **AC ID** | AC-NFR-03.a |
| **Requirement (verbatim)** | "`tasks.json` 原子寫(進程中斷後仍為合法 JSON)" (SRS §4 NFR-03) |
| **Owner module** | `taskq.store` |
| **Design element** | Backed by `taskq.store:atomic_write_json` (AC-FR-01.3.c). Crash-injection test: `tests/test_nfr03_reliability.py::test_nfr03_crash_mid_write_recovery` — spawns child process, `kill -9` mid-write, parent reloads file, asserts valid JSON parse. TBD-by-phase-3. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 → GATE2 → BASELINE |
| **Test case ID** | `tests/test_nfr03_reliability.py::test_nfr03_crash_mid_write_recovery`. TBD-by-phase-3. |
| **Bidirectional link notes** | **Same property as** AC-FR-01.3.c — FR owns writer, NFR owns crash-resilience claim. |

#### AC-NFR-03.b — redaction pre-write

| Field | Value |
|-------|-------|
| **AC ID** | AC-NFR-03.b |
| **Requirement (verbatim)** | "`stdout_tail` / `stderr_tail` 落盤前過濾 `(sk-[A-Za-z0-9_-]{8,}\|token=\S+)` 整行以 `[REDACTED]` 取代" (SRS §4 NFR-03) |
| **Owner module** | `taskq.redaction` |
| **Design element** | `taskq.redaction:REDACT_RE = re.compile(r'(sk-[A-Za-z0-9_-]{8,}|token=\S+)'); redact_line(line: str) -> str` replaces entire line with `[REDACTED]` on match. Called from `taskq.executor:build_result_record` before persistence. TBD-by-phase-2. |
| **Verification locus** | TDD-RED → TDD-GREEN → GATE1 → GATE2 → BASELINE |
| **Test case ID** | `tests/test_nfr03_reliability.py::test_nfr03_redact_sk_key` + `::test_nfr03_redact_token_assignment` + `::test_nfr03_no_match_preserves_line` + `::test_nfr03_redaction_entire_line_replaced`. TBD-by-phase-3. |
| **Bidirectional link notes** | Applied to `stdout_tail`/`stderr_tail` fields from AC-FR-02.4.a. |

**NFR-03 subtotal (forward)**: 2 ACs.

---

## 2. Backward Matrix — Test → Design → Requirement (per-AC rows)

This is the canonical backward walk. For each AC, the test case ID is restated with explicit reverse links back to design element and source AC, so any test failure can be traced to the requirement it verifies.

| Test case ID (in progress) | Verifies AC ID | Design element (module:construct) | Source requirement | Owner module |
|----------------------------|----------------|-----------------------------------|--------------------|--------------|
| `tests/test_fr01_submit.py::test_fr01_empty_command_rejected` | AC-FR-01.2.a | `taskq.cli:validate_submit_command` | SRS §3 FR-01.2 — 非空 | taskq.cli |
| `tests/test_fr01_submit.py::test_fr01_length_over_1000_rejected` | AC-FR-01.2.b | `taskq.cli:validate_submit_command` | SRS §3 FR-01.2 — 長度 | taskq.cli |
| `tests/test_fr01_submit.py::test_fr01_injection_chars_all_seven_rejected` | AC-FR-01.2.c, AC-NFR-02.b | `taskq.cli:INJECTION_CHARS` + `validate_submit_command` | SRS §3 FR-01.2 — 注入字元 + §4 NFR-02 | taskq.cli |
| `tests/test_fr01_submit.py::test_fr01_id_is_eight_lowercase_hex` | AC-FR-01.3.a | `taskq.cli:generate_task_id` | SRS §3 FR-01.3 — uuid4 前 8 hex | taskq.cli |
| `tests/test_fr01_submit.py::test_fr01_initial_record_fields` | AC-FR-01.3.b | `taskq.cli:new_task_record` | SRS §3 FR-01.3 — pending/command/created_at | taskq.cli |
| `tests/test_fr01_store.py::test_fr01_atomic_write_no_partial_observed` | AC-FR-01.3.c, AC-NFR-03.a | `taskq.store:atomic_write_json` | SRS §3 FR-01.3 — tmp + os.replace + §4 NFR-03 | taskq.store |
| `tests/test_fr01_store.py::test_fr01_corrupted_store_exits_one_no_rebuild` | AC-FR-01.3.d, AC-FR-03.3.d | `taskq.store:load_store` + `taskq.cli:cli_main` | SRS §3 FR-01.3 — 損壞 + §3 FR-03.3 — exit 1 | taskq.store / taskq.cli |
| `tests/test_fr02_executor.py::test_fr02_subprocess_kwargs_verbatim` | AC-FR-02.2.a | `taskq.executor:run_command` | SRS §3 FR-02.2 — subprocess.run kwargs | taskq.executor |
| `tests/test_nfr02_security.py::test_nfr02_no_shell_true_anywhere` | AC-FR-02.2.b, AC-NFR-02.a | `taskq.executor:run_command` + codebase scan | SRS §3 FR-02.2 — 不得 shell=True + §4 NFR-02 | taskq.executor / test harness |
| `tests/test_fr02_executor.py::test_fr02_exit_zero_done` | AC-FR-02.3.a | `taskq.executor:execute` | SRS §3 FR-02.3 — exit 0 → done | taskq.executor |
| `tests/test_fr02_executor.py::test_fr02_nonzero_exit_failed` | AC-FR-02.3.b | `taskq.executor:execute` | SRS §3 FR-02.3 — 非 0 → failed | taskq.executor |
| `tests/test_fr02_executor.py::test_fr02_timeout_expired_state` | AC-FR-02.3.c | `taskq.executor:execute` | SRS §3 FR-02.3 — TimeoutExpired → timeout | taskq.executor |
| `tests/test_fr02_executor.py::test_fr02_result_fields_present` | AC-FR-02.4.a | `taskq.executor:build_result_record` | SRS §3 FR-02.4 — 5 fields | taskq.executor |
| `tests/test_fr02_executor.py::test_fr02_tail_truncation_2000_chars` | AC-FR-02.4.a | `taskq.executor:build_result_record` | SRS §3 FR-02.4 — 末 2000 字元 | taskq.executor |
| `tests/test_fr02_executor.py::test_fr02_retry_caps_at_limit` | AC-FR-02.5.a | `taskq.executor:execute_with_retry` | SRS §3 FR-02.5 — TASKQ_RETRY_LIMIT | taskq.executor |
| `tests/test_fr02_executor.py::test_fr02_no_retry_on_done` | AC-FR-02.5.a | `taskq.executor:execute_with_retry` | SRS §3 FR-02.5 — 無 retry on done | taskq.executor |
| `tests/test_fr02_executor.py::test_fr02_retry_default_two` | AC-FR-02.5.a | `taskq.executor:execute_with_retry` + `taskq.config:resolve_retry_limit` | SRS §3 FR-02.5 — 預設 2 | taskq.executor / taskq.config |
| `tests/test_fr02_executor.py::test_fr02_single_task_timeout_exits_four` | AC-FR-02.6.a, AC-FR-03.3.c | `taskq.executor:execute_with_retry` + `taskq.cli:cmd_run` | SRS §3 FR-02.6 — exit 4 + §3 FR-03.3 — exit 4 | taskq.executor / taskq.cli |
| `tests/test_fr02_executor.py::test_fr02_unexpected_exception_exits_one` | AC-FR-02.6.b, AC-FR-03.3.d | `taskq.executor:execute` + `taskq.cli:cli_main` | SRS §3 FR-02.6 — exit 1 + §3 FR-03.3 — exit 1 | taskq.executor / taskq.cli |
| `tests/test_nfr02_security.py::test_nfr02_no_bare_except` | AC-FR-02.6.b | AST scan of `taskq/executor.py` | SRS §3 FR-02.6 — 不得裸 except | taskq.executor |
| `tests/test_fr03_cli.py::test_fr03_status_prints_all_fields` | AC-FR-03.1.a, AC-NFR-01.a | `taskq.cli:cmd_status` | SRS §3 FR-03.1 — status 全欄位 | taskq.cli |
| `tests/test_fr03_cli.py::test_fr03_status_unknown_id_exits_two` | AC-FR-03.1.b, AC-FR-03.3.b | `taskq.cli:cmd_status` + `cli_main` | SRS §3 FR-03.1 — unknown id + §3 FR-03.3 — exit 2 | taskq.cli |
| `tests/test_fr03_cli.py::test_fr03_status_unknown_id_stderr_message_verbatim` | AC-FR-03.1.b | `taskq.cli:cmd_status` | SRS §3 FR-03.1 — `unknown task: <id>` | taskq.cli |
| `tests/test_fr03_cli.py::test_fr03_list_one_line_per_task` | AC-FR-03.1.c | `taskq.cli:cmd_list` | SRS §3 FR-03.1 — list 行 | taskq.cli |
| `tests/test_fr03_cli.py::test_fr03_list_command_truncated_to_50_chars` | AC-FR-03.1.c | `taskq.cli:cmd_list` | SRS §3 FR-03.1 — command 前 50 字元 | taskq.cli |
| `tests/test_fr03_cli.py::test_fr03_clear_empties_store` | AC-FR-03.1.d, AC-FR-01.3.c, AC-NFR-03.a | `taskq.cli:cmd_clear` + `taskq.store:atomic_write_json` | SRS §3 FR-03.1 — clear + §3 FR-01.3 — atomic + §4 NFR-03 | taskq.cli / taskq.store |
| `tests/test_fr03_cli.py::test_fr03_json_flag_emits_single_line` | AC-FR-03.2.a | `taskq.cli:emit_json` | SRS §3 FR-03.2 — 單行 JSON | taskq.cli |
| `tests/test_fr03_cli.py::test_fr03_json_flag_parseable` | AC-FR-03.2.a | `taskq.cli:emit_json` | SRS §3 FR-03.2 — 單行 JSON | taskq.cli |
| `tests/bench/test_nfr01_p95.py::test_nfr01_submit_status_p95_under_50ms` | AC-NFR-01.a | end-to-end submit+status loop | SRS §4 NFR-01 — p95 < 50ms | test harness |
| `tests/test_nfr02_security.py::test_nfr02_no_shell_true_codebase_wide` | AC-NFR-02.a | AST scan of `taskq/**/*.py` | SRS §4 NFR-02 — 全 codebase 禁用 shell=True | test harness |
| `tests/test_nfr02_security.py::test_nfr02_blacklist_coverage` | AC-NFR-02.b, AC-FR-01.2.c | coverage metric on `validate_submit_command` | SRS §4 NFR-02 — 注入字元黑名單測試覆蓋 + §3 FR-01.2 | taskq.cli / test harness |
| `tests/test_nfr03_reliability.py::test_nfr03_crash_mid_write_recovery` | AC-NFR-03.a, AC-FR-01.3.c | `taskq.store:atomic_write_json` | SRS §4 NFR-03 — 原子寫 + §3 FR-01.3 | taskq.store |
| `tests/test_nfr03_reliability.py::test_nfr03_redact_sk_key` | AC-NFR-03.b | `taskq.redaction:redact_line` | SRS §4 NFR-03 — sk- regex | taskq.redaction |
| `tests/test_nfr03_reliability.py::test_nfr03_redact_token_assignment` | AC-NFR-03.b | `taskq.redaction:redact_line` | SRS §4 NFR-03 — token= regex | taskq.redaction |
| `tests/test_nfr03_reliability.py::test_nfr03_no_match_preserves_line` | AC-NFR-03.b | `taskq.redaction:redact_line` | SRS §4 NFR-03 — 整行取代 | taskq.redaction |
| `tests/test_nfr03_reliability.py::test_nfr03_redaction_entire_line_replaced` | AC-NFR-03.b | `taskq.redaction:redact_line` | SRS §4 NFR-03 — 整行取代 | taskq.redaction |

**Test case count**: 36 distinct test cases (more than 30 ACs because some ACs have parametric/multi-case coverage, e.g., AC-FR-01.2.c enumerates 7 chars, AC-FR-02.5.a has 3 distinct retry scenarios). All test cases are TBD-by-phase-3 (per-FR TDD).

---

## 3. Owner × AC × Test Cross-Reference (three-way matrix)

Each cell shows `AC-ID → test count` for that owner. Empty cells indicate the owner has no ACs.

| Owner module | AC IDs owned | Test cases (count) | Backing-test locus |
|--------------|--------------|--------------------|--------------------|
| `taskq.cli` | AC-FR-01.2.a, AC-FR-01.2.b, AC-FR-01.2.c, AC-FR-01.3.a, AC-FR-01.3.b, AC-FR-03.1.a, AC-FR-03.1.b, AC-FR-03.1.c, AC-FR-03.1.d, AC-FR-03.2.a, AC-FR-03.3.a, AC-FR-03.3.b, AC-FR-03.3.d, AC-NFR-02.b | 14 ACs → 19 tests | `tests/test_fr01_submit.py` + `tests/test_fr03_cli.py` |
| `taskq.executor` | AC-FR-02.2.a, AC-FR-02.2.b, AC-FR-02.3.a, AC-FR-02.3.b, AC-FR-02.3.c, AC-FR-02.4.a, AC-FR-02.5.a, AC-FR-02.6.a, AC-FR-02.6.b, AC-FR-03.3.c | 10 ACs → 13 tests | `tests/test_fr02_executor.py` |
| `taskq.store` | AC-FR-01.3.c, AC-FR-01.3.d, AC-NFR-03.a | 3 ACs → 3 tests | `tests/test_fr01_store.py` + `tests/test_nfr03_reliability.py` |
| `taskq.redaction` | AC-NFR-03.b | 1 AC → 4 tests | `tests/test_nfr03_reliability.py` |
| `taskq.config` | (cross-cutting — no direct AC ownership) | 0 ACs → 1 indirect test (AC-FR-02.5.a `::test_fr02_retry_default_two` exercises config) | `tests/test_fr02_executor.py` |
| `test harness` | AC-NFR-01.a, AC-NFR-02.a | 2 ACs → 3 tests | `tests/bench/test_nfr01_p95.py` + `tests/test_nfr02_security.py` |
| **Total** | 30 ACs | 36 tests (parametric coverage of multi-case ACs) | |

Cross-references:
- `taskq.config` is cross-cutting (resolves `TASKQ_HOME`, `TASKQ_TASK_TIMEOUT`, `TASKQ_RETRY_LIMIT`) but does not own any AC row directly; it is referenced from AC-FR-02.2.a (`timeout=TASKQ_TASK_TIMEOUT`), AC-FR-02.5.a (`TASKQ_RETRY_LIMIT`), AC-FR-01.3.c (`$TASKQ_HOME/tasks.json`), AC-FR-03.1.d (`$TASKQ_HOME/tasks.json`).

---

## 4. Cross-Cutting Bindings (NFR ↔ FR ↔ Test)

| NFR | Binds to FR AC(s) | Backing test(s) | Why |
|-----|--------------------|-----------------|-----|
| NFR-01 (performance) | AC-FR-01.3.c, AC-FR-03.1.a | `tests/bench/test_nfr01_p95.py::test_nfr01_submit_status_p95_under_50ms` | `submit` + `status` exercises store write + read paths; p95 bound covers both. |
| NFR-02.a (no shell=True) | AC-FR-02.2.b | `tests/test_nfr02_security.py::test_nfr02_no_shell_true_anywhere` + `::test_nfr02_no_shell_true_codebase_wide` | Same rule, two verification loci: unit test on executor + codebase scan (NFR-02.a). |
| NFR-02.b (injection-char test coverage) | AC-FR-01.2.c | `tests/test_nfr02_security.py::test_nfr02_blacklist_coverage` + `tests/test_fr01_submit.py::test_fr01_injection_chars_all_seven_rejected` | The blacklist AC and its test coverage are the same requirement viewed from two angles. |
| NFR-03.a (atomic write) | AC-FR-01.3.c | `tests/test_fr01_store.py::test_fr01_atomic_write_no_partial_observed` + `tests/test_nfr03_reliability.py::test_nfr03_crash_mid_write_recovery` | Atomic write is the same property; FR owns the writer, NFR owns the crash-resilience claim. |
| NFR-03.b (redaction) | AC-FR-02.4.a | `tests/test_nfr03_reliability.py::test_nfr03_redact_sk_key` + `::test_nfr03_redact_token_assignment` + `::test_nfr03_no_match_preserves_line` + `::test_nfr03_redaction_entire_line_replaced` | Redaction applies to the `stdout_tail`/`stderr_tail` fields created by FR-02.4.a. |

---

## 5. Coverage Validation (Round 1)

Validation against SRS.md + SPEC_TRACKING.md:

- [x] **All 30 canonical AC IDs** from SPEC_TRACKING.md §3 are present as exactly one row in §1 of this matrix.
- [x] **Forward linkage**: every AC row in §1 names a design element (owner module + construct).
- [x] **Backward linkage**: every AC row in §1 names a test case ID (§2 restates test→AC→design in reverse).
- [x] **Cross-cutting NFR bindings** documented in §4 (same as SPEC_TRACKING.md §5, with test IDs added).
- [x] **Three-way owner × AC × test** cross-reference in §3 reconciles to 30 ACs and 36 test cases.
- [x] **No new FR/NFR/AC/design/test invented** — all entries derive from approved SRS.md + SPEC_TRACKING.md. Design constructs and test names marked `TBD-by-phase-2` / `TBD-by-phase-3` use the names Phase 2/3 are expected to assign (no new naming invention).
- [x] **Verification locus per row** matches SPEC_TRACKING.md §1 + §2 (no locus changed).
- [x] **Cross-checks**:
  - AC-FR-01.2.c (injection blacklist) ↔ AC-NFR-02.b (test coverage requirement) — same rule, two views, both rows present.
  - AC-FR-02.2.b (no shell=True under run) ↔ AC-NFR-02.a (codebase-wide no shell=True) — same rule, two views, both rows present.
  - AC-FR-01.3.c (atomic write) ↔ AC-NFR-03.a (atomic write crash resilience) — same property, FR owns writer, NFR owns crash claim, both rows present.
  - AC-FR-02.6.a (single-task timeout exit 4) ↔ AC-FR-03.3.c (global exit 4 on timeout) — exit-code routing pair, both rows present.
  - AC-FR-02.6.b (unexpected exception exit 1) ↔ AC-FR-03.3.d (global exit 1 on internal errors) — exit-code routing pair, both rows present.
  - AC-FR-03.1.b (unknown task id exit 2) ↔ AC-FR-03.3.b (exit 2 on validation failure) — exit-code routing pair, both rows present.

---

## 6. Status Snapshot (Round 1, 2026-06-29)

| Bucket | DRAFT | OWNED | TESTED | VERIFIED | BLOCKED |
|--------|-------|-------|--------|----------|---------|
| FR-01 (7 ACs / 7 tests) | 7 | 0 | 0 | 0 | 0 |
| FR-02 (9 ACs / 13 tests) | 9 | 0 | 0 | 0 | 0 |
| FR-03 (9 ACs / 11 tests) | 9 | 0 | 0 | 0 | 0 |
| NFR-01 (1 AC / 1 test) | 1 | 0 | 0 | 0 | 0 |
| NFR-02 (2 ACs / 3 tests) | 2 | 0 | 0 | 0 | 0 |
| NFR-03 (2 ACs / 5 tests) | 2 | 0 | 0 | 0 | 0 |
| **Total (30 ACs / 36 tests)** | **30** | **0** | **0** | **0** | **0** |

Initial state: all ACs and tests `DRAFT`. Round 2+ will transition rows to `OWNED` as Phase 2 architecture assigns design elements, then to `TESTED` per Phase 3 per-FR TDD, then to `VERIFIED` per Phase 4–6 gates.

---

## 7. Open Items for Phase 2 / Phase 3 Handoff

1. **Design element naming finalization**: Phase 2 architecture may rename `taskq.cli:validate_submit_command`, `taskq.executor:execute_with_retry`, etc. Round 2 should reconcile any restructure here.
2. **Test file naming**: TBD-by-phase-3 — current test file names (`tests/test_fr01_submit.py`, etc.) follow the convention `test_fr<NN>_<scope>.py`. Phase 3 should adopt or revise.
3. **NFR-01 harness script location**: confirm whether `tests/bench/test_nfr01_p95.py` lives under `tests/bench/` (separate) or `tests/` (flat).
4. **NFR-02 AST scan implementation**: confirm whether the scan is a static AST check (tree-sitter / Python `ast`), a grep, or both.
5. **NFR-03 crash-injection harness**: confirm tooling for `kill -9` mid-write (pytest fixture vs subprocess helper).
6. **Redaction regex binding**: confirm that `taskq.redaction:redact_line` is invoked from `taskq.executor:build_result_record` (not from a separate post-write hook). Round 1 assumes pre-write filter inside the executor.
7. **Exit-code 4 routing owner**: confirm whether `taskq.cli:cmd_run` or `taskq.executor:execute_with_retry` performs the `sys.exit(4)` translation. Round 1 splits: executor returns sentinel, cli translates to exit.

These are observational notes for downstream phases; no action required from TRACEABILITY_MATRIX owner at Round 1.

---

*End of TRACEABILITY_MATRIX.md — Round 1 INGESTION deliverable for Phase 1.*
