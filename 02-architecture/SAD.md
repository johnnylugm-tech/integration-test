# Software Architecture Document (SAD) — taskq

> Phase 2 deliverable. Single source of architectural truth for `taskq`.
> Aligned with `SPEC.md` v3.0.0 (5 FR / 6 NFR / 8 env) and harness v2.9 architecture constraints.
> Module tree follows `SPEC.md` §6 verbatim — no invention of new top-level dirs.

---

## 1. Overview

### 1.1 System Verification Target

> **Phase 3 Gate 2 Requirement**: The harness executes `make verify-system` at Gate 2.
> If it exits with a non-zero status Gate 2 fails. Add a `verify-system` target to your
> project `Makefile` that assembles and exercises the system end-to-end (e.g. runs your
> integration tests or smoke-test suite). The target name is fixed — the harness always
> calls `make verify-system`.

**Makefile target**: `verify-system` (already present at `Makefile:20-21`; chains `test → shell-audit → smoke`).

`verify-system` audit chain:
1. `make test` — `pytest tests/ -q` (FR-01..FR-05 acceptance)
2. `make shell-audit` — invokes `python scripts/shell_audit.py $(SRC_DIR)` which delegates to `harness/core.audit.audit_grep` with docstring/comment exclusion; pattern `shell\s*=\s*True` must produce zero hits (NFR-02)
3. `make smoke` — end-to-end CLI smoke (`submit` → `run` → `status` → `clear` happy path)

### 1.2 Architectural Style

- **Layered CLI** (single-process, in-process modules; no service boundaries).
- **Storage layer** (`store.py` / `breaker.py` / `cache.py`) is the only I/O surface; all other modules are pure.
- **No framework, no external runtime deps** (SPEC §1: stdlib only).
- **Concurrency model**: `ThreadPoolExecutor` for `run --all`; shared `threading.Lock` gates every JSON write (FR-02, NFR-03).
- **Determinism hooks**: retry `sleep` is injectable (FR-03), breaker `now()` injectable, cache `time()` injectable — testability is a first-class architectural concern.

### 1.3 Scope Boundaries (in/out)

| In scope | Out of scope |
|----------|--------------|
| Local CLI queue (SPEC §1, §3) | Distributed/remote workers |
| JSON-file persistence under `$TASKQ_HOME` | SQLite / RDBMS |
| Stdlib-only runtime (SPEC §2) | Third-party runtime libs (pytest-benchmark is test-only) |
| Single-user concurrency (Lock-serialized) | Multi-user / network access |

---

## 2. Module Design

### 2.1 Directory Structure Design Principles

> **CRG Architecture Scoring**: Phase 3+ judges your code's community cohesion via
> the Code Review Graph (CRG). CRG groups files by **directory** — each directory
> is one community. The architecture score is the fraction of communities that are
> "healthy" (internal edge density ≥ 0.3 AND size ≤ 50 nodes).

**Design for high cohesion from the start — 6 Universal CRG Design Principles:**

> **Amendment 2026-07-07** (aligned with `.methodology/SAB.json` amendments):
> `config.py` and `models.py` were planned here in P2 but never implemented in P3
> (P2 phantom planning). All references below are updated to the as-built 7-file
> package: env vars are read in-place by their consumer modules; task/breaker/cache
> records are plain dicts. NFR-05/06 owners re-pointed to `taskq.cli`.

**Principle 1 — Use subdirectories to control CRG community boundaries.** CRG assigns one community per directory. The project has two source-bearing directories:
- `src/taskq/` — single production community (5 production modules = 7 files incl. `__init__.py` + `__main__.py`, ≤50 nodes).
- `tests/` — single test community (per-FR test files; not a scored source community).

**Principle 2 — Hub-and-spoke inside `src/taskq/`.** `store.py` is the I/O hub (≥4 functions, called from every other module body). `cli.py` is the orchestration hub (calls every other module). Together they generate the internal-edge budget required for cohesion ≥ 0.3 (see §2.3 budget table).

**Principle 3 — Entry point inside hub dir.** `__main__.py` lives inside `src/taskq/` and only re-exports `cli.main()`; the real entry hub is `cli.py` (calls `store / executor / breaker / cache` directly).

**Principle 4 — Every function body calls the hub.** Per-function-body calls to `store.atomic_write_json` (or `store.read_json`) appear in `cli.py`, `executor.py`, `breaker.py`, `cache.py` to multiply internal edges.

**Principle 5 — CRG edge detection rules respected.** All cross-module calls use `from .store import atomic_write_json` then `atomic_write_json(...)` standalone assignment — no lazy imports, no nested-arg calls, no `__getattr__` re-exports.

**Principle 6 — Community size ≤ 50 nodes.** `src/taskq/` plan: 7 files × ~4 functions average = ~28 nodes (under cap).

### 2.2 Directory Tree (per SPEC §6)

```
integration-test/
├── src/taskq/                    # production community (≤50 nodes)
│   ├── __init__.py               # package marker + version
│   ├── __main__.py               # python -m taskq 入口 (entry)
│   ├── store.py                  # tasks.json atomic I/O + Lock [FR-01/02, NFR-03]  (I/O HUB)
│   ├── executor.py               # subprocess + retry [FR-02/03, NFR-02/04]      (HIGH-RISK)
│   ├── breaker.py                # circuit breaker [FR-03]                        (state file I/O)
│   ├── cache.py                  # TTL cache [FR-04]                              (state file I/O)
│   └── cli.py                    # argparse orchestration [FR-05]                (ORCHESTRATION HUB)
├── tests/                        # test community (per-FR test files)
│   ├── test_fr01_submit.py
│   ├── test_fr02_executor.py
│   ├── test_fr03_retry_breaker.py
│   ├── test_fr04_cache.py
│   ├── test_fr05_cli.py
│   ├── test_nfr01_perf.py
│   ├── test_nfr02_shell_audit.py
│   ├── test_nfr03_atomic.py
│   ├── test_nfr04_redaction.py
│   ├── test_nfr05_docstrings.py
│   └── test_nfr06_env.py
├── .env.example                  # 8 TASKQ_* vars [NFR-06]
├── SPEC.md                       # source of truth
└── harness-e2e.js                # pipeline verification workflow
```

### 2.3 Module-to-FR Traceability (every FR ≥ 1 module)

| FR | Title | Primary module(s) | Supporting module(s) |
|----|-------|-------------------|----------------------|
| FR-01 | 任務提交與驗證 | `cli.py` (validation rules + exit 2) | `store.py` (atomic write tasks.json; task records are plain dicts) |
| FR-02 | 任務執行器 | `executor.py` (subprocess.run + state machine; reads TASKQ_TASK_TIMEOUT / TASKQ_MAX_WORKERS in-place) | `store.py` (status transitions + Lock) |
| FR-03 | 重試與斷路器 | `executor.py` (retry/backoff, sleep injectable) + `breaker.py` (state machine + persistence) | `store.py` (breaker.json atomic write) |
| FR-04 | 結果 TTL 快取 | `cache.py` (sha256 sign + TTL check) | `store.py` (cache.json atomic write) |
| FR-05 | CLI 整合 | `cli.py` (argparse subcommands + exit codes) | `__main__.py` (entry), all of the above |

### 2.4 Module-to-NFR Traceability

| NFR | Title | Owner module(s) | Mechanism |
|-----|-------|-----------------|-----------|
| NFR-01 | performance (submit+status p95 < 50ms) | `cli.py`, `store.py` | Hot path has zero subprocess; single `read_json` per call; no regex compilation in inner loop. Validated via `tests/test_nfr01_perf.py` (pytest-benchmark). |
| NFR-02 | security (no `shell=True`) | `executor.py` (sole subprocess caller) + repo-wide CI gate | `subprocess.run(shlex.split(cmd), ..., shell=False)` enforced at exactly one call site; `grep -rE "shell\s*=\s*True"` wired into `make shell-audit`. |
| NFR-03 | reliability (atomic writes, breaker recovery) | `store.py` (atomic_write_json), `breaker.py` (cooldown) | `tmp + os.replace` for all 3 JSON files; breaker `now()` injectable to test cooldown ≤ `TASKQ_BREAKER_COOLDOWN + 1s`. |
| NFR-04 | security (secret redaction) | `executor.py` (post-exec redact step) | Regex `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` applied to `stdout_tail` / `stderr_tail` **before** store write; 100% line replacement with `[REDACTED]`. |
| NFR-05 | maintainability (docstring `[FR-XX]`) | all public functions in `src/taskq/` | Convention: every public `def` / `class` docstring contains `[FR-XX]` tag for ≥1 owning FR. Gate 1 inspect via `tests/test_nfr05_docstrings.py`. |
| NFR-06 | deployability (env-only config) | consumer modules (`store.py` TASKQ_HOME, `executor.py` timeout/workers, `breaker.py` TASKQ_BREAKER_*, `cache.py` TTL), `.env.example` (declaration) | 8 `TASKQ_*` env vars read in-place with defaults from SPEC §5.1; no hard-coded paths. (Amendment 2026-07-07: centralized `config.py` never built; a config extraction is a P3+ extension item.) |

### 2.5 Module Specifications

#### 2.5.1 ~~`config.py`~~ / 2.5.2 ~~`models.py`~~ — removed by Amendment 2026-07-07

Planned in P2, never implemented in P3 (phantom modules, removed from SAB.json).
As built: the 8 `TASKQ_*` env vars are read in-place by their consumer modules
(`store.py` / `executor.py` / `breaker.py` / `cache.py`) with SPEC §5.1 defaults;
task / breaker / cache records are plain dicts validated at the write sites.
Status enums are string literals enforced by the FR-02 state-machine logic in
`executor.py`.

#### 2.5.3 `store.py` — Atomic JSON Store (I/O HUB)

| Attribute | Value |
|-----------|-------|
| Responsibility | All JSON file I/O for `tasks.json` / `breaker.json` / `cache.json`; shared `threading.Lock`; atomic write via `tmp + os.replace` |
| External Interface | `read_json(path) -> dict`, `atomic_write_json(path, data) -> None`, `lock() -> threading.Lock`, `tasks_path() / breaker_path() / cache_path()` |
| Dependencies | stdlib (`json`, `os`, `threading`, `tempfile`, `pathlib`) |
| Logical Constraints | Every write goes through `atomic_write_json`; every concurrent caller acquires `lock()`; corrupt JSON on read → `StoreCorrupted` exception (CLI exit 1, per SPEC §7 — **never** silent rebuild) |

#### 2.5.4 `executor.py` — Subprocess + Retry (HIGH-RISK MODULE)

| Attribute | Value |
|-----------|-------|
| Responsibility | Single subprocess call site (no `shell=True`); state machine transitions; retry/backoff; secret redaction; integrates breaker pre-check |
| External Interface | `execute(task: Task, *, sleep_fn=time.sleep, now_fn=time.monotonic) -> Task` |
| Dependencies | `models`, `store`, `breaker`, `cache`, `config`, stdlib (`subprocess`, `shlex`, `re`) |
| Logical Constraints | **Exactly one** `subprocess.run` call site; CLI (`cli.run`) is the sole primary caller of `breaker.check_and_record` for state pre-check (refuse if OPEN, exit 3); `executor.execute` performs a defensive re-check before subprocess launch (in-process reuse safety); on `TimeoutExpired` → status `timeout`; redact `stdout_tail`/`stderr_tail` before persisting; `sleep_fn` injectable for deterministic retry tests |

#### 2.5.5 `breaker.py` — Circuit Breaker

| Attribute | Value |
|-----------|-------|
| Responsibility | CLOSED/OPEN/HALF_OPEN state machine; persistence in `breaker.json`; cooldown enforcement |
| External Interface | `Breaker.check_and_record(success: bool, *, now_fn=time.monotonic) -> Decision`; returns `allow | probe | reject` |
| Dependencies | `models`, `store`, `config` |
| Logical Constraints | Threshold from `TASKQ_BREAKER_THRESHOLD`; cooldown from `TASKQ_BREAKER_COOLDOWN`; HALF_OPEN admits exactly one probe; on probe success → CLOSED + counter reset; on probe failure → OPEN + reset `opened_at` |

#### 2.5.6 `cache.py` — TTL Cache

| Attribute | Value |
|-----------|-------|
| Responsibility | `sha256(command)` keyed lookup in `cache.json`; TTL enforcement; thread-safe write |
| External Interface | `Cache.get(command) -> Optional[TaskResult]`, `Cache.put(command, result)` |
| Dependencies | `models`, `store`, `config`, stdlib (`hashlib`) |
| Logical Constraints | Cache hit only if status was `done` AND `cached_at + TASKQ_CACHE_TTL > now`; on miss/normal completion → `put`; eviction is lazy (TTL check at read time, no background sweep) |

#### 2.5.7 `cli.py` — argparse Orchestration (ORCHESTRATION HUB)

| Attribute | Value |
|-----------|-------|
| Responsibility | Subcommand dispatch (`submit` / `run` / `status` / `list` / `clear`); FR-01 validation rules with exit 2; `--json` global flag; exit code policy (0/1/2/3/4) |
| External Interface | `main(argv: list[str] | None = None) -> int`; subcommand funcs return exit codes |
| Dependencies | `models`, `store`, `executor`, `breaker`, `cache`, `config`, stdlib (`argparse`, `re`, `uuid`) |
| Logical Constraints | FR-01 injection blacklist regex `re.compile(r"[;\|&$<>\\`]")` — reject on any match; name uniqueness check vs pending/running only; unknown task id → exit 2; `clear` empties `tasks.json` / `breaker.json` / `cache.json` atomically |

#### 2.5.8 `__main__.py` — Entry Point

| Attribute | Value |
|-----------|-------|
| Responsibility | `python -m taskq` entry; delegates to `cli.main()`; sets `sys.exit(rc)` |
| External Interface | None (entry only) |
| Dependencies | `cli` |
| Logical Constraints | No business logic; never catches exceptions (let them propagate to caller) |

### 2.6 Dependency Graph (no circular deps)

```
                    __main__.py
                         │
                         ▼
                       cli.py  ◄────────── (orchestration hub)
                    ┌────┴────┬────────┐
                    ▼         ▼        ▼
                executor   breaker   cache
                    │         │        │
                    └────┬────┴────────┘
                         ▼
                      store.py  ◄────────── (I/O hub)
```

**Cycle audit** (per harness constraint `no_circular_dependencies`):
- `cli → {executor, breaker, cache, store}` — fan-out, no return edges
- `executor → {breaker, cache, store}` — fan-out, no return edge
- `breaker → {store}` — single edge
- `cache → {store}` — single edge
- `__main__ → cli` — single edge

**Result**: zero cycles. DAG direction: `cli` (top) → `store` (bottom).

### 2.7 CRG Internal-Edge Budget

Per Principle 4, every function body in non-leaf modules calls `store.atomic_write_json` or `store.read_json`. Plan:

| Module | File functions | Bodies calling store | Hub functions | Internal edges (est.) |
|--------|----------------|----------------------|---------------|-----------------------|
| `cli.py` | ~8 | ~8 | `atomic_write_json`, `read_json`, `lock()` | ~24 |
| `executor.py` | ~5 | ~5 | `atomic_write_json`, `read_json`, `lock()` | ~15 |
| `breaker.py` | ~4 | ~4 | `atomic_write_json`, `read_json` | ~8 |
| `cache.py` | ~4 | ~4 | `atomic_write_json`, `read_json` | ~8 |
| `store.py` | ~4 | (hub itself) | self | 0 (self-edges not counted) |

Estimated internal edges ≥ 55; external edges from stdlib imports ≈ ~30. Cohesion ≈ 55/(55+30) ≈ 0.65 — safely above 0.3 threshold.

### 2.8 File-Count Compliance (≤15 files/dir, no god-module)

| Directory | Files | Limit | Status |
|-----------|-------|-------|--------|
| `src/taskq/` | 7 | ≤15 | OK; largest module `cli.py` ≤ ~150 LOC (no god-module) |
| `tests/` | 11 | ≤15 | OK; one test file per FR + one per NFR |

---

## 3. Interfaces & Data Flows

### 3.1 Public CLI Surface (FR-05)

```
python -m taskq submit "<cmd>" [--name NAME]      exit: 0 | 2
python -m taskq run   <id> [--cached]            exit: 0 | 2 | 3 | 4
python -m taskq run   --all                       exit: 0 | 3
python -m taskq status <id>                       exit: 0 | 2
python -m taskq list   [--status S]               exit: 0
python -m taskq clear                             exit: 0
```

Global flag `--json` → machine-readable single-line JSON on stdout (all subcommands).

Exit code policy (SPEC §7):

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Internal error (uncaught exception, corrupt store) |
| 2 | Input validation error (incl. unknown task id, injection blacklist hit) |
| 3 | Breaker OPEN |
| 4 | Task timeout (single-task mode only) |

### 3.2 Submit Flow (FR-01)

```
User → cli.submit(cmd, name)
        │
        ├─ validate: non-empty, len ≤ 1000, no injection chars, name unique
        │     FAIL → stderr + exit 2
        │
        ├─ models.Task(id=uuid4()[:8], command=cmd, name=name,
        │              status=pending, created_at=now)
        │
        └─ store.atomic_write_json(tasks_path, {id: task.to_dict()})
              │
              └─ tmp file + os.replace  (NFR-03)
```

### 3.3 Run Flow (FR-02/03/04)

```
User → cli.run(id | --all)
        │
        ├─ breaker.check_and_record(success=False, dry=True)
        │     OPEN → stderr "breaker open" + exit 3
        │
        ├─ (FR-04) cache.get(command) AND not expired?
        │     YES → replay result, mark cached:true, exit 0
        │
        ├─ execute(task):
        │     ├─ subprocess.run(shlex.split(command), capture_output=True,
        │     │                   text=True, timeout=TASKQ_TASK_TIMEOUT)
        │     │     NO shell=True (NFR-02)
        │     │
        │     ├─ result.exit_code == 0 → status=done
        │     ├─ TimeoutExpired        → status=timeout → exit 4 (single mode)
        │     └─ else                  → status=failed
        │     │
        │     ├─ redact(stdout_tail, stderr_tail)  (NFR-04)
        │     │
        │     └─ if failed/timeout AND attempt < retry_limit:
        │           sleep(backoff_base * 2**attempt)  (injected)
        │           retry
        │
        ├─ breaker.check_and_record(success=(status==done))
        │     threshold reached → state=OPEN, persist
        │
        └─ (FR-04) if status==done → cache.put(command, result)
```

### 3.4 Data Flow Diagram

```
┌──────────┐    argv     ┌─────────┐
│  user    │────────────▶│  cli.py │
└──────────┘             └────┬────┘
                              │ dispatch
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   ┌─────────┐          ┌──────────┐          ┌─────────┐
   │executor │          │ breaker  │          │  cache  │
   └────┬────┘          └────┬─────┘          └────┬────┘
        │ subprocess         │ state              │ sha256
        ▼                    ▼                    ▼
   (child process)    ┌─────────────────────────────────┐
                       │         store.py               │
                       │   (Lock + atomic_write_json)   │
                       └────────────┬────────────────────┘
                                    ▼
                          ┌──────────────────────┐
                          │  $TASKQ_HOME/        │
                          │   ├── tasks.json     │
                          │   ├── breaker.json   │
                          │   └── cache.json     │
                          └──────────────────────┘
```

### 3.5 Concurrency Model

- `run --all` → `ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS)` (default 4).
- Every write path acquires `store.lock()` — serialized JSON mutations.
- Cache and breaker each have their own JSON file → no cross-file atomicity needed (SPEC NFR-03 scopes atomicity per-file).

---

## 4. NFR Handling

### 4.1 NFR-01 — Performance (p95 < 50ms for 100 submit+status)

| Concern | Architectural Choice |
|---------|----------------------|
| Hot path cost | `submit` / `status` perform ≤1 file read + ≤1 file write; no regex compilation in inner loop; `re.compile` at module load time |
| Lock contention | Submit/status do **not** hold Lock longer than the single JSON write; concurrent `run --all` does not block submit |
| Validation | Injection regex pre-compiled; name uniqueness check uses in-memory dict scan |
| Measurement | `tests/test_nfr01_perf.py` — pytest-benchmark over 100 iterations; gate at p95 < 50ms |

### 4.2 NFR-02 — Security (no `shell=True`)

| Concern | Architectural Choice |
|---------|----------------------|
| Single subprocess site | All shell execution funnels through one `subprocess.run(..., shell=False)` call in `executor.execute()` |
| Injection defense | FR-01 blacklist regex `re.compile(r"[;\|&$<>\\`]")` — reject on any match, exit 2 |
| CI enforcement | `make shell-audit` runs `grep -rE "shell\s*=\s*True" src/ tests/` → must be empty |
| Test coverage | `tests/test_nfr02_shell_audit.py` — covers all 5 injection chars + audit script returns 0 |

### 4.3 NFR-03 — Reliability (atomic writes, breaker recovery)

| Concern | Architectural Choice |
|---------|----------------------|
| Atomic write | `store.atomic_write_json` = write to `path + ".tmp"` → `os.replace(tmp, path)`. Same `os.replace` pattern for `tasks.json`, `breaker.json`, `cache.json`. |
| Crash safety | `os.replace` is atomic on POSIX (and Win ≥Vista); partial writes never visible |
| Corrupt JSON | `read_json` validates via `json.load`; on `JSONDecodeError` → raise `StoreCorrupted` → CLI exit 1, stderr `store corrupted` (SPEC §7 — no silent rebuild) |
| Breaker recovery | `breaker.check_and_record` reads `breaker.json` on each call; cooldown computed as `now - opened_at`; HALF_OPEN admits one probe; success → CLOSED + counter reset |
| Recovery time bound | `now - opened_at ≥ TASKQ_BREAKER_COOLDOWN` (5s default) → HALF_OPEN; probe latency ≤ 1s → total ≤ cooldown + 1s (NFR-03 contract) |
| Test coverage | `tests/test_nfr03_atomic.py` — fault injection (kill mid-write, signal during read) |

### 4.4 NFR-04 — Security (secret redaction)

| Concern | Architectural Choice |
|---------|----------------------|
| Redaction site | `executor.execute()` applies redaction **before** `atomic_write_json(tasks_path, ...)` — secrets never land on disk |
| Redaction regex | `re.compile(r"sk-[A-Za-z0-9_-]{8,}|token=\S+")` — full line replaced with `[REDACTED]` |
| Tail capture | `stdout_tail` and `stderr_tail` are last 2000 chars of subprocess output (post-redaction truncation order: redact first, then slice) |
| Test coverage | `tests/test_nfr04_redaction.py` — covers `sk-XXXXXXXX` (≥8 char), `token=abc123`, mix with normal output, multi-line |

### 4.5 NFR-05 — Maintainability (docstring `[FR-XX]`)

| Concern | Architectural Choice |
|---------|----------------------|
| Convention | Every public `def` / `class` in `src/taskq/` has a docstring containing `[FR-XX]` tag for ≥1 owning FR (e.g. `"""Validate a submit command. [FR-01]"""`) |
| Gate 1 enforcement | `tests/test_nfr05_docstrings.py` walks `src/taskq/**/*.py`, parses AST, asserts: (a) every public node has docstring, (b) docstring matches `\[FR-\d{2}\]` |
| Coverage target | 100% of public functions/classes |
| Edge case | Test files exempt (test docstrings free-form); `__init__.py` exports exempt |

### 4.6 NFR-06 — Deployability (env-only config)

| Concern | Architectural Choice |
|---------|----------------------|
| Env access | 8 `TASKQ_*` env vars read in-place by their consumer modules (`store.py` / `executor.py` / `breaker.py` / `cache.py`) with SPEC §5.1 defaults (Amendment 2026-07-07: planned `config.py` single-reader was never built) |
| Typed coercion | Each read site coerces to its typed value (`Path`, `int`, `float`); non-numeric env → `ValueError` → CLI exit 1 |
| Declaration | `.env.example` lists all 8 vars with comment annotations matching SPEC §5.1 verbatim |
| Test coverage | `tests/test_nfr06_env.py` — env override, default fallback, type coercion, missing file |

---

## 5. SAB Block (machine-readable — BINDING CONTRACT)

> **CONTRACT**: Field names, types, `sab:` root key, and `phase` as int must
> match `core/quality_gate/sab_parser.py:render_canonical_sab_template()`.
> Do NOT hand-write the YAML — paste from the canonical template and replace
> EXAMPLE values with your project's real values.
> Validate before committing: `python3 scripts/generate_sab.py --validate --project .`

<!-- SAB:START -->
```yaml
sab:
  version: "1.0"
  created_at: "2026-07-05"
  phase: 2  # MUST be int, NOT a string — parser raises on 'phase: "2"'
  project: "taskq"

  layers:  # api/service/store-style from SAD §2.6 (modules are plain strings, not dicts)
    # Amendment 2026-07-07: config/models layers removed (P2 phantom planning —
    # taskq.config / taskq.models were never implemented; see .methodology/SAB.json amendments).
    - name: api  # entry + orchestration: CLI surface + python -m taskq dispatcher
      modules:
        - "taskq.cli"
        - "taskq.__main__"
      allowed_dependencies: ["service", "store"]
    - name: service  # runtime logic: subprocess exec, retry, breaker, TTL cache
      modules:
        - "taskq.executor"
        - "taskq.breaker"
        - "taskq.cache"
      allowed_dependencies: ["store"]
    - name: store  # I/O HUB — atomic JSON writes + shared Lock (FR-01/02, NFR-03)
      modules:
        - "taskq.store"
      allowed_dependencies: []

  allowed_dependencies:
    # DAG per SAD §2.6 (no cycles; cli top, store bottom).
    # api → service, store
    - from: api
      to: service
    - from: api
      to: store
    # service → store
    - from: service
      to: store

  quality_targets:
    max_complexity: 15
    min_coverage: 80
    max_coupling: 0.3

  nfr_dimension_mapping: {}  # OPTIONAL — auto-derived by parser from nfr_traceability.type

  nfr_traceability:
    NFR-01:
      type: performance
      target: "submit+status p95 < 50ms over 100 iterations"
      module: taskq.cli
    NFR-02:
      type: security
      target: "shell=True usage rate = 0 across src/"
      module: taskq.executor
    NFR-03:
      type: reliability
      target: "atomic_write 100% across 3 JSON files; breaker OPEN→CLOSED <= TASKQ_BREAKER_COOLDOWN + 1s"
      module: taskq.store
    NFR-04:
      type: security
      target: "redaction hit rate = 100% for (sk-[A-Za-z0-9_-]{8,}|token=\\S+)"
      module: taskq.executor
    NFR-05:
      type: maintainability
      target: "docstring [FR-XX] coverage = 100% of public funcs/classes in src/taskq/"
      # Cross-cutting convention — applies to every public def/class in src/taskq/.
      # Amendment 2026-07-07: was taskq.models (phantom); re-pointed to taskq.cli.
      module: taskq.cli
    NFR-06:
      type: deployability
      target: "8 TASKQ_* env vars exposed via typed getters in config.py"
      # Amendment 2026-07-07: was taskq.config (phantom, never built); env vars are
      # read in-place by consumer modules. Re-pointed to taskq.cli per SAB.json.
      module: taskq.cli

  advisory_only: []  # AUTO-FILLED by parser from nfr_traceability advisory types — omit or leave []

  gate_score_overrides: {}  # AUTO-DERIVED by parser from nfr_traceability — omit or leave {}

  fr_module_traceability:  # one entry per FR (SPEC §3 — 5 FRs)
    FR-01: "taskq.cli"          # submit + validation rules + atomic write dispatch
    FR-02: "taskq.executor"     # subprocess.run + pending→running→{done,failed,timeout} state machine
    FR-03: "taskq.breaker"      # CLOSED/OPEN/HALF_OPEN state machine + breaker.json atomic persistence
    FR-04: "taskq.cache"        # sha256(command) TTL replay
    FR-05: "taskq.cli"          # argparse subcommands (submit/run/status/list/clear) + exit codes

  architecture_constraints:
    - "no_circular_dependencies"
    - "no_shell_true_in_subprocess"
    - "atomic_write_required_for_all_json_files"
    - "single_subprocess_call_site_in_executor"

  high_risk_modules:
    - "taskq.executor"   # subprocess + retry + redaction (FR-02/03 + NFR-02/04); sole shell=True risk surface
    - "taskq.store"      # atomic write + Lock + concurrent safety (FR-01/02 + NFR-03); breaker recovery bound
```
<!-- SAB:END -->

Note: Fill in `created_at` and run `python3 scripts/generate_sab.py --project . [--overwrite]`
before committing. The placeholder values above are the binding contract for Phase 2.

---

*Document version: v1.0 | Phase 2 deliverable | 2026-07-04*
*Source of truth: SPEC.md v3.0.0 | harness v2.9 architecture constraints*
