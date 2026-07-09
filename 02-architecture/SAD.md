# Software Architecture Document (SAD) — taskq

> 對齊上游 requirements specification `SPEC.md v3.0.0`(5 FR / 6 NFR / 8 env;本專案以 SPEC.md 作為 SRS — Software Requirements Specification),依 `SPEC.md §6` 資料夾結構落地模組設計。
> 框架對齊來源:`harness-methodology v2.9`(`harness/CLAUDE.md` — `no_circular_dependencies`、High-Risk Module 標記)。

---

## 1. Overview

`taskq` 為本地任務佇列 CLI。提交 shell 命令為任務,受控執行(timeout / 重試 / 斷路器 / TTL 快取),狀態可查詢。Python 3.11,**runtime 零外部依賴**,僅依賴標準函式庫。

- **入口**:`python -m taskq`(由 `__main__.py` 啟動 `cli.main()`)
- **形態**:命令列工具(argparse 子命令)
- **持久化**:三個 JSON 資料檔位於 `$TASKQ_HOME/`(`tasks.json` / `breaker.json` / `cache.json`),原子寫入(tmp + `os.replace`)
- **並發模型**:`run --all` 用 `ThreadPoolExecutor`,共享 `threading.Lock` 保護存儲寫入
- **設定來源**:8 個 `TASKQ_*` 環境變數,`config.py` 統一讀取(預設值見 SPEC §5.1)
- **執行邊界**:**任何路徑禁止 `shell=True`**(NFR-02),一律 `subprocess.run(..., shlex.split(command), shell=False, ...)`

設計原則:
1. 模組單向依賴(§2 依賴圖,無循環)
2. High-Risk Module(`executor.py`、`store.py`)與其餘模組介面隔離,便於 Gate 1 / Gate 2 / Gate 4 重點驗證
3. 持久層(store / breaker / cache)皆為「原子寫 + Lock」同 pattern,降低 NFR-03 實作漂移
4. 公開函式 docstring 強制含 `[FR-XX]` 引用(NFR-05)

---

## 2. Module Design

### 2.1 模組清單(SPEC §6 完整保留;≤ 15 files/dir)

| 模組 | 路徑 | 職責 | 主要涵蓋 FR/NFR | 風險層級 |
|------|------|------|----------------|---------|
| `__init__.py` | `src/taskq/__init__.py` | 套件標記、版本字串 | — | 低 |
| `__main__.py` | `src/taskq/__main__.py` | `python -m taskq` 入口,呼叫 `cli.main()` | FR-05 | 低 |
| `config.py` | `src/taskq/config.py` | 8 個 `TASKQ_*` 環境變數讀取 + 預設值 + 型別轉換 | NFR-06 | 低 |
| `models.py` | `src/taskq/models.py` | `Task` / `Status` / `BreakerState` / `CacheEntry` 資料類別 | 全 FR(資料形狀) | 低 |
| `store.py` | `src/taskq/store.py` | `tasks.json` 原子寫 + `threading.Lock` + 損壞偵測 | FR-01, FR-02, NFR-03 | **High-Risk** |
| `executor.py` | `src/taskq/executor.py` | subprocess 執行 + 重試(可注入 sleep)+ 結果欄位組裝 + redaction | FR-02, FR-03, FR-04, NFR-02, NFR-04 | **High-Risk** |
| `breaker.py` | `src/taskq/breaker.py` | CLOSED/OPEN/HALF_OPEN 狀態機 + `breaker.json` 原子寫 | FR-03, NFR-03 | 中 |
| `cache.py` | `src/taskq/cache.py` | `sha256(command)` 簽名 + TTL 過期判定 + `cache.json` 原子寫 + Lock | FR-04, NFR-03 | 中 |
| `cli.py` | `src/taskq/cli.py` | argparse 子命令分派 + `--json` 輸出 + exit code 映射 | FR-05 | 中 |

**模組總數 = 9**(含 `__init__.py` / `__main__.py` 兩個語言慣例檔,實質邏輯模組 7 個)。每模組檔案規模目標 ≤ 300 行,**無 god-module**。

### 2.2 FR → 模組映射 / Traceability Matrix(SPEC §3 全部 5 條 requirement)

| FR | 主要模組 | 次要/協作模組 | 驗證證據(SPEC §8) |
|----|----------|--------------|--------------------|
| FR-01 任務提交與驗證 | `cli.submit_cmd` → `store.add_task` | `config`(讀 `TASKQ_HOME`)、`models.Task` | exit 2 on 注入字元/空/超長/重名 |
| FR-02 任務執行器 | `executor.run_task`、`store.update_task`、`cli.run_cmd` | `config`、`models`、`breaker.check_and_acquire` | exit 4 on timeout、`run --all` 並發後 tasks.json 合法 |
| FR-03 重試與斷路器 | `executor.run_task`(重試 + backoff)、`breaker.record_failure / record_success / try_acquire` | `config`、`store`(任務狀態讀寫) | 連續失敗 ≥ threshold → exit 3,cooldown 後 HALF_OPEN 恢復 |
| FR-04 結果 TTL 快取 | `cache.get`、`cache.put`、`executor.run_task`(快取分支) | `config`(TTL)、`store` | TTL 內 `run --cached` 不執行 subprocess,`cached: true` |
| FR-05 CLI 整合 | `cli.main`(argparse dispatcher) | `__main__`(entry)、所有上述模組 | 5 子命令 + `--json` + exit code 表 |

### 2.3 模組依賴圖(無循環)

```
                ┌──────────────┐
                │  __main__.py │
                └──────┬───────┘
                       │
                       ▼
                ┌──────────────┐
                │    cli.py    │
                └─┬────┬────┬─┬┘
                  │    │    │ │
       ┌──────────┘    │    │ └────────────┐
       ▼               ▼    ▼              ▼
 ┌──────────┐   ┌──────────┐ ┌────────┐ ┌────────┐
 │ store.py │   │executor  │ │breaker │ │ cache  │
 │          │   │   .py    │ │  .py   │ │  .py   │
 └────┬─────┘   └─┬──┬──┬──┘ └───┬────┘ └───┬────┘
      │           │  │  │        │          │
      ▼           ▼  ▼  ▼        ▼          ▼
        ┌────────────┐         ┌──────────┐
        │ models.py  │         │ config.py│(所有模組皆讀)
        └────────────┘         └──────────┘
```

**依賴規則**(強制,harness `no_circular_dependencies`):
- `cli.py` 可呼叫 store / executor / breaker / cache
- `executor.py` 可呼叫 store / breaker / cache / models / config
- `breaker.py` / `cache.py` / `store.py` 三者**彼此不互依**,僅依 models + config
- `models.py` 與 `config.py` 為葉節點,不依賴任何業務模組
- 無雙向依賴 → 無循環

### 2.4 關鍵介面(型別層級,實作於 P3)

```text
# models.py
class Task:           # id, name, command, status, created_at,
                      # exit_code, stdout_tail, stderr_tail,
                      # duration_ms, finished_at, cached
class Status(Enum):   # PENDING, RUNNING, DONE, FAILED, TIMEOUT
class BreakerState:   # state(CLOSED/OPEN/HALF_OPEN), failures, opened_at
class CacheEntry:     # exit_code, stdout_tail, cached_at

# store.py
class TaskStore:
    def add(task: Task) -> None           # FR-01;寫入前驗證唯一性
    def get(task_id: str) -> Task         # FR-05 status
    def list(status: Status|None) -> list # FR-05 list
    def update(task: Task) -> None        # FR-02 狀態推進;Lock 保護
    def clear() -> None                   # FR-05 clear

# executor.py
def run_task(task: Task, *, sleep=_sleep) -> Task
    # FR-02/03/04:timeout → TIMEOUT + exit 4(單任務模式)
    # FR-03:retry up to TASKQ_RETRY_LIMIT,backoff TASKQ_BACKOFF_BASE * 2**n
    # NFR-02:shlex.split + shell=False
    # NFR-04:apply redaction to stdout_tail/stderr_tail before store.update

# breaker.py
class Breaker:
    def try_acquire() -> bool              # FR-03:False → caller exit 3
    def record_success() -> None
    def record_failure() -> None           # 達 threshold → OPEN + 持久化

# cache.py
class Cache:
    def get(signature: str) -> CacheEntry|None   # FR-04:TTL 內回放
    def put(signature: str, entry: CacheEntry)   # 僅 done 寫入
```

### 2.5 持久化與並發(SPEC §5.2 + NFR-03)

所有資料檔(`tasks.json` / `breaker.json` / `cache.json`)統一 pattern:
1. 序列化至 `*.json.tmp`
2. `os.replace(tmp, real)`(POSIX 原子)
3. 寫入路徑全程持有對應 `threading.Lock`(每檔獨立 Lock;`run --all` 共用 `TaskStore._lock`)

損壞偵測:`TaskStore.__init__` 嘗試 `json.load`;`JSONDecodeError` → exit 1,stderr `store corrupted`,**不**靜默重建(SPEC §7)。

---

## 3. Interfaces & Data Flows

### 3.1 主要資料流

```text
使用者 ──argparse──> cli.main()
                       │
                       ├── submit "<cmd>" ──> validate(cmd) ──> TaskStore.add(task)
                       │                                            │
                       │                                            ▼
                       │                                  $TASKQ_HOME/tasks.json(原子寫)
                       │
                       ├── run <id>
                       │     │
                       │     ├── Breaker.try_acquire() ── False ──> exit 3
                       │     │                          ── True
                       │     ▼
                       │     Cache.get(sha256(cmd))? ── hit + TTL OK ──> replay result
                       │     │                                              │
                       │     └── miss/expired ──> executor.run_task(task)   │
                       │                              │                     │
                       │                              ├─ subprocess.run     │
                       │                              ├─ redaction(NFR-04) │
                       │                              ├─ retry w/ backoff   │
                       │                              └─ Breaker.record_*   │
                       │                                                    ▼
                       │                                          TaskStore.update(task)
                       │
                       ├── run --all ──> ThreadPoolExecutor.map([run_task for t in pendings])
                       │                  (共享 TaskStore._lock + Breaker.Lock)
                       │
                       ├── status <id> ──> TaskStore.get(id) ──> print(json or table)
                       ├── list [--status S] ──> TaskStore.list(S) ──> print
                       └── clear ──> TaskStore.clear() + remove breaker.json + cache.json
```

### 3.2 跨程序斷路器流程(SPEC §FR-03)

```text
[程序 A] run 失敗 → Breaker.record_failure() → 寫 breaker.json(原子)
                                              ↓
                                    threshold 達標 → state=OPEN, opened_at=now
                                              ↓
[程序 B] run → Breaker.try_acquire()
                  ├─ state=CLOSED        → 放行
                  ├─ state=OPEN          → now - opened_at < cooldown → 拒絕(exit 3)
                  │                       → ≥ cooldown → state=HALF_OPEN, 放行 1 個
                  └─ HALF_OPEN + 成功    → state=CLOSED, failures=0
                  └─ HALF_OPEN + 失敗    → state=OPEN, opened_at=now(重新計時)
```

### 3.3 對外介面摘要(SPEC §5.1 + §3)

| 介面 | 形式 | 輸入 | 輸出 | 出口碼 |
|------|------|------|------|--------|
| `taskq submit "<cmd>" [--name N]` | CLI | shell 命令字串 | task id(`--json`:`{"id","status":"pending"}`) | 0 / 2 |
| `taskq run <id> [--cached]` | CLI | task id | 該任務最終狀態 | 0 / 2 / 3 / 4 |
| `taskq run --all` | CLI | — | 全部 pending 結果摘要 | 0 / 3 |
| `taskq status <id>` | CLI | task id | 全欄位(json 或表格) | 0 / 2 |
| `taskq list [--status S]` | CLI | 狀態過濾(可選) | 任務列表 | 0 |
| `taskq clear` | CLI | — | 清空 `$TASKQ_HOME` 三檔 | 0 |
| `--json`(全域) | flag | — | 機器可讀單行 JSON | — |

### 3.4 錯誤處理介面(SPEC §7)

| 觸發條件 | 模組 | 行為 |
|----------|------|------|
| 空/超長/注入字元/重名 | `cli.submit_cmd` → `store.add` 預檢 | exit 2 + stderr |
| unknown task id | `cli.run_cmd` / `cli.status_cmd` | exit 2 + stderr `unknown task: <id>` |
| breaker OPEN | `breaker.try_acquire` 返回 False | exit 3 + stderr `breaker open` |
| subprocess timeout | `executor.run_task` 捕捉 `TimeoutExpired` | 狀態 `timeout`;單任務模式 exit 4 |
| `tasks.json` JSON 損壞 | `TaskStore.__init__` | exit 1 + stderr `store corrupted`(**不**靜默重建) |
| 未預期例外 | 各模組頂層 | exit 1,**禁止**裸 `except:` |

---

## 4. NFR Handling

| NFR | 類別 | 設計落點 | 驗證手段(SPEC §11) |
|-----|------|---------|---------------------|
| NFR-01 | performance | `cli.submit_cmd` + `cli.status_cmd` 純本地操作,**不**觸 subprocess;`TaskStore.add` / `get` 為單檔原子寫,瓶頸在 `json.dump` 與 fsync。 | pytest-benchmark:`submit` + `status` 100 iter p95 < 50ms |
| NFR-02 | security | `executor.run_task` 內一律 `shlex.split(command)` + `shell=False`;`cli.submit_cmd` 預檢注入字元黑名單 `; \| & $ > < \`` 。 | 全 codebase grep `shell=True` = 0;注入字元測試覆蓋 ≥ 7 字元 |
| NFR-03 | reliability | `store.py` / `breaker.py` / `cache.py` 三處皆採 `tmp + os.replace` 原子寫 + `threading.Lock`;breaker 恢復時間由 `opened_at + cooldown` 計算。 | fault-injection 中斷後 `json.load` 成功;breaker `OPEN → CLOSED` ≤ `cooldown + 1s` |
| NFR-04 | security | `executor.run_task` 在寫回 `store.update` 前對 `stdout_tail` / `stderr_tail` 套用 `redact(line)`:`(sk-[A-Za-z0-9_-]{8,} \| token=\S+)` 命中行整行 → `[REDACTED]`。 | 單元測試覆蓋 sk-* 與 token= 兩類樣本,命中率 100% |
| NFR-05 | maintainability | 所有 `src/taskq/*.py` 公開函式 / 類別 docstring 第一行包含 `[FR-XX]` 或 `[NFR-XX]` 引用;CI gate `inspect` 強制 100%。 | Gate 1 inspect 報告覆蓋率 = 100% |
| NFR-06 | deployability | `config.py` 集中讀取 8 個 `TASKQ_*` 環境變數 + 型別轉換(str→int / str→float)+ 預設值;`.env.example` 逐一宣告並附註解。 | `.env.example` 8 vars 全列;runtime 零外部依賴 |

### 4.1 NFR 監控門檻對齊(SPEC §11)

| 指標 | 閾值 | 量測責任模組 |
|------|------|-------------|
| `submit` + `status` p95 latency | < 50ms / 100 iter | `tests/perf/`(pytest-benchmark) |
| `run --all` 並發後 tasks.json 合法率 | 100% | fault-injection + `json.load` |
| breaker `OPEN → CLOSED` 恢復時間 | ≤ `TASKQ_BREAKER_COOLDOWN` + 1s | `tests/integration/test_breaker.py` |
| secret redaction 命中率 | 100% | `tests/unit/test_redaction.py` |
| `shell=True` 使用率 | 0 | CI grep gate |
| docstring `[FR-XX]` 覆蓋率 | 100% | Gate 1 inspect |

---

## 5. SAB Block (placeholder)

> SAB YAML 由後續 SAB Generation 階段填入,本節保留 anchor 與 placeholder。

<!-- SAB:START -->
```yaml
sab:
  version: "1.0"
  created_at: "2026-07-10"
  phase: 2  # MUST be int, NOT a string — parser raises on 'phase: "2"'
  project: "taskq"

  # Layers mirror SAD §2.3 dependency graph (api/service/store style):
  # entry → api → service → store → model/config
  layers:
    - name: entry
      modules:
        - "taskq.__main__"
    - name: api
      modules:
        - "taskq.cli"
    - name: service
      modules:
        - "taskq.executor"
    - name: store
      modules:
        - "taskq.store"
        - "taskq.breaker"
        - "taskq.cache"
    - name: model
      modules:
        - "taskq.models"
    - name: config
      modules:
        - "taskq.config"

  # Allowed dependencies — single-direction edges from SAD §2.3 (no_circular_dependencies)
  allowed_dependencies:
    - from: entry
      to: api
    - from: api
      to: service
    - from: api
      to: store
    - from: service
      to: store
    - from: service
      to: model
    - from: service
      to: config
    - from: store
      to: model
    - from: store
      to: config

  quality_targets:
    max_complexity: 15
    min_coverage: 80
    max_coupling: 0.3

  nfr_dimension_mapping: {}  # OPTIONAL — auto-derived from nfr_traceability.type

  # NFR traceability — one entry per NFR from SPEC.md §4 (NFR-01..NFR-06)
  nfr_traceability:
    NFR-01:
      type: performance
      target: "p95 < 50ms / 100 iter"
      module: taskq.cli
    NFR-02:
      type: security
      target: "shell=True usage = 0 across codebase"
      module: taskq.executor
    NFR-03:
      type: reliability
      target: "100% atomic write recovery; breaker OPEN→CLOSED ≤ cooldown+1s"
      module: taskq.store
    NFR-04:
      type: security
      target: "100% redaction hit rate on (sk-[A-Za-z0-9_-]{8,}|token=\\S+)"
      module: taskq.executor
    NFR-05:
      type: maintainability
      target: "100% docstring [FR-XX]/[NFR-XX] coverage on public API"
      module: taskq.cli
    NFR-06:
      type: deployability
      target: "8 TASKQ_* vars declared in .env.example; zero runtime external deps"
      module: taskq.config

  advisory_only: []  # AUTO-FILLED by parser — omit or leave []
  gate_score_overrides: {}  # AUTO-DERIVED by parser — omit or leave {}

  # FR traceability — one entry per FR from SPEC.md §3 (FR-01..FR-05)
  fr_module_traceability:
    FR-01: "taskq.cli"
    FR-02: "taskq.executor"
    FR-03: "taskq.executor"
    FR-04: "taskq.cache"
    FR-05: "taskq.cli"

  architecture_constraints:
    - "no_circular_dependencies"

  # High-risk modules per harness/CLAUDE.md alignment (SPEC §10)
  high_risk_modules:
    - "taskq.executor"
    - "taskq.store"
```
<!-- SAB:END -->

---

## 附錄 A:與 SPEC / framework 對齊聲明

- **SPEC §6 資料夾結構**:本 SAD §2.1 9 模組與 SPEC §6 完全一致(無新增 / 無刪除 / 無重新命名)。
- **SPEC §10 framework 對齊**:
  - `no_circular_dependencies`:§2.3 依賴圖證明無循環。
  - High-Risk Module:`taskq.executor`(FR-02/03)、`taskq.store`(FR-01/02)— 標記於 §2.1。
  - NFR → dimension:`performance` (NFR-01) / `security` (NFR-02, NFR-04) / `error_handling` (NFR-03)— 落於 §4。
- **SPEC §11 監控門檻**:6 項指標全數對應 §4.1 量測責任。

*文件版本:對齊 SPEC.md v3.0.0 | 2026-07-10*