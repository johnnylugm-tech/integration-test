# PROJECT_BRIEF — taskq

> Authored by orchestrator (bootstrap) from `SPEC.md`. Seed input for Phase 1;
> Agent B (BUSINESS_ANALYST) embeds it as DOC 1 in every B-1 review prompt.

canonical_spec: SPEC.md

## 1. Project name & purpose

- **Project name**: `taskq` (project root: /Users/johnny/projects/integration-test)
- **Purpose**: 本地任務佇列 CLI — 提交 shell 命令為任務,受控執行(timeout/重試),狀態可查詢。
- **Language**: Python 3.11, runtime 零外部依賴(stdlib only)
- **Experiment role**: harness-methodology v2.9 整合驗證標的 — 框架在本專案完整行使 P1-P8;框架本身的修改 out of scope(框架 bug 由 e2e 監督者處理,不在本專案內 workaround)。

## 2. Stakeholders

- **Primary user**: 需要批次執行/重試本地命令的開發者(Johnny)
- **Methodology reviewers**: harness-methodology 維護者 — 以本專案的 P1-P8 工件評估框架健康度
- **Project owner**: Johnny (repo: https://github.com/johnnylugm-tech/integration-test)

## 3. Business goals

- 任務提交驗證(注入字元拒絕,FR-01)、受控 subprocess 執行(timeout/重試,FR-02)
- 完整 CLI 與查詢(FR-03)
- 可靠性:原子寫存儲、secret redaction(NFR-03);安全:禁 shell=True(NFR-02)
- 效能:submit+status 100 次 p95 < 50ms(NFR-01)

## 4. Key constraints

- **3 functional requirements are pre-defined and immutable** (FR-01..FR-03, SPEC.md §3). Do not invent new FRs.
- **Tech stack locked**: Python 3.11 stdlib only(runtime)。No external runtime deps.
- **Configuration values fixed** (SPEC.md §5): 3 個 TASKQ_* 環境變數與預設值(TASKQ_HOME / TASKQ_TASK_TIMEOUT / TASKQ_RETRY_LIMIT)。
- **Single source of truth**: SPEC.md is canonical. No overlay document may amend it.

## 5. Out of scope

- Daemon/服務化、遠端執行、非 JSON 持久化後端、斷路器、快取(本版精簡,聚焦主流程)、並發
- 修改 harness-methodology 框架(submodule 唯讀,HR-17)
