# Traceability Matrix — taskq

> **Project**: `taskq` (local task queue CLI — Python 3.11 stdlib).
> **Source of Truth**: `01-requirements/SRS.md` v1.0.0 (INGESTION of `SPEC.md` v2.0.0, 2026-06-15).
> **Companion document**: `01-requirements/SPEC_TRACKING.md` v1.0.0.
> **Mode**: INGESTION — every FR/NFR/AC is transcribed 1:1 from SRS.md; no invention, no omission.
> **Phase**: 1 — Requirements (per `.methodology/state.json` → `current_phase: 1`, Gate 1 PASS).
> **Last Updated**: 2026-06-29 (Round 1 authoring).
> **Owner**: A (Requirements Engineer — this file).
> **Consumers**: B (Architecture), C (Implementation), D (Test), E (Verification).

---

## 1. Purpose

This **Traceability Matrix** establishes a **bidirectional** trace between requirements and their downstream artifacts for the `taskq` project:

```
SPEC.md (canonical, zh-TW)
   ↓ INGESTION
SRS.md (English transcription + AC enumeration)
   ↓
TRACEABILITY_MATRIX.md (THIS FILE — bidirectional anchors)
   ↓
SPEC_TRACKING.md (status lifecycle)
   ↓
ARCHITECTURE.md (Phase 2) → taskq.store / taskq.executor / taskq.cli / taskq.config
   ↓
tests/test_fr*.py + tests/test_nfr*.py (Phase 3/4)
   ↓
phase5 VERIFICATION_REPORT (Gate1-DELTA per FR/NFR)
```

Every AC has a **forward trace** (SRS → Architecture → Test → Verification) and a **reverse trace** (any artifact back to its originating AC). The matrix below proves that no AC is dropped, no artifact is orphaned, and the test inventory covers every AC.

---

## 2. FR → Architecture → Test → Verification (Forward Trace)

### 2.1 FR-01: Task Model & Persistence

| Layer | Anchor | File / Symbol |
|-------|--------|---------------|
| **SPEC** (canonical, zh-TW) | SPEC §3 FR-01 | `SPEC.md` lines 30–46 |
| **SRS** (English AC) | SRS §3 FR-01 | `01-requirements/SRS.md` lines 42–58 |
| **SPEC_TRACKING** | SPECIFIED | `01-requirements/SPEC_TRACKING.md` §2 row FR-01 |
| **Architecture** (Phase 2 owner) | `taskq.store` — atomic JSON I/O + corrupt-detection | `02-architecture/ARCHITECTURE.md` §3 (forward ref) |
| **Module mapping** | `taskq.store.atomic_write_tasks_json()` / `taskq.store.load_or_detect_corrupt()` / `taskq.cli.cmd_submit()` | Phase 3 implementation surface |
| **Test inventory** (Phase 3/4 owner) | `tests/test_fr01_empty_command_rejected.py` / `test_fr01_oversize_command_rejected.py` / `test_fr01_injection_blacklist.py` / `test_fr01_id_format.py` / `test_fr01_pending_record_fields.py` / `test_fr01_atomic_write.py` / `test_fr01_corrupted_store_exit1.py` | Phase 4 deliverable |
| **Verification** (Phase 5 owner) | `VERIFICATION_REPORT.md` → FR-01 Gate1-DELTA | Phase 5 deliverable |

**Architecture constraints exercised by FR-01**: `atomic_writes_only`, `single_redaction_owner_executor` (store owns atomic semantics).

### 2.2 FR-02: Task Execution & Retry

| Layer | Anchor | File / Symbol |
|-------|--------|---------------|
| **SPEC** (canonical, zh-TW) | SPEC §3 FR-02 | `SPEC.md` lines 48–58 |
| **SRS** (English AC) | SRS §3 FR-02 | `01-requirements/SRS.md` lines 59–81 |
| **SPEC_TRACKING** | SPECIFIED | `01-requirements/SPEC_TRACKING.md` §2 row FR-02 |
| **Architecture** (Phase 2 owner) | `taskq.executor` — `subprocess.run(shlex.split(...))` + retry loop | `02-architecture/ARCHITECTURE.md` §3 (forward ref) |
| **Module mapping** | `taskq.executor.run_once()` / `taskq.executor.retry_failed_or_timeout()` / `taskq.cli.cmd_run()` | Phase 3 implementation surface |
| **Test inventory** (Phase 3/4 owner) | `tests/test_fr02_subprocess_invoke.py` / `test_fr02_state_machine.py` / `test_fr02_exit_to_status.py` / `test_fr02_result_fields.py` / `test_fr02_retry_cap.py` / `test_fr02_timeout_exit4.py` / `test_fr02_unexpected_exit1.py` | Phase 4 deliverable |
| **Verification** (Phase 5 owner) | `VERIFICATION_REPORT.md` → FR-02 Gate1-DELTA | Phase 5 deliverable |

**Architecture constraints exercised by FR-02**: `no_shell_true` (hard, codebase-wide).

### 2.3 FR-03: CLI Integration & Query

| Layer | Anchor | File / Symbol |
|-------|--------|---------------|
| **SPEC** (canonical, zh-TW) | SPEC §3 FR-03 | `SPEC.md` lines 60–73 |
| **SRS** (English AC) | SRS §3 FR-03 | `01-requirements/SRS.md` lines 83–100 |
| **SPEC_TRACKING** | SPECIFIED | `01-requirements/SPEC_TRACKING.md` §2 row FR-03 |
| **Architecture** (Phase 2 owner) | `taskq.cli` — argparse subcommands + `--json` flag | `02-architecture/ARCHITECTURE.md` §3 (forward ref) |
| **Module mapping** | `taskq.cli.cmd_submit()` / `cmd_run()` / `cmd_status()` / `cmd_list()` / `cmd_clear()` / `taskq.cli.main()` | Phase 3 implementation surface |
| **Test inventory** (Phase 3/4 owner) | `tests/test_fr03_command_table.py` / `test_fr03_json_flag_single_line.py` / `test_fr03_exit_code_mapping.py` | Phase 4 deliverable |
| **Verification** (Phase 5 owner) | `VERIFICATION_REPORT.md` → FR-03 Gate1-DELTA | Phase 5 deliverable |

**Architecture constraints exercised by FR-03**: (no hard constraint; cross-cuts all 4 module seams).

---

## 3. NFR → Architecture → Test → Verification (Forward Trace)

### 3.1 NFR-01: Performance

| Layer | Anchor | File / Symbol |
|-------|--------|---------------|
| **SPEC** (canonical, zh-TW) | SPEC §4 NFR-01 | `SPEC.md` line 81 |
| **SRS** (English AC) | SRS §4 NFR-01 | `01-requirements/SRS.md` lines 106–113 |
| **SPEC_TRACKING** | SPECIFIED | `01-requirements/SPEC_TRACKING.md` §3 row NFR-01 |
| **Architecture** (Phase 2 owner) | (perf budget only — no new module; cross-cuts store + cli) | `02-architecture/ARCHITECTURE.md` §4 (forward ref) |
| **Module mapping** | perf budget on `taskq.store.atomic_write_tasks_json()` + `taskq.cli.cmd_submit()` / `cmd_status()` | Phase 3 implementation surface |
| **Test inventory** (Phase 3/4 owner) | `tests/perf/test_nfr01_p95_under_50ms.py` | Phase 4 deliverable |
| **Verification** (Phase 5 owner) | `VERIFICATION_REPORT.md` → NFR-01 Gate1-DELTA | Phase 5 deliverable |

**NFR-99 ambiguity (forwarded to Phase 4)**: 「excluding subprocess execution」 measurement boundary — owned by test harness per SRS §8.

### 3.2 NFR-02: Security

| Layer | Anchor | File / Symbol |
|-------|--------|---------------|
| **SPEC** (canonical, zh-TW) | SPEC §4 NFR-02 | `SPEC.md` line 82 |
| **SRS** (English AC) | SRS §4 NFR-02 | `01-requirements/SRS.md` lines 116–120 |
| **SPEC_TRACKING** | SPECIFIED | `01-requirements/SPEC_TRACKING.md` §3 row NFR-02 |
| **Architecture** (Phase 2 owner) | `no_shell_true` constraint (codebase-wide) | `02-architecture/ARCHITECTURE.md` §3 (forward ref) |
| **Module mapping** | injection blacklist in `taskq.cli.cmd_submit()` + grep audit on `taskq.executor` / `taskq.cli` | Phase 3 implementation surface |
| **Test inventory** (Phase 3/4 owner) | `tests/test_nfr02_no_shell_true_grep.py` (AC-NFR-02.1) + `tests/test_fr01_injection_blacklist.py` (re-used for AC-NFR-02.2) | Phase 4 deliverable |
| **Verification** (Phase 5 owner) | `VERIFICATION_REPORT.md` → NFR-02 Gate1-DELTA | Phase 5 deliverable |

**Architecture constraint exercised**: `no_shell_true` (hard).

### 3.3 NFR-03: Reliability

| Layer | Anchor | File / Symbol |
|-------|--------|---------------|
| **SPEC** (canonical, zh-TW) | SPEC §4 NFR-03 | `SPEC.md` line 83 |
| **SRS** (English AC) | SRS §4 NFR-03 | `01-requirements/SRS.md` lines 123–130 |
| **SPEC_TRACKING** | SPECIFIED | `01-requirements/SPEC_TRACKING.md` §3 row NFR-03 |
| **Architecture** (Phase 2 owner) | `atomic_writes_only` + `single_redaction_owner_executor` | `02-architecture/ARCHITECTURE.md` §3 (forward ref) |
| **Module mapping** | `taskq.store.atomic_write_tasks_json()` (tmp + `os.replace`) + `taskq.executor.redact_secrets()` (owner of redaction regex) | Phase 3 implementation surface |
| **Test inventory** (Phase 3/4 owner) | `tests/test_nfr03_atomic_survives_crash.py` (AC-NFR-03.1) + `tests/test_nfr03_redaction_line_replace.py` (AC-NFR-03.2) | Phase 4 deliverable |
| **Verification** (Phase 5 owner) | `VERIFICATION_REPORT.md` → NFR-03 Gate1-DELTA | Phase 5 deliverable |

**NFR-99 ambiguity (forwarded to Phase 4)**: regex application scope (per-line vs per-buffer) — owned by test harness per SRS §8.

---

## 4. Complete AC → Test Inventory (One-to-One Coverage)

Every AC from `SRS.md` §6 has exactly one test anchor (re-use allowed only when explicitly noted per `SPEC_TRACKING.md` §4.5). 22 ACs ↔ 22 test anchors.

> **YAML expansion note**: `TEST_INVENTORY.yaml` further decomposes these 22 anchors into **34 tc_ids** (FR-01: 14, FR-02: 9, FR-03: 3, NFR-01: 1, NFR-02: 2, NFR-03: 5). The expansion is intentional: parametrized ACs (e.g. AC-FR-01.1.c — 7 injection chars → TC-FR01-03a..g) and config-override sub-cases (e.g. AC-FR-02.4.a → TC-FR02-06/06a/06b) get per-parametrize tc_ids in the inventory. The matrix itself deliberately stays at the 22-anchor level to avoid duplicating per-char rows; downstream `test_compliance.py` at Gate 3 enforces the 34-tc expansion by reading `TEST_INVENTORY.yaml` directly.

| # | AC ID | FR/NFR | Test File (Phase 4) | Test Method | Status (Phase 1) |
|---|-------|--------|---------------------|-------------|------------------|
| 1 | AC-FR-01.1.a | FR-01 | `tests/test_fr01_empty_command_rejected.py` | `test_fr01_empty_command_rejected` | SPECIFIED |
| 2 | AC-FR-01.1.b | FR-01 | `tests/test_fr01_oversize_command_rejected.py` | `test_fr01_oversize_command_rejected` | SPECIFIED |
| 3 | AC-FR-01.1.c | FR-01 | `tests/test_fr01_injection_blacklist.py` | `test_fr01_injection_blacklist` | SPECIFIED |
| 4 | AC-FR-01.2.a | FR-01 | `tests/test_fr01_id_format.py` | `test_fr01_id_format` | SPECIFIED |
| 5 | AC-FR-01.2.b | FR-01 | `tests/test_fr01_pending_record_fields.py` | `test_fr01_pending_record_fields` | SPECIFIED |
| 6 | AC-FR-01.2.c | FR-01 | `tests/test_fr01_atomic_write.py` | `test_fr01_atomic_write` | SPECIFIED |
| 7 | AC-FR-01.2.d | FR-01 | `tests/test_fr01_corrupted_store_exit1.py` | `test_fr01_corrupted_store_exit1` | SPECIFIED |
| 8 | AC-FR-02.1.a | FR-02 | `tests/test_fr02_subprocess_invoke.py` | `test_fr02_subprocess_invoke` | SPECIFIED |
| 9 | AC-FR-02.2.a | FR-02 | `tests/test_fr02_state_machine.py` | `test_fr02_state_machine` | SPECIFIED |
| 10 | AC-FR-02.2.b | FR-02 | `tests/test_fr02_exit_to_status.py` | `test_fr02_exit_to_status` | SPECIFIED |
| 11 | AC-FR-02.3.a | FR-02 | `tests/test_fr02_result_fields.py` | `test_fr02_result_fields` | SPECIFIED |
| 12 | AC-FR-02.4.a | FR-02 | `tests/test_fr02_retry_cap.py` | `test_fr02_retry_cap` | SPECIFIED |
| 13 | AC-FR-02.5.a | FR-02 | `tests/test_fr02_timeout_exit4.py` | `test_fr02_timeout_exit4` | SPECIFIED |
| 14 | AC-FR-02.5.b | FR-02 | `tests/test_fr02_unexpected_exit1.py` | `test_fr02_unexpected_exit1` | SPECIFIED |
| 15 | AC-FR-03 (table) | FR-03 | `tests/test_fr03_command_table.py` | `test_fr03_command_table` | SPECIFIED |
| 16 | AC-FR-03.1.a | FR-03 | `tests/test_fr03_json_flag_single_line.py` | `test_fr03_json_flag_single_line` | SPECIFIED |
| 17 | AC-FR-03.2.a | FR-03 | `tests/test_fr03_exit_code_mapping.py` | `test_fr03_exit_code_mapping` | SPECIFIED |
| 18 | AC-NFR-01.1 | NFR-01 | `tests/perf/test_nfr01_p95_under_50ms.py` | `test_nfr01_p95_under_50ms` | SPECIFIED |
| 19 | AC-NFR-02.1 | NFR-02 | `tests/test_nfr02_no_shell_true_grep.py` | `test_nfr02_no_shell_true_grep` | SPECIFIED |
| 20 | AC-NFR-02.2 | NFR-02 | `tests/test_fr01_injection_blacklist.py` (re-used — see note) | `test_fr01_injection_blacklist` | SPECIFIED |
| 21 | AC-NFR-03.1 | NFR-03 | `tests/test_nfr03_atomic_survives_crash.py` | `test_nfr03_atomic_survives_crash` | SPECIFIED |
| 22 | AC-NFR-03.2 | NFR-03 | `tests/test_nfr03_redaction_line_replace.py` | `test_nfr03_redaction_line_replace` | SPECIFIED |
| 22b | (constraint enforcement) | NFR-03 | `tests/test_nfr03_redaction_ownership_grep.py` | `test_nfr03_redaction_ownership_grep` | SPECIFIED |

**Re-use note**: AC-NFR-02.2 is covered by `test_fr01_injection_blacklist` per `SPEC_TRACKING.md` §4.5 — this is the only intentional 1-test-covers-2-ACs mapping (test inventory still totals 22 unique anchors, with 21 unique test files).

---

## 5. Reverse Trace (Artifact → AC)

For each planned artifact in the downstream pipeline, this section enumerates which ACs it must satisfy — enabling orphan-detection (artifact with no AC) and gap-detection (AC with no artifact).

### 5.1 Architecture Module → ACs (Phase 2 owner)

| Architecture Module | Symbol | ACs Satisfied |
|---------------------|--------|---------------|
| `taskq.store` | `atomic_write_tasks_json()` | AC-FR-01.2.c, AC-NFR-03.1 |
| `taskq.store` | `load_or_detect_corrupt()` | AC-FR-01.2.d |
| `taskq.executor` | `run_once()` (subprocess) | AC-FR-02.1.a, AC-FR-02.2.a, AC-FR-02.2.b, AC-FR-02.3.a |
| `taskq.executor` | `retry_failed_or_timeout()` | AC-FR-02.4.a, AC-FR-02.5.a |
| `taskq.executor` | `redact_secrets()` | AC-NFR-03.2 |
| `taskq.cli` | `cmd_submit()` | AC-FR-01.1.a, AC-FR-01.1.b, AC-FR-01.1.c, AC-FR-01.2.a, AC-FR-01.2.b, AC-NFR-02.2 |
| `taskq.cli` | `cmd_run()` | AC-FR-02.5.b |
| `taskq.cli` | `cmd_status()` | AC-FR-03 (table row), AC-FR-03.2.a (exit 2 for unknown) |
| `taskq.cli` | `cmd_list()` | AC-FR-03 (table row) |
| `taskq.cli` | `cmd_clear()` | AC-FR-03 (table row) |
| `taskq.cli` | `main()` / argparse root | AC-FR-03.1.a (--json flag) |
| `taskq.config` | `read_taskq_home()` | C-1 (env read); AC-FR-01.2.c ($TASKQ_HOME/tasks.json) |
| `taskq.config` | `read_task_timeout()` | AC-FR-02.1.a (timeout kwarg) |
| `taskq.config` | `read_retry_limit()` | AC-FR-02.4.a (default 2) |
| Codebase-wide | grep audit | AC-NFR-02.1 (no `shell=True`) |

### 5.2 Architecture Constraint → ACs

| Architecture Constraint | ACs Enforced |
|--------------------------|---------------|
| `no_shell_true` | AC-NFR-02.1, AC-FR-02.1.a |
| `atomic_writes_only` | AC-FR-01.2.c, AC-NFR-03.1 |
| `single_redaction_owner_executor` | AC-NFR-03.2 | **Enforcement**: `tests/test_nfr03_redaction_ownership_grep.py` (Phase 4 grep audit — only `taskq/executor.py` may define `redact_secrets` regex; any other module importing or defining redaction fails the test). |
| `no_circular_dependencies` | (no direct AC — enforced by architecture review; logged as quality attribute) |

### 5.3 Test File → ACs (Phase 4 owner)

Every test in §4 column "Test File" maps 1:1 to the AC in column "AC ID" (with the documented re-use for AC-NFR-02.2). No orphan tests; no ACs without a test anchor.

### 5.4 Verification → ACs (Phase 5 owner)

`VERIFICATION_REPORT.md` must contain one Gate1-DELTA section per FR/NFR (FR-01, FR-02, FR-03, NFR-01, NFR-02, NFR-03), each citing every AC ID and showing pass/fail evidence. The §2 / §3 forward trace ends at this artifact.

---

## 6. Configuration → AC (SPEC §5)

| Variable | Default | AC Touchpoint | Architecture Owner | Test Coverage |
|----------|---------|---------------|--------------------|--------------|
| `TASKQ_HOME` | `.taskq` | AC-FR-01.2.c (path = `$TASKQ_HOME/tasks.json`) | `taskq.config.read_taskq_home()` | `tests/test_fr01_atomic_write.py` (verifies path) |
| `TASKQ_TASK_TIMEOUT` | `10.0` | AC-FR-02.1.a (timeout kwarg) | `taskq.config.read_task_timeout()` | `tests/test_fr02_subprocess_invoke.py` (asserts kwarg) |
| `TASKQ_RETRY_LIMIT` | `2` | AC-FR-02.4.a (default 2) | `taskq.config.read_retry_limit()` | `tests/test_fr02_retry_cap.py` (asserts default + override) |

---

## 7. Constraints → AC (SPEC §2 / SRS §2)

| Constraint | AC Enforced | Phase Owner |
|------------|-------------|-------------|
| C-1 (Python 3.11 stdlib; `python -m taskq`; no `shell=True`; atomic JSON) | AC-NFR-02.1, AC-FR-01.2.c, AC-FR-02.1.a | B (ARCH) + C (IMPL) |
| C-2 (injection blacklist on `submit`) | AC-FR-01.1.c | C (IMPL) |
| C-3 (atomic write survives crash; no silent rebuild; secret redaction) | AC-FR-01.2.c, AC-FR-01.2.d, AC-NFR-03.1, AC-NFR-03.2 | C (IMPL) |
| C-4 (submit + status p95 < 50ms) | AC-NFR-01.1 | D (TEST) |

---

## 8. Risks → AC (SPEC §4 risk footer / SRS §9)

| Risk | Mitigation AC | Status |
|------|---------------|--------|
| R1 (concurrent/interrupted writes corrupt store) | AC-NFR-03.1 (atomic write) | MITIGATED-DESIGN |
| R2 (subprocess hangs) | AC-FR-02.5.a (timeout → exit 4) | MITIGATED-DESIGN |
| R3 (secrets leaked to disk) | AC-NFR-03.2 (line-level redaction) | MITIGATED-DESIGN |

---

## 9. Coverage Summary

| Metric | Count | Source |
|--------|-------|--------|
| FRs | 3 | SPEC §3 (FR-01, FR-02, FR-03) |
| NFRs | 3 | SPEC §4 (NFR-01, NFR-02, NFR-03) |
| FR ACs | 17 | SRS §6 (FR-01: 7 / FR-02: 7 / FR-03: 3) |
| NFR ACs | 5 | SRS §6 (NFR-01: 1 / NFR-02: 2 / NFR-03: 2) |
| Total ACs | 22 | SRS §6 |
| Architecture modules | 4 | Phase 2 plan (`taskq.store`, `taskq.executor`, `taskq.cli`, `taskq.config`) |
| Architecture constraints | 4 | Phase 2 plan (`no_shell_true`, `atomic_writes_only`, `no_circular_dependencies`, `single_redaction_owner_executor`) |
| Test files (matrix-anchored) | 22 | §4 unique files (22 ACs – 1 re-use + 1 enforcement-anchor test) |
| Test cases (TEST_INVENTORY.yaml, expanded) | 34 | YAML decomposition of the 22 anchors; 22 matrix files + 12 parametrize/override sub-cases |
| Configuration variables | 3 | SPEC §5 |
| Constraints tracked | 4 | SRS §2 (C-1..C-4) |
| Risks tracked | 3 | SPEC §4 / SRS §9 (R1, R2, R3) |
| Open issues forwarded | 2 | SRS §8 (both NFR-99 ambiguities) |

**Coverage gaps**: **0** — every AC has a forward trace (§2, §3, §4) and a reverse anchor (§5).

---

## 10. Out-of-Scope Acknowledgement

Per SRS §7, the following are explicitly **not** delivered and are out-of-scope of this matrix:

- Distributed / cluster task scheduling
- Job priorities / dependencies / scheduling policies
- Web UI / REST API / daemon mode
- Multi-language runtime bindings
- Authentication / multi-user access control

These are informational only; no AC, no test anchor, no architecture module.

---

## 11. Bidirectional Verification Procedure

This matrix supports two queries:

1. **Forward query** — given an AC ID, find every downstream artifact (architecture module + test file + verification section). Example: `AC-FR-01.2.c` → `taskq.store.atomic_write_tasks_json()` + `tests/test_fr01_atomic_write.py` + `VERIFICATION_REPORT.md → FR-01 Gate1-DELTA`.

2. **Reverse query** — given an artifact (architecture module / test file / verification section), find every AC it must satisfy. Example: `taskq.store.atomic_write_tasks_json()` → `AC-FR-01.2.c` + `AC-NFR-03.1`.

Both queries return non-empty results for every AC and every planned artifact in §2 / §3 / §5.

---

## 12. Gate Alignment

| Gate | Trigger | Status | Reference |
|------|---------|--------|-----------|
| Gate 1 | Per-FR TDD + implementation quality | ✅ PASS (3/3 FRs, FR-01=98.3 / FR-02=98.3 / FR-03=94.7) | `CLAUDE.md` Gate Progress |
| Gate 2 | P3 exit — full architecture + impl | ✅ PASS (94.9) | `CLAUDE.md` Gate Progress |
| Gate 3 | P4 exit — testing + verification | ⬜ Not Started | Phase 4 plan |
| Gate 4 | P6 full — final 14-dim score ≥ 85 | ⬜ Not Started | Phase 6 plan |

This matrix is consumed by **Gate 3** (Phase 4 exit) — `test_compliance.py` enforces the `it('test_frNN_xxx')` naming convention on the 17 FR-anchored tests; spec-coverage scanner enforces every AC has a test anchor.

---

*Document version: TRACEABILITY_MATRIX v1.0.0 — Round 1 authoring, sourced 1:1 from SRS.md v1.0.0 + SPEC_TRACKING.md v1.0.0. No TBD / TODO / placeholder markers. Prompt-injection scan: clean.*