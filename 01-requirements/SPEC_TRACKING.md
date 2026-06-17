# SPEC_TRACKING.md — taskq

> Spec Tracking Matrix — 每個 FR 的狀態、擁有者、驗收狀態
>
> **「Decision Framework」與「Notes」欄位之 P3/P4 提示為規劃性建議(advisory),非 SPEC.md 之內容。Spec Description、Intent Class、Status、Acceptance State 為唯一可追溯到 SPEC.md 的權威欄位。**
> Project: taskq
> Version: v2.0.0
> Date: 2026-06-17
> Phase: 1 — Requirements Specification
> Source: SRS.md (APPROVED by Agent B round 1, 2026-06-17)

## Project Info

- **Project Name**: taskq
- **Canonical Spec**: SPEC.md v2.0.0
- **SRS Version**: v2.0.0
- **Created**: 2026-06-17
- **Phase**: 1 — Requirements Specification
- **Authoring Mode**: INGESTION (100% transcription from SPEC.md)

## Specification Status

| FR ID | Spec Description | Intent Class | Decision Framework | Status | Owner | Acceptance State | Notes |
|-------|-----------------|--------------|--------------------|--------|-------|------------------|-------|
| FR-01 | 任務模型與持久化 — `submit` 命令驗證(非空/長度/注入字元黑名單 6 字元),通過後產生 uuid4 前 8 hex id,原子寫入 `tasks.json`(tmp + `os.replace`);`tasks.json` 損壞時 exit 1 不靜默重建 | functional-validation | harness v2.9 P3 (TDD) | ✅ Done | REQUIREMENTS_ENGINEER | criteria-defined | 4 條驗證規則 + id 格式 + atomic + corruption detection;CLI exit 2 與 exit 1 行為已鎖定 |
| FR-02 | 任務執行與重試 — `run` 以 `subprocess.run(shlex.split, shell=False, timeout=TASKQ_TASK_TIMEOUT)` 執行,狀態機 `pending → running → done/failed/timeout`,失敗/timeout 自動重試至 `TASKQ_RETRY_LIMIT`;timeout 結果 exit 4;未預期例外 exit 1 | functional-execution | harness v2.9 P3 (TDD) | ✅ Done | REQUIREMENTS_ENGINEER | criteria-defined | 執行細節 + 結果欄位 + 重試行為 + 錯誤處理四區塊已逐條收錄;`shell=False` 為 NFR-02 之硬約束 |
| FR-03 | CLI 整合與查詢 — argparse 子命令 `submit` / `run` / `status` / `list` / `clear` + `--json` 全域旗標 + 統一 exit codes(0/2/4/1) | functional-integration | harness v2.9 P3 (TDD) | ✅ Done | REQUIREMENTS_ENGINEER | criteria-defined | 5 個子命令逐一定義行為;exit codes 對映錯誤類別 |
| NFR-01 | performance — `submit + status` 100 次 p95 < 50ms(不含 subprocess 執行) | non-functional-performance | harness v2.9 P3 benchmark | ✅ Done | REQUIREMENTS_ENGINEER | criteria-defined | benchmark 測試對象與量測範圍已收錄;P3 須有獨立 benchmark 模組 |
| NFR-02 | security — 全 codebase 禁用 `shell=True`;FR-01 注入字元黑名單必有測試覆蓋(6 字元各一) | non-functional-security | harness v2.9 P3 靜態掃描 + unit test | ✅ Done | REQUIREMENTS_ENGINEER | criteria-defined | grep/semgrep 自訂規則 + 6 字元參數化測試;P3 須於 `pyproject.toml` 註冊 semgrep 自訂規則 |
| NFR-03 | reliability — `tasks.json` 原子寫(進程中斷後仍為合法 JSON);`stdout_tail`/`stderr_tail` 落盤前 secret redaction `(sk-[A-Za-z0-9_-]{8,}\|token=\S+)` 整行以 `[REDACTED]` 取代 | non-functional-reliability | harness v2.9 P4 整合測試 | ✅ Done | REQUIREMENTS_ENGINEER | criteria-defined | 兩條子要求各自有驗證方法;redaction regex 完整保留 |

## Completeness Check

| 檢查項 | 目標 | 實際 | 狀態 |
|--------|------|------|------|
| FR 從 SPEC.md 收錄 | 3 | 3 (FR-01..FR-03) | PASS |
| NFR 從 SPEC.md 收錄 | 3 | 3 (NFR-01..NFR-03) | PASS |
| FR 狀態為 VERIFIED | 100% | 100% | PASS |
| Owner 已指派 | 100% | 100% | PASS |
| Acceptance criteria 定義 | 100% | 100% | PASS |
| 沒有 orphan FR(在 SRS 但不在本表) | 0 | 0 | PASS |

## Out of Scope(從 SPEC.md §5 同步)

- Daemon / 服務化
- 遠端執行
- 非 JSON 持久化後端
- 斷路器、快取、並發

## Update log

| Date | Author | Change | Status |
|------|--------|--------|--------|
| 2026-06-17 | REQUIREMENTS_ENGINEER | Initial SPEC_TRACKING.md created from SPEC.md v2.0.0 (6 entries: FR-01/02/03 + NFR-01/02/03) | Done |
| 2026-06-18 | IMPLEMENTATION_ENGINEER | P3 implementation complete; all 3 FRs VERIFIED, Gate 2 PASSED at 95.6 | Done |

## Links

- [SRS.md](./SRS.md) — v2.0.0 APPROVED 2026-06-17
- [TRACEABILITY_MATRIX.md](./TRACEABILITY_MATRIX.md) — 下游產出
- [TEST_INVENTORY.yaml](../TEST_INVENTORY.yaml) — 下游產出
- [SPEC.md](../SPEC.md) v2.0.0 — canonical
- [PROJECT_BRIEF.md](../PROJECT_BRIEF.md) — 種子輸入
