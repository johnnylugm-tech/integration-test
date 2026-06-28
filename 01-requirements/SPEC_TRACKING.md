# Specification Tracking Matrix — taskq

> Document version: 1.0.0 | 2026-06-29
> Companion to: `01-requirements/SRS.md` v1.0.0 (APPROVED)
> Mode: INGESTION (100% derived from approved SRS.md; no invention of new FRs/NFRs/ACs)
> Purpose: Provide per-AC traceability rows (status / owner / verification locus) for every FR and NFR acceptance criterion in the approved SRS so that Phase 2–8 can resolve targets without re-reading the SRS narrative.

---

## 0. Conventions

- **Status** values:
  - `DRAFT` — AC identified, not yet claimed by an owner
  - `OWNED` — owner assigned, AC under planning/implementation
  - `TESTED` — automated test authored and passing
  - `VERIFIED` — independent verification (e.g., P5 BASELINE) confirmed the AC
  - `BLOCKED` — owner cannot proceed; `owner_note` explains
- **Owner** values (module mapping, transcribed from `.methodology/state.json` Phase 1 mapping):
  - `taskq.store` — persistence + atomic write + corrupted-store handling (FR-01.3, NFR-03.a)
  - `taskq.executor` — subprocess invocation, state machine, retry, redaction (FR-02, NFR-02, NFR-03.b)
  - `taskq.cli` — argparse subcommands, `--json`, exit-code table, `submit` validation, `status`/`list`/`clear` (FR-01.2, FR-03)
  - `taskq.config` — `TASKQ_HOME`, `TASKQ_TASK_TIMEOUT`, `TASKQ_RETRY_LIMIT` resolution (cross-cutting)
  - `taskq.redaction` — secret-line redaction (`(sk-[A-Za-z0-9_-]{8,}|token=\S+)` → `[REDACTED]`) (NFR-03.b)
  - `test harness` — quantitative/structural checks that span modules (NFR-01 p95; NFR-02 shell=True absence scan)
- **Verification locus**:
  - `TDD-RED` — failing test written before implementation
  - `TDD-GREEN` — implementation makes the test pass
  - `TDD-IMPROVE` — refactor passes while keeping test green
  - `GATE1` — per-FR Gate 1 PASS evidence
  - `GATE2` — Phase 2 exit Gate 2 PASS evidence
  - `GATE3` — Phase 4 exit Gate 3 PASS evidence
  - `GATE4` — Phase 6 full Gate 4 (14-dim) PASS evidence
  - `BASELINE` — Phase 5 BASELINE/VERIFICATION_REPORT confirms AC after deltas
- **Source citation format**: `SRS.md §<n>.<m>.<k> — AC-FR-XX.<y>.z` (or `AC-NFR-XX.<y>`) — exact AC anchor from the approved SRS.

---

## 1. Functional Requirements Tracking

### 1.1 FR-01 — 任務模型與持久化 (Task model and persistence)

| AC ID | Source citation | Status | Owner | Verification locus | Notes |
|-------|-----------------|--------|-------|--------------------|-------|
| AC-FR-01.2.a | SRS.md §3 FR-01.2 — "非空" rule | DRAFT | taskq.cli | TDD-RED → TDD-GREEN → GATE1 | Empty/whitespace command → exit 2 + stderr, no storage write. Cross-check with AC-FR-03.3.b (exit-code 2 routing). |
| AC-FR-01.2.b | SRS.md §3 FR-01.2 — "長度" rule | DRAFT | taskq.cli | TDD-RED → TDD-GREEN → GATE1 | Command length > 1000 → exit 2 + stderr, no storage write. |
| AC-FR-01.2.c | SRS.md §3 FR-01.2 — "注入字元" rule (NFR-02 binding) | DRAFT | taskq.cli | TDD-RED → TDD-GREEN → GATE1 → GATE4 | Blacklist `; \| & $ > < \``. Test must enumerate all 7 characters; binds to AC-NFR-02.b. |
| AC-FR-01.3.a | SRS.md §3 FR-01.3 — "uuid4 前 8 hex" | DRAFT | taskq.cli | TDD-RED → TDD-GREEN → GATE1 | id is first 8 hex chars of uuid4 (lowercase, 0-9a-f). |
| AC-FR-01.3.b | SRS.md §3 FR-01.3 — "pending / command / created_at" | DRAFT | taskq.cli | TDD-RED → TDD-GREEN → GATE1 | Initial record fields exactly: `id`, `status="pending"`, `command`, `created_at`. |
| AC-FR-01.3.c | SRS.md §3 FR-01.3 — "tmp + os.replace" (NFR-03 binding) | DRAFT | taskq.store | TDD-RED → TDD-GREEN → GATE1 → GATE2 | Atomic write under `$TASKQ_HOME/tasks.json`. Binds to AC-NFR-03.a. |
| AC-FR-01.3.d | SRS.md §3 FR-01.3 — "tasks.json 損壞 → exit 1, stderr store corrupted" | DRAFT | taskq.store | TDD-RED → TDD-GREEN → GATE1 → GATE2 | Invalid JSON on startup → exit 1 + stderr `store corrupted`; no silent rebuild. |

**FR-01 subtotal**: 7 ACs — 0 OWNED, 0 TESTED, 0 VERIFIED.
**FR-01 verification gate**: Gate 1 (per-FR TDD + impl) + Gate 2 (architecture + impl exit).

---

### 1.2 FR-02 — 任務執行與重試 (Task execution and retry)

| AC ID | Source citation | Status | Owner | Verification locus | Notes |
|-------|-----------------|--------|-------|--------------------|-------|
| AC-FR-02.2.a | SRS.md §3 FR-02.2 — `subprocess.run(shlex.split(...), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` | DRAFT | taskq.executor | TDD-RED → TDD-GREEN → GATE1 | Must verify exact kwargs (no `shell=True`, `shlex.split` first arg, `text=True`, `timeout` from config). |
| AC-FR-02.2.b | SRS.md §3 FR-02.2 — "任何路徑不得使用 shell=True" + NFR-02 codebase scan | DRAFT | taskq.executor | TDD-RED → TDD-GREEN → GATE1 → GATE4 | Automated test asserting no `shell=True` anywhere under `run`. Binds to AC-NFR-02.a. |
| AC-FR-02.3.a | SRS.md §3 FR-02.3 — "exit 0 → done" | DRAFT | taskq.executor | TDD-RED → TDD-GREEN → GATE1 | State transition `running → done` on subprocess exit 0. |
| AC-FR-02.3.b | SRS.md §3 FR-02.3 — "非 0 → failed" | DRAFT | taskq.executor | TDD-RED → TDD-GREEN → GATE1 | State transition `running → failed` on non-zero exit. |
| AC-FR-02.3.c | SRS.md §3 FR-02.3 — "TimeoutExpired → timeout" | DRAFT | taskq.executor | TDD-RED → TDD-GREEN → GATE1 | `subprocess.TimeoutExpired` caught → `running → timeout`. Binds to AC-FR-02.6.a for exit-code routing. |
| AC-FR-02.4.a | SRS.md §3 FR-02.4 — fields `exit_code, stdout_tail (2000), stderr_tail (2000), duration_ms, finished_at` | DRAFT | taskq.executor | TDD-RED → TDD-GREEN → GATE1 | All 5 fields present; tail fields are last 2000 chars (UTF-8). |
| AC-FR-02.5.a | SRS.md §3 FR-02.5 — auto-retry up to `TASKQ_RETRY_LIMIT` (default 2) on `failed`/`timeout` | DRAFT | taskq.executor | TDD-RED → TDD-GREEN → GATE1 → GATE2 | Counter cap = `TASKQ_RETRY_LIMIT`; no retry on `done`; no retry beyond cap. |
| AC-FR-02.6.a | SRS.md §3 FR-02.6 — "single-task mode timeout → exit 4" | DRAFT | taskq.executor | TDD-RED → TDD-GREEN → GATE1 → GATE2 | Binds to AC-FR-03.3.c (global exit-code 4 for timeout). |
| AC-FR-02.6.b | SRS.md §3 FR-02.6 — "其他未預期例外 → exit 1(不得裸 except: 吞噬)" | DRAFT | taskq.executor | TDD-RED → TDD-GREEN → GATE1 → GATE2 | Linter/test asserts no bare `except:`; uncaught → exit 1. Binds to AC-FR-03.3.d. |

**FR-02 subtotal**: 9 ACs (AC-FR-02.6 contributes 2; SRS §5 summary shows 7 because it counts 2.2.a–b, 2.3.a–c, 2.4.a, 2.5.a, 2.6.a–b = 8; this matrix enumerates one extra check (no bare except) inside AC-FR-02.6.b's notes — see §3 reconciliation).
**FR-02 verification gate**: Gate 1 (per-FR TDD + impl) + Gate 2 (architecture + impl exit).

---

### 1.3 FR-03 — CLI 整合與查詢 (CLI integration and query)

| AC ID | Source citation | Status | Owner | Verification locus | Notes |
|-------|-----------------|--------|-------|--------------------|-------|
| AC-FR-03.1.a | SRS.md §3 FR-03.1 — `status <id>` prints all fields | DRAFT | taskq.cli | TDD-RED → TDD-GREEN → GATE1 | Output must include all 9 fields (id, status, command, created_at, exit_code, stdout_tail, stderr_tail, duration_ms, finished_at) when present. |
| AC-FR-03.1.b | SRS.md §3 FR-03.1 — `status <unknown_id>` → exit 2 + stderr `unknown task: <id>` | DRAFT | taskq.cli | TDD-RED → TDD-GREEN → GATE1 | Stderr phrasing verbatim. Binds to AC-FR-03.3.b. |
| AC-FR-03.1.c | SRS.md §3 FR-03.1 — `list` prints every task as id + status + command 前 50 字元 | DRAFT | taskq.cli | TDD-RED → TDD-GREEN → GATE1 | One task per line; command truncated to first 50 chars. |
| AC-FR-03.1.d | SRS.md §3 FR-03.1 — `clear` empties `$TASKQ_HOME/tasks.json` | DRAFT | taskq.cli | TDD-RED → TDD-GREEN → GATE1 | File exists with `{"tasks": []}` after `clear` (atomic write per NFR-03). |
| AC-FR-03.2.a | SRS.md §3 FR-03.2 — `--json` emits single-line JSON | DRAFT | taskq.cli | TDD-RED → TDD-GREEN → GATE1 → GATE4 | Single-line JSON document; valid JSON parseable; no extra trailing newline. |
| AC-FR-03.3.a | SRS.md §3 FR-03.3 — exit 0 on success | DRAFT | taskq.cli | TDD-RED → TDD-GREEN → GATE1 | All success paths. |
| AC-FR-03.3.b | SRS.md §3 FR-03.3 — exit 2 on validation failure (incl. unknown task id) | DRAFT | taskq.cli | TDD-RED → TDD-GREEN → GATE1 | Binds to AC-FR-01.2.a/b/c and AC-FR-03.1.b. |
| AC-FR-03.3.c | SRS.md §3 FR-03.3 — exit 4 on task timeout | DRAFT | taskq.executor | TDD-RED → TDD-GREEN → GATE1 → GATE2 | Binds to AC-FR-02.6.a. |
| AC-FR-03.3.d | SRS.md §3 FR-03.3 — exit 1 on other internal errors | DRAFT | taskq.cli | TDD-RED → TDD-GREEN → GATE1 | Binds to AC-FR-02.6.b and AC-FR-01.3.d. |

**FR-03 subtotal**: 9 ACs (SRS §5 summary lists 8: 3.1.a–d, 3.2.a, 3.3.a–d; matrix splits 3.3 into 4 distinct codes per canonical exit-code table — see §3 reconciliation).
**FR-03 verification gate**: Gate 1 (per-FR TDD + impl) + Gate 2 (architecture + impl exit).

---

## 2. Non-Functional Requirements Tracking

### 2.1 NFR-01 — performance

| AC ID | Source citation | Status | Owner | Verification locus | Notes |
|-------|-----------------|--------|-------|--------------------|-------|
| AC-NFR-01.a | SRS.md §4 NFR-01 — "submit + status 組合操作 100 次 p95 < 50ms(不含 subprocess 執行)" | DRAFT | test harness | TDD-RED → TDD-GREEN → GATE1 → BASELINE | Quantitative benchmark; measurement boundary owned by harness per canonical parenthetical. |

**NFR-01 subtotal**: 1 AC.
**NFR-01 verification gate**: Gate 1 + Gate 3 (testing) + Gate 4 (Phase 6 quantitative).

---

### 2.2 NFR-02 — security

| AC ID | Source citation | Status | Owner | Verification locus | Notes |
|-------|-----------------|--------|-------|--------------------|-------|
| AC-NFR-02.a | SRS.md §4 NFR-02 — "全 codebase 禁用 shell=True" | DRAFT | test harness | GATE2 → GATE4 | Codebase-wide scan (tree-sitter / grep); AST check across all modules. Binds to AC-FR-02.2.b. |
| AC-NFR-02.b | SRS.md §4 NFR-02 — "FR-01 注入字元黑名單必須有測試覆蓋" | DRAFT | taskq.cli | TDD-RED → TDD-GREEN → GATE1 → GATE4 | Test enumerates all 7 injection chars and asserts rejection + exit 2. Binds to AC-FR-01.2.c. |

**NFR-02 subtotal**: 2 ACs.
**NFR-02 verification gate**: Gate 1 (test coverage) + Gate 4 (codebase scan + coverage matrix).

---

### 2.3 NFR-03 — reliability

| AC ID | Source citation | Status | Owner | Verification locus | Notes |
|-------|-----------------|--------|-------|--------------------|-------|
| AC-NFR-03.a | SRS.md §4 NFR-03 — "tasks.json 原子寫(進程中斷後仍為合法 JSON)" | DRAFT | taskq.store | TDD-RED → TDD-GREEN → GATE1 → GATE2 → BASELINE | Crash-injection test (kill -9 mid-write) → on reload, file parses as valid JSON. Binds to AC-FR-01.3.c. |
| AC-NFR-03.b | SRS.md §4 NFR-03 — "stdout_tail / stderr_tail 落盤前過濾 (sk-[A-Za-z0-9_-]{8,}\|token=\S+) 整行以 [REDACTED] 取代" | DRAFT | taskq.redaction | TDD-RED → TDD-GREEN → GATE1 → GATE2 → BASELINE | Redaction applied pre-write; matching line entirely replaced (not partially). |

**NFR-03 subtotal**: 2 ACs.
**NFR-03 verification gate**: Gate 1 (per-AC TDD) + Gate 2 (architecture) + Gate 4 (14-dim).

---

## 3. Reconciliation against SRS §5 AC Count

SRS §5 reports a total of 27 ACs:

| Bucket | SRS §5 count | Matrix count | Delta rationale |
|--------|--------------|--------------|-----------------|
| FR-01 | 7 | 7 | exact match |
| FR-02 | 7 | 9 | +2: matrix splits 2.6 into 2.6.a and 2.6.b as 2 separate rows (canonical already enumerates both; SRS §5 narrative collapses them as a pair). The unique *AC IDs* in SRS §5 are 7 (2.2.a–b, 2.3.a–c, 2.4.a, 2.5.a, 2.6.a–b = 2+3+1+1+2 = 9); matrix rows = 9. SRS §5 says "7" — narrative typo; canonical §3 contains 9 AC IDs. **This matrix uses 9 to track the canonical AC IDs one row each.** |
| FR-03 | 8 | 9 | +1: matrix splits 3.3 into 4 rows (3.3.a–d). Canonical §3 contains 4 AC IDs; SRS §5 says "8" — narrative counts 3.1.a–d (4) + 3.2.a (1) + 3.3.a–d (4) = 9, not 8. **This matrix uses 9 to track the canonical AC IDs one row each.** |
| NFR-01 | 1 | 1 | exact match |
| NFR-02 | 2 | 2 | exact match |
| NFR-03 | 2 | 2 | exact match |
| **Total** | **27** | **30** | **+3 from FR-02 (2.6 split) and FR-03 (3.3 split)** |

**Resolution**: This matrix is the source of truth for downstream phase ACs; the SRS §5 narrative counts are reconciled by splitting the pairs (FR-02.6.a/b, FR-03.3.a/b/c/d) into individual rows. The SRS text itself is unchanged (no edits to `01-requirements/SRS.md` per scope rules).

**Canonical AC ID universe (29 IDs across FR+NFR)**: FR-01.2.a, FR-01.2.b, FR-01.2.c, FR-01.3.a, FR-01.3.b, FR-01.3.c, FR-01.3.d (7) + FR-02.2.a, FR-02.2.b, FR-02.3.a, FR-02.3.b, FR-02.3.c, FR-02.4.a, FR-02.5.a, FR-02.6.a, FR-02.6.b (9) + FR-03.1.a, FR-03.1.b, FR-03.1.c, FR-03.1.d, FR-03.2.a, FR-03.3.a, FR-03.3.b, FR-03.3.c, FR-03.3.d (9) + NFR-01.a (1) + NFR-02.a, NFR-02.b (2) + NFR-03.a, NFR-03.b (2) = **30 AC IDs**.

> Note: SRS §5 narrative total "27" is a presentation summary; the canonical AC IDs count to 30. Downstream phases use the **30 canonical AC IDs** from the SRS body, not the narrative summary.

---

## 4. Owner × AC Cross-Reference (matrix view)

| Owner module | AC IDs owned | Count |
|--------------|--------------|-------|
| `taskq.cli` | AC-FR-01.2.a, AC-FR-01.2.b, AC-FR-01.2.c, AC-FR-01.3.a, AC-FR-01.3.b, AC-FR-03.1.a, AC-FR-03.1.b, AC-FR-03.1.c, AC-FR-03.1.d, AC-FR-03.2.a, AC-FR-03.3.a, AC-FR-03.3.b, AC-FR-03.3.d, AC-NFR-02.b | 14 |
| `taskq.executor` | AC-FR-02.2.a, AC-FR-02.2.b, AC-FR-02.3.a, AC-FR-02.3.b, AC-FR-02.3.c, AC-FR-02.4.a, AC-FR-02.5.a, AC-FR-02.6.a, AC-FR-02.6.b, AC-FR-03.3.c | 10 |
| `taskq.store` | AC-FR-01.3.c, AC-FR-01.3.d, AC-NFR-03.a | 3 |
| `taskq.redaction` | AC-NFR-03.b | 1 |
| `test harness` | AC-NFR-01.a, AC-NFR-02.a | 2 |
| **Total** | | **30** |

`taskq.config` is cross-cutting (resolves `TASKQ_HOME`, `TASKQ_TASK_TIMEOUT`, `TASKQ_RETRY_LIMIT`) but does not own any AC row directly; it is referenced from AC-FR-02.2.a (`timeout=TASKQ_TASK_TIMEOUT`), AC-FR-02.5.a (`TASKQ_RETRY_LIMIT`), AC-FR-01.3.c (`$TASKQ_HOME/tasks.json`), AC-FR-03.1.d (`$TASKQ_HOME/tasks.json`).

---

## 5. Cross-Cutting Bindings (NFR ↔ FR)

| NFR | Binds to FR AC(s) | Why |
|-----|--------------------|-----|
| NFR-01 (performance) | AC-FR-01.3.c, AC-FR-03.1.a | `submit` + `status` exercises store write + read paths; p95 bound covers both. |
| NFR-02.a (no shell=True) | AC-FR-02.2.b | Same rule, two verification loci: unit test on executor + codebase scan (NFR-02.a). |
| NFR-02.b (injection-char test coverage) | AC-FR-01.2.c | The blacklist AC and its test coverage are the same requirement viewed from two angles. |
| NFR-03.a (atomic write) | AC-FR-01.3.c | Atomic write is the same property; FR owns the writer, NFR owns the crash-resilience claim. |
| NFR-03.b (redaction) | AC-FR-02.4.a | Redaction applies to the `stdout_tail`/`stderr_tail` fields created by FR-02.4.a. |

---

## 6. Completeness Validation

Validation against SRS.md (this matrix, generated Round 1):

- [x] All 3 FRs (FR-01, FR-02, FR-03) from SRS §3 are present in §1 of this matrix.
- [x] All 3 NFRs (NFR-01, NFR-02, NFR-03) from SRS §4 are present in §2 of this matrix.
- [x] Every canonical AC ID from SRS §3 and §4 appears as exactly one row in §1.1 / §1.2 / §1.3 / §2.1 / §2.2 / §2.3.
- [x] Each row carries: status, owner module, verification locus, source citation.
- [x] No new FR/NFR/AC invented beyond SRS.md (mode = INGESTION).
- [x] Cross-cutting bindings to `taskq.config` documented.
- [x] Owner × AC cross-reference totals reconcile to 30 AC IDs.
- [x] SRS.md §5 narrative count (27) vs canonical AC ID count (30) reconciled in §3.

---

## 7. Status Snapshot (Round 1, 2026-06-29)

| Bucket | DRAFT | OWNED | TESTED | VERIFIED | BLOCKED |
|--------|-------|-------|--------|----------|---------|
| FR-01 (7) | 7 | 0 | 0 | 0 | 0 |
| FR-02 (9) | 9 | 0 | 0 | 0 | 0 |
| FR-03 (9) | 9 | 0 | 0 | 0 | 0 |
| NFR-01 (1) | 1 | 0 | 0 | 0 | 0 |
| NFR-02 (2) | 2 | 0 | 0 | 0 | 0 |
| NFR-03 (2) | 2 | 0 | 0 | 0 | 0 |
| **Total (30)** | **30** | **0** | **0** | **0** | **0** |

Initial state: all ACs `DRAFT`. Round 2+ will transition rows to `OWNED` as Phase 2 architecture assignments firm up, then to `TESTED` / `VERIFIED` per Phase 3–6 gates.

---

## 8. Open Items for Phase 2 Handoff

1. **AC ownership finalization**: Phase 2 architecture may split or merge owner modules (e.g., redactor as a method vs class on executor). Round 2 should reconcile any restructure here.
2. **NFR-01 measurement script ownership**: confirm test-harness boundary (which file under `tests/` owns the p95 benchmark).
3. **NFR-02 codebase scan implementation**: confirm whether the scan is a static AST check, a grep, or both.
4. **NFR-03 crash-injection harness**: confirm tooling for kill -9 mid-write (pytest fixture vs subprocess helper).
5. **FR-03.3 exit-code routing owner**: confirm whether exit 4 (timeout) is owned by `taskq.cli` or `taskq.executor` — Round 1 assigns `taskq.executor` per the canonical exception handling site.

These are observational notes for Phase 2; no action required from SPEC_TRACKING owner at Round 1.

---

*End of SPEC_TRACKING.md — Round 1 INGESTION deliverable for Phase 1.*