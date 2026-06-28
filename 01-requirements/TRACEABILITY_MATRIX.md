# Traceability Matrix — taskq

> Phase 1 deliverable. Bidirectional traceability between `01-requirements/SRS.md` (APPROVED) and the design + test surface.
> Source: SPEC.md v2.0.0 (2026-06-15). Date: 2026-06-29.
> Agent A scope: FR ↔ Design Element ↔ Test Case bidirectional links + coverage validation.
> Authority chain: SPEC.md → SRS.md (APPROVED) → TRACEABILITY_MATRIX.md (this file) → TEST_INVENTORY.yaml (next deliverable).
> Every row in §3 (FR) and §4 (NFR) of `SRS.md` MUST appear here with at least one design link and one test link. No invention, no silent omission.

---

## 1. Purpose

This document is the **bidirectional traceability layer** for `taskq`:

- **Forward link** (FR → Design → Test): proves every requirement is implemented and exercised.
- **Backward link** (Test → Design → FR): proves every test exercises a documented requirement (no orphan tests).

`SRS.md` defines **what** (FRs / NFRs / ACs). `SPEC.md` defines **how** at the architecture / module level. This file binds them: each FR / AC is linked to one or more design elements and one or more test cases, with no orphans in either direction.

---

## 2. Conventions

### 2.1 Identifier Vocabulary

| Identifier | Source | Format | Example |
|-----------|--------|--------|---------|
| FR / NFR | `SRS.md` §3 / §4 | `FR-NN`, `NFR-NN` | `FR-01`, `NFR-02` |
| AC | `SRS.md` §5 | `FR-NN.AC-N` / `NFR-NN.AC-N` | `FR-01.AC-3`, `NFR-03.AC-2` |
| Design Element | `SPEC.md` §2 + §3 + §5 | `<module>.<symbol>` (Python path) | `taskq.store.atomic_write_json`, `taskq.cli.main` |
| Test Case | `TEST_INVENTORY.yaml` (Sub-Task 4/4 forward) | `TC-FRNN-NN` (1:1 with AC enumeration) | `TC-FR01-01`, `TC-NFR02-02` |

### 2.2 Module Map (from `SPEC.md` §2)

| Module | Responsibility | FRs Touched |
|--------|---------------|-------------|
| `taskq.cli` | argparse entry: `python -m taskq`, subcommands `submit` / `run` / `status` / `list` / `clear`, global `--json`, exit-code matrix | FR-03 |
| `taskq.validate` | input validation rules: empty / length / injection-blacklist | FR-01 |
| `taskq.store` | atomic JSON write (`tmp + os.replace`); corrupt-store detection at startup; `load_tasks` / `save_tasks` | FR-01, NFR-03 |
| `taskq.executor` | `subprocess.run(shlex.split(...))` execution; `TASKQ_TASK_TIMEOUT`; result-field capture; retry loop on `failed`/`timeout` | FR-02 |
| `taskq.redact` | whole-line redaction of `(sk-[A-Za-z0-9_-]{8,}\|token=\S+)` to `[REDACTED]` for `stdout_tail` / `stderr_tail` | NFR-03 |
| `taskq.config` | uniform env-var reader: `TASKQ_HOME`, `TASKQ_TASK_TIMEOUT`, `TASKQ_RETRY_LIMIT` | FR-01, FR-02, FR-03 (indirect) |

### 2.3 Test Module Map (downstream Phase 4)

| Test Module | ACs Touched |
|-------------|-------------|
| `tests/test_fr01_submit.py` | FR-01.AC-1..AC-5 |
| `tests/test_fr02_run.py` | FR-02.AC-1..AC-5 |
| `tests/test_fr03_cli.py` | FR-03.AC-1..AC-6 |
| `tests/test_nfr01_perf.py` | NFR-01.AC-1 |
| `tests/test_nfr02_security.py` | NFR-02.AC-1..AC-2 |
| `tests/test_nfr03_reliability.py` | NFR-03.AC-1..AC-2 |

> Test module names are conventions fixed by `TEST_INVENTORY.yaml` (Sub-Task 4/4); Phase 4 (`phase4_plan.md`) creates the actual files. This file only links to the AC-to-test_id mapping.

---

## 3. Forward Link — FR / AC → Design → Test

One row per AC (21 total per `SRS.md` §5). Columns:

- **AC** — stable handle from `SRS.md` §5.
- **Design Elements** — module + symbol where the AC is realized (1 or more).
- **Test IDs** — 1:1 with AC enumeration; multiple TC IDs per AC only when an AC enumerates a multi-element set (e.g. NFR-02.AC-2 = per-character blacklist).
- **Coverage** — `COVERED` (has both design + test links) or `DEFERRED` (SRS §7 marks it so).

### 3.1 FR-01 — Task Model & Persistence

| AC | Design Elements | Test IDs | Coverage |
|----|-----------------|----------|----------|
| FR-01.AC-1 (empty / whitespace reject) | `taskq.validate.is_empty`, `taskq.cli.submit_cmd` (error branch), `taskq.store.save_tasks` (NOT called on reject) | `TC-FR01-01` | COVERED |
| FR-01.AC-2 (length > 1000 reject) | `taskq.validate.check_length`, `taskq.cli.submit_cmd` (error branch), `taskq.store.save_tasks` (NOT called on reject) | `TC-FR01-02` | COVERED |
| FR-01.AC-3 (injection-char reject) | `taskq.validate.check_injection_chars`, `taskq.cli.submit_cmd` (error branch) | `TC-FR01-03` (cross-ref NFR-02.AC-2) | COVERED |
| FR-01.AC-4 (valid submit → uuid4-8hex + pending + atomic write) | `taskq.store.atomic_write_json`, `taskq.store.new_task_id` (uuid4 first 8 hex), `taskq.store.save_tasks` | `TC-FR01-04` | COVERED |
| FR-01.AC-5 (corrupt store → exit 1 + `store corrupted`, no silent rebuild) | `taskq.store.load_tasks` (parse-fail branch) | `TC-FR01-05` | COVERED |

### 3.2 FR-02 — Task Execution & Retry

| AC | Design Elements | Test IDs | Coverage |
|----|-----------------|----------|----------|
| FR-02.AC-1 (`subprocess.run(shlex.split(...))`; never `shell=True`) | `taskq.executor.run_task`, `subprocess.run(...)` call site | `TC-FR02-01` + cross-ref NFR-02.AC-1 (`shell=True` static check) | COVERED |
| FR-02.AC-2 (record `exit_code`, `stdout_tail(2000)`, `stderr_tail(2000)`, `duration_ms`, `finished_at`) | `taskq.executor.run_task` (post-exec field capture), `taskq.store.save_tasks` | `TC-FR02-02` | COVERED |
| FR-02.AC-3 (retry on `failed`/`timeout` up to `TASKQ_RETRY_LIMIT`, default 2) | `taskq.executor.run_with_retry`, `taskq.config.get_retry_limit` | `TC-FR02-03` | COVERED |
| FR-02.AC-4 (single-task mode `timeout` → exit 4) | `taskq.cli.run_cmd` (exit-code mapping), `taskq.executor.run_task` (TimeoutExpired path) | `TC-FR02-04` | COVERED |
| FR-02.AC-5 (unexpected exception → exit 1, no bare `except:`) | `taskq.cli.run_cmd` (top-level catch), `taskq.executor.run_with_retry` (no bare except) | `TC-FR02-05` | COVERED |

### 3.3 FR-03 — CLI Integration & Query

| AC | Design Elements | Test IDs | Coverage |
|----|-----------------|----------|----------|
| FR-03.AC-1 (`python -m taskq` exposes submit/run/status/list/clear via argparse) | `taskq.cli.main`, `taskq.cli.build_parser` (argparse subparsers) | `TC-FR03-01` | COVERED |
| FR-03.AC-2 (`status <id>` outputs all fields; unknown id → exit 2 + `unknown task: <id>`) | `taskq.cli.status_cmd`, `taskq.store.load_tasks` | `TC-FR03-02` | COVERED |
| FR-03.AC-3 (`list` outputs id + status + first 50 chars of command per task) | `taskq.cli.list_cmd`, `taskq.store.load_tasks` | `TC-FR03-03` | COVERED |
| FR-03.AC-4 (`clear` empties `$TASKQ_HOME/tasks.json`) | `taskq.cli.clear_cmd`, `taskq.store.save_tasks` (empty list) | `TC-FR03-04` | COVERED |
| FR-03.AC-5 (global `--json` flag → single-line JSON output) | `taskq.cli.main` (json-mode formatting), `taskq.cli.status_cmd` / `taskq.cli.list_cmd` (json branch) | `TC-FR03-05` | COVERED |
| FR-03.AC-6 (exit codes: 0 / 2 / 4 / 1) | `taskq.cli.main` (exit-code matrix dispatch), `taskq.cli.submit_cmd`, `taskq.cli.run_cmd`, `taskq.cli.status_cmd`, `taskq.cli.clear_cmd` | `TC-FR03-06` | COVERED |

### 3.4 NFR-01 — Performance

| AC | Design Elements | Test IDs | Coverage |
|----|-----------------|----------|----------|
| NFR-01.AC-1 (submit+status ×100 p95 < 50ms, excluding subprocess exec) | `taskq.cli.submit_cmd`, `taskq.cli.status_cmd`, `taskq.store.atomic_write_json`, `taskq.store.load_tasks` (under measurement harness) | `TC-NFR01-01` | COVERED |

### 3.5 NFR-02 — Security

| AC | Design Elements | Test IDs | Coverage |
|----|-----------------|----------|----------|
| NFR-02.AC-1 (static check: zero `shell=True` in codebase) | `taskq.executor.run_task` (single `subprocess.run` call site with `shell=False`), `tests/test_nfr02_security.py::test_no_shell_true_in_codebase` | `TC-NFR02-01` | COVERED |
| NFR-02.AC-2 (injection-blacklist covered by ≥1 test per char/class) | `taskq.validate.check_injection_chars` (blacklist source-of-truth), `tests/test_fr01_submit.py` (parameterized over the 7 forbidden chars) | `TC-NFR02-02` (enum 7 sub-cases: `;`, `\|`, `&`, `$`, `>`, `<`, `` ` ``) | COVERED |

> Per `phase1_plan.md` HR-04 1:1 rule: `TC-NFR02-02` enumerates as 7 sub-entries `TC-NFR02-02a..g` in `TEST_INVENTORY.yaml` (one entry per forbidden char). Listed here as a single row for readability; the YAML explodes it.

### 3.6 NFR-03 — Reliability

| AC | Design Elements | Test IDs | Coverage |
|----|-----------------|----------|----------|
| NFR-03.AC-1 (atomic write survives SIGKILL mid-write) | `taskq.store.atomic_write_json` (`tmp + os.replace`); `taskq.store.load_tasks` (parses either pre- or post-write state) | `TC-NFR03-01` | COVERED |
| NFR-03.AC-2 (whole-line redaction of `(sk-[A-Za-z0-9_-]{8,}\|token=\S+)` → `[REDACTED]`) | `taskq.redact.redact_line`, `taskq.executor.run_task` (applies redaction before persist) | `TC-NFR03-02` (enum ≥2 sub-cases: `sk-` line, `token=` line) | COVERED |

> `TC-NFR03-02` enumerates ≥2 sub-entries in `TEST_INVENTORY.yaml` (one per regex branch + whole-line semantics).

---

## 4. Backward Link — Test → Design → FR

Mirrors §3 in reverse direction. One row per test module / test surface. Validates that no orphan tests exist (every test traces to a documented AC).

| Test Module / Surface | Test IDs | FR / NFR | ACs Covered |
|-----------------------|----------|----------|-------------|
| `tests/test_fr01_submit.py` | `TC-FR01-01..05` | FR-01 | FR-01.AC-1..AC-5 |
| `tests/test_fr02_run.py` | `TC-FR02-01..05` | FR-02 | FR-02.AC-1..AC-5 |
| `tests/test_fr03_cli.py` | `TC-FR03-01..06` | FR-03 | FR-03.AC-1..AC-6 |
| `tests/test_nfr01_perf.py` | `TC-NFR01-01` | NFR-01 | NFR-01.AC-1 |
| `tests/test_nfr02_security.py` | `TC-NFR02-01..02` (+ 7 sub-cases under `-02`) | NFR-02 | NFR-02.AC-1..AC-2 |
| `tests/test_nfr03_reliability.py` | `TC-NFR03-01..02` (+ ≥2 sub-cases under `-02`) | NFR-03 | NFR-03.AC-1..AC-2 |

---

## 5. Cross-Cutting Link Map

These mappings are not 1:1 — they touch multiple FRs / ACs.

| Concern | Touched FRs / NFRs | Design Elements | Test IDs |
|---------|--------------------|-----------------|----------|
| `TASKQ_HOME` env var (storage location) | FR-01.AC-4, FR-01.AC-5, FR-03.AC-4 | `taskq.config.get_home`, `taskq.store.atomic_write_json`, `taskq.store.load_tasks` | `TC-FR01-04`, `TC-FR01-05`, `TC-FR03-04` |
| `TASKQ_TASK_TIMEOUT` env var | FR-02.AC-1, FR-02.AC-4 | `taskq.config.get_task_timeout`, `taskq.executor.run_task` | `TC-FR02-01`, `TC-FR02-04` |
| `TASKQ_RETRY_LIMIT` env var | FR-02.AC-3 | `taskq.config.get_retry_limit`, `taskq.executor.run_with_retry` | `TC-FR02-03` |
| Exit-code matrix (0/2/4/1) | FR-03.AC-6 + FR-01.AC-1..AC-3 (exit 2) + FR-01.AC-5 (exit 1) + FR-02.AC-4 (exit 4) + FR-02.AC-5 (exit 1) + FR-03.AC-2 (exit 2) | `taskq.cli.main` (dispatch), per-subcommand error handlers | All `TC-FR0X-XX` |
| Redaction pipeline | NFR-03.AC-2 (cross-cuts FR-02.AC-2 since `stdout_tail`/`stderr_tail` are produced by FR-02) | `taskq.redact.redact_line`, `taskq.executor.run_task` (pre-persist hook) | `TC-FR02-02`, `TC-NFR03-02` |
| `shell=False` invariant | FR-02.AC-1 + NFR-02.AC-1 | `taskq.executor.run_task` (single call site) | `TC-FR02-01`, `TC-NFR02-01` |
| Injection blacklist | FR-01.AC-3 + NFR-02.AC-2 | `taskq.validate.check_injection_chars` | `TC-FR01-03`, `TC-NFR02-02` |

---

## 6. Coverage Summary

Computed from §3 row counts vs. `SRS.md` §5 AC enumeration.

| Family | ACs in SRS | Rows in §3 | Coverage |
|--------|------------|------------|----------|
| FR-01 | 5 | 5 (rows FR-01.AC-1..AC-5) | 5 / 5 |
| FR-02 | 5 | 5 (rows FR-02.AC-1..AC-5) | 5 / 5 |
| FR-03 | 6 | 6 (rows FR-03.AC-1..AC-6) | 6 / 6 |
| NFR-01 | 1 | 1 (row NFR-01.AC-1) | 1 / 1 |
| NFR-02 | 2 | 2 (rows NFR-02.AC-1..AC-2) | 2 / 2 |
| NFR-03 | 2 | 2 (rows NFR-03.AC-1..AC-2) | 2 / 2 |
| **Total** | **21** | **21** | **21 / 21** |

No row marked `DEFERRED` (matches `SRS.md` §7 NFR-99 `(none)` verdict).

---

## 7. Completeness Checks

Validators, not requirements. Re-run after any `SRS.md` / `SPEC.md` change.

| # | Check | Rule | Pass criterion |
|---|-------|------|----------------|
| C1 | FR completeness | Every FR ID in `SRS.md` §3 has at least one row in §3 of this file | 3 / 3 |
| C2 | NFR completeness | Every NFR ID in `SRS.md` §4 has at least one row in §3 of this file | 3 / 3 |
| C3 | AC count consistency | Sum of `§3.X` rows == `SRS.md` §5 row count == 21 | 21 == 21 |
| C4 | Bidirectional parity | Every Test ID in §3 has a matching module entry in §4 | 21 / 21 |
| C5 | No orphan tests | Every Test ID in §4 traces back to an AC in §3 | 21 / 21 (after TEST_INVENTORY.yaml enumeration) |
| C6 | No orphan design | Every Design Element listed in §3 appears in the module map §2.2 (or is a sub-symbol — flag and document if not) | 100% (sub-symbols allowed, must be reachable) |
| C7 | 1:1 enumeration | Multi-element ACs (e.g. NFR-02.AC-2 = 7 chars; NFR-03.AC-2 = ≥2 regex branches) carry explicit enumeration notes; `TEST_INVENTORY.yaml` MUST explode to sub-cases | NFR-02.AC-2 = 7 sub-cases; NFR-03.AC-2 = ≥2 sub-cases |
| C8 | Deferred fidelity | No row marked `DEFERRED` (matches `SRS.md` §7 NFR-99 `(none)`) | 0 deferred |
| C9 | Cross-cutting declaration | Every cross-cutting concern in §5 traces to ≥2 distinct rows in §3 | 7 / 7 |
| C10 | Stable handle uniqueness | No duplicate `AC` or `Design Element` identifier across §3 | 0 duplicates |

If any check fails → re-edit this file. Do **not** edit `SRS.md` to satisfy the matrix; SRS is APPROVED.

---

## 8. Risk-to-Link Map

Maps each risk in `SRS.md` §8 to the AC + design + test that mitigates it.

| Risk ID | Risk | Mitigating AC(s) | Mitigating Design | Mitigating Test(s) |
|---------|------|------------------|-------------------|---------------------|
| R1 | Concurrent / interrupted write corrupting `tasks.json` | NFR-03.AC-1 | `taskq.store.atomic_write_json` | `TC-NFR03-01` |
| R2 | Subprocess hang | FR-02.AC-4 | `taskq.executor.run_task` (TimeoutExpired), `taskq.cli.run_cmd` (exit 4 mapping) | `TC-FR02-04` |
| R3 | Secret leakage to disk via stdout/stderr tails | NFR-03.AC-2 | `taskq.redact.redact_line` | `TC-NFR03-02` (+ sub-cases) |

---

## 9. Out-of-Scope / Deferred

| Tag | Description | Reference |
|-----|-------------|-----------|
| NFR-99 (none) | No deferred requirements — matches `SRS.md` §7 NFR-99 verdict verbatim; no row invented. | SRS.md §7, SPEC_TRACKING.md §5 |

---

## 10. Change Log

| Date | Round | Change | Author |
|------|-------|--------|--------|
| 2026-06-29 | 1 (initial) | Authored TRACEABILITY_MATRIX.md from `SRS.md` (APPROVED). Established bidirectional FR ↔ Design ↔ Test links for all 21 ACs across FR-01..FR-03 + NFR-01..NFR-03. Module map derived from `SPEC.md` §2 + §3 + §5. No invention of FRs / ACs / NFR-99 items. Cross-cutting concerns enumerated in §5; risk-to-link map in §8. | REQUIREMENTS_ENGINEER (Agent A) |

---

*End of TRACEABILITY_MATRIX.md — Phase 1 deliverable. Awaiting BUSINESS_ANALYST (Agent B) peer review for APPROVE → next Sub-Task 4/4 (TEST_INVENTORY.yaml).*