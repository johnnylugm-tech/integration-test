# Architecture Decision Records (ADR) — taskq

> 對齊 `SRS.md / SPEC.md v3.0.0`(SRS = Software Requirements Specification,即本專案的 requirements specification 來源文件)與 `02-architecture/SAD.md`。本文件記錄 `taskq` 在 P2 階段做成、且需在 P3+ 維持的架構決策;每筆 ADR 對應 SAD.md 一段可標註的設計斷面,並透過文末 **FR / NFR traceability matrix** 對應回 SRS.md 的 FR / NFR 編號。
> 框架對齊:`harness-methodology v2.9`(`harness/CLAUDE.md` — `no_circular_dependencies`、High-Risk Module 標記)。

---

## ADR-001: Python 3.11 standard-library-only runtime

### Status
Accepted

### Context
`taskq` 是一個本地任務佇列 CLI(SRS §1,5 FR / 6 NFR / 8 env)。本 specification 需求強調部署簡潔性(SRS NFR-06)與「無 vendor lock」,CI 環境不希望為了單一 CLI 工具引入 `pip` / virtualenv 維運成本。SRS §5.1 把所有設定收斂為 8 個 `TASKQ_*` 環境變數,意圖讓「單一可執行檔 + 環境變數」即可運行。

### Decision
`taskq` runtime **完全使用 Python 3.11 標準函式庫**,禁止新增任何 `requirements.txt` / `pyproject.toml` 第三方依賴(僅允許 dev/test 依賴走 dev 群組)。CLI 入口使用 `argparse`,持久化使用 `json`,並發使用 `concurrent.futures.ThreadPoolExecutor` + `threading.Lock`,子行程使用 `subprocess` + `shlex`,檔案原子寫入使用 `os.replace`。

### Consequences
- (+) 部署只需 `python -m taskq` 即可;容器化 / portable shell 場景零摩擦。
- (+) 升級 Python 解譯器即可獲得安全補丁,無 transitive dependency 漏洞面。
- (+) `pip install` / lockfile 漂移 / 依賴衝突等問題完全不存在。
- (-) 任何超出 stdlib 的需求(如 HTTP client、caching backend)需自行實作,工作量大於直接 `import requests`。
- (-) 若日後 SPEC 要求 JSONL / MessagePack / SQLite 等格式,需在 stdlib 邊界內尋解(可用 `sqlite3` 模組)。
- 維護成本與 SPEC §5.1 8 env-var 設定契約成正比。

### Alternatives Considered
- **A. Click + Pydantic + structlog 為基礎的現代 Python CLI stack** — 開發體驗好,但違反 NFR-06「runtime 零外部依賴」。拒絕。
- **B. 採用 `uv` / `poetry` 管理依賴 + 一個極小依賴集** — 仍引入 `pip` lock 機制,SPEC §5.1 表達意圖是「無依賴即設定」。拒絕。
- **C. 採用 Python 3.10(放棄 3.11 的 `tomllib` / 效能改善)** — 無實質效益,只會增加技術債。拒絕。
- **D. 改寫成 Go / Rust 單檔二進位** — 違反 SPEC §1「Python CLI」身份;且引入新語言 toolchain。拒絕。

---

## ADR-002: 9 模組單向依賴切分

### Status
Accepted

### Context
SPEC §6 定義 9 個模組(`__init__` / `__main__` / `config` / `models` / `store` / `executor` / `breaker` / `cache` / `cli`),harness `no_circular_dependencies` 規則禁止任何循環依賴;`executor` 與 `store` 屬 High-Risk Module,需在 Gate 1 / 2 / 4 單獨驗證。如果模組邊界切錯,High-Risk 模組的可隔離測試性會崩解。

### Decision
模組依賴遵循 SAD §2.3 圖:
- `cli.py` 為唯一 dispatcher,可呼叫 `store` / `executor` / `breaker` / `cache`。
- `executor.py` 可呼叫 `store` / `breaker` / `cache` / `models` / `config`(業務邏輯核心)。
- `store.py` / `breaker.py` / `cache.py` **三者互不依賴**,僅依 `models` + `config`。
- `models.py` 與 `config.py` 為葉節點,不依賴任何業務模組。
- 無雙向 edge → 拓樸無循環。

High-Risk Module 標記:`taskq.executor`(FR-02/03)與 `taskq.store`(FR-01/02),於 SAD §2.1 表格明確列出,Gate 1 / 2 / 4 的 per-FR / per-dimension 評分對此兩模組加重權重。

### Consequences
- (+) 任何業務模組(`store` / `breaker` / `cache`)可在沒有 `cli` / `executor` 的情況下獨立單元測試,符合 NFR-05「可維護性」中隔離測試意圖。
- (+) High-Risk Module 變更時可精準定位 blast radius,降低 P3+ 變更風險。
- (+) `models` / `config` 為葉節點 → 變更頻率最低,適合作為 type contract 的「穩定根」。
- (-) 若日後想在 `breaker.py` 內讀 `cache.py`(例如「冷卻期間優先回放快取」),需重新評估是否歸入 `executor.py` 內(目前規劃是 `executor` 串接三者)。
- (-) 嚴格禁止橫向呼叫的規定會在某些「跨模組共用工具」場景下造成重複小函式;由 `models` 收容常數是預設解。

### Alternatives Considered
- **A. 全部邏輯塞進 `cli.py`** — 違反 SPEC §6 9 模組切分,且 Gate 1 inspect 會因 docstring [FR-XX] 過於分散而失準。拒絕。
- **B. 採用 plugin 架構(`entry_points`)** — 過度設計,SPEC §3 沒有擴展點需求。拒絕。
- **C. 把 `breaker` / `cache` 合併進 `executor`** — 失去獨立單元測試面與 SAD §2.1 模組清單,違反 SPEC §6。拒絕。

---

## ADR-003: 持久化使用「tmp + `os.replace`」POSIX 原子寫

### Status
Accepted

### Context
SPEC NFR-03 要求 fault-injection(中斷行程、kill -9、磁碟短暫離線)後 `$TASKQ_HOME/*.json` 仍可正確讀回;`run --all` 並發場景下多執行緒同時寫入單一檔。SPEC §5.2 指定三個 JSON 資料檔(`tasks.json` / `breaker.json` / `cache.json`)。

### Decision
所有持久化寫入遵循同一 pattern(由 `store` / `breaker` / `cache` 共用):
1. 序列化目標資料至同目錄的 `*.json.tmp`(`tempfile` 命名避免衝突)。
2. `os.fsync(tmp_fd)` 後 `os.close()`。
3. `os.replace(tmp, real)`(POSIX 原子,跨目錄亦然)。
4. 對應 `threading.Lock` 從序列化開始到 `os.replace` 完成全程持有,每檔獨立 Lock。

損壞偵測:`TaskStore.__init__` 嘗試 `json.load`;遇 `JSONDecodeError` 立即 `exit 1` + stderr `store corrupted`,**不**靜默重建(SPEC §7 明確要求)。

### Consequences
- (+) `os.replace` 在同一 filesystem 內是 POSIX 保證的原子操作,行程中斷只會留下 `*.tmp` 殘檔(下次啟動可清除),目標檔要嘛舊、要嘛新。
- (+) 單一寫入 pattern → NFR-03 驗證只需測一份 atomic-write 邏輯,三個模組同源。
- (+) `run --all` 並發寫入不需擔心半寫狀態。
- (-) `fsync` 增加單次寫入延遲;NFR-01 50ms p95 預算下需審慎使用(只在 `submit` / `update` 觸發,`status` / `list` 為唯讀不受影響)。
- (-) 跨磁碟或跨 mount-point 的 `os.replace` 不保證原子(SPEC §5.2 預設 `$TASKQ_HOME` 在同一 filesystem,於文件與 `.env.example` 加註)。
- 若未來擴充 SQLite,需重新評估 atomic-write contract(預期沿用 `BEGIN IMMEDIATE` 模式)。

### Alternatives Considered
- **A. SQLite 取代 JSON 檔** — 內建 transaction 保證更強,但 SPEC §5.2 明確要求 JSON 檔案儲存,且 SQLite 增加 stdlib 之外的操作複雜度(雖屬 stdlib)。暫不採,留作 v2 選項。
- **B. `shutil.move` 取代 `os.replace`** — `shutil.move` 跨 filesystem 會退化為 copy + remove,失去原子保證。拒絕。
- **C. 直接 `open(real, 'w').write(json.dumps(...))`** — 半寫風險高,違反 NFR-03。拒絕。
- **D. 加上 file lock (`fcntl.flock`)** — POSIX-only,Windows / WSL 行為差異;且 `threading.Lock` 已涵蓋同程序並發需求。跨程序並發不在 SPEC 範圍。拒絕。

---

## ADR-004: 並發模型採 ThreadPoolExecutor + per-store `threading.Lock`

### Status
Accepted

### Context
SPEC FR-02 要求 `run --all` 對所有 PENDING 任務並行執行,共享同一個 `tasks.json`。Python 內建並發選項有 thread(受限 GIL,但 I/O bound 工作適合)、process(隔離性強但狀態共享成本高)、async(生態複雜)。本任務的執行內容是 `subprocess.run` — **I/O bound + 外部程式**,thread 即可。

### Decision
`cli.run_cmd --all` 使用 `concurrent.futures.ThreadPoolExecutor(max_workers=...)` 對 PENDING 任務平行呼叫 `executor.run_task`;每個 storage 物件(TaskStore / Breaker / Cache)持有一把 `threading.Lock`,寫入路徑全程持鎖。

`max_workers` 預設值取自 `TASKQ_MAX_WORKERS` 環境變數(SPEC §5.1,預設 4)。無 process pool / 無 `multiprocessing` / 無 asyncio。

### Consequences
- (+) Thread 建立成本低,`run --all` 啟動延遲可忽略;`subprocess.run` 期間 GIL 自然釋放,I/O bound 場景效益等同多 process。
- (+) 共享 `threading.Lock` 模型單純,debug 與 race 重現門檻低(無 manager / proxy 額外層)。
- (+) 與 ADR-003「同程序寫入受 Lock 保護」邏輯一致,只需一層鎖。
- (-) 受限 GIL:CPU bound 的 redaction 邏輯(SPEC NFR-04)在大量輸出時理論上會被序列化;但實務上 redaction 為 regex 比對,瓶頸在 I/O 而非 CPU。
- (-) 跨程序並發不在保護範圍;若 SPEC 未來要求「背景 daemon 接受多客戶端」,需改 IPC + file lock。
- 無法在 thread 內安裝 SIGINT handler;`KeyboardInterrupt` 由主執行緒處理,中斷時已送出的子行程由 `subprocess.run` 預設行為處理。

### Alternatives Considered
- **A. `multiprocessing.Pool`** — 各行程獨立 GIL,效能優勢明顯,但 state 共享需 manager / file lock,違反 ADR-003「同程序單一 Lock」簡潔模型。拒絕。
- **B. `asyncio` + `asyncio.subprocess`** — 生態複雜,且 `argparse` 同步設計與 async 入口整合度差。拒絕。
- **C. 單執行緒循序執行** — SPEC FR-02 明確要求並發。拒絕。
- **D. 第三方 worker 框架(RQ / Celery)** — 違反 ADR-001 stdlib-only。拒絕。

---

## ADR-005: Circuit Breaker 三態狀態機(CLOSED / OPEN / HALF_OPEN)

### Status
Accepted

### Context
SPEC FR-03 定義斷路器需求:連續失敗 ≥ `TASKQ_BREAKER_THRESHOLD` 後 `run` 拒絕執行並回 `exit 3`;冷卻 `TASKQ_BREAKER_COOLDOWN` 秒後允許單一探測;成功 → CLOSED,失敗 → 重新計時。狀態需持久化以支援跨程序(`[A 程序失敗,B 程序讀到 OPEN]`),SPEC §3.2 明確描述此流程。

### Decision
`breaker.py` 實作三態狀態機:

```
CLOSED ──(failures ≥ threshold)──> OPEN
OPEN   ──(now - opened_at ≥ cooldown)──> HALF_OPEN
HALF_OPEN ──(success)──> CLOSED
HALF_OPEN ──(failure)──> OPEN(opened_at = now)
```

持久化:`breaker.json` 內含 `{state, failures, opened_at}`(SPEC §5.2)。同程序由 `Breaker._lock` 保護,跨程序由 ADR-003 原子寫保證。

`try_acquire()` 是唯一入口:
- CLOSED → True
- OPEN + 未過冷卻 → False
- OPEN + 已過冷卻 → flip to HALF_OPEN,回 True(放行 1 個探測)
- HALF_OPEN → True(已經在放行單一探測的狀態;呼叫端需在完成後 `record_success` / `record_failure`)

### Consequences
- (+) 狀態機邊界封閉,4 條轉換規則可列舉驗證;Gate 1 unit test 可對每條 transition 寫 1 case。
- (+) 跨程序狀態共享不需 IPC:任何程序啟動時 `Breaker()` 載入 `breaker.json`,結束時 flush。
- (+) HALF_OPEN 單一探測語意清楚,不會出現「半開狀態同時湧入 N 個請求」的雷擊。
- (-) 單一探測語意不支援 SPEC 未來若要求「HALF_OPEN 放行 N 個」;需擴展時改 `try_acquire(n=1)`。
- (-) 冷卻時間是「絕對時間」,clock skew 在多主機部署時會失效(SPEC 假設單機本地 CLI,問題不存在)。
- 無後台 timer 主動 close:`try_acquire` 時才做時間比較,故需有觸發才能從 OPEN 轉移。

### Alternatives Considered
- **A. Hystrix-style sliding window(統計最近 N 次失敗率)** — SPEC §FR-03 明確「連續失敗 ≥ threshold」是計數器語意,非比率。拒絕。
- **B. 直接在 `executor` 內做 retry 不另起 `breaker` 模組** — 失去獨立單元測試面 + 跨程序狀態共享能力。拒絕。
- **C. 用 Redis / memcached** — 違反 ADR-001 stdlib-only。拒絕。
- **D. 採 half-open 一次放行 K 個(K > 1)** — 過度設計,SPEC 未要求;HALF_OPEN 設計目的就是「單一探測」降低雷擊。拒絕。

---

## ADR-006: 行程隔離以 `subprocess.run(..., shell=False, shlex.split(command))` 強制

### Status
Accepted

### Context
SPEC NFR-02 明確禁止 `shell=True`,理由是注入風險;SPEC §5.3 列出注入字元黑名單(`; | & $ > < \``)。`taskq` 接受任意 shell 命令字串,需在「保留 shell 表達力」與「避免 shell injection」間取平衡。

### Decision
`executor.run_task` 一律:
```python
subprocess.run(shlex.split(command), shell=False, timeout=..., check=False, capture_output=True)
```
字串分割使用 `shlex.split`(POSIX shell 詞法),不啟動 shell 行程。`cli.submit_cmd` 預檢命令字串是否含 SPEC §5.3 黑名單字元;命中 → `exit 2` + stderr 拒絕訊息(FR-01 拒收)。

### Consequences
- (+) 即使輸入含 backtick / `$()` / `;` 等注入元,也只會被當作單一字串引數傳給目標程式,shell 不介入解析。
- (+) `shlex.split` 提供與 shell 相同的詞法(quoting / escaping),使用者體驗貼近直接打命令。
- (+) `subprocess.run` 預設不會被 shell metacharacter 觸發 → NFR-02「0 `shell=True` 使用率」自然達成。
- (-) 失去 shell pipeline / glob / 變數展開能力(例如 `taskq submit "ls *.txt"` 不展開) — SPEC 沒要求,且視為「更安全的預設」。
- (-) Windows shell 詞法與 `shlex` 不完全一致(SPEC 假設 POSIX / WSL);若跨平台 Windows 需求出現,需改 `shlex` 替代品或文件宣告 POSIX-only。
- 拒絕黑名單是「粗略過濾」,最終防線是 `shell=False` 本身(SPEC §5.3 設計意圖)。

### Alternatives Considered
- **A. 啟用 `shell=True` + 依賴 shlex.quote 包裹每個引數** — 任何一個遺漏就破口。拒絕。
- **B. 採自製 mini-shell parser** — 工作量遠超 `shlex`,效益零。拒絕。
- **C. 完全禁止特殊字元(白名單)** — 太嚴苛,會讓 `taskq submit "echo a;b"` 等合法情境失效。拒絕。
- **D. 拒絕 `; | & $ > < \`` 黑名單但允許 `shell=False` 不用** — 黑名單只為「使用者自我警示」,最終不依賴它。採納,目前實作即如此。

---

## ADR-007: 結果快取以 `sha256(command) + TTL` 為鍵

### Status
Accepted

### Context
SPEC FR-04 要求對已完成任務的結果做 TTL 快取;`run --cached` 命中快取時不執行子行程,直接回放。`taskq` 沒有「呼叫端傳遞 cache key」的介面,因此 key 必須由命令字串本身衍生。

### Decision
`cache.py` 採以下規則:
- **鍵**:`sha256(command.encode('utf-8')).hexdigest()`(命令字串 utf-8 位元組的 SHA-256)。
- **值**:`CacheEntry{exit_code, stdout_tail, cached_at}`(對齊 SPEC §2.4 介面)。
- **TTL**:`TASKQ_CACHE_TTL` 秒(預設 3600,SPEC §5.1),`Cache.get(key)` 發現 `(now - cached_at) > TTL` 視為 miss 並丟棄。
- **寫入時機**:僅任務 `status == DONE` 時 `cache.put`(`FAILED` / `TIMEOUT` 不快取,避免重試時污染)。
- **持久化**:`cache.json` 內含 `{signature: CacheEntry}`,ADR-003 原子寫。

### Consequences
- (+) 命令字串天然決定 cache key,無需使用者額外標註;同一命令兩次執行可命中(SPEC FR-04 預期)。
- (+) SHA-256 為單向,key 不洩漏命令內容(對 `cache.json` 有讀權限的觀察者)。
- (+) TTL 過期即丟棄 → 陳舊結果不會無限存活。
- (-) 命令字串含「時間敏感」字串(例如 `$(date)`)時,因 cache 命中不會重算 — 視為使用者預期,文件加註。
- (-) 大量不同命令會撐大 `cache.json`;SPEC 沒要求 LRU eviction,目前「TTL 到期自然淘汰」是唯一機制。若未來需要容量上限,需擴充。
- (-) `sha256` 對小字串(< 1KB)成本可忽略;極度 batch 場景下若成為瓶頸,可改 `blake2b(digest_size=16)`。

### Alternatives Considered
- **A. 用 `command` 字串本身當 key(JSON dict 內以字串為鍵)** — 長字串 + Unicode 編碼一致性風險,SHA-256 統一為 hex 更穩。採 ADR 方案。
- **B. 用 `mtime` 或檔案 hash 當 key** — `taskq` 的命令是字串,無關檔案。拒絕。
- **C. 不快取失敗 / TIMEOUT** — 採 ADR 方案(SPEC FR-04 隱含)。
- **D. LRU eviction** — SPEC 沒要求,過度設計。拒絕。

---

## ADR-008: 資料模型以 `@dataclass` + `Enum` 為主

### Status
Accepted

### Context
SPEC §2.4 列出資料形狀:`Task` / `Status` / `BreakerState` / `CacheEntry`。`Task` 欄位較多(11 個欄位),`Status` 是封閉集合(PENDING / RUNNING / DONE / FAILED / TIMEOUT)。需要序列化(`json.dump`)、型別安全(高階介面傳遞)、可讀性高(維護性 NFR-05)。

### Decision
`models.py`:
- `Task` / `BreakerState` / `CacheEntry` 用 `@dataclass`(Python 3.7+ 標準庫)。
- `Status` 用 `enum.Enum`,序列化時轉字串(`status.value`)。
- `Task` 額外提供 `to_dict() / from_dict()` helper,給 `store` 與 `cli --json` 輸出使用。

### Consequences
- (+) `@dataclass` 自動生成 `__init__` / `__repr__` / `__eq__`,程式碼精簡且欄位即文件。
- (+) `Enum` 在型別層級防止 `Status = "DONE"` 字串飄移;`from_dict` 集中處理字串 → Enum 轉換。
- (+) 序列化 / 反序列化集中於 helper,符合 NFR-05「資料形狀單一入口」。
- (-) `@dataclass` 不可變性需 `frozen=True` 才達成(目前 `Task` 是 mutable,因為執行期間欄位需被 `executor` 推進)。明確選擇,日後若要 immutable 需評估 executor 的 in-place 更新 pattern。
- (-) `Enum` 反序列化需 try/except;若 `status.json` 出現未定義值,`from_dict` 需決定 fail-fast 還是 fallback — 採 fail-fast(對齊 SPEC §7「不靜默重建」精神)。

### Alternatives Considered
- **A. `pydantic.BaseModel`** — 違反 ADR-001 stdlib-only。拒絕。
- **B. `attrs` / `cattrs`** — 同上。拒絕。
- **C. 純 dict / TypedDict** — 失去 `__eq__` 與 `__repr__`,debug 體驗差。拒絕。
- **D. `frozen=True` 的 `@dataclass(frozen=True)`** — `executor` in-place 更新需重寫成「回傳新 Task」風格,工作量高;目前 `Task` 單一擁有者(被 store 管理)暫不採。

---

## ADR-009: CLI 採 `argparse` + 全域 `--json` + 退出碼表

### Status
Accepted

### Context
SPEC §3.3 列出 5 個子命令(`submit` / `run` / `status` / `list` / `clear`),SPEC §3.4 列出 5 種退出碼(0 成功 / 1 內部 / 2 參數 / 3 breaker / 4 timeout)。`taskq` 同時要支援「人讀」與「機讀」輸出,後者要可被 shell pipeline 串接。本 ADR 直接落實 **FR-05(CLI 整合)** 的可觀察契約:argparse 子命令分派 + `--json` 機讀輸出 + 5 值退出碼表對應 SPEC §3.3 / §3.4;`__main__.py` 為 FR-05 進入點(SAD §2.2)。

### Decision
- **Parser**:`argparse` 標準庫,父解析器加 `--json` 全域 flag,5 個子命令各為 `subparsers.add_parser(...)`。
- **輸出**:`--json` 開啟時所有 print 走單行 JSON;否則走人讀格式(表格 / 多行)。
- **退出碼**:`cli.main()` 最後 `sys.exit(<code>)`,各 handler 回傳 int(0 / 1 / 2 / 3 / 4),handler 內 raise 不對應退出碼的例外 → 轉 exit 1。
- **錯誤輸出**:退出碼 ≥ 2 的訊息一律走 `print(..., file=sys.stderr)`,不污染 stdout JSON 輸出。

### Consequences
- (+) `argparse` 自動處理 `--help` 與錯誤訊息(子命令缺引數 / 未知選項),減少手寫錯誤處理。
- (+) `--json` 單一全域 flag → 使用者只需記一個語法;輸出格式集中在 helper,易測試。
- (+) 退出碼語意清楚,可被 `set -e` shell / systemd unit / 上層 orchestrator 監控。
- (-) `argparse` 在「短選項 / 自動補完」體驗略遜於 `click`;但換來零依賴(ADR-001)。
- (-) 子命令分派的 `if/elif` 鏈需手動維護;目前 5 個命令規模可接受,超過 10 個時考慮 table dispatch。
- 退出碼表是公開契約 → 之後變更需要 deprecation 流程(目前無此需求)。

### Alternatives Considered
- **A. `click`** — 違反 ADR-001。拒絕。
- **B. `typer`** — 同上,依賴 click。拒絕。
- **C. 自行解析 `argv[1:]`** — 重造 `argparse` 輪子,得不償失。拒絕。
- **D. 不分層(全部走 stdin JSON)** — 違反 SPEC §3.3 定義的 5 個子命令語法。拒絕。

---

## ADR-010: 敏感輸出以 regex 黑名單整行 redact

### Status
Accepted

### Context
SPEC NFR-04 要求對 stdout_tail / stderr_tail 套用 redaction,避免 token / API key 等祕密外洩到 `$TASKQ_HOME/tasks.json` 與 `--json` 輸出。Pattern 列表是 `sk-[A-Za-z0-9_-]{8,}` 與 `token=\S+`(SPEC §4)。

### Decision
`executor.run_task` 在呼叫 `store.update(task)` 之前對 `task.stdout_tail` / `task.stderr_tail` 各行套用 `redact(line)`:
- `re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", line)`
- `re.sub(r"token=\S+", "token=[REDACTED]", line)`
- 命中整行 → 整行替換為 `[REDACTED]`(避免部分遮罩洩漏長度資訊)。

redaction 在 `store.update` 之前執行(SPEC §4 設計意圖),寫入磁碟 / 輸出 `--json` 都不再含原始 secret。

### Consequences
- (+) 簡單 regex 即可覆蓋 SPEC 列出的兩類樣本(SPEC NFR-04 驗證:「命中率 100%」)。
- (+) 整行 `[REDACTED]` 語意清楚,debug log 易讀;同時避免「保留前後 4 字元」之類的長度側通道。
- (+) 集中於 `executor.run_task` 內,呼叫端不需各自處理。
- (-) regex 黑名單永遠落後於新型 secret 格式(例如 JWT、Bearer、AWS access key);SPEC 沒要求擴充,留 v2 議題。
- (-) 「整行替換」可能遮蔽非敏感資訊;若日後需要更細粒度,需擴展為「命中片段替換」。
- (-) redaction 為 regex 比對,極大量輸出時有 CPU 成本(ADR-004 已說明,GIL 釋放足以吸收)。

### Alternatives Considered
- **A. 使用 secret-detection 函式庫(`detect-secrets`)** — 違反 ADR-001 stdlib-only;且 `detect-secrets` 需要 baseline 訓練,不符合 CLI 即時使用情境。拒絕。
- **B. 寫入磁碟前 redact(在 store 內)** — 分散職責,失去「單一 redaction 入口」可見性。採 ADR 方案(集中在 `executor`)。
- **C. 僅 redact 命中片段(例如 `sk-XXXX****`)而非整行** — 增加長度側通道洩漏風險。拒絕。
- **D. 完全不 redact(仰賴使用者自負)** — 違反 SPEC NFR-04。拒絕。

---

## ADR-011: 設定以 8 個 `TASKQ_*` 環境變數為唯一來源

### Status
Accepted

### Context
SPEC §5.1 列出 8 個環境變數(`TASKQ_HOME` / `TASKQ_TASK_TIMEOUT` / `TASKQ_RETRY_LIMIT` / `TASKQ_BACKOFF_BASE` / `TASKQ_BREAKER_THRESHOLD` / `TASKQ_BREAKER_COOLDOWN` / `TASKQ_CACHE_TTL` / `TASKQ_MAX_WORKERS`),無設定檔(無 `.toml` / `.yaml` / `.ini`)。

### Decision
- 所有設定讀取集中於 `config.py`,每個變數一個 `get_xxx()` helper,內含「讀 env → 型別轉換 → 套用預設值 → 範圍檢查」四步。
- 型別轉換失敗(例如 `TASKQ_TASK_TIMEOUT=abc`)→ 啟動時 `exit 1` + stderr 明確訊息(fail-fast,符合 SPEC §7)。
- 預設值對齊 SPEC §5.1;`.env.example` 在 repo 根目錄逐一列舉 8 vars + 註解。

### Consequences
- (+) 設定與程式碼完全解耦 → 部署時只需 export env,無檔案 IO 風險。
- (+) 集中 8 個 helper → 變更預設值或新增檢查只需改一處。
- (+) 環境變數在 shell / systemd / docker / k8s 都通用,符合 NFR-06。
- (-) 無設定檔 → 複雜多專案環境下使用者需在每次啟動前 export;SPEC 沒要求 config file,接受此限制。
- (-) 環境變數的「8 個」是 hard cap;若 SPEC 未來加到第 9 個,需改 `config.py` + `.env.example` + SPEC §5.1(預期是同步變更)。
- 沒有 schema 驗證函式庫(無 `pydantic`)→ 自製輕量 helper 是當前可接受 trade-off。

### Alternatives Considered
- **A. 使用 `.toml` / `.yaml` / `.ini` 設定檔** — SPEC §5.1 明確「env-only」,違規。拒絕。
- **B. 設定 + CLI flag** — 雙來源,優先順序混亂。拒絕。
- **C. `dynaconf` / `pydantic-settings`** — 違反 ADR-001。拒絕。
- **D. 8 個變數分散在各自模組讀取** — 失去 SSOT,debug 與環境切換成本高。拒絕。

---

## ADR-012: 跨程序狀態以 JSON 檔 + atomic write 取代 IPC

### Status
Accepted

### Context
SPEC §3.2 描述「[A 程序 run 失敗 → 寫 breaker.json;B 程序 run → 讀 breaker.json 拒絕]」的跨程序協作模式。實作選項有:Socket / Named pipe / Shared memory / File。各有取捨。

### Decision
跨程序狀態統一以「JSON 檔 + atomic write + Lock(同程序內)」承載。`breaker.json` 是唯一跨程序狀態;`tasks.json` / `cache.json` 為本程序查詢 / 寫入(不假設跨程序一致性,SPEC §3 未要求跨程序 task 共享)。

### Consequences
- (+) 與 ADR-003 atomic-write 邏輯共用,實作簡潔。
- (+) 任何「外部工具」可直接 `cat $TASKQ_HOME/breaker.json` debug,符合 CLI 哲學。
- (+) 零 IPC 設定成本(無 socket 路徑 / 權限議題)。
- (-) 跨程序讀取沒有「通知機制」,B 程序只能輪詢(本設計下 B 程序只在 `try_acquire` 時讀一次,符合 SPEC §3.2 流程)。
- (-) 多主機部署下不適用(SPEC 假設單機,問題不存在)。
- 沒有比 JSON 更高吞吐的需求(SPEC §3 規模為「任務佇列」非「訊息流」)。

### Alternatives Considered
- **A. Unix domain socket** — 額外監聽 / 連線管理成本,SPEC 規模不需要。拒絕。
- **B. D-Bus / systemd bus** — 違反 ADR-001;Linux-only。拒絕。
- **C. Shared memory + semaphore** — 跨程序重啟後狀態消失,違反「B 程序需看到 A 留下的 OPEN」。拒絕。
- **D. SQLite WAL 模式** — stdlib 內有 `sqlite3`,但 SPEC §5.2 明確要求 JSON 檔,違反契約。拒絕(留 v2 選項)。

---

## ADR-013: 退出碼語意固定為 5 值(0/1/2/3/4)

### Status
Accepted

### Context
SPEC §3.4 + §7 列出 5 種退出碼,語意對應不同錯誤類別。`taskq` 沒有自訂退出碼擴充機制,SPEC 也未預留擴充空間。

### Decision
`cli.main()` 統一出口碼表:
| 碼 | 語意 | 觸發範例 |
|----|------|---------|
| 0 | 成功 | 所有正常路徑 |
| 1 | 內部錯誤 | JSON 損壞、未預期例外、redaction regex 編譯失敗 |
| 2 | 參數 / 業務輸入錯誤 | 注入字元、空命令、超長、重名、unknown task id |
| 3 | 斷路器 OPEN | `Breaker.try_acquire` 回 False |
| 4 | timeout | `subprocess.run` `TimeoutExpired` 在單任務模式觸發 |

`run --all` 在任何一個任務 timeout 時不立即 exit 4(會干擾批次),改為把該任務標 `TIMEOUT` 並繼續;結束時 exit 0(全部完成或失敗已記錄)或 exit 3(breaker open 中斷整批)。

### Consequences
- (+) 5 值語意清楚,可被 `set -e` / orchestrator 直接判讀。
- (+) `run --all` 與單任務 `run` 退出碼語意有差異,但對應不同使用情境(batch vs single)。
- (-) 5 值是 hard cap;若日後需要區分「部分成功」等新語意,需重新檢視契約。
- (-) exit 1 同時承載「內部錯誤」與「資料損壞」,debug 時需讀 stderr 區分(可接受)。

### Alternatives Considered
- **A. 採用 sysexits.h 風格(64-78 區段)** — POSIX 慣例但對 CLI 使用者不友善,且 `taskq` 規模不需要這麼細。拒絕。
- **B. 全部錯誤統一 exit 1** — 失去「參數錯誤 vs 系統錯誤」區分,`set -e` 無法精準重試。拒絕。
- **C. 退出碼含 sub-error 子碼(例如 4.1)** — shell 不支援。拒絕。
- **D. 失敗時輸出 JSON `{"error_code": "BREAKER_OPEN"}`** — 可與退出碼並行,但 SPEC §3.3 沒要求,留 v2 議題。

---

## ADR-014: NFR-01 performance 預算採「純本地操作 + 單檔原子寫」

### Status
Accepted

### Context
SPEC NFR-01 要求 `submit` 與 `status` 在 100 iter 下 p95 < 50ms(SPEC §11 + §4.1)。這兩個 CLI 子命令的特性是「**純本地操作**,不觸 subprocess,單一檔案原子寫」。NFR-01 為橫切性 NFR — 不屬任何單一 FR,而是 `cli.submit_cmd` + `cli.status_cmd` + `TaskStore.add` / `get` 共同承擔。

### Decision
NFR-01 採「**單檔原子寫** + **避免 fsync(在 submit)** + **純 dict 操作**」組合:
- `submit` 路徑:`validate(command)` → 建構 `Task` dataclass → `json.dump([new_task, *existing])` → `os.replace`。**不**呼叫 `os.fsync`(提交階段 NFR-01 預算緊,且 `os.replace` 在同一 fs 下已足夠 atomic)。
- `status` 路徑:`json.load(tasks.json)` → dict lookup → 序列化結果;**零寫入,零 subprocess**。
- `cache.json` / `breaker.json` 在 `submit` / `status` 路徑**不**觸發(僅 `run` 觸發)。

驗證:`tests/perf/` 用 `pytest-benchmark` 跑 100 iter,斷言 p95 < 50ms。

### Consequences
- (+) 不引入 async / process pool 即可達標(純本地操作,單 thread)。
- (+) `submit` 與 `status` 職責分離,perf 預算不互相牽制。
- (+) 「不觸 subprocess」語意在 `cli` 層即可靜態驗證(grep `subprocess` in submit/status code path = 0)。
- (-) 放棄 `fsync` 在 `submit` 階段的強持久性 → 系統當機可能遺失最近一次 submit(SPEC §5.2 沒要求 submit fsync,屬可接受 trade-off)。
- (-) 橫切 NFR 沒有單一 owner 模組 → 後續若其他命令也需套用 NFR-01 預算,需在 `cli` 層加 perf decorator / benchmark fixture(目前未實作,留 v2)。
- 若 SPEC 未來要求 `submit` 也 fsync,需重新評估 NFR-01 預算(可能放寬至 100ms 或允許 batch fsync)。

### Alternatives Considered
- **A. 全路徑 `fsync`(在 store.add 內無條件呼叫)** — 拉高 `submit` p95,違反 NFR-01。拒絕。
- **B. 改用 SQLite(走 WAL,fsync 開銷低於 JSON 重寫整檔)** — 違反 SPEC §5.2 JSON 契約。拒絕(留 v2)。
- **C. 對 `tasks.json` 採 append-only log + 週期 compact** — 過度設計,SPEC 規模不需要。拒絕。
- **D. 完全不做 perf 監控,仰賴人工觀察** — 違反 NFR-01 + SPEC §11 量化門檻。拒絕。

*文件版本:對齊 SPEC.md v3.0.0 + SAD.md v1 | 2026-07-10*

---

## FR / NFR traceability matrix (追溯表)

> 對齊 SAD.md §2.2(FR → 模組)與 §4(NFR Handling),以表格形式把 5 個 FR 與 6 個 NFR 對應回 owning ADR — 即 traceability matrix 的 requirement → decision 對應關係。供 `check_nfr_adr_coverage` 等下游 checker 結構化比對,避免 Sync 階段誤判;每一行代表 SRS 內一條 requirement 經 specification → design → implementation 的可追溯節點。

### NFR → ADR(traceability matrix row)

| NFR | 類別 | 摘要 | Owning ADR(s) |
|-----|------|------|---------------|
| NFR-01 | performance | `submit` + `status` 100 iter p95 < 50ms | ADR-003, ADR-014 |
| NFR-02 | security | 0 `shell=True` 使用率 + 注入字元黑名單 | ADR-006, ADR-009 |
| NFR-03 | reliability | 持久層 fault-injection 後可正確讀回 + 跨程序狀態共享 | ADR-003, ADR-005, ADR-012 |
| NFR-04 | security | stdout_tail / stderr_tail redaction(整行 `[REDACTED]`) | ADR-006, ADR-010 |
| NFR-05 | maintainability | 公開函式 docstring 強制含 `[FR-XX]` 引用 | ADR-001, ADR-008 |
| NFR-06 | deployability | 8 個 env vars + runtime 零外部依賴 | ADR-001, ADR-011 |

### FR → 對應決策(traceability matrix row)

| 需求編號 | 摘要 | Owning 決策 | Owning 模組(SAD §2.1) |
|----|------|---------------|------------------------|
| FR-01 | 任務提交與驗證 | ADR-002, ADR-009, ADR-011 | `cli.submit_cmd` → `store.add_task` |
| FR-02 | 任務執行器(`run` / `run --all`) | ADR-002, ADR-004, ADR-006, ADR-009 | `executor.run_task` · `cli.run_cmd` · `store.update_task` |
| FR-03 | 重試與斷路器 | ADR-005, ADR-006, ADR-009 | `breaker.try_acquire / record_*` · `executor.run_task` |
| FR-04 | 結果 TTL 快取 | ADR-007, ADR-009 | `cache.get / put` · `executor.run_task` |
| FR-05 | CLI 整合(入口 + 子命令 + 退出碼) | ADR-002, ADR-009, ADR-013 | `__main__.py` · `cli.main` |

### 決策 → 全域引用(traceability matrix column view)

| 決策編號 | 對應需求 | 對應模組 | 對齊 SRS / SPEC |
|-----|---------------|----------|------------------|
| ADR-001 | NFR-05, NFR-06 | 全 runtime | SPEC §5 |
| ADR-002 | FR-01..05(模組邊界) | 全部 9 模組 | SPEC §6 |
| ADR-003 | NFR-01, NFR-03 | `store` · `breaker` · `cache` | SPEC §5.2 |
| ADR-004 | FR-02 | `cli.run_cmd` · `executor.run_task` | SPEC §3.3 |
| ADR-005 | FR-03, NFR-03 | `breaker.py` | SPEC §3.4 |
| ADR-006 | FR-02, NFR-02, NFR-04 | `executor.run_task` | SPEC §5.3 + §4 |
| ADR-007 | FR-04 | `cache.py` | SPEC §2.4 |
| ADR-008 | NFR-05 | `models.py` | SPEC §2.4 |
| ADR-009 | FR-01..05, NFR-02 | `cli.py` · `__main__.py` | SPEC §3.3 + §3.4 |
| ADR-010 | NFR-04 | `executor.run_task` | SPEC §4 |
| ADR-011 | NFR-06 | `config.py` | SPEC §5.1 |
| ADR-012 | NFR-03 | `breaker.py` + 持久層 | SPEC §3.2 |
| ADR-013 | — (cross-cutting 退出碼表) | `cli.main` | SPEC §3.4 + §7 |
| ADR-014 | NFR-01 | `cli.submit_cmd` + `cli.status_cmd` + `TaskStore` | SPEC §11 + §4.1 |
