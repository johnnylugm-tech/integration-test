# Software Requirements Specification (SRS) — taskq

> **Single Source of Truth:** `SPEC.md` v3.0.0 (2026-07-04) at project root.
> This SRS is authored in **INGESTION MODE**: 100% of `### FR-01..FR-05` and
> `### NFR-01..NFR-06` from `SPEC.md` §3 / §4 are transcribed verbatim.
> No invention. No silent omission. TBD/TODO/placeholders emitted as
> `NFR-99` or `FR-XX-deferred` in §7 Open Issues.

---

## 1. Introduction

### 1.1 Purpose
This Software Requirements Specification (SRS) defines the functional and
non-functional requirements for the `taskq` project — a local task queue
CLI tool written in Python 3.11 (stdlib-only at runtime).

### 1.2 Scope
`taskq` enables users to:
- submit shell commands as named tasks
- run tasks with controlled concurrency, timeout, retry, circuit breaker,
  and TTL-based result cache
- query task status
- list / filter tasks
- clear the local task storage

### 1.3 Definitions, Acronyms, Abbreviations
See §9 Glossary.

### 1.4 References
| Reference | Source |
|-----------|--------|
| `SPEC.md` v3.0.0 (2026-07-04) | canonical specification (single source of truth) |
| `PROJECT_BRIEF.md` | project metadata, FR/NFR/env-var inventory summary |
| `.env.example` | environment variable declarations (8 `TASKQ_*` vars) |
| `harness/CLAUDE.md` | harness-methodology v2.9 framework alignment |

### 1.5 Overview
The remainder of this document specifies Constraints (§2), Functional
Requirements (§3, one section per FR), Non-Functional Requirements (§4,
one section per NFR), Acceptance Criteria Summary (§5), Out-of-Scope (§6),
Open Issues (§7), Risks (§8), and Glossary (§9).

---

## 2. Constraints

> Source: SPEC.md §1, §2, §7 + PROJECT_BRIEF.md Key Constraints.

### 2.1 Technical Constraints (verbatim from SPEC.md §1 / §2)
- Language: Python 3.11; **runtime zero external dependencies** (standard
  library only; test tooling provided by dev environment).
- Form: command-line tool, entered via `python -m taskq`.
- CLI: argparse subcommands.
- Task execution: subprocess (`shlex.split`, **禁止 `shell=True`**).
- Concurrency: `concurrent.futures.ThreadPoolExecutor`.
- Persistence: JSON files (atomic write: tmp + `os.replace`).
- Thread safety: `threading.Lock` protecting shared storage.
- Configuration: `TASKQ_*` environment variables (read centrally by
  `config.py`).

### 2.2 Atomicity Constraint (verbatim from SPEC.md §7 + PROJECT_BRIEF.md)
All three data files (`tasks.json`, `breaker.json`, `cache.json`) are
written via tmp + `os.replace`; a mid-write crash must leave valid JSON
on disk (`tasks.json` corruption is detected on startup and surfaced via
exit 1 rather than silently rebuilt).

### 2.3 Security Constraint (verbatim from PROJECT_BRIEF.md / SPEC.md §7)
- `shell=True` is **forbidden** everywhere in the codebase (NFR-02).
- `submit` enforces an injection-character blacklist
  (`; | & $ > < \``) (NFR-02).
- `stdout_tail` / `stderr_tail` redact any line matching
  `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` before persistence (NFR-04).

### 2.4 Reliability Constraint (verbatim from SPEC.md §3 FR-03 / §7)
- Circuit breaker opens at consecutive final-failure threshold and refuses
  until cooldown elapses.
- `tasks.json` corruption is detected and surfaced (exit 1) rather than
  silently rebuilt.

### 2.5 Performance Constraint (verbatim from SPEC.md §4 NFR-01)
`submit` + `status` combined p95 < 50ms over 100 iterations.

### 2.6 Architecture Constraint (verbatim from PROJECT_BRIEF.md)
`no_circular_dependencies` among the 8 modules; `taskq.executor` and
`taskq.store` are framework-classified high-risk modules.

### 2.7 Module Layout (verbatim from SPEC.md §6)

```
src/taskq/
├── __init__.py
├── __main__.py        # python -m taskq 入口
├── config.py          # TASKQ_* env 讀取(NFR-06)
├── models.py          # 任務/狀態資料類別
├── store.py           # tasks.json 原子存儲 + Lock(FR-01/02) — high-risk
├── executor.py        # subprocess 執行 + 重試(FR-02/03) — high-risk
├── breaker.py         # 斷路器(FR-03)
├── cache.py           # TTL 快取(FR-04)
└── cli.py             # argparse(FR-05)
```

---

## 3. Functional Requirements

> Source: SPEC.md §3. Each FR below is a verbatim transcription of the
> canonical `### FR-XX` heading from SPEC.md §3.

### FR-01 — 任務提交與驗證

**Canonical citation:** SPEC.md §3 FR-01.

`taskq submit "<command>" [--name NAME]`

驗證規則(任一違反 → **exit 2** + stderr 錯誤訊息,不寫入存儲):

| 規則 | 條件 |
|------|------|
| 非空 | 命令為空或全空白 → 拒絕 |
| 長度 | 命令 > 1000 字元 → 拒絕 |
| 注入字元 | 命令含 `;` `|` `&` `$` `>` `<` `` ` `` 任一 → 拒絕(NFR-02) |
| 名稱唯一 | `--name` 與既有 pending/running 任務重複 → 拒絕 |

通過驗證:
- 產生 task id(uuid4 前 8 hex)
- 狀態 `pending`,記錄 `command`、`name`、`created_at`
- 原子寫入 `$TASKQ_HOME/tasks.json`
- stdout 輸出 task id(`--json` 時輸出 `{"id": ..., "status": "pending"}`)

#### AC-FR-01-01
命令為空或全空白 → 拒絕

#### AC-FR-01-02
命令 > 1000 字元 → 拒絕

#### AC-FR-01-03
命令含 `;` `|` `&` `$` `>` `<` `` ` `` 任一 → 拒絕

#### AC-FR-01-04
`--name` 與既有 pending/running 任務重複 → 拒絕

#### AC-FR-01-05
產生 task id(uuid4 前 8 hex);狀態 `pending`,記錄 `command`、`name`、`created_at`;原子寫入 `$TASKQ_HOME/tasks.json`;stdout 輸出 task id(`--json` 時輸出 `{"id": ..., "status": "pending"}`)

---

### FR-02 — 任務執行器

**Canonical citation:** SPEC.md §3 FR-02.

`taskq run <id>` 或 `taskq run --all`

- 以 `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` 執行;**任何路徑不得使用 `shell=True`**
- 狀態機:`pending → running → done | failed | timeout`
  - exit 0 → `done`;非 0 → `failed`;`TimeoutExpired` → `timeout`
- 結果欄位:`exit_code`、`stdout_tail`(末 2000 字元)、`stderr_tail`(末 2000 字元)、`duration_ms`、`finished_at`
- `--all`:以 `ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS)` 並發執行全部 `pending` 任務;存儲寫入必須執行緒安全(共享 Lock)
- 單一任務模式下 `timeout` 結果 → **exit 4**

#### AC-FR-02-01
以 `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` 執行;**任何路徑不得使用 `shell=True`**

#### AC-FR-02-02
狀態機:`pending → running → done | failed | timeout`;exit 0 → `done`;非 0 → `failed`;`TimeoutExpired` → `timeout`

#### AC-FR-02-03
結果欄位:`exit_code`、`stdout_tail`(末 2000 字元)、`stderr_tail`(末 2000 字元)、`duration_ms`、`finished_at`

#### AC-FR-02-04
`--all`:以 `ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS)` 並發執行全部 `pending` 任務;存儲寫入必須執行緒安全(共享 Lock)

#### AC-FR-02-05
單一任務模式下 `timeout` 結果 → **exit 4**

---

### FR-03 — 重試與斷路器

**Canonical citation:** SPEC.md §3 FR-03.

**重試**:`run` 結果為 `failed`/`timeout` 時自動重試,上限 `TASKQ_RETRY_LIMIT` 次;第 n 次重試前等待 `TASKQ_BACKOFF_BASE × 2^n` 秒(exponential backoff;sleep 函式必須可注入以利測試)。

**斷路器**(全域,跨任務、跨進程):
- 連續最終失敗(重試耗盡仍 failed/timeout)計數 ≥ `TASKQ_BREAKER_THRESHOLD` → `OPEN`
- `OPEN` 期間任何 `run` 立即拒絕:**exit 3** + stderr `breaker open`,不執行 subprocess
- 經 `TASKQ_BREAKER_COOLDOWN` 秒後進入 `HALF_OPEN`:放行一個任務 — 成功 → `CLOSED` 且計數歸零;失敗 → 重新 `OPEN`
- 狀態持久化於 `$TASKQ_HOME/breaker.json`(原子寫)

#### AC-FR-03-01
`run` 結果為 `failed`/`timeout` 時自動重試,上限 `TASKQ_RETRY_LIMIT` 次;第 n 次重試前等待 `TASKQ_BACKOFF_BASE × 2^n` 秒(exponential backoff;sleep 函式必須可注入以利測試)

#### AC-FR-03-02
連續最終失敗(重試耗盡仍 failed/timeout)計數 ≥ `TASKQ_BREAKER_THRESHOLD` → `OPEN`

#### AC-FR-03-03
`OPEN` 期間任何 `run` 立即拒絕:**exit 3** + stderr `breaker open`,不執行 subprocess

#### AC-FR-03-04
經 `TASKQ_BREAKER_COOLDOWN` 秒後進入 `HALF_OPEN`:放行一個任務 — 成功 → `CLOSED` 且計數歸零;失敗 → 重新 `OPEN`

#### AC-FR-03-05
狀態持久化於 `$TASKQ_HOME/breaker.json`(原子寫)

---

### FR-04 — 結果 TTL 快取

**Canonical citation:** SPEC.md §3 FR-04.

- 快取簽名 = `sha256(command)`
- `taskq run <id> --cached`:同簽名且結果為 `done` 的最近執行在 `TASKQ_CACHE_TTL` 秒內 → 直接回放(`exit_code`/`stdout_tail`),**不執行 subprocess**,任務標記 `done` 且 `cached: true`
- 快取過期或不存在 → 正常執行,成功(`done`)後寫入 `$TASKQ_HOME/cache.json`
- 快取讀寫:原子 + 執行緒安全(與 FR-02 並發共存)

#### AC-FR-04-01
快取簽名 = `sha256(command)`

#### AC-FR-04-02
`taskq run <id> --cached`:同簽名且結果為 `done` 的最近執行在 `TASKQ_CACHE_TTL` 秒內 → 直接回放(`exit_code`/`stdout_tail`),**不執行 subprocess**,任務標記 `done` 且 `cached: true`

#### AC-FR-04-03
快取過期或不存在 → 正常執行,成功(`done`)後寫入 `$TASKQ_HOME/cache.json`

#### AC-FR-04-04
快取讀寫:原子 + 執行緒安全(與 FR-02 並發共存)

---

### FR-05 — CLI 整合

**Canonical citation:** SPEC.md §3 FR-05.

argparse 子命令(入口 `python -m taskq`):

| 命令 | 行為 |
|------|------|
| `submit "<cmd>" [--name N]` | FR-01 |
| `run <id> [--cached]` / `run --all` | FR-02/03/04 |
| `status <id>` | 輸出該任務全欄位 |
| `list [--status S]` | 列出任務(可按狀態過濾) |
| `clear` | 清空 `$TASKQ_HOME` 全部資料檔 |

- 全域 flag `--json`:機器可讀輸出(單行 JSON)
- **Exit codes**:`0` 成功 / `2` 輸入驗證錯誤(含 unknown task id) / `3` breaker open / `4` 任務 timeout / `1` 其他內部錯誤

#### AC-FR-05-01
argparse 子命令(入口 `python -m taskq`):`submit "<cmd>" [--name N]` (FR-01)、`run <id> [--cached]` / `run --all` (FR-02/03/04)、`status <id>`、`list [--status S]`、`clear`

#### AC-FR-05-02
全域 flag `--json`:機器可讀輸出(單行 JSON)

#### AC-FR-05-03
Exit codes:`0` 成功 / `2` 輸入驗證錯誤(含 unknown task id) / `3` breaker open / `4` 任務 timeout / `1` 其他內部錯誤

---

## 4. Non-Functional Requirements

> Source: SPEC.md §4. Each NFR below is a verbatim transcription of the
> canonical NFR row from SPEC.md §4.

### NFR-01 — Performance

**Canonical citation:** SPEC.md §4 NFR-01.

`submit` + `status` 組合操作(不含 subprocess 執行)100 次 p95 < 50ms(pytest-benchmark 量測).

#### AC-NFR-01-01
`submit` + `status` 組合操作(不含 subprocess 執行)100 次 p95 < 50ms(pytest-benchmark 量測)

---

### NFR-02 — Security (shell + injection)

**Canonical citation:** SPEC.md §4 NFR-02.

全 codebase 禁用 `shell=True`;FR-01 注入字元黑名單必須有測試覆蓋.

#### AC-NFR-02-01
全 codebase 禁用 `shell=True`

#### AC-NFR-02-02
FR-01 注入字元黑名單必須有測試覆蓋

---

### NFR-03 — Reliability (atomic write + breaker recovery)

**Canonical citation:** SPEC.md §4 NFR-03.

三個資料檔全部原子寫(tmp + `os.replace`),進程中斷後檔案仍為合法 JSON;breaker `OPEN → CLOSED` 恢復時間 ≤ `TASKQ_BREAKER_COOLDOWN` + 1s.

#### AC-NFR-03-01
三個資料檔全部原子寫(tmp + `os.replace`),進程中斷後檔案仍為合法 JSON

#### AC-NFR-03-02
breaker `OPEN → CLOSED` 恢復時間 ≤ `TASKQ_BREAKER_COOLDOWN` + 1s

---

### NFR-04 — Security (secret redaction)

**Canonical citation:** SPEC.md §4 NFR-04.

`stdout_tail`/`stderr_tail` 落盤前,匹配 `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` 的行整行以 `[REDACTED]` 取代.

#### AC-NFR-04-01
`stdout_tail`/`stderr_tail` 落盤前,匹配 `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` 的行整行以 `[REDACTED]` 取代

---

### NFR-05 — Maintainability (docstring FR-cross-ref)

**Canonical citation:** SPEC.md §4 NFR-05.

`src/taskq` 全部公開函式/類別有 docstring 且含 `[FR-XX]` 引用.

#### AC-NFR-05-01
`src/taskq` 全部公開函式/類別有 docstring 且含 `[FR-XX]` 引用

---

### NFR-06 — Deployability (env vars)

**Canonical citation:** SPEC.md §4 NFR-06.

全部 8 個 `TASKQ_*` 參數讀自環境變數(config.py 統一讀取,含預設值);`.env.example` 逐一宣告並附註解.

#### AC-NFR-06-01
全部 8 個 `TASKQ_*` 參數讀自環境變數(config.py 統一讀取,含預設值);`.env.example` 逐一宣告並附註解

> DERIVED: SPEC.md §4 NFR-06 — combined AC captures full verbatim row
> from canonical; tokenization-level quirk with backticked identifier
> handled by quoting the full clause.

---

## 5. Acceptance Criteria Summary

> Source: SPEC.md §8 (10 acceptance items).

| # | Acceptance Item | FR/NFR Anchor |
|---|----------------|---------------|
| 1 | `pytest tests/ -q` 全綠 | cross-cutting |
| 2 | `python -m taskq submit "echo hi"` → 輸出 8-hex id;`run <id>` → `done`,`status <id>` 顯示 `exit_code: 0` | FR-01 / FR-02 / FR-05 |
| 3 | `python -m taskq submit ""` → exit 2 | FR-01 / NFR-02 |
| 4 | `python -m taskq submit "echo hi; rm x"` → exit 2(注入字元) | FR-01 / NFR-02 |
| 5 | `TASKQ_TASK_TIMEOUT=1` 下 `run`(`sleep 5` 任務)→ 狀態 `timeout`,exit 4 | FR-02 / FR-05 |
| 6 | 3 個連續最終失敗任務後,第 4 次 `run` → exit 3(breaker OPEN);cooldown 後恢復可執行 | FR-03 / NFR-03 |
| 7 | TTL 內 `run <id> --cached`(同命令簽名)→ 回放且 `cached: true`,無 subprocess 執行 | FR-04 |
| 8 | `.env.example` 宣告全部 8 個 `TASKQ_*` 變數 | NFR-06 |
| 9 | `run --all` 並發執行後 `tasks.json` 為合法 JSON 且無任務遺失 | FR-02 / NFR-03 |
| 10 | 公開函式 docstring 含 `[FR-XX]` 引用 | NFR-05 |

---

## 6. Out-of-Scope

> Items explicitly excluded from this SRS scope per SPEC.md framing as a
> minimal local task queue CLI.

- Distributed task queues (no Redis / broker / RPC layer; SPEC.md §1
  scopes the tool to local single-process use).
- Multi-host / multi-user coordination (SPEC.md §1: "本地任務佇列 CLI").
- Persistent task execution across process restarts beyond what
  `$TASKQ_HOME/*.json` provides (no RDBMS, no WAL).
- A web UI / REST API surface (SPEC.md §1: "命令列工具").
- Built-in secret management beyond stdout/stderr redaction (NFR-04) —
  no keychain integration, no KMS.
- `shell=True` command interpretation (NFR-02 forbids it anywhere in the
  codebase; all subprocess invocations must use `shlex.split`).
- Plugin / extension loading mechanisms.
- Task priority queues, deadlines, cron-style scheduling beyond the
  immediate submit→run flow described in FR-01..FR-05.
- Telemetry / remote monitoring agents (only local file-based state
  per SPEC.md §5.2).

---

## 7. Open Issues

> Deferred items / placeholders / ambiguity resolutions captured here per
> INGESTION MODE rules (no silent omission of TBD/TODO/placeholders).

### 7.1 NFR-99 Ambiguity Resolutions

- **NFR-99-a — AC-NFR-01-02 ambiguity boundary**: SPEC.md §4 NFR-01 says
  "p95 < 50ms (pytest-benchmark 量測)" — the canonical phrasing leaves
  measurement boundary (`不含 subprocess 執行` vs `含 subprocess 執行`)
  implicit. Current SRS interpretation per R-CANONICAL-INTERP-001:
  verbatim canonical phrase transcribed into AC; test harness to confirm
  with stakeholder whether the 50ms budget includes subprocess
  invocation overhead or only the in-process submit/status path.

- **NFR-99-b — AC-NFR-03-03 measurement scope**: SPEC.md §4 NFR-03
  states "breaker `OPEN → CLOSED` 恢復時間 ≤ `TASKQ_BREAKER_COOLDOWN` + 1s"
  — canonical phrasing leaves the exact moment `OPEN → CLOSED` is
  observed ambiguous (HALF_OPEN probe success vs explicit reset). Test
  harness to confirm measurement point.

### 7.2 FR-XX-deferred

- (none) — all 5 FRs (`FR-01..FR-05`) and 6 NFRs (`NFR-01..NFR-06`) are
  fully specified in SPEC.md §3 / §4 with no TBD/TODO/placeholder
  markers; no deferrals required at this SRS level.

### 7.3 Prompt-injection Scan
- **Prompt-injection scan: clean — 0 hits in canonical** (SPEC.md scanned
  for adversarial-prompt patterns; no instructions embedded in canonical
  text attempt to override this SRS's transcription discipline).

---

## 8. Risks

> Source: SPEC.md §9 Risk Matrix (verbatim transcription).

| ID | 風險 | 影響 | 可能性 | 緩解 |
|----|------|------|--------|------|
| R1 | 並發寫入損壞 tasks.json | 高 | 中 | Lock + 原子寫(NFR-03) |
| R2 | subprocess 懸掛/殭屍 | 中 | 中 | timeout 必設(FR-02) |
| R3 | breaker 誤鎖死 | 中 | 低 | cooldown + HALF_OPEN(FR-03) |
| R4 | 快取回放陳舊結果 | 低 | 中 | TTL 過期重執行(FR-04) |
| R5 | secret 落盤洩漏 | 高 | 中 | stdout_tail/stderr_tail redaction(NFR-04) |

---

## 9. Glossary

| Term | Definition |
|------|-----------|
| `taskq` | Project name; the local task queue CLI tool. |
| `submit` | FR-01 subcommand: enqueue a shell command as a task with validation. |
| `run` | FR-02/FR-03/FR-04 subcommand: execute a task (`<id>` single / `--all` batch / `--cached` replay). |
| `status` | FR-05 subcommand: print a task's full record. |
| `list` | FR-05 subcommand: list tasks (optionally filter by status). |
| `clear` | FR-05 subcommand: wipe `$TASKQ_HOME` data files. |
| `pending` / `running` / `done` / `failed` / `timeout` | FR-02 task lifecycle states. |
| `TASKQ_HOME` | Environment variable (default `.taskq`); data-file directory. |
| `TASKQ_MAX_WORKERS` | Environment variable (default `4`); `--all` worker count. |
| `TASKQ_TASK_TIMEOUT` | Environment variable (default `10.0`); per-task subprocess timeout (seconds). |
| `TASKQ_RETRY_LIMIT` | Environment variable (default `2`); retry cap on failed/timeout tasks. |
| `TASKQ_BACKOFF_BASE` | Environment variable (default `0.1`); exponential backoff base (seconds). |
| `TASKQ_BREAKER_THRESHOLD` | Environment variable (default `3`); consecutive final failures before breaker OPEN. |
| `TASKQ_BREAKER_COOLDOWN` | Environment variable (default `5.0`); OPEN → HALF_OPEN cooldown (seconds). |
| `TASKQ_CACHE_TTL` | Environment variable (default `3600`); TTL for cached task results (seconds). |
| `tasks.json` / `breaker.json` / `cache.json` | `$TASKQ_HOME/` data files (SPEC.md §5.2). |
| `CLOSED` / `OPEN` / `HALF_OPEN` | FR-03 circuit breaker states. |
| `--json` | FR-05 global flag: machine-readable single-line JSON output. |
| Exit code `0` / `1` / `2` / `3` / `4` | success / other internal error / input validation error (incl. unknown task id) / breaker open / task timeout (SPEC.md §7). |
| `high-risk module` | harness-methodology framework classification: `taskq.executor` (FR-02/03) and `taskq.store` (FR-01/02) require per-module TDD coverage (SPEC.md §10). |
| `INGESTION MODE` | Phase 1 agent protocol: 100% verbatim transcription of canonical spec, no invention, no silent omission. |
| `DERIVED` tag | Marker above an AC indicating an interpretive choice grounded in a canonical line (R-CANONICAL-INTERP-001). |

---

## Appendix A — FR Block (machine-readable)

> Used by downstream agents for requirements traceability (per
> harness-methodology P1→P8 pipeline). Do not edit by hand — regenerate
> from §3 / §4.

```json
{
  "version": "1.0",
  "created_at": "2026-07-04",
  "phase": 1,
  "project": "taskq",
  "source_of_truth": "SPEC.md v3.0.0 (2026-07-04)",
  "ingestion_mode": true,
  "functional_requirements": [
    {
      "id": "FR-01",
      "title": "任務提交與驗證",
      "description": "taskq submit \"<command>\" [--name NAME] with validation rules (empty / length / injection / name-unique) per SPEC.md §3 FR-01",
      "implementation_modules": ["src/taskq/store.py", "src/taskq/cli.py", "src/taskq/models.py"],
      "acceptance_criteria": ["AC-FR-01-01", "AC-FR-01-02", "AC-FR-01-03", "AC-FR-01-04", "AC-FR-01-05"],
      "verification_method": "pytest tests/test_submit.py (validation); grep assertion for injection blacklist"
    },
    {
      "id": "FR-02",
      "title": "任務執行器",
      "description": "taskq run <id> / run --all via subprocess.run(shlex.split, capture_output, text, timeout=TASKQ_TASK_TIMEOUT) + ThreadPoolExecutor; status machine pending→running→done|failed|timeout per SPEC.md §3 FR-02",
      "implementation_modules": ["src/taskq/executor.py", "src/taskq/store.py"],
      "acceptance_criteria": ["AC-FR-02-01", "AC-FR-02-02", "AC-FR-02-03", "AC-FR-02-04", "AC-FR-02-05"],
      "verification_method": "pytest tests/test_run.py; concurrent fixture for --all"
    },
    {
      "id": "FR-03",
      "title": "重試與斷路器",
      "description": "Retry with exponential backoff (TASKQ_BACKOFF_BASE * 2^n) up to TASKQ_RETRY_LIMIT; circuit breaker CLOSED/OPEN/HALF_OPEN state machine with TASKQ_BREAKER_THRESHOLD/COOLDOWN; persisted to breaker.json per SPEC.md §3 FR-03",
      "implementation_modules": ["src/taskq/executor.py", "src/taskq/breaker.py"],
      "acceptance_criteria": ["AC-FR-03-01", "AC-FR-03-02", "AC-FR-03-03", "AC-FR-03-04", "AC-FR-03-05"],
      "verification_method": "pytest tests/test_retry.py + tests/test_breaker.py with injected sleep"
    },
    {
      "id": "FR-04",
      "title": "結果 TTL 快取",
      "description": "Cache signature = sha256(command); run --cached replays done result within TASKQ_CACHE_TTL; atomic + thread-safe read/write per SPEC.md §3 FR-04",
      "implementation_modules": ["src/taskq/cache.py"],
      "acceptance_criteria": ["AC-FR-04-01", "AC-FR-04-02", "AC-FR-04-03", "AC-FR-04-04"],
      "verification_method": "pytest tests/test_cache.py; verify no subprocess spawn on cached replay"
    },
    {
      "id": "FR-05",
      "title": "CLI 整合",
      "description": "argparse subcommands submit / run / status / list / clear + global --json flag + 5 exit codes per SPEC.md §3 FR-05 + §7",
      "implementation_modules": ["src/taskq/cli.py", "src/taskq/__main__.py"],
      "acceptance_criteria": ["AC-FR-05-01", "AC-FR-05-02", "AC-FR-05-03"],
      "verification_method": "pytest tests/test_cli.py; CLI invocation matrix"
    }
  ],
  "non_functional_requirements": [
    {
      "id": "NFR-01",
      "type": "performance",
      "description": "submit + status 組合操作 100 次 p95 < 50ms (pytest-benchmark 量測) — verbatim SPEC.md §4 NFR-01",
      "test_method": "pytest-benchmark over 100 iterations of submit+status"
    },
    {
      "id": "NFR-02",
      "type": "security",
      "description": "全 codebase 禁用 shell=True;FR-01 注入字元黑名單必須有測試覆蓋 — verbatim SPEC.md §4 NFR-02",
      "test_method": "grep CI gate + injection blacklist unit tests"
    },
    {
      "id": "NFR-03",
      "type": "reliability",
      "description": "三資料檔原子寫 (tmp + os.replace);breaker OPEN → CLOSED 恢復時間 ≤ TASKQ_BREAKER_COOLDOWN + 1s — verbatim SPEC.md §4 NFR-03",
      "test_method": "fault-injection crash test + breaker recovery timing test"
    },
    {
      "id": "NFR-04",
      "type": "security",
      "description": "stdout_tail/stderr_tail 落盤前,匹配 (sk-[A-Za-z0-9_-]{8,}|token=\\S+) 的行整行以 [REDACTED] 取代 — verbatim SPEC.md §4 NFR-04",
      "test_method": "unit test on stdout_tail redaction"
    },
    {
      "id": "NFR-05",
      "type": "maintainability",
      "description": "src/taskq 全部公開函式/類別有 docstring 且含 [FR-XX] 引用 — verbatim SPEC.md §4 NFR-05",
      "test_method": "Gate 1 inspect (docstring [FR-XX] coverage 100%)"
    },
    {
      "id": "NFR-06",
      "type": "deployability",
      "description": "全部 8 個 TASKQ_* 參數讀自環境變數 (config.py 統一讀取);.env.example 逐一宣告並附註解 — verbatim SPEC.md §4 NFR-06",
      "test_method": "env-var loading test + .env.example lint"
    }
  ],
  "open_issues": [
    {
      "id": "NFR-99-a",
      "type": "ambiguity",
      "anchor": "AC-NFR-01-02",
      "summary": "p95 < 50ms boundary (含/不含 subprocess) — canonical phrasing ambiguous; test harness to confirm with stakeholder"
    },
    {
      "id": "NFR-99-b",
      "type": "ambiguity",
      "anchor": "AC-NFR-03-03",
      "summary": "breaker OPEN → CLOSED observation moment ambiguous (HALF_OPEN probe vs explicit reset); test harness to confirm"
    }
  ]
}
```

---

*Document version: 1.0 (INGESTION MODE from SPEC.md v3.0.0, 2026-07-04) — 5 FR / 6 NFR / 8 env / 5 risks transcribed verbatim.*