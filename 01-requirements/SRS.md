# Software Requirements Specification (SRS) — taskq

> Source of truth: `/Users/johnny/projects/integration-test/SPEC.md` (v2.0.0, 2026-06-15)
> Project role: integration-test target for harness-methodology v2.9 pipeline validation
> Language: Python 3.11 (zero external runtime dependencies — stdlib only)

## 1. Introduction

### 1.1 Purpose
This document specifies the requirements for `taskq`, a local task queue CLI tool. The tool allows users to submit shell commands as tasks, execute them under control (timeout + retry), and query status. All operational requirements defined here originate from `SPEC.md` and are transcribed verbatim per INGESTION MODE rules.

### 1.2 Scope
`taskq` is a command-line interface invoked via `python -m taskq`. It supports `submit`, `run`, `status`, `list`, `clear` subcommands with task persistence in a JSON store and atomic write semantics.

### 1.3 Definitions, Acronyms, Abbreviations
- **FR**: Functional Requirement
- **NFR**: Non-Functional Requirement
- **AC**: Acceptance Criterion
- **atomic write**: write to temp file followed by `os.replace` rename
- **stdout_tail / stderr_tail**: last N chars of process output

### 1.4 References
- `SPEC.md` v2.0.0 (canonical specification)
- `PROJECT_BRIEF.md` (project brief)

### 1.5 Overview
The remainder of this SRS follows the structure required by the methodology: §2 Constraints, §3 Functional Requirements (one § per FR with verbatim AC + canonical citation), §4 Non-Functional Requirements, §5 Acceptance Criteria Summary, §6 Out-of-Scope, §7 Open Issues, §8 Risks, §9 Glossary.

## 2. Constraints

| ID | Constraint | Source |
|----|------------|--------|
| C-01 | Python 3.11 stdlib only | SPEC §1 |
| C-02 | `python -m taskq` CLI entry point | SPEC §1 |
| C-03 | `shell=True` forbidden everywhere in codebase | SPEC §2 / NFR-02 |
| C-04 | `tasks.json` atomic write (tmp + `os.replace`) | SPEC §2 / NFR-03 |
| C-05 | Configuration via `TASKQ_*` env vars (config.py) | SPEC §2 |
| C-06 | `shlex.split` for command tokenization | SPEC §2 |
| C-07 | Runtime zero external dependencies | PROJECT_BRIEF |

## 3. Functional Requirements

### FR-01: 任務模型與持久化 (Task Model and Persistence)

**Canonical source**: SPEC.md §3 FR-01

`taskq submit "<command>"`

#### 3.1.1 Validation Rules (任一違反 → exit 2 + stderr error, 不寫入存儲)

| Rule | Condition | AC |
|------|-----------|-----|
| Non-empty | 命令為空或全空白 → 拒絕 | `taskq submit ""` exits 2 and does not write store; `taskq submit "   "` exits 2 |
| Length | 命令 > 1000 字元 → 拒絕 | command of 1001 chars exits 2; command of 1000 chars accepted |
| Injection characters | 命令含 `;` `|` `&` `$` `>` `<` `` ` `` 任一 → 拒絕(NFR-02) | each of `;`, `\|`, `&`, `$`, `>`, `<`, `` ` `` rejected (NFR-02) |

#### 3.1.2 On Validation Pass

- 產生 task id (uuid4 前 8 hex) — AC: id is 8-char hex string
- 狀態 `pending`,記錄 `command`、`created_at` — AC: persisted record contains fields {id, command, status=pending, created_at}
- 原子寫入 `$TASKQ_HOME/tasks.json`(tmp + `os.replace`) — AC: store file is valid JSON after write; partial write does not corrupt
- `tasks.json` 損壞(非法 JSON)→ 啟動偵測 → exit 1,stderr `store corrupted`(不靜默重建) — AC: corrupted JSON triggers exit 1 with stderr text `store corrupted`; no auto-rebuild

### FR-02: 任務執行與重試 (Task Execution and Retry)

**Canonical source**: SPEC.md §3 FR-02

`taskq run <id>`

#### 3.2.1 Execution

> DERIVED: SPEC.md §3 FR-02 — one-line rationale: canonical lists specific `subprocess.run` kwargs but does not enumerate all kwargs (e.g. `check`, `cwd`, `env`); verbatim kwargs are transcribed, rest is harness-owned.

- 以 `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` 執行;**任何路徑不得使用 `shell=True`** — verbatim canonical phrase — measurement / interpretation boundary is owned by the test harness per SPEC.md §3 FR-02.

#### 3.2.2 State Machine

`pending → running → done | failed | timeout`

- exit 0 → `done` — AC: command with exit 0 transitions to `done`
- 非 0 → `failed` — AC: command with non-zero exit transitions to `failed`
- `TimeoutExpired` → `timeout` — AC: command exceeding `TASKQ_TASK_TIMEOUT` transitions to `timeout`

#### 3.2.3 Result Fields

> DERIVED: SPEC.md §3 FR-02 — one-line rationale: canonical phrase "末 2000 字元" is ambiguous between byte-count and char-count truncation; AC preserves verbatim phrase and defers measurement to harness.

| Field | Description |
|-------|-------------|
| `exit_code` | process return code |
| `stdout_tail` | 末 2000 字元 — verbatim canonical phrase — measurement / interpretation boundary is owned by the test harness per SPEC.md §3 FR-02 |
| `stderr_tail` | 末 2000 字元 — verbatim canonical phrase — measurement / interpretation boundary is owned by the test harness per SPEC.md §3 FR-02 |
| `duration_ms` | execution duration in ms |
| `finished_at` | ISO timestamp of completion |

#### 3.2.4 Retry

`run` 結果為 `failed`/`timeout` 時自動重試,上限 `TASKQ_RETRY_LIMIT` 次(預設 2) — AC: failed/timeout triggers retry up to `TASKQ_RETRY_LIMIT` times (default 2); done does NOT retry.

#### 3.2.5 Exit Codes

- 單一任務模式下 `timeout` 結果 → exit 4 — AC: in single-task mode, timeout yields exit 4
- 其他未預期例外 → exit 1(不得裸 `except:` 吞噬) — AC: unexpected exceptions exit 1; no bare `except:` swallow

### FR-03: CLI 整合與查詢 (CLI Integration and Query)

**Canonical source**: SPEC.md §3 FR-03

argparse 子命令(入口 `python -m taskq`):

| 命令 | 行為 |
|------|------|
| `submit "<cmd>"` | FR-01 — AC: dispatches to FR-01 validator + writer |
| `run <id>` | FR-02 — AC: dispatches to FR-02 executor |
| `status <id>` | 輸出該任務全欄位;unknown id → exit 2 + `unknown task: <id>` — AC: known id prints all fields; unknown id exits 2 with stderr `unknown task: <id>` |
| `list` | 列出全部任務(id + status + command 前 50 字元) — AC: list shows id, status, command truncated to 50 chars |
| `clear` | 清空 `$TASKQ_HOME/tasks.json` — AC: tasks.json becomes empty valid JSON after clear |

#### 3.3.1 Global Flags

- `--json`:機器可讀輸出(單行 JSON) — AC: with `--json`, output is single-line valid JSON parseable by `json.loads`

#### 3.3.2 Exit Codes

| Code | Meaning |
|------|---------|
| 0 | 成功 |
| 2 | 輸入驗證錯誤(含 unknown task id) |
| 4 | 任務 timeout |
| 1 | 其他內部錯誤 |

## 4. Non-Functional Requirements

### NFR-01: Performance

**Canonical source**: SPEC.md §4 NFR-01

**Verbatim canonical**: `submit` + `status` 組合操作 100 次 p95 < 50ms(不含 subprocess 執行) — verbatim canonical phrase — measurement / interpretation boundary is owned by the test harness per SPEC.md §4 NFR-01.

> DERIVED: SPEC.md §4 NFR-01 row — one-line rationale: canonical phrasing gives a numeric threshold but does not specify the p95 calculation algorithm (sort-and-index vs linear interpolation) or the warm-up methodology; AC restates the threshold verbatim and defers algorithm choice to the test harness.

**AC**: p95 of 100 combined `submit`+`status` invocations < 50ms; subprocess execution excluded.

### NFR-02: Security

**Canonical source**: SPEC.md §4 NFR-02

**Verbatim canonical**: 全 codebase 禁用 `shell=True`;FR-01 注入字元黑名單必須有測試覆蓋 — verbatim canonical phrase — measurement / interpretation boundary is owned by the test harness per SPEC.md §4 NFR-02.

> DERIVED: SPEC.md §4 NFR-02 row — one-line rationale: canonical says "必須有測試覆蓋" (must have test coverage) without specifying the coverage unit (per-character case vs per-rule case); AC interprets coverage as per-character and notes production-code grep boundary as a derived enforcement check.

**AC**: codebase-wide grep for `shell=True` returns zero hits in production code; FR-01 injection character blacklist has unit test coverage for each of `; | & $ > < \``.

### NFR-03: Reliability

**Canonical source**: SPEC.md §4 NFR-03

**Verbatim canonical**: `tasks.json` 原子寫(進程中斷後仍為合法 JSON);`stdout_tail`/`stderr_tail` 落盤前過濾 `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` 整行以 `[REDACTED]` 取代 — verbatim canonical phrase — measurement / interpretation boundary is owned by the test harness per SPEC.md §4 NFR-03.

> DERIVED: SPEC.md §4 NFR-03 row — one-line rationale: canonical specifies redaction pattern and atomic write but does not enumerate the kill-signal simulation mechanism or line-vs-partial-line matching semantics; AC restates canonical and labels test-mechanism boundary as harness-owned.

**AC**:
- Atomic write: simulated mid-write kill leaves `tasks.json` as valid JSON (tmp + `os.replace` semantics)
- Redaction: lines matching `sk-[A-Za-z0-9_-]{8,}` OR `token=\S+` are replaced with `[REDACTED]` before persistence

## 5. Configuration (config.py)

**Canonical source**: SPEC.md §5

| 變數 | 預設 | 說明 |
|------|------|------|
| `TASKQ_HOME` | `.taskq` | 資料檔目錄 |
| `TASKQ_TASK_TIMEOUT` | `10.0` | 單任務 subprocess timeout(秒) |
| `TASKQ_RETRY_LIMIT` | `2` | 失敗自動重試上限 |

**AC**: each variable has the documented default when env var unset; values consumed via `config.py`.

## 6. Acceptance Criteria Summary

| FR/NFR | AC Count | Testable |
|--------|----------|----------|
| FR-01 | 7 (3 validation rules + 4 pass-conditions) | Yes |
| FR-02 | 6 (exec + 3 state-machine + 2 exit codes + 1 retry) | Yes |
| FR-03 | 6 (5 subcommands + --json + exit code table) | Yes |
| NFR-01 | 1 (p95 < 50ms) | Yes (benchmark) |
| NFR-02 | 2 (no shell=True + blacklist tests) | Yes |
| NFR-03 | 2 (atomic write + redaction) | Yes |
| Config | 3 (default values) | Yes |

## 7. Out-of-Scope

- Concurrent task execution (single-worker design per SPEC.md)
- Network/remote submission
- Task priority / scheduling algorithms
- Web UI / daemon mode
- Cross-platform shell quirks (POSIX semantics assumed per `shlex.split`)

## 8. Open Issues

- **NFR-99**: Resolve SPEC.md §3 FR-02 "末 2000 字元" ambiguity between byte-count and char-count truncation semantics; test harness to confirm with stakeholder. Current SRS preserves verbatim canonical phrase and defers measurement to harness.
- **NFR-99**: Resolve SPEC.md §3 FR-02 `subprocess.run(...)` parameter set completeness — canonical lists specific params but does not enumerate all kwargs (e.g. `check`, `cwd`, `env`); test harness to confirm.
- **NFR-99**: Resolve SPEC.md §4 NFR-01 "100 次 p95" — p95 statistical method (sort then index vs quantile interpolation) is owned by test harness per canonical phrase "p95".
- Prompt-injection scan: clean — 0 hits in canonical.

## 9. Risks

| ID | Risk | Mitigation | Source |
|----|------|------------|--------|
| R1 | 並發/中斷寫入損壞 | NFR-03 atomic write | SPEC.md §4 |
| R2 | subprocess 懸掛 | FR-02 timeout | SPEC.md §4 |
| R3 | secret 落盤洩漏 | NFR-03 redaction | SPEC.md §4 |

## 10. Glossary

- **taskq**: Local task queue CLI; project codename and CLI entry (`python -m taskq`)
- **submit / run / status / list / clear**: Five CLI subcommands
- **pending / running / done / failed / timeout**: Task lifecycle states
- **tasks.json**: Persistent store under `$TASKQ_HOME`
- **TASKQ_HOME / TASKQ_TASK_TIMEOUT / TASKQ_RETRY_LIMIT**: Environment variables (config.py)
- **shell=True**: Forbidden `subprocess` flag (NFR-02)
- **atomic write**: `tmp + os.replace` pattern (NFR-03)
- **REDACTED**: Marker replacing secret lines matching `sk-[A-Za-z0-9_-]{8,}` or `token=\S+`

---

*Document version: SRS v1.0.0 (INGESTION MODE — transcribed from SPEC.md v2.0.0) | 2026-06-29*