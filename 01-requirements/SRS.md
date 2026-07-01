# Software Requirements Specification (SRS) — taskq

> Source of truth: `SPEC.md` v2.0.0 (2026-06-15). All FR-01..FR-03 and NFR-01..NFR-03 headings are transcribed verbatim from canonical spec.
> Mode: INGESTION (PROJECT_BRIEF.md → `canonical_spec: SPEC.md`). No invention. TBD/TODO/`<placeholder>` markers from SPEC.md captured as NFR-99 / FR-XX-deferred (none found in canonical).

---

## 1. Introduction

### 1.1 Purpose
This Software Requirements Specification (SRS) is the canonical requirements document for the `taskq` project. It transcribes the functional and non-functional requirements defined in `SPEC.md` v2.0.0 (2026-06-15) into a structured, testable form suitable for downstream architecture (Phase 2) and implementation (Phase 3).

### 1.2 Project Name
`taskq` — local task queue CLI tool for submitting shell commands as tasks and running them under control (timeout + retry).

### 1.3 Project Domain
Local task queue CLI tool. Stakeholders:
- Project owner / product manager: `johnnylugm-tech`
- Integration test target: harness-methodology v2.9 pipeline validation

### 1.4 Language & Runtime
- Language: Python 3.11
- Runtime: **zero external dependencies** (standard library only; test tooling provided by development environment)
- Form: command-line tool, entry `python -m taskq`

### 1.5 Conventions
- All `FR-XX` / `NFR-XX` identifiers below correspond 1:1 with the canonical `SPEC.md` headings.
- All acceptance criteria are transcribed verbatim from canonical lines (with measurement / interpretation boundary owned by the test harness per `<canonical-line>`).
- Where an interpretation choice is necessary beyond verbatim canonical, the AC carries a `DERIVED:` tag citing `<canonical-line>` immediately above.

---

## 2. Constraints

The following constraints are transcribed from `SPEC.md` §2 (技術架構) and `PROJECT_BRIEF.md` §Key Constraints.

| ID | Constraint | Source |
|----|------------|--------|
| C-01 | CLI implemented via argparse subcommands | SPEC §2 row `CLI \| argparse 子命令` |
| C-02 | Task execution via `subprocess` using `shlex.split`; `shell=True` is **forbidden everywhere** in the codebase | SPEC §2 + PROJECT_BRIEF §Key Constraints |
| C-03 | Persistence: JSON file with atomic write (`tmp + os.replace`) | SPEC §2 |
| C-04 | Configuration: `TASKQ_*` environment variables read uniformly via `config.py` | SPEC §2 |
| C-05 | Runtime: Python 3.11 stdlib only; entry point `python -m taskq` | PROJECT_BRIEF §Key Constraints |
| C-06 | Security: injection character blacklist (`; \| & $ > < \``) enforced on `submit` (see NFR-02) | PROJECT_BRIEF §Key Constraints |
| C-07 | Reliability: `tasks.json` atomic write must survive mid-write crash; never silently rebuilt on parse failure; secret-line redaction on `stdout_tail` / `stderr_tail` (see NFR-03) | PROJECT_BRIEF §Key Constraints |
| C-08 | Performance: `submit` + `status` combined p95 < 50ms over 100 iterations (see NFR-01) | PROJECT_BRIEF §Key Constraints |

---

## 3. Functional Requirements

### FR-01: 任務模型與持久化 (Task Model & Persistence)

**Canonical spec citation:** `SPEC.md` §3 — `### FR-01:任務模型與持久化`

**Command form:** `taskq submit "<command>"`

**Validation rules** — verbatim from canonical (any violation → **exit 2** + stderr error message, **no write to storage**):

| Rule | Condition |
|------|-----------|
| 非空 (Non-empty) | Command is empty or all whitespace → reject |
| 長度 (Length) | Command > 1000 characters → reject |
| 注入字元 (Injection chars) | Command contains any of `;` `|` `&` `$` `>` `<` `` ` `` → reject (NFR-02) |

**On passing validation** (verbatim from canonical):
- Generate task id (uuid4 first 8 hex)
- Status `pending`, record `command`, `created_at`
- Atomic write to `$TASKQ_HOME/tasks.json` (`tmp + os.replace`)
- `tasks.json` corrupted (invalid JSON) → startup detection → **exit 1**, stderr `store corrupted` (no silent rebuild)

**FR-01 Acceptance Criteria (verbatim from canonical):**

DERIVED: SPEC.md FR-01 — single canonical validation rule decomposed into per-rule ACs; "Owner (test harness)" column adds methodology wrapper, not new requirements.

- **AC-FR01-01 (Non-empty rejection):** `"非空 | 命令為空或全空白 → 拒絕"` — measurement boundary owned by test harness per `SPEC.md` FR-01 table row "非空".
DERIVED: SPEC.md FR-01 table row "長度" — "1000 chars inclusive vs exclusive" is interpretive boundary owned by test harness; canonical uses `>` strictly.
- **AC-FR01-02 (Length rejection):** `"長度 | 命令 > 1000 字元 → 拒絕"` — boundary condition (1000 chars inclusive vs exclusive) owned by test harness per `SPEC.md` FR-01 table row "長度".
- **AC-FR01-03 (Injection character blacklist):** `"注入字元 | 命令含 ; | & $ > < \` 任一 → 拒絕 (NFR-02)"` — character set and OR-semantics verbatim from canonical.
DERIVED: SPEC.md FR-01 — `format = [0-9a-f]{8}` interpretation of "uuid4 前 8 hex" is test-harness boundary.
- **AC-FR01-04 (Id generation):** `"產生 task id (uuid4 前 8 hex)"` — `前 8 hex` (first 8 hex chars) verbatim from canonical.
- **AC-FR01-05 (Pending state record):** `"狀態 pending,記錄 command、created_at"` — field set verbatim from canonical.
- **AC-FR01-06 (Atomic write):** `"原子寫入 $TASKQ_HOME/tasks.json (tmp + os.replace)"` — mechanism verbatim from canonical.
- **AC-FR01-07 (Corruption detection):** `"tasks.json 損壞(非法 JSON)→ 啟動偵測 → exit 1,stderr store corrupted(不靜默重建)"` — exit code, stderr message, and "no silent rebuild" constraint verbatim from canonical.

DERIVED: SPEC.md FR-01 preamble "任一違反 → exit 2 + stderr 錯誤訊息,不寫入存儲" — "no write to storage" lifted to its own AC for testability.
- **AC-FR01-08 (Reject writes nothing):** On any validation rule violation, **no write to storage** — verbatim from canonical preamble.

---

### FR-02: 任務執行與重試 (Task Execution & Retry)

**Canonical spec citation:** `SPEC.md` §3 — `### FR-02:任務執行與重試`

**Command form:** `taskq run <id>`

**Behavior** (verbatim from canonical):
- Execute with `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)`; **no path in the codebase may use `shell=True`**
- State machine: `pending → running → done | failed | timeout`
  - exit 0 → `done`; non-zero → `failed`; `TimeoutExpired` → `timeout`
- Result fields: `exit_code`, `stdout_tail` (last 2000 chars), `stderr_tail` (last 2000 chars), `duration_ms`, `finished_at`
- **Retry**: when `run` result is `failed`/`timeout`, auto-retry up to `TASKQ_RETRY_LIMIT` times (default 2)
- Single-task mode: `timeout` result → **exit 4**
- Other unexpected exceptions → exit 1 (no bare `except:` swallow)

**FR-02 Acceptance Criteria (verbatim from canonical):**

DERIVED: SPEC.md FR-02 — single canonical block decomposed into per-aspect ACs (invocation / state machine / result fields / retry / exit codes); no new requirements invented.

- **AC-FR02-01 (Subprocess invocation):** `"以 subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT) 執行;任何路徑不得使用 shell=True"` — invocation form and "no `shell=True`" prohibition verbatim from canonical.
- **AC-FR02-02 (State transitions):** `"狀態機:pending → running → done | failed | timeout"` with mapping `exit 0 → done; 非 0 → failed; TimeoutExpired → timeout` — verbatim from canonical.
DERIVED: SPEC.md FR-02 "末 2000 字元" — English gloss "last 2000 chars" is interpretive boundary owned by test harness; canonical number is 2000.
- **AC-FR02-03 (Result fields):** `"結果欄位:exit_code、stdout_tail(末 2000 字元)、stderr_tail(末 2000 字元)、duration_ms、finished_at"` — field names and `末 2000 字元` (last 2000 chars) verbatim from canonical.
- **AC-FR02-04 (Retry on failed/timeout):** `"run 結果為 failed/timeout 時自動重試,上限 TASKQ_RETRY_LIMIT 次(預設 2)"` — trigger set and limit verbatim from canonical.

DERIVED: SPEC.md FR-02 "單一任務模式下" — "single-task mode" scope is canonical phrase; harness boundary owns which invocation form constitutes "single-task mode".
- **AC-FR02-05 (Timeout exit code):** `"單一任務模式下 timeout 結果 → exit 4"` — exit code and scope ("single-task mode") verbatim from canonical.
- **AC-FR02-06 (Unhandled-exception exit code):** `"其他未預期例外 → exit 1(不得裸 except: 吞噬)"` — exit code and bare-except prohibition verbatim from canonical.

---

### FR-03: CLI 整合與查詢 (CLI Integration & Query)

**Canonical spec citation:** `SPEC.md` §3 — `### FR-03:CLI 整合與查詢`

**Entry:** `python -m taskq`

**Subcommands** (verbatim from canonical table):

| Command | Behavior |
|---------|----------|
| `submit "<cmd>"` | FR-01 |
| `run <id>` | FR-02 |
| `status <id>` | Output all task fields; unknown id → **exit 2** + `unknown task: <id>` |
| `list` | List all tasks (id + status + command first 50 chars) |
| `clear` | Clear `$TASKQ_HOME/tasks.json` |

- Global flag `--json`: machine-readable output (single-line JSON)
- **Exit codes**: `0` success / `2` input validation error (incl. unknown task id) / `4` task timeout / `1` other internal errors

**FR-03 Acceptance Criteria (verbatim from canonical):**

DERIVED: SPEC.md FR-03 — canonical subcommand table decomposed per row into ACs; no new requirements invented.

- **AC-FR03-01 (submit routes to FR-01):** `"submit \"<cmd>\" | FR-01"` — verbatim from canonical table.
- **AC-FR03-02 (run routes to FR-02):** `"run <id> | FR-02"` — verbatim from canonical table.
- **AC-FR03-03 (status unknown-id error):** `"status <id> | 輸出該任務全欄位;unknown id → exit 2 + unknown task: <id>"` — exit code, stderr/stdout message verbatim from canonical.

DERIVED: SPEC.md FR-03 "前 50 字元" — English gloss "first 50 chars" is interpretive boundary owned by test harness; canonical number is 50.
- **AC-FR03-04 (list truncation):** `"list | 列出全部任務(id + status + command 前 50 字元)"` — `前 50 字元` (first 50 chars) verbatim from canonical.
- **AC-FR03-05 (clear semantics):** `"clear | 清空 $TASKQ_HOME/tasks.json"` — verbatim from canonical table.
- **AC-FR03-06 (--json flag):** `"全域 flag --json:機器可讀輸出(單行 JSON)"` — verbatim from canonical.
- **AC-FR03-07 (Exit-code table):** `"0 成功 / 2 輸入驗證錯誤(含 unknown task id)/ 4 任務 timeout / 1 其他內部錯誤"` — exit code table verbatim from canonical.

---

## 4. Non-Functional Requirements

### NFR-01: Performance

**Canonical spec citation:** `SPEC.md` §4 — row `NFR-01 | performance`

**Requirement (verbatim from canonical):** `submit + status` combined operation 100 times p95 < 50ms (excluding subprocess execution)

DERIVED: SPEC.md §4 NFR-01 — "(excluding subprocess execution)" boundary gloss owned by test harness; canonical phrase "不含 subprocess 執行" verbatim.
**AC-NFR01-01 (p95 latency):** `"submit + status 組合操作 100 次 p95 < 50ms(不含 subprocess 執行)"` — `p95 < 50ms` and "100 次" iteration count verbatim from canonical; the "excluding subprocess execution" boundary is owned by the test harness per `SPEC.md` §4 NFR-01.

---

### NFR-02: Security

**Canonical spec citation:** `SPEC.md` §4 — row `NFR-02 | security`

**Requirement (verbatim from canonical):** `shell=True` is forbidden across the entire codebase; the FR-01 injection-character blacklist must have test coverage.

DERIVED: SPEC.md §4 NFR-02 — single canonical row decomposed into two ACs (forbid / coverage); no new requirements invented.
**AC-NFR02-01 (shell=True forbidden):** `"全 codebase 禁用 shell=True"` — verbatim from canonical.
**AC-NFR02-02 (Blacklist test coverage):** `"FR-01 注入字元黑名單必須有測試覆蓋"` — verbatim from canonical.

---

### NFR-03: Reliability

**Canonical spec citation:** `SPEC.md` §4 — row `NFR-03 | reliability`

**Requirement (verbatim from canonical):** `tasks.json` atomic write (must remain valid JSON after process interruption); before persisting, `stdout_tail` / `stderr_tail` must redact lines matching `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` by replacing the whole line with `[REDACTED]`.

DERIVED: SPEC.md §4 NFR-03 — single canonical row decomposed into two ACs (atomic write / redaction); regex `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` transcribed verbatim and not re-interpreted.
**AC-NFR03-01 (Atomic-write crash safety):** `"tasks.json 原子寫(進程中斷後仍為合法 JSON)"` — verbatim from canonical.
**AC-NFR03-02 (Secret-line redaction):** `"stdout_tail/stderr_tail 落盤前過濾 (sk-[A-Za-z0-9_-]{8,}|token=\S+) 整行以 [REDACTED] 取代"` — regex and replacement string verbatim from canonical.

---

## 5. Acceptance Criteria Summary

| AC ID | Requirement | Verbatim canonical phrase | Owner (test harness) |
|-------|-------------|---------------------------|----------------------|
| AC-FR01-01 | FR-01 non-empty | `非空 \| 命令為空或全空白 → 拒絕` | rejection observable on empty/whitespace input |
| AC-FR01-02 | FR-01 length | `長度 \| 命令 > 1000 字元 → 拒絕` | boundary test at 1000 / 1001 chars |
| AC-FR01-03 | FR-01 injection | `注入字元 \| 命令含 ; \| & $ > < \` 任一 → 拒絕 (NFR-02)` | per-character coverage |
| AC-FR01-04 | FR-01 id | `產生 task id (uuid4 前 8 hex)` | format = `[0-9a-f]{8}` |
| AC-FR01-05 | FR-01 pending state | `狀態 pending,記錄 command、created_at` | field presence on read |
| AC-FR01-06 | FR-01 atomic write | `原子寫入 $TASKQ_HOME/tasks.json (tmp + os.replace)` | crash-injection test |
| AC-FR01-07 | FR-01 corruption | `tasks.json 損壞(非法 JSON)→ 啟動偵測 → exit 1,stderr store corrupted(不靜默重建)` | startup detection + exit-1 |
| AC-FR01-08 | FR-01 no write on reject | (preamble) **不寫入存儲** | storage byte-for-byte unchanged |
| AC-FR02-01 | FR-02 invocation | `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT); 任何路徑不得使用 shell=True` | code grep + behavior test |
| AC-FR02-02 | FR-02 state machine | `pending → running → done \| failed \| timeout` | state transitions table |
| AC-FR02-03 | FR-02 result fields | `exit_code、stdout_tail(末 2000 字元)、stderr_tail(末 2000 字元)、duration_ms、finished_at` | field presence + tail length |
| AC-FR02-04 | FR-02 retry | `run 結果為 failed/timeout 時自動重試,上限 TASKQ_RETRY_LIMIT 次(預設 2)` | retry-counter test |
| AC-FR02-05 | FR-02 timeout exit | `單一任務模式下 timeout 結果 → exit 4` | single-task-mode exit code |
| AC-FR02-06 | FR-02 unhandled exit | `其他未預期例外 → exit 1(不得裸 except: 吞噬)` | exception injection test |
| AC-FR03-01 | FR-03 submit | `submit "<cmd>" \| FR-01` | routing test |
| AC-FR03-02 | FR-03 run | `run <id> \| FR-02` | routing test |
| AC-FR03-03 | FR-03 status unknown | `unknown id → exit 2 + unknown task: <id>` | message + exit code |
| AC-FR03-04 | FR-03 list truncation | `command 前 50 字元` | 50/51 char boundary |
| AC-FR03-05 | FR-03 clear | `清空 $TASKQ_HOME/tasks.json` | post-clear list is empty |
| AC-FR03-06 | FR-03 --json | `全域 flag --json:機器可讀輸出(單行 JSON)` | JSON parse round-trip |
| AC-FR03-07 | FR-03 exit codes | `0 成功 / 2 輸入驗證錯誤(含 unknown task id)/ 4 任務 timeout / 1 其他內部錯誤` | full exit-code matrix |
| AC-NFR01-01 | NFR-01 p95 | `p95 < 50ms(不含 subprocess 執行)` | harness owns subprocess-exclusion measurement |
| AC-NFR02-01 | NFR-02 shell=True | `全 codebase 禁用 shell=True` | repo-wide grep |
| AC-NFR02-02 | NFR-02 coverage | `FR-01 注入字元黑名單必須有測試覆蓋` | test-count on blacklist cases |
| AC-NFR03-01 | NFR-03 atomic | `原子寫(進程中斷後仍為合法 JSON)` | SIGKILL mid-write |
| AC-NFR03-02 | NFR-03 redaction | `(sk-[A-Za-z0-9_-]{8,}\|token=\S+) 整行以 [REDACTED] 取代` | regex unit + integration test |

---

## 6. Out-of-Scope

The following are explicitly NOT required by `SPEC.md` v2.0.0 and are therefore out of scope for this SRS:

- Concurrent `submit` from multiple processes (R1 mitigation is NFR-03 atomic write; multi-writer race is not specified)
- A daemon / long-running service form (only `python -m taskq` invocation is specified)
- Network APIs or remote submission (only local CLI is specified)
- Authentication / authorization (single-user local CLI)
- Config-file formats other than `TASKQ_*` environment variables (only env-vars + `.env.example` declared in SPEC §5)
- Internationalization / localization (only zh-TW canonical phrasing)

---

## 7. Open Issues

**Prompt-injection scan:** clean — 0 hits in canonical (`SPEC.md`).

**Deferred items from SPEC.md:** None. The canonical spec contains no TBD / TODO / `<placeholder>` markers in the transcribed sections (§3 FR-01..FR-03, §4 NFR-01..NFR-03, §5 config).

**NFR-99 / FR-XX-deferred placeholders:** None required. If during Phase 2/3 implementation a canonical ambiguity is discovered that cannot be resolved by the test harness boundary clause already in §1.5, an `NFR-99: Resolve <canonical-line> ambiguity in <FR-XX/NFR-XX> — current SPEC phrasing is ambiguous between <A> and <B>; test harness to confirm with stakeholder` entry will be added here per @rule R-CANONICAL-INTERP-001.

**Canonical ambiguities currently delegated to test harness (not NFR-99):**
- `SPEC.md FR-02 — "單一任務模式下 timeout 結果 → exit 4"`: canonical uses `單一任務模式` without defining which invocation form (single `run <id>` call vs `run` over a one-element queue vs. batch-mode default) constitutes "single-task mode". Measurement boundary owned by test harness per `SPEC.md FR-02`; not elevated to NFR-99 because canonical phrase is verbatim and a reasonable interpretation exists (default `run <id>` form).
- `SPEC.md FR-01 — "命令 > 1000 字元 → 拒絕"`: canonical uses `>` strictly; 1000/1001 char boundary inclusive/exclusive owned by test harness.
- `SPEC.md FR-01 — "uuid4 前 8 hex"`: regex `[0-9a-f]{8}` interpretation owned by test harness.
- `SPEC.md FR-02 — "末 2000 字元"` / `SPEC.md FR-03 — "前 50 字元"`: tail/head boundary gloss (ellipsis vs plain cut) owned by test harness.
- `SPEC.md §4 NFR-01 — "(不含 subprocess 執行)"`: subprocess-exclusion measurement boundary owned by test harness.
- `SPEC.md §4 NFR-03 — "進程中斷後仍為合法 JSON"`: failure-mode scope (SIGKILL mid-write vs power-loss / OOM-kill / partial-flush) owned by test harness.

---

## 8. Risks

| ID | Risk | Mitigation (from canonical) |
|----|------|------------------------------|
| R1 | Concurrent / interrupted writes corrupt `tasks.json` | NFR-03 (atomic write `tmp + os.replace`) |
| R2 | subprocess hangs indefinitely | FR-02 (`timeout=TASKQ_TASK_TIMEOUT`) |
| R3 | Secret leakage to persistent store | NFR-03 (secret-line redaction before persist) |

Source: `SPEC.md` §4 trailing paragraph.

---

## 9. Glossary

| Term | Definition |
|------|------------|
| taskq | The CLI tool name and project codename |
| task | A shell command submitted for controlled execution |
| submit | FR-01 entry-point subcommand |
| run | FR-02 entry-point subcommand |
| status / list / clear | FR-03 query / maintenance subcommands |
| atomic write | Write-via-tempfile + `os.replace`; yields valid JSON even on mid-write crash |
| p95 | 95th-percentile latency |
| `$TASKQ_HOME` | Configurable data directory (default `.taskq`); see SPEC §5 |
| `TASKQ_TASK_TIMEOUT` | Per-task subprocess timeout in seconds (default `10.0`); see SPEC §5 |
| `TASKQ_RETRY_LIMIT` | Auto-retry upper bound on `failed`/`timeout` (default `2`); see SPEC §5 |
| `tasks.json` | Persistent store under `$TASKQ_HOME` |
| canonical spec | `SPEC.md` v2.0.0 (2026-06-15) — single source of truth |
| `[REDACTED]` | Sentinel literal replacing redacted secret lines in `stdout_tail` / `stderr_tail` |

---

*End of SRS.md — transcribed from `SPEC.md` v2.0.0 (2026-06-15).*