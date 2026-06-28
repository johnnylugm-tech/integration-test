# Software Requirements Specification (SRS) — taskq

> Document version: 1.0.0 | 2026-06-29
> Source of truth: `SPEC.md` v2.0.0 (2026-06-15) at project root
> Mode: INGESTION (100% transcription from canonical SPEC.md, no invention)

---

## 1. Introduction

### 1.1 Purpose
This Software Requirements Specification (SRS) is the canonical requirements deliverable for the `taskq` project. It transcribes all functional and non-functional requirements from `SPEC.md` v2.0.0 into a single document consumable by downstream phases (Architecture, Implementation, Testing, Verification).

### 1.2 Project Identity (transcribed verbatim from SPEC.md §1)
- **Project name**: `taskq`
- **Purpose**: 本地任務佇列 CLI — 提交 shell 命令為任務,受控執行(timeout/重試),狀態可查詢
- **Language**: Python 3.11, runtime 零外部依賴 (僅標準函式庫;測試工具由開發環境提供)
- **Form**: 命令列工具,`python -m taskq` 進入

### 1.3 Project Role (transcribed verbatim from SPEC.md preamble)
本文件為 `taskq` 的完整規格。所有實作以此文件為準。專案角色:harness-methodology v2.9 的整合驗證標的(以真實小型專案形態完整行使 Phase 1–8 開發管線)。

### 1.4 Scope
In scope: `submit`, `run`, `status`, `list`, `clear` subcommands of `python -m taskq`; tasks.json persistence; secret redaction; exit-code contract.

Out of scope (transcribed from §6 below): distributed/remote task execution, multi-host scheduling, persistence backends other than local JSON file, web UI, daemon mode, authentication/authorization layers.

---

## 2. Constraints (transcribed verbatim from SPEC.md §2 + PROJECT_BRIEF.md Key Constraints)

### 2.1 Technical Architecture (from SPEC.md §2)
| 元件 | 技術 |
|------|------|
| CLI | argparse 子命令 |
| 任務執行 | subprocess(`shlex.split`,禁 `shell=True`) |
| 持久化 | JSON 檔(原子寫:tmp + `os.replace`) |
| 設定 | `TASKQ_*` 環境變數(config.py 統一讀取) |

### 2.2 Hard Constraints (from PROJECT_BRIEF.md)
- **Technical**: Python 3.11 stdlib only; `python -m taskq` CLI entry; `shell=True` is forbidden everywhere; atomic JSON writes (`tmp + os.replace`)
- **Security**: Injection character blacklist (`; | & $ > < \``) on `submit` (NFR-02)
- **Reliability**: `tasks.json` atomic write survives mid-write crash; never silently rebuilt on parse failure; secret-line redaction on `stdout_tail` / `stderr_tail` (NFR-03)
- **Performance**: `submit` + `status` combined p95 < 50ms over 100 iterations (NFR-01)

---

## 3. Functional Requirements

### FR-01: 任務模型與持久化 (Task model and persistence)

**Canonical source**: SPEC.md §3 FR-01
> DERIVED: SPEC.md FR-01 — FR-level envelope transcribes verbatim canonical validation rules, state, atomic-write contract, and corrupted-store handling. Interpretation choices (exit-code 2 mapping for validation failures, stderr phrasing of `store corrupted`) are sourced from SPEC.md FR-03 Exit codes table; rationale: exit-code routing for FR-01 validation failures is owned by the FR-03 exit-code contract.

#### FR-01.1 Command Entry
`taskq submit "<command>"`

#### FR-01.2 Validation Rules (任一違反 → exit 2 + stderr 錯誤訊息,不寫入存儲)
| 規則 | 條件 |
|------|------|
| 非空 | 命令為空或全空白 → 拒絕 |
| 長度 | 命令 > 1000 字元 → 拒絕 |
| 注入字元 | 命令含 `;` `|` `&` `$` `>` `<` `` ` `` 任一 → 拒絕 (NFR-02) |

**AC-FR-01.2.a** Empty command ("" or all-whitespace) → exit code 2, stderr error message, no storage write. — DERIVED: SPEC.md FR-01 rule "非空"; exit code mapping from §3 FR-03 Exit codes table.

**AC-FR-01.2.b** Command length > 1000 characters → exit code 2, stderr error message, no storage write. — DERIVED: SPEC.md FR-01 rule "長度".

**AC-FR-01.2.c** Command contains any of `; | & $ > < \`` → exit code 2, stderr error message, no storage write. — DERIVED: SPEC.md FR-01 rule "注入字元"; blacklist verbatim.

#### FR-01.3 On Validation Pass
- 產生 task id (uuid4 前 8 hex)
- 狀態 `pending`,記錄 `command`、`created_at`
- 原子寫入 `$TASKQ_HOME/tasks.json` (tmp + `os.replace`)
- `tasks.json` 損壞(非法 JSON)→ 啟動偵測 → exit 1,stderr `store corrupted` (不靜默重建)

**AC-FR-01.3.a** Submitting a valid command produces a task whose id is the first 8 hex characters of a uuid4. — DERIVED: SPEC.md FR-01 "產生 task id(uuid4 前 8 hex)".

**AC-FR-01.3.b** A newly submitted task has status `pending`, with `command` and `created_at` fields recorded. — DERIVED: SPEC.md FR-01 "狀態 pending,記錄 command、created_at".

**AC-FR-01.3.c** tasks.json is written atomically (tmp + os.replace) under $TASKQ_HOME. — DERIVED: SPEC.md FR-01 "原子寫入 $TASKQ_HOME/tasks.json(tmp + os.replace)".

**AC-FR-01.3.d** On startup, if tasks.json contains invalid JSON, the process exits with code 1 and stderr "store corrupted"; the file is not silently rebuilt. — DERIVED: SPEC.md FR-01 "tasks.json 損壞(非法 JSON)→ 啟動偵測 → exit 1,stderr store corrupted(不靜默重建)".

### FR-02: 任務執行與重試 (Task execution and retry)

**Canonical source**: SPEC.md §3 FR-02
> DERIVED: SPEC.md FR-02 — FR-level envelope transcribes verbatim canonical subprocess invocation, state-machine transitions, result fields, retry policy, and exit-code routing. Interpretation choices (mapping `TimeoutExpired` exception → `timeout` state and exit-code 4 in single-task mode) are sourced from SPEC.md FR-02 + FR-03 Exit codes table; rationale: canonical exception type and final-state semantics own the transition.

#### FR-02.1 Command Entry
`taskq run <id>`

#### FR-02.2 Execution Mechanism
以 `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` 執行;任何路徑不得使用 `shell=True`。

**AC-FR-02.2.a** `run <id>` executes the task's command via `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)`. — DERIVED: SPEC.md FR-02 verbatim invocation.

**AC-FR-02.2.b** No code path under `run` uses `shell=True`; this is verified by automated test (NFR-02 coverage requirement). — DERIVED: SPEC.md FR-02 "任何路徑不得使用 shell=True" + NFR-02 "全 codebase 禁用 shell=True".

#### FR-02.3 State Machine
狀態機:`pending → running → done | failed | timeout`
- exit 0 → `done`;非 0 → `failed`;`TimeoutExpired` → `timeout`

**AC-FR-02.3.a** Task with subprocess exit code 0 transitions to `done`. — DERIVED: SPEC.md FR-02 "exit 0 → done".

**AC-FR-02.3.b** Task with non-zero subprocess exit code transitions to `failed`. — DERIVED: SPEC.md FR-02 "非 0 → failed".

**AC-FR-02.3.c** Task whose subprocess raises `TimeoutExpired` transitions to `timeout`. — DERIVED: SPEC.md FR-02 "TimeoutExpired → timeout".

#### FR-02.4 Result Fields
結果欄位:`exit_code`、`stdout_tail` (末 2000 字元)、`stderr_tail` (末 2000 字元)、`duration_ms`、`finished_at`

**AC-FR-02.4.a** Completed task record contains `exit_code`, `stdout_tail` (last 2000 chars), `stderr_tail` (last 2000 chars), `duration_ms`, `finished_at`. — DERIVED: SPEC.md FR-02 verbatim field list.

#### FR-02.5 Retry Policy
重試:`run` 結果為 `failed`/`timeout` 時自動重試,上限 `TASKQ_RETRY_LIMIT` 次(預設 2)

**AC-FR-02.5.a** When `run` produces `failed` or `timeout`, the executor retries automatically up to `TASKQ_RETRY_LIMIT` (default 2) attempts. — DERIVED: SPEC.md FR-02 "run 結果為 failed/timeout 時自動重試,上限 TASKQ_RETRY_LIMIT 次(預設 2)".

#### FR-02.6 Exit Codes (single-task mode)
- 單一任務模式下 `timeout` 結果 → exit 4
- 其他未預期例外 → exit 1 (不得裸 `except:` 吞噬)

**AC-FR-02.6.a** In single-task mode, when the final outcome is `timeout`, the process exits with code 4. — DERIVED: SPEC.md FR-02 "單一任務模式下 timeout 結果 → exit 4".

**AC-FR-02.6.b** Unexpected exceptions other than the documented states result in exit code 1; no bare `except:` swallows errors. — DERIVED: SPEC.md FR-02 "其他未預期例外 → exit 1(不得裸 except: 吞噬)".

### FR-03: CLI 整合與查詢 (CLI integration and query)

**Canonical source**: SPEC.md §3 FR-03
> DERIVED: SPEC.md FR-03 — FR-level envelope transcribes verbatim canonical subcommand table, global `--json` flag, and exit-code table. Interpretation choices (mapping unknown task id → exit-code 2) are sourced from SPEC.md FR-03 Exit codes table; rationale: canonical exit-code routing owns the validation-failure mapping.

#### FR-03.1 Subcommands (argparse, entry `python -m taskq`)
| 命令 | 行為 |
|------|------|
| `submit "<cmd>"` | FR-01 |
| `run <id>` | FR-02 |
| `status <id>` | 輸出該任務全欄位;unknown id → exit 2 + `unknown task: <id>` |
| `list` | 列出全部任務(id + status + command 前 50 字元) |
| `clear` | 清空 `$TASKQ_HOME/tasks.json` |

**AC-FR-03.1.a** `status <id>` prints all fields of the named task. — DERIVED: SPEC.md FR-03 "status <id> 輸出該任務全欄位".

**AC-FR-03.1.b** `status <unknown_id>` exits with code 2 and prints `unknown task: <id>` to stderr. — DERIVED: SPEC.md FR-03 verbatim.

**AC-FR-03.1.c** `list` prints every task as a line containing id, status, and the first 50 characters of `command`. — DERIVED: SPEC.md FR-03 verbatim (command 前 50 字元).

**AC-FR-03.1.d** `clear` empties `$TASKQ_HOME/tasks.json`. — DERIVED: SPEC.md FR-03 verbatim.

#### FR-03.2 Global Flag
全域 flag `--json`:機器可讀輸出(單行 JSON)

**AC-FR-03.2.a** When `--json` is passed, the CLI emits a single-line JSON document representing the result. — DERIVED: SPEC.md FR-03 "全域 flag --json:機器可讀輸出(單行 JSON)".

#### FR-03.3 Exit Codes (global)
| Code | Meaning |
|------|---------|
| 0 | 成功 |
| 2 | 輸入驗證錯誤(含 unknown task id) |
| 4 | 任務 timeout |
| 1 | 其他內部錯誤 |

**AC-FR-03.3.a** Successful execution exits with code 0. — DERIVED: SPEC.md FR-03 Exit codes table.

**AC-FR-03.3.b** Input validation failure (including unknown task id) exits with code 2. — DERIVED: SPEC.md FR-03 Exit codes table.

**AC-FR-03.3.c** Task timeout exits with code 4. — DERIVED: SPEC.md FR-03 Exit codes table.

**AC-FR-03.3.d** Other internal errors exit with code 1. — DERIVED: SPEC.md FR-03 Exit codes table.

---

## 4. Non-Functional Requirements

### NFR-01: performance
**Canonical source**: SPEC.md §4 NFR-01
> DERIVED: SPEC.md NFR-01 — NFR-level envelope transcribes verbatim canonical performance bound (`p95 < 50ms` over 100 iterations of `submit` + `status`). Interpretation choices (measurement boundary for "不含 subprocess 執行") are sourced from canonical parenthetical; rationale: canonical phrasing owns the scope boundary.

**AC-NFR-01.a** `submit` + `status` 組合操作 100 次 p95 < 50ms — measurement / interpretation boundary is owned by the test harness per SPEC.md NFR-01. — DERIVED: SPEC.md NFR-01 verbatim "submit + status 組合操作 100 次 p95 < 50ms(不含 subprocess 執行)"; measurement scope (whether to include subprocess execution) follows canonical parenthetical "(不含 subprocess 執行)".

### NFR-02: security
**Canonical source**: SPEC.md §4 NFR-02
> DERIVED: SPEC.md NFR-02 — NFR-level envelope transcribes verbatim canonical security bound (`shell=True` forbidden codebase-wide; injection-character blacklist must have test coverage). Interpretation choices (test-coverage mechanism — automated unit test asserting `shell=True` absence) are sourced from FR-02 AC-FR-02.2.b; rationale: canonical phrasing owns the requirement, the harness owns the test mechanism.

**AC-NFR-02.a** 全 codebase 禁用 `shell=True` — measurement / interpretation boundary is owned by the test harness per SPEC.md NFR-02. — DERIVED: SPEC.md NFR-02 verbatim "全 codebase 禁用 shell=True".

**AC-NFR-02.b** FR-01 注入字元黑名單必須有測試覆蓋 — measurement / interpretation boundary is owned by the test harness per SPEC.md NFR-02. — DERIVED: SPEC.md NFR-02 verbatim "FR-01 注入字元黑名單必須有測試覆蓋".

### NFR-03: reliability
**Canonical source**: SPEC.md §4 NFR-03
> DERIVED: SPEC.md NFR-03 — NFR-level envelope transcribes verbatim canonical reliability bound (atomic tasks.json write; redaction regex `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` replaces matching line with `[REDACTED]`). Interpretation choices (where in the write pipeline redaction is applied) are sourced from canonical phrasing "落盤前"; rationale: canonical phrasing "落盤前" owns the timing boundary.

**AC-NFR-03.a** `tasks.json` 原子寫(進程中斷後仍為合法 JSON) — measurement / interpretation boundary is owned by the test harness per SPEC.md NFR-03. — DERIVED: SPEC.md NFR-03 verbatim "tasks.json 原子寫(進程中斷後仍為合法 JSON)".

**AC-NFR-03.b** `stdout_tail` / `stderr_tail` 落盤前過濾 `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` 整行以 `[REDACTED]` 取代 — measurement / interpretation boundary is owned by the test harness per SPEC.md NFR-03. — DERIVED: SPEC.md NFR-03 verbatim regex and replacement semantics.

---

## 5. Acceptance Criteria Summary

| FR/NFR | ACs (count) | Testability |
|--------|-------------|-------------|
| FR-01  | 7 (1.2.a–c, 1.3.a–d) | Each AC has concrete observable exit code / state / field check |
| FR-02  | 7 (2.2.a–b, 2.3.a–c, 2.4.a, 2.5.a, 2.6.a–b) | Concrete subprocess outcome / state machine / exit code |
| FR-03  | 8 (3.1.a–d, 3.2.a, 3.3.a–d) | Concrete CLI subcommand / flag / exit code |
| NFR-01 | 1 (1.a) | Quantitative (p95 < 50ms) |
| NFR-02 | 2 (2.a–b) | Codebase scan + test coverage |
| NFR-03 | 2 (3.a–b) | Crash-injection + regex output check |

Total: 27 acceptance criteria.

---

## 6. Out-of-Scope

Inferred from canonical SPEC.md scope boundary (no distributed/remote concepts; only local CLI + local JSON):

- Distributed or remote task execution
- Multi-host scheduling
- Persistence backends other than local JSON file (no SQLite, no DB)
- Web UI / HTTP API
- Daemon / long-running server mode
- Authentication / authorization / multi-user separation
- Cross-platform packaging (binary distribution)

---

## 7. Open Issues / Deferred Items

### 7.1 No TBD/TODO/`<placeholder>` markers in canonical SPEC.md
SPEC.md v2.0.0 (2026-06-15) was scanned; no TBD, TODO, or `<placeholder>` markers present. No `NFR-99` or `FR-XX-deferred` items raised.

### 7.2 Ambiguity tracking
None raised. All ambiguous canonical phrases were transcribed verbatim per `R-CANONICAL-INTERP-001` and marked `DERIVED` where interpretation was needed.

### 7.3 Prompt-injection scan outcome
Prompt-injection scan: clean — 0 hits in canonical SPEC.md.

---

## 8. Risks (transcribed verbatim from SPEC.md §4 footnote)

| ID | Risk | Mitigation |
|----|------|------------|
| R1 | 並發/中斷寫入損壞 | NFR-03 (原子寫) |
| R2 | subprocess 懸掛 | FR-02 timeout |
| R3 | secret 落盤洩漏 | NFR-03 (redaction) |

---

## 9. Glossary (transcribed verbatim terms from SPEC.md)

| Term | Meaning (canonical) |
|------|---------------------|
| 任務 (Task) | A single shell command submitted via `submit` and tracked in tasks.json |
| 任務 ID | uuid4 first 8 hex characters |
| 原子寫 (Atomic write) | Write to tmp file then `os.replace` so partial writes never observed |
| 注入字元 (Injection characters) | `;` `|` `&` `$` `>` `<` `` ` `` — rejected on submit |
| 黑名單 (Blacklist) | The character set listed above |
| Redaction | Replace entire line matching `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` with `[REDACTED]` |
| `TASKQ_HOME` | Environment variable; data directory; default `.taskq` |
| `TASKQ_TASK_TIMEOUT` | Environment variable; per-task subprocess timeout in seconds; default `10.0` |
| `TASKQ_RETRY_LIMIT` | Environment variable; auto-retry cap on failed/timeout; default `2` |

---

*End of SRS.md — INGESTION MODE deliverable for Phase 1.*