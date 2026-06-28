# Traceability Matrix — taskq

> Source of truth: `/Users/johnny/projects/integration-test/01-requirements/SRS.md` (v1.0.0, 2026-06-29)
> Upstream deliverable: `/Users/johnny/projects/integration-test/01-requirements/SPEC_TRACKING.md` (v1.0.0, APPROVED-pending-B-review)
> Project role: integration-test target for harness-methodology v2.12.0 pipeline validation
> Phase: 1 — Requirements | Sub-Task: 3/4 (TRACEABILITY_MATRIX.md)
> Language: Python 3.11 (zero external runtime dependencies — stdlib only)

## 1. Document Metadata

| Field | Value |
|-------|-------|
| Document ID | TRACEABILITY_MATRIX.md |
| Created | 2026-06-29 |
| Author Role | REQUIREMENTS_ENGINEER (Agent A) |
| Source Spec | SRS.md v1.0.0 + SPEC_TRACKING.md v1.0.0 |
| Project Codename | taskq |
| Language | Python 3.11 (stdlib only) |
| Total FRs | 3 (FR-01, FR-02, FR-03) |
| Total NFRs | 3 (NFR-01, NFR-02, NFR-03) |
| Total Constraints | 7 (C-01 ~ C-07) |
| Total Config Vars | 3 (TASKQ_HOME, TASKQ_TASK_TIMEOUT, TASKQ_RETRY_LIMIT) |
| Total Risks | 3 (R1, R2, R3) |
| Traceability Direction | Bidirectional (FR → Design → Test, and Test → FR) |

## 2. Forward Traceability (FR → Design → Test)

Each FR row links: requirement → design element(s) in the planned module layout → planned test cases. Test IDs use the `TC-FRxx-NN` convention that downstream Sub-Task 4/4 (TEST_INVENTORY.yaml) will enumerate.

### 2.1 Functional Requirements

| FR ID | Title | Design Elements (planned modules) | Test Cases | AC Count | Spec Reference |
|-------|-------|-----------------------------------|------------|----------|----------------|
| FR-01 | 任務模型與持久化 | `taskq.models.task` (Task dataclass); `taskq.store.json_store` (read/atomic_write/corruption_detect); `taskq.cli.submit` (validator dispatcher) | TC-FR01-01a..g | 7 | SRS §3.1.1, §3.1.2 |
| FR-02 | 任務執行與重試 | `taskq.executor.runner` (subprocess.run + shlex.split); `taskq.models.state` (state machine); `taskq.executor.retry` (retry policy); FR-02 §3.2.5 exit-code mapping | TC-FR02-01..06 | 6 | SRS §3.2.1–§3.2.5 |
| FR-03 | CLI 整合與查詢 | `taskq.cli.main` (argparse dispatcher); `taskq.cli.submit / run / status / list / clear`; `--json` formatter; FR-03 §3.3.2 exit-code table | TC-FR03-01..06 | 6 | SRS §3.3, §3.3.1, §3.3.2 |

#### 2.1.1 FR-01 Sub-cases (1:1 with TC-FR01-01a..g)

| TC ID | Sub-case | Design Element | AC |
|-------|----------|----------------|-----|
| TC-FR01-01a | Empty command rejection | `taskq.cli.submit` validator → `taskq.store.json_store` (no-write path) | `taskq submit ""` exits 2 + no store write |
| TC-FR01-01b | Whitespace-only command rejection | `taskq.cli.submit` validator | `taskq submit "   "` exits 2 |
| TC-FR01-01c | Length-limit rejection (1001 chars) | `taskq.cli.submit` validator | 1001-char command exits 2 |
| TC-FR01-01d | Length-limit acceptance (1000 chars) | `taskq.cli.submit` validator | 1000-char command accepted |
| TC-FR01-01e | Injection-char blacklist (`;`) | `taskq.cli.submit` validator + NFR-02 per-char unit | `;` rejected |
| TC-FR01-01f | Injection-char blacklist (`|` `&` `$` `>` `<` `` ` ``) | `taskq.cli.submit` validator + NFR-02 per-char unit | each remaining char rejected |
| TC-FR01-01g | Pass condition: id 8-hex + status=pending + atomic write + corruption-detect | `taskq.models.task` + `taskq.store.json_store` | persisted record has {id, command, status=pending, created_at}; tmp + os.replace; corrupted JSON → exit 1 + stderr `store corrupted` |

#### 2.1.2 FR-02 Sub-cases (1:1 with TC-FR02-01..06)

| TC ID | Sub-case | Design Element | AC |
|-------|----------|----------------|-----|
| TC-FR02-01 | Execution via subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=...) | `taskq.executor.runner` | no shell=True; kwargs verbatim canonical |
| TC-FR02-02 | State transition: exit 0 → done | `taskq.models.state` | exit 0 → status=done |
| TC-FR02-03 | State transition: non-zero → failed | `taskq.models.state` | non-zero → status=failed |
| TC-FR02-04 | State transition: TimeoutExpired → timeout (single-task exit 4) | `taskq.executor.runner` + FR-02 §3.2.5 exit-code mapping | TimeoutExpired → status=timeout + exit 4 |
| TC-FR02-05 | Result fields persisted: exit_code, stdout_tail, stderr_tail, duration_ms, finished_at | `taskq.models.task` result schema | all 5 fields present in store record |
| TC-FR02-06 | Retry policy: failed/timeout → retry up to TASKQ_RETRY_LIMIT; done → no retry | `taskq.executor.retry` | retry counter ≤ TASKQ_RETRY_LIMIT; done path unchanged |

#### 2.1.3 FR-03 Sub-cases (1:1 with TC-FR03-01..06)

| TC ID | Sub-case | Design Element | AC |
|-------|----------|----------------|-----|
| TC-FR03-01 | `submit "<cmd>"` dispatches to FR-01 | `taskq.cli.submit` | TC-FR01 cases reachable via `submit` subcommand |
| TC-FR03-02 | `run <id>` dispatches to FR-02 | `taskq.cli.run` | TC-FR02 cases reachable via `run` subcommand |
| TC-FR03-03 | `status <id>` prints all fields; unknown id → exit 2 + `unknown task: <id>` | `taskq.cli.status` | known id → fields; unknown id → exit 2 + stderr |
| TC-FR03-04 | `list` shows id + status + command truncated to 50 chars | `taskq.cli.list` | output format enforced |
| TC-FR03-05 | `clear` empties tasks.json (valid empty JSON) | `taskq.cli.clear` + `taskq.store.json_store` | tasks.json valid empty JSON after clear |
| TC-FR03-06 | `--json` flag → single-line JSON parseable by json.loads | `taskq.cli.main` JSON formatter | output parses with json.loads |

### 2.2 Non-Functional Requirements

| NFR ID | Title | Design Elements | Test Cases | AC Count | Spec Reference |
|--------|-------|-----------------|------------|----------|----------------|
| NFR-01 | Performance | `taskq.cli.submit` + `taskq.cli.status`; harness benchmark harness | TC-NFR01-01 | 1 | SRS §4 |
| NFR-02 | Security | `taskq.cli.submit` blacklist + codebase-wide grep gate | TC-NFR02-01a..g | 2 (with 7-char sub-coverage) | SRS §4 |
| NFR-03 | Reliability | `taskq.store.json_store` (tmp + os.replace) + `taskq.redact` (regex line-replace) | TC-NFR03-01..02 | 2 | SRS §4 |

#### 2.2.1 NFR Sub-cases (1:1 with TC-NFRxx-NN)

| TC ID | Sub-case | Design Element | AC |
|-------|----------|----------------|-----|
| TC-NFR01-01 | p95 of 100 combined submit+status invocations < 50ms (excludes subprocess exec) | benchmark harness | p95 < 50ms |
| TC-NFR02-01 | Codebase grep: zero `shell=True` in production code | grep gate (P5) | 0 hits |
| TC-NFR02-02a..g | Per-char blacklist unit tests (`;` `\|` `&` `$` `>` `<` `` ` ``) | `taskq.cli.submit` validator unit tests | each char rejected independently |
| TC-NFR03-01 | Atomic-write kill simulation: mid-write kill leaves valid JSON | `taskq.store.json_store` | tmp + os.replace semantics verified |
| TC-NFR03-02 | Redaction: lines matching `sk-[A-Za-z0-9_-]{8,}` OR `token=\S+` → `[REDACTED]` | `taskq.redact` | pattern matched; line replaced before persistence |

### 2.3 Constraint → Design → Test

| C ID | Constraint | Design Element | Verification | Test Phase |
|------|------------|----------------|--------------|------------|
| C-01 | Python 3.11 stdlib only | project layout (no requirements.txt runtime deps) | P3 import scan + lockfile absence | P3 |
| C-02 | `python -m taskq` CLI entry | `taskq/__main__.py` | P4 argparse entry | P4 |
| C-03 | `shell=True` forbidden everywhere | codebase-wide convention + TC-NFR02-01 | P5 grep gate | P5 |
| C-04 | `tasks.json` atomic write (tmp + os.replace) | `taskq.store.json_store` + TC-NFR03-01 | P5 kill-signal sim | P5 |
| C-05 | Configuration via TASKQ_* env vars | `taskq.config` | P3 module test | P3 |
| C-06 | `shlex.split` for command tokenization | `taskq.executor.runner` + TC-FR02-01 | P3 code review | P3 |
| C-07 | Runtime zero external dependencies | `requirements.txt` empty / absent | P3 import audit | P3 |

### 2.4 Config Variable → Design → Test

| Var | Default | Design Element | Test Case | AC |
|-----|---------|----------------|-----------|-----|
| TASKQ_HOME | `.taskq` | `taskq.config.home` | TC-CFG-01 | default applied when env unset |
| TASKQ_TASK_TIMEOUT | `10.0` | `taskq.config.timeout` | TC-CFG-02 | default applied when env unset; used by FR-02 |
| TASKQ_RETRY_LIMIT | `2` | `taskq.config.retry_limit` | TC-CFG-03 | default applied when env unset; used by FR-02 §3.2.4 |

### 2.5 Risk → Mitigation → Test

| Risk | Description | Mitigation (FR/NFR) | Test Cases |
|------|-------------|----------------------|------------|
| R1 | 並發/中斷寫入損壞 | NFR-03 atomic write (C-04) | TC-NFR03-01 |
| R2 | subprocess 懸掛 | FR-02 timeout (C-06 + TASKQ_TASK_TIMEOUT) | TC-FR02-04 |
| R3 | secret 落盤洩漏 | NFR-03 redaction | TC-NFR03-02 |

## 3. Backward Traceability (Test → FR/NFR)

Every test case maps back to its originating requirement. Test IDs that do not resolve to a FR/NFR row below are **orphans** and must be removed.

| TC ID | Resolves To | Direction |
|-------|-------------|-----------|
| TC-FR01-01a | FR-01 (empty) | forward+backward |
| TC-FR01-01b | FR-01 (whitespace) | forward+backward |
| TC-FR01-01c | FR-01 (length > 1000) | forward+backward |
| TC-FR01-01d | FR-01 (length ≤ 1000) | forward+backward |
| TC-FR01-01e | FR-01 + NFR-02 (blacklist `;`) | forward+backward (cross-link) |
| TC-FR01-01f | FR-01 + NFR-02 (blacklist remaining chars) | forward+backward (cross-link) |
| TC-FR01-01g | FR-01 (id + status + atomic + corruption-detect) | forward+backward |
| TC-FR02-01 | FR-02 §3.2.1 | forward+backward |
| TC-FR02-02 | FR-02 §3.2.2 (done) | forward+backward |
| TC-FR02-03 | FR-02 §3.2.2 (failed) | forward+backward |
| TC-FR02-04 | FR-02 §3.2.2 + §3.2.5 (timeout → exit 4) | forward+backward |
| TC-FR02-05 | FR-02 §3.2.3 (result fields) | forward+backward |
| TC-FR02-06 | FR-02 §3.2.4 (retry) | forward+backward |
| TC-FR03-01 | FR-03 (submit dispatch) → FR-01 | forward+backward |
| TC-FR03-02 | FR-03 (run dispatch) → FR-02 | forward+backward |
| TC-FR03-03 | FR-03 (status) | forward+backward |
| TC-FR03-04 | FR-03 (list) | forward+backward |
| TC-FR03-05 | FR-03 (clear) | forward+backward |
| TC-FR03-06 | FR-03 §3.3.1 (--json) | forward+backward |
| TC-NFR01-01 | NFR-01 | forward+backward |
| TC-NFR02-01 | NFR-02 (shell=True grep) | forward+backward |
| TC-NFR02-02a..g | NFR-02 (per-char blacklist) | forward+backward (cross-link to FR-01) |
| TC-NFR03-01 | NFR-03 (atomic write) + C-04 | forward+backward |
| TC-NFR03-02 | NFR-03 (redaction) | forward+backward |
| TC-CFG-01 | TASKQ_HOME | forward+backward |
| TC-CFG-02 | TASKQ_TASK_TIMEOUT + FR-02 | forward+backward |
| TC-CFG-03 | TASKQ_RETRY_LIMIT + FR-02 §3.2.4 | forward+backward |

## 4. Coverage Matrix

### 4.1 FR Coverage

| FR ID | # Test Cases | Test IDs | Coverage Status |
|-------|--------------|----------|-----------------|
| FR-01 | 7 | TC-FR01-01a..g | COMPLETE |
| FR-02 | 6 | TC-FR02-01..06 | COMPLETE |
| FR-03 | 6 | TC-FR03-01..06 | COMPLETE |
| **Total** | **19** | — | **100%** |

### 4.2 NFR Coverage

| NFR ID | # Test Cases | Test IDs | Coverage Status |
|--------|--------------|----------|-----------------|
| NFR-01 | 1 | TC-NFR01-01 | COMPLETE |
| NFR-02 | 2 (with 7-char sub-coverage → 9 TCs total) | TC-NFR02-01 + TC-NFR02-02a..g | COMPLETE |
| NFR-03 | 2 | TC-NFR03-01, TC-NFR03-02 | COMPLETE |
| **Total** | **5 (12 with sub-coverage)** | — | **100%** |

### 4.3 Constraint Coverage

| C ID | # Test Cases | Test Phase | Coverage Status |
|------|--------------|------------|-----------------|
| C-01 | 1 (import scan) | P3 | COMPLETE |
| C-02 | 1 (argparse entry) | P4 | COMPLETE |
| C-03 | 1 (grep gate) → TC-NFR02-01 | P5 | COMPLETE |
| C-04 | 1 → TC-NFR03-01 | P5 | COMPLETE |
| C-05 | 1 (config module) | P3 | COMPLETE |
| C-06 | 1 → TC-FR02-01 | P3 | COMPLETE |
| C-07 | 1 (import audit) | P3 | COMPLETE |
| **Total** | **7** | — | **100%** |

### 4.4 Config Coverage

| Var | # Test Cases | Test ID | Coverage Status |
|-----|--------------|---------|-----------------|
| TASKQ_HOME | 1 | TC-CFG-01 | COMPLETE |
| TASKQ_TASK_TIMEOUT | 1 | TC-CFG-02 | COMPLETE |
| TASKQ_RETRY_LIMIT | 1 | TC-CFG-03 | COMPLETE |
| **Total** | **3** | — | **100%** |

### 4.5 Risk Coverage

| Risk | # Test Cases | Test IDs | Coverage Status |
|------|--------------|----------|-----------------|
| R1 | 1 | TC-NFR03-01 | COMPLETE |
| R2 | 1 | TC-FR02-04 | COMPLETE |
| R3 | 1 | TC-NFR03-02 | COMPLETE |
| **Total** | **3** | — | **100%** |

## 5. Orphan / Gap Analysis

| Check | Result | Evidence |
|-------|--------|----------|
| All FRs from SRS.md have ≥1 downstream test? | PASS | FR-01 (7), FR-02 (6), FR-03 (6) → §2.1 |
| All NFRs from SRS.md have ≥1 downstream test? | PASS | NFR-01 (1), NFR-02 (2+7 sub), NFR-03 (2) → §2.2 |
| All Constraints from SRS.md traced? | PASS | C-01..C-07 → §2.3 |
| All Config vars from SRS.md traced? | PASS | TASKQ_HOME, TASKQ_TASK_TIMEOUT, TASKQ_RETRY_LIMIT → §2.4 |
| All Risks from SRS.md traced? | PASS | R1, R2, R3 → §2.5 |
| Orphan requirements (in SRS but not traced)? | NONE | FR/NFR counts in §2 match SRS §3, §4 |
| Orphan test cases (no FR/NFR owner)? | NONE | §3 backward map covers every TC ID in §2 |
| Cross-links (one test → multiple FR/NFRs)? | DOCUMENTED | TC-FR01-01e/f ↔ NFR-02; TC-FR03-01 → FR-01; TC-FR03-02 → FR-02 |
| Bidirectional consistency? | PASS | every TC ID in §3 maps to a row in §2 and vice versa |

## 6. NFR-99 / Open Issue Carriage

| ID | Source | Test-Mechanism Boundary | Downstream Owner |
|----|--------|-------------------------|------------------|
| NFR-99 / FR-02 §3.2.3 | stdout_tail "末 2000 字元" byte-vs-char ambiguity | harness owns measurement interpretation | P3/P5 harness |
| NFR-99 / FR-02 §3.2.1 | subprocess.run kwargs completeness | harness owns parameter set enumeration | P3 harness |
| NFR-99 / NFR-01 | p95 algorithm (sort-index vs quantile) | harness owns statistical method | P5 benchmark |
| NFR-99 / NFR-03 | redaction line-vs-partial-line semantics | harness owns match semantics | P5 |

## 7. Phase Hand-off

| Hand-off Target | Items to Carry |
|-----------------|----------------|
| Sub-Task 4/4 (TEST_INVENTORY.yaml) | TC IDs from §2.1.1, §2.1.2, §2.1.3, §2.2.1 — must be enumerated 1:1 (no collapsing) per phase1_plan.md rule |
| Phase 3 (Implementation) | Design element column from §2.1/§2.2/§2.3; module layout above |
| Phase 4 (Testing) | Full TC ID set (19 FR + 12 NFR + 7 C + 3 CFG = 41 sub-cases) |
| Phase 5 (Verification) | Coverage table §4 + AC count per FR/NFR row |
| Phase 6 (Quality / Peer Review) | Owner attribution inherited from SPEC_TRACKING.md |

## 8. Completeness Validation

| Check | Result | Evidence |
|-------|--------|----------|
| H1 contains "Traceability Matrix"? | PASS | `# Traceability Matrix — taskq` |
| Bidirectional traceability (FR↔Test)? | PASS | §2 forward + §3 backward |
| All FRs from SRS.md enumerated? | PASS | FR-01, FR-02, FR-03 → §2.1 |
| All NFRs from SRS.md enumerated? | PASS | NFR-01, NFR-02, NFR-03 → §2.2 |
| All Constraints from SRS.md enumerated? | PASS | C-01..C-07 → §2.3 |
| All Config vars from SRS.md enumerated? | PASS | TASKQ_HOME/TASKQ_TASK_TIMEOUT/TASKQ_RETRY_LIMIT → §2.4 |
| All Risks from SRS.md enumerated? | PASS | R1, R2, R3 → §2.5 |
| FR coverage = 100%? | PASS | §4.1 → 19/19 ACs |
| NFR coverage = 100%? | PASS | §4.2 → 5/5 ACs (with 7-char sub-coverage) |
| Constraint coverage = 100%? | PASS | §4.3 → 7/7 |
| Config coverage = 100%? | PASS | §4.4 → 3/3 |
| Risk coverage = 100%? | PASS | §4.5 → 3/3 |
| Cross-link candidates documented? | PASS | TC-FR01-01e/f ↔ NFR-02; TC-FR03-01 → FR-01; TC-FR03-02 → FR-02 |
| Orphan requirements? | NONE | §5 gap analysis |
| Orphan test cases? | NONE | §3 backward map exhaustive |

## 9. Document Status

| Field | Value |
|-------|-------|
| Version | v1.0.0 |
| Status | DRAFT (awaiting Agent B review per phase1_plan.md §Sub-Task 3/4) |
| Authored | 2026-06-29 |
| Phase | 1 — Requirements |
| Sub-Task | 3/4 |

---

*Document version: TRACEABILITY_MATRIX v1.0.0 | Authored: 2026-06-29 | Phase: 1 — Requirements | Status: DRAFT (pending-B-review)*