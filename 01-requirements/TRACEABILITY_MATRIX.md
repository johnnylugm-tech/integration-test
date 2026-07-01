# Traceability Matrix — taskq

> Source of truth: `01-requirements/SRS.md` (APPROVED, transcribed from `SPEC.md` v2.0.0, 2026-06-15) and `01-requirements/SPEC_TRACKING.md` (APPROVED).
> Purpose: provide **bidirectional** traceability between Requirements (FR/NFR/AC), Design elements (Phase 2 SAD/ADR/TEST_SPEC), Implementation (Phase 3 TDD), Verification (Phase 4 testing), and Quality (Phase 6 14-dim Gate-4).
> Mode: INGESTION. All requirements lifted 1:1 from SRS.md §3–§4. No invention.

---

## 1. Project Metadata

| Field | Value |
|-------|-------|
| Project | `taskq` |
| SRS version | `SPEC.md` v2.0.0 (2026-06-15) |
| Language | Python 3.11 (stdlib only) |
| Runtime | CLI tool, entry `python -m taskq` |
| Total FRs | 3 (FR-01, FR-02, FR-03) |
| Total NFRs | 3 (NFR-01, NFR-02, NFR-03) |
| Total ACs | 25 (FR-01×8, FR-02×6, FR-03×7, NFR-01×1, NFR-02×2, NFR-03×2) |
| Total Constraints | 8 (C-01..C-08, see SRS §2) |
| Total Risks | 3 (R1..R3, see SRS §8) |

---

## 2. Master Matrix — FR → AC → Phase 2/3/4/6 (forward traceability)

### 2.1 FR-01 — 任務模型與持久化 (Task Model & Persistence)

| AC ID | Requirement (canonical) | Owner / Test boundary | Phase 2 (SAD/ADR/TEST_SPEC) | Phase 3 (TDD impl) | Phase 4 (verify) | Phase 6 (Gate-4) |
|-------|--------------------------|------------------------|------------------------------|----------------------|--------------------|-------------------|
| AC-FR01-01 | 非空 \| 命令為空或全空白 → 拒絕 | rejection observable on empty/whitespace input | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR01-02 | 長度 \| 命令 > 1000 字元 → 拒絕 | boundary test at 1000 / 1001 chars | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR01-03 | 注入字元 \| 命令含 ; \| & $ > < \` 任一 → 拒絕 (NFR-02) | per-character coverage | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR01-04 | 產生 task id (uuid4 前 8 hex) | format = `[0-9a-f]{8}` | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR01-05 | 狀態 pending,記錄 command、created_at | field presence on read | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR01-06 | 原子寫入 $TASKQ_HOME/tasks.json (tmp + os.replace) | crash-injection test | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR01-07 | tasks.json 損壞(非法 JSON)→ 啟動偵測 → exit 1,stderr store corrupted(不靜默重建) | startup detection + exit-1 | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR01-08 | (preamble) 不寫入存儲 | storage byte-for-byte unchanged | ⬜ | ⬜ | ⬜ | ⬜ |

### 2.2 FR-02 — 任務執行與重試 (Task Execution & Retry)

| AC ID | Requirement (canonical) | Owner / Test boundary | Phase 2 (SAD/ADR/TEST_SPEC) | Phase 3 (TDD impl) | Phase 4 (verify) | Phase 6 (Gate-4) |
|-------|--------------------------|------------------------|------------------------------|----------------------|--------------------|-------------------|
| AC-FR02-01 | `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT); 任何路徑不得使用 shell=True` | code grep + behavior test | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR02-02 | `pending → running → done \| failed \| timeout` (exit 0→done; ≠0→failed; TimeoutExpired→timeout) | state transitions table | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR02-03 | exit_code、stdout_tail(末 2000 字元)、stderr_tail(末 2000 字元)、duration_ms、finished_at | field presence + tail length | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR02-04 | run 結果為 failed/timeout 時自動重試,上限 TASKQ_RETRY_LIMIT 次(預設 2) | retry-counter test | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR02-05 | 單一任務模式下 timeout 結果 → exit 4 | single-task-mode exit code | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR02-06 | 其他未預期例外 → exit 1(不得裸 except: 吞噬) | exception injection test | ⬜ | ⬜ | ⬜ | ⬜ |

### 2.3 FR-03 — CLI 整合與查詢 (CLI Integration & Query)

| AC ID | Requirement (canonical) | Owner / Test boundary | Phase 2 (SAD/ADR/TEST_SPEC) | Phase 3 (TDD impl) | Phase 4 (verify) | Phase 6 (Gate-4) |
|-------|--------------------------|------------------------|------------------------------|----------------------|--------------------|-------------------|
| AC-FR03-01 | `submit "<cmd>" \| FR-01` | routing test | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR03-02 | `run <id> \| FR-02` | routing test | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR03-03 | status <id> — unknown id → exit 2 + `unknown task: <id>` | message + exit code | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR03-04 | list — command 前 50 字元 | 50/51 char boundary | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR03-05 | clear — 清空 $TASKQ_HOME/tasks.json | post-clear list is empty | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR03-06 | `--json` 全域 flag:機器可讀輸出(單行 JSON) | JSON parse round-trip | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-FR03-07 | 0 成功 / 2 輸入驗證錯誤(含 unknown task id)/ 4 任務 timeout / 1 其他內部錯誤 | full exit-code matrix | ⬜ | ⬜ | ⬜ | ⬜ |

### 2.4 NFR-01..03 — Non-Functional Requirements

| AC ID | Requirement (canonical) | Owner / Test boundary | Phase 2 (SAD/ADR/TEST_SPEC) | Phase 3 (TDD impl) | Phase 4 (verify) | Phase 6 (Gate-4) |
|-------|--------------------------|------------------------|------------------------------|----------------------|--------------------|-------------------|
| AC-NFR01-01 | `submit + status 組合操作 100 次 p95 < 50ms(不含 subprocess 執行)` | harness owns subprocess-exclusion measurement | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-NFR02-01 | 全 codebase 禁用 `shell=True` | repo-wide grep | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-NFR02-02 | FR-01 注入字元黑名單必須有測試覆蓋 | test-count on blacklist cases | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-NFR03-01 | tasks.json 原子寫(進程中斷後仍為合法 JSON) | SIGKILL mid-write | ⬜ | ⬜ | ⬜ | ⬜ |
| AC-NFR03-02 | `stdout_tail/stderr_tail` 落盤前過濾 `(sk-[A-Za-z0-9_-]{8,}\|token=\S+)` 整行以 `[REDACTED]` 取代 | regex unit + integration test | ⬜ | ⬜ | ⬜ | ⬜ |

---

## 3. Reverse Matrix — Constraints → ACs → Risks (backward traceability)

### 3.1 Constraint Coverage (SRS §2 → ACs)

| Constraint | Description (canonical) | Mapped AC(s) | Risk mitigated |
|------------|--------------------------|--------------|----------------|
| C-01 | CLI via argparse subcommands | AC-FR03-01..07 | — |
| C-02 | `subprocess` + `shlex.split`; `shell=True` forbidden everywhere | AC-FR02-01, AC-NFR02-01 | R2 |
| C-03 | JSON atomic write (`tmp + os.replace`) | AC-FR01-06, AC-NFR03-01 | R1 |
| C-04 | `TASKQ_*` env-vars read via `config.py` | (cross-cutting; verified in P3/P4; no AC) | — |
| C-05 | Python 3.11 stdlib only; entry `python -m taskq` | (cross-cutting; verified in P6; no AC) | — |
| C-06 | Injection blacklist `; \| & $ > < \`` on `submit` | AC-FR01-03, AC-NFR02-02 | — |
| C-07 | Atomic-write crash safety + secret-line redaction | AC-FR01-06, AC-NFR03-01, AC-NFR03-02 | R1, R3 |
| C-08 | `submit`+`status` p95 < 50ms over 100 iterations | AC-NFR01-01 | — |

### 3.2 Risk Coverage (SRS §8 → ACs)

| Risk ID | Risk (canonical) | Mitigation AC(s) | AC count |
|---------|------------------|------------------|----------|
| R1 | Concurrent / interrupted writes corrupt `tasks.json` | AC-FR01-06, AC-NFR03-01 | 2 |
| R2 | subprocess hangs indefinitely | AC-FR02-01 (timeout), AC-FR02-05 (exit 4) | 2 |
| R3 | Secret leakage to persistent store | AC-NFR03-02 | 1 |

### 3.3 AC → Constraint reverse index

| AC ID | Mapped Constraint(s) | Reverse: which constraints this AC satisfies |
|-------|-----------------------|----------------------------------------------|
| AC-FR01-01 | — (input-rejection rule: non-empty; cross-cuts validator layer) | (validation rule distinct from C-06 injection blacklist; P3 unit-test verifies) |
| AC-FR01-02 | — (input-rejection rule: length ≤ 1000; cross-cuts validator layer) | (validation rule distinct from C-06 injection blacklist; P3 boundary test verifies) |
| AC-FR01-03 | C-06 | C-06 (full — injection branch) |
| AC-FR01-04 | — | (no constraint; pure data shape) |
| AC-FR01-05 | — | (no constraint; pure data shape) |
| AC-FR01-06 | C-03, C-07 | C-03, C-07 (atomic-write mechanism) |
| AC-FR01-07 | C-07 | C-07 (corruption detection) |
| AC-FR01-08 | — | (no constraint; "no write on reject" preamble) |
| AC-FR02-01 | C-02 | C-02 (subprocess + no shell=True) |
| AC-FR02-02 | — | (no constraint; pure state semantics) |
| AC-FR02-03 | — | (no constraint; pure data shape) |
| AC-FR02-04 | — | (no constraint; pure retry semantics) |
| AC-FR02-05 | — | (no constraint; pure exit code) |
| AC-FR02-06 | — | (no constraint; pure exception handling) |
| AC-FR03-01..07 | C-01 | C-01 (CLI surface) |
| AC-NFR01-01 | C-08 | C-08 (p95) |
| AC-NFR02-01 | C-02 | C-02 (no shell=True) |
| AC-NFR02-02 | C-06 | C-06 (blacklist coverage) |
| AC-NFR03-01 | C-03, C-07 | C-03, C-07 (atomic-write crash safety) |
| AC-NFR03-02 | C-07 | C-07 (secret-line redaction) |

### 3.4 AC → Risk reverse index

| AC ID | Mapped Risk(s) | Mechanism |
|-------|----------------|-----------|
| AC-FR01-06 | R1 | atomic write (`tmp + os.replace`) survives mid-write crash |
| AC-NFR03-01 | R1 | SIGKILL mid-write test validates atomic-write claim |
| AC-FR02-01 | R2 | `timeout=TASKQ_TASK_TIMEOUT` caps subprocess run time |
| AC-FR02-05 | R2 | timeout → exit 4 surfaces hang to caller |
| AC-NFR03-02 | R3 | regex redaction prevents `sk-...` / `token=...` from reaching persistent store |

---

## 4. Bidirectional Coverage Check (forward × reverse × completeness)

### 4.1 Forward coverage — every AC has design/impl/verify/quality placeholder

| FR/NFR Group | AC count | Phase 2 cells | Phase 3 cells | Phase 4 cells | Phase 6 cells |
|--------------|----------|----------------|----------------|----------------|----------------|
| FR-01 (AC-FR01-01..08) | 8 | 8/8 ⬜ | 8/8 ⬜ | 8/8 ⬜ | 8/8 ⬜ |
| FR-02 (AC-FR02-01..06) | 6 | 6/6 ⬜ | 6/6 ⬜ | 6/6 ⬜ | 6/6 ⬜ |
| FR-03 (AC-FR03-01..07) | 7 | 7/7 ⬜ | 7/7 ⬜ | 7/7 ⬜ | 7/7 ⬜ |
| NFR-01 (AC-NFR01-01) | 1 | 1/1 ⬜ | 1/1 ⬜ | 1/1 ⬜ | 1/1 ⬜ |
| NFR-02 (AC-NFR02-01..02) | 2 | 2/2 ⬜ | 2/2 ⬜ | 2/2 ⬜ | 2/2 ⬜ |
| NFR-03 (AC-NFR03-01..02) | 2 | 2/2 ⬜ | 2/2 ⬜ | 2/2 ⬜ | 2/2 ⬜ |
| **Total** | **25** | **25/25 ⬜** | **25/25 ⬜** | **25/25 ⬜** | **25/25 ⬜** |

### 4.2 Reverse coverage — every constraint/risk has at least one mapped AC

| Source | Count | Mapped-to-AC | Coverage |
|--------|-------|--------------|----------|
| Constraints (C-01..C-08) | 8 | 6 mapped + 2 cross-cutting (C-04, C-05) | 6/8 AC-mapped, 2/8 cross-cutting |
| Risks (R1..R3) | 3 | 3/3 mapped | 3/3 (100%) |

> **Cross-cutting constraints (C-04, C-05)** are intentionally not assigned per-AC rows because they are environmental/runtime invariants verified at P3 (config.py wiring) and P6 (stdlib-only dependency audit) rather than at single-AC granularity. This matches `SPEC_TRACKING.md` §5.

### 4.3 Orphan / unparented check

| Check | Result |
|-------|--------|
| Any AC not linked back to any FR/NFR? | NO — every AC has a parent FR-XX or NFR-XX (25/25) |
| Any FR/NFR not expanded into ACs? | NO — FR-01=8, FR-02=6, FR-03=7, NFR-01=1, NFR-02=2, NFR-03=2 (matches SRS §5 summary) |
| Any constraint with no AC and no cross-cutting slot? | NO — C-04 + C-05 = cross-cutting (P3/P6 verification), C-01..C-03 + C-06..C-08 = AC-mapped |
| Any risk with no mitigation AC? | NO — R1→2 ACs, R2→2 ACs, R3→1 AC |
| Any test boundary owned by AC but untraced to a canonical line? | NO — every AC's verbatim phrase traces to a `SPEC.md` row/block (per SRS §5) |

---

## 5. Status Legend

- ⬜ Pending — not yet started in this phase
- 🔄 In Progress — actively being worked on
- ✅ Passed — verified & signed off
- ❌ Failed — blocked, requires rework

> **Update protocol:** Phase 3 updates the P3 column when each AC passes Gate-1; Phase 4 updates the P4 column from harness manifest qc; Phase 6 updates the P6 column after 14-dim Gate-4 re-verification.

---

## 6. Phase Handoff Hooks (per FR)

| FR | Phase 2 deliverable | Phase 3 deliverable | Phase 4 deliverable | Phase 6 deliverable |
|----|----------------------|----------------------|----------------------|----------------------|
| FR-01 | SAD §storage + ADR (atomic-write choice) + TEST_SPEC for 8 ACs | 8 RED/GREEN tests under `tests/test_fr01_*.py` | Gate-3 manifest qc on all 8 ACs | Gate-4 14-dim re-verification |
| FR-02 | SAD §executor + ADR (no shell=True + timeout) + TEST_SPEC for 6 ACs | 6 RED/GREEN tests under `tests/test_fr02_*.py` | Gate-3 manifest qc on all 6 ACs | Gate-4 14-dim re-verification |
| FR-03 | SAD §cli + ADR (--json + exit-code matrix) + TEST_SPEC for 7 ACs | 7 RED/GREEN tests under `tests/test_fr03_*.py` | Gate-3 manifest qc on all 7 ACs | Gate-4 14-dim re-verification |
| NFR-01 | SAD §perf (p95 budget) + ADR (iteration count) + TEST_SPEC | 1 RED/GREEN test (perf micro-bench) | Gate-3 p95 measurement | Gate-4 latency re-check |
| NFR-02 | ADR (blacklist + grep gate) + TEST_SPEC | 2 RED/GREEN tests (grep + blacklist) | Gate-3 grep + coverage | Gate-4 security re-check |
| NFR-03 | ADR (atomic-write + redaction regex verbatim) + TEST_SPEC | 2 RED/GREEN tests (SIGKILL + regex) | Gate-3 crash + leak | Gate-4 reliability re-check |

---

## 7. Completeness Validation

| Check | Result |
|-------|--------|
| All SRS §3 FRs (FR-01..FR-03) present in forward matrix | PASS (3/3) |
| All SRS §4 NFRs (NFR-01..NFR-03) present in forward matrix | PASS (3/3) |
| All SRS §5 AC rows present in §2 forward tables | PASS (25/25) |
| AC count matches SRS §5 summary | PASS (8+6+7+1+2+2 = 25) |
| Every AC has Phase 2/3/4/6 placeholder column | PASS |
| Every AC has explicit Owner / Test boundary | PASS |
| Constraint C-01..C-08 backward-indexed to ACs (or cross-cutting tagged) | PASS |
| Risk R1..R3 backward-indexed to mitigation ACs | PASS |
| Bidirectional coverage: every AC has FR/NFR parent AND every FR/NFR has ACs | PASS |
| Orphan ACs (no parent) | NONE |
| Orphan FRs/NFRs (no ACs) | NONE |
| NFR-99 / FR-XX-deferred entries required | NONE (per SRS §7 — no canonical TBDs) |

**Completeness verdict:** All 25 ACs + 3 FRs + 3 NFRs + 8 constraints + 3 risks are bidirectionally traced. Forward (req → phase) and reverse (constraint/risk → AC) links all populated. No gaps detected vs `SRS.md` + `SPEC_TRACKING.md`.

---

## 8. Cross-Reference Index

| Item | Where defined | Where traced |
|------|---------------|--------------|
| FR-01..FR-03 (titles, canonical phrases) | `SRS.md` §3 | §2.1–2.3 (forward); §3.3 (reverse) |
| NFR-01..NFR-03 (canonical phrases) | `SRS.md` §4 | §2.4 (forward); §3.3 (reverse) |
| AC-FR01-01..AC-FR03-07, AC-NFR01-01..AC-NFR03-02 | `SRS.md` §3–§4 + §5 summary | §2 (forward matrix); §3.3, §3.4 (reverse indices); §4 (coverage) |
| C-01..C-08 constraints | `SRS.md` §2 | §3.1 (forward); §3.3 (reverse AC→constraint) |
| R1..R3 risks | `SRS.md` §8 | §3.2 (forward); §3.4 (reverse AC→risk) |
| Phase-2/3/4/6 status placeholders | `SPEC_TRACKING.md` §2–§4 | §2 (forward matrix); §6 (phase handoff hooks) |

---

*End of TRACEABILITY_MATRIX.md — generated from `01-requirements/SRS.md` (APPROVED) + `01-requirements/SPEC_TRACKING.md` (APPROVED). Bidirectional forward + reverse traceability for 25 ACs / 3 FRs / 3 NFRs / 8 constraints / 3 risks.*
