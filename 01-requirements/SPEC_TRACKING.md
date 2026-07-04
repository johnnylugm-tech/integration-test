# Specification Tracking Matrix — taskq

> Authoritative per-FR / per-NFR tracking register for the `taskq` project.
> Source of truth: `01-requirements/SRS.md` (already APPROVED, INGESTION MODE from
> `SPEC.md` v3.0.0 2026-07-04). This matrix owns: **status, owner, decision
> framework, and per-row traceability notes** for every requirement. The SRS owns
> the requirement definitions themselves — never edit canonical requirement text
> here; only annotate.

---

## Project Info

- Project Name: **taskq** (local task queue CLI, Python 3.11, stdlib-only at runtime)
- Spec Source of Truth: `SPEC.md` v3.0.0 (2026-07-04)
- SRS Reference: `01-requirements/SRS.md` (status: **APPROVED** — INGESTION MODE)
- Module Layout: `src/taskq/{__init__,__main__,config,models,store,executor,breaker,cache,cli}.py`
- High-risk modules (per `PROJECT_BRIEF.md`): `taskq.executor`, `taskq.store`
- Env Vars: 8 `TASKQ_*` parameters (centralized in `config.py`)
- Persistence: 3 JSON files in `$TASKQ_HOME/` — `tasks.json`, `breaker.json`, `cache.json`

---

## Tracking Conventions

| Column | Meaning |
|--------|---------|
| **FR / NFR ID** | Canonical identifier from `SPEC.md` §3 / §4 (transcribed verbatim into SRS §3 / §4). |
| **Spec Description** | Short label of what the requirement does (1-line summary; full text in SRS). |
| **Intent Class** | Functional category: `Functional` / `Performance` / `Security` / `Reliability` / `Maintainability` / `Deployability` / `Operational`. |
| **Decision Framework** | The verification strategy that gates acceptance: unit / integration / benchmark / grep-gate / lint / fault-injection. |
| **Status** | Lifecycle phase: `APPROVED` (SRS canonical), `DESIGNED` (P2 architecture), `IMPLEMENTED` (P3 done), `TESTED` (P4 done), `VERIFIED` (P5 done), `ACCEPTED` (Gate 1 closed). |
| **Owner** | Module path + downstream-phase agent (e.g. `store.py @ Agent-IMP`) responsible for delivering this row. |
| **Notes** | Open issues, deferred items, cross-links to AC IDs, risk IDs, hazard notes. |

**Status legend for Round 1**: every row starts as `APPROVED` (the SRS canonical
specification is approved; this matrix tracks downstream-phase progression of
each requirement).

---

## Functional Requirements (FRs)

| FR ID | Spec Description | Intent Class | Decision Framework | Status | Owner | Notes |
|-------|------------------|--------------|--------------------|--------|-------|-------|
| FR-01 | 任務提交與驗證 (`taskq submit "<cmd>"` with empty / length / injection / name-unique validation; uuid4-first-8 task id; atomic write to `$TASKQ_HOME/tasks.json`; exit 2 on validation failure) | Functional | Unit tests (validation rules) + CLI invocation matrix + grep-gate for injection blacklist | APPROVED | `src/taskq/store.py` + `src/taskq/cli.py` + `src/taskq/models.py` @ Agent-IMP (P3) | High-risk module `taskq.store`. ACs: AC-FR-01-01..05. Exit code 2 on validation fail. Risk R1 (concurrent write corruption). |
| FR-02 | 任務執行器 (`taskq run <id>` / `run --all` via `subprocess.run(shlex.split, …, timeout=TASKQ_TASK_TIMEOUT)`; status machine `pending → running → done / failed / timeout`; tail-2000 stdout/stderr; `ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS)`; single-task timeout → exit 4) | Functional | Unit tests (status machine) + concurrent fixture for `--all` + thread-safety test (shared Lock) | APPROVED | `src/taskq/executor.py` + `src/taskq/store.py` @ Agent-IMP (P3) | High-risk module `taskq.executor`. `shell=True` forbidden everywhere (NFR-02). ACs: AC-FR-02-01..05. Risk R2 (subprocess hang / zombie). |
| FR-03 | 重試與斷路器 (exponential backoff `TASKQ_BACKOFF_BASE × 2^n`, cap `TASKQ_RETRY_LIMIT`, injected sleep for tests; circuit breaker CLOSED/OPEN/HALF_OPEN; threshold `TASKQ_BREAKER_THRESHOLD`; cooldown `TASKQ_BREAKER_COOLDOWN`; persisted to `$TASKQ_HOME/breaker.json`; OPEN → exit 3 + stderr `breaker open`, no subprocess) | Functional + Reliability | Unit tests with injected sleep + fault-injection (consecutive failure threshold) + breaker-recovery timing test | APPROVED | `src/taskq/executor.py` + `src/taskq/breaker.py` @ Agent-IMP (P3) | ACs: AC-FR-03-01..05. Sleep function MUST be injectable (testability). Risk R3 (false breaker lock). Open issue: NFR-99-b (HALF_OPEN probe observation moment). |
| FR-04 | 結果 TTL 快取 (signature = `sha256(command)`; `run <id> --cached` replays `done` result within `TASKQ_CACHE_TTL` seconds — no subprocess; expired/missing → normal execution + cache write; atomic + thread-safe read/write) | Functional + Performance | Unit tests (cache hit / miss / expiry) + verify no subprocess spawn on cached replay | APPROVED | `src/taskq/cache.py` @ Agent-IMP (P3) | ACs: AC-FR-04-01..04. Cache writes require atomic + lock (coexists with FR-02 concurrency). Risk R4 (stale replay). |
| FR-05 | CLI 整合 (argparse subcommands `submit` / `run` / `status` / `list` / `clear`; global `--json` flag; 5 exit codes `0 / 1 / 2 / 3 / 4`) | Functional + Operational | CLI invocation matrix (each subcommand × each flag × each exit code) + `--json` round-trip | APPROVED | `src/taskq/cli.py` + `src/taskq/__main__.py` @ Agent-IMP (P3) | ACs: AC-FR-05-01..03. Exit codes: 0 success / 2 validation+unknown-id / 3 breaker open / 4 timeout / 1 other internal. |

---

## Non-Functional Requirements (NFRs)

| NFR ID | Spec Description | Intent Class | Decision Framework | Status | Owner | Notes |
|--------|------------------|--------------|--------------------|--------|-------|-------|
| NFR-01 | Performance: `submit` + `status` combined (no subprocess) p95 < 50ms over 100 iterations (pytest-benchmark) | Performance | pytest-benchmark suite (`tests/bench/test_bench_submit_status.py`); 100 iterations; report p95 | APPROVED | Agent-PERF (P4 testing) gated on Agent-IMP (P3) | AC: AC-NFR-01-01. Open issue: NFR-99-a (50ms budget boundary — with/without subprocess invocation overhead; canonical phrasing ambiguous). |
| NFR-02 | Security (shell + injection): `shell=True` forbidden codebase-wide; FR-01 injection character blacklist (`; \| & $ > < \``) must have test coverage | Security | CI grep-gate (`grep -rn 'shell=True' src/ tests/` must return zero hits in production paths) + unit tests on blacklist characters | APPROVED | Agent-IMP (P3) + Agent-SEC (P5 verification) | Cross-cuts FR-01 / FR-02 / FR-05. ACs: AC-NFR-02-01..02. Verified by repository-wide grep at Gate 1. |
| NFR-03 | Reliability (atomic write + breaker recovery): all 3 data files written atomically (tmp + `os.replace`); breaker `OPEN → CLOSED` recovery ≤ `TASKQ_BREAKER_COOLDOWN` + 1s | Reliability | Fault-injection crash test (kill -9 mid-write, validate JSON parse on restart) + breaker recovery timing test | APPROVED | Agent-IMP (P3) + Agent-REL (P5 verification) | Cross-cuts FR-01..04. ACs: AC-NFR-03-01..02. Open issue: NFR-99-b (observation moment for OPEN→CLOSED). |
| NFR-04 | Security (secret redaction): `stdout_tail` / `stderr_tail` lines matching `(sk-[A-Za-z0-9_-]{8,}\|token=\S+)` replaced whole-line with `[REDACTED]` before persistence | Security | Unit tests on stdout/stderr redaction (positive + negative cases for both regex branches) | APPROVED | Agent-IMP (P3) + Agent-SEC (P5 verification) | AC: AC-NFR-04-01. Redaction happens before persistence, not just before display. Risk R5 (secret leak to disk). |
| NFR-05 | Maintainability (docstring FR-cross-ref): every public function/class in `src/taskq/` has docstring containing `[FR-XX]` reference | Maintainability | Gate 1 inspect (AST scan of `src/taskq/`; assert every public symbol has docstring + matches `/\[FR-\d{2}\]/`) | APPROVED | Agent-IMP (P3) — runtime check at Gate 1 | AC: AC-NFR-05-01. Coverage target: 100% of public symbols. |
| NFR-06 | Deployability (env vars): all 8 `TASKQ_*` parameters read from env (centralized in `config.py`, with defaults); `.env.example` declares all 8 with annotations | Deployability | Env-var loading test (set/unset each var, assert default fallback) + `.env.example` lint (8 lines, each var annotated) | APPROVED | Agent-IMP (P3) + Agent-CFG (P8 config) | AC: AC-NFR-06-01. 8 vars: TASKQ_HOME / MAX_WORKERS / TASK_TIMEOUT / RETRY_LIMIT / BACKOFF_BASE / BREAKER_THRESHOLD / BREAKER_COOLDOWN / CACHE_TTL. |

---

## Cross-Cutting Tracking

### Acceptance Items (from SRS §5)

| # | Acceptance Item | FR/NFR Anchor | Tracking Row |
|---|----------------|---------------|--------------|
| 1 | `pytest tests/ -q` all green | cross-cutting | Verified at Gate 1 closure (post-P5). |
| 2 | `python -m taskq submit "echo hi"` → 8-hex id; `run <id>` → `done`; `status <id>` → `exit_code: 0` | FR-01 / FR-02 / FR-05 | FR-01, FR-02, FR-05 |
| 3 | `python -m taskq submit ""` → exit 2 | FR-01 / NFR-02 | FR-01, NFR-02 |
| 4 | `python -m taskq submit "echo hi; rm x"` → exit 2 (injection char) | FR-01 / NFR-02 | FR-01, NFR-02 |
| 5 | `TASKQ_TASK_TIMEOUT=1` + `sleep 5` task → status `timeout`, exit 4 | FR-02 / FR-05 | FR-02, FR-05 |
| 6 | 3 consecutive final failures → 4th `run` → exit 3 (breaker OPEN); cooldown restores | FR-03 / NFR-03 | FR-03, NFR-03 |
| 7 | TTL window `run <id> --cached` (same signature) → replay + `cached: true`, no subprocess | FR-04 | FR-04 |
| 8 | `.env.example` declares all 8 `TASKQ_*` vars | NFR-06 | NFR-06 |
| 9 | `run --all` concurrent → `tasks.json` valid JSON, zero task loss | FR-02 / NFR-03 | FR-02, NFR-03 |
| 10 | Public function docstrings contain `[FR-XX]` references | NFR-05 | NFR-05 |

### Open Issues (from SRS §7)

| ID | Type | Anchor | Tracking Implication |
|----|------|--------|----------------------|
| NFR-99-a | ambiguity | AC-NFR-01-02 | Resolve before P5 verification: confirm with stakeholder whether NFR-01's 50ms budget includes subprocess invocation overhead. Owner: Agent-PERF. |
| NFR-99-b | ambiguity | AC-NFR-03-03 | Resolve before P5 verification: confirm measurement point for breaker `OPEN → CLOSED` recovery (HALF_OPEN probe vs explicit reset). Owner: Agent-REL. |

### Risk Map (from SRS §8)

| Risk | Linked FR/NFR | Tracking Row |
|------|---------------|--------------|
| R1 — concurrent write corrupts `tasks.json` | FR-01/02 + NFR-03 | FR-01, FR-02, NFR-03 |
| R2 — subprocess hang / zombie | FR-02 | FR-02 |
| R3 — false breaker lock | FR-03 | FR-03 |
| R4 — stale cache replay | FR-04 | FR-04 |
| R5 — secret leak to disk | NFR-04 | NFR-04 |

---

## Completeness Validation (Round 1 self-check)

| Check | Result |
|-------|--------|
| All 5 FRs (`FR-01..FR-05`) present in matrix? | YES (5 / 5 rows) |
| All 6 NFRs (`NFR-01..NFR-06`) present in matrix? | YES (6 / 6 rows) |
| Every FR has an owner module assignment? | YES |
| Every FR/NFR has a Decision Framework entry? | YES |
| Every FR/NFR has a Status entry (all `APPROVED` for Round 1)? | YES |
| Cross-cutting Acceptance Items (10 / 10) mapped to tracking rows? | YES (see table above) |
| Open Issues (2 / 2: NFR-99-a, NFR-99-b) carry forward? | YES (NFR-99-b unresolved at FR-03 row; NFR-99-a unresolved at NFR-01 row) |
| Risk Map (5 / 5) cross-referenced? | YES (R1..R5 mapped) |
| High-risk modules (`executor`, `store`) flagged in owner notes? | YES (FR-01, FR-02 explicit) |
| H1 anchor matches `Specification Tracking Matrix — <project-name>`? | YES (this line: `# Specification Tracking Matrix — taskq`) |

---

## Downstream-Phase Status (Round 1 snapshot)

> Populated by Phase 2-8 agents as each row progresses. Round 1 leaves all
> rows at `APPROVED` until downstream owners update.

| Phase | Trigger | Update pattern |
|-------|---------|----------------|
| P2 (Architecture) | Architecture plan ratified | Promote row → `DESIGNED` (module-level design landed). |
| P3 (Implementation) | `pytest tests/ -q` green for the row's module | Promote row → `IMPLEMENTED`. |
| P4 (Testing) | All ACs in the row have passing tests | Promote row → `TESTED`. |
| P5 (Verification) | Decision Framework gate green (benchmark / grep / fault-injection / etc.) | Promote row → `VERIFIED`. |
| P6 / Gate 1 | Per-FR TDD + implementation quality closed | Promote row → `ACCEPTED`. |

**Round 1 conclusion**: every row currently `APPROVED`. No row has been
`DESIGNED` / `IMPLEMENTED` / `TESTED` / `VERIFIED` / `ACCEPTED` yet — those
promotions are the explicit hand-off to downstream phase agents.

---

*Matrix version: 1.0 (Round 1, 2026-07-04). Owner: Requirements Engineer (Agent A). Source of truth: `01-requirements/SRS.md` (APPROVED). Re-rendered by Phase 2-8 agents as rows progress.*