# SRS - taskq (Software Requirements Specification)

> Project: taskq (本地任務佇列 CLI)
> Version: v2.0.0
> Date: 2026-06-17
> Source of truth: SPEC.md v2.0.0 (canonical_spec declared in PROJECT_BRIEF.md)
> Phase: 1 — Requirements Specification
> Authoring mode: INGESTION (100% transcription from SPEC.md, no invention)

---

## 1. Requirements Overview

`taskq` 是一個本地任務佇列命令列工具(CLI),以 Python 3.11 標準函式庫實作(零 runtime 外部依賴)。使用者透過 `python -m taskq` 入口提交 shell 命令為任務,框架以受控方式執行 subprocess(具 timeout 與自動重試),並提供任務狀態查詢。整體目標是把批次/重試式本地命令執行從腳本中抽離,提供一致的錯誤碼、原子持久化與 secret redaction。

**核心能力**:
- 任務提交(FR-01) — 注入字元黑名單 + 長度上限 + 原子寫入
- 任務執行(FR-02) — 受控 subprocess(`shell=False` 強制)+ timeout + 自動重試
- CLI 與查詢(FR-03) — `submit` / `run` / `status` / `list` / `clear` + `--json` 旗標 + 一致 exit codes

**非功能性目標**:
- 效能(NFR-01)— `submit + status` 100 次 p95 < 50ms
- 安全(NFR-02)— 全 codebase 禁用 `shell=True`;注入字元黑名單必有測試覆蓋
- 可靠性(NFR-03)— `tasks.json` 原子寫;`stdout_tail` / `stderr_tail` 落盤前 secret redaction

**角色與利害關係人**:
- 主要使用者:需要批次執行/重試本地命令的開發者
- 方法論審查者:harness-methodology 維護者(以本專案 P1-P8 工件評估框架健康度)
- 專案擁有者:Johnny

---

## 2. Functional Requirements

> 「Implementation Function (est.)」欄位為對應 FR 之預期 Python 模組/函式路徑(**非 SPEC.md 內容,為 SRS 自行估計以引導 P2 架構設計**);待 P2 SAD.md 確認後如有調整,需在 ADR 紀錄變更。

| ID | Requirement Description | Implementation Function (est.) | Verification Method |
|----|------------------------|--------------------------------|---------------------|
| FR-01 | 任務模型與持久化:`taskq submit "<command>"`,命令驗證(非空/長度/注入字元),通過後產生 task id(uuid4 前 8 hex)並原子寫入 `$TASKQ_HOME/tasks.json` | `taskq.store.submit_task` / `taskq.cli.submit` | 單元測試驗證四條驗證規則、task id 格式、原子寫;整合測試驗證 CLI exit 2 路徑與 `tasks.json` 損壞時 exit 1 |
| FR-02 | 任務執行與重試:`taskq run <id>`,以 `subprocess.run(shlex.split(...), capture_output=True, text=True, timeout=...)` 執行,`pending → running → done/failed/timeout` 狀態機,失敗/timeout 自動重試至 `TASKQ_RETRY_LIMIT` 次 | `taskq.executor.run_task` / `taskq.cli.run` | 單元測試驗證狀態機、退出碼對應、`TimeoutExpired` 路徑、重試上限;整合測試驗證 exit 4(timeout)路徑 |
| FR-03 | CLI 整合與查詢:`submit` / `run` / `status` / `list` / `clear` 子命令 + `--json` 全域旗標 + exit codes(0/2/4/1) | `taskq.cli.main` | 整合測試驗證每個子命令的 happy path、unknown task id(→ exit 2)、`--json` 機器可讀輸出 |

### FR-01 詳細條款

**命令**:`taskq submit "<command>"`

**驗證規則(任一違反 → exit 2 + stderr 錯誤訊息,不得寫入存儲)**:

| 規則 | 條件 |
|------|------|
| 非空 | 命令為空或全空白 → 拒絕 |
| 長度 | 命令 > 1000 字元 → 拒絕 |
| 注入字元 | 命令含 `;` `|` `&` `$` `>` `<` `` ` `` 任一 → 拒絕(對應 NFR-02) |

**通過驗證後**:
- 產生 task id(uuid4 前 8 hex)
- 狀態 `pending`,記錄 `command`、`created_at`
- 原子寫入 `$TASKQ_HOME/tasks.json`(tmp + `os.replace`)
- `tasks.json` 損壞(非法 JSON)→ 啟動偵測 → **exit 1**,stderr 輸出 `store corrupted`(不得靜默重建)

### FR-02 詳細條款

**命令**:`taskq run <id>`

**執行細節**:
- 以 `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` 執行
- **任何路徑不得使用 `shell=True`**(對應 NFR-02)

**狀態機**:`pending → running → done | failed | timeout`
- exit 0 → `done`
- 非 0 → `failed`
- `TimeoutExpired` → `timeout`

**結果欄位**:`exit_code`、`stdout_tail`(末 2000 字元)、`stderr_tail`(末 2000 字元)、`duration_ms`、`finished_at`

**重試行為**:`run` 結果為 `failed`/`timeout` 時自動重試,上限 `TASKQ_RETRY_LIMIT` 次(預設 2)

**錯誤處理**:
- 單一任務模式下 `timeout` 結果 → **exit 4**
- 其他未預期例外 → exit 1(不得以裸 `except:` 吞噬)

### FR-03 詳細條款

**入口**:`python -m taskq`(argparse 子命令)

| 命令 | 行為 |
|------|------|
| `submit "<cmd>"` | 委派至 FR-01 |
| `run <id>` | 委派至 FR-02 |
| `status <id>` | 輸出該任務全欄位;unknown id → **exit 2** + stderr `unknown task: <id>` |
| `list` | 列出全部任務(id + status + command 前 50 字元) |
| `clear` | 清空 `$TASKQ_HOME/tasks.json` |

**全域旗標**:`--json` — 機器可讀輸出(單行 JSON)

**Exit codes**(全 CLI 統一):
- `0` — 成功
- `2` — 輸入驗證錯誤(含 unknown task id)
- `4` — 任務 timeout
- `1` — 其他內部錯誤

---

## 3. Non-Functional Requirements (NFR)

| ID | Type | Requirement | Test Method |
|----|------|-------------|-------------|
| NFR-01 | performance | `submit` + `status` 組合操作 100 次 p95 < 50ms(不含 subprocess 執行) | benchmark 測試:100 次 `submit → status` 循環,量測 p95 |
| NFR-02 | security | 全 codebase 禁用 `shell=True`;FR-01 注入字元黑名單必須有測試覆蓋 | 靜態掃描(grep / semgrep 自訂規則)確認 `shell=True` 不存在;FR-01 測試覆蓋六個注入字元每個 |
| NFR-03 | reliability | `tasks.json` 原子寫(進程中斷後仍為合法 JSON);`stdout_tail`/`stderr_tail` 落盤前過濾 `(sk-[A-Za-z0-9_-]{8,}\|token=\S+)` 整行以 `[REDACTED]` 取代 | 整合測試:寫入後中途 kill 進程,驗證檔案仍為合法 JSON;secret 注入測試確認落盤內容不含原 secret |

### 風險緩解對映(SPEC.md §4 內附)

| 風險 | 緩解 |
|------|------|
| R1 並發/中斷寫入損壞 | NFR-03(原子寫) |
| R2 subprocess 懸掛 | FR-02 timeout |
| R3 secret 落盤洩漏 | NFR-03(redaction) |

---

## 4. Constraints

- **語言**:Python 3.11,**runtime 零外部依賴**(僅標準函式庫;測試工具由開發環境提供)
- **形態**:命令列工具,`python -m taskq` 進入
- **3 個 FR 為 pre-defined 且不可變**(FR-01..FR-03),不得新增或修改範圍
- **3 個 NFR 為 pre-defined 且不可變**(NFR-01..NFR-03)
- **3 個 TASKQ_* 環境變數為固定配置**:`TASKQ_HOME` / `TASKQ_TASK_TIMEOUT` / `TASKQ_RETRY_LIMIT`(見 §5)
- **SPEC.md 為 single source of truth**;無 overlay 文件可修訂之
- **Out of scope**:daemon/服務化、遠端執行、非 JSON 持久化後端、斷路器、快取、並發

---

## 5. Glossary

| Term | Definition |
|------|------------|
| task id | uuid4 取前 8 個 hex 字元(共 8 字元),例如 `a1b2c3d4` |
| pending | 任務已提交,尚未執行 |
| running | 任務正在被 `run` 處理中 |
| done | 子進程 exit 0 |
| failed | 子進程 exit 非 0 |
| timeout | 子進程超過 `TASKQ_TASK_TIMEOUT` 未結束 |
| atomic write | 寫入到 `tasks.json.tmp` 後以 `os.replace` 取代原檔(同檔案系統下保證 atomic) |
| redaction | 把 stdout/stderr 中符合 `(sk-[A-Za-z0-9_-]{8,}\|token=\S+)` 整行以 `[REDACTED]` 取代 |
| exit code | 0=成功, 2=輸入驗證錯誤, 4=任務 timeout, 1=其他內部錯誤 |

---

## 6. Configuration

| 變數 | 預設 | 說明 |
|------|------|------|
| `TASKQ_HOME` | `.taskq` | 資料檔目錄(存放 `tasks.json`) |
| `TASKQ_TASK_TIMEOUT` | `10.0` | 單任務 subprocess timeout(秒) |
| `TASKQ_RETRY_LIMIT` | `2` | 失敗自動重試上限 |

所有設定由 `taskq.config` 統一讀取,`.env.example` 完整宣告三個變數。

---

## 7. FR Block (machine-readable)

<!-- FR:START -->
```json
{
  "version": "1.0",
  "created_at": "2026-06-17",
  "phase": 1,
  "project": "taskq",
  "functional_requirements": [
    {
      "id": "FR-01",
      "description": "任務模型與持久化:submit 命令驗證(非空/長度/注入字元黑名單),通過後產生 task id 並原子寫入 tasks.json;tasks.json 損壞時 exit 1 不靜默重建",
      "implementation_functions": ["taskq.store.submit_task", "taskq.cli.submit"],
      "verification_method": "unit + integration: validation rules, id format, atomic write, store-corruption detection"
    },
    {
      "id": "FR-02",
      "description": "任務執行與重試:run 以 subprocess.run(shlex.split, shell=False, timeout) 執行,狀態機 pending→running→done/failed/timeout,失敗/timeout 自動重試至 TASKQ_RETRY_LIMIT",
      "implementation_functions": ["taskq.executor.run_task", "taskq.cli.run"],
      "verification_method": "unit + integration: state machine, exit code mapping, TimeoutExpired, retry cap, exit 4 on timeout"
    },
    {
      "id": "FR-03",
      "description": "CLI 整合與查詢:argparse 子命令 submit/run/status/list/clear + --json 全域旗標 + 統一 exit codes(0/2/4/1)",
      "implementation_functions": ["taskq.cli.main"],
      "verification_method": "integration: each subcommand happy path, unknown id → exit 2, --json machine-readable"
    }
  ],
  "non_functional_requirements": [
    {
      "id": "NFR-01",
      "type": "performance",
      "description": "submit + status 組合操作 100 次 p95 < 50ms(不含 subprocess 執行)",
      "test_method": "benchmark test measuring p95 latency over 100 submit+status cycles"
    },
    {
      "id": "NFR-02",
      "type": "security",
      "description": "全 codebase 禁用 shell=True;FR-01 注入字元黑名單必須有測試覆蓋(六個注入字元每個)",
      "test_method": "static scan (semgrep custom rule) for shell=True absence + unit tests for each injection char"
    },
    {
      "id": "NFR-03",
      "type": "reliability",
      "description": "tasks.json 原子寫(tmp + os.replace);stdout_tail/stderr_tail 落盤前 secret redaction(整行 sk-/token= → [REDACTED])",
      "test_method": "integration: kill mid-write → still valid JSON; secret injection → stored content scrubbed"
    }
  ]
}
```
<!-- FR:END -->

---

## 8. Cross-Cutting Test Requirements (TEST_INVENTORY source)

> 測試名稱在 TEST_INVENTORY.yaml 中宣告為 P1 naming authority,並由 Phase 2 `derive_test_cases.md` 引入 TEST_SPEC.md。

### API Completeness(每個 CLI 子命令必須有以下測試)
- 正常流程(exit 0)
- 輸入驗證錯誤(exit 2:FR-01 三條規則、FR-03 unknown task id)
- 任務 timeout(exit 4:FR-02)
- 內部錯誤(exit 1:store corrupted 等)

**對應測試清單**(由 TEST_INVENTORY.yaml 詳細列舉):
- [ ] `test_fr01_submit_valid_command_returns_zero`
- [ ] `test_fr01_submit_empty_command_returns_two`
- [ ] `test_fr01_submit_whitespace_command_returns_two`
- [ ] `test_fr01_submit_long_command_returns_two`
- [ ] `test_fr01_submit_injection_chars_returns_two`(parametrized over 6 chars)
- [ ] `test_fr01_submit_produces_uuid4_id_format`
- [ ] `test_fr01_store_corruption_returns_one`
- [ ] `test_fr02_run_executes_subprocess_with_shell_false`
- [ ] `test_fr02_run_exit_zero_yields_done`
- [ ] `test_fr02_run_nonzero_yields_failed`
- [ ] `test_fr02_run_timeout_yields_timeout_and_exit_four`
- [ ] `test_fr02_run_failed_retries_up_to_limit`
- [ ] `test_fr02_run_retry_limit_respected`
- [ ] `test_fr03_status_unknown_id_returns_two`
- [ ] `test_fr03_list_returns_all_tasks`
- [ ] `test_fr03_clear_empties_store`
- [ ] `test_fr03_json_flag_emits_single_line_json`

### Security Red Team
- [ ] `test_redteam_prompt_injection_via_submit_blocked`(每個注入字元)
- [ ] `test_redteam_secret_in_stdout_redacted_before_persist`
- [ ] `test_redteam_secret_in_stderr_redacted_before_persist`
- [ ] `test_redteam_shell_true_absent_in_codebase`

### KPI Gates
- [ ] `test_kpi_p95_submit_status_under_50ms`

### Reliability (NFR-03 atomic write)
- [ ] `test_reliability_kill_during_write_keeps_valid_json`
- [ ] `test_reliability_concurrent_writes_do_not_corrupt`

### Configuration Liveness
- [ ] `test_config_env_keys_declared_in_env_example`

---

*End of SRS v2.0.0 — taskq | 2026-06-17*
