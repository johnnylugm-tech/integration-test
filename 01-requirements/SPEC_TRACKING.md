# Specification Tracking Matrix — taskq

> **Source**: `01-requirements/SRS.md` v1.0.0 (INGESTION of SPEC.md v2.0.0, 2026-06-15).
> **Mode**: INGESTION — every AC traces back to a SPEC §X citation in SRS.md.
> **Phase**: 2 — Architecture (per `.methodology/state.json` → `current_phase: 1`, Gate 1 PASS).
> **Last Updated**: 2026-06-29 (Round 1 authoring).
> **Owners**: A (Requirements Engineer — this file); downstream phases B (Architecture), C (Implementation), D (Test), E (Verification) will consume and update.

---

## 1. Purpose

This document tracks every Functional Requirement (FR) and Non-Functional Requirement (NFR) declared in `SRS.md` through its downstream lifecycle (Architecture → Implementation → Test → Verification → Release). It is the single source of truth for "what must be delivered" and "what state each requirement is in".

Each row anchors to a verifiable artifact. Statuses transition via gates (Gate 1 → Gate 2 → Gate 3 → Gate 4) per `.methodology/phase*_plan.md` and `CLAUDE.md` Gate Status Reference.

---

## 2. Functional Requirements (FR) Matrix

| FR ID  | Title                              | AC Count | Status         | Owner (Phase)        | SRS Anchor          | SPEC Citation   | Architecture Ref                | Test Anchor (Phase 3/4) | Verification (Phase 5) | Notes |
|--------|------------------------------------|----------|----------------|----------------------|---------------------|-----------------|---------------------------------|-------------------------|------------------------|-------|
| FR-01  | Task Model & Persistence           | 7        | SPECIFIED      | A (REQ) → B (ARCH)   | SRS §3 FR-01        | SPEC §3 FR-01   | `taskq.store` (atomic JSON I/O) | `tests/test_fr01_*.py`  | Gate1-DELTA FR-01      | AC set: 1.1.a–c, 1.2.a–d |
| FR-02  | Task Execution & Retry             | 7        | SPECIFIED      | A (REQ) → B (ARCH)   | SRS §3 FR-02        | SPEC §3 FR-02   | `taskq.executor` (subprocess)    | `tests/test_fr02_*.py`  | Gate1-DELTA FR-02      | AC set: 2.1.a, 2.2.a–b, 2.3.a, 2.4.a, 2.5.a–b |
| FR-03  | CLI Integration & Query            | 3        | SPECIFIED      | A (REQ) → B (ARCH)   | SRS §3 FR-03        | SPEC §3 FR-03   | `taskq.cli` (argparse)           | `tests/test_fr03_*.py`  | Gate1-DELTA FR-03      | AC set: 03.table, 03.1.a, 03.2.a |

**FR totals**: 3 FRs, 17 ACs (FR-01: 7 / FR-02: 7 / FR-03: 3 — includes FR-03 command-table AC).

---

## 3. Non-Functional Requirements (NFR) Matrix

| NFR ID | Title        | AC Count | Status    | Owner (Phase)        | SRS Anchor       | SPEC Citation | Architecture Constraint       | Test Anchor (Phase 3/4)             | Verification (Phase 5) | Notes |
|--------|--------------|----------|-----------|----------------------|------------------|---------------|-------------------------------|-------------------------------------|------------------------|-------|
| NFR-01 | Performance  | 1        | SPECIFIED | A (REQ) → D (TEST)   | SRS §4 NFR-01    | SPEC §4 NFR-01| (perf budget only)            | `tests/perf/test_nfr01_submit_status.py` | Gate1-DELTA NFR-01    | NFR-99 ambiguity flagged in SRS §8 (test harness owns interpretation boundary) |
| NFR-02 | Security     | 2        | SPECIFIED | A (REQ) → B (ARCH)   | SRS §4 NFR-02    | SPEC §4 NFR-02| `no_shell_true` (hard)        | `tests/test_nfr02_shell_forbidden.py` | Gate1-DELTA NFR-02    | AC-NFR-02.1 (codebase-wide) + AC-NFR-02.2 (FR-01 blacklist coverage) |
| NFR-03 | Reliability  | 2        | SPECIFIED | A (REQ) → B (ARCH)   | SRS §4 NFR-03    | SPEC §4 NFR-03| `atomic_writes_only`, `single_redaction_owner_executor` | `tests/test_nfr03_*.py`             | Gate1-DELTA NFR-03    | NFR-99 ambiguity flagged in SRS §8 (regex application scope = harness's call) |

**NFR totals**: 3 NFRs, 5 ACs (NFR-01: 1 / NFR-02: 2 / NFR-03: 2).

---

## 4. Acceptance Criteria (AC) Traceability — Complete

Every AC from SRS §6 with its downstream anchor.

### 4.1 FR-01 ACs

| AC ID         | Description                                              | Source Citation       | Test Anchor (Phase 3/4)              | Status    |
|---------------|----------------------------------------------------------|-----------------------|--------------------------------------|-----------|
| AC-FR-01.1.a  | Empty/whitespace command rejected (exit 2, no write)     | SPEC §3 FR-01         | `test_fr01_empty_command_rejected`   | SPECIFIED |
| AC-FR-01.1.b  | Command > 1000 chars rejected (exit 2, no write)         | SPEC §3 FR-01         | `test_fr01_oversize_command_rejected`| SPECIFIED |
| AC-FR-01.1.c  | Injection chars `;\|&$><\`` rejected (exit 2, no write)  | SPEC §3 FR-01 + NFR-02| `test_fr01_injection_blacklist`      | SPECIFIED |
| AC-FR-01.2.a  | task id = uuid4 first 8 hex                              | SPEC §3 FR-01         | `test_fr01_id_format`                | SPECIFIED |
| AC-FR-01.2.b  | status=pending + record command/created_at               | SPEC §3 FR-01         | `test_fr01_pending_record_fields`    | SPECIFIED |
| AC-FR-01.2.c  | atomic write to $TASKQ_HOME/tasks.json (tmp+os.replace)  | SPEC §3 FR-01         | `test_fr01_atomic_write`             | SPECIFIED |
| AC-FR-01.2.d  | corrupted tasks.json → exit 1 + stderr `store corrupted` | SPEC §3 FR-01         | `test_fr01_corrupted_store_exit1`    | SPECIFIED |

### 4.2 FR-02 ACs

| AC ID         | Description                                              | Source Citation       | Test Anchor (Phase 3/4)              | Status    |
|---------------|----------------------------------------------------------|-----------------------|--------------------------------------|-----------|
| AC-FR-02.1.a  | subprocess.run with shlex.split, capture_output, text, timeout; no shell=True | SPEC §3 FR-02 | `test_fr02_subprocess_invoke`        | SPECIFIED |
| AC-FR-02.2.a  | state machine pending→running→done\|failed\|timeout      | SPEC §3 FR-02         | `test_fr02_state_machine`            | SPECIFIED |
| AC-FR-02.2.b  | exit-code-to-status mapping                              | SPEC §3 FR-02         | `test_fr02_exit_to_status`           | SPECIFIED |
| AC-FR-02.3.a  | record exit_code, stdout_tail (last 2000), stderr_tail (last 2000), duration_ms, finished_at | SPEC §3 FR-02 | `test_fr02_result_fields`     | SPECIFIED |
| AC-FR-02.4.a  | auto-retry on failed/timeout up to TASKQ_RETRY_LIMIT (default 2) | SPEC §3 FR-02 | `test_fr02_retry_cap`                | SPECIFIED |
| AC-FR-02.5.a  | single-task mode timeout → exit 4                        | SPEC §3 FR-02         | `test_fr02_timeout_exit4`            | SPECIFIED |
| AC-FR-02.5.b  | unexpected exception → exit 1 (no bare except:)          | SPEC §3 FR-02         | `test_fr02_unexpected_exit1`         | SPECIFIED |

### 4.3 FR-03 ACs

| AC ID         | Description                                              | Source Citation       | Test Anchor (Phase 3/4)              | Status    |
|---------------|----------------------------------------------------------|-----------------------|--------------------------------------|-----------|
| AC-FR-03 (table) | submit/run/status/list/clear behaviors                 | SPEC §3 FR-03         | `test_fr03_command_table`            | SPECIFIED |
| AC-FR-03.1.a  | --json global flag → single-line JSON                    | SPEC §3 FR-03         | `test_fr03_json_flag_single_line`    | SPECIFIED |
| AC-FR-03.2.a  | exit codes 0/2/4/1 mapping                               | SPEC §3 FR-03         | `test_fr03_exit_code_mapping`        | SPECIFIED |

### 4.4 NFR-01 AC

| AC ID         | Description                                              | Source Citation       | Test Anchor (Phase 3/4)              | Status    |
|---------------|----------------------------------------------------------|-----------------------|--------------------------------------|-----------|
| AC-NFR-01.1   | submit+status 100-iter p95 < 50ms (excluding subprocess) | SPEC §4 NFR-01        | `test_nfr01_p95_under_50ms`          | SPECIFIED |

### 4.5 NFR-02 ACs

| AC ID         | Description                                              | Source Citation       | Test Anchor (Phase 3/4)              | Status    |
|---------------|----------------------------------------------------------|-----------------------|--------------------------------------|-----------|
| AC-NFR-02.1   | shell=True forbidden across codebase                     | SPEC §4 NFR-02        | `test_nfr02_no_shell_true_grep`      | SPECIFIED |
| AC-NFR-02.2   | FR-01 injection blacklist test coverage required         | SPEC §4 NFR-02        | `test_fr01_injection_blacklist` (re-used) | SPECIFIED |

### 4.6 NFR-03 ACs

| AC ID         | Description                                              | Source Citation       | Test Anchor (Phase 3/4)              | Status    |
|---------------|----------------------------------------------------------|-----------------------|--------------------------------------|-----------|
| AC-NFR-03.1   | tasks.json atomic write survives interruption            | SPEC §4 NFR-03        | `test_nfr03_atomic_survives_crash`   | SPECIFIED |
| AC-NFR-03.2   | redaction regex `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` line-level → `[REDACTED]` | SPEC §4 NFR-03 | `test_nfr03_redaction_line_replace`  | SPECIFIED |

---

## 5. Configuration Requirements (from SRS §5)

| Variable             | Default  | Description                                  | Source   | Status    | Owner |
|----------------------|----------|----------------------------------------------|----------|-----------|-------|
| `TASKQ_HOME`         | `.taskq` | Data directory                               | SPEC §5  | SPECIFIED | B (ARCH — `config.py`) |
| `TASKQ_TASK_TIMEOUT` | `10.0`   | Per-task subprocess timeout (seconds)        | SPEC §5  | SPECIFIED | B (ARCH — `config.py`) |
| `TASKQ_RETRY_LIMIT`  | `2`      | Auto-retry limit on failure                  | SPEC §5  | SPECIFIED | B (ARCH — `config.py`) |

---

## 6. Constraints Tracking (from SRS §2)

| Constraint ID | Description                                                            | Source         | Owner (Phase) | Status    |
|---------------|------------------------------------------------------------------------|----------------|---------------|-----------|
| C-1           | Python 3.11 stdlib only; `python -m taskq` CLI entry; `shell=True` forbidden everywhere; atomic JSON writes (`tmp + os.replace`) | PROJECT_BRIEF  | B (ARCH)      | SPECIFIED |
| C-2           | Injection character blacklist (`; \| & $ > < \``) on `submit`          | PROJECT_BRIEF  | C (IMPL)      | SPECIFIED |
| C-3           | `tasks.json` atomic write survives mid-write crash; never silently rebuilt on parse failure; secret-line redaction on `stdout_tail` / `stderr_tail` | PROJECT_BRIEF | C (IMPL) | SPECIFIED |
| C-4           | `submit` + `status` combined p95 < 50ms over 100 iterations             | PROJECT_BRIEF  | D (TEST)      | SPECIFIED |

---

## 7. Risks Tracking (from SRS §9)

| Risk ID | Description                                  | Mitigation         | Source    | Status    |
|---------|----------------------------------------------|--------------------|-----------|-----------|
| R1      | concurrent / interrupted writes corrupt the store | NFR-03 (atomic write) | SPEC §4 | MITIGATED-DESIGN |
| R2      | subprocess hangs                             | FR-02 (`timeout`)  | SPEC §4   | MITIGATED-DESIGN |
| R3      | secrets leaked to disk                       | NFR-03 (redaction) | SPEC §4   | MITIGATED-DESIGN |

---

## 8. Open Issues Forwarded (from SRS §8)

| Issue ID | Description                                                              | Owner   | Action                                                 |
|----------|--------------------------------------------------------------------------|---------|--------------------------------------------------------|
| NFR-99   | SPEC §4 NFR-01 「excluding subprocess execution」 measurement boundary   | D (TEST)| Harness to confirm with stakeholder; defer to Phase 4.  |
| NFR-99   | SPEC §4 NFR-03 regex application scope (per-line vs per-buffer)          | D (TEST)| Harness to decide; defer to Phase 4.                   |

---

## 9. Status Legend

| Status               | Meaning                                                                                  |
|----------------------|------------------------------------------------------------------------------------------|
| SPECIFIED            | Declared in SRS.md; not yet architected / implemented / tested.                          |
| IN-PROGRESS          | Active work by the listed owner phase.                                                   |
| COMPLETE             | All ACs of the requirement have passing tests + implementation + verification evidence.   |
| MITIGATED-DESIGN     | Risk mitigated at the design/architecture level (verified by AC coverage).               |
| DEFERRED             | Out of scope per SRS §7 or stakeholder decision; logged but not delivered.               |
| BLOCKED              | Cannot progress due to dependency or open issue; owner must clear blocker before resume.  |

---

## 10. Completeness Check

- FRs covered: **3 / 3** (FR-01, FR-02, FR-03) — `SRS §3`.
- NFRs covered: **3 / 3** (NFR-01, NFR-02, NFR-03) — `SRS §4`.
- FR ACs covered: **17 / 17** — `SRS §6` (FR-01: 7 / FR-02: 7 / FR-03: 3).
- NFR ACs covered: **5 / 5** — `SRS §6` (NFR-01: 1 / NFR-02: 2 / NFR-03: 2).
- Configuration vars covered: **3 / 3** — `SRS §5` (`TASKQ_HOME`, `TASKQ_TASK_TIMEOUT`, `TASKQ_RETRY_LIMIT`).
- Constraints covered: **4 / 4** — `SRS §2` (C-1, C-2, C-3, C-4).
- Risks covered: **3 / 3** — `SRS §9` (R1, R2, R3).
- Open issues forwarded: **2** — `SRS §8` (both NFR-99 ambiguities deferred to Phase 4).
- Out-of-scope acknowledged: `SRS §7` (5 items) — not tracked individually (informational only).

**No TBD / TODO / placeholder markers in SRS.md v1.0.0** — all 3 FRs and 3 NFRs are fully specified.

---

## 11. Gate Alignment

| Gate | FR/NFR Trigger                          | Status      | Reference              |
|------|-----------------------------------------|-------------|------------------------|
| Gate 1 | Per-FR TDD + implementation quality   | ✅ PASS (3/3 FRs, FR-01=98.3 / FR-02=98.3 / FR-03=94.7) | `CLAUDE.md` Gate Progress |
| Gate 2 | P3 exit — full architecture + impl     | ✅ PASS (94.9)                           | `CLAUDE.md` Gate Progress |
| Gate 3 | P4 exit — testing + verification       | ⬜ Not Started                          | Phase 4 plan |
| Gate 4 | P6 full — final 14-dim score ≥ 85      | ⬜ Not Started                          | Phase 6 plan |

---

*Document version: SPEC_TRACKING v1.0.0 — Round 1 authoring, sourced 1:1 from SRS.md v1.0.0.*