# SAD — taskq

This System Architecture Document (SAD) traces every design decision back to the SRS requirement specification (FR-01..FR-05, NFR-01..NFR-06). Refer to the FR/NFR traceability matrix in §5 (SAB block) for the complete FR→module mapping. Acceptance criteria for each FR are satisfied by the module listed in the traceability matrix.

## 1. Architecture Overview

`taskq` is a local task queue CLI tool written in Python 3.11 with zero runtime external dependencies (stdlib only). It exposes subcommands (`submit`, `run`, `status`, `list`, `clear`) via argparse and executes shell commands as managed tasks under timeout, retry, circuit-breaker, and TTL-cache controls. All persistent state is stored as JSON files under `$TASKQ_HOME/` using atomic writes (tmp + `os.replace`) protected by a shared `threading.Lock`.

The package lives at `src/taskq/` and is invoked via `python -m taskq`. It consists of seven focused modules plus the entry-point shim, all in a single directory that is the sole CRG community. `config.py` functions as the directory hub — every sibling module imports and calls it.

### 1.1 System Verification Target

Gate 2 invokes `make verify-system`. This target must:

1. Run `python -m taskq --help` (smoke-test CLI entrypoint).
2. Execute `pytest tests/ -x -q` (full test suite, fail-fast).
3. Run `grep -R "shell=True" src/ | wc -l` and assert 0 hits (NFR-02 audit).
4. Run `python -m taskq submit --command "echo ok" --name smoke && python -m taskq run smoke && python -m taskq status smoke` end-to-end.

Phase 3 implementors MUST provide a `Makefile` with a `verify-system` target that executes all four steps and exits non-zero on any failure.

### High-Level Component Diagram

```
         User
           │ python -m taskq <subcommand>
           ▼
       ┌────────┐
       │ cli.py │◄─── argparse subcommands (FR-05)
       └───┬────┘
           │ calls
    ┌──────┼────────────────────────────────┐
    │      │                                │
    ▼      ▼                                ▼
┌────────┐ ┌──────────┐            ┌──────────────┐
│store.py│ │executor.py│           │ breaker.py   │
│(FR-01) │ │(FR-02/03) │           │ (FR-03)      │
└───┬────┘ └────┬─────┘            └──────┬───────┘
    │           │                         │
    │     ┌─────┴────┐             ┌──────┴──────┐
    │     │ cache.py │             │ models.py   │
    │     │ (FR-04)  │             │ (all FRs)   │
    │     └──────────┘             └─────────────┘
    │
    └──── All above read config via config.py (hub — NFR-06)
```

---

## 2. Module Design

### 2.1 Directory Structure Design Principles

> **CRG Architecture Scoring**: Phase 3+ judges your code's community cohesion via
> the Code Review Graph (CRG).  CRG groups files by **directory** — each directory
> is one community.  The architecture score is the fraction of communities that are
> "healthy" (internal edge density ≥ 0.3 AND size ≤ 50 nodes).
>
> **CRG scoring formula**: Each community's cohesion = internal_edges / (internal_edges + external_edges).
> External edges = calls to libraries (stdlib, frameworks) + calls to other communities.
> Internal edge dilution is the primary risk — entry points (CLI, main.py) import many libraries,
> producing external edges with no offsetting internal edges unless they also call sibling modules.
> The fix is **not** to reduce library imports — it is to ensure every function body also calls at least one
> sibling within the same directory.
>
> **Required edge budget**: To reach cohesion ≥ 0.3 with E external edges, you need
> I ≥ ceil(0.4286 × E) internal edges. Each function-body call to a hub function = 1 internal edge.
> Module-level calls create 1 edge per file, but per-function-body calls multiply the count.
> Example: 48 external edges → need ≥21 internal edges. With 5 sibling files each having
> 4 function bodies calling 2 hub functions → 40 internal edges — safely above threshold.

**Design for high cohesion from the start — 6 Universal CRG Design Principles:**

**Principle 1 — Use subdirectories to control CRG community boundaries.** CRG assigns one community per directory. If you dump 10+ files into a flat `src/`, CRG's Leiden algorithm freely splits them into unpredictable communities — some will likely fall below the 0.3 cohesion threshold. Explicit subdirectories (`src/api/`, `src/core/`, `src/infrastructure/`) each become one predictable community. Aim for 3-6 source directories total (excluding tests). Fewer than 3 → oversized single community; more than 6 → too many communities to keep all above 0.3.

**Principle 2 — Every directory needs a hub module (≥2 functions for 4+ siblings).** Each directory with ≥2 files must have a shared module (`utils.py`, `common.py`, `helpers.py`) that ≥70% of sibling files import and call via standalone function calls: `result = hub.fn(...)`. This creates cross-file internal edges. Pure library-utility files that no sibling calls produce zero internal edges — they only dilute the community.

For directories with ≥4 sibling files, **one hub function is rarely enough** — a single function called from 5 files produces ~5 edges, which may not offset ~40+ external edges. Use **≥2 hub functions** so each sibling can call both from multiple function bodies, multiplying internal edge count. The tts-new infrastructure directory (5 siblings, 48 external edges) required 2 hub functions (`validate_config` + `get_config_snapshot`) called from every function body to reach ~32 internal edges and pass 0.3.

Exception: directories that form a linear processing pipeline (A→B→C) where each file calls the next in chain.

**Principle 3 — Entry points must live inside a hub directory.** Entry-point modules (CLI, `main.py`, `app.py`, daemon) unavoidably import many external libraries — httpx, FastAPI, argparse, asyncio, etc. Each external import adds an external edge. If the entry point sits alone at the project root (e.g. `src/cli.py`), those external edges dominate and cohesion drops below 0.3. Place entry points inside a directory that also contains a hub module — the entry point calls the hub (internal edges) to compensate for its external edges.

**Principle 4 — Every function body must call a hub function (not just module-level).** A file that is never imported or called by any other file in its directory contributes only external edges (its own imports) and zero internal edges — pure dilution. For each file in your design, verify it is either: (a) the hub module itself, (b) called by the hub, or (c) calls the hub. Files that fail this check should be merged into another file or directory.

Critically, **module-level calls alone are insufficient**. A module-level `_ = validate_config()` creates 1 internal edge per file regardless of how many functions it has. CRG counts edges per (caller_node, callee_node) pair — each function body that calls the hub creates a separate edge. To accumulate enough internal edges (see edge budget above), the hub function must be called **from every accessible function body** in each sibling file, not just at module level. Example: a 5-sibling directory needs ~21 internal edges; 5 module-level calls + 5×4 function-body calls = 25 edges.

**Principle 5 — Respect CRG edge-detection limits.** CRG uses Tree-sitter AST parsing and detects cross-file function calls resolved through imports. These limitations are cross-language:
- Calls between functions in the **same** file — NOT detected (zero cohesion contribution)
- `self.method()` calls inside a class — DETECTED (class hierarchy contributes edges)
- `import sibling` → `sibling.fn()` — DETECTED (cross-file import resolved)
- `result = hub.fn(...)` then `log.info(..., extra=result)` — DETECTED (standalone assignment)
- `log.info(..., extra=hub.fn(...))` — INCONSISTENTLY detected (nested arg position)
- Calls through imports at runtime (lazy imports in `__getattr__`, `__init__.py` re-exports) — may be missed if not statically resolvable

**Principle 6 — Size cap: communities stay under 50 nodes.** CRG marks any community with >50 nodes as unhealthy regardless of cohesion. A node ≈ one function or class in a file. If your directory design would produce >50 nodes (roughly 4-6 modules with 8-12 functions each), split into subdirectories. Unlike Principles 1-5, this can be relaxed slightly — the cap is 50, not 30 — so this is rarely the binding constraint unless you have large god-modules.

| Quick reference | check |
|----------------|-------|
| Source directories count? | 1 (src/taskq/) — fits all 7 modules + 2 entry-point files |
| Each dir has a hub file? | Yes — config.py is the hub |
| Hub has ≥2 functions if ≥4 sibling files? | Yes — `get_config()` + `validate_config()` |
| Entry points inside a hub dir? | Yes — `__main__.py` and `cli.py` live in src/taskq/ alongside config.py |
| Each function body calls a hub function? | Yes — every public function calls `config.get_config()` or `config.validate_config()` |
| Cross-file calls use standalone assignment? | Yes |
| Community size ≤ 50 nodes? | Yes — see mandatory node budget below; models.py MUST stay ≤5 public symbols |
| Edge budget: I ≥ 0.4286 × E? | Targeted — 9 siblings × 6 function bodies × 2 hub calls = 108 internal edges |

**Mandatory Node Budget (binding on Phase 3):**

| File | Max public functions/classes | Reason |
|------|------------------------------|--------|
| config.py | 4 (`Config` dataclass + `get_config` + `validate_config` + `_parse_env`) | Hub |
| models.py | 5 (`Task`, `TaskStatus`, `BreakerState`, `BreakerRecord`, `CacheEntry`) | Pure data |
| store.py | 5 (`load_tasks`, `save_task`, `load_task`, `_redact`, `_atomic_write`) | Store |
| executor.py | 5 (`run_task`, `run_all`, `_retry_loop`, `_capture_output`, `_run_one`) | Executor |
| breaker.py | 5 (`can_run`, `record_failure`, `record_success`, `get_state`, `_load`) | Breaker |
| cache.py | 4 (`lookup`, `write`, `_load`, `_key`) | Cache |
| cli.py | 7 (`main`, `cmd_submit`, `cmd_run`, `cmd_status`, `cmd_list`, `cmd_clear`, `_fmt`) | CLI |
| __main__.py | 1 (module-level script) | Entry shim |
| __init__.py | 0 (re-export only) | Package |
| **Total** | **≤ 36 nodes** | **Well under 50 cap** |

Phase 3 implementors MUST NOT exceed these per-file public symbol counts. If a function needs to be added, first confirm it replaces an existing one.

### 2.2 Directory Layout

```
src/taskq/
├── __init__.py        # re-exports public API
├── __main__.py        # python -m taskq entry point — calls cli.main()
├── config.py          # HUB — TASKQ_* env reads + validate_config() + get_config() [NFR-06]
├── models.py          # Task / BreakerState / CacheEntry dataclasses [FR-01..05]
├── store.py           # tasks.json atomic R/W + threading.Lock [FR-01/02]
├── executor.py        # subprocess execution + retry + backoff [FR-02/03]
├── breaker.py         # circuit-breaker FSM + breaker.json persistence [FR-03]
├── cache.py           # SHA-256 TTL cache + cache.json persistence [FR-04]
└── cli.py             # argparse subcommands + output formatting [FR-05]
```

9 files / 1 directory — under the ≤15 file limit; no god-module (each file has a single bounded responsibility).

### 2.3 Module Specifications

#### config.py — Configuration Hub (FR-01..FR-05, NFR-06)

| Attribute | Value |
|-----------|-------|
| Responsibility | Read all 8 `TASKQ_*` env vars with defaults; expose `get_config() -> Config` and `validate_config() -> bool`; enforce `TASKQ_HOME` directory creation |
| External Interface | `get_config() -> Config`, `validate_config() -> bool` |
| Dependencies | stdlib: `os`, `dataclasses` |
| CRG role | **Hub** — imported and called by all 6 sibling modules |

**Logical Constraints:**
- All env-var reads are centralised here; no other module calls `os.environ` directly.
- `Config` is a frozen dataclass; mutation forbidden after construction.
- `validate_config()` is called from every function body in sibling modules (CRG internal-edge anchor).

#### models.py — Domain Data Classes (FR-01..FR-05)

| Attribute | Value |
|-----------|-------|
| Responsibility | Define `Task`, `TaskStatus` (Enum), `BreakerState` (Enum), `BreakerRecord`, `CacheEntry` as plain dataclasses / NamedTuples |
| External Interface | All dataclass types — imported by store, executor, breaker, cache, cli |
| Dependencies | stdlib: `dataclasses`, `enum`, `typing` |

**Logical Constraints:**
- No business logic; pure data carriers. Import-time side effects (env reads, directory creation) are forbidden.
- **CRG hub-call exemption**: `models.py` is exempt from the per-function-body hub-call rule. It contains only dataclasses/NamedTuples with no method bodies that would naturally call a hub function; adding `validate_config()` calls would violate the pure-data-carrier constraint and risk import-order issues in tests. CRG internal edges for the `src/taskq/` community are supplied by the other 5 sibling files (store, executor, breaker, cache, cli) each of which calls `config.get_config()` and/or `config.validate_config()` from every public function body.
- `TaskStatus` values: `pending`, `running`, `done`, `failed`, `timeout`.
- `BreakerState` values: `CLOSED`, `OPEN`, `HALF_OPEN`.

#### store.py — Task Store (FR-01, FR-02)

| Attribute | Value |
|-----------|-------|
| Responsibility | Atomic read/write of `$TASKQ_HOME/tasks.json`; thread-safe via `threading.Lock`; redacts secrets in `stdout_tail`/`stderr_tail` before persistence (NFR-04) |
| External Interface | `load_tasks() -> dict`, `save_task(task: Task)`, `load_task(id: str) -> Task` |
| Dependencies | config (hub), models; stdlib: `json`, `os`, `threading`, `tempfile`, `re` |

**Logical Constraints:**
- Atomic write: write to `<file>.tmp` then `os.replace` (NFR-03).
- Shared `Lock` instance must be passed to executor for concurrent `--all` runs.
- Redaction regex `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` applied line-by-line before write (NFR-04).
- Calls `config.get_config()` in every public function body (CRG hub-call rule).

#### executor.py — Task Executor + Retry (FR-02, FR-03)

| Attribute | Value |
|-----------|-------|
| Responsibility | Run a task via `subprocess.run(shlex.split(...))` (shell=True forbidden — NFR-02); capture stdout/stderr tails; implement exponential-backoff retry; delegate breaker check/update |
| External Interface | `run_task(task: Task, store: Store, breaker: Breaker, cache: Cache, sleep_fn=time.sleep) -> Task` |
| Dependencies | config (hub), models, store, breaker, cache; stdlib: `subprocess`, `shlex`, `time`, `concurrent.futures` |

**Logical Constraints:**
- `shell=True` forbidden on any code path (NFR-02).
- Timeout via `subprocess.run(..., timeout=config.TASKQ_TASK_TIMEOUT)`.
- Retry loop: up to `TASKQ_RETRY_LIMIT` retries; backoff = `TASKQ_BACKOFF_BASE × 2^n`; `sleep_fn` injectable for tests.
- `run_all(ids, store, breaker, cache)` uses `ThreadPoolExecutor(max_workers=config.TASKQ_MAX_WORKERS)`.
- Calls `config.get_config()` in every public function body (CRG hub-call rule).

#### breaker.py — Circuit Breaker (FR-03)

| Attribute | Value |
|-----------|-------|
| Responsibility | FSM: CLOSED → OPEN → HALF_OPEN → CLOSED; persist state in `$TASKQ_HOME/breaker.json` (atomic write); expose `can_run()`, `record_failure()`, `record_success()` |
| External Interface | `can_run() -> bool`, `record_failure()`, `record_success()`, `get_state() -> BreakerRecord` |
| Dependencies | config (hub), models; stdlib: `json`, `os`, `time`, `tempfile` |

**Logical Constraints:**
- State persists across processes (cross-process circuit breaker per SPEC.md §3 FR-03).
- `can_run()` checks elapsed time vs `TASKQ_BREAKER_COOLDOWN` to auto-transition `OPEN → HALF_OPEN`.
- Atomic write to `breaker.json` (NFR-03).
- Calls `config.get_config()` in every public function body (CRG hub-call rule).

#### cache.py — TTL Result Cache (FR-04)

| Attribute | Value |
|-----------|-------|
| Responsibility | `sha256(command)` keyed cache stored in `$TASKQ_HOME/cache.json`; lookup within `TASKQ_CACHE_TTL` seconds returns cached result; write on `done`; atomic + thread-safe |
| External Interface | `lookup(command: str) -> Task | None`, `write(command: str, task: Task)` |
| Dependencies | config (hub), models; stdlib: `json`, `os`, `hashlib`, `time`, `threading`, `tempfile` |

**Logical Constraints:**
- Cache key = `hashlib.sha256(command.encode()).hexdigest()`.
- Expiry check: `time.time() - cached_at > TASKQ_CACHE_TTL`.
- Thread-safe: `cache.py` owns its **own** module-level `threading.Lock` instance (distinct from `store.py`'s Lock). The two files never share a Lock object; each guards its own JSON file exclusively. This avoids deadlock while still satisfying FR-04 AC-04.3 thread-safety because `cache.json` and `tasks.json` are separate files with no ordering dependency.
- Atomic write (NFR-03).
- Calls `config.get_config()` and `config.validate_config()` in every public function body (CRG hub-call rule).

#### cli.py — CLI Entry Point (FR-05)

| Attribute | Value |
|-----------|-------|
| Responsibility | argparse subcommand dispatch (`submit`, `run`, `status`, `list`, `clear`); global `--json` flag; exit-code enforcement; human-readable and JSON output formatting |
| External Interface | `main() -> None` (called by `__main__.py`) |
| Dependencies | config (hub), models, store, executor, breaker, cache; stdlib: `argparse`, `json`, `sys` |

**Logical Constraints:**
- All exit codes as per SPEC.md §3 FR-05: 0 / 1 / 2 / 3 / 4.
- `submit` validation: non-empty, ≤1000 chars, injection-char blacklist `; | & $ > < \``, name uniqueness (FR-01).
- Calls `config.get_config()` in every public function body (CRG hub-call rule).
- Entry point lives inside `src/taskq/` alongside hub — satisfies CRG Principle 3.

#### __main__.py — Package Entry Shim

| Attribute | Value |
|-----------|-------|
| Responsibility | `python -m taskq` entry point; delegates to `cli.main()` |
| External Interface | Module-level `if __name__ == "__main__": cli.main()` |
| Dependencies | cli (sibling) |

---

## 3. Interfaces & Data Flows

### 3.1 FR-01: Task Submission Flow

```
cli.cmd_submit(args)
  ├─ config.get_config()          # hub call
  ├─ validate_command(cmd)        # injection + length check
  ├─ store.load_tasks()           # check name uniqueness
  ├─ models.Task(...)             # build Task with uuid4[:8]
  └─ store.save_task(task)        # atomic write to tasks.json
       └─ redact_secrets(...)     # NFR-04
```

Exit 2 on any validation failure; task id to stdout on success.

### 3.2 FR-02: Task Execution Flow

```
cli.cmd_run(args)
  ├─ config.get_config()
  ├─ store.load_task(id)
  ├─ breaker.can_run()            # FR-03 guard — exit 3 if OPEN
  ├─ [--cached] cache.lookup(cmd) # FR-04 — return early if hit
  └─ executor.run_task(task, ...)
       ├─ config.get_config()     # hub call inside executor
       ├─ subprocess.run(shlex.split(cmd), timeout=...)   # NFR-02
       ├─ [on fail/timeout] retry loop with backoff       # FR-03
       ├─ breaker.record_failure() / record_success()
       ├─ cache.write(cmd, task)  # on done — FR-04
       └─ store.save_task(task)   # atomic write
```

### 3.3 FR-03: Circuit Breaker State Machine

```
CLOSED ──[consecutive_failures ≥ THRESHOLD]──► OPEN
  ▲                                              │
  │                                        [cooldown elapsed]
  │                                              ▼
  │                                         HALF_OPEN
  │                                              │
  └──────[trial success]────────────────────────┘
         [trial failure → re-OPEN]
```

State persisted to `$TASKQ_HOME/breaker.json` (atomic write, cross-process).

### 3.4 FR-04: Cache Lookup Flow

```
cache.lookup(command)
  ├─ key = sha256(command)
  ├─ load cache.json
  ├─ entry exists AND (now - cached_at) ≤ TTL → return cached Task
  └─ miss → return None → executor runs subprocess
```

### 3.5 FR-05: CLI Subcommand Map

| Subcommand | Modules Called |
|------------|---------------|
| `submit` | config, store, models |
| `run [--cached]` | config, store, executor, breaker, cache |
| `status <id>` | config, store |
| `list [--status S]` | config, store |
| `clear` | config, store (delete data files) |

### 3.6 Dependency Graph (no circular dependencies)

```
__main__ → cli
cli      → config, models, store, executor, breaker, cache
executor → config, models, store, breaker, cache
store    → config, models
breaker  → config, models
cache    → config, models
models   → config
config   → (stdlib only)
```

Verified acyclic: `config` has no project imports; `models` depends only on `config`; all others depend upward through the hierarchy with no back-edges.

---

## 4. NFR Handling

### NFR-01 — Performance (submit + status p95 < 50ms)

- `config.get_config()` uses a module-level cached `Config` singleton (parsed once).
- `store.load_tasks()` reads a single JSON file; no DB overhead.
- No network I/O in `submit` / `status` paths.
- `pytest-benchmark` measures the 100-iteration combined operation.

### NFR-02 — Security: shell=True forbidden + injection blacklist

- **Primary enforcement module: `executor.py`** — `subprocess.run(shlex.split(command), ...)` is the only subprocess call site; `shell=True` is forbidden on all code paths.
- **Secondary enforcement: `cli.cmd_submit`** — validates against `[;|&$><\`]` before any store write (defence-in-depth).
- CI audit: `grep -R "shell=True" src/` must return no hits (part of `make verify-system`).

### NFR-03 — Reliability: atomic writes + breaker recovery ≤ cooldown + 1s

- All three JSON files (`tasks.json`, `breaker.json`, `cache.json`) use `tmp + os.replace` pattern.
- `store.py` owns its own module-level `threading.Lock`; `cache.py` owns a **separate** module-level `threading.Lock`. Each guards its own JSON file exclusively — the two locks are never shared. This avoids deadlock because `cache.json` and `tasks.json` have no ordering dependency.
- `breaker.can_run()` auto-transitions `OPEN → HALF_OPEN` after `TASKQ_BREAKER_COOLDOWN` seconds.

### NFR-04 — Security: secret redaction

- `store.save_task()` applies `re.sub(r'(sk-[A-Za-z0-9_-]{8,}|token=\S+)', '[REDACTED]', line)` per line of `stdout_tail` / `stderr_tail` before serialising.

### NFR-05 — Maintainability: docstrings with [FR-XX] references

- All public functions and classes carry a docstring containing the relevant `[FR-XX]` tag.
- Enforced by `check-constitution` during Phase 6.

### NFR-06 — Deployability: all 8 TASKQ_* env vars in config.py + .env.example

- `config.py` is the sole reader of `os.environ` for all 8 variables.
- `.env.example` declares each variable with an inline comment.
- Variables: `TASKQ_HOME`, `TASKQ_MAX_WORKERS`, `TASKQ_TASK_TIMEOUT`, `TASKQ_RETRY_LIMIT`, `TASKQ_BACKOFF_BASE`, `TASKQ_BREAKER_THRESHOLD`, `TASKQ_BREAKER_COOLDOWN`, `TASKQ_CACHE_TTL`.

---

## 5. SAB Block (machine-readable — BINDING CONTRACT)

> **CONTRACT**: Field names, types, `sab:` root key, and `phase` as int must
> match `core/quality_gate/sab_parser.py:render_canonical_sab_template()`.

<!-- SAB:START -->
```yaml
sab:
  version: "1.0"
  created_at: "2026-06-23"
  phase: 2
  project: "taskq"

  layers:
    - name: cli
      modules:
        - "taskq.cli"
        - "taskq.__main__"
      allowed_dependencies: ["core", "infra"]
    - name: core
      modules:
        - "taskq.executor"
        - "taskq.breaker"
        - "taskq.cache"
        - "taskq.store"
      allowed_dependencies: ["infra"]
    - name: infra
      modules:
        - "taskq.config"
        - "taskq.models"
      allowed_dependencies: []

  allowed_dependencies:
    - from: cli
      to: core
    - from: cli
      to: infra
    - from: core
      to: infra

  quality_targets:
    max_complexity: 15
    min_coverage: 80
    max_coupling: 0.3

  nfr_dimension_mapping: {}

  nfr_traceability:
    NFR-01:
      type: performance
      target: "p95 < 50ms"
      module: taskq.store
    NFR-02:
      type: security
      target: "grep -R shell=True src/ returns 0 hits; injection chars blocked in cli.cmd_submit"
      module: taskq.executor
    NFR-03:
      type: reliability
      target: "atomic write on all 3 JSON files; breaker recovery <= cooldown + 1s"
      module: taskq.store
    NFR-04:
      type: security
      target: "stdout_tail/stderr_tail redacted before write matching sk-*/token=*"
      module: taskq.store
    NFR-05:
      type: maintainability
      target: "all public functions have docstring with [FR-XX] reference"
      module: taskq.config
    NFR-06:
      type: deployability
      target: "all 8 TASKQ_* env vars declared in config.py and .env.example"
      module: taskq.config

  advisory_only: []

  gate_score_overrides: {}

  fr_module_traceability:
    FR-01: "taskq.store"
    FR-02: "taskq.executor"
    FR-03: "taskq.breaker"
    FR-04: "taskq.cache"
    FR-05: "taskq.cli"

  architecture_constraints:
    - "no_circular_dependencies"
    - "no_shell_true"
    - "atomic_writes_only"

  high_risk_modules:
    - "taskq.executor"
    - "taskq.breaker"
    - "taskq.store"
```
<!-- SAB:END -->
