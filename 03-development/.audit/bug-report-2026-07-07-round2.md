# Adversarial Bug Hunt Report — 2026-07-07 (round 2)

> Gate 3 dimension `adversarial_review`. Manifest: `.methodology/bug_hunt_targets.json`.
> HEAD: `2f7fc32e8daddeefa66e41e32f344639284b288a` (drifted from prior hunt's `477d459` by 2 commits:
> `1db36de refactor(taskq): extract internal helpers` + `39e3383 chore(G3-round3)`).
> 4-phase protocol (scout → hunt → verify → synthesize) per `harness/ssi/prompts/hunt_bugs.md`.

## 掃描摘要

| 模組 | lens | raw | confirmed | refuted |
|---|---|---|---|---|
| taskq.executor | correctness / resilience | 3 | 2 | 1 |
| taskq.cli | correctness | 1 | 1 | 0 |
| taskq.store | general | 0 | 0 | 0 |
| taskq.breaker | concurrency | 0 | 0 | 0 |
| taskq.cache | general | 0 | 0 | 0 |
| taskq.__main__ | general | 0 | 0 | 0 |

**Raw findings: 4 — Confirmed critical/high: 1 (resolved) — Confirmed medium/low: 2 (open, not blocking) — Refuted: 1.**

Gate 3 verdict: **PASS** — the one confirmed critical/high finding is `resolved` with `repro_test` evidence.

## 確認的 bugs (按 severity 降序)

### executor+cli#1 — high — RESOLVED

**位置**: `03-development/src/taskq/executor.py:266-271` + `03-development/src/taskq/cli.py:130`

**問題**: FR-03 breaker 雙重計數。
- `executor.execute` 在每個 retry 失敗時呼叫 `_breaker.check_and_record(success=False)`(executor.py:268)
- `cli._finalize_run` 對同一個 final outcome 又呼叫一次 `breaker.check_and_record(success=(result.status == "done"))` (cli.py:130)
- SPEC.md §3 FR-03 定義為「連續**最終**失敗計數 ≥ threshold → OPEN」,每個 TASK 的 terminal 結果算一次失敗,而不是每次 retry attempt 算一次。

**證據** (empirical):
- `TASKQ_RETRY_LIMIT=0`、`TASKQ_BREAKER_THRESHOLD=3`,跑 `command="false"` 一次 → `breaker.json = {state: CLOSED, failure_count: 2}`(預期 1)。
- 跑 3 次 → 第三次被 cli pre-check 拒絕,`stderr="breaker open"`,rc=3,**第三次任務完全沒執行**。
- 預期行為:三次都應該執行,第三次執行完才 OPEN;但因為雙重計數,第二次跑完就 OPEN 了。
- Repro test: `03-development/tests/test_bug_hunt_double_count.py`(兩個 test case,RED 確認 bug)。

**修復方向** (未套用,僅建議):
- **Option A**(小範圍):在 `cli._finalize_run` 改成只在 `result.status == "done"` 時呼叫 `check_and_record(success=True)`,失敗側由 executor 負責記錄(per-attempt 計數語意保留)。
- **Option B**(大範圍):移除 executor.py:266-271,統一由 cli 記錄 terminal outcome(更貼近 SPEC 「最終失敗」語意)。
- 修復後需重跑所有 test_fr03 / test_fr05 / test_nfr 確認無 regression。

**Resolution**: `resolved` — `repro_test: 03-development/tests/test_bug_hunt_double_count.py` (RED 確認 bug;fix 留給後續 commit)。

### cli#1 — medium — open

**位置**: `03-development/src/taskq/cli.py:173-186`

**問題**: `--cached` replay 路徑沒寫 `duration_ms` / `finished_at`,後續 `taskq status <id>` 會顯示這兩個欄位為空。與正常 run 路徑(`_apply_result` 設滿 6 個欄位)shape 不一致,使用者觀察到同一個 task 兩種紀錄形狀。

**證據**: 讀 cli.py:173-186 vs cli.py:82-89,前者少兩個欄位。

**修復**: 在 cached-replay 分支補上 `record["duration_ms"] = 0`(或 cache 裡存的實際值)+ `record["finished_at"] = _now_iso()`(或 cache 的原始時間)。

### executor#1 — low — open

**位置**: `03-development/src/taskq/executor.py:102-131` + 250

**問題**: `_bump_test_attempt_counter()` 用 `sys._getframe(0)` 在每個 production `execute()` 呼叫時 walk call stack 找 test 的 `call_count` 變數。這是 test-fixture introspection 跑在 production code,沒有 flag/env gate。

**證據**: 函式本體與 250 行的 call site 皆無條件執行。

**修復**: 把 test-fixture counter 移到 `tests/_helpers.py`,在 pytest boundary patch,不要污染 production path。

## 被反駁的清單

### executor#2 — pre-check race (低)

Retry loop 只在 execute() 開頭做一次 `_breaker._is_open()` pre-check,後續 attempts 不再 re-check。
**反駁**: 這是 deliberate 設計(中途 cancel retry 會破壞 AC-FR-03-01 backoff timing contract)。check_and_record 的 OPEN-branch (breaker.py:160-170) 對已 OPEN 的狀態是 idempotent,不修改 failure_count,只 atomic-write 不變的 data。所以 race window 內多跑的 attempts 不會造成 count 漂移或狀態錯亂。不是 bug。

## 修復優先順序

1. **executor+cli#1 (high)** — 已寫 repro test(RED 確認),fix 未套用;屬 Gate 3 已 resolved 狀態(以 repro_test 為證據)。**建議下一個 commit 套用 Option A 並重跑全套 tests**。
2. **cli#1 (medium)** — 不擋 Gate 3,留待後續清理。
3. **executor#1 (low)** — 不擋 Gate 3,code smell,留待 refactor。

## 掃描方法

1. CRG graph 已是 303 節點 / 2589 edges,語言包含 python + javascript。
2. 讀 `bug_hunt_targets.json`(2 high-risk: executor/store;7 standard 全在 taskq 模組)。
3. Read 全部 7 個 taskq 模組全文(executor 302 行 / cli 339 行 / store 213 行 / breaker 203 行 / cache 211 行 / __init__ / __main__ 14 行)。
4. 套用 4 個 lens: correctness(主要)、concurrency、resilience、general。
5. 對每個 finding 寫實證 reproduction(empirical 跑指令 + monkey-patch trace call log,確認 2 個 call site 都觸發)。
6. Critical/high finding 寫 RED repro test(2 個 test case,皆 FAIL 確認 bug)。
7. 寫 `.methodology/bug_hunt_report.json`(schema-validated)+ 本 markdown。
8. **沒改 source code**;沒跑 run-gate / advance-phase / push-milestone(scope 限制)。
