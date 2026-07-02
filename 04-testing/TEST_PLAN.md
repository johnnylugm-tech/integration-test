# TEST PLAN — Phase 4 (Testing)

> Project: `taskq` — local task queue CLI (`python -m taskq`)
> Plan owner: P4 test plan author (one-shot, pre-execution)
> Python: `/Users/johnny/projects/integration-test/.venv/bin/python`
> Source spec: `01-requirements/SRS.md` v1.0 (canonical: `SPEC.md` v2.0.0, 2026-06-15)
> FR registry: `.methodology/quality_manifest.json` (`fr_ids: [FR-01, FR-02, FR-03]`)
> Canonical test surface: `/Users/johnny/projects/integration-test/TEST_INVENTORY.yaml` v1.2 (33 tc_ids, 1:1 with `01-requirements/TRACEABILITY_MATRIX.md` §2)
> Module under test: `03-development/src/taskq/` (`__main__`, `cli`, `executor`, `store`, `models`, `validation`, `redact`, `config`)
> Test discovery: `03-development/tests/` (pytest, conftest-managed `TASKQ_HOME` isolation)
> Quality gate: Gate 3 (P4 exit) — must pass before Phase 5

---

## 1. Scope and Coverage Matrix

This plan enumerates positive, negative, boundary, and edge-case test cases for **every** FR and **every** NFR listed in `.methodology/quality_manifest.json`. Each case maps 1:1 to a `tc_id` in `TEST_INVENTORY.yaml` and is anchored to a canonical AC ID from `SRS.md`.

| Scope | Source IDs | tc_count | Coverage |
|-------|-----------|----------|----------|
| FR-01 — Task Model & Persistence | AC-FR01-01..08 | 15 | negative (rejection × 4), boundary (length × 1), edge (injection × 7), positive (× 3) |
| FR-02 — Task Execution & Retry | AC-FR02-01..06 | 6 | positive (success × 2), negative (fail/timeout × 2), boundary (retry-limit × 1), edge (unhandled × 1) |
| FR-03 — CLI Integration & Query | AC-FR03-01..07 | 7 | positive (routing × 2), negative (unknown-id × 1), boundary (truncation × 1), edge (clear, --json, exit matrix × 3) |
| NFR-01 — Performance | AC-NFR01-01 | 1 | benchmark (p95 over 100 iter) |
| NFR-02 — Security | AC-NFR02-01..02 | 2 | static grep (shell=True), coverage meta (blacklist) |
| NFR-03 — Reliability | AC-NFR03-01..02 | 2 | crash-injection (atomic write), redaction (regex unit + integration) |
| **Total** | — | **33** | All 22 canonical ACs covered (1:1 expanded into 33 executable cases) |

Coverage verification rule: `sum(fr_count) + nfr_count == 33` and the tc_id sets in `TEST_PLAN.md` MUST equal the sets in `TEST_INVENTORY.yaml` `coverage_summary.by_fr`. Any deviation is a Gate 3 blocker.

---

## 2. Test Strategy

### 2.1 Layers
- **unit** (`tests/test_fr01_submit.py` core validators): pure-function validation, no subprocess, no disk.
- **integration** (everywhere else): subprocess `python -m taskq ...` invocation against a per-test `TASKQ_HOME` (`tests/conftest.py`).
- **cross_cutting**: repo-wide invariants (NFR-02 grep), atomic-write crash injection (NFR-03), p95 benchmark (NFR-01).

### 2.2 Isolation contract
- `TASKQ_HOME` is redirected per-test via env-var override (`tests/conftest.py`).
- `tasks.json` is created/cleared in `setup` / torn down in `teardown`.
- No test relies on host CWD, no test mutates `~/.taskq` or `$PWD/tasks.json`.

### 2.3 Execution order
1. Run FR-01 unit (validators) — these are pure functions and must pass first to gate FR-03 routing.
2. Run FR-01 integration (store writes, atomic-write, corruption, no-write-on-reject).
3. Run FR-02 integration (subprocess invocation, state machine, fields, retry, timeout, unhandled).
4. Run FR-03 integration (routing, status, list, clear, --json, exit matrix).
5. Run NFR cross-cutting (perf benchmark, security grep, redaction, atomic crash).

### 2.4 Pass/fail criteria
- All 33 cases pass.
- Coverage ≥ 95% (per `quality_manifest.json.quality_targets.min_coverage`).
- No `shell=True` literal anywhere in `03-development/src/`.
- p95 < 50 ms over 100 `submit + status` iterations (warm-process, no subprocess exec).

### 2.5 Out-of-scope (per SRS §6)
- Multi-process concurrency, daemon mode, network APIs, auth/authz, config files, i18n. Not tested.

---

## 3. FR-01 — Task Model & Persistence (`taskq.store` + `taskq.cli.submit`)

**Canonical spec:** `SPEC.md` §3 FR-01; **SRS:** §3.1; **Owning module:** `taskq.store` + `taskq.cli.submit`.
**Validation rules** (per SPEC): non-empty / length ≤ 1000 / no injection chars `; | & $ > < \``.

### 3.1 Negative — Validation Rejection (rejection must write NOTHING to storage)

| ID | Category | Description | Input | Expected Output | Priority |
|----|----------|-------------|-------|-----------------|----------|
| TC-FR01-01 | negative | Empty command → exit 2, no write | `python -m taskq submit ""` | exit_code=2; stderr non-empty; `tasks.json` byte-identical to pre-call | P0 |
| TC-FR01-01b | negative | Whitespace-only command → exit 2, no write | `python -m taskq submit "   "` | exit_code=2; stderr non-empty; `tasks.json` unchanged | P0 |
| TC-FR01-02b | boundary | Length boundary 1000/1001 chars | (a) `submit` 1000-char `a...a` → accept; (b) 1001-char → reject | (a) exit_code=0; (b) exit_code=2; on (b) `tasks.json` unchanged | P0 |
| TC-FR01-03a | edge / security | Injection char `;` rejected | `submit "echo a;b"` | exit_code=2; `tasks.json` unchanged | P0 |
| TC-FR01-03b | edge / security | Injection char `\|` rejected | `submit "echo a\|b"` | exit_code=2; `tasks.json` unchanged | P0 |
| TC-FR01-03c | edge / security | Injection char `&` rejected | `submit "echo a&b"` | exit_code=2; `tasks.json` unchanged | P0 |
| TC-FR01-03d | edge / security | Injection char `$` rejected | `submit "echo $HOME"` | exit_code=2; `tasks.json` unchanged | P0 |
| TC-FR01-03e | edge / security | Injection char `>` rejected | `submit "echo a>file"` | exit_code=2; `tasks.json` unchanged | P0 |
| TC-FR01-03f | edge / security | Injection char `<` rejected | `submit "echo a<file"` | exit_code=2; `tasks.json` unchanged | P0 |
| TC-FR01-03g | edge / security | Injection char `` ` `` rejected | `submit "echo \`pwd\`"` | exit_code=2; `tasks.json` unchanged | P0 |

### 3.2 Positive — Submit success path

| ID | Category | Description | Input | Expected Output | Priority |
|----|----------|-------------|-------|-----------------|----------|
| TC-FR01-04 | positive | Valid submit → write pending record | `submit "echo hi"` | exit_code=0; `tasks.json` parses; exactly 1 record; `task.id` matches `[0-9a-f]{8}`; `task.status == "pending"`; `task.command == "echo hi"`; `task.created_at` is ISO 8601 | P0 |
| TC-FR01-05 | positive | Pending record carries exact field set | inspect `tasks.json` after submit | record fields = `{id, status="pending", command, attempts, created_at}`; field set verbatim from canonical | P0 |

### 3.3 Reliability / boundary — atomic write + corruption + no-write-on-reject

| ID | Category | Description | Input | Expected Output | Priority |
|----|----------|-------------|-------|-----------------|----------|
| TC-FR01-06 | boundary / reliability | Atomic write uses tmp + os.replace | inspect write path (monkey-patch `os.replace` to assert tmp-file pattern `tasks.json.tmp.<id>`); crash-inject mid-write | tmp path then `os.replace`; no partial writes observable after interruption | P0 |
| TC-FR01-07 | edge / reliability | Corrupt `tasks.json` → exit 1 + stderr | write `"{not json"` to `tasks.json`; run `submit "echo x"` | exit_code=1; stderr contains literal `store corrupted`; `tasks.json` NOT silently rebuilt on disk | P0 |
| TC-FR01-08 | negative / boundary | Reject path leaves storage byte-for-byte unchanged | capture `mtime`/`size` of `tasks.json`; submit rejected input | `tasks.json` byte-identical; `mtime`/`size` unchanged after rejection | P0 |

---

## 4. FR-02 — Task Execution & Retry (`taskq.executor` — high-risk)

**Canonical spec:** `SPEC.md` §3 FR-02; **SRS:** §3.2; **Owning module:** `taskq.executor` (high-risk per manifest).
**Exit-code matrix:** `0` success/failed-exhausted / `4` timeout-exhausted / `1` other internal / `2` unknown task id.

| ID | Category | Description | Input | Expected Output | Priority |
|----|----------|-------------|-------|-----------------|----------|
| TC-FR02-01 | positive / security | Subprocess invocation form + no `shell=True` | submit `"echo hi"`, then `run <id>` | invocation uses `subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)`; repo-wide `shell=True` count = 0; success path → `status="done"`, `exit_code=0` | P0 |
| TC-FR02-02 | positive | State-machine transitions | (a) exit-0 cmd; (b) exit-1 cmd; (c) `sleep 5` with `TASKQ_TASK_TIMEOUT=1` | (a) `pending → running → done`; (b) `… → failed`; (c) `… → timeout`; mapping verbatim from canonical | P0 |
| TC-FR02-03 | positive / boundary | Result fields populated + 2000-char tail truncation | submit `"python -c 'print(\"x\"*5000)'"` (stdout > 2000 chars); run | record carries `exit_code`, `stdout_tail` (last 2000 chars), `stderr_tail` (last 2000 chars), `duration_ms` (int ≥ 0), `finished_at` (ISO 8601); tail length ≤ 2000 | P0 |
| TC-FR02-04 | edge / boundary | Retry cap = `TASKQ_RETRY_LIMIT` (default 2) | submit `"false"` with default env; run; observe attempts | retries triggered on `failed`; total attempts ≤ `TASKQ_RETRY_LIMIT + 1` (1 initial + 2 retries = 3); exhaustion → final `status="failed"` | P0 |
| TC-FR02-05 | boundary / timeout | Single-task-mode timeout → exit 4 | submit `"sleep 5"`; `TASKQ_TASK_TIMEOUT=0.5`; `run <id>` | process exit_code=4; persisted `status="timeout"`; `exit_code == 4` on record | P0 |
| TC-FR02-06 | negative / edge | Unhandled exception → exit 1, no bare `except:` | inject `FileNotFoundError` (submit `"definitely-not-a-binary-xyz"`); run | process exit_code=1; persisted record has `status="failed"`, `stderr_tail` carries error; source has no bare `except:` (lint-enforced via `pylint/ruff`) | P0 |

---

## 5. FR-03 — CLI Integration & Query (`taskq.cli`)

**Canonical spec:** `SPEC.md` §3 FR-03; **SRS:** §3.3; **Owning module:** `taskq.cli` (`__main__.py`).

| ID | Category | Description | Input | Expected Output | Priority |
|----|----------|-------------|-------|-----------------|----------|
| TC-FR03-01 | positive / routing | `submit "<cmd>"` → FR-01 | `submit "echo hi"` then inspect `tasks.json` | record present with FR-01 field set; delegation verbatim from canonical | P0 |
| TC-FR03-02 | positive / routing | `run <id>` → FR-02 | submit `"echo hi"`; `run <id>` | record transitions; delegation verbatim from canonical | P0 |
| TC-FR03-03 | negative | `status <unknown>` → exit 2 + stderr message | `status deadbeef` (no record) | exit_code=2; stderr contains `unknown task: deadbeef`; `status <existing>` returns all fields, exit_code=0 | P0 |
| TC-FR03-04 | boundary | `list` truncates `command` to first 50 chars | submit a 60-char `"echo "` + 55-char tail; `list` | stdout JSON shows `command` truncated to first 50 chars; persisted record unchanged (truncation is display-only) | P0 |
| TC-FR03-05 | positive / mutation | `clear` empties `tasks.json` | submit two tasks; `clear`; `list` | exit_code=0; `tasks.json` parses as `[]`; subsequent `list` shows empty array | P0 |
| TC-FR03-06 | boundary / format | `--json` → single-line JSON, no trailing newline | `submit "echo hi" --json`; capture stdout | exactly one line; `json.loads` round-trips; no trailing `\n`; record field set matches FR-01 | P0 |
| TC-FR03-07 | boundary / exit-matrix | Full exit-code table | (a) `submit "echo hi"` → 0; (b) `submit ""` → 2; (c) `submit "echo a;b"` → 2; (d) `status deadbeef` → 2; (e) `run <id-of-sleep5-with-tiny-timeout>` → 4; (f) corrupt store then `list` → 1 | exit codes = 0/2/2/2/4/1 respectively — verbatim from canonical exit-code matrix | P0 |

---

## 6. NFR-01 — Performance (`taskq.cli + taskq.store`)

**Canonical spec:** `SPEC.md` §4 NFR-01; **target:** `p95 < 50ms` over 100 `submit + status` iterations, **excluding subprocess execution** (measurement boundary owned by harness).

| ID | Category | Description | Input | Expected Output | Priority |
|----|----------|-------------|-------|-----------------|----------|
| TC-NFR01-01 | benchmark / boundary | p95 latency of 100× submit+status | 100-iter warm loop: each iter `submit "echo x"` then `status <new_id>` | measured p95 < 50ms; subprocess execution time explicitly excluded from measurement window | P0 |

---

## 7. NFR-02 — Security (codebase-wide invariant)

**Canonical spec:** `SPEC.md` §4 NFR-02; `shell=True` forbidden codebase-wide; FR-01 blacklist must have test coverage.

| ID | Category | Description | Input | Expected Output | Priority |
|----|----------|-------------|-------|-----------------|----------|
| TC-NFR02-01 | static-grep / invariant | No `shell=True` literal in `03-development/src/` | `grep -rn 'shell=True' 03-development/src/` | exit_code=1 (grep finds zero matches); zero occurrences | P0 |
| TC-NFR02-02 | coverage-meta | All 7 injection chars have parametrized submit tests | inspect `tests/test_fr01_submit.py` | test functions `test_fr01_submit_injection_{semicolon,pipe,amp,dollar,gt,lt,backtick}` exist and each asserts exit_code=2 + storage unchanged | P0 |

---

## 8. NFR-03 — Reliability (`taskq.store` + `taskq.executor`)

**Canonical spec:** `SPEC.md` §4 NFR-03; atomic write survives mid-write crash; secret-line redaction.

| ID | Category | Description | Input | Expected Output | Priority |
|----|----------|-------------|-------|-----------------|----------|
| TC-NFR03-01 | crash-injection / reliability | Atomic write survives SIGKILL mid-write | `submit`; SIGKILL subprocess between `write(tmp)` and `os.replace` (use a patched `os.replace` that sleeps to widen window); on next CLI invocation | `tasks.json` either absent or fully-valid JSON; no truncated/half-written file observable | P0 |
| TC-NFR03-02 | redaction / unit+integration | `(sk-[A-Za-z0-9_-]{8,}\|token=\S+)` lines replaced by `[REDACTED]` | (a) unit: `redact.redact("sk-abcdef12345\nhello\ntoken=abc\nbye\n")`; (b) integration: command emits such lines, run, inspect `tasks.json` | (a) → `"[REDACTED]\nhello\n[REDACTED]\nbye\n"` (line-wise); (b) `stdout_tail`/`stderr_tail` in persisted record has matching lines replaced verbatim with `[REDACTED]`; no secret substring persists | P0 |

---

## 9. Test Execution Procedure

```bash
# Environment
cd /Users/johnny/projects/integration-test
source .venv/bin/activate

# 1. Full suite (Gate 3 trigger)
.venv/bin/python -m pytest 03-development/tests/ -v --tb=short

# 2. Per-FR layered runs
.venv/bin/python -m pytest 03-development/tests/test_fr01_submit.py -v     # FR-01 unit + integration
.venv/bin/python -m pytest 03-development/tests/test_fr02_run.py -v        # FR-02 integration
.venv/bin/python -m pytest 03-development/tests/test_fr03_cli.py -v        # FR-03 integration
.venv/bin/python -m pytest 03-development/tests/test_nfr.py -v             # NFR cross-cutting

# 3. Coverage gate (must be ≥ 95%)
.venv/bin/python -m pytest 03-development/tests/ \
    --cov=taskq --cov-report=term-missing --cov-fail-under=95

# 4. Static NFR-02 grep
grep -rn 'shell=True' 03-development/src/ && exit 1 || echo "OK: 0 matches"

# 5. Performance benchmark (TC-NFR01-01)
.venv/bin/python -m pytest 03-development/tests/test_nfr.py::test_nfr01_p95_latency -v -s
```

---

## 10. Acceptance for Gate 3 (P4 Exit)

| Check | Threshold | Source |
|-------|-----------|--------|
| All 33 tc_ids pass | 33/33 | `TEST_INVENTORY.yaml.coverage_summary.total_test_cases` |
| Line coverage on `taskq/*` | ≥ 95% | `quality_manifest.json.quality_targets.min_coverage` |
| Cyclomatic complexity (per-fn) | ≤ 10 | `quality_manifest.json.quality_targets.max_complexity` |
| Coupling | ≤ 0.30 | `quality_manifest.json.quality_targets.max_coupling` |
| `shell=True` count in `src/` | 0 | `AC-NFR02-01` |
| Blacklist coverage | 7/7 chars | `AC-NFR02-02` |
| Atomic-write crash safety | pass | `AC-NFR03-01` |
| Redaction regex correctness | pass | `AC-NFR03-02` |
| p95 latency | < 50 ms / 100 iter | `AC-NFR01-01` |

Gate 3 passes only when every row above is green. Any deviation → log as Gate 3 defect, do not advance to Phase 5.

---

## 11. Cross-Reference Tables

### 11.1 FR → TC coverage (must match `TEST_INVENTORY.yaml.coverage_summary.by_fr`)

| FR / NFR | ACs | tc_count | tc_ids |
|----------|-----|----------|--------|
| FR-01 | 8 | 15 | TC-FR01-01, TC-FR01-01b, TC-FR01-02b, TC-FR01-03a, TC-FR01-03b, TC-FR01-03c, TC-FR01-03d, TC-FR01-03e, TC-FR01-03f, TC-FR01-03g, TC-FR01-04, TC-FR01-05, TC-FR01-06, TC-FR01-07, TC-FR01-08 |
| FR-02 | 6 | 6  | TC-FR02-01, TC-FR02-02, TC-FR02-03, TC-FR02-04, TC-FR02-05, TC-FR02-06 |
| FR-03 | 7 | 7  | TC-FR03-01, TC-FR03-02, TC-FR03-03, TC-FR03-04, TC-FR03-05, TC-FR03-06, TC-FR03-07 |
| NFR-01 | 1 | 1 | TC-NFR01-01 |
| NFR-02 | 2 | 2 | TC-NFR02-01, TC-NFR02-02 |
| NFR-03 | 2 | 2 | TC-NFR03-01, TC-NFR03-02 |
| **Total** | **26** | **33** | — |

### 11.2 Quality-manifest FR list ↔ this plan

`quality_manifest.json.fr_ids = [FR-01, FR-02, FR-03]`. All three FRs are covered (§3, §4, §5). NFRs `NFR-01..NFR-03` are mapped via `quality_manifest.json.nfr_dimension_mapping` and each has a dedicated section (§6, §7, §8). No manifest FR/NFR is omitted.

---

## 12. Risks and Watch-outs

| Risk | Mitigation in plan |
|------|--------------------|
| Coverage drop on `executor.py` (high-risk module) | TC-FR02-01..06 all integration; explicit `shell=True` lint + atomic-write crash test |
| Boundary off-by-one on 1000/1001 char limit | TC-FR01-02b tests both sides of boundary in a single parameterized case |
| 2000-char tail truncation edge | TC-FR02-03 emits 5000 chars and asserts `len(tail) <= 2000` and tail == last 2000 chars |
| Redaction regex fragility | TC-NFR03-02 covers both unit (`redact.redact` direct) and integration (`run` → persisted record) paths |
| `p95` benchmark flakiness | TC-NFR01-01 uses warm-process loop; excludes subprocess exec per canonical boundary |
| Corrupt-store regression | TC-FR01-07 asserts exit 1 + stderr message + "no silent rebuild" invariant |

---

*End of TEST_PLAN.md — covers all FRs (FR-01, FR-02, FR-03) and NFRs (NFR-01, NFR-02, NFR-03) per `quality_manifest.json`; 33 test cases enumerated, 1:1 with `TEST_INVENTORY.yaml` v1.2.*