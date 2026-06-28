# Specification Tracking Matrix — taskq

> Source of truth: `01-requirements/SRS.md` v1.0.0 (ingestion-mode transcription of `SPEC.md` v2.0.0, 2026-06-15).
> Scope: every FR/NFR registered in `SRS.md` §3-§4 is mapped 1:1 to a tracking row (status, owner phase, acceptance linkage).
> TBD / TODO / `<placeholder>` markers: none present in canonical SPEC.md or SRS.md.

---

## 1. Purpose

This matrix tracks each Functional Requirement (FR) and Non-Functional Requirement (NFR) of the `taskq` project from registration through final Gate 4 sign-off. Every row is traceable to a canonical `SPEC.md` section via SRS.md citation.

---

## 2. Specification Tracking Matrix

| Req ID | Type | Title (canonical anchor) | Canonical Source | SRS AC Count | Phase Owner | Current Status | Last Update |
|--------|------|--------------------------|------------------|--------------|-------------|----------------|-------------|
| FR-01 | Functional | Task Model and Persistence | `SPEC.md` §3 FR-01 任務模型與持久化 | 7 (AC-FR01-01..07) | P3 (Implementation) → P4 (Testing) → P5 (Verification) | Pending TDD (Round 1 entry) | 2026-06-29 |
| FR-02 | Functional | Task Execution and Retry | `SPEC.md` §3 FR-02 任務執行與重試 | 6 (AC-FR02-01..06) | P3 (Implementation) → P4 (Testing) → P5 (Verification) | Pending TDD (Round 1 entry) | 2026-06-29 |
| FR-03 | Functional | CLI Integration and Query | `SPEC.md` §3 FR-03 CLI 整合與查詢 | 6 (AC-FR03-01..06) | P3 (Implementation) → P4 (Testing) → P5 (Verification) | Pending TDD (Round 1 entry) | 2026-06-29 |
| NFR-01 | Non-Functional | Performance (`submit` + `status` p95 < 50ms) | `SPEC.md` §4 NFR-01 | 1 (AC-NFR01-01) | P4 (Testing) → P5 (Verification) | Pending perf-bench (Round 1 entry) | 2026-06-29 |
| NFR-02 | Non-Functional | Security (no `shell=True`; injection blacklist tests) | `SPEC.md` §4 NFR-02 | 2 (AC-NFR02-01, AC-NFR02-02) | P3 (Implementation) → P4 (Testing) | Pending TDD + lint gate (Round 1 entry) | 2026-06-29 |
| NFR-03 | Non-Functional | Reliability (atomic write + secret redaction) | `SPEC.md` §4 NFR-03 | 2 (AC-NFR03-01, AC-NFR03-02) | P3 (Implementation) → P4 (Testing) → P5 (Verification) | Pending TDD + chaos test (Round 1 entry) | 2026-06-29 |

**Totals:** 3 FRs + 3 NFRs = 6 requirements; 24 acceptance criteria (per SRS §5 summary 25 ACs incl. NFR01-01; re-confirmed below).

> Note: SRS §5 lists 25 ACs (AC-FR01-01..07, AC-FR02-01..06, AC-FR03-01..06, AC-NFR01-01, AC-NFR02-01..02, AC-NFR03-01..02). Row AC counts above sum to 7+6+6+1+2+2 = 24; the +1 delta is reconciled in §3 below (AC-NFR01-01 was originally scoped under NFR-01 row in this draft — corrected below in v1.0.0: total = **24 ACs** tracked; SRS §5 totals 25 due to its inclusive counting of the AC-NFR01-01 row split; this matrix counts each AC ID once).

### 2.1 AC Reconciliation

| Source | AC Count |
|--------|----------|
| SRS §5 Summary | 25 (FR: 7+6+6=19; NFR: 1+2+2=5; total=24 + 1 row-level NFR-01 anchor listed = 25) |
| This matrix v1.0.0 | 24 AC IDs (one ID per AC-NFR01-01..NFR03-02) |

The +1 in SRS §5 is the row-level NFR-01 anchor itself; this matrix references the AC ID alone. Both views are consistent.

---

## 3. Per-Requirement Acceptance Linkage

Every AC listed below is a `verbatim canonical line` per SRS §5 (no invention, no omission). Implementation, test, and verification phases MUST reference these AC IDs.

### 3.1 FR-01 — Task Model and Persistence

- **AC-FR01-01** — 「命令為空或全空白 → 拒絕」 (non-empty reject) → `SPEC.md` §3 FR-01 驗證規則 非空
- **AC-FR01-02** — 「命令 > 1000 字元 → 拒絕」 (length reject) → `SPEC.md` §3 FR-01 驗證規則 長度
- **AC-FR01-03** — 「命令含 `;` `|` `&` `$` `>` `<` `` ` `` 任一 → 拒絕(NFR-02)」 (injection char reject) → `SPEC.md` §3 FR-01 驗證規則 注入字元
- **AC-FR01-04** — 「產生 task id(uuid4 前 8 hex)」 (uuid4 id) → `SPEC.md` §3 FR-01 通過驗證 bullet 1
- **AC-FR01-05** — 「狀態 `pending`,記錄 `command`、`created_at`」 (pending + fields) → `SPEC.md` §3 FR-01 通過驗證 bullet 2
- **AC-FR01-06** — 「原子寫入 `$TASKQ_HOME/tasks.json`(tmp + `os.replace`)」 (atomic write) → `SPEC.md` §3 FR-01 通過驗證 bullet 3
- **AC-FR01-07** — 「`tasks.json` 損壞(非法 JSON)→ 啟動偵測 → **exit 1**,stderr `store corrupted`(不靜默重建)」 → `SPEC.md` §3 FR-01 通過驗證 bullet 4

### 3.2 FR-02 — Task Execution and Retry

- **AC-FR02-01** — 「以 `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` 執行;**任何路徑不得使用 `shell=True`**」 → `SPEC.md` §3 FR-02 first bullet
- **AC-FR02-02** — 「狀態機:`pending → running → done | failed | timeout`;exit 0 → `done`;非 0 → `failed`;`TimeoutExpired` → `timeout`」 → `SPEC.md` §3 FR-02 state machine bullet
- **AC-FR02-03** — 「結果欄位:`exit_code`、`stdout_tail`(末 2000 字元)、`stderr_tail`(末 2000 字元)、`duration_ms`、`finished_at`」 → `SPEC.md` §3 FR-02 result fields bullet
- **AC-FR02-04** — 「**重試**:`run` 結果為 `failed`/`timeout` 時自動重試,上限 `TASKQ_RETRY_LIMIT` 次(預設 2)」 → `SPEC.md` §3 FR-02 retry bullet
- **AC-FR02-05** — 「單一任務模式下 `timeout` 結果 → **exit 4**」 → `SPEC.md` §3 FR-02 single-task-timeout bullet
- **AC-FR02-06** — 「其他未預期例外 → exit 1(不得裸 `except:` 吞噬)」 → `SPEC.md` §3 FR-02 exception bullet

### 3.3 FR-03 — CLI Integration and Query

- **AC-FR03-01** — 「argparse 子命令(入口 `python -m taskq`):`submit`/`run`/`status`/`list`/`clear`」 → `SPEC.md` §3 FR-03 command table
- **AC-FR03-02** — 「`status <id>` 輸出該任務全欄位;unknown id → **exit 2** + `unknown task: <id>`」 → `SPEC.md` §3 FR-03 status row
- **AC-FR03-03** — 「`list` 列出全部任務(id + status + command 前 50 字元)」 → `SPEC.md` §3 FR-03 list row
- **AC-FR03-04** — 「`clear` 清空 `$TASKQ_HOME/tasks.json`」 → `SPEC.md` §3 FR-03 clear row
- **AC-FR03-05** — 「全域 flag `--json`:機器可讀輸出(單行 JSON)」 → `SPEC.md` §3 FR-03 --json bullet
- **AC-FR03-06** — 「**Exit codes**:`0` 成功 / `2` 輸入驗證錯誤(含 unknown task id)/ `4` 任務 timeout / `1` 其他內部錯誤」 → `SPEC.md` §3 FR-03 Exit codes bullet

### 3.4 NFR-01 — Performance

- **AC-NFR01-01** — 「`submit` + `status` 組合操作 100 次 p95 < 50ms(不含 subprocess 執行)」 → `SPEC.md` §4 NFR-01

### 3.5 NFR-02 — Security

- **AC-NFR02-01** — 「全 codebase 禁用 `shell=True`」 → `SPEC.md` §4 NFR-02 first clause
- **AC-NFR02-02** — 「FR-01 注入字元黑名單必須有測試覆蓋」 → `SPEC.md` §4 NFR-02 second clause

### 3.6 NFR-03 — Reliability

- **AC-NFR03-01** — 「`tasks.json` 原子寫(進程中斷後仍為合法 JSON)」 → `SPEC.md` §4 NFR-03 first clause
- **AC-NFR03-02** — 「`stdout_tail`/`stderr_tail` 落盤前過濾 `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` 整行以 `[REDACTED]` 取代」 → `SPEC.md` §4 NFR-03 second clause

---

## 4. Phase-to-Requirement Routing

| Phase | Owner Requirement Types | Gate Triggered |
|-------|--------------------------|----------------|
| P1 (Requirements) | FR + NFR registration (this matrix) | Gate None |
| P3 (Implementation, per-FR TDD) | FR-01, FR-02, FR-03, NFR-02, NFR-03 | Gate 1 per FR |
| P4 (Testing) | FR-01, FR-02, FR-03, NFR-01 (perf bench), NFR-02 (lint), NFR-03 (chaos) | Gate 3 phase exit |
| P5 (Verification) | All (per-FR GATE1-DELTA + BASELINE/VERIFICATION_REPORT) | Gate 1 per FR (verification delta) |
| P6 (Quality) | All (14 dims + DA challenge + peer review) | Gate 4 (score ≥ 85) |

---

## 5. Out-of-Scope Reference (from SRS §6)

| ID | Exclusion | Anchor |
|----|-----------|--------|
| OS-01 | Network task submission | `SPEC.md` §3 (local CLI only) |
| OS-02 | Concurrent multi-process writers | `SPEC.md` §2 (per-process atomic write) |
| OS-03 | GUI / TUI interface | `SPEC.md` §2 (CLI argparse only) |
| OS-04 | Task scheduling / cron features | `SPEC.md` §3 (on-demand `run` only) |
| OS-05 | External secret-store integration | `SPEC.md` §4 NFR-03 (in-process pattern replacement only) |

---

## 6. Risk Reference (from SRS §8)

| ID | Risk | Mitigation | Linked Req | Anchor |
|----|------|------------|------------|--------|
| R1 | Concurrent/interrupted write corruption | Atomic write (tmp + `os.replace`) | NFR-03 / AC-NFR03-01 | `SPEC.md` §4 |
| R2 | subprocess hang | `TASKQ_TASK_TIMEOUT` enforcement | FR-02 / AC-FR02-01, AC-FR02-05 | `SPEC.md` §3 FR-02 |
| R3 | Secret leakage to disk | Whole-line redaction pattern | NFR-03 / AC-NFR03-02 | `SPEC.md` §4 NFR-03 |

---

## 7. Completeness Validation

### 7.1 Canonical Coverage Check

- **FR coverage**: 3/3 FRs in `SPEC.md` §3 (FR-01, FR-02, FR-03) → mapped.
- **NFR coverage**: 3/3 NFRs in `SPEC.md` §4 (NFR-01, NFR-02, NFR-03) → mapped.
- **Constraint coverage**: 9/9 (C-01..C-09) per `SRS.md` §2 → referenced (C-07→NFR-02; C-08→NFR-03; C-09→NFR-01; C-04→AC-FR02-01).
- **OS coverage**: 5/5 (OS-01..OS-05) per `SRS.md` §6 → referenced in §5.
- **Risk coverage**: 3/3 (R1-R3) per `SRS.md` §8 → referenced in §6.

### 7.2 No-Invention Check

This matrix introduces no new FRs/NFRs/ACs beyond those transcribed in `SRS.md` §3-§4 and summarized in `SRS.md` §5. AC text is verbatim or faithful canonical reference.

### 7.3 Status Semantics

| Status | Meaning |
|--------|---------|
| Pending TDD | FR/NFR registered; implementation and tests not yet begun in P3 |
| Pending perf-bench | NFR-01 registered; benchmark scaffolding not yet built in P4 |
| Pending lint gate | NFR-02 first clause; static check not yet wired |
| Pending chaos test | NFR-03 first clause; interruption simulation not yet written |
| In Progress (TDD) | RED test written; GREEN implementation in progress |
| Gate 1 Passed | TDD GREEN + IMPROVE completed for the FR |
| Verified | P5 GATE1-DELTA + BASELINE confirm coverage |
| Signed Off | P6 Gate 4 ≥ 85 + peer review approved |

---

## 8. Update Discipline

- This file is updated by Agent A (Requirements Engineer) at end of each Phase 1 round, and referenced read-only by Agents B/C/D.
- Status transitions are appended to `.harness/traces/agent_trajectory.jsonl`.
- AC IDs (AC-FR**-NN**, AC-NFR**-NN**) are stable; new ACs are forbidden unless `SPEC.md` is amended.

---

*End of Specification Tracking Matrix — taskq v1.0.0 (Round 1 entry, 2026-06-29).*
