# Specification Tracking Matrix — taskq

> Source of truth: `01-requirements/SRS.md` (APPROVED).
> Project: taskq — local task queue CLI (Python 3.11 stdlib).
> Purpose: assign per-FR / per-AC owner, status, and verification hookup for downstream Phases (P2 architecture, P3 implementation TDD, P4 testing, P5 verification, P6 quality, P8 config).

---

## 1. Registry

| Field | Value |
|-------|-------|
| Project | taskq |
| SPEC source | `/Users/johnny/projects/integration-test/SPEC.md` v2.0.0 (2026-06-15) |
| SRS source | `01-requirements/SRS.md` |
| FR count | 3 (FR-01, FR-02, FR-03) |
| NFR count | 3 (NFR-01, NFR-02, NFR-03) |
| Total AC count | 20 (FR: 15, NFR: 5) — see §2 |
| Generated | 2026-06-29 (Phase 1, Agent A sub-task 2/4) |

> AC count cross-check vs. `01-requirements/SRS.md` §5 table: 20 rows (15 FR + 5 NFR — NFR-01 has 1 AC, NFR-02 has 2 ACs, NFR-03 has 2 ACs).

---

## 2. Per-FR Tracking

### FR-01 — 任務模型與持久化

| AC ID | Description (1-line) | Owner | Status | Verification Hook | Source |
|-------|----------------------|-------|--------|-------------------|--------|
| AC-FR-01-01 | Empty / whitespace-only command → reject (exit 2, no store write) | @phase3-impl | RED | P3 TDD: `test_fr01_001_empty_command_rejected` | SRS §3 FR-01 驗證規則 row 1 |
| AC-FR-01-02 | Command length > 1000 chars → reject | @phase3-impl | RED | P3 TDD: `test_fr01_002_length_exceeds_1000_rejected` | SRS §3 FR-01 驗證規則 row 2 |
| AC-FR-01-03 | Injection chars `; \| & $ > < `` ` → reject (NFR-02 cross-link) | @phase3-impl | RED | P3 TDD: `test_fr01_003_injection_chars_rejected` (one negative per char) | SRS §3 FR-01 驗證規則 row 3 |
| AC-FR-01-04 | On pass: uuid4 8-hex id, status `pending`, fields `command` + `created_at` | @phase3-impl | RED | P3 TDD: `test_fr01_004_pending_fields_initialized` | SRS §3 FR-01 通過驗證 |
| AC-FR-01-05 | Atomic write `$TASKQ_HOME/tasks.json` (tmp + `os.replace`) | @phase3-impl + @phase4-test | RED | P4: `test_fr01_005_atomic_write_survives_interrupt` | SRS §3 FR-01 通過驗證 + NFR-03 |
| AC-FR-01-06 | `tasks.json` corrupted → detect, exit 1, stderr `store corrupted` (no silent rebuild) | @phase3-impl | RED | P3 TDD: `test_fr01_006_corrupt_store_exit1` | SRS §3 FR-01 通過驗證 |

**FR-01 sub-tasks (P3 work-package prep)**:
- `impl_subtask_fr01_validation` — owns AC-FR-01-01/02/03 → validate_command().
- `impl_subtask_fr01_persistence` — owns AC-FR-01-04/05/06 → store.py.

### FR-02 — 任務執行與重試

| AC ID | Description (1-line) | Owner | Status | Verification Hook | Source |
|-------|----------------------|-------|--------|-------------------|--------|
| AC-FR-02-01 | `subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)`; **no `shell=True` anywhere** | @phase3-impl + @phase5-static | RED | P3 TDD: `test_fr02_001_subprocess_form_no_shell`; P5: static scan asserts no `shell=True` in src/ | SRS §3 FR-02 + NFR-02 |
| AC-FR-02-02 | State machine `pending → running → done \| failed \| timeout`; exit 0→done, ≠0→failed, TimeoutExpired→timeout | @phase3-impl | RED | P3 TDD: `test_fr02_002_state_transitions` (parametrized over 3 exit classes) | SRS §3 FR-02 |
| AC-FR-02-03 | Result fields `exit_code`, `stdout_tail` (last 2000), `stderr_tail` (last 2000), `duration_ms`, `finished_at` | @phase3-impl | RED | P3 TDD: `test_fr02_003_result_fields_populated` | SRS §3 FR-02 |
| AC-FR-02-04 | On `failed`/`timeout` → auto-retry up to `TASKQ_RETRY_LIMIT` (default 2) | @phase3-impl | RED | P3 TDD: `test_fr02_004_retry_until_limit` + `test_fr02_004b_no_retry_on_done` | SRS §3 FR-02 |
| AC-FR-02-05 | Single-task mode `timeout` → **exit 4** | @phase3-impl | RED | P3 TDD: `test_fr02_005_timeout_exit_code_4` | SRS §3 FR-02 |
| AC-FR-02-06 | Unexpected exception → exit 1 (no bare `except:` swallowing) | @phase3-impl | RED | P3 TDD: `test_fr02_006_unexpected_exception_exit1` | SRS §3 FR-02 |

**FR-02 sub-tasks (P3 work-package prep)**:
- `impl_subtask_fr02_runner` — owns AC-FR-02-01/02/04/05/06 → runner.py.
- `impl_subtask_fr02_result` — owns AC-FR-02-03 → result serialization (incl. stdout_tail/stderr_tail capture).

### FR-03 — CLI 整合與查詢

| AC ID | Description (1-line) | Owner | Status | Verification Hook | Source |
|-------|----------------------|-------|--------|-------------------|--------|
| AC-FR-03-01 | argparse subcommands: `submit` / `run` / `status` / `list` / `clear`; `status <unknown>` → exit 2 + `unknown task: <id>` | @phase3-impl | RED | P3 TDD: `test_fr03_001_subcommands_dispatch` + `test_fr03_001b_status_unknown_id_exit2` | SRS §3 FR-03 |
| AC-FR-03-02 | Global flag `--json`: machine-readable single-line JSON output | @phase3-impl | RED | P3 TDD: `test_fr03_002_json_flag_single_line` (validates `json.loads` parses one line) | SRS §3 FR-03 |
| AC-FR-03-03 | Exit codes: `0` success / `2` validation (incl. unknown id) / `4` timeout / `1` other internal | @phase3-impl + @phase4-test | RED | P4: `test_fr03_003_exit_code_matrix` covers all 4 codes via parametrized cases | SRS §3 FR-03 |

**FR-03 sub-tasks (P3 work-package prep)**:
- `impl_subtask_fr03_cli` — owns AC-FR-03-01/02/03 → cli.py (argparse wiring + exit-code policy).

### NFR-01 — Performance

| AC ID | Description (1-line) | Owner | Status | Verification Hook | Source |
|-------|----------------------|-------|--------|-------------------|--------|
| AC-NFR-01-01 | `submit` + `status` combined p95 < 50ms over 100 iterations (excludes subprocess exec) | @phase5-perf | NOT-STARTED | P5: `perf_fr03_nfr01_p95_under_50ms` benchmark (100-iter loop, time.perf_counter) | SRS §4 NFR-01 |

### NFR-02 — Security

| AC ID | Description (1-line) | Owner | Status | Verification Hook | Source |
|-------|----------------------|-------|--------|-------------------|--------|
| AC-NFR-02-01 | `shell=True` forbidden across all codebase | @phase5-static + @phase6-quality | NOT-STARTED | P5: `grep -rn "shell=True" src/` must yield 0; P6 Gate 4 quality scan re-runs | SRS §4 NFR-02 |
| AC-NFR-02-02 | FR-01 injection blacklist must have test coverage (TDD evidence) | @phase3-impl + @phase4-test | RED | P3: `test_fr01_003_*` (one case per char) — coverage tool run in P4 | SRS §4 NFR-02 |

### NFR-03 — Reliability

| AC ID | Description (1-line) | Owner | Status | Verification Hook | Source |
|-------|----------------------|-------|--------|-------------------|--------|
| AC-NFR-03-01 | `tasks.json` atomic write (crash mid-write → legal JSON recoverable) | @phase3-impl + @phase4-test | RED | P3: `test_fr01_005_atomic_write`; P4: chaos test simulates SIGKILL mid-write, asserts post-state parses | SRS §4 NFR-03 |
| AC-NFR-03-02 | `stdout_tail`/`stderr_tail` line-level redaction of `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` → `[REDACTED]` | @phase3-impl | RED | P3 TDD: `test_nfr03_002_secret_line_redacted` (parametric over both patterns + non-match control) | SRS §4 NFR-03 |

---

## 3. Status Codes

| Status | Meaning | Phase-of-origin |
|--------|---------|-----------------|
| `RED` | Test exists (or will exist in P3) and currently fails — TDD-red phase | P3 |
| `GREEN` | Implementation passing test | P3 → P4 |
| `NOT-STARTED` | Verification deferred to a later phase (perf / static / chaos) | P5 / P6 |
| `BLOCKED` | Cannot start pending dependency or external signal | any |

> All FR-01 / FR-02 / FR-03 ACs enter P3 as **RED**. NFR-01 enters P5 as **NOT-STARTED**. NFR-02 / NFR-03 partial entries are RED (where TDD applies) or NOT-STARTED (where static / chaos applies).

---

## 4. Cross-Cutting Dependencies

| Dependency | From | To | Why |
|------------|------|-----|-----|
| AC-FR-01-03 needs AC-NFR-02-02 evidence | FR-01 §3 row 3 | NFR-02 row 2 | Inversion-of-test evidence (tests covering the blacklist) |
| AC-FR-02-01 must satisfy AC-NFR-02-01 | FR-02 §3 row 1 | NFR-02 row 1 | `shell=True` ban is global |
| AC-FR-01-05 implements AC-NFR-03-01 | FR-01 §3 atomic write bullet | NFR-03 row 1 | Same code path |
| AC-FR-02-03 captures tails consumed by AC-NFR-03-02 | FR-02 §3 result fields | NFR-03 row 2 | Redaction runs on the captured tails |
| AC-NFR-01-01 depends on FR-01 + FR-03 hot path | NFR-01 | FR-01 / FR-03 | Bench traverses submit+status only |

---

## 5. Coverage Sanity (P3 gate-1 readiness)

| Module (P2 decomposition intent) | Owns FR(s) | AC count | Test naming convention |
|----------------------------------|-----------|----------|----------------------|
| `cli.py` (argparse dispatch + exit-code policy) | FR-03 | 3 | `test_fr03_NNN_*` (pytest) |
| `validate.py` (command validation) | FR-01 (rows 1/2/3) | 3 | `test_fr01_001/002/003_*` (pytest, per SRS §3 owner=taskq Python) |
| `store.py` (atomic load/save + corruption detect) | FR-01 (rows 4/5/6) + NFR-03-01 | 4 | `test_fr01_004/005/006_*`, `test_nfr03_001_*` (pytest) |
| `runner.py` (subprocess + retry) | FR-02 | 6 | `test_fr02_NNN_*` (pytest) |
| `redact.py` (stdout_tail / stderr_tail redaction) | NFR-03-02 | 1 | `test_nfr03_002_*` (pytest) |
| `config.py` (TASKQ_* env) | all env-driven ACs | (no own AC) | n/a (cross-cut) |

**Total ACs by module = 17** (3 FR-03 + 3 FR-01-valid + 4 FR-01-store + 6 FR-02 + 1 NFR-03). Remaining 4 ACs (AC-NFR-01-01 perf, AC-NFR-02-01 static, AC-NFR-02-02 coverage, AC-FR-01-05 also ties to NFR-03-01 — already counted under store.py) live in P5 / P6 verification artifacts; not test-named at P3.

---

## 6. Gate Hookup (forward references)

| Gate | Feeds from this matrix | Goes to |
|------|------------------------|---------|
| Gate 1 (P3 exit, per-FR TDD) | §2 RED rows → GREEN | Gate 2 |
| Gate 2 (P3 exit — architecture + impl) | §5 module decomposition | Gate 3 |
| Gate 3 (P4 exit — testing quality) | §5 test naming + §2 AC rows | Gate 4 |
| Gate 4 (P6 full — 14 dims, ≥ 85) | §4 cross-cutting deps validated; §1 registry counts verified | Release |

---

## 7. Open / Deferred Items

- None at SPEC_TRACKING time. All FR-01..FR-03 and NFR-01..NFR-03 are concrete, falsifiable, and assigned an owner + verification hook per §2.

---

*Generated 2026-06-29 by Agent A (Sub-Task 2/4) in INGESTION MODE from `01-requirements/SRS.md` (APPROVED). No SRS edits — SRS is the source of truth.*
