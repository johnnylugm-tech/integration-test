# Software Requirements Specification (SRS) — taskq

> **Source of truth**: `SPEC.md` v4.0.0 (2026-07-11), 5 FR / 10 NFR / 8 env vars.
> **Mode**: INGESTION MODE — 100% transcription of all `### FR-01..FR-05` and `### NFR-01..NFR-10` headings from `SPEC.md`.
> **Citation style**: `[SPEC §X.Y]` (or `[SPEC §X table]`).

---

## 1. Introduction

### 1.1 Purpose
`taskq` 是一個本地任務佇列 CLI — 提交 shell 命令為任務,受控執行(timeout / 重試 / 斷路器 / 快取),狀態可查詢 [SPEC §1].

### 1.2 Scope
命令列工具,`python -m taskq` 進入 [SPEC §1].

### 1.3 Language & Runtime
Python 3.11,**runtime 零外部依賴**(僅標準函式庫;測試工具由開發環境提供) [SPEC §1].

### 1.4 Definitions / Acronyms
| Term | Meaning |
|------|---------|
| task | 提交後寫入 `tasks.json` 的單位;具 id / status / command / result |
| pending / running / done / failed / timeout | 任務狀態機 [SPEC §3 FR-02] |
| breaker | 跨任務、跨進程的全域斷路器 [SPEC §3 FR-03] |
| TTL cache | sha256(command) 索引,`TASKQ_CACHE_TTL` 秒存活 [SPEC §3 FR-04] |
| fault injection | 透過 `--inject-fault=<scenario>` 觸發之損壞/失敗情境 [SPEC §5.3] |
| atomic write | tmp + `os.replace` 寫法 [SPEC §2 / §4 NFR-03] |

### 1.5 References
- `SPEC.md` v4.0.0(本專案單一事實來源)
- `PROJECT_BRIEF.md`(phase 1 規範與 FR/NFR 索引)
- `.env.example`(8 個 `TASKQ_*` 環境變數宣告)
- `harness/CLAUDE.md`(framework 對齊;§10 framework alignment 對應)

---

## 2. Constraints

### 2.1 Technical
- Python 3.11 stdlib only at runtime [SPEC §1 / PROJECT_BRIEF §"Key Constraints"]
- `python -m taskq` CLI entry [SPEC §1]
- `shell=True` is forbidden everywhere — NFR-02 [SPEC §3 FR-02 / §4 NFR-02]
- `ThreadPoolExecutor` for `run --all` with shared `threading.Lock` over store [SPEC §3 FR-02 / PROJECT_BRIEF §"Key Constraints"]

### 2.2 Atomicity
- All three data files (`tasks.json`, `breaker.json`, `cache.json`) written via tmp + `os.replace`; mid-write crash must leave valid JSON — NFR-03 [SPEC §2 / §4 NFR-03]

### 2.3 Security
- Injection character blacklist (`; | & $ > < \``) on `submit` — NFR-02 [SPEC §3 FR-01 / §4 NFR-02]
- Secret-line redaction on `stdout_tail` / `stderr_tail` pattern `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` — NFR-04 [SPEC §4 NFR-04]

### 2.4 Reliability
- Circuit breaker opens at consecutive final-failure threshold and refuses until cooldown — FR-03 [SPEC §3 FR-03]
- `tasks.json` corruption is detected and surfaced (exit 1) rather than silently rebuilt — NFR-03, FR-03 [SPEC §4 NFR-03 / §7]

### 2.5 Performance
- `submit` + `status` combined p95 < 50ms over 100 iterations — NFR-01 [SPEC §4 NFR-01]

### 2.6 Architecture
- `no_circular_dependencies` among the 8 modules [SPEC §10 / PROJECT_BRIEF §"Key Constraints"]
- `taskq.executor` and `taskq.store` are framework-classified high-risk modules [SPEC §10 / PROJECT_BRIEF §"Key Constraints"]

### 2.7 Resilience
- Three data files must survive fault-injection scenarios (mid-write corruption / `OSError` / disk-full) — either recover from backup or fail-fast with explicit stderr + non-zero exit; never silently rebuild or swallow errors — NFR-07 [SPEC §4 NFR-07]

### 2.8 Concurrency
- Multiple `python -m taskq` processes operating on the same `$TASKQ_HOME` must not corrupt the three data files — NFR-08 [SPEC §4 NFR-08]
- `fcntl.flock` / `msvcrt.locking` as best-effort enhancement layered on top of NFR-03 atomic write — NFR-08 [SPEC §4 NFR-08]

### 2.9 Scalability
- 1000-task scale `submit` + `status` p95 < 100ms — NFR-09 [SPEC §4 NFR-09]
- `run --all` on 100 tasks leaves `tasks.json` valid with no task loss — NFR-09 [SPEC §4 NFR-09]
- Streaming iterator (no full load in memory) — NFR-09 [SPEC §4 NFR-09]

### 2.10 Evolvability
- Data files carry a `version` field at root [SPEC §5.2 / §4 NFR-10]
- Reading `version < 1` triggers automatic migration — NFR-10 [SPEC §4 NFR-10]
- Reading `version > 1` refuses with upgrade prompt — NFR-10 [SPEC §4 NFR-10]
- Pre-migration backup as `<file>.v<n>.bak` retained on failure — NFR-10 [SPEC §4 NFR-10]

---

## 3. Functional Requirements

### FR-01: 任務提交與驗證

`taskq submit "<command>" [--name NAME]` [SPEC §3 FR-01]

**Validation rules**(任一違反 → **exit 2** + stderr 錯誤訊息,不寫入存儲)[SPEC §3 FR-01]:

| Rule | 條件 |
|------|------|
| 非空 | 命令為空或全空白 → 拒絕 |
| 長度 | 命令 > 1000 字元 → 拒絕 |
| 注入字元 | 命令含 `;` `|` `&` `$` `>` `<` `` ` `` 任一 → 拒絕 (NFR-02) |
| 名稱唯一 | `--name` 與既有 pending/running 任務重複 → 拒絕 |

**Pass validation**:
- 產生 task id(uuid4 前 8 hex)
- 狀態 `pending`,記錄 `command`、`name`、`created_at`
- 原子寫入 `$TASKQ_HOME/tasks.json`
- stdout 輸出 task id(`--json` 時輸出 `{"id": ..., "status": "pending"}`)

> DERIVED: SPEC §8 line 208 — AC is the testable elaboration of "submit \"echo hi\"\" → 8-hex id; run → done; status → exit_code: 0" verbatim canonical check item.

**Acceptance Criteria (testable)**:
- **AC-FR01-01**(happy):`python -m taskq submit "echo hi"` → exit 0;stdout 為 8-hex id;`tasks.json` 內對應 id 之 task 欄位齊全(`command="echo hi"` / `status="pending"` / `created_at` 為 ISO timestamp)
- **AC-FR01-02**(`--json`):`python -m taskq submit --json "echo hi"` → stdout 為合法單行 JSON `{"id": "<8-hex>", "status": "pending"}`
- **AC-FR01-03**(empty):`python -m taskq submit ""` → exit 2;stderr 含錯誤訊息;`tasks.json` 無新增
- **AC-FR01-04**(whitespace-only):`python -m taskq submit "   "` → exit 2
- **AC-FR01-05**(length > 1000):長度 1001 字元命令 → exit 2
- **AC-FR01-06**(injection `;`):`python -m taskq submit "echo hi; rm x"` → exit 2(NFR-02 注入黑名單覆蓋)
- **AC-FR01-07**(injection `|` / `&` / `$` / `>` / `<` / `` ` ``):六個黑名單字元各自一個獨立測試案例 → 全 exit 2
- **AC-FR01-08**(name-unique):`submit --name foo` 後,未消費此 id 前再次 `submit --name foo` → exit 2;第二次寫入未發生
- **AC-FR01-09**(atomicity):模擬 `submit` 中途 `OSError`(單元測試 monkeypatch)→ `tasks.json` 仍為合法 JSON(NFR-03)

### FR-02: 任務執行器

`taskq run <id>` 或 `taskq run --all` [SPEC §3 FR-02]

- 以 `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` 執行;**任何路徑不得使用 `shell=True`** [SPEC §3 FR-02]
- 狀態機:`pending → running → done | failed | timeout` [SPEC §3 FR-02]
  - exit 0 → `done`;非 0 → `failed`;`TimeoutExpired` → `timeout`
- 結果欄位:`exit_code`、`stdout_tail`(末 2000 字元)、`stderr_tail`(末 2000 字元)、`duration_ms`、`finished_at` [SPEC §3 FR-02]
- `--all`:以 `ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS)` 並發執行全部 `pending` 任務;存儲寫入必須執行緒安全(共享 Lock)[SPEC §3 FR-02]
- 單一任務模式下 `timeout` 結果 → **exit 4** [SPEC §3 FR-02]

**Acceptance Criteria (testable)**:
- **AC-FR02-01**(happy single):`submit "echo hi"` 後 `run <id>` → exit 0;task status `done`;`exit_code=0`;`stdout_tail` 含 `hi\n`
- **AC-FR02-02**(failed):`submit "false"` 後 `run <id>` → task status `failed`;`exit_code=1`(非 0)
- **AC-FR02-03**(timeout):`TASKQ_TASK_TIMEOUT=1` + `submit "sleep 5"` 後 `run <id>` → task status `timeout`;exit 4(單任務模式)
- **AC-FR02-04**(stdout/stderr tail 2000 chars):`submit "printf '%2048s'"` 後 `run <id>` → `stdout_tail` 長度 = 2000(末 2000 字元)
- **AC-FR02-05**(`--all` happy):3 個 pending tasks `run --all` → 全部 status `done`;`tasks.json` 為合法 JSON
- **AC-FR02-06**(`--all` thread safety):10 個 pending tasks `run --all` → `tasks.json` 為合法 JSON,所有 task 欄位齊全(無半寫狀態)
- **AC-FR02-07**(`shell=True` absent):`grep -RE 'shell\s*=\s*True' src/taskq/` → 0 hits(NFR-02)
- **AC-FR02-08**(duration_ms + finished_at):`run` 成功後 `status <id>` 顯示 `duration_ms >= 0` 且 `finished_at` 為 ISO timestamp

### FR-03: 重試與斷路器

**重試**:`run` 結果為 `failed`/`timeout` 時自動重試,上限 `TASKQ_RETRY_LIMIT` 次;第 n 次重試前等待 `TASKQ_BACKOFF_BASE × 2^n` 秒(exponential backoff;sleep 函式必須可注入以利測試)[SPEC §3 FR-03].

**斷路器**(全域,跨任務、跨進程)[SPEC §3 FR-03]:
- 連續最終失敗(重試耗盡仍 failed/timeout)計數 ≥ `TASKQ_BREAKER_THRESHOLD` → `OPEN`
- `OPEN` 期間任何 `run` 立即拒絕:**exit 3** + stderr `breaker open`,不執行 subprocess
- 經 `TASKQ_BREAKER_COOLDOWN` 秒後進入 `HALF_OPEN`:放行一個任務 — 成功 → `CLOSED` 且計數歸零;失敗 → 重新 `OPEN`
- 狀態持久化於 `$TASKQ_HOME/breaker.json`(原子寫)

> DERIVED: SPEC §3 FR-03 + SPEC §8 line 212 — AC elaborates the canonical retry+breaker contract: `failed`/`timeout` triggers retry up to `TASKQ_RETRY_LIMIT`, backoff = `TASKQ_BACKOFF_BASE × 2^n`; threshold consecutive failures → OPEN; cooldown → HALF_OPEN → CLOSED.

**Acceptance Criteria (testable)**:
- **AC-FR03-01**(retry on failed):`submit "false"` 後 `run <id>` → 自動重試 `TASKQ_RETRY_LIMIT` 次後 status `failed`
- **AC-FR03-02**(retry on timeout):`TASKQ_TASK_TIMEOUT=1` + `submit "sleep 5"` → 自動重試後 status `timeout`
- **AC-FR03-03**(backoff sequence):sleep 注入式單元測試驗證第 n 次重試前呼叫 sleep(`TASKQ_BACKOFF_BASE × 2^n`)
- **AC-FR03-04**(breaker OPEN):`TASKQ_BREAKER_THRESHOLD=3` 下連續 3 個最終失敗任務,第 4 次 `run` → exit 3 + stderr `breaker open`;不執行 subprocess
- **AC-FR03-05**(breaker HALF_OPEN success):`OPEN` 經 `TASKQ_BREAKER_COOLDOWN` 後,`run <id>`(`submit "echo hi"`)→ 成功,breaker 轉 `CLOSED`,計數歸零
- **AC-FR03-06**(breaker HALF_OPEN failure):`HALF_OPEN` 試探任務最終失敗 → breaker 重新 `OPEN`,新 cooldown 重啟
- **AC-FR03-07**(breaker persistence):`OPEN` 狀態寫入 `breaker.json`(JSON 合法);跨 process 重啟後讀取仍為 `OPEN`
- **AC-FR03-08**(recovery time):`OPEN → CLOSED` 恢復時間 ≤ `TASKQ_BREAKER_COOLDOWN` + 1s(integration test 量測)

### FR-04: 結果 TTL 快取

- 快取簽名 = `sha256(command)` [SPEC §3 FR-04]
- `taskq run <id> --cached`:同簽名且結果為 `done` 的最近執行在 `TASKQ_CACHE_TTL` 秒內 → 直接回放(`exit_code`/`stdout_tail`),**不執行 subprocess**,任務標記 `done` 且 `cached: true` [SPEC §3 FR-04]
- 快取過期或不存在 → 正常執行,成功(`done`)後寫入 `$TASKQ_HOME/cache.json` [SPEC §3 FR-04]
- 快取讀寫:原子 + 執行緒安全(與 FR-02 並發共存)[SPEC §3 FR-04]

> DERIVED: SPEC §8 line 213 — AC is the testable elaboration of "TTL 內 run <id> --cached (同命令簽名) → 回放且 cached: true, 無 subprocess 執行" verbatim canonical check item.

**Acceptance Criteria (testable)**:
- **AC-FR04-01**(cache hit, fresh):同 `command` 第一次 `run` 後未過 TTL 內 `--cached` 重跑 → 不執行 subprocess(monkeypatch `subprocess.run` 計次驗證);task status `done`;`cached: true`
- **AC-FR04-02**(cache miss, expired):TTL 過期後 `--cached` → 重新執行 subprocess;正常寫入 `cache.json`
- **AC-FR04-03**(cache signature):不同 `command` 各自 `run --cached` 互不命中(簽名 = sha256(command))
- **AC-FR04-04**(only `done` cached):`failed` / `timeout` 任務結果**不**寫入 `cache.json`(replay 僅命中 `done`)
- **AC-FR04-05**(atomic write):模擬 `cache.json` 中途 `OSError` → 檔案仍為合法 JSON
- **AC-FR04-06**(thread safety):`run --all` 並發場景下 `cache.json` 為合法 JSON,無半寫條目

### FR-05: CLI 整合

argparse 子命令(入口 `python -m taskq`)[SPEC §3 FR-05]:

| 命令 | 行為 |
|------|------|
| `submit "<cmd>" [--name N]` | FR-01 |
| `run <id> [--cached]` / `run --all` | FR-02/03/04 |
| `status <id>` | 輸出該任務全欄位 |
| `list [--status S]` | 列出任務(可按狀態過濾) |
| `clear` | 清空 `$TASKQ_HOME` 全部資料檔 |

- 全域 flag `--json`:機器可讀輸出(單行 JSON)
- 測試用 flag `--inject-fault=<scenario>`(`corrupt-mid-write` / `oserror-on-write` / `disk-full` / `kill-mid-write`):由 `cli.py` 解析但**僅**用於 NFR-07 fault injection 測試,正式執行路徑完全不啟用 [SPEC §5.3 / §4 NFR-07](測試-only,不出現在上列 user-facing CLI table 中)
- **Exit codes**:`0` 成功 / `2` 輸入驗證錯誤(含 unknown task id) / `3` breaker open / `4` 任務 timeout / `1` 其他內部錯誤 [SPEC §3 FR-05 / §7]

**Acceptance Criteria (testable)**:
- **AC-FR05-01**(`status <id>`):`run <id>` 後 `status <id>` → 該 task 全欄位(`id` / `command` / `name` / `status` / `exit_code` / `stdout_tail` / `stderr_tail` / `duration_ms` / `created_at` / `finished_at`)
- **AC-FR05-02**(`status <id>` `--json`):`--json` flag 下 `status <id>` 輸出單行 JSON
- **AC-FR05-03**(`list` happy):3 個 tasks 完成後 `list` → 列出 3 行(每行一筆)
- **AC-FR05-04**(`list --status done`):5 個 tasks 中 3 個 `done`,`list --status done` → 3 行
- **AC-FR05-05**(`clear`):`clear` 後 `$TASKQ_HOME/` 三個資料檔皆不存在或為空合法 JSON;後續 `list` → 空輸出
- **AC-FR05-06**(unknown task id):`status <non-existent-id>` → exit 2 + stderr `unknown task: <id>`(NFR / §7)
- **AC-FR05-07**(exit code map):五個 exit code(`0` / `1` / `2` / `3` / `4`)各自對應情境可重現(happy / internal error / validation / breaker open / timeout)

---

## 4. Non-Functional Requirements

### NFR-01: performance
**Canonical text** [SPEC §4 table NFR-01]:
> `submit` + `status` 組合操作(不含 subprocess 執行)100 次 p95 < 50ms(pytest-benchmark 量測)

> DERIVED: SPEC §4 NFR-01 + SPEC §11 line 257 — AC restates the canonical latency threshold verbatim and pins pytest-benchmark as the measurement tool per canonical §11.

**Acceptance Criteria (testable)**:
- **AC-NFR01-01**:`submit` + `status` 100 iter(不含 subprocess 執行)p95 < 50ms — pytest-benchmark 量測 [SPEC §11]

> DERIVED boundary: `(不含 subprocess 執行)` is verbatim canonical phrasing — measurement / interpretation boundary is owned by the test harness per [SPEC §4 NFR-01].

### NFR-02: security
**Canonical text** [SPEC §4 table NFR-02]:
> 全 codebase 禁用 `shell=True`;FR-01 注入字元黑名單必須有測試覆蓋

> DERIVED: SPEC §4 NFR-02 + SPEC §11 line 265 — AC elaborates "0 shell=True usage" as the grep-based CI gate per canonical §11 threshold and references the FR-01 blacklist test coverage.

**Acceptance Criteria (testable)**:
- **AC-NFR02-01**:`grep -RE 'shell\s*=\s*True' src/taskq/` → 0 hits(全 codebase 禁用)
- **AC-NFR02-02**:注入字元黑名單(`;` `|` `&` `$` `>` `<` `` ` ``)6 字元各有一個獨立 `pytest` 案例(見 AC-FR01-06/07)
- **AC-NFR02-03**:CI gate 阻擋 `shell=True` 回歸(§11 監控門檻)

### NFR-03: reliability
**Canonical text** [SPEC §4 table NFR-03]:
> 三個資料檔全部原子寫(tmp + `os.replace`),進程中斷後檔案仍為合法 JSON;breaker `OPEN → CLOSED` 恢復時間 ≤ `TASKQ_BREAKER_COOLDOWN` + 1s

> DERIVED: SPEC §4 NFR-03 + SPEC §11 line 263 — AC restates the atomic-write + recovery-time thresholds verbatim; `tasks.json` corruption detection + `store corrupted` exit 1 verbatim from canonical §7.

**Acceptance Criteria (testable)**:
- **AC-NFR03-01**:三資料檔寫入採 tmp + `os.replace`(code review / 單元測試 monkeypatch 模擬 mid-write 中斷 → 檔案仍合法 JSON)
- **AC-NFR03-02**:breaker `OPEN → CLOSED` 恢復時間 ≤ `TASKQ_BREAKER_COOLDOWN` + 1s(integration test 量測)
- **AC-NFR03-03**:`tasks.json` 損壞(非法 JSON)→ 啟動偵測 → exit 1,stderr `store corrupted`,**不**靜默重建 [SPEC §7]

### NFR-04: security
**Canonical text** [SPEC §4 table NFR-04]:
> `stdout_tail`/`stderr_tail` 落盤前,匹配 `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` 的行整行以 `[REDACTED]` 取代

> DERIVED: SPEC §4 NFR-04 — AC elaborates the canonical redaction regex by enumerating the two pattern families (`sk-*` / `token=*`) as test cases; `100%` redaction hit rate per canonical §11 line 264.

**Acceptance Criteria (testable)**:
- **AC-NFR04-01**:`stdout_tail` 含 `sk-abcdef1234567890` 之行 → 該行整行以 `[REDACTED]` 取代
- **AC-NFR04-02**:`stdout_tail` 含 `token=abc123` 之行 → 該行整行以 `[REDACTED]` 取代
- **AC-NFR04-03**:未匹配上述 pattern 的行不變動
- **AC-NFR04-04**:redaction 發生於落盤**前**(單元測試 `cache.json` / `tasks.json` 內容檢查;runtime stub stdout 觸發)

### NFR-05: maintainability
**Canonical text** [SPEC §4 table NFR-05]:
> `src/taskq` 全部公開函式/類別有 docstring 且含 `[FR-XX]` 引用

> DERIVED: SPEC §4 NFR-05 + SPEC §11 line 266 — AC restates the 100% docstring coverage threshold verbatim and extends `[FR-XX]` to also accept `[NFR-XX]` cross-references per canonical intent.

**Acceptance Criteria (testable)**:
- **AC-NFR05-01**:`src/taskq/` 全部 `def` / `class` 公開符號(docstring 存在)→ 100% docstring 覆蓋率(§11 監控門檻)
- **AC-NFR05-02**:每個公開函式 docstring 含至少一個 `[FR-XX]` 或 `[NFR-XX]` 引用(§11 監控門檻)

### NFR-06: deployability
**Canonical text** [SPEC §4 table NFR-06]:
> 全部 8 個 `TASKQ_*` 參數讀自環境變數(config.py 統一讀取,含預設值);`.env.example` 逐一宣告並附註解

> DERIVED: SPEC §4 NFR-06 + SPEC §5.1 — AC restates the 8-env inventory and elaborates the centralized `config.py` reading as a single-source pattern per canonical intent.

**Acceptance Criteria (testable)**:
- **AC-NFR06-01**:`.env.example` 完整宣告 8 個 `TASKQ_*` 變數並附註解(§5.1 全表)
- **AC-NFR06-02**:`config.py` 統一讀取(無散落 `os.environ.get` 散彈式讀取);每個變數含預設值

### NFR-07: resilience
**Canonical text** [SPEC §4 table NFR-07]:
> 三個資料檔必須在 fault injection 情境下正確處理:`tasks.json` / `breaker.json` / `cache.json` 寫入中途損壞(模擬 `OSError` / 模擬磁碟滿 / 中途 kill -9 模擬) → 要麼自動恢復(下次啟動偵測 + 從備份還原)要麼 fail-fast(明確 stderr + 明確 exit code),**不可靜默重建或靜默吞錯**;fault injection 觸發點透過 CLI flag `--inject-fault=<scenario>` 或單元測試的 monkeypatch,正式執行路徑完全不啟用

> DERIVED: SPEC §4 NFR-07 + SPEC §5.3 — AC enumerates the four `--inject-fault` scenarios verbatim from canonical §5.3 flag values and elaborates the dual recovery/fail-fast outcomes per canonical.

**Acceptance Criteria (testable)**:
- **AC-NFR07-01**:`--inject-fault=corrupt-mid-write` → 寫入中途產生損壞檔案;下次啟動偵測後從備份還原 **或** fail-fast(exit 1 + 明確 stderr)
- **AC-NFR07-02**:`--inject-fault=oserror-on-write` → 寫入觸發 `OSError`;同上(恢復 或 fail-fast)
- **AC-NFR07-03**:`--inject-fault=disk-full` → 寫入空間不足;同上
- **AC-NFR07-04**:`--inject-fault=kill-mid-write` → 模擬中途 kill -9;同上
- **AC-NFR07-05**:正式執行路徑(無 `--inject-fault`)完全不啟用 fault injection(§11 監控門檻;靜默重建率 0% / 靜默吞錯率 0%)

> DERIVED boundary: `模擬磁碟滿` 是 verbatim canonical phrasing — measurement / interpretation boundary is owned by the test harness per [SPEC §4 NFR-07].

### NFR-08: concurrency
**Canonical text** [SPEC §4 table NFR-08]:
> **跨行程**(cross-process)安全:多個 `python -m taskq` process 同時操作同一 `$TASKQ_HOME` 不得損壞三個資料檔;使用 `fcntl.flock`(POSIX)/ `msvcrt.locking`(Windows)的檔案鎖;寫入前取得 exclusive lock,讀取前取得 shared lock;**best-effort 增強**,主防線仍為 NFR-03 原子寫;NFS / 網路檔案系統下降級為「無 flock 但維持 atomic write」並發出 `WARNING`

> DERIVED: SPEC §4 NFR-08 + SPEC §11 line 260 — AC pins 4-process concurrency as the integration-test scale per canonical §11 monitoring threshold; `fcntl.flock`/`msvcrt.locking` verbatim from canonical.

**Acceptance Criteria (testable)**:
- **AC-NFR08-01**:4 個 process 並發 `submit` + `run` + `clear` 操作後,三資料檔為合法 JSON、**無任務遺失**(§11 監控門檻;cross-process flock 整合測試)
- **AC-NFR08-02**:POSIX 路徑使用 `fcntl.flock`;Windows 路徑使用 `msvcrt.locking`(code review / platform skip)
- **AC-NFR08-03**:NFS / 網路檔案系統偵測後降級為「無 flock + atomic write」並輸出 `WARNING` 到 stderr

> DERIVED boundary: `NFS / 網路檔案系統` 是 verbatim canonical phrasing — detection / classification boundary is owned by the test harness per [SPEC §4 NFR-08].

### NFR-09: scalability
**Canonical text** [SPEC §4 table NFR-09]:
> 規模擴展:1000 個 task 規模下 `submit` + `status` 組合操作(不含 subprocess 執行)p95 < **100ms**(單一 100 iter 規模 < 50ms 仍由 NFR-01 覆蓋);`run --all` 處理 100 個 task 後 `tasks.json` 為合法 JSON 且 **無任務遺失**;記憶體使用 < 100MB peak(streaming iterator,不在記憶體中載入全部 task)

> DERIVED: SPEC §4 NFR-09 + SPEC §11 line 258 — AC restates the 1000-task p95<100ms threshold and run --all 100-task integrity verbatim from canonical; 100MB memory ceiling is an interpretive operationalization of "streaming iterator" canonical phrasing.

**Acceptance Criteria (testable)**:
- **AC-NFR09-01**:1000 task 規模 `submit` + `status` 組合操作 p95 < 100ms(pytest-benchmark scaled;§11 監控門檻)
- **AC-NFR09-02**:`run --all` 處理 100 個 task 後 `tasks.json` 合法率 100%(§11 監控門檻);**無任務遺失**
- **AC-NFR09-03**:記憶體 peak < 100MB(tracemalloc 量測)

> DERIVED boundary: `(不含 subprocess 執行)` 是 verbatim canonical phrasing — measurement / interpretation boundary is owned by the test harness per [SPEC §4 NFR-09].

### NFR-10: evolvability
**Canonical text** [SPEC §4 table NFR-10]:
> **Schema migration**:三個資料檔 root 必須包含 `version` 欄位(目前 v1);讀到 `version < 1` 時自動升級到 v1 並寫回;讀到 `version > 1`(未來版本)時拒絕讀取並提示升級工具;migrate 前備份原檔為 `<file>.v<n>.bak`;版本升級失敗時保留備份並以 exit 1 fail-fast

> DERIVED: SPEC §4 NFR-10 + SPEC §5.2 — AC elaborates the canonical version-migration contract: `version: 0 → 1` auto-migrate + `<file>.v0.bak` backup; `version > 1` refusal + upgrade-tool prompt + exit 1 — all verbatim from canonical.

**Acceptance Criteria (testable)**:
- **AC-NFR10-01**:三資料檔 root 包含 `version: 1`(§5.2 table)
- **AC-NFR10-02**:讀到 `version: 0` 資料檔 → 自動 migrate 到 v1,並備份為 `<file>.v0.bak`
- **AC-NFR10-03**:讀到 `version: 2`(未來版本)→ 拒絕讀取,stderr 提示升級工具,exit 1
- **AC-NFR10-04**:migrate 失敗時 `<file>.v<n>.bak` 保留,exit 1
- **AC-NFR10-05**:`pytest` fixture-based migration test 驗證 `version: 0 → 1` 100% 成功率 + 備份存在 + 資料可讀(§11 監控門檻)

---

## 5. Acceptance Criteria Summary

對應 `SPEC.md §8` 之 10 個驗收項目,逐條覆蓋到上方 §3/§4 AC[SPEC §8]:

| # | SPEC §8 項目 | 對應 AC |
|---|--------------|---------|
| 1 | `pytest tests/ -q` 全綠 | 所有 AC(整合) |
| 2 | `python -m taskq submit "echo hi"` → 8-hex id;`run <id>` → `done`;`status <id>` 顯示 `exit_code: 0` | AC-FR01-01, AC-FR02-01, AC-FR05-01 |
| 3 | `python -m taskq submit ""` → exit 2 | AC-FR01-03 |
| 4 | `python -m taskq submit "echo hi; rm x"` → exit 2(注入字元) | AC-FR01-06 |
| 5 | `TASKQ_TASK_TIMEOUT=1` 下 `run`(`sleep 5` 任務)→ 狀態 `timeout`,exit 4 | AC-FR02-03 |
| 6 | 3 個連續最終失敗任務後,第 4 次 `run` → exit 3(breaker OPEN);cooldown 後恢復可執行 | AC-FR03-04, AC-FR03-05 |
| 7 | TTL 內 `run <id> --cached`(同命令簽名)→ 回放且 `cached: true`,無 subprocess 執行 | AC-FR04-01 |
| 8 | `.env.example` 宣告全部 8 個 `TASKQ_*` 變數 | AC-NFR06-01 |
| 9 | `run --all` 並發執行後 `tasks.json` 為合法 JSON 且無任務遺失 | AC-FR02-05/06, AC-NFR09-02 |
| 10 | 公開函式 docstring 含 `[FR-XX]` 引用 | AC-NFR05-01/02 |

---

## 6. Out-of-Scope

下列項目**不在本 SRS 範圍內**(明確排除):

- 遠端任務分派 / 跨機器叢集執行(僅本機 process 內 + 本機檔案系統)
- Web UI / HTTP API(僅 CLI,`python -m taskq` 進入)
- 非 Python 3.11 runtime 支援(僅 stdlib only;`shell=True` 永久禁用)
- 持久化以外的資料庫後端(SQLite / Redis 等)— 僅 JSON 檔
- 任務優先級佇列 / 排程(僅 FIFO `pending` 順序)
- 跨平台 UI / TUI
- 國際化 / 多語系錯誤訊息

---

## 7. Open Issues / Deferred Items

### 7.1 NFR-99 — Ambiguity resolution backlog
None at time of authoring — SPEC.md v4.0.0 對所有 FR/NFR 已提供充分實作細節。若後續實作/測試階段發現任何 ambiguous canonical phrasing,新增條目至本節。

### 7.2 FR-XX-deferred / NFR-XX-deferred
None at time of authoring — SPEC.md v4.0.0 §3/§4 全部 FR/NFR 均已落地。

### 7.3 Prompt-injection scan summary
Prompt-injection scan: clean — 0 hits in canonical `SPEC.md`.

---

## 8. Risks

對應 `SPEC.md §9` 風險矩陣,逐條覆蓋 [SPEC §9]:

| ID | 風險 | 緩解 | 對應 NFR/FR |
|----|------|------|------------|
| R1 | 並發寫入損壞 tasks.json | Lock + 原子寫 | NFR-03 |
| R2 | subprocess 懸掛/殭屍 | timeout 必設 | FR-02 |
| R3 | breaker 誤鎖死 | cooldown + HALF_OPEN | FR-03 |
| R4 | 快取回放陳舊結果 | TTL 過期重執行 | FR-04 |
| R5 | secret 落盤洩漏 | stdout_tail/stderr_tail redaction | NFR-04 |
| R6 | fault injection 干擾正常測試 | 觸發僅透過顯式 CLI flag `--inject-fault` 或測試 monkeypatch;正式執行不接受此 flag | NFR-07 |
| R7 | cross-process flock 在 NFS / 網路檔案系統失效 | flock 為 best-effort 增強;偵測到網路 fs 時降級為「無 flock 但維持 atomic write」並 `WARNING` | NFR-08 |
| R8 | scale 1000 tasks 觸發 memory limit | streaming iterator;不一次載入全部 task 到記憶體 | NFR-09 |
| R9 | schema migration 失敗導致資料遺失 | migrate 前備份原檔為 `<file>.v<n>.bak`;失敗時保留備份並 exit 1 fail-fast | NFR-10 |

---

## 9. Glossary

| Term | Meaning |
|------|---------|
| atomic write | tmp + `os.replace` 兩段式寫入,確保中斷後仍為合法檔案 |
| backoff | 重試前指數退避:`TASKQ_BACKOFF_BASE × 2^n` 秒 |
| breaker | 跨任務 / 跨 process 全域斷路器;CLOSED / OPEN / HALF_OPEN |
| cached | `run --cached` 命中 TTL 快取時,任務標記欄位 |
| circuit breaker | 同 breaker |
| fault injection | 透過 `--inject-fault=<scenario>` 觸發之預設失敗情境 |
| HALF_OPEN | breaker 中間態:放行單一任務試探 |
| pending | 任務初始狀態,尚未執行 |
| running | 任務執行中 |
| done / failed / timeout | 任務最終狀態 |
| redaction | 匹配 secret pattern 之行整行以 `[REDACTED]` 取代 |
| streaming iterator | 不一次載入全部資料到記憶體的迭代方式(NFR-09) |
| TASKQ_HOME | 資料檔目錄環境變數(預設 `.taskq`) |
| TTL | Time-To-Live;此處指快取存活秒數(`TASKQ_CACHE_TTL`) |
| version field | 三資料檔 root 必含 `version: 1`;NFR-10 schema migration 基礎 |
| `--json` | CLI 全域 flag,要求單行 JSON 輸出 |

---

## Appendix A: Module Layout(對應 SPEC §6)

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

**Framework alignment** [SPEC §10]:high-risk 模組 `taskq.executor` / `taskq.store` 需 Gate 1 重點驗證。

## Appendix B: Environment Variables(對應 SPEC §5.1)

| 變數 | 預設 | 說明 |
|------|------|------|
| `TASKQ_HOME` | `.taskq` | 資料檔目錄 |
| `TASKQ_MAX_WORKERS` | `4` | `run --all` 並發 worker 數 |
| `TASKQ_TASK_TIMEOUT` | `10.0` | 單任務 subprocess timeout(秒) |
| `TASKQ_RETRY_LIMIT` | `2` | 失敗自動重試上限 |
| `TASKQ_BACKOFF_BASE` | `0.1` | 重試退避基數(秒) |
| `TASKQ_BREAKER_THRESHOLD` | `3` | 連續失敗 → OPEN 閾值 |
| `TASKQ_BREAKER_COOLDOWN` | `5.0` | OPEN → HALF_OPEN 冷卻(秒) |
| `TASKQ_CACHE_TTL` | `3600` | 結果快取存活(秒) |

## Appendix C: Data Files(對應 SPEC §5.2)

| 檔案 | 內容 | version (NFR-10) |
|------|------|----------------|
| `tasks.json` | `{version:1, tasks:{id→全欄位}}` | `1` |
| `breaker.json` | `{version:1, state, failure_count, opened_at}` | `1` |
| `cache.json` | `{version:1, entries:{簽名→done 結果 + cached_at}}` | `1` |

## Appendix D: Exit Codes(對應 SPEC §3 / §7)

| Code | Meaning |
|------|---------|
| 0 | success |
| 2 | input validation error(incl. unknown task id) |
| 3 | breaker OPEN |
| 4 | task timeout(單一任務模式 only) |
| 1 | other internal error |
