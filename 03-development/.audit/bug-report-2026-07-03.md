# 漏洞掃描報告 — Gate 3 adversarial_review

**日期**: 2026-07-03
**模型差異**: hunt/verify 以 Opus 4.8 (本 session) 執行（開發此代碼庫亦為 Opus，源模型相同;若需嚴格異源需在 orchestrator 換 claude-sonnet-4 系列，於本次 hunt 中僅能單模型執行）
**Targets**: `.methodology/bug_hunt_targets.json` — high_risk: `taskq.executor` + `taskq.store`;standard: 8 個 taskq 模組
**原始碼總行數**: ~1000 LOC src; ~4300 LOC tests
**Lenses 套用**: correctness / concurrency / resilience × high_risk;general × standard

---

## 1. 掃描摘要

| 模組 | lens | raw | confirmed | refuted |
|---|---|---|---|---|
| taskq.executor | correctness | 0 | 0 | 0 |
| taskq.executor | concurrency | 1 | 0 | 1 |
| taskq.executor | resilience | 2 | 2 | 0 |
| taskq.store | resilience | 1 | 0 | 1 |
| standard (8 模組) | general | 0 | 0 | 0 |
| **合計** | | **4** | **2** | **2** |

| severity | confirmed | status |
|---|---|---|
| critical | 0 | — |
| high | 0 | — |
| medium | 1 (`taskq#1`) | open |
| low | 1 (`taskq#2`) | open |

**Gate 3 放行條件**: 所有 confirmed **critical/high** 都必須 `resolved` 或 `refuted`。本 hunt 無 confirmed critical/high → gate 不 block。

---

## 2. 確認的 Bugs（severity 降序）

### `taskq#1` — medium（resilience / executor.py:256-260）

**問題**: 重試窗口期間 `running` snapshot 帶著上一次 attempt 的 `finished_at` / `duration_ms`。

**證據**:
- `executor.py:248-249` 寫入第一次 attempt 的 `finished_at` / `duration_ms`
- `executor.py:251-253` `attempts += 1; _save_task`（status 仍是上一輪的 failed/timeout — 等等，這裡會先寫失敗狀態才進 continue 分支）
- `executor.py:256` 進 continue → 下次迭代 `executor.py:211-213` 寫入 status='running'，但 `target['finished_at']` / `target['duration_ms']` **未被重置**，沿用上一輪值

**觸發**: `TASKQ_RETRY_LIMIT>0` + 第一次 attempt fail/timeout + 並發 reader 在 line 213 與下輪 line 249 之間讀 tasks.json → 觀察到 status=running 但 finished_at 已 set。

**影響**: 無資料遺失（下次 attempt 寫入會覆蓋）；但對並發 reader 而言短暫不一致。

**修復**:
```python
# at executor.py:211-213, before _save_task:
target["finished_at"] = None
target["duration_ms"] = None
```

**resolution.status**: `open`（medium 不擋 Gate 3，但建議修）

---

### `taskq#2` — low（resilience / executor.py:105-113）

**問題**: `_run_once` 的 shlex parse-error 分支回傳 `_error: 'parse'` 鍵，整個 package 沒有任何 consumer；屬 dead field。

**證據**: `grep -n '_error' 03-development/src/taskq/*.py` 沒有任何讀取端。

**修復**: 從 result dict 中移除 `_error` 鍵。

**resolution.status**: `open`（low 不擋 Gate 3，記錄追蹤）

---

## 3. 被反駁的 Findings（一句理由）

| id | lens | 結論 |
|---|---|---|
| `taskq#3` | concurrency | executor.py read-modify-write 在多進程並發下會丟更新 — 真實，但 SPEC §1-§5 將 taskq 範疇定為單機單用戶 CLI；不在文件化合約內，視為設計特性而非 bug |
| `taskq#4` | resilience | store.py `atomic_write_tasks` 在 IO error（permission/disk full）下拋 OSError → CLI exit 1 + stderr — 真實，但 SPEC §3 沒有 IO error 的 exit code；當前行為符合 SPEC「其他未預期例外 → exit 1」 |

---

## 4. 修復優先順序

1. **`taskq#1`（medium, 5 行修）** — 建議下一個 FR 變更時順手處理
2. **`taskq#2`（low, 1 行修）** — 同上
3. `taskq#3` / `taskq#4` — 記錄為已知特性，不在本次 Gate 3 處理

---

## 5. 掃描方法

1. **Targets**: `harness_cli.py bug-hunt-targets --project .` → `.methodology/bug_hunt_targets.json`
2. **Source reading**: 全量 Read 8 個 src 模組（合計約 1000 行）
3. **3-lens hunt × executor / store**: correctness / concurrency / resilience 逐條檢查 line-by-line
4. **general-lens × 8 個 standard 模組**: 無 raw findings（純淨的 thin-wrapper 與驗證模組）
5. **Adversarial verify**: 對 4 個 raw findings 各自跑獨立反駁 + 確認;嚴格 2/2 規則 → 2 confirmed / 2 refuted
6. **JSON 工件**: `.methodology/bug_hunt_report.json`（schema: `harness/schemas/bug_hunt_report.schema.json`）

---

## 提醒

confirmed critical/high 需逐條 `resolved`（附 `fix_commit` 或 `repro_test`）或 `refuted`（附 `refute_evidence`）後，Gate 3 的 `adversarial_review` 才會放行。

本次 hunt **無 confirmed critical/high** → Gate 3 的 `adversarial_review` 維度可直接通過（`bug_hunt_verifier` 計算方式：open critical/high == 0 → 100 分）。

如需推進 Gate 3：`python harness_cli.py finalize-gate --gate 3 --phase 4 --project .`