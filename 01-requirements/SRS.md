# Software Requirements Specification (SRS) — taskq

> Source of truth: `SPEC.md` v2.0.0 (2026-06-15) at project root.
> Ingestion mode: 100% transcription of canonical `### FR-01..FR-03` and `### NFR-01..NFR-03` headings from `SPEC.md` — no invention, no omission.
> TBD / TODO / `<placeholder>` markers: none present in canonical SPEC.md.

---

## 1. Introduction

### 1.1 Purpose
This Software Requirements Specification (SRS) transcribes the functional and non-functional requirements of the `taskq` local task queue CLI tool, as canonically defined in `SPEC.md` v2.0.0. Per `PROJECT_BRIEF.md`, the source of truth is `SPEC.md`; this SRS document operates in **INGESTION MODE** — every requirement originates from `SPEC.md` and is cited inline.

### 1.2 Scope
`taskq` is a local task queue CLI for submitting shell commands as tasks and running them under controlled execution (timeout + retry). Entry point: `python -m taskq`. Runtime: Python 3.11 standard library only (zero external runtime dependencies).

### 1.3 Definitions, Acronyms, Abbreviations
- **taskq** — the project name and CLI command namespace (`python -m taskq`)
- **task** — a submitted shell command tracked in `$TASKQ_HOME/tasks.json`
- **TASKQ_HOME** — environment variable defining the data directory (default `.taskq`)
- **Ingestion mode** — authoring style that transcribes canonical spec verbatim, with citations

### 1.4 References
- Canonical spec: `SPEC.md` (project root), v2.0.0, dated 2026-06-15
- Project brief: `PROJECT_BRIEF.md` (project root)

### 1.5 Overview
This document is organized per the canonical structure: §2 Constraints, §3 Functional Requirements, §4 Non-Functional Requirements, §5 Acceptance Criteria Summary, §6 Out-of-Scope, §7 Open Issues, §8 Risks, §9 Glossary.

---

## 2. Constraints

Constraints transcribed from canonical `SPEC.md` §2 技術架構 and PROJECT_BRIEF.md Key Constraints:

| ID | Category | Constraint | Source |
|----|----------|------------|--------|
| C-01 | Language | Python 3.11 standard library only; zero external runtime dependencies | `SPEC.md` §1 概述 |
| C-02 | Form factor | CLI tool; entry point `python -m taskq` | `SPEC.md` §1 概述 |
| C-03 | CLI parser | argparse subcommands | `SPEC.md` §2 技術架構 |
| C-04 | Task execution | subprocess (`shlex.split`; `shell=True` is forbidden everywhere) | `SPEC.md` §2 技術架構 |
| C-05 | Persistence | JSON file (atomic write: tmp + `os.replace`) | `SPEC.md` §2 技術架構 |
| C-06 | Configuration | `TASKQ_*` environment variables (unified read via `config.py`) | `SPEC.md` §2 技術架構 |
| C-07 | Security | Injection character blacklist (`;` `|` `&` `$` `>` < ` `` ` ``) on `submit` (see NFR-02) | `PROJECT_BRIEF.md` Key Constraints |
| C-08 | Reliability | `tasks.json` atomic write survives mid-write crash; never silently rebuilt on parse failure; secret-line redaction on `stdout_tail` / `stderr_tail` (NFR-03) | `PROJECT_BRIEF.md` Key Constraints |
| C-09 | Performance | `submit` + `status` combined p95 < 50ms over 100 iterations (NFR-01) | `PROJECT_BRIEF.md` Key Constraints |

---

## 3. Functional Requirements

### FR-01: Task Model and Persistence

**Canonical source (verbatim):** `SPEC.md` §3 FR-01 任務模型與持久化

```
`taskq submit "<command>"`

驗證規則(任一違反 → **exit 2** + stderr 錯誤訊息,**不寫入存儲**):

| 規則 | 條件 |
|------|------|
| 非空 | 命令為空或全空白 → 拒絕 |
| 長度 | 命令 > 1000 字元 → 拒絕 |
| 注入字元 | 命令含 `;` `|` `&` `$` `>` `<` `` ` `` 任一 → 拒絕(NFR-02) |

通過驗證:
- 產生 task id(uuid4 前 8 hex)
- 狀態 `pending`,記錄 `command`、`created_at`
- 原子寫入 `$TASKQ_HOME/tasks.json`(tmp + `os.replace`)
- `tasks.json` 損壞(非法 JSON)→ 啟動偵測 → **exit 1**,stderr `store corrupted`(不靜默重建)
```

**Acceptance criteria** — each AC is a verbatim canonical line; multiple ACs derive from a single canonical row to make each condition independently testable.

> DERIVED: `SPEC.md` §3 FR-01 驗證規則 table — single canonical row decomposed into one AC per 條件 (非空/長度/注入字元) for testability; measurement / interpretation boundary is owned by the test harness per `SPEC.md` §3 FR-01 驗證規則.

- AC-FR01-01: 「命令為空或全空白 → 拒絕」 — verbatim from `SPEC.md` §3 FR-01 驗證規則 非空 row.
- AC-FR01-02: 「命令 > 1000 字元 → 拒絕」 — verbatim from `SPEC.md` §3 FR-01 驗證規則 長度 row.
- AC-FR01-03: 「命令含 `;` `|` `&` `$` `>` `<` `` ` `` 任一 → 拒絕(NFR-02)」 — verbatim from `SPEC.md` §3 FR-01 驗證規則 注入字元 row.

> DERIVED: `SPEC.md` §3 FR-01 通過驗證 bullets — single canonical bullet list decomposed into one AC per bullet for testability; measurement / interpretation boundary is owned by the test harness per `SPEC.md` §3 FR-01 通過驗證.

- AC-FR01-04: 「產生 task id(uuid4 前 8 hex)」 — verbatim from `SPEC.md` §3 FR-01 通過驗證 bullet 1.
- AC-FR01-05: 「狀態 `pending`,記錄 `command`、`created_at`」 — verbatim from `SPEC.md` §3 FR-01 通過驗證 bullet 2.
- AC-FR01-06: 「原子寫入 `$TASKQ_HOME/tasks.json`(tmp + `os.replace`)」 — verbatim from `SPEC.md` §3 FR-01 通過驗證 bullet 3.
- AC-FR01-07: 「`tasks.json` 損壞(非法 JSON)→ 啟動偵測 → **exit 1**,stderr `store corrupted`(不靜默重建)」 — verbatim from `SPEC.md` §3 FR-01 通過驗證 bullet 4.

---

### FR-02: Task Execution and Retry

**Canonical source (verbatim):** `SPEC.md` §3 FR-02 任務執行與重試

```
`taskq run <id>`

- 以 `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` 執行;**任何路徑不得使用 `shell=True`**
- 狀態機:`pending → running → done | failed | timeout`
  - exit 0 → `done`;非 0 → `failed`;`TimeoutExpired` → `timeout`
- 結果欄位:`exit_code`、`stdout_tail`(末 2000 字元)、`stderr_tail`(末 2000 字元)、`duration_ms`、`finished_at`
- **重試**:`run` 結果為 `failed`/`timeout` 時自動重試,上限 `TASKQ_RETRY_LIMIT` 次(預設 2)
- 單一任務模式下 `timeout` 結果 → **exit 4**
- 其他未預期例外 → exit 1(不得裸 `except:` 吞噬)
```

**Acceptance criteria** — each AC is a verbatim canonical line.

> DERIVED: `SPEC.md` §3 FR-02 bullet list — decomposed into one AC per canonical bullet for testability; measurement / interpretation boundary is owned by the test harness per `SPEC.md` §3 FR-02.

- AC-FR02-01: 「以 `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` 執行;**任何路徑不得使用 `shell=True`**」 — verbatim from `SPEC.md` §3 FR-02 first bullet.
- AC-FR02-02: 「狀態機:`pending → running → done | failed | timeout`;exit 0 → `done`;非 0 → `failed`;`TimeoutExpired` → `timeout`」 — verbatim from `SPEC.md` §3 FR-02 state machine bullet.
- AC-FR02-03: 「結果欄位:`exit_code`、`stdout_tail`(末 2000 字元)、`stderr_tail`(末 2000 字元)、`duration_ms`、`finished_at`」 — verbatim from `SPEC.md` §3 FR-02 result fields bullet.
- AC-FR02-04: 「**重試**:`run` 結果為 `failed`/`timeout` 時自動重試,上限 `TASKQ_RETRY_LIMIT` 次(預設 2)」 — verbatim from `SPEC.md` §3 FR-02 retry bullet.
- AC-FR02-05: 「單一任務模式下 `timeout` 結果 → **exit 4**」 — verbatim from `SPEC.md` §3 FR-02 single-task-timeout bullet.
- AC-FR02-06: 「其他未預期例外 → exit 1(不得裸 `except:` 吞噬)」 — verbatim from `SPEC.md` §3 FR-02 exception bullet.

---

### FR-03: CLI Integration and Query

**Canonical source (verbatim):** `SPEC.md` §3 FR-03 CLI 整合與查詢

```
argparse 子命令(入口 `python -m taskq`):

| 命令 | 行為 |
|------|------|
| `submit "<cmd>"` | FR-01 |
| `run <id>` | FR-02 |
| `status <id>` | 輸出該任務全欄位;unknown id → **exit 2** + `unknown task: <id>` |
| `list` | 列出全部任務(id + status + command 前 50 字元) |
| `clear` | 清空 `$TASKQ_HOME/tasks.json` |

- 全域 flag `--json`:機器可讀輸出(單行 JSON)
- **Exit codes**:`0` 成功 / `2` 輸入驗證錯誤(含 unknown task id)/ `4` 任務 timeout / `1` 其他內部錯誤
```

**Acceptance criteria** — each AC is a verbatim canonical line.

> DERIVED: `SPEC.md` §3 FR-03 command table + bullets — decomposed into one AC per row/bullet for testability; measurement / interpretation boundary is owned by the test harness per `SPEC.md` §3 FR-03.

- AC-FR03-01: 「argparse 子命令(入口 `python -m taskq`):`submit`/`run`/`status`/`list`/`clear`」 — verbatim from `SPEC.md` §3 FR-03 command table.
- AC-FR03-02: 「`status <id>` 輸出該任務全欄位;unknown id → **exit 2** + `unknown task: <id>`」 — verbatim from `SPEC.md` §3 FR-03 status row.
- AC-FR03-03: 「`list` 列出全部任務(id + status + command 前 50 字元)」 — verbatim from `SPEC.md` §3 FR-03 list row.
- AC-FR03-04: 「`clear` 清空 `$TASKQ_HOME/tasks.json`」 — verbatim from `SPEC.md` §3 FR-03 clear row.
- AC-FR03-05: 「全域 flag `--json`:機器可讀輸出(單行 JSON)」 — verbatim from `SPEC.md` §3 FR-03 --json bullet.
- AC-FR03-06: 「**Exit codes**:`0` 成功 / `2` 輸入驗證錯誤(含 unknown task id)/ `4` 任務 timeout / `1` 其他內部錯誤」 — verbatim from `SPEC.md` §3 FR-03 Exit codes bullet.

---

## 4. Non-Functional Requirements

### NFR-01: Performance

**Canonical source (verbatim):** `SPEC.md` §4 NFR-01 row

```
| NFR-01 | performance | `submit` + `status` 組合操作 100 次 p95 < 50ms(不含 subprocess 執行) |
```

**Acceptance criteria:**

> DERIVED: `SPEC.md` §4 NFR-01 row — single canonical row kept as one AC verbatim; measurement / interpretation boundary (「不含 subprocess 執行」) is owned by the test harness per `SPEC.md` §4 NFR-01.

- AC-NFR01-01: 「`submit` + `status` 組合操作 100 次 p95 < 50ms(不含 subprocess 執行)」 — verbatim from `SPEC.md` §4 NFR-01.

---

### NFR-02: Security

**Canonical source (verbatim):** `SPEC.md` §4 NFR-02 row

```
| NFR-02 | security | 全 codebase 禁用 `shell=True`;FR-01 注入字元黑名單必須有測試覆蓋 |
```

**Acceptance criteria:**

> DERIVED: `SPEC.md` §4 NFR-02 row — single canonical row decomposed into one AC per clause (全 codebase 禁用 / 注入字元黑名單測試覆蓋) for testability; measurement / interpretation boundary is owned by the test harness per `SPEC.md` §4 NFR-02.

- AC-NFR02-01: 「全 codebase 禁用 `shell=True`」 — verbatim from `SPEC.md` §4 NFR-02 first clause.
- AC-NFR02-02: 「FR-01 注入字元黑名單必須有測試覆蓋」 — verbatim from `SPEC.md` §4 NFR-02 second clause.

---

### NFR-03: Reliability

**Canonical source (verbatim):** `SPEC.md` §4 NFR-03 row

```
| NFR-03 | reliability | `tasks.json` 原子寫(進程中斷後仍為合法 JSON);`stdout_tail`/`stderr_tail` 落盤前過濾 `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` 整行以 `[REDACTED]` 取代 |
```

**Acceptance criteria:**

> DERIVED: `SPEC.md` §4 NFR-03 row — single canonical row decomposed into one AC per clause (原子寫存活 / 整行 redaction) for testability; measurement / interpretation boundary is owned by the test harness per `SPEC.md` §4 NFR-03.

- AC-NFR03-01: 「`tasks.json` 原子寫(進程中斷後仍為合法 JSON)」 — verbatim from `SPEC.md` §4 NFR-03 first clause.
- AC-NFR03-02: 「`stdout_tail`/`stderr_tail` 落盤前過濾 `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` 整行以 `[REDACTED]` 取代」 — verbatim from `SPEC.md` §4 NFR-03 second clause.

---

## 5. Acceptance Criteria Summary

| AC ID | Requirement | Verbatim canonical anchor |
|-------|-------------|---------------------------|
| AC-FR01-01 | FR-01 non-empty reject | `SPEC.md` §3 FR-01 驗證規則 非空 |
| AC-FR01-02 | FR-01 length reject (>1000) | `SPEC.md` §3 FR-01 驗證規則 長度 |
| AC-FR01-03 | FR-01 injection char reject | `SPEC.md` §3 FR-01 驗證規則 注入字元 |
| AC-FR01-04 | FR-01 uuid4 first-8-hex id | `SPEC.md` §3 FR-01 通過驗證 bullet 1 |
| AC-FR01-05 | FR-01 pending state + fields | `SPEC.md` §3 FR-01 通過驗證 bullet 2 |
| AC-FR01-06 | FR-01 atomic write | `SPEC.md` §3 FR-01 通過驗證 bullet 3 |
| AC-FR01-07 | FR-01 corrupted-store exit 1 | `SPEC.md` §3 FR-01 通過驗證 bullet 4 |
| AC-FR02-01 | FR-02 subprocess w/o shell=True | `SPEC.md` §3 FR-02 first bullet |
| AC-FR02-02 | FR-02 state machine | `SPEC.md` §3 FR-02 state machine bullet |
| AC-FR02-03 | FR-02 result fields | `SPEC.md` §3 FR-02 result fields bullet |
| AC-FR02-04 | FR-02 retry on failed/timeout | `SPEC.md` §3 FR-02 retry bullet |
| AC-FR02-05 | FR-02 single-task timeout exit 4 | `SPEC.md` §3 FR-02 single-task-timeout bullet |
| AC-FR02-06 | FR-02 no bare except | `SPEC.md` §3 FR-02 exception bullet |
| AC-FR03-01 | FR-03 subcommands | `SPEC.md` §3 FR-03 command table |
| AC-FR03-02 | FR-03 status unknown id | `SPEC.md` §3 FR-03 status row |
| AC-FR03-03 | FR-03 list first-50-chars | `SPEC.md` §3 FR-03 list row |
| AC-FR03-04 | FR-03 clear | `SPEC.md` §3 FR-03 clear row |
| AC-FR03-05 | FR-03 --json single-line | `SPEC.md` §3 FR-03 --json bullet |
| AC-FR03-06 | FR-03 exit codes | `SPEC.md` §3 FR-03 Exit codes bullet |
| AC-NFR01-01 | NFR-01 p95 < 50ms | `SPEC.md` §4 NFR-01 |
| AC-NFR02-01 | NFR-02 no shell=True anywhere | `SPEC.md` §4 NFR-02 first clause |
| AC-NFR02-02 | NFR-02 injection blacklist test coverage | `SPEC.md` §4 NFR-02 second clause |
| AC-NFR03-01 | NFR-03 atomic write survives interruption | `SPEC.md` §4 NFR-03 first clause |
| AC-NFR03-02 | NFR-03 secret-line redaction pattern | `SPEC.md` §4 NFR-03 second clause |

Total: 25 acceptance criteria across 3 FRs and 3 NFRs.

---

## 6. Out-of-Scope

Per `SPEC.md`, the following are explicitly out-of-scope:

- OS-01: Network task submission (only local CLI; `TASKQ_HOME` is local filesystem)
- OS-02: Concurrent multi-process writers (atomic write is per-process; concurrent writer arbitration is not specified)
- OS-03: GUI / TUI interface (CLI argparse only per `SPEC.md` §2 技術架構)
- OS-04: Task scheduling / cron features (only on-demand `run` per `SPEC.md` §3 FR-02)
- OS-05: External secret-store integration (redaction is in-process pattern replacement only, per NFR-03)

---

## 7. Open Issues

Prompt-injection scan: clean — 0 hits in canonical `SPEC.md` (verified via grep on `ignore (previous|above|all)|system prompt|disregard|act as|you must|jailbreak|role:|<\s*system|<\s*user|<\s*assistant`).

No deferred items; no NFR-99 ambiguity markers required (canonical spec is non-ambiguous for all transcribed FRs/NFRs).

---

## 8. Risks

Per `SPEC.md` §4 risk merge paragraph:

| ID | Risk | Mitigation | Source |
|----|------|------------|--------|
| R1 | Concurrent/interrupted write corruption | Mitigated by NFR-03 (atomic write via tmp + `os.replace`) | `SPEC.md` §4 |
| R2 | subprocess hang | Mitigated by FR-02 timeout | `SPEC.md` §4 |
| R3 | Secret leakage to disk | Mitigated by NFR-03 (redaction before persist) | `SPEC.md` §4 |

---

## 9. Glossary

- **taskq** — project name and CLI namespace (`python -m taskq`)
- **task** — submitted shell command tracked in `$TASKQ_HOME/tasks.json`
- **TASKQ_HOME** — env var; data directory (default `.taskq`)
- **TASKQ_TASK_TIMEOUT** — env var; per-task subprocess timeout in seconds (default `10.0`)
- **TASKQ_RETRY_LIMIT** — env var; failed/timeout auto-retry cap (default `2`)
- **Ingestion mode** — authoring style transcribing canonical spec verbatim
- **DERIVED marker** — `DERIVED: <canonical-line> — <one-line rationale>` annotation placed above ACs where a single canonical row is decomposed into multiple independently testable ACs
- **canonical line** — a verbatim quote from `SPEC.md` used as the citation anchor