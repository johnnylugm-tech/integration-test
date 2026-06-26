# taskq — 規格文件(單一事實來源)

> 本文件為 `taskq` 的完整規格。**所有實作以此文件為準。**
> 專案角色:harness-methodology v2.9 的整合驗證標的(以真實小型專案形態完整行使 Phase 1–8 開發管線)。

---

## 1. 概述

- **專案名稱**:`taskq`
- **目的**:本地任務佇列 CLI — 提交 shell 命令為任務,受控執行(timeout/重試),狀態可查詢
- **語言**:Python 3.11,**runtime 零外部依賴**(僅標準函式庫;測試工具由開發環境提供)
- **形態**:命令列工具,`python -m taskq` 進入

---

## 2. 技術架構

| 元件 | 技術 |
|------|------|
| CLI | argparse 子命令 |
| 任務執行 | subprocess(`shlex.split`,禁 `shell=True`) |
| 持久化 | JSON 檔(原子寫:tmp + `os.replace`) |
| 設定 | `TASKQ_*` 環境變數(config.py 統一讀取) |

---

## 3. 功能需求(Functional Requirements)

### FR-01:任務模型與持久化

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

### FR-02:任務執行與重試

`taskq run <id>`

- 以 `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` 執行;**任何路徑不得使用 `shell=True`**
- 狀態機:`pending → running → done | failed | timeout`
  - exit 0 → `done`;非 0 → `failed`;`TimeoutExpired` → `timeout`
- 結果欄位:`exit_code`、`stdout_tail`(末 2000 字元)、`stderr_tail`(末 2000 字元)、`duration_ms`、`finished_at`
- **重試**:`run` 結果為 `failed`/`timeout` 時自動重試,上限 `TASKQ_RETRY_LIMIT` 次(預設 2)
- 單一任務模式下 `timeout` 結果 → **exit 4**
- 其他未預期例外 → exit 1(不得裸 `except:` 吞噬)

### FR-03:CLI 整合與查詢

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

---

## 4. 非功能需求(Non-Functional Requirements)

| ID | 類別 | 要求 |
|----|------|------|
| NFR-01 | performance | `submit` + `status` 組合操作 100 次 p95 < 50ms(不含 subprocess 執行) |
| NFR-02 | security | 全 codebase 禁用 `shell=True`;FR-01 注入字元黑名單必須有測試覆蓋 |
| NFR-03 | reliability | `tasks.json` 原子寫(進程中斷後仍為合法 JSON);`stdout_tail`/`stderr_tail` 落盤前過濾 `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` 整行以 `[REDACTED]` 取代 |

> 風險併入:**R1** 並發/中斷寫入損壞(由 NFR-03 緩解)、**R2** subprocess 懸掛(由 FR-02 timeout 緩解)、**R3** secret 落盤洩漏(由 NFR-03 緩解)。

---

## 5. 參數配置(config.py 統一讀取,含預設值;`.env.example` 完整宣告)

| 變數 | 預設 | 說明 |
|------|------|------|
| `TASKQ_HOME` | `.taskq` | 資料檔目錄 |
| `TASKQ_TASK_TIMEOUT` | `10.0` | 單任務 subprocess timeout(秒) |
| `TASKQ_RETRY_LIMIT` | `2` | 失敗自動重試上限 |

---

*文件版本:v2.0.0(3-FR 精簡版) | 2026-06-15*
