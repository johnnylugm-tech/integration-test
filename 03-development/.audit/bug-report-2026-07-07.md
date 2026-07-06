# Adversarial Bug Hunt Report — 2026-07-07

> Gate 3 dimension `adversarial_review`. Manifest: `.methodology/bug_hunt_targets.json`.
> HEAD: `477d459de43c8f8ea7fa2eafba6fb5ae094d7246`.
> 4-phase protocol (scout → hunt → verify → synthesize) per
> `harness/ssi/prompts/hunt_bugs.md`.

## 掃描摘要

| 模組 | lens | 確認 | 反駁 |
|---|---|---|---|
| taskq.breaker | concurrency | 1 | 1 |
| taskq.executor | correctness / resilience | 0 | 2 |
| taskq.store | concurrency | 0 | 1 |
| taskq.cli | correctness | 0 | 1 |
| taskq.cache | general | 0 | 0 |
| taskq.__main__ | general | 0 | 0 |

**Raw findings: 6 — Confirmed (critical/high): 1 — Refuted: 5.**

唯一一條 confirmed (HIGH) → 已 resolved by fix commit `477d459`。

## 確認的 bugs

### breaker#1 — 嚴重性 high

**位置**: `03-development/src/taskq/breaker.py:120-162`
**問題**: `check_and_record` 在 `breaker.json` 上做 read-modify-write 沒有序列化。`run --all` 把 N 個失敗的 subprocess 透過 `ThreadPoolExecutor` 扇出時,每個 worker 的失敗都會 race,造成 lost-update:
- threshold=10 + 20 個並行失敗 → observation `failure_count=5`(少了 15)
- breaker 仍然 `CLOSED`,雖然 20 個失敗已經發生

**證據**:
- `tests/test_bug_hunt_breaker_race.py::test_breaker_concurrent_check_and_record_no_lost_updates` (RED → GREEN)
- `tests/test_bug_hunt_breaker_race.py::test_breaker_concurrent_failures_trip_threshold` (RED → GREEN)

**修復**: `fix(breaker): serialize read-modify-write` — 加入 `threading.Lock()`,把 `check_and_record` 的整段 load-modify-write critical section 包進 `with _breaker_lock:`(鏡像 `cache.py` 對 `cache.json` 的 pattern)。

**Resolution**: resolved — `fix_commit: 477d459de43c8f8ea7fa2eafba6fb5ae094d7246`, `repro_test: 03-development/tests/test_bug_hunt_breaker_race.py`。

## 被反駁的清單

### breaker#2 — `opened_at=None` 卡在 OPEN

Line 140 的防禦性 fallback `elapsed = now - (opened_at if opened_at is not None else now)` 在 `opened_at is None` 時會讓 `elapsed = 0`,breaker 永遠卡在 OPEN。
**反駁**: 唯一設定 `state='OPEN'` 的路徑(line 180)同時也設了 `opened_at=now`。這個防禦分支只能透過外部竄改 `breaker.json` 達成,production-unreachable。

### store#1 — `add_task --name` 衝突缺 lock

`add_task` load → check conflict → write 中間沒有 lock。
**反駁**: 5 次 `threading.Barrier` 壓測每次都只有 1 個 task 寫入,in-process CLI 用法下 race window 不可達。

### executor#1 — `isinstance(result, ExecutionResult)` 防禦分支

`_run_once` 在 production 一定 return `ExecutionResult`,這個 isinstance 分支只在 mock 的 deferred-call pattern 下觸發。
**反駁**: 純測試 fixture bridge,production path 不可能產生 callable。

### executor#2 — `except Exception` 吞掉 handler 錯誤

`except Exception` 會吞錯——但 `Exception` 不含 `BaseException`(KeyboardInterrupt / SystemExit 仍會傳上去)。Non-existent command 已經驗證返回正確的 `status='failed'` shape。
**反駁**: 符合 SPEC §7 的 reliability 設計,行為正確。

### cli#1 — argparse `--json` 同時掛在 parent parser 與 subparser

`_build_parser` 把 `common`(含 `--json`)同時餵給 top-level parser 與每個 subparser。
**反駁**: 3 種 `--json` 位置(前/中/後)全部正確解析,argparse 靜默接受。

## 修復優先順序

1. **breaker#1 (high)** — 已 committed `477d459`,**ALL TESTS GREEN**(55/55)。

## 掃描方法

1. CRG 圖全量重建 (286 節點 / 2054 edges / 24 communities / 50 flows)。
2. 讀取 `bug_hunt_targets.json`(2 high-risk: executor/store;7 standard + 2 high-risk 共 7 個檔案)。
3. 直接 Read 7 個 target 模組全文(平均 200-300 行)。
4. 對每個 high-risk 模組套用 correctness + concurrency + resilience 3-lens,其他模組套用 general 1-lens。
5. 對每個 finding 寫 reproduction 腳本驗證(empirical pytest 證據),2 verifiers(strict confirmed rule)。
6. 對 confirmed critical/high 寫 RED repro test → fix → verify GREEN → commit。
7. 寫 `.methodology/bug_hunt_report.json` + 本 markdown 報告。
