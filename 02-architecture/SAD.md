# Software Architecture Document (SAD) — `taskq`

> Project: `taskq` — local task-queue CLI
> SPEC version: v4.1.0 (5 FR / 10 NFR / 8 env, 2026-07-12)
> Phase: 2 — Architecture
> Scope: Authoritative architectural description; directory layout decided here per SPEC v4.1.0 (v4.1.0 removed the §6 folder constraint and delegated layout authority to Phase 2 SAD.md).
> Companion artifacts: `SPEC.md` (single source of truth), `SRS.md` (requirements narrative).

---

## 1. Overview

`taskq` is a Python 3.11 CLI (`python -m taskq`) that submits shell commands as managed tasks and runs them under controlled execution (timeout, retry, breaker, TTL cache). State is queryable and persisted across processes. The runtime is intentionally dependency-free (standard library only).

This document satisfies Phase 2 architecture for the 5 FR / 10 NFR set. SPEC v4.1.0 (2026-07-12) removed the §6 folder-structure constraint and delegated directory-layout authority to Phase 2 SAD.md (SPEC §0 changelog line 14); this SAD therefore owns the layout decision. To satisfy harness CRG Principle 1 (3–6 source directories) and the cohesion budget, the 9 modules are split into **4 sub-packages** under `src/taskq/` (`core`, `storage`, `runtime`, `interface`), each becoming one CRG community with an explicit hub module. The dependency graph remains a DAG rooted at `interface/cli` and is trivially acyclic.

**Architectural constraints (from harness-methodology v2.9):**
- `no_circular_dependencies` — module graph is a DAG rooted at `taskq.interface.cli`.
- High-risk modules: `taskq.runtime.executor` (subprocess + retry), `taskq.storage.store` (atomic write + concurrency).
- Public functions/classes carry docstrings with `[FR-XX]` citation (NFR-05).
- All data-file writes are atomic (tmp + `os.replace`) with shared `threading.Lock` and best-effort cross-process `fcntl.flock`.

**Document roadmap:**
| § | Topic |
|---|-------|
| 2 | Module design (4 sub-packages; FR → module mapping) |
| 3 | Interfaces and data flows |
| 4 | NFR handling (10 NFRs grouped by category) |
| 5 | SAB block (machine-readable contract) |

---

## 2. Module Design

### 2.1 Module tree (Phase 2 decision; satisfies CRG Principle 1)

**Decision (post-v4.1.0 rationale):** SPEC.md v4.1.0 (2026-07-12) removed §6 and delegated directory-layout authority to this SAD (SPEC §0 changelog line 14). The 9 modules are split into **4 sub-packages** under `src/taskq/` to satisfy harness CRG Principle 1 (3–6 source directories) — this places the boundary at the natural layering (`core` / `storage` / `runtime` / `interface`) rather than forcing a flat layout that would violate Principle 1 and produce an oversized single CRG community. Each sub-package becomes one CRG community with an explicit hub module (Principle 2). Flat-layout alternative was considered and rejected — a single 9-file `src/taskq/` community is plausibly 60–90 nodes (functions/classes), which exceeds the 50-node size cap (Principle 6) in addition to the Principle 1 violation, so the flat choice is unsupportable under v4.1.0.

```
integration-test/
├── src/taskq/
│   ├── __init__.py             # package marker; version string
│   ├── core/                   # foundational types + config (CRG community A)
│   │   ├── __init__.py
│   │   ├── config.py           # TASKQ_* env loader              (NFR-06)  [hub]
│   │   └── models.py           # Task / RunResult dataclasses     (FR-01..04) [hub]
│   ├── storage/                # data-file persistence (CRG community B)
│   │   ├── __init__.py
│   │   ├── store.py            # tasks.json atomic store + Lock   (FR-01/02, NFR-03/08/09/10) [hub]
│   │   ├── breaker.py          # circuit breaker state machine    (FR-03, NFR-03/08/10)
│   │   └── cache.py            # TTL result cache                 (FR-04, NFR-03/08/09/10)
│   ├── runtime/                # execution layer (CRG community C)
│   │   ├── __init__.py
│   │   └── executor.py         # subprocess + retry               (FR-02/03, NFR-02/04/07)
│   └── interface/              # CLI entry (CRG community D)
│       ├── __init__.py
│       ├── cli.py              # argparse subcommands             (FR-05) [hub]
│       └── __main__.py         # python -m taskq entry point → cli.main
├── tests/
├── .env.example
├── SPEC.md
└── harness-e2e.js
```

**File-count budget:** 4 sub-packages, 9 source files total — well under the 15-files-per-directory cap. No file combines responsibilities from two FRs.

**Cohesion strategy (per CRG Principles 2 & 4):**
- `core/models.py` is the type-hub: every sibling in `storage`, `runtime`, `interface` constructs/consumes `Task` / `RunResult` / `TaskStatus` / `BreakerState` from `core.models`.
- `core/config.py` is the config-hub: every sibling calls `get_config()` (not scattered `os.environ.get`) to read the 8 `TASKQ_*` vars.
- `storage/store.py` is the storage-hub: `cli.status` / `cli.list` route through `store.get()` / `store.list()`; `executor` writes back via `store.update_status()`.
- `interface/cli.py` is the dispatch-hub: routes every user-facing command to one of `runtime.executor`, `storage.breaker`, `storage.cache`, `storage.store`.

**Edge-budget analysis (template formula `I/(I+E) ≥ 0.3`, i.e. `I ≥ ceil(0.4286×E)`):** E (external edges) per community = stdlib/library import call-sites + cross-community calls. With the split, E is reduced per community (each community imports a smaller stdlib subset) and I is increased (each community's hub is called by every sibling function body, per Principle 4 binding implementation constraint). Cohesion is measured empirically by the CRG at Gate 2/3. If a community falls short of 0.3, the only remediation is increasing hub-call density per Principle 4 (sub-package split is already done).

### 2.2 Module responsibilities and FR coverage

| Module | Public surface | Implements FR(s) | Implements NFR(s) | Size budget |
|--------|----------------|------------------|-------------------|-------------|
| `taskq/__init__.py` | `__version__` | — | NFR-05 | <10 LoC |
| `taskq/core/config.py` | `get_config()` returning typed `Config` dataclass | — | NFR-06 | ~60 LoC |
| `taskq/core/models.py` | `Task`, `RunResult`, `TaskStatus`, `BreakerState` | FR-01 status enum, FR-02 result shape, FR-03 breaker state, FR-04 cache entry | NFR-05 docstring citation | ~80 LoC |
| `taskq/storage/store.py` | `Store.submit()`, `Store.get()`, `Store.list()`, `Store.update_status()`, atomic write + Lock + flock | FR-01 (write), FR-02 (read/update), FR-05 (list) | NFR-03 (atomic), NFR-08 (flock), NFR-09 (streaming iter), NFR-10 (version migration) | ~200 LoC |
| `taskq/runtime/executor.py` | `execute(task, *, sleep=time.sleep)`, redaction filter, retry/backoff, breaker consult | FR-02 (subprocess), FR-03 (retry) | NFR-02 (no `shell=True`), NFR-04 (redaction), NFR-07 (fault injection hooks via `--inject-fault` + monkeypatch) | ~180 LoC |
| `taskq/storage/breaker.py` | `Breaker.allow()`, `Breaker.record()`, state machine `CLOSED/OPEN/HALF_OPEN` | FR-03 (state) | NFR-03 (atomic state persistence), NFR-08 (flock on `breaker.json`), NFR-10 (version) | ~120 LoC |
| `taskq/storage/cache.py` | `Cache.lookup(signature)`, `Cache.put(signature, result)`, TTL eviction | FR-04 | NFR-03, NFR-08, NFR-10 | ~100 LoC |
| `taskq/interface/cli.py` | `submit / run / status / list / clear` argparse subcommands; `--json`; `--cached`; `--inject-fault`; exit code mapping | FR-05 | NFR-02 (CLI rejection of injection chars), NFR-07 (fault flag plumbing) | ~220 LoC |
| `taskq/interface/__main__.py` | `python -m taskq` boot → `cli.main` | FR-05 (entry) | — | <10 LoC |

**`Config.env` field (source of truth for the `--inject-fault` production-lockout gate, §3.5/§4.3, mitigating Risk R6):** `get_config()` returns a `Config` dataclass with a computed `env: Literal["test", "prod"]` field. It is **not** one of the 8 declared `TASKQ_*` environment variables (NFR-06's 8-var inventory in §2.5/§4.7 is unaffected) and is deliberately excluded from `.env.example` — it must not be user-overridable, or the lockout it enforces would be defeatable by setting an env var. `get_config()` derives it internally as `"test" if "PYTEST_CURRENT_TEST" in os.environ else "prod"`; production process invocations never carry that variable (pytest sets it automatically for the duration of each test), so `--inject-fault` is refused unconditionally outside of a pytest test run.

### 2.3 Dependency graph (single DAG, no cycles)

**Diagram scope:** the ASCII graph below draws only the `cli`-rooted dispatch layer and the shared-foundation layer (`models`/`config`); it is intentionally simplified to avoid crossing lines. The peer fan-out edges (`executor → breaker/cache/store`) are not drawn — see the bulleted edge list immediately below, which is authoritative for the full graph.

```
                       ┌───────────────┐
                       │ interface.cli │  (root — argparse + dispatch)
                       └───┬─────┬─────┘
            ┌──────────────┤     ├──────────────┐
            ▼              ▼     ▼              ▼
    ┌───────────────┐  ┌──────────┐  ┌──────────────────┐
    │ runtime.      │  │ storage. │  │ storage.         │
    │   executor    │  │  store   │  │   breaker / cache│
    └───────┬───────┘  └────┬─────┘  └────────┬─────────┘
            │               │                 │
            └───────┬───────┴─────────────────┘
                    ▼
            ┌─────────────┐   ┌─────────────┐
            │ core.models │   │ core.config │
            └─────────────┘   └─────────────┘
```

**Edges (authoritative, unidirectional, no cycles — 15 total, all intra-`src/taskq/`):**
- `interface.cli → runtime.executor`, `interface.cli → storage.breaker`, `interface.cli → storage.cache`, `interface.cli → storage.store`
- `runtime.executor → storage.breaker` (consult `Breaker.allow()` before running), `runtime.executor → storage.store` (write result via `store.update_status()`), `runtime.executor → core.models`, `runtime.executor → core.config`
- `runtime.executor → storage.cache` **conditionally**: only when executor actually runs AND result status is `done` (cache-hit path bypasses executor entirely per §3.3). When triggered: `cache.put(signature=sha256(command), result)` writes the result into `cache.json` after the atomic write to `tasks.json`.
- `storage.breaker → core.models`, `storage.breaker → core.config`
- `storage.cache → core.models`, `storage.cache → core.config` (no `cache → store` edge — `interface.cli` orchestrates `store.get()` and `cache.lookup()` independently per §3.3; `cache` never calls `store`)
- `storage.store → core.models`, `storage.store → core.config`
- `interface.__main__ → interface.cli`

No module imports from `interface.cli` (cli is the consumer, not the producer). No module re-exports `cli`. **No cycles.**

### 2.4 Per-FR module mapping (every FR → ≥1 module)

| FR | Primary module(s) | Supporting modules | Notes |
|----|-------------------|--------------------|-------|
| **FR-01** Submit + validate | `store.submit()` | `cli` (entry + validation), `models.Task` | Inject-char blacklist enforced in `cli` before `store` is called; atomic write in `store` |
| **FR-02** Execute | `executor.execute()` | `store.update_status()`, `breaker.allow()` | `subprocess.run(shlex.split(cmd), …, shell=False)` — never `shell=True` |
| **FR-03** Retry + breaker | `executor` (retry/backoff), `breaker` (state machine + `breaker.json` persistence) | `store` (task status update on retry outcome) | Backoff `time.sleep` injected via kwarg for deterministic test |
| **FR-04** TTL cache | `cache` | `cli` (reads via `store.get()`/`cache.lookup()` on `--cached` — see §3.3), `executor` (writes via `cache.put()` on completion, invoked only when executor actually runs AND result status is `done`; cache-hit path bypasses executor entirely — see §3.3) | Signature = `sha256(command)` |
| **FR-05** CLI integration | `cli` | All other modules | Exit codes: 0/1/2/3/4 mapped at the `cli` boundary |

### 2.5 Per-NFR module mapping (10 NFRs, every NFR → ≥1 module)

| NFR | Owner module(s) | Mechanism |
|-----|------------------|-----------|
| NFR-01 performance | `store`, `cli` | Targeted `pytest-benchmark`; p95 <50ms over 100 iters on `submit`+`status` |
| NFR-02 security | `cli` (injection blacklist), `executor` (no `shell=True`) | Pre-acceptance blacklist; lint test `grep -r 'shell=True' src/` returns 0 |
| NFR-03 reliability | `store`, `breaker`, `cache` | All three data files: tmp+`os.replace`; on-load corruption → exit 1 (no silent rebuild) |
| NFR-04 security | `executor` | Redaction regex `(sk-[A-Za-z0-9_-]{8,}\|token=\S+)` applied to `stdout_tail`/`stderr_tail` before write |
| NFR-05 maintainability | All public surface | Docstring convention `[FR-XX]` enforced by Gate 1 lint. **Note:** the SAB `nfr_traceability` module field is a singular string (flat-field limitation of the SAB schema) and therefore points to `taskq.core.models` as the canonical hub module rather than enumerating the full surface. The "All public surface" scope above is the authoritative target; the SAB entry is a representative designator, not a scope reduction. |
| NFR-06 deployability | `config` | Single `get_config()` reads all 8 `TASKQ_*` vars; `.env.example` mirrors |
| NFR-07 resilience | `store`, `breaker`, `cache` | `--inject-fault=<scenario>` CLI flag + monkeypatch hooks; production paths reject the flag |
| NFR-08 concurrency | `store`, `breaker`, `cache` | `fcntl.flock` exclusive-write / shared-read; warning + atomic-only on NFS/network FS |
| NFR-09 scalability | `store`, `cache` | Streaming iter (no full-task load); p95 <100ms @ 1000 tasks; 100-task `run --all` correctness |
| NFR-10 evolvability | `store`, `breaker`, `cache` | `version` field; auto-upgrade v0→v1; reject `version>1`; backup `.v<n>.bak` before mutate |

---

## 3. Interfaces and Data Flows

### 3.1 Public interfaces (one-line contracts)

```python
# taskq.core.config
def get_config() -> Config: ...                       # [NFR-06]

# taskq.core.models
@dataclass class Task: ...                            # [FR-01]
@dataclass class RunResult: ...                       # [FR-02]
enum TaskStatus: pending|running|done|failed|timeout  # [FR-01..02]
enum BreakerState: CLOSED|OPEN|HALF_OPEN             # [FR-03]

# taskq.storage.store
class Store:
    def submit(self, command: str, name: str | None) -> Task: ...     # [FR-01]
    def get(self, task_id: str) -> Task: ...                          # [FR-05 status]
    def list(self, status: TaskStatus | None = None) -> Iterator[Task]: ...  # [FR-05 list]
    def update_status(self, task_id: str, **fields) -> None: ...     # [FR-02]

# taskq.runtime.executor
def execute(task: Task, *, sleep: Callable[[float], None] = time.sleep) -> RunResult: ...  # [FR-02/03]

# taskq.storage.breaker
class Breaker:
    def allow(self) -> bool: ...                     # [FR-03]
    def record(self, success: bool) -> None: ...     # [FR-03]

# taskq.storage.cache
class Cache:
    def lookup(self, signature: str) -> RunResult | None: ...  # [FR-04]
    def put(self, signature: str, result: RunResult) -> None: ...  # [FR-04]

# taskq.interface.cli
def main(argv: list[str] | None = None) -> int: ...  # [FR-05]
```

### 3.2 Data flow: `submit` then `run` (happy path)

```
$ python -m taskq submit "echo hi"
        │
        ▼
   ┌─────────┐  validate (FR-01)   ┌──────────────┐
   │   cli   │────────────────────►│     store    │
   └─────────┘  id = uuid4[:8]     │  submit()    │
        ▲       write tasks.json   │  atomic write│
        │                          └──────┬───────┘
   stdout: id                            │
                                         │
$ python -m taskq run <id>               │
        ▼                                │
   ┌─────────┐  allow?       ┌────────────────┐
   │   cli   │──────────────►│    breaker     │
   └─────────┘               │  state machine │
        │                    └────────────────┘
        ▼
   ┌─────────────────────────┐
   │      executor           │
   │ shlex.split + run(...)  │   ─► subprocess("echo hi")
   │ redact stdout/stderr    │       exit_code, tails, duration
   │ apply retry/backoff*    │
   └────┬──────────┬─────────┘
        │          │
   write│          │write
        ▼          ▼
   ┌─────────┐  ┌──────┐
   │  store  │  │cache │  (on done, signature=sha256(cmd))
   └─────────┘  └──────┘
```

`*` retry only applies when execution outcome is `failed` or `timeout` and retry budget (`TASKQ_RETRY_LIMIT`) remains.

### 3.3 Data flow: cache replay (`run <id> --cached`)

```
cli run --cached
  ├─ store.get(id)              # fetch task
  ├─ cache.lookup(sha256(cmd))  # present + same status + within TTL ?
  │     └─ yes → store.update_status(done, cached=True); return cached RunResult
  └─ no  → executor.execute(...)  (normal path)
```

### 3.4 Data flow: cross-process flock

```
process A                    process B
  store._acquire_exclusive()     store._acquire_shared()
  write tmp                       (blocks)
  os.replace                       (wakes)
  flock release                   flock release
```

On NFS / network FS: warning logged; flock skipped, atomic write remains. NFR-08 best-effort posture is preserved.

### 3.5 Data flow: fault injection (`--inject-fault=…`)

```
cli submit/run
  └─ executor._fault_hook(scenario)
        ├─ corrupt-mid-write  → atomic write aborts, .bak preserved (NFR-07)
        ├─ oserror-on-write   → OSError raised, stderr message + exit 1
        ├─ disk-full          → ENOSPC → stderr + exit 1
        └─ kill-mid-write     → kill -9 in subprocess; store detects on next start
```

The flag is refused in production paths (i.e. when `get_config().env != "test"` it is rejected with `exit 2`).

### 3.6 Persistent file shape (all v1, per NFR-10)

```jsonc
// $TASKQ_HOME/tasks.json
{ "version": 1, "tasks": { "<id>": { /* Task fields */ } } }

// $TASKQ_HOME/breaker.json
{ "version": 1, "state": "CLOSED|OPEN|HALF_OPEN",
  "failure_count": 0, "opened_at": null }

// $TASKQ_HOME/cache.json
{ "version": 1, "entries": { "<sha256>": { /* RunResult + cached_at */ } } }
```

### 3.7 Exit-code matrix (single source: `cli`)

| Outcome | Exit | Where decided |
|---------|------|---------------|
| Success | 0 | `cli` |
| Internal / unexpected | 1 | `cli` |
| Validation / unknown task | 2 | `cli` |
| Breaker open | 3 | `cli` (after `breaker.allow()` returns False) |
| Task timeout (single-task mode) | 4 | `executor` → `cli` |

---

## 4. NFR Handling

The 10 NFRs are grouped by SPEC §4 category. Each NFR names its enforcement site(s) and the failure surface it closes.

**SAB `nfr_traceability.type` mapping (decided now, not deferred to SAB generation):** the 8 SPEC §4 category labels used as this section's headings (performance, security, reliability, concurrency, scalability, evolvability, maintainability, deployability) do not map 1:1 onto the harness's 8 legal `sab_parser.py` enum values (`performance`, `security`, `maintainability`, `reliability`, `testability`, `deployability`, `scalability`, `usability`). `concurrency` and `evolvability` have no same-named enum value; `testability` and `usability` are unused because none of the 10 NFRs concern them. The per-NFR `type` value to use when the SAB body is generated:

| NFR | SAD §4 category | SAB `type` |
|-----|------------------|------------|
| NFR-01 | performance | `performance` |
| NFR-02 | security | `security` |
| NFR-03 | reliability | `reliability` |
| NFR-04 | security | `security` |
| NFR-05 | maintainability | `maintainability` |
| NFR-06 | deployability | `deployability` |
| NFR-07 | resilience | `reliability` |
| NFR-08 | concurrency | `reliability` (data-integrity guarantee under concurrent access; closest legal value) |
| NFR-09 | scalability | `scalability` |
| NFR-10 | evolvability | `maintainability` (schema/version-migration upkeep; closest legal value) |

### 4.1 Performance (NFR-01, NFR-09)

- **NFR-01** (`submit` + `status` 100-iter p95 < 50 ms)
  - **Where:** `cli` → `store.submit/get`. No subprocess.
  - **Budget:** lockless hot read path for `get`; tiny JSON file.
  - **Verify:** `pytest-benchmark` group `perf_basic`; assertion `p95 < 0.050 s`.

- **NFR-09** (1000-task scale; `run --all` 100 tasks, no loss, peak memory < 100 MB)
  - **Where:** `store.list()` streaming iterator; `cache` lazy decode.
  - **Verify:** `pytest-benchmark` group `perf_scaled` (1000 iter < 100 ms p95); integration test on 100-task `run --all` (legal JSON + all-IDs-present).

### 4.2 Security (NFR-02, NFR-04)

- **NFR-02** (no `shell=True`; injection-blacklist tested)
  - **Where:** `cli._validate_command()` rejects `; | & $ > < \`` ` characters. `executor` uses `shlex.split(cmd)` + `subprocess.run([...], shell=False)`.
  - **Verify:** static gate `grep -R "shell=True" src/` returns 0 hits; parametrized tests for each blocked char.

- **NFR-04** (secret redaction before persisting tails)
  - **Where:** `executor._redact(text)` applies regex `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` line-by-line, replacing matching lines with `[REDACTED]`.
  - **Verify:** unit table on `stdout_tail`/`stderr_tail` samples including `sk-abcdefgh1234` and `token=xyz`.

### 4.3 Reliability (NFR-03, NFR-07)

- **NFR-03** (atomic writes; breaker recovery)
  - **Where:** `store`, `breaker`, `cache` all use `_atomic_write(path, payload)` helper: write tmp → `os.replace`. On load, `json.JSONDecodeError` → `exit 1` (`store corrupted`); no silent rebuild. Breaker recovery ≤ `TASKQ_BREAKER_COOLDOWN + 1s`.
  - **Verify:** fault-injection tests for each of three files.

- **NFR-07** (fault injection scenarios)
  - **Where:** `executor._fault_hook` + `cli --inject-fault=…`. `--inject-fault` rejected when `cfg.env != "test"`.
  - **Scenarios:** `corrupt-mid-write`, `oserror-on-write`, `disk-full`, `kill-mid-write`.
  - **Verify:** per-scenario test asserts recovery-or-failfast, never silent data loss.

### 4.4 Concurrency (NFR-08)

- **Where:** `store`, `breaker`, `cache` wrap reads/writes with `fcntl.flock` (POSIX) / `msvcrt.locking` (Windows).
- **Detect NFS / network FS:** `_is_network_fs()` probe; if True → log WARNING, skip `flock`, keep atomic write.
- **Verify:** multi-process subprocess test (4 × `python -m taskq …` in parallel); all three files load as legal JSON afterward.

### 4.5 Scalability (NFR-09, also covered above)

- Streaming iter; no full load; peak memory < 100 MB on 1000-task workload.

### 4.6 Evolvability (NFR-10)

- **Where:** `_load_or_migrate(path)` reads `version`; if `<1`, write v1 + back-up `<path>.v<n>.bak`; if `>1`, refuse with `exit 1` and an upgrade hint.
- **Verify:** fixture-based tests for `version: 0` (auto-upgrade), `version: 2` (refuse), backup retention on migrate failure.

### 4.7 Maintainability (NFR-05), Deployability (NFR-06)

- **NFR-05:** every public function/class docstring starts with `[FR-XX]` or `[NFR-YY]` reference; lint enforced in Gate 1.
- **NFR-06:** `config.get_config()` reads the 8 `TASKQ_*` vars with defaults from SPEC §5.1; `.env.example` is updated in lockstep (CI lint asserts parity).

### 4.8 Risk traceability (SPEC §9 → module mitigations)

| Risk | Mitigating NFR(s) | Module(s) |
|------|-------------------|-----------|
| R1 concurrent write corruption | NFR-03, NFR-08 | `store`, `breaker`, `cache` |
| R2 subprocess hang / zombie | FR-02 timeout | `executor` |
| R3 breaker false-positive lockout | cooldown + HALF_OPEN | `breaker` |
| R4 stale cache replay | TTL eviction | `cache` |
| R5 secret leakage | redaction | `executor` |
| R6 fault-injection prod leak | `--inject-fault` prod rejection | `cli` |
| R7 NFS flock failure | network-FS detection | `store`, `breaker`, `cache` |
| R8 1000-task memory blow-up | streaming iter | `store` |
| R9 schema migration data loss | backup + fail-fast | `store`, `breaker`, `cache` |

---

## 5. SAB Block (machine-readable — BINDING CONTRACT)

The literal `SAB:START` / `SAB:END` markers below anchor the parser (see `harness/core/quality_gate/sab_parser.py` `_SAB_BLOCK_RE`). Field names, types, and the `phase: 2` (int, NOT string) invariant are authoritative against `render_canonical_sab_template()`. NFR `type` values are restricted to the 8 legal enum values; mapping per-NFR from §4 prose to SAB enum is shown in the §4 table and materialized in the YAML body below.

<!-- SAB:START -->

```yaml
sab:
  version: "1.0"
  created_at: "2026-07-12"
  phase: 2  # MUST be int, NOT a string — parser raises on 'phase: "2"'
  project: "taskq"

  layers:  # 4 sub-packages — satisfy CRG Principle 1 (3-6 source dirs)
    - name: interface
      modules:
        - name: "taskq.cli"
          implemented_in: "taskq.interface.cli"
        - name: "taskq.main"
          implemented_in: "taskq.interface.__main__"
      allowed_dependencies: ["core", "storage", "runtime"]
    - name: runtime
      modules:
        - name: "taskq.executor"
          implemented_in: "taskq.runtime.executor"
      allowed_dependencies: ["core", "storage"]
    - name: storage
      modules:
        - name: "taskq.store"
          implemented_in: "taskq.storage.store"
        - name: "taskq.breaker"
          implemented_in: "taskq.storage.breaker"
        - name: "taskq.cache"
          implemented_in: "taskq.storage.cache"
      allowed_dependencies: ["core"]
    - name: core
      modules:
        - name: "taskq.config"
          implemented_in: "taskq.core.config"
        - name: "taskq.models"
          implemented_in: "taskq.core.models"
      allowed_dependencies: []

  allowed_dependencies:
    - from: interface
      to: core
    - from: interface
      to: storage
    - from: interface
      to: runtime
    - from: runtime
      to: core
    - from: runtime
      to: storage
    - from: storage
      to: core

  quality_targets:
    max_complexity: 15
    min_coverage: 80
    max_coupling: 0.3

  nfr_dimension_mapping: {}  # OPTIONAL — auto-derived from nfr_traceability.type

  nfr_traceability:
    NFR-01:
      type: performance
      target: "p95 < 50ms"
      module: taskq.storage.store
    NFR-02:
      type: security
      target: ">=100"
      module: taskq.interface.cli
    NFR-03:
      type: reliability
      target: ">=100"
      module: taskq.storage.store
    NFR-04:
      type: security
      target: ">=100"
      module: taskq.runtime.executor
    NFR-05:
      type: maintainability
      target: ">=100"
      module: taskq.core.models
    NFR-06:
      type: deployability
      target: ">=100"
      module: taskq.core.config
    NFR-07:
      type: reliability
      target: ">=100"
      module: taskq.storage.store
    NFR-08:
      type: reliability
      target: ">=100"
      module: taskq.storage.store
    NFR-09:
      type: scalability
      target: "p95 < 100ms @ 1000 tasks"
      module: taskq.storage.store
    NFR-10:
      type: maintainability
      target: ">=100"
      module: taskq.storage.store

  advisory_only: []  # AUTO-FILLED by parser — deployability / scalability land here

  gate_score_overrides: {}  # AUTO-DERIVED by parser

  fr_module_traceability:
    FR-01: "taskq.storage.store"
    FR-02: "taskq.runtime.executor"
    FR-03: "taskq.storage.breaker"
    FR-04: "taskq.storage.cache"
    FR-05: "taskq.interface.cli"

  architecture_constraints:
    - "no_circular_dependencies"
    - "no_shell_true"
    - "atomic_write_all_data_files"
    - "stream_iter_no_full_load"
    - "no_silent_rebuild_or_silent_swallow_errors"

  high_risk_modules:
    - "taskq.runtime.executor"
    - "taskq.storage.store"
```

<!-- SAB:END -->

---

## Appendix A — Out of scope for this document

- ADR (Architecture Decision Records) — separate `ADR.md` authored in a parallel sub-task.
- TEST_SPEC — separate `TEST_SPEC.md` authored in a parallel sub-task; test cases will cite `[FR-XX]` tags here for traceability.
- Bench harness details — owned by Phase 4–6; this document only commits the perf budgets.
- Phase-transition / gate / SAB-generation commands — out of scope; this document does not invoke them.

---

*Author: Architect Agent A (Round 2 — B-2 gap fixes applied) | Phase 2 | 2026-07-12*
*Refers: `SPEC.md` v4.1.0 (2026-07-12) §0–§10 | Verify against `01-requirements/SRS.md` (5 FR / 10 NFR)*
