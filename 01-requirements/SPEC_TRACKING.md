# Specification Tracking Matrix — taskq

> Source of truth: `01-requirements/SRS.md` (APPROVED, transcribed from `SPEC.md` v2.0.0, 2026-06-15).
> Purpose: track every FR/NFR + AC through downstream phases (Phase 2 Architecture → Phase 3 Implementation → Phase 4 Testing → Phase 6 Quality).
> Mode: INGESTION. All rows lifted 1:1 from SRS.md §3–§4 + §5 summary table. No invention.

---

## 1. Project Metadata

| Field | Value |
|-------|-------|
| Project | `taskq` |
| SRS version | `SPEC.md` v2.0.0 (2026-06-15) |
| Language | Python 3.11 |
| Runtime | stdlib only (zero external deps); entry `python -m taskq` |
| Total FRs | 3 (FR-01, FR-02, FR-03) |
| Total NFRs | 3 (NFR-01, NFR-02, NFR-03) |
| Total ACs | 25 (FR-01×8, FR-02×6, FR-03×7, NFR-01×1, NFR-02×2, NFR-03×2) |
| Constraints | 8 (C-01..C-08, see SRS §2) |

---

## 2. Functional Requirements Tracking

| FR ID | Title | AC count | Phase 2 (SAD/ADR/TEST_SPEC) | Phase 3 (TDD impl) | Phase 4 (verify) | Phase 6 (quality) | Status | Owner |
|-------|-------|----------|------------------------------|---------------------|-------------------|--------------------|--------|-------|
| FR-01 | 任務模型與持久化 (Task Model & Persistence) | 8 | ⬜ Pending | ⬜ Pending | ⬜ Pending | ⬜ Pending | **Not Started** | requirements-engineer → architect → implementer → qa |
| FR-02 | 任務執行與重試 (Task Execution & Retry) | 6 | ⬜ Pending | ⬜ Pending | ⬜ Pending | ⬜ Pending | **Not Started** | requirements-engineer → architect → implementer → qa |
| FR-03 | CLI 整合與查詢 (CLI Integration & Query) | 7 | ⬜ Pending | ⬜ Pending | ⬜ Pending | ⬜ Pending | **Not Started** | requirements-engineer → architect → implementer → qa |

---

## 3. Non-Functional Requirements Tracking

| NFR ID | Title | AC count | Phase 2 (SAD/ADR/TEST_SPEC) | Phase 3 (TDD impl) | Phase 4 (verify) | Phase 6 (quality) | Status | Owner |
|--------|-------|----------|------------------------------|---------------------|-------------------|--------------------|--------|-------|
| NFR-01 | Performance (p95 latency) | 1 | ⬜ Pending | ⬜ Pending | ⬜ Pending | ⬜ Pending | **Not Started** | requirements-engineer → architect → implementer → qa |
| NFR-02 | Security (shell=True forbidden + blacklist coverage) | 2 | ⬜ Pending | ⬜ Pending | ⬜ Pending | ⬜ Pending | **Not Started** | requirements-engineer → architect → implementer → qa |
| NFR-03 | Reliability (atomic write + secret-line redaction) | 2 | ⬜ Pending | ⬜ Pending | ⬜ Pending | ⬜ Pending | **Not Started** | requirements-engineer → architect → implementer → qa |

---

## 4. Acceptance Criteria Detail (verbatim from SRS.md §5)

### 4.1 FR-01 Acceptance Criteria

| AC ID | Requirement | Verbatim canonical phrase | Owner (test harness) | Phase 2 | Phase 3 | Phase 4 | Phase 6 | Status |
|-------|-------------|---------------------------|----------------------|---------|---------|---------|---------|--------|
| AC-FR01-01 | FR-01 non-empty | `非空 \| 命令為空或全空白 → 拒絕` | rejection observable on empty/whitespace input | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR01-02 | FR-01 length | `長度 \| 命令 > 1000 字元 → 拒絕` | boundary test at 1000 / 1001 chars | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR01-03 | FR-01 injection | `注入字元 \| 命令含 ; \| & $ > < \` 任一 → 拒絕 (NFR-02)` | per-character coverage | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR01-04 | FR-01 id | `產生 task id (uuid4 前 8 hex)` | format = `[0-9a-f]{8}` | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR01-05 | FR-01 pending state | `狀態 pending,記錄 command、created_at` | field presence on read | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR01-06 | FR-01 atomic write | `原子寫入 $TASKQ_HOME/tasks.json (tmp + os.replace)` | crash-injection test | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR01-07 | FR-01 corruption | `tasks.json 損壞(非法 JSON)→ 啟動偵測 → exit 1,stderr store corrupted(不靜默重建)` | startup detection + exit-1 | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR01-08 | FR-01 no write on reject | (preamble) **不寫入存儲** | storage byte-for-byte unchanged | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |

### 4.2 FR-02 Acceptance Criteria

| AC ID | Requirement | Verbatim canonical phrase | Owner (test harness) | Phase 2 | Phase 3 | Phase 4 | Phase 6 | Status |
|-------|-------------|---------------------------|----------------------|---------|---------|---------|---------|--------|
| AC-FR02-01 | FR-02 invocation | `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT); 任何路徑不得使用 shell=True` | code grep + behavior test | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR02-02 | FR-02 state machine | `pending → running → done \| failed \| timeout` | state transitions table | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR02-03 | FR-02 result fields | `exit_code、stdout_tail(末 2000 字元)、stderr_tail(末 2000 字元)、duration_ms、finished_at` | field presence + tail length | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR02-04 | FR-02 retry | `run 結果為 failed/timeout 時自動重試,上限 TASKQ_RETRY_LIMIT 次(預設 2)` | retry-counter test | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR02-05 | FR-02 timeout exit | `單一任務模式下 timeout 結果 → exit 4` | single-task-mode exit code | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR02-06 | FR-02 unhandled exit | `其他未預期例外 → exit 1(不得裸 except: 吞噬)` | exception injection test | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |

### 4.3 FR-03 Acceptance Criteria

| AC ID | Requirement | Verbatim canonical phrase | Owner (test harness) | Phase 2 | Phase 3 | Phase 4 | Phase 6 | Status |
|-------|-------------|---------------------------|----------------------|---------|---------|---------|---------|--------|
| AC-FR03-01 | FR-03 submit | `submit "<cmd>" \| FR-01` | routing test | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR03-02 | FR-03 run | `run <id> \| FR-02` | routing test | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR03-03 | FR-03 status unknown | `unknown id → exit 2 + unknown task: <id>` | message + exit code | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR03-04 | FR-03 list truncation | `command 前 50 字元` | 50/51 char boundary | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR03-05 | FR-03 clear | `清空 $TASKQ_HOME/tasks.json` | post-clear list is empty | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR03-06 | FR-03 --json | `全域 flag --json:機器可讀輸出(單行 JSON)` | JSON parse round-trip | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-FR03-07 | FR-03 exit codes | `0 成功 / 2 輸入驗證錯誤(含 unknown task id)/ 4 任務 timeout / 1 其他內部錯誤` | full exit-code matrix | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |

### 4.4 NFR Acceptance Criteria

| AC ID | Requirement | Verbatim canonical phrase | Owner (test harness) | Phase 2 | Phase 3 | Phase 4 | Phase 6 | Status |
|-------|-------------|---------------------------|----------------------|---------|---------|---------|---------|--------|
| AC-NFR01-01 | NFR-01 p95 | `p95 < 50ms(不含 subprocess 執行)` | harness owns subprocess-exclusion measurement | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-NFR02-01 | NFR-02 shell=True | `全 codebase 禁用 shell=True` | repo-wide grep | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-NFR02-02 | NFR-02 coverage | `FR-01 注入字元黑名單必須有測試覆蓋` | test-count on blacklist cases | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-NFR03-01 | NFR-03 atomic | `原子寫(進程中斷後仍為合法 JSON)` | SIGKILL mid-write | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |
| AC-NFR03-02 | NFR-03 redaction | `(sk-[A-Za-z0-9_-]{8,}\|token=\S+) 整行以 [REDACTED] 取代` | regex unit + integration test | ⬜ | ⬜ | ⬜ | ⬜ | **Not Started** |

---

## 5. Constraint Coverage (from SRS §2)

| Constraint | Description | Mapped AC(s) | Status |
|------------|-------------|--------------|--------|
| C-01 | CLI via argparse subcommands | AC-FR03-01..07 | **Not Started** |
| C-02 | subprocess + shlex.split; shell=True forbidden everywhere | AC-FR02-01, AC-NFR02-01 | **Not Started** |
| C-03 | JSON atomic write (tmp + os.replace) | AC-FR01-06, AC-NFR03-01 | **Not Started** |
| C-04 | TASKQ_* env-vars via config.py | (cross-cutting; verified in P3/P4) | **Not Started** |
| C-05 | Python 3.11 stdlib only; entry `python -m taskq` | (cross-cutting; verified in P6) | **Not Started** |
| C-06 | Injection blacklist `; \| & $ > < \`` on submit | AC-FR01-03, AC-NFR02-02 | **Not Started** |
| C-07 | Atomic-write crash safety + secret-line redaction | AC-FR01-06, AC-NFR03-01, AC-NFR03-02 | **Not Started** |
| C-08 | submit+status p95 < 50ms over 100 iterations | AC-NFR01-01 | **Not Started** |

---

## 6. Risk Coverage (from SRS §8)

| Risk ID | Risk | Mitigation AC(s) | Status |
|---------|------|------------------|--------|
| R1 | Concurrent / interrupted writes corrupt `tasks.json` | AC-FR01-06, AC-NFR03-01 | **Not Started** |
| R2 | subprocess hangs indefinitely | AC-FR02-01 (timeout), AC-FR02-05 (exit 4) | **Not Started** |
| R3 | Secret leakage to persistent store | AC-NFR03-02 | **Not Started** |

---

## 7. Completeness Validation

| Check | Result |
|-------|--------|
| All SRS §3 FRs (FR-01..FR-03) present in §2 matrix | PASS (3/3) |
| All SRS §4 NFRs (NFR-01..NFR-03) present in §3 matrix | PASS (3/3) |
| All SRS §5 AC rows present in §4 detail tables | PASS (25/25) |
| AC count matches SRS §5 summary | PASS (8+6+7+1+2+2 = 25) |
| Every AC has Phase 2/3/4/6 placeholder column | PASS |
| Every AC has explicit Status | PASS |
| Constraint C-01..C-08 mapped to ACs (cross-cutting tagged) | PASS |
| Risk R1..R3 mapped to mitigation ACs | PASS |
| NFR-99 / FR-XX-deferred entries required | NONE (per SRS §7 — no canonical TBDs) |

**Completeness verdict:** All 25 ACs + 3 FRs + 3 NFRs + 8 constraints + 3 risks are tracked. No gaps detected vs SRS.md.

---

## 8. Status Legend

- ⬜ Pending — not yet started in this phase
- 🔄 In Progress — actively being worked on
- ✅ Passed — verified & signed off
- ❌ Failed — blocked, requires rework

---

## 9. Phase Handoff Hooks

- **Phase 2 (Architecture):** Read §2/§3 to scope SAD/ADR/TEST_SPEC per FR. Every AC in §4 must have an architectural decision or be marked as "no architecture needed" (test-only boundary).
- **Phase 3 (Implementation):** Per-FR TDD. Every AC in §4 must have a RED/GREEN test. Update this file's status columns when each AC passes its Gate-1 verdict.
- **Phase 4 (Testing):** Verify every AC in §4 against harness manifest. Gate-3 verdict = all 25 ACs ✅.
- **Phase 6 (Quality):** Re-verify all 25 ACs + 8 constraints + 3 risks under 14-dim Gate-4.

---

*End of SPEC_TRACKING.md — generated from `01-requirements/SRS.md` (APPROVED).*