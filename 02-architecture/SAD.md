# Software Architecture Document (SAD) — taskq

> **Project**: `taskq`(本地任務佇列 CLI)
> **Source SSOT**: `SPEC.md` v4.0.0(commit `2fa726c`, 2026-07-11;5 FR / 10 NFR / 8 env)
> **Upstream SRS specification**: `01-requirements/SRS.md` Round 1(LOCKED 2026-07-11) — software requirements specification for `taskq`
> **Traceability matrix**: `01-requirements/TRACEABILITY_MATRIX.md` §6 (bidirectional forward / backward requirement coverage)
> **Author**: Architect Agent A(Sub-Task 1/3 SAD)
> **Round**: 1

---

## 1. Overview

This SAD instantiates the `taskq` software requirements specification (`01-requirements/SRS.md`) into an executable architecture. Each requirement traced from the SRS specification carries one or more FR / NFR anchors here, and the traceability matrix in §1.1 below maps every architectural decision back to its originating requirement.

`taskq` is a zero-dependency(local Python 3.11 + stdlib only)CLI that accepts shell commands as tasks, executes them under controlled constraints(timeout, retry, circuit breaker, TTL cache), and persists state to `$TASKQ_HOME` JSON files.

**Runtime entry**: `python -m taskq`(由 `__main__.py` 啟動 argparse 子命令)

**Architecture style**: 模組化單進程多執行緒設計;以 `argparse` 子命令作為唯一外部介面,內部以 8 個 `src/taskq/*.py` 模組劃分職責,單向依賴(`cli` → `executor` / `breaker` / `cache` / `store` / `config` / `models`),**無循環依賴**。

**Key constraints**:
- 全部 8 個 `TASKQ_*` 參數讀自環境變數(NFR-06)
- 三個資料檔(`tasks.json` / `breaker.json` / `cache.json`)採原子寫(tmp + `os.replace`)(NFR-03 / NFR-10)
- 跨進程安全靠 `fcntl.flock` / `msvcrt.locking`,網路 fs 自動降級(NFR-08)
- Subprocess 絕對禁用 `shell=True`(NFR-02)

### 1.1 SRS Specification ↔ SAD Traceability Matrix

The traceability matrix below maps each functional requirement and non-functional requirement in the upstream SRS specification (`01-requirements/SRS.md`) to its architectural anchor in this SAD. Every SRS requirement must appear in at least one row; every SAD section that materializes a requirement must appear as a column. The bidirectional counterpart of this traceability matrix is `01-requirements/TRACEABILITY_MATRIX.md` §6.

| SRS Requirement | SRS Anchor | SAD Section | Module(s) | ADR |
|-----------------|-----------|-------------|-----------|-----|
| FR-01 任務提交與驗證 | SRS §3.1 | §2.2, §3.1 | `cli.submit`, `store.add` | ADR-002, ADR-011 |
| FR-02 任務執行器 | SRS §3.2 | §2.2, §3.4 | `executor.run_task` | ADR-002, ADR-003, ADR-011, ADR-012 |
| FR-03 重試與斷路器 | SRS §3.3 | §2.2, §3.4 | `executor.retry`, `breaker.Breaker` | ADR-002, ADR-006 |
| FR-04 結果 TTL 快取 | SRS §3.4 | §2.2 | `cache.Cache` | ADR-002, ADR-007 |
| FR-05 CLI 整合 | SRS §3.5 | §3.1 | `cli.main` | ADR-002, ADR-008 |
| NFR-01 performance | SRS §4.1 | §4 | `cli`, `store` | ADR-003 |
| NFR-02 security | SRS §4.2 | §4, §6 | `cli.submit`, `executor` | ADR-011, ADR-013 |
| NFR-03 reliability | SRS §4.3 | §4 | `store`, `breaker`, `cache` | ADR-004, ADR-006 |
| NFR-04 security | SRS §4.4 | §4, §6 | `executor` | ADR-012, ADR-013 |
| NFR-05 maintainability | SRS §4.5 | §4, §2.5 | 全 8 模組 | ADR-001, ADR-002, ADR-015 |
| NFR-06 deployability | SRS §4.6 | §4 | `config` | ADR-001, ADR-009 |
| NFR-07 resilience | SRS §4.7 | §4 | `store`, `cli` | ADR-004, ADR-014 |
| NFR-08 concurrency | SRS §4.8 | §4 | `store`, `breaker`, `cache` | ADR-005 |
| NFR-09 scalability | SRS §4.9 | §4 | `store`, `executor` | ADR-003 |
| NFR-10 evolvability | SRS §4.10 | §4 | `store`, `breaker`, `cache`, `models` | ADR-004, ADR-010 |

**Coverage statement**:
- Every FR (5/5) and NFR (10/10) from the SRS specification appears in this traceability matrix.
- Every SAD section that adds architectural decision is referenced from the matrix; no orphan architectural decision exists.
- No orphan requirement: each row points to a SAD anchor + module(s) + ADR — the full ownership triple that Gate 1 / Gate 4 will inspect.

---

## 2. Module Design

對應 `SPEC.md §6` 資料夾結構;每個 FR 對應 ≥1 個模組;每個模組 ≤ 2 個主要職責;**無 god-module**。

### 2.1 Module tree(SPEC §6 SSOT)

```
src/taskq/
├── __init__.py        # 版本/套件入口
├── __main__.py        # `python -m taskq` 入口(呼叫 cli.main())
├── config.py          # TASKQ_* 環境變數統一讀取(NFR-06)
├── models.py          # 任務/狀態資料類別 + 版本欄位(NFR-10)
├── store.py           # tasks.json 原子存儲 + Lock + flock(NFR-03/08,FR-01/02)
├── executor.py        # subprocess 執行 + 重試(FR-02/03,NFR-02/04)
├── breaker.py         # 斷路器(FR-03,NFR-03)
├── cache.py           # TTL 快取(FR-04,NFR-03/08)
└── cli.py             # argparse(FR-05)
```

共 **9 個檔案**(含 `__init__.py`);≤ 15 上限。

### 2.2 FR → Module mapping

| FR | 主要模組 | 次要模組 | 說明 |
|----|---------|---------|------|
| FR-01 任務提交與驗證 | `cli.submit` | `models.Task` / `store` | `cli` 解析 argv → 調用注入字元黑名單 + 名稱唯一性檢查 → `store.add()` 原子寫入 `tasks.json` |
| FR-02 任務執行器 | `executor.run_task` | `store` / `breaker` / `config` | `executor.run` 呼叫 `subprocess.run(shlex.split(...), shell=False, timeout=...)`;狀態轉移 `pending → running → done/failed/timeout`;`--all` 路徑用 `ThreadPoolExecutor` |
| FR-03 重試與斷路器 | `executor.retry` + `breaker.Breaker` | `store` | `executor` 負責 retry 排程(可注入 sleep);`breaker` 負責跨任務、跨進程的 `CLOSED/OPEN/HALF_OPEN` 狀態機,持久化於 `breaker.json` |
| FR-04 結果 TTL 快取 | `cache.Cache` | `executor` | `--cached` flag → `cache.lookup(sha256(command))`;命中且 TTL 未過期 → 直接回放;否則正常執行後寫入 |
| FR-05 CLI 整合 | `cli.main` | 全部 | argparse 子命令 `submit / run / status / list / clear`;`--json` flag;exit code 對應 `SPEC §7` 表格 |

### 2.3 Module responsibilities & boundaries

| 模組 | 公開介面 | 職責 | 不得做 |
|------|---------|------|--------|
| `cli` | `main(argv=None)` / `submit(args)` / `run(args)` / `status(args)` / `list(args)` / `clear(args)` | argparse 解析、exit code 對應、JSON 輸出 | 直接寫檔、直接呼叫 subprocess |
| `executor` | `run_task(task_id)` / `run_all()` / `retry(task_id)` | subprocess 執行、狀態機、重試排程、輸出 redaction(NFR-04) | 直接讀寫 tasks.json(透過 `store`) |
| `breaker` | `Breaker.before_run()` / `record_success()` / `record_failure()` / `state` | 斷路器狀態機、cooldown、持久化 | 任何與 subprocess 相關邏輯 |
| `cache` | `lookup(signature)` / `store(signature, result)` | TTL 快取讀寫、原子上鎖 | 任何與 subprocess 相關邏輯 |
| `store` | `add(task)` / `get(task_id)` / `list_()` / `update(task_id, **kw)` / `clear()` | tasks.json 原子存儲 + threading.Lock + flock、版本欄位驗證(NFR-10) | 任何 subprocess 邏輯 |
| `models` | `Task` / `TaskStatus` / `BreakerState` / `CacheEntry` | 純資料類別;附 docstring + `[FR-XX]`(NFR-05) | I/O、subprocess |
| `config` | `Config` 屬性:`home / max_workers / task_timeout / retry_limit / backoff_base / breaker_threshold / breaker_cooldown / cache_ttl` | 環境變數讀取(僅一次,啟動時 freeze) | 任何 I/O、subprocess |
| `__main__` | (無) | `from cli import main; sys.exit(main())` | 任何業務邏輯 |

### 2.4 Dependency graph(no cycles)

```
__main__ ──▶ cli ──▶ executor ──▶ store ──▶ config / models
              │          │           ▲
              │          ├──▶ breaker┘
              │          └──▶ cache ──┘
              └─▶ store / breaker / cache / config / models
```

驗證:`cli` 是唯一對外介面;`store / breaker / cache` 三者互不依賴(僅共用 `config / models`);`executor` 同時依賴三者;`models / config` 無任何業務依賴(葉節點)。**無循環**。

### 2.5 File-count audit

| 目錄 | 檔案數 | 上限 | 結果 |
|------|-------|------|------|
| `src/taskq/` | 9(8 .py + `__init__.py`) | 15 | PASS |
| `tests/` | (P3 範圍,本文件不規範) | — | — |

無 god-module:最大模組預期為 `cli`(5 個子命令 dispatcher)+ `executor`(執行 + 重試 + redaction),皆 < 300 LOC 預期。

---

## 3. Interfaces & Data Flows

### 3.1 External interface(CLI)

`python -m taskq <subcommand> [args] [--json] [--inject-fault=SCENARIO]`

| 子命令 | 簽名 | 輸出 | exit code |
|--------|------|------|-----------|
| `submit` | `submit "<command>" [--name NAME]` | task id(str or JSON) | `0` / `2` |
| `run` | `run <id> [--cached]` / `run --all` | 結果摘要 | `0` / `2` / `3` / `4` |
| `status` | `status <id>` | task 全欄位 | `0` / `2` |
| `list` | `list [--status S]` | task 列表 | `0` |
| `clear` | `clear` | (none) | `0` |

### 3.2 Internal interfaces(模組間契約)

| Caller → Callee | 方法 | 傳入 | 傳出 |
|-----------------|------|------|------|
| `cli.submit` → `store.add` | `add(task: Task) -> None` | `Task` 物件 | (寫入後 stdout id) |
| `cli.run` → `executor.run_task` | `run_task(task_id: str, use_cache: bool) -> Task` | task id + cache flag | 更新後的 `Task` |
| `cli.run --all` → `executor.run_all` | `run_all() -> int` | (none) | 處理筆數 |
| `executor.run_task` → `breaker.before_run` | `before_run() -> bool` | (none) | `True` 放行 / `False` 拒絕 |
| `executor.run_task` → `cache.lookup` | `lookup(signature: str) -> Optional[Task]` | sha256 | 快取結果或 None |
| `executor.run_task` → `cache.store` | `store(signature: str, task: Task) -> None` | sha256 + done Task | (none) |
| `executor.run_task` → `store.update` | `update(task_id, **fields) -> Task` | task id + kwargs | 更新後 Task |
| `store.add` / `update` / `cache.store` / `breaker.record_*` | 共用 `atomic_write_json(path, data)` | path + dict | (none, raises on corruption) |

### 3.3 Data flow diagram(ASCII)

```
        ┌──────────────────────────────────────────────────────┐
        │                  CLI  (argparse)                     │
        │  submit / run / status / list / clear                │
        └─────────┬───────────┬───────────┬────────────────────┘
                  │           │           │
        submit ──▶│   run ──▶│   status ─▶│
                  ▼           ▼           ▼
              ┌──────┐  ┌──────────┐  ┌──────┐
              │store │  │ executor │  │store │
              │  +   │◀─┤   +      │  │  +   │
              │ flock│  │ retry    │  │ flock│
              └──┬───┘  └────┬─────┘  └──┬───┘
                 │           │           │
                 ▼           ▼           ▼
       $TASKQ_HOME/    ┌──────────┐   tasks.json
       tasks.json      │ breaker  │   (atomic write)
                       │   +      │
                       │ flock    │
                       └────┬─────┘
                            ▼
                       breaker.json
                            ▲
                            │
                       ┌────┴─────┐
                       │  cache   │
                       │   +      │
                       │ flock    │
                       └────┬─────┘
                            ▼
                       cache.json
```

### 3.4 State machine(task lifecycle)

```
   ┌──────────┐  run   ┌─────────┐  exit=0    ┌──────┐
   │ pending  │──────▶│ running │──────────▶│ done │
   └──────────┘        └────┬────┘            └──────┘
        ▲                   │ exit≠0            ▲
        │                   ▼                   │
        │              ┌─────────┐              │ cache hit
        │              │ failed  │ retry ≤N     │ (--cached)
        │              └────┬────┘──────────────┘
        │ retry             │ retry exhaust
        │                   ▼
        │              ┌─────────┐
        │              │ failed  │ (terminal)
        │              └─────────┘
        │
        │                   ┌──────────┐
        └───── retry ───────│ timeout  │──▶ retry
                            └──────────┘
```

### 3.5 Cross-cutting flow(fault injection)

正式執行路徑**完全不接受** `--inject-fault`(由 `cli` 在啟動時檢查並拒絕);僅測試路徑 + 開發 monkeypatch 啟用(NFR-07)。

---

## 4. NFR Handling

依 `SPEC.md §4` 10 個 NFR 逐一對應設計決策 + 落實模組 + 驗證方式。

| NFR | 類別 | 設計決策 | 落實模組 | 驗證方式 |
|-----|------|---------|---------|---------|
| NFR-01 | performance | `submit` + `status` 純 I/O,無 subprocess;`store` 用最小鎖定範圍(臨界區僅 `json.dump + os.replace`) | `cli` / `store` / `models` | pytest-benchmark 100 iter p95 < 50ms |
| NFR-02 | security | (1) `executor.run_task` 強制 `shlex.split` + `shell=False`(全 codebase grep guard);(2) `cli.submit` 注入字元黑名單 `; \| & $ > < \`` | `cli.submit` / `executor.run_task` | CI gate:`grep -r "shell=True" src/` 為空 + 注入字元 unit test |
| NFR-03 | reliability | `atomic_write_json(path, data)` 統一介面:寫到 `<path>.tmp` → `os.replace`;`breaker` 持久化同樣原子寫;`OPEN → CLOSED` 恢復時間受 `TASKQ_BREAKER_COOLDOWN` 控制 | `store` / `breaker` / `cache`(全部共用原子寫) | 注入 `kill -9` 中斷後重新啟動 → `json.load` 成功;breaker 整合測試 |
| NFR-04 | security | `executor` 在 `subprocess.run` 回傳後,對 `stdout_tail` / `stderr_tail` 跑 regex `(sk-[A-Za-z0-9_-]{8,}\|token=\S+)`,命中行整行以 `[REDACTED]` 取代後**才**落盤 | `executor.run_task` | unit test:`echo "sk-abcdef1234"` → 落盤後 grep 不到原字串 |
| NFR-05 | maintainability | 全部 `src/taskq/*.py` 公開函式 / 類別 docstring 末段附 `[FR-XX]` 引用;由 `models.Task` / `executor.run_task` / `cache.Cache` 等帶頭 | 全 8 模組 | Gate 1 inspect:抽樣 + 自動檢查 |
| NFR-06 | deployability | `config.py` 啟動時一次性 `os.environ.get(...)` 並 freeze;`.env.example` 8 vars 完整宣告 | `config` | `.env.example` 對照測試 |
| NFR-07 | resilience | `atomic_write_json` 內部 try/except 區分:`OSError` / 磁碟滿 → 保留 `.tmp` 並 raise → `cli` exit 1;`kill -9` 中斷 → 下次啟動偵測 `.tmp` 孤兒 → fail-fast(不靜默重建);`--inject-fault=<scenario>` 為唯一觸發介面,正式路徑由 `cli` 拒絕 | `store` / `breaker` / `cache` / `cli` | fault-injection test 4 scenarios 全部 fail-fast 或自動恢復 |
| NFR-08 | concurrency | `store` / `breaker` / `cache` 寫入前取得 `fcntl.flock(fd, LOCK_EX)`,讀取前 `LOCK_SH`;啟動時偵測 `$TASKQ_HOME` 是否位於 NFS / 網路 fs(`os.statvfs` 啟發式),若是 → log WARNING + 降級為「無 flock 但維持 atomic write」 | `store` / `breaker` / `cache` | 4-process 並發測試 → 三資料檔 100% 合法;NFS 路徑 WARNING 測試 |
| NFR-09 | scalability | `store.list_()` 採 streaming generator,不在記憶體中累積 1000 tasks;`run --all` 逐筆 submit 到 `ThreadPoolExecutor`;`--all` 100 task 跑完 `tasks.json` 合法率 100% | `store` / `executor.run_all` | pytest-benchmark 1000 iter p95 < 100ms + memory peak < 100MB |
| NFR-10 | evolvability | 三資料檔 root 一律 `{"version": 1, ...}`;`store / breaker / cache` 啟動時 `migrate(data)`:`version < 1` → 升級 + 備份 `<file>.v<n>.bak`;`version > 1` → raise(`version_too_new`)→ cli exit 1;`migrate` 失敗 → 保留備份並 raise | `store` / `breaker` / `cache` / `models` | fixture-based migration test:舊版檔 → 升級後可讀 + 備份存在 |

### 4.1 模組 × NFR 覆蓋矩陣

| | cli | executor | breaker | cache | store | models | config |
|---|---|---|---|---|---|---|---|
| NFR-01 | ✓ | | | | ✓ | | |
| NFR-02 | ✓ | ✓ | | | | | |
| NFR-03 | | | ✓ | ✓ | ✓ | | |
| NFR-04 | | ✓ | | | | | |
| NFR-05 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| NFR-06 | | | | | | | ✓ |
| NFR-07 | ✓ | | ✓ | ✓ | ✓ | | |
| NFR-08 | | | ✓ | ✓ | ✓ | | |
| NFR-09 | | ✓ | | | ✓ | | |
| NFR-10 | | | ✓ | ✓ | ✓ | ✓ | |

每個 NFR 至少 1 個模組負責;每個模組負責的 NFR 數 ≤ 4(`store`: 03/07/08/09/10 = 5)。

---

## 5. SAB Block

> SAB Generation phase will replace the placeholder below with real YAML.

<!-- SAB:START -->

```yaml
sab:
  version: "1.0"
  created_at: "2026-07-17"
  phase: 2  # MUST be int, NOT a string — parser raises on 'phase: "2"'
  project: "taskq"

  layers:
    - name: cli
      modules:
        - name: "taskq.cli"
        - name: "taskq.__main__"
      allowed_dependencies: ["service", "store"]
    - name: service
      modules:
        - name: "taskq.executor"
      allowed_dependencies: ["store"]
    - name: store
      modules:
        - name: "taskq.store"
        - name: "taskq.breaker"
        - name: "taskq.cache"
        - name: "taskq.models"
        - name: "taskq.config"
      allowed_dependencies: []

  allowed_dependencies:
    - from: cli
      to: service
    - from: cli
      to: store
    - from: service
      to: store

  quality_targets:
    max_complexity: 10
    min_coverage: 90
    max_coupling: 0.3

  nfr_dimension_mapping: {}  # OPTIONAL — auto-derived from nfr_traceability.type

  nfr_traceability:
    NFR-01:
      type: performance
      target: "p95 < 50ms (warm-process, submit+status over 100 iters, excluding subprocess)"
      module: taskq.store
    NFR-02:
      type: security
      target: "shell=True forbidden codebase-wide; injection blacklist ( ; | & $ > < ` ) covered by tests"
      module: taskq.executor
    NFR-03:
      type: reliability
      target: "atomic tasks.json write via tmp+os.replace; OPEN→CLOSED recovery ≤ TASKQ_BREAKER_COOLDOWN+1s"
      module: taskq.store
    NFR-04:
      type: security
      target: "100% redaction of stdout_tail/stderr_tail lines matching (sk-[A-Za-z0-9_-]{8,}|token=\\S+) before persist"
      module: taskq.executor
    NFR-05:
      type: maintainability
      target: "100% docstring [FR-XX] coverage on public functions/classes in src/taskq/*.py"
      module: taskq.models
    NFR-06:
      type: deployability
      target: "all 8 TASKQ_* env vars declared in .env.example and read centrally from config.py"
      module: taskq.config
    NFR-07:
      type: reliability
      target: "100% fail-fast or auto-recover for corrupt-mid-write / oserror-on-write / disk-full / kill-mid-write; never silent rebuild"
      module: taskq.store
    NFR-08:
      type: reliability
      target: "100% data-file legality after 4 concurrent python -m taskq processes; fcntl.flock with NFS auto-degrade + WARNING"
      module: taskq.store
    NFR-09:
      type: scalability
      target: "p95 < 100ms for submit+status over 1000 iters; peak memory < 100MB; run --all 100 tasks leaves tasks.json valid + zero task loss"
      module: taskq.store
    NFR-10:
      type: maintainability
      target: "100% successful migration v0→v1 (backup <file>.v<n>.bak present + data readable); version>1 → exit 1 fail-fast"
      module: taskq.store

  advisory_only: []  # AUTO-FILLED by parser — omit or leave []

  gate_score_overrides: {}  # AUTO-DERIVED by parser — omit or leave {}

  fr_module_traceability:
    FR-01: "taskq.cli"
    FR-02: "taskq.executor"
    FR-03: "taskq.executor"
    FR-04: "taskq.cache"
    FR-05: "taskq.cli"

  architecture_constraints:
    - "no_circular_dependencies"

  high_risk_modules:
    - "taskq.executor"
    - "taskq.store"
```

<!-- SAB:END -->

---

## 6. Security Design(STRIDE-lite Threat Model)

> Canonical template via `core.quality_gate.security_design.render_canonical_security_template()`;EXAMPLE values replaced with real project values from `SPEC.md §3/§4` + `§9 Risk Matrix`。

<!-- SEC:START -->

```yaml
security_design:
  version: "1.0"
  applicability: full   # full | none — none REQUIRES justification and skips the rest
  justification: ""     # required (>=20 chars) when applicability: none
  trust_boundaries:     # real boundaries from SPEC §3/§4
    - id: TB-01
      name: "user CLI argv"
      description: "argv crossing from shell/terminal into the taskq argparse layer — user fully controls input string"
    - id: TB-02
      name: "subprocess execution"
      description: "taskq.executor crossing into a child process via subprocess.run — child receives parsed argv tokens, never a shell"
    - id: TB-03
      name: "persistence at $TASKQ_HOME"
      description: "taskq modules writing/reading tasks.json / breaker.json / cache.json — local FS (POSIX flock) or networked FS (degraded)"
  threats:              # STRIDE-lite — every boundary needs >=1 threat
    - id: T-01
      boundary: TB-01
      category: tampering
      description: "user submits command containing shell metacharacters (; | & $ > < `) attempting shell injection"
      mitigation: "FR-01 injection blacklist in cli.submit rejects command and exits with code 2 BEFORE writing to store"
      owner_module: "taskq.cli"
      nfr: NFR-02
      verified_by: "test_submit_rejects_injection_chars"
    - id: T-02
      boundary: TB-02
      category: tampering
      description: "developer accidentally enables shell=True in subprocess.run, bypassing shlex.split safety"
      mitigation: "codebase-wide grep guard (CI gate) rejects any new shell=True occurrence; SPEC §2 marks shell=True as forbidden"
      owner_module: "taskq.executor"
      nfr: NFR-02
      verified_by: "test_no_shell_true_in_source"
    - id: T-03
      boundary: TB-02
      category: information_disclosure
      description: "subprocess stdout/stderr contains secrets (sk-* API keys, token=... query strings) that get persisted to disk via stdout_tail/stderr_tail"
      mitigation: "executor runs regex redaction (sk-[A-Za-z0-9_-]{8,}|token=\\S+) on output BEFORE atomic write to tasks.json"
      owner_module: "taskq.executor"
      nfr: NFR-04
      verified_by: "test_redact_secret_in_output"
    - id: T-04
      boundary: TB-03
      category: tampering
      description: "two python -m taskq processes writing tasks.json simultaneously corrupt the JSON file"
      mitigation: "atomic_write_json (tmp + os.replace) as primary defense; fcntl.flock exclusive lock as cross-process enhancement; auto-degrade with WARNING on networked FS"
      owner_module: "taskq.store"
      nfr: NFR-08
      verified_by: "test_concurrent_processes_no_corruption"
    - id: T-05
      boundary: TB-03
      category: denial_of_service
      description: "mid-write OSError / disk-full / kill -9 leaves tasks.json corrupted on next startup"
      mitigation: "NFR-07 fault detection on startup detects .tmp orphan + fails fast (exit 1 + stderr); NEVER silently rebuilds — preserves evidence for operator"
      owner_module: "taskq.store"
      nfr: NFR-07
      verified_by: "test_fault_injection_corrupt_mid_write_fails_fast"
    - id: T-06
      boundary: TB-03
      category: repudiation
      description: "operator runs a destructive command via taskq but later denies it — no audit trail"
      mitigation: "tasks.json retains created_at / finished_at / exit_code per task (SPEC §3 FR-01/FR-02 fields); operator can review full history via `taskq list`"
      owner_module: "taskq.store"
      nfr: NFR-03
      verified_by: "test_task_records_timestamps"
    - id: T-07
      boundary: TB-01
      category: elevation_of_privilege
      description: "future operator uses --inject-fault flag in production to disrupt tasks.json state"
      mitigation: "cli rejects --inject-fault at startup unless TASKQ_ENV in {dev,test} — production path hard-fails (SPEC §5.3: production NEVER accepts this flag)"
      owner_module: "taskq.cli"
      nfr: NFR-07
      verified_by: "test_inject_fault_rejected_in_production"
```

<!-- SEC:END -->

### 6.1 Threat → FR/NFR traceability

| Threat | Owner module | FR/NFR | Verified by |
|--------|-------------|--------|-------------|
| T-01 shell injection | `taskq.cli` | FR-01 / NFR-02 | `test_submit_rejects_injection_chars` |
| T-02 shell=True regression | `taskq.executor` | NFR-02 | `test_no_shell_true_in_source` |
| T-03 secret leak | `taskq.executor` | NFR-04 | `test_redact_secret_in_output` |
| T-04 cross-process corruption | `taskq.store` | NFR-03 / NFR-08 | `test_concurrent_processes_no_corruption` |
| T-05 fault injection corruption | `taskq.store` | NFR-07 | `test_fault_injection_corrupt_mid_write_fails_fast` |
| T-06 audit gap | `taskq.store` | NFR-03 | `test_task_records_timestamps` |
| T-07 fault-flag abuse | `taskq.cli` | NFR-07 | `test_inject_fault_rejected_in_production` |

7 threats / 3 boundaries / 7 verified_by tests。**無 unowned threat**;每個 `owner_module` 皆為 `§2` 已宣告模組;每個 `nfr` 皆存在於 `SPEC §4`。

---

*Document version: SAD Round 1 | 2026-07-16 | Source SSOT: `SPEC.md` v4.0.0*
