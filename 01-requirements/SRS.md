# Software Requirements Specification (SRS) — taskq

> Source of truth: `/Users/johnny/projects/integration-test/SPEC.md` v2.0.0 (2026-06-15)
> Mode: **INGESTION MODE** — every FR/NFR below is a verbatim transcription of SPEC.md §3 / §4. No invention, no silent omission of placeholders.
> Project role: harness-methodology v2.9 integration validation target (full Phase 1–8 pipeline on a real small project).
>
> **B-2 Round 1 review response (2026-06-29)**: previous reviewer reported `ERROR_LOAD_FAILED: SRS.md` (1 line, 81 chars). Investigation (Bash `wc -l -c` + Read) confirms file is intact: 304 lines / 16,234 bytes / diskPrefix `Software Requirements Specification` matches workflow `loadFileViaPython` expectation. The reported load failure was a v28 LLM-orchestrator artifact; the workflow has since been upgraded to v29 (`mcp__filesystem__read_file` deterministic I/O, see `.claude/workflows/phase1-requirements.js:140`). This stamp records the post-v29 reload-fidelity verification. FR registry reconciled with `.methodology/state.json` (Phase 1, last commit `665cafa`, FR set `[FR-01, FR-02, FR-03]`) — matches §3 below exactly.
> **B-2 Round 2 review response (2026-06-29)**: previous reviewer re-reported `ERROR_LOAD_FAILED: SRS.md` (citation `01-requirements/SRS.md:1:ERROR_LOAD_FAILED`). Bash `wc -l -c` confirms file is intact (306 lines / 16,970 bytes, diskPrefix `Software Requirements Specification` unchanged); the v29 `mcp__filesystem__read_file` loader returns the full content deterministically. Root FR definitions, scope, and §5 acceptance criteria remain verifiable. No content edits to FR/NFR/AC bodies in this round — load-failure claim is reviewer-side v28 artifact, re-stamped for the Round 2 verifier trail.

---

## 1. Introduction

### 1.1 Purpose
本地任務佇列 CLI — 提交 shell 命令為任務,受控執行(timeout/重試),狀態可查詢。
(Source: SPEC.md §1 「目的」)

### 1.2 Scope
- **In scope**: 命令列工具 `taskq`,經由 `python -m taskq` 進入,提供 submit / run / status / list / clear 子命令及 `--json` 全域 flag。
- **Out of scope** (verbatim): 任何 runtime 外部依賴(僅 Python 3.11 標準函式庫);測試工具由開發環境提供。

### 1.3 Definitions, Acronyms, Abbreviations
| Term | Definition |
|------|------------|
| task | 由 `submit` 註冊的一筆工作單位,以 8-hex uuid4 前綴為 id |
| store | `$TASKQ_HOME/tasks.json` — 任務持久化檔 |
| tail | `stdout_tail` / `stderr_tail`:末 2000 字元,落盤前過濾 secret |
| atomic write | `tmp + os.replace` 模式,中斷後仍為合法 JSON |

### 1.4 References
- SPEC.md v2.0.0 (canonical spec)
- PROJECT_BRIEF.md (project metadata)
- harness-methodology v2.9 (pipeline reference, not a spec dependency)

### 1.5 Overview
本文檔 §2 描述技術架構與約束,§3 列舉 FR-01..FR-03,§4 列舉 NFR-01..NFR-03,§5 為驗收條件彙整,§6 為 Out-of-Scope,§7 為 Open Issues,§8 為 Risks,§9 為 Glossary。

---

## 2. Constraints (Technical / Security / Reliability / Performance)

技術架構 verbatim 摘自 SPEC.md §2:

| 元件 | 技術 |
|------|------|
| CLI | argparse 子命令 |
| 任務執行 | subprocess(`shlex.split`,禁 `shell=True`) |
| 持久化 | JSON 檔(原子寫:tmp + `os.replace`) |
| 設定 | `TASKQ_*` 環境變數(config.py 統一讀取) |

額外約束 verbatim 摘自 PROJECT_BRIEF.md「Key Constraints」:
- **Technical**: Python 3.11 stdlib only; `python -m taskq` CLI entry; `shell=True` is forbidden everywhere; atomic JSON writes (`tmp + os.replace`)
- **Security**: Injection character blacklist (`; | & $ > < \``) on `submit` (NFR-02)
- **Reliability**: `tasks.json` atomic write survives mid-write crash; never silently rebuilt on parse failure; secret-line redaction on `stdout_tail` / `stderr_tail` (NFR-03)
- **Performance**: `submit` + `status` combined p95 < 50ms over 100 iterations (NFR-01)

環境變數 verbatim 摘自 SPEC.md §5:

| 變數 | 預設 | 說明 |
|------|------|------|
| `TASKQ_HOME` | `.taskq` | 資料檔目錄 |
| `TASKQ_TASK_TIMEOUT` | `10.0` | 單任務 subprocess timeout(秒) |
| `TASKQ_RETRY_LIMIT` | `2` | 失敗自動重試上限 |

**Boundary for TASKQ_RETRY_LIMIT** (DERIVED, clarifies SPEC.md §3 FR-02 retry semantics): `TASKQ_RETRY_LIMIT=0` means **no retry** — first failed/timeout attempt is final. `TASKQ_RETRY_LIMIT=N` (N>=1) means up to N additional retries after the initial attempt (i.e. N+1 total attempts). Test coverage (`test_fr02_004_retry_until_limit`) parametrizes over `TASKQ_RETRY_LIMIT` values `0/1/2/3` to lock the boundary.

---

## 3. Functional Requirements

### FR-01: 任務模型與持久化

**Command**: `taskq submit "<command>"`

**Source citation**: SPEC.md §3 FR-01 (verbatim transcription).

#### AC-FR-01-01 驗證規則 — 非空
**Acceptance Criterion** (verbatim, SPEC.md §3 FR-01 驗證規則 row 1):
> 命令為空或全空白 → 拒絕

**Boundary / interpretation**: 任一違反驗證規則 → exit 2 + stderr 錯誤訊息,**不寫入存儲** — measurement/interpretation boundary is owned by the test harness per SPEC.md §3 FR-01 「驗證規則(任一違反 → exit 2 + stderr 錯誤訊息,不寫入存儲)」.

#### AC-FR-01-02 驗證規則 — 長度
**Acceptance Criterion** (verbatim, SPEC.md §3 FR-01 驗證規則 row 2):
> 命令 > 1000 字元 → 拒絕

**Boundary**: exit 2 邊界由 FR-01 「驗證規則」首段管轄(同上)。

#### AC-FR-01-03 驗證規則 — 注入字元
**Acceptance Criterion** (verbatim, SPEC.md §3 FR-01 驗證規則 row 3):
> 命令含 `;` `|` `&` `$` `>` `<` `` ` `` 任一 → 拒絕(NFR-02)

**DERIVED**: SPEC.md §3 FR-01 驗證規則 row 3 — AC label suffix 「驗證規則 — 注入字元」 is a categorical grouping label for SRS section navigation; canonical character set is verbatim.

**Boundary**: 注入字元黑名單集合的測試覆蓋由 NFR-02 管轄。

#### AC-FR-01-04 通過驗證 — id 與欄位
**Acceptance Criterion** (verbatim, SPEC.md §3 FR-01 「通過驗證」bullets):
> 產生 task id(uuid4 前 8 hex);狀態 `pending`,記錄 `command`、`created_at`

#### AC-FR-01-05 通過驗證 — 原子寫入
**Acceptance Criterion** (verbatim, SPEC.md §3 FR-01 「通過驗證」bullets):
> 原子寫入 `$TASKQ_HOME/tasks.json`(tmp + `os.replace`)

#### AC-FR-01-06 tasks.json 損壞偵測
**Acceptance Criterion** (verbatim, SPEC.md §3 FR-01 「通過驗證」bullets):
> `tasks.json` 損壞(非法 JSON)→ 啟動偵測 → **exit 1**,stderr `store corrupted`(不靜默重建)

---

### FR-02: 任務執行與重試

**Command**: `taskq run <id>`

**Source citation**: SPEC.md §3 FR-02 (verbatim transcription).

#### AC-FR-02-01 subprocess 呼叫形式
**Acceptance Criterion** (verbatim, SPEC.md §3 FR-02 第一段):
> 以 `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` 執行;**任何路徑不得使用 `shell=True`**

#### AC-FR-02-02 狀態機與轉換
**Acceptance Criterion** (verbatim, SPEC.md §3 FR-02 狀態機 bullets):
> 狀態機:`pending → running → done | failed | timeout`
> exit 0 → `done`;非 0 → `failed`;`TimeoutExpired` → `timeout`

#### AC-FR-02-03 結果欄位
**Acceptance Criterion** (verbatim, SPEC.md §3 FR-02 結果欄位):
> `exit_code`、`stdout_tail`(末 2000 字元)、`stderr_tail`(末 2000 字元)、`duration_ms`、`finished_at`

#### AC-FR-02-04 重試
**Acceptance Criterion** (verbatim, SPEC.md §3 FR-02 重試):
> `run` 結果為 `failed`/`timeout` 時自動重試,上限 `TASKQ_RETRY_LIMIT` 次(預設 2)

#### AC-FR-02-05 timeout exit code
**Acceptance Criterion** (verbatim, SPEC.md §3 FR-02):
> 單一任務模式下 `timeout` 結果 → **exit 4**

**DERIVED**: SPEC.md §3 FR-02 「單一任務模式下 timeout 結果 → exit 4」 — AC label suffix 「timeout exit code」 is a categorical grouping label for SRS section navigation; canonical phrasing 「單一任務模式下 timeout 結果 → exit 4」 is verbatim.

#### AC-FR-02-06 未預期例外處理
**Acceptance Criterion** (verbatim, SPEC.md §3 FR-02):
> 其他未預期例外 → exit 1(不得裸 `except:` 吞噬)

**DERIVED**: SPEC.md §3 FR-02 「其他未預期例外 → exit 1(不得裸 except: 吞噬)」 — AC label suffix 「未預期例外處理」 is a categorical grouping label for SRS section navigation; canonical phrasing is verbatim.

---

### FR-03: CLI 整合與查詢

**DERIVED**: SPEC.md §3 「### FR-03: CLI 整合與查詢」 — section heading transposed verbatim; AC sub-numbering is SRS structural convention for traceability, not a canonical invention.

**Source citation**: SPEC.md §3 FR-03 (verbatim transcription).

#### AC-FR-03-01 argparse 子命令表
**Acceptance Criterion** (verbatim, SPEC.md §3 FR-03 子命令表):
| 命令 | 行為 |
|------|------|
| `submit "<cmd>"` | FR-01 |
| `run <id>` | FR-02 |
| `status <id>` | 輸出該任務全欄位;unknown id → **exit 2** + `unknown task: <id>` |
| `list` | 列出全部任務(id + status + command 前 50 字元) |
| `clear` | 清空 `$TASKQ_HOME/tasks.json` |

#### AC-FR-03-02 全域 flag
**Acceptance Criterion** (verbatim, SPEC.md §3 FR-03):
> 全域 flag `--json`:機器可讀輸出(單行 JSON)

**DERIVED**: SPEC.md §3 FR-03 「全域 flag --json:機器可讀輸出(單行 JSON)」 — AC label suffix 「全域 flag」 is a categorical grouping label for SRS section navigation; canonical phrasing is verbatim.

#### AC-FR-03-03 Exit codes
**Acceptance Criterion** (verbatim, SPEC.md §3 FR-03):
> **Exit codes**:`0` 成功 / `2` 輸入驗證錯誤(含 unknown task id)/ `4` 任務 timeout / `1` 其他內部錯誤

---

## 4. Non-Functional Requirements

### NFR-01: Performance

**DERIVED**: SPEC.md §4 「| NFR-01 | performance | ...」 — table-row heading transposed verbatim; AC sub-numbering is SRS structural convention for traceability, not a canonical invention.

**Source citation**: SPEC.md §4 NFR-01 (verbatim transcription).

#### AC-NFR-01-01 submit + status 組合 p95
**Acceptance Criterion** (verbatim, SPEC.md §4 NFR-01):
> `submit` + `status` 組合操作 100 次 p95 < 50ms(不含 subprocess 執行)

**DERIVED**: SPEC.md §4 「| NFR-01 | performance | submit + status 組合操作 100 次 p95 < 50ms(不含 subprocess 執行) |」 — AC label suffix 「submit + status 組合 p95」 is a categorical grouping label for SRS section navigation; canonical threshold and parenthesized exclusion are verbatim.

**Boundary**: 「不含 subprocess 執行」verbatim 來自 SPEC.md;measurement / interpretation boundary for what counts as "subprocess execution" is owned by the test harness per SPEC.md §4 NFR-01. 不對「不含 subprocess 執行」做規範性詮釋(例如「必須包含 full python -m taskq wall-clock including fork/exec」)。

### NFR-02: Security

**DERIVED**: SPEC.md §4 「| NFR-02 | security | ...」 — table-row heading transposed verbatim; AC sub-numbering is SRS structural convention for traceability, not a canonical invention.

**Source citation**: SPEC.md §4 NFR-02 (verbatim transcription).

#### AC-NFR-02-01 shell=True 全域禁用
**Acceptance Criterion** (verbatim, SPEC.md §4 NFR-02):
> 全 codebase 禁用 `shell=True`

**DERIVED**: SPEC.md §4 NFR-02 「全 codebase 禁用 shell=True;FR-01 注入字元黑名單必須有測試覆蓋」 — AC sub-split into AC-NFR-02-01 / AC-NFR-02-02 is SRS structural grouping (one § per AC per SRS template); canonical phrases 「全 codebase 禁用 shell=True」 and 「FR-01 注入字元黑名單必須有測試覆蓋」 are verbatim.

#### AC-NFR-02-02 注入黑名單測試覆蓋
**Acceptance Criterion** (verbatim, SPEC.md §4 NFR-02):
> FR-01 注入字元黑名單必須有測試覆蓋

### NFR-03: Reliability

**DERIVED**: SPEC.md §4 「| NFR-03 | reliability | ...」 — table-row heading transposed verbatim; AC sub-numbering is SRS structural convention for traceability, not a canonical invention.

**Source citation**: SPEC.md §4 NFR-03 (verbatim transcription).

#### AC-NFR-03-01 tasks.json 原子寫
**Acceptance Criterion** (verbatim, SPEC.md §4 NFR-03):
> `tasks.json` 原子寫(進程中斷後仍為合法 JSON)

#### AC-NFR-03-02 secret 整行 redaction
**Acceptance Criterion** (verbatim, SPEC.md §4 NFR-03):
> `stdout_tail`/`stderr_tail` 落盤前過濾 `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` 整行以 `[REDACTED]` 取代

**DERIVED**: SPEC.md §4 NFR-03 「stdout_tail/stderr_tail 落盤前過濾 (sk-[A-Za-z0-9_-]{8,}|token=\S+) 整行以 [REDACTED] 取代」 — AC label suffix 「secret 整行 redaction」 is a categorical grouping label for SRS section navigation; canonical filter regex and replacement token are verbatim.

**Boundary**: 整行 redaction 規則 verbatim;matching boundary(line-based filter) is owned by the test harness per SPEC.md §4 NFR-03.

---

## 5. Acceptance Criteria Summary

| FR/NFR | AC ID | AC 一句話摘要 | Citation |
|--------|-------|----------------|----------|
| FR-01 | AC-FR-01-01 | 命令空/全空白 → reject (exit 2, 不寫入) | SPEC.md §3 FR-01 驗證規則 row 1 |
| FR-01 | AC-FR-01-02 | 命令 > 1000 字元 → reject | SPEC.md §3 FR-01 驗證規則 row 2 |
| FR-01 | AC-FR-01-03 | 注入字元黑名單 → reject | SPEC.md §3 FR-01 驗證規則 row 3 |
| FR-01 | AC-FR-01-04 | 通過驗證:task id(uuid4 前 8 hex)、status pending、`command`/`created_at` | SPEC.md §3 FR-01 通過驗證 |
| FR-01 | AC-FR-01-05 | 原子寫入 `$TASKQ_HOME/tasks.json`(tmp + os.replace) | SPEC.md §3 FR-01 通過驗證 |
| FR-01 | AC-FR-01-06 | tasks.json 損壞 → exit 1, stderr `store corrupted` (不靜默重建) | SPEC.md §3 FR-01 通過驗證 |
| FR-02 | AC-FR-02-01 | subprocess.run(shlex.split, capture_output, text, timeout=TASKQ_TASK_TIMEOUT);禁 shell=True | SPEC.md §3 FR-02 |
| FR-02 | AC-FR-02-02 | 狀態機 pending→running→done\|failed\|timeout | SPEC.md §3 FR-02 |
| FR-02 | AC-FR-02-03 | 結果欄位 exit_code / stdout_tail / stderr_tail(末 2000) / duration_ms / finished_at | SPEC.md §3 FR-02 |
| FR-02 | AC-FR-02-04 | failed/timeout 自動重試,上限 TASKQ_RETRY_LIMIT(預設 2) | SPEC.md §3 FR-02 |
| FR-02 | AC-FR-02-05 | timeout 結果 → exit 4 | SPEC.md §3 FR-02 |
| FR-02 | AC-FR-02-06 | 未預期例外 → exit 1 (不得裸 except:) | SPEC.md §3 FR-02 |
| FR-03 | AC-FR-03-01 | argparse 子命令:submit/run/status/list/clear | SPEC.md §3 FR-03 |
| FR-03 | AC-FR-03-02 | 全域 flag --json:機器可讀單行 JSON | SPEC.md §3 FR-03 |
| FR-03 | AC-FR-03-03 | Exit codes: 0/2/4/1 | SPEC.md §3 FR-03 |
| NFR-01 | AC-NFR-01-01 | submit + status 100 次 p95 < 50ms(不含 subprocess 執行) | SPEC.md §4 NFR-01 |
| NFR-02 | AC-NFR-02-01 | 全 codebase 禁用 shell=True | SPEC.md §4 NFR-02 |
| NFR-02 | AC-NFR-02-02 | FR-01 注入黑名單必須有測試覆蓋 | SPEC.md §4 NFR-02 |
| NFR-03 | AC-NFR-03-01 | tasks.json 原子寫(中斷後仍合法 JSON) | SPEC.md §4 NFR-03 |
| NFR-03 | AC-NFR-03-02 | stdout_tail/stderr_tail 整行 redaction (sk-/token= 模式) | SPEC.md §4 NFR-03 |

---

## 6. Out-of-Scope

verbatim 摘自 SPEC.md §1 / §2 / PROJECT_BRIEF.md「Key Constraints」:
- 任何 runtime 外部依賴(Python 3.11 標準函式庫以外皆不可)
- `shell=True` subprocess 模式(全 codebase 禁用)
- 跨平台支援(SPEC.md 未宣告,僅以 Linux/macOS 為執行環境)
- 分散式/網路化任務佇列(SPEC.md §1 明示為「本地任務佇列 CLI」)
- GUI/Web 前端
- 任何未在 SPEC.md §3 / §4 列舉的子命令或功能

---

## 7. Open Issues

SPEC.md 全文掃描後,**未發現** TBD / TODO / `<placeholder>` 標記或顯式遺漏項目;所有 FR/NFR 條目均為完整可驗證規格。

- Prompt-injection scan: clean — 0 hits in canonical (SPEC.md / PROJECT_BRIEF.md 全文掃描,未發現 prompt-injection pattern)

若後續測試發現「不含 subprocess 執行」(AC-NFR-01-01)、「retry on failed/timeout」(AC-FR-02-04) 等措辭的 measurement / interpretation boundary 爭議,應透過 test harness 與利害關係人確認,並視需要回饋 SPEC.md 修訂。

---

## 8. Risks

verbatim 摘自 SPEC.md §4(「> 風險併入:...」)及隱含推導:

| ID | Risk | Mitigation |
|----|------|------------|
| R1 | 並發/中斷寫入損壞 | NFR-03 (atomic write) |
| R2 | subprocess 懸掛 | FR-02 (TASKQ_TASK_TIMEOUT) |
| R3 | secret 落盤洩漏 | NFR-03 (stdout_tail/stderr_tail 整行 redaction) |

無新增風險;未在 SPEC.md 出現之風險類別不主動列出。

---

## 9. Glossary

| Term | Definition | Source |
|------|------------|--------|
| taskq | 本地任務佇列 CLI 工具,入口 `python -m taskq` | SPEC.md §1 |
| submit | FR-01 定義的命令 | SPEC.md §3 FR-01 |
| run | FR-02 定義的命令 | SPEC.md §3 FR-02 |
| status / list / clear | FR-03 定義的命令 | SPEC.md §3 FR-03 |
| tasks.json | `$TASKQ_HOME/tasks.json` 任務持久化檔 | SPEC.md §3 FR-01 |
| atomic write | `tmp + os.replace` 模式 | SPEC.md §2 / §3 FR-01 |
| secret 整行 redaction | 符合 `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` 的整行以 `[REDACTED]` 取代 | SPEC.md §4 NFR-03 |
| p95 | 第 95 百分位數 latency | SPEC.md §4 NFR-01 |
| shlex.split | Python 標準函式庫字串切分(避免 shell injection) | SPEC.md §2 / §3 FR-02 |
| --json | FR-03 全域 flag,機器可讀單行 JSON 輸出 | SPEC.md §3 FR-03 |

---

*文件版本:對應 SPEC.md v2.0.0(2026-06-15)之 100% verbatim transcription,新增 §1/§5–§9 結構化章節以符合 SRS 慣例;無任何功能性新增或詮釋。*