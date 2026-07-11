# Traceability Matrix — integration-test (`taskq`)

> **Project**: `taskq` — local task queue CLI (Python 3.11 stdlib only)
> **Canonical source**: `SPEC.md` v4.0.0 (2026-07-11) — 5 FR / 10 NFR / 8 env vars
> **Upstream inputs (verbatim, not modified here)**: `01-requirements/SRS.md` (LOCKED 2026-07-11), `01-requirements/SPEC_TRACKING.md`
> **Owner**: REQUIREMENTS_ENGINEER (Sub-Task 3/4, Round 1)
> **Direction**: bidirectional — FR/NFR → module → AC (forward) and AC → FR/NFR + module → FR/NFR (backward)

---

## 1. Method & Legend

This matrix links every requirement to (a) its implementing module(s) in `src/taskq/` (SRS Appendix A), (b) its testable acceptance criteria (SRS §3/§4), and (c) the downstream deliverable that verifies it. It is derived from `SRS.md` §3/§4/§5 and reconciles 1:1 with `SPEC_TRACKING.md` §3 (69 AC) and §4 (coupling edges).

- **Module keys** (SRS Appendix A): `cli` = `cli.py`, `store` = `store.py` (high-risk), `executor` = `executor.py` (high-risk), `breaker` = `breaker.py`, `cache` = `cache.py`, `config` = `config.py`, `models` = `models.py`, `main` = `__main__.py`.
- **Test type**: `unit` / `integration` / `bench` (pytest-benchmark) / `static` (grep / code review / docstring scan).
- **Verifier**: downstream deliverable that closes the loop — `02-architecture/TEST_SPEC.md` (test design), `04-testing/TEST_PLAN.md` + `04-testing/TEST_RESULTS.md` (execution), `05-verification/BASELINE.md` + `05-verification/VERIFICATION_REPORT.md` (baseline sign-off). Authoring of the code + tests happens in Phase 3 per-FR Gate 1; those artifacts are not `NN-stage/*.md` deliverables and are referenced by path only.

---

## 2. Forward Trace — FR → Module → AC → Verifier

| FR | Title | Primary Module(s) | Supporting Module(s) | AC (SRS §3) | AC count | Coupled NFR | Verifier deliverable |
|----|-------|-------------------|----------------------|-------------|----------|-------------|----------------------|
| FR-01 | 任務提交與驗證 (`submit`) | `cli`, `store` | `models`, `config` | AC-FR01-01 … AC-FR01-09 | 9 | NFR-02, NFR-03 | `TEST_SPEC.md` → `TEST_PLAN.md` → `TEST_RESULTS.md` |
| FR-02 | 任務執行器 (`run` / `run --all`) | `executor`, `store` | `models`, `config` | AC-FR02-01 … AC-FR02-08 | 8 | NFR-02, NFR-03, NFR-04, NFR-08 | `TEST_SPEC.md` → `TEST_PLAN.md` → `TEST_RESULTS.md` |
| FR-03 | 重試與斷路器 | `executor`, `breaker` | `config`, `store` | AC-FR03-01 … AC-FR03-08 | 8 | NFR-03 | `TEST_SPEC.md` → `TEST_PLAN.md` → `TEST_RESULTS.md` |
| FR-04 | 結果 TTL 快取 (`run --cached`) | `cache`, `executor` | `config`, `models` | AC-FR04-01 … AC-FR04-06 | 6 | NFR-03, NFR-08 | `TEST_SPEC.md` → `TEST_PLAN.md` → `TEST_RESULTS.md` |
| FR-05 | CLI 整合 (argparse + exit codes) | `cli` | `main`, all FR modules | AC-FR05-01 … AC-FR05-07 | 7 | (integrates all) | `TEST_SPEC.md` → `TEST_PLAN.md` → `TEST_RESULTS.md` |

**FR AC subtotal: 9 + 8 + 8 + 6 + 7 = 38.**

### 2.1 FR per-AC detail

| AC | Requirement point (SRS §3) | Module(s) | Test type | Cross-NFR |
|----|-----------------------------|-----------|-----------|-----------|
| AC-FR01-01 | happy `submit "echo hi"` → exit 0 + 8-hex id + full `tasks.json` | `cli`, `store`, `models` | integration | — |
| AC-FR01-02 | `--json` → single-line `{"id":..., "status":"pending"}` | `cli` | unit | — |
| AC-FR01-03 | empty command → exit 2; no write | `cli`, `store` | unit | — |
| AC-FR01-04 | whitespace-only → exit 2 | `cli`, `store` | unit | — |
| AC-FR01-05 | length > 1000 → exit 2 | `cli`, `store` | unit | — |
| AC-FR01-06 | injection `;` → exit 2 | `cli`, `store` | unit | NFR-02 |
| AC-FR01-07 | injection `\|` `&` `$` `>` `<` `` ` `` (6 cases) → exit 2 | `cli`, `store` | unit | NFR-02 |
| AC-FR01-08 | `--name` dup vs pending/running → exit 2; no write | `store` | unit | — |
| AC-FR01-09 | mid-write `OSError` (monkeypatch) → `tasks.json` still valid | `store` | unit | NFR-03 |
| AC-FR02-01 | `run <id>` happy → `done` + exit_code=0 + stdout `hi\n` | `executor`, `store` | integration | — |
| AC-FR02-02 | `submit "false"` → `failed` + exit_code=1 | `executor` | integration | — |
| AC-FR02-03 | `TASKQ_TASK_TIMEOUT=1` + `sleep 5` → `timeout` + exit 4 | `executor`, `config` | integration | NFR-06 |
| AC-FR02-04 | stdout_tail = last 2000 chars | `executor` | unit | — |
| AC-FR02-05 | `run --all` 3 tasks → all `done` + valid JSON | `executor`, `store` | integration | — |
| AC-FR02-06 | `run --all` 10 tasks concurrent → valid JSON, no partial write | `executor`, `store` | integration | NFR-08 |
| AC-FR02-07 | `grep 'shell=True' src/taskq/` → 0 hits | `executor` (whole tree) | static | NFR-02 |
| AC-FR02-08 | duration_ms ≥ 0 + finished_at ISO | `executor`, `models` | unit | — |
| AC-FR03-01 | `failed` auto-retry RETRY_LIMIT times | `executor`, `config` | unit | — |
| AC-FR03-02 | `timeout` auto-retry | `executor`, `config` | unit | — |
| AC-FR03-03 | nth retry waits sleep(`BACKOFF_BASE × 2^n`) (injected sleep) | `executor` | unit | — |
| AC-FR03-04 | 3 consecutive final failures → 4th `run` exit 3 + `breaker open` | `breaker`, `executor` | integration | NFR-06 |
| AC-FR03-05 | OPEN→cooldown→HALF_OPEN success→CLOSED + count reset | `breaker` | integration | — |
| AC-FR03-06 | HALF_OPEN probe fails → re-OPEN + cooldown restart | `breaker` | unit | — |
| AC-FR03-07 | OPEN persisted to `breaker.json`; cross-process restart still OPEN | `breaker`, `store` | integration | NFR-03 |
| AC-FR03-08 | `OPEN → CLOSED` recovery ≤ cooldown + 1s | `breaker` | integration | NFR-03 |
| AC-FR04-01 | TTL-fresh `run --cached` → no subprocess + `cached:true` | `cache`, `executor` | unit | — |
| AC-FR04-02 | TTL expired → re-exec + write `cache.json` | `cache` | unit | — |
| AC-FR04-03 | different command → no cross-hit (sha256 signature) | `cache` | unit | — |
| AC-FR04-04 | `failed`/`timeout` not cached (replay only `done`) | `cache` | unit | — |
| AC-FR04-05 | mid-write OSError → `cache.json` still valid | `cache` | unit | NFR-03 |
| AC-FR04-06 | `run --all` concurrent → `cache.json` valid, no partial entry | `cache` | integration | NFR-08 |
| AC-FR05-01 | `status <id>` → all fields | `cli` | integration | — |
| AC-FR05-02 | `status <id> --json` → single-line JSON | `cli` | unit | — |
| AC-FR05-03 | `list` 3 tasks → 3 rows | `cli` | integration | — |
| AC-FR05-04 | `list --status done` 5→3 → 3 rows | `cli` | integration | — |
| AC-FR05-05 | `clear` → 3 data files empty + subsequent `list` empty | `cli`, `store` | integration | — |
| AC-FR05-06 | `status <unknown-id>` → exit 2 + `unknown task: <id>` | `cli` | unit | — |
| AC-FR05-07 | exit codes `0/1/2/3/4` five scenarios reproducible | `cli`, `main` | integration | — |

---

## 3. Forward Trace — NFR → Module → AC → Verifier

| NFR | Category | Primary Module(s) | AC (SRS §4) | AC count | Anchoring FR | Verifier deliverable |
|-----|----------|-------------------|-------------|----------|--------------|----------------------|
| NFR-01 | performance | `cli`, `store` | AC-NFR01-01 | 1 | FR-01, FR-05 | `TEST_PLAN.md` (bench) → `TEST_RESULTS.md` |
| NFR-02 | security | `executor`, `store`, `cli` | AC-NFR02-01 … 03 | 3 | FR-01, FR-02 | `TEST_PLAN.md` → `TEST_RESULTS.md` |
| NFR-03 | reliability | `store`, `breaker`, `cache` | AC-NFR03-01 … 03 | 3 | FR-02, FR-03 | `TEST_PLAN.md` → `TEST_RESULTS.md` |
| NFR-04 | security | `executor`, `models` | AC-NFR04-01 … 04 | 4 | FR-02 | `TEST_SPEC.md` → `TEST_PLAN.md` → `TEST_RESULTS.md` |
| NFR-05 | maintainability | all `src/taskq/*` | AC-NFR05-01 … 02 | 2 | all FRs | `TEST_PLAN.md` → `TEST_RESULTS.md` |
| NFR-06 | deployability | `config` | AC-NFR06-01 … 02 | 2 | FR-02/03/04 | `TEST_PLAN.md` → `TEST_RESULTS.md` |
| NFR-07 | resilience | `store`, `cache`, `cli` | AC-NFR07-01 … 05 | 5 | FR-02, FR-04 | `TEST_SPEC.md` → `TEST_PLAN.md` → `TEST_RESULTS.md` |
| NFR-08 | concurrency | `store`, `cache` | AC-NFR08-01 … 03 | 3 | FR-02, NFR-03 | `TEST_PLAN.md` → `TEST_RESULTS.md` |
| NFR-09 | scalability | `store`, `executor` | AC-NFR09-01 … 03 | 3 | FR-01, FR-02 | `TEST_PLAN.md` (bench) → `TEST_RESULTS.md` |
| NFR-10 | evolvability | `store`, `breaker`, `cache` | AC-NFR10-01 … 05 | 5 | NFR-03 | `TEST_PLAN.md` → `TEST_RESULTS.md` |

**NFR AC subtotal: 1 + 3 + 3 + 4 + 2 + 2 + 5 + 3 + 3 + 5 = 31.**

### 3.1 NFR per-AC detail

| AC | Requirement point (SRS §4) | Module(s) | Test type |
|----|-----------------------------|-----------|-----------|
| AC-NFR01-01 | `submit`+`status` 100 iter p95 < 50ms (pytest-benchmark) | `cli`, `store` | bench |
| AC-NFR02-01 | `grep 'shell=True' src/taskq/` → 0 hits | whole tree | static |
| AC-NFR02-02 | 6 injection chars each 1 pytest case (= AC-FR01-06/07) | `cli`, `store` | unit |
| AC-NFR02-03 | CI gate blocks `shell=True` regression (= AC-FR02-07) | whole tree | static |
| AC-NFR03-01 | 3 data files tmp + `os.replace`; mid-write sim → valid JSON | `store`, `breaker`, `cache` | unit |
| AC-NFR03-02 | `OPEN → CLOSED` ≤ cooldown + 1s (= AC-FR03-08) | `breaker` | integration |
| AC-NFR03-03 | `tasks.json` corruption → exit 1 + `store corrupted`, no silent rebuild | `store` | unit |
| AC-NFR04-01 | line with `sk-abcdef1234567890` → `[REDACTED]` | `executor` | unit |
| AC-NFR04-02 | line with `token=abc123` → `[REDACTED]` | `executor` | unit |
| AC-NFR04-03 | non-matching lines unchanged | `executor` | unit |
| AC-NFR04-04 | redaction happens before disk write (content check) | `executor`, `store`, `cache` | unit |
| AC-NFR05-01 | 100% public-symbol docstring coverage | all `src/taskq/*` | static |
| AC-NFR05-02 | each docstring ≥ 1 `[FR-XX]` / `[NFR-XX]` ref | all `src/taskq/*` | static |
| AC-NFR06-01 | `.env.example` declares 8 `TASKQ_*` vars + comments | `config` | static |
| AC-NFR06-02 | `config.py` centralized read + per-var default | `config` | unit |
| AC-NFR07-01 | `--inject-fault=corrupt-mid-write` → recover or fail-fast | `store`, `cache`, `cli` | unit |
| AC-NFR07-02 | `--inject-fault=oserror-on-write` → recover or fail-fast | `store`, `cache`, `cli` | unit |
| AC-NFR07-03 | `--inject-fault=disk-full` → recover or fail-fast | `store`, `cache`, `cli` | unit |
| AC-NFR07-04 | `--inject-fault=kill-mid-write` → recover or fail-fast | `store`, `cache`, `cli` | unit |
| AC-NFR07-05 | production path (no flag) disables fault injection (0% silent) | `cli` | static |
| AC-NFR08-01 | 4-process concurrent submit+run+clear → valid JSON, no loss | `store`, `cache` | integration |
| AC-NFR08-02 | POSIX `fcntl.flock` / Windows `msvcrt.locking` | `store` | static |
| AC-NFR08-03 | NFS / network fs detect → degrade + WARNING | `store` | unit |
| AC-NFR09-01 | 1000 tasks `submit`+`status` p95 < 100ms | `store`, `cli` | bench |
| AC-NFR09-02 | `run --all` 100 tasks → 100% valid, no loss | `executor`, `store` | integration |
| AC-NFR09-03 | memory peak < 100MB (tracemalloc, streaming iterator) | `store` | unit |
| AC-NFR10-01 | 3 data files root `version: 1` | `store`, `breaker`, `cache` | unit |
| AC-NFR10-02 | `version: 0` → auto-migrate v1 + `<file>.v0.bak` | `store`, `breaker`, `cache` | unit |
| AC-NFR10-03 | `version: 2` → refuse + upgrade prompt + exit 1 | `store`, `breaker`, `cache` | unit |
| AC-NFR10-04 | migrate failure → keep backup + exit 1 | `store`, `breaker`, `cache` | unit |
| AC-NFR10-05 | pytest fixture `v0 → v1` 100% + backup + readable | `store`, `breaker`, `cache` | unit |

---

## 4. Backward Trace — Module → Requirements

Confirms every implementing module traces back to at least one FR/NFR (no orphan module), and every module carrying an AC is reachable from §2/§3.

| Module | Risk | Owning FR(s) | Owning NFR(s) | Notes |
|--------|------|--------------|---------------|-------|
| `cli.py` | normal | FR-01, FR-05 | NFR-01, NFR-02, NFR-07 | argparse surface + validation + `--inject-fault` gating |
| `store.py` | **high-risk** | FR-01, FR-02 | NFR-01, NFR-03, NFR-07, NFR-08, NFR-09, NFR-10 | `tasks.json` atomic write + Lock; carries most NFRs |
| `executor.py` | **high-risk** | FR-02, FR-03, FR-04 | NFR-02, NFR-04, NFR-09 | subprocess (no `shell=True`) + retry + redaction |
| `breaker.py` | normal | FR-03 | NFR-03, NFR-10 | `breaker.json` state machine + persistence |
| `cache.py` | normal | FR-04 | NFR-03, NFR-07, NFR-08, NFR-10 | `cache.json` TTL + atomic + thread-safe |
| `config.py` | normal | (params for FR-02/03/04) | NFR-06 | 8 `TASKQ_*` centralized read + defaults |
| `models.py` | normal | FR-01, FR-02 | NFR-04 | task/status dataclasses + result fields |
| `__main__.py` | normal | FR-05 | — | `python -m taskq` entry, delegates to `cli` |

`__init__.py` is package scaffolding (no behavioral AC); excluded from the 8-module `no_circular_dependencies` graph per SRS §2.6.

---

## 5. FR ⇄ NFR Coupling (mirrors SPEC_TRACKING.md §4, verbatim edges)

| Edge | Anchor AC | Rationale |
|------|-----------|-----------|
| FR-01 → NFR-02 | AC-FR01-06/07 | submit injection blacklist is NFR-02's implementation anchor |
| FR-01 → NFR-03 | AC-FR01-09 | first store atomic-write evidence |
| FR-02 → NFR-02 | AC-FR02-07 | FR-02 is the only path `shell=True` could flow through |
| FR-02 → NFR-03 | AC-FR02-06 | concurrent `--all` partial-write protection |
| FR-02 → NFR-04 | AC-NFR04-01…04 | redaction target is FR-02 output (stdout/stderr tail) |
| FR-03 → NFR-03 | AC-FR03-07/08 | breaker cross-process persistence + recovery timing |
| FR-04 → NFR-03 | AC-FR04-05 | third atomic-write data file (`cache.json`) |
| FR-04 → NFR-08 | AC-FR04-06 | cache shares lock under `run --all` |
| FR-05 → all FRs | AC-FR05-07 | argparse integrates all commands; introduces no new behavior |
| NFR-05 → all FRs | AC-NFR05-02 | every public function must cite upstream `[FR-XX]`/`[NFR-XX]` |
| NFR-06 → FR-02/03/04 | AC-NFR06-01/02 | 8 env vars parameterize the 5 FRs |
| NFR-07 → FR-02/04 | AC-NFR07-01…05 | fault-injection touchpoints = store / cache |
| NFR-08 → FR-02 | AC-NFR08-01…03 | `fcntl`/`msvcrt` flock matches real `run --all` concurrency |
| NFR-09 → FR-01/02 | AC-NFR09-01/02 | scale 1000 submit + 100-task run integrity |
| NFR-10 → NFR-03 | AC-NFR10-02…05 | migration itself runs through the atomic-write path |

---

## 6. Downstream Deliverable Trace (which phase doc consumes each requirement)

| Requirement group | 02-architecture | 04-testing | 05-verification |
|-------------------|-----------------|------------|-----------------|
| FR-01 … FR-05 | `SAD.md` (module design), `TEST_SPEC.md` (test design) | `TEST_PLAN.md`, `TEST_RESULTS.md` | `BASELINE.md`, `VERIFICATION_REPORT.md` |
| NFR-01, NFR-09 (perf/scale) | `TEST_SPEC.md` (bench design) | `TEST_PLAN.md`, `TEST_RESULTS.md` | `VERIFICATION_REPORT.md` |
| NFR-02, NFR-04, NFR-07 (security/resilience) | `ADR.md`, `TEST_SPEC.md` | `TEST_PLAN.md`, `TEST_RESULTS.md` | `VERIFICATION_REPORT.md` |
| NFR-03, NFR-08, NFR-10 (atomicity/concurrency/schema) | `ADR.md` (constraints), `SAD.md` | `TEST_PLAN.md`, `TEST_RESULTS.md` | `VERIFICATION_REPORT.md` |
| NFR-05, NFR-06 (maintainability/deployability) | `SAD.md` | `TEST_PLAN.md`, `TEST_RESULTS.md` | `BASELINE.md` |

The 10 `SPEC §8` acceptance items (SRS §5) form the `05-verification/BASELINE.md` baseline AC set.

---

## 7. Coverage Validation (bidirectional completeness)

| Check | Expectation | Result |
|-------|-------------|--------|
| Every FR maps to ≥ 1 module | 5/5 | ✅ (§2) |
| Every NFR maps to ≥ 1 module | 10/10 | ✅ (§3) |
| Every FR maps to ≥ 1 AC | 5/5 (38 AC) | ✅ (§2.1) |
| Every NFR maps to ≥ 1 AC | 10/10 (31 AC) | ✅ (§3.1) |
| Total AC reconciles with SPEC_TRACKING §3 | 38 + 31 = **69** | ✅ |
| Every AC traces back to exactly one FR/NFR (no orphan AC) | 69/69 | ✅ (§2.1/§3.1) |
| Every behavioral module traces back to ≥ 1 requirement (no orphan module) | 8/8 | ✅ (§4) |
| High-risk modules (`store`, `executor`) explicitly tagged (SRS §2.6) | 2/2 | ✅ (§4) |
| Every FR/NFR has a downstream verifier deliverable | 15/15 | ✅ (§2/§3/§6) |
| Open gaps | 0 (per SPEC_TRACKING §5) | ✅ |

**Assertion**: the requirement→module→AC→verifier chain is closed in both directions with 0 orphans and 0 gaps. AC totals match `SPEC_TRACKING.md` §3 (69) and the 15 requirements match `SRS.md` §3/§4 (5 FR + 10 NFR).

---

## 8. Citations

- **SRS.md** §3 — FR-01..05 AC (lines 86–201)
- **SRS.md** §4 — NFR-01..10 AC (lines 206–324)
- **SRS.md** §5 — Acceptance Criteria Summary, 10 SPEC §8 items (lines 327–342)
- **SRS.md** §2.6 — high-risk modules `executor` / `store` + `no_circular_dependencies` (lines 60–62)
- **SRS.md** Appendix A — 8-module layout (lines 414–427)
- **SPEC_TRACKING.md** §2 — FR/NFR register + primary modules (lines 95–118)
- **SPEC_TRACKING.md** §3 — 69-AC per-AC status map (lines 122–223)
- **SPEC_TRACKING.md** §4 — FR⇄NFR coupling edges (lines 227–247)
- **SPEC_TRACKING.md** §5 — 0 open gaps at Phase 1 lock (lines 251–257)
- **SPEC.md** v4.0.0 — canonical single source of truth (per SRS.md header line 3)
