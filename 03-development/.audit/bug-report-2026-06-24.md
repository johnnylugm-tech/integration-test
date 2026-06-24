# 對抗式 Bug Hunt 報告 — taskq（Gate 3 / adversarial_review）

- 掃描時間：2026-06-24T12:27:51Z
- 掃描 HEAD：`df11087`
- targeting manifest：`.methodology/bug_hunt_targets.json`（3 high-risk × 3-lens、9 standard × general）
- lenses：correctness / concurrency / resilience / general
- 原始 findings 6、確認 2（皆 high，已 resolved）、反駁 4
- 模型異源：hunt/verify 由 claude-opus-4-8 執行（與開發者模型不同源）；CRG 未建圖，目標僅 9 檔 ~700 行，以完整 Read + 可執行 repro 驗證

## 掃描摘要（module × severity）

| module | critical | high | medium | low | 反駁 |
|---|---|---|---|---|---|
| taskq.executor | 0 | 2 | 0 | 1 | 1 |
| taskq.store | 0 | 0 | 0 | 0 | 1 |
| taskq.breaker | 0 | 0 | 0 | 0 | 1 |
| taskq.config | 0 | 0 | 0 | 0 | 1 |

## 確認的 Bug（severity 降序）

### executor#1（high, resilience）— 無法啟動的命令拋出未捕獲 OSError
- 位置：`03-development/src/taskq/executor.py:97-134`
- 問題：`run_task` 只 `except subprocess.TimeoutExpired`。命令不存在／不可執行／空 argv（如 `shlex.split("''")` → `['']`）會讓 `subprocess.run` 拋 `FileNotFoundError`/`PermissionError` 逸出：單任務模式任務卡在 `running`、斷路器不被通知、CLI 直接吐 Python traceback（違反 SPEC §7）；`run_all` 經 `future.result()` 整批中止、其餘任務卡 `running`。打錯命令名是最常見觸發。
- 證據：HEAD repro，`run_task('nonexistent_program_xyz')` 拋 FileNotFoundError 且 status 停在 running；`run_all([echo,nonexistent,echo])` 整批中止；命令通過 `cmd_submit` 驗證即可達。全測試套件無 command-not-found 覆蓋。
- 修復：新增 `except OSError` → 記為 terminal `failed`（exit_code=127、stderr_tail 記錄錯誤），與 non-zero 退出的 failed 分支對齊；斷路器被通知、批次續跑。
- resolution：resolved（repro_test：`03-development/tests/test_bughunt_regressions.py`，修前 RED／修後 GREEN）

### executor#2（high, concurrency）— HALF_OPEN 經 run_all 放行全部任務而非單一 trial
- 位置：`03-development/src/taskq/executor.py:167-187`
- 問題：SPEC FR-03 要求 HALF_OPEN「放行一個任務」。`run_all` 以 ThreadPoolExecutor 並發派發全部 pending；每個 `run_task` 呼叫 `breaker.is_open()` 在 HALF_OPEN 回傳 False，導致全部同時通過、一起執行，斷路器的限流保護被破壞。
- 證據：HEAD repro，強制 HALF_OPEN 後 `run_all` 5 個失敗任務全部執行（預期 1）；`is_open()` 在 HALF_OPEN == False。無測試斷言 HALF_OPEN 單一 trial。
- 修復：`run_all` 偵測 HALF_OPEN 時先同步跑一個 trial，由斷路器 CLOSED/OPEN 結果決定其餘是否放行（失敗 → 其餘 exit 3，成功 → 其餘正常執行）。
- resolution：resolved（同一 repro_test）

## 被反駁清單（一句理由）

- executor#3（failed 任務回傳 0）：SPEC §FR-05 退出碼表無「failed」專屬碼，docstring 明載「else 0」，status 仍正確記為 failed → 設計如此。
- store#1（redaction 大小寫/長度）：SPEC NFR-04 逐字釘死 regex `(sk-[A-Za-z0-9_-]{8,}|token=\S+)`，現況逐字相符。
- breaker#1（連續失敗計數）：repro F,F,S,F,F → CLOSED(count=2)、閾值邊界正確，符合 FR-03。
- config#1（get_config 快取僅 HOME 失效）：taskq 為一次性 CLI 進程，每次呼叫重建 config，陳舊路徑在產品執行模型不可達。

## 修復優先順序

1. executor#1（high）— 已修：常見打錯命令即觸發、批次崩潰／任務遺失。
2. executor#2（high）— 已修：斷路器核心限流語義失效。
3. 反駁項：無需處理（留檔追蹤）。

## 掃描方法

讀 targeting manifest → 完整 Read 9 個模組 + SPEC/TEST_SPEC 對照 → 依 lens 列候選 → 對每個候選寫可執行 repro 在 HEAD 上 confirm/refute（refuter 預設 is_real=false）→ 確認項以 surgical 修復並加回歸測試（修前 RED、修後 GREEN，反 fabrication）→ 全套件 175 passed → 寫 `bug_hunt_report.json` 並以框架 `bug_hunt_verifier` 自我驗證 score=100。
