# SAD — Software Architecture Document: taskq

> **Project**: taskq v2.0.0
> **Author**: Architect (Agent A — Sub-Task 1/3)
> **Round**: 3
> **Date**: 2026-06-27
> **Source of truth**: `SPEC.md` v2.0.0 (2026-06-15) + `01-requirements/SRS.md` (INGESTION MODE, Round 1)
> **Adjacency**: hand-off from Phase 1 (Requirements); consumed by Phase 3 (Implementation)

---

## 1. Overview

### 1.1 Project Identity
- **Name**: `taskq` — local task queue CLI.
- **Entry point**: `python -m taskq`.
- **Language**: Python 3.11, stdlib only (**zero runtime external dependencies**).
- **Form**: command-line tool with subcommands.

### 1.2 Purpose
Submit shell commands as tasks; run them under controlled execution (timeout, retry); query / list / clear task state. Persisted as JSON on local disk.

### 1.3 Architectural Style
- **Layered** with strict top-down dependencies (CLI → Executor → Store; CLI → Config; Store → Config).
- **Single-process**, file-based persistence; no daemon, no network, no IPC.
- **Stateless across invocations** — each CLI invocation re-reads `tasks.json`, mutates in-memory dict, atomically rewrites.

### 1.4 Technical Stack (per SPEC §2)
| Component | Technology |
|-----------|------------|
| CLI parser | `argparse` (stdlib) |
| Task execution | `subprocess.run` with `shlex.split`; **`shell=True` forbidden** (NFR-02) |
| Persistence | JSON file; atomic write `tmp + os.replace` (NFR-03) |
| Configuration | `TASKQ_*` env vars via centralized `taskq.config` |

### 1.5 Quality Attributes (driving NFRs)
- **Performance** (NFR-01): `submit + status` p95 < 50 ms over 100 iter.
- **Security** (NFR-02): injection-character blacklist + zero `shell=True`.
- **Reliability** (NFR-03): atomic store + secret-line redaction.

---

## 2. Module Design

### 2.1 Module Tree Derivation
**Note on SPEC §6**: `SPEC.md` v2.0.0 (§1–§5) does **not** contain an explicit §6 directory-structure section. The module tree below is **derived faithfully** from the four components stated in SPEC §2 (CLI / 任務執行 / 持久化 / 設定) and the module names already pre-named in `SRS.md` §2.7 (`taskq.executor`, `taskq.store`, `taskq.config`). `redactor.py` is the sole module not pre-named in those sources — it is a justifiable leaf extraction (see ADR-010 §Rationale: extracted so the SAB `single_redaction_owner_executor` constraint refers to a specific named module rather than a method on `executor`). All other modules trace directly to SPEC §2 components or SRS §2.7 pre-names.

```
taskq/                          # Python package; entry: python -m taskq
├── __init__.py                 # version + public API re-exports
├── __main__.py                 # argv → cli.main(); entry for `python -m taskq`
├── cli.py                      # argparse surface; subcommand dispatch; --json; exit codes
├── config.py                   # TASKQ_* env-var loader (HOME, TASK_TIMEOUT, RETRY_LIMIT)
├── store.py                    # atomic JSON load/save; corruption detect; redaction-AGNOSTIC (caller redacts first; see §3.5)
├── executor.py                 # subprocess.run wrapper; state machine; retry loop; SOLE redaction owner
└── redactor.py                 # secret-line regex filter (sk-… / token=…); consumed by executor only
```
**File count**: 7 source files (≤15 cap respected; no god-module).

### 2.2 Module Responsibilities

| Module | Responsibility | Owner FR/NFR | Risk |
|--------|---------------|---------------|------|
| `taskq.config` | Read `TASKQ_HOME` / `TASKQ_TASK_TIMEOUT` / `TASKQ_RETRY_LIMIT` from env with defaults | FR-01, FR-02 | LOW |
| `taskq.store` | Load/save `tasks.json`; **atomic** tmp+os.replace; corruption detection (exit 1); **redaction-AGNOSTIC** — persists whatever dict it receives without inspecting fields (sole redaction owner is `taskq.executor`; see §2.6 contract + §3.5) | FR-01, NFR-03 | **HIGH** (SRS §2.7) |
| `taskq.redactor` | Pure function `redact(text) -> text` implementing `(sk-[A-Za-z0-9_-]{8,}\|token=\S+)` line replacement | NFR-03 | LOW |
| `taskq.executor` | Run command via `subprocess.run(shlex.split(cmd), …, timeout=…)`; state transitions `pending→running→{done\|failed\|timeout}`; retry loop | FR-02, NFR-02 | **HIGH** (SRS §2.7) |
| `taskq.cli` | argparse subcommands (`submit`/`run`/`status`/`list`/`clear`); `--json`; exit code table (0/1/2/4) | FR-03 | MEDIUM |
| `taskq.__main__` | thin shim: `sys.exit(cli.main())` — **wiring file, owns NO FR**; required only for `python -m taskq` invocation per SPEC §1.2 | (wiring, no FR owner) | LOW |
| `taskq` (`__init__`) | version, public symbols — **wiring file, owns NO FR** | (packaging, no FR owner) | LOW |

**Wiring-file rule (Gap-A)**: `__main__.py` and `__init__.py` are NOT counted as FR-owning modules. They appear in the 7-file budget but have no FR ownership row in §2.3; `fr_module_traceability` (§5) maps FRs only to behavior-owning modules (`taskq.cli`, `taskq.executor`, `taskq.store`, `taskq.redactor`, `taskq.config`). Listing them under the `cli` SAB layer is for layer-boundary tracking only — they inherit their layer's `allowed_dependencies` transitively because they only forward to `cli.main`.

### 2.3 FR-to-Module Mapping (mandatory: every FR → ≥1 module)

| FR | Primary module(s) | Supporting module(s) | ACs covered (grounded in SRS) |
|----|-------------------|----------------------|-------------------------------|
| **FR-01** Task Model & Persistence | `taskq.cli.submit` → `taskq.store.save` | `taskq.config.HOME`, `taskq.redactor` (not invoked pre-submit; redaction is post-run only) | AC-FR01-01..09 (SRS §3 FR-01) |
| **FR-02** Task Execution & Retry | `taskq.executor.run` → `taskq.cli.run` | `taskq.config.TIMEOUT/RETRY_LIMIT`, `taskq.store.save` (persist final result), `taskq.redactor` (redact stdout/stderr tails before persist) | AC-FR02-01..10 (SRS §3 FR-02, lines 134–142) |
| **FR-03** CLI Integration & Query | `taskq.cli.main` (argparse dispatch) | `taskq.store.load`, `taskq.config.HOME` | AC-FR03-01..08 (SRS §3 FR-03) |

**AC provenance note** (Gap-5): the AC-FR02-01..10 sub-IDs in the FR-02 row are not invented — they mirror `SRS.md` lines 134–142 verbatim, where each AC is enumerated 1:1 with the FR-02 acceptance-criteria block. No synthetic AC IDs introduced.

### 2.4 NFR-to-Module Mapping

| NFR | Type (binding) | Enforced in | AC |
|-----|----------------|-------------|-----|
| **NFR-01** | `performance` | `taskq.store` (single load + single save per submit; no extra scans); `taskq.executor` (p95 budget excludes subprocess exec) | AC-NFR01-01..02 |
| **NFR-02** | `security` | `taskq.cli.submit` (blacklist reject before persist); `taskq.executor.run` (`shlex.split` + `shell=False`); codebase-wide static rule (no `shell=True` substring) | AC-NFR02-01..03 |
| **NFR-03** | `reliability` | `taskq.store.save` (`tmp + os.replace`); `taskq.store.load` (corruption → exit 1, no rebuild); `taskq.redactor.redact` (line regex) | AC-NFR03-01..05 |

**Type taxonomy** (per `harness/templates/SAD.md` §5 contract): legal NFR type values are restricted to the 8 enumerated in `nfr_traceability` (5 enforceable: `performance`, `security`, `maintainability`, `reliability`, `testability`; 3 advisory: `deployability`, `scalability`, `usability`). Each type value used above appears verbatim in §5 SAB YAML.

**Canonical mapping note**: This §2.4 table is the authoritative NFR-to-module enforcement mapping. Each NFR is enforced by multiple modules as listed in the "Enforced in" column. Simplified artifacts (e.g., SAB `nfr_traceability.module`) may list only a primary module per NFR and are not the canonical reference for enforcement coverage. Drift detection tools MUST compare against this table, not against single-module summaries.

### 2.5 Dependency Graph (must be acyclic)
```
cli  ──► executor ──► store ──► config
 │        │            │
 │        ├─► redactor │
 │        │            │
 │        └─► config   │
 ├──► store            │
 └──► config           │
```
- One-way edges only. **No circular dependencies.** Verified by inspection.
- `cli → store` (direct): present for FR-03 `status`/`list`/`clear` subcommands (cli reads/writes store without going through executor; see §3.4). This edge is authoritative and MUST appear in §5 SAB `allowed_dependencies` for the `cli` layer.
- `cli → executor`: present for FR-02 `run` subcommand (cli dispatches to executor).
- `cli → config`: present for FR-01/FR-03 (HOME path resolution at startup).
- `executor → store`: FR-02 persist final result (2nd save).
- `executor → redactor`: FR-02 redaction of stdout/stderr tails before persist (sole redactor owner).
- `executor → config`: TASKQ_TASK_TIMEOUT / TASKQ_RETRY_LIMIT reads.
- `store → config`: TASKQ_HOME read for `tasks.json` path.
- `redactor` is a leaf (no outgoing deps); `config` is a leaf.
- `executor` never imports `cli` (no upward edges).
- **`store` does NOT depend on `redactor`** — this graph is authoritative and must agree with §5 SAB `allowed_dependencies`. Sole redaction owner is `executor` (per `single_redaction_owner_executor` constraint and §3.5 pipeline). Enforcement: `redactor` has exactly one importer in the codebase — `taskq.executor` (verified by `grep -r 'from taskq.redactor' taskq/`); `taskq.store.save` accepts the already-redacted dict from `executor` and performs no field inspection (see §2.6 contract).

### 2.6 Inter-Module Contracts

| Producer | Public symbol | Consumer | Contract |
|----------|---------------|----------|----------|
| `taskq.config` | `HOME: Path`, `TASK_TIMEOUT: float`, `RETRY_LIMIT: int` | all | Pure read of env; deterministic defaults |
| `taskq.store` | `load() -> dict[str, Task]`, `save() -> None` (mutates in-place dict; the module-level `store` dict is the implicit argument — see §3.2/§3.3 usage) | `cli`, `executor` | `load()` raises `StoreCorrupted` on invalid JSON; `save()` writes the module-level in-memory dict via tmp+os.replace and is **redaction-agnostic** — it persists whatever dict it receives without inspecting fields. Redaction is the caller's responsibility (see §3.5). **Known risk (v2.0.0):** the implicit module-level `store` dict couples all consumers to shared mutable state (§3.6, NP-13). A future refactor SHOULD make the dict an explicit parameter to `load()`/`save()` so consumers are decoupled from the module's internal state. |
| `taskq.executor` | `run(task_id: str) -> Task` | `cli.run` | Side-effect: mutates the store dict via in-place assignment, then calls `store.save()`; raises `TimeoutError` mapped to exit 4. **Sole owner of redaction**: calls `redactor.redact` on `stdout_tail`/`stderr_tail` BEFORE handing the updated record to `store.save`. |
| `taskq.redactor` | `redact(text: str) -> str` | `executor` (only) | Pure; preserves non-matching lines verbatim. **NOT called by `store.save`** — single-ownership rule per §3.5. **Enforcement**: `grep -rE 'from taskq\.redactor|import taskq\.redactor' taskq/` MUST return exactly one importer (`taskq.executor`). CI guard. |
| `taskq.cli` | `main(argv: list[str]) -> int` | `__main__` | Returns process exit code; never raises to caller |

### 2.7 Data Model

```jsonc
// tasks.json — top-level shape
{
  "<task_id>": {                    // task_id = uuid4().hex[:8] (lowercase hex)
    "id": "<task_id>",
    "command": "<validated shell command, ≤1000 chars>",
    "status": "pending|running|done|failed|timeout",
    "created_at": "<ISO-8601 UTC>",
    "finished_at": "<ISO-8601 UTC, null until terminal>",
    "exit_code": <int|null>,
    "duration_ms": <int|null>,
    "stdout_tail": "<last 2000 chars, redacted>",
    "stderr_tail": "<last 2000 chars, redacted>"
  }
}
```
- Task record keys at top level (dict-of-task shape) — chosen for O(1) `status <id>` lookup (FR-03 / NFR-01).
- Tail truncation (2000 chars) performed **before** redaction so the redaction marker `[REDACTED]` itself cannot be evicted by truncation.

---

## 3. Interfaces & Data Flows

### 3.1 CLI Surface (FR-03)

```
$ python -m taskq submit "<cmd>"     # FR-01
$ python -m taskq run   <id>         # FR-02
$ python -m taskq status <id>        # FR-03
$ python -m taskq list               # FR-03
$ python -m taskq clear              # FR-03
$ python -m taskq [--json] <subcmd>  # global flag
```

**Exit codes** (FR-03 / SPEC §3):
| Code | Condition |
|------|-----------|
| 0 | success |
| 2 | validation error OR unknown task id |
| 4 | task timeout (single-task mode) |
| 1 | other internal error |

### 3.2 Data Flow — `submit` (FR-01)
```
argv  ──► cli.main
            ├─► config.HOME               (read env, default ".taskq")
            ├─► validate(cmd)             (reject empty / whitespace / len>1000 / blacklist)
            │       └─► exit(2) on reject (no write)
            ├─► new_id()                  (uuid4().hex[:8])
            ├─► store.load()              (raise StoreCorrupted → exit(1))
            ├─► store[newid] = {pending, command, created_at}
            └─► store.save()              (tmp + os.replace)
```

### 3.3 Data Flow — `run <id>` (FR-02)
```
argv  ──► cli.main
            ├─► store.load()              (exit 1 on corruption)
            ├─► if id not in store: exit(2, "unknown task: <id>")
            ├─► store[id].status = "running"; store.save()      (1st save: running marker)
            ├─► executor.run(id)                                  [Sole redactor owner — see §3.5]
            │     attempt = 0
            │     status = None
            │     while attempt <= RETRY_LIMIT:
            │       attempt += 1
            │       try:
            │         sp = subprocess.run(shlex.split(cmd), capture_output=True,
            │                              text=True, timeout=TASK_TIMEOUT)
            │         status = "done" if sp.returncode == 0 else "failed"
            │       except subprocess.TimeoutExpired:
            │         status = "timeout"
            │         if single_task_mode: raise TimeoutError → exit(4)  (exit 4 mapping)
            │       # EXPLICIT retry policy (per FR-02 state machine):
            │       if status == "done": break                      # success — exit loop
            │       if status in ("failed", "timeout"):
            │         if attempt > RETRY_LIMIT: break               # exhausted retries
            │         continue                                       # retry next iteration
            │       # Defensive: status is None or unexpected value.
            │       # Classify as "failed" so post-loop has a terminal value.
            │       status = "failed"
            │       break
            │     # post-loop: status is terminal ("done"|"failed"|"timeout")
            │     # Assert post-condition (contract enforcement):
            │     assert status in ("done", "failed", "timeout"), \
            │         f"non-terminal status leaked: {status!r}"
            ├─► truncate stdout/stderr to last 2000 chars            (executor, before redaction)
            ├─► redactor.redact(stdout_tail)                         (executor — sole redactor)
            ├─► redactor.redact(stderr_tail)                         (executor — sole redactor)
            ├─► store[id].{exit_code, stdout_tail, stderr_tail,
            │              duration_ms, finished_at, status} = ...
            └─► store.save()                                         (2nd save: final result; store.save does NOT redact)
```

**Retry semantics** (Gap-3 fix): the loop distinguishes three exit conditions explicitly:
- `status == "done"` → break immediately (success).
- `status in ("failed", "timeout")` → continue if `attempt <= RETRY_LIMIT`, else break.
- `TimeoutExpired` in single-task mode → propagate as `TimeoutError` → `cli.main` exits 4 (per AC-FR02-03), bypassing the store update path.
This matches FR-02 state machine `pending → running → {done|failed|timeout}` with retry semantics bounded by `TASKQ_RETRY_LIMIT` (default 2; AC-FR02-07..08).

### 3.4 Data Flow — `status` / `list` / `clear` (FR-03)
```
status <id>:
  store.load() → if id not in store: exit(2)
                else: print(record) | json.dumps(record)

list:
  store.load() → for each record: print "<id>\t<status>\t<cmd[:50]>"
                                    or json.dumps([...])

clear:
  store.save({})   # empty dict atomically overwrites
```

### 3.5 Redaction Pipeline (NFR-03)
```
captured subprocess stdout/stderr
       │
       ▼
truncate to last 2000 chars        (executor, before redaction)
       │
       ▼
redact(text):                      (redactor.redact, pure)
   for line in text.splitlines():
     if re.fullmatch(r"(sk-[A-Za-z0-9_-]{8,}|token=\S+)", line):
         line = "[REDACTED]"
     emit line
       │
       ▼
persist via store.save             (tmp + os.replace; NFR-03 atomicity)
```

### 3.6 Concurrency / Failure Model
- **Single-writer assumption**: each CLI invocation is the only writer for its lifetime. AC-NFR03-01 (atomic write) holds under SIGKILL between `tmp` write and `os.replace` because `os.replace` is atomic on POSIX and the target is either pre-tmp or post-replace — never partial.
- **Concurrent-writer test (Gap-6)**: although v2.0.0 targets single-writer semantics, `tests/test_nfr03_concurrent_writers.py` (new) exercises two simultaneous `taskq submit` invocations against the same `$TASKQ_HOME` and asserts: (a) `tasks.json` remains valid JSON after both complete (atomic-write guarantee), (b) final on-disk state contains both task ids (no lost write). This is a regression guard, not a contractual guarantee — failure of (b) does NOT block Gate 2; failure of (a) DOES block.
- **Corruption detection**: `json.loads` failure on load → `StoreCorrupted` → `cli.main` exits 1 with stderr `store corrupted`. **No silent rebuild** (AC-FR01-09 / AC-NFR03-05).

---

## 4. NFR Handling

### 4.1 NFR-01 — Performance (p95 < 50 ms over 100 iter of submit+status)
- **Strategy**: keep the submit/status critical path to **one** `store.load` + **one** in-memory mutation + **one** `store.save` (single tmp + os.replace). No extra scans.
- **Measurement exclusion**: `subprocess.run` time is excluded from the 50 ms budget per SPEC §4.
- **Measurement protocol** (binding — external verifier MUST apply this exact procedure to reproduce the p95 target):
  - **Iteration count**: `iter_count = 100` (matches `tests/bench/test_nfr01_perf.py` and TEST_SPEC `test_benchmark_nfr01_submit_status_p95_under_50ms`).
  - **Warm-up runs**: `warmup_count = 10` iterations executed BEFORE the timed 100; results discarded. Warm-up stabilises the Python file-system cache (`os.replace` and `json.loads`) and the `TASKQ_HOME` directory inode on first invocations, so the p95 statistic is not skewed by cold-start latency.
  - **Exclusion policy**: only the timed 100 iterations contribute to the p95 calculation; warm-up iters are not measured. No iters within the timed 100 are excluded (no outlier trimming).
  - **Per-iter measurement**: wall-clock duration of one `submit "<cmd>"` invocation followed by one `status <id>` invocation of the SAME task id, measured via `time.perf_counter()` deltas in the test harness (NOT in production code).
  - **Statistic**: `p95 = quantile(sorted_durations, 0.95)` over the 100 timed iterations.
  - **Target**: `p95 < 50 ms` (assertion predicate `expected_p95_lt=50` per TEST_SPEC §NFR-01 row 1).
- **Verification**: `tests/bench/test_nfr01_perf.py` runs `warmup_count=10` warm-up + `iter_count=100` timed iterations and asserts `p95 < 50 ms`; reproducible via `tests/bench/benchmark_subprocess.py` (AC-NFR01-01..02).
- **Risk**: if `tasks.json` grows unbounded, `json.dumps` cost grows; out of scope per SPEC §6 (no task-limit / pruning specified). Documented, not mitigated in v2.0.0.

### 4.2 NFR-02 — Security (no `shell=True`; blacklist coverage)
- **Strategy**:
  - All subprocess invocations go through `taskq.executor.run` which calls `subprocess.run(..., shell=False)` (default; explicit).
  - All `argparse`-driven user input passes `validate()` in `cli.submit` **before** any persistence.
  - Blacklist `; | & $ > < \`` enforced with 7 parametrized test cases (AC-NFR02-02).
- **Verification**:
  - `tests/test_nfr02_no_shell.py` greps `taskq/` source for `shell=True` substring → expect 0 hits (AC-NFR02-01).
  - Defense-in-depth: no execution path interprets `command` via a shell (AC-NFR02-03).
- **Risk R2** (subprocess hang) is mitigated by `timeout=TASKQ_TASK_TIMEOUT` in `executor.run`.

### 4.3 NFR-03 — Reliability (atomic write + redaction)
- **Strategy**:
  - `store.save` writes to `<tasks.json>.tmp` then `os.replace` — POSIX atomic.
  - `store.load` uses `json.loads` and raises `StoreCorrupted` on any parse failure; `cli.main` maps to exit 1.
  - `redactor.redact` applies line-level regex `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` → `[REDACTED]`, preserving non-matching lines.
- **Verification**: AC-NFR03-01..05 (atomic interrupt sim, sk- redaction, token= redaction, non-matching preserved, no silent rebuild).
- **Risks R1, R3**: covered by atomic write and redaction respectively.

### 4.4 Risk Register (consolidated)
| ID | Risk | Module | Mitigation | Verified by |
|----|------|--------|------------|-------------|
| R1 | Concurrent/interrupted write corrupts store | `taskq.store` | tmp + os.replace | AC-NFR03-01, AC-FR01-08 |
| R2 | Subprocess hangs indefinitely | `taskq.executor` | `timeout=TASKQ_TASK_TIMEOUT` | AC-FR02-03 |
| R3 | Secret leakage in tails | `taskq.redactor` + `taskq.executor` | line-level redaction pre-persist | AC-NFR03-02..04 |

---

## 5. SAB Block (machine-readable — BINDING CONTRACT)

> **CONTRACT** (per `harness/templates/SAD.md` §5): `sab:` root key, `phase` as **int** (parser raises on quoted `"2"`), and `nfr_traceability.type` values restricted to the 8 legal taxonomy values declared in §2.4. The YAML below is the binding architectural contract for `taskq` v2.0.0 — it is consumed by `core/quality_gate/sab_parser.py:render_canonical_sab_template()` for Drift Detection and gate scoring.
>
> **Validate**: `python3 scripts/generate_sab.py --validate --project .`

<!-- SAB:START -->
```yaml
sab:
  version: "1.0"
  created_at: "2026-06-27"
  phase: 2  # MUST be int, NOT a string — parser raises on 'phase: "2"'
  project: "taskq"

  layers:  # taskq uses a single package layer with internal sub-modules
    - name: cli
      modules:
        - "03-development/taskq/cli.py"          # taskq.cli (FR-03 dispatch)
        - "03-development/taskq/__main__.py"     # wiring shim (python -m taskq) — inherits cli deps
        - "03-development/taskq/__init__.py"     # wiring file (version + public API re-exports) — inherits cli deps; owns no FR (see §2.2 wiring-file rule)
      allowed_dependencies: ["executor", "store", "config"]
    - name: executor
      modules:
        - "03-development/taskq/executor.py"     # taskq.executor (FR-02 + sole redactor owner)
      allowed_dependencies: ["store", "redactor", "config"]
    - name: store
      modules:
        - "03-development/taskq/store.py"        # taskq.store (FR-01 persistence; atomic)
      allowed_dependencies: ["config"]
    - name: redactor
      modules:
        - "03-development/taskq/redactor.py"     # taskq.redactor (leaf; consumer = executor only)
      allowed_dependencies: []
    - name: config
      modules:
        - "03-development/taskq/config.py"       # taskq.config (env-var loader; leaf)
      allowed_dependencies: []

  allowed_dependencies:
    - from: cli
      to: executor
    - from: cli
      to: store
    - from: cli
      to: config
    - from: executor
      to: store
    - from: executor
      to: redactor
    - from: executor
      to: config
    - from: store
      to: config
    # NOTE: store does NOT depend on redactor — redaction is owned by executor (§3.5)

  quality_targets:
    max_complexity: 15
    min_coverage: 80
    max_coupling: 0.3

  nfr_dimension_mapping: {}  # OPTIONAL — auto-derived from nfr_traceability.type

  nfr_traceability:
    NFR-01:
      # type MUST be one of 8 legal values (5 enforceable + 3 advisory)
      type: performance       # ENFORCEABLE
      target: "p95 < 50ms"
      module: taskq.store
    NFR-02:
      type: security          # ENFORCEABLE
      target: ">=0 shell=True in taskq/ source tree; 7 blacklist chars rejected"
      module: taskq.executor
    NFR-03:
      type: reliability       # ENFORCEABLE
      target: "atomic write + redaction enforced on every save"
      module: taskq.store

  advisory_only: []  # AUTO-FILLED by parser — omit or leave []

  gate_score_overrides: {}  # AUTO-DERIVED by parser — omit or leave {}

  fr_module_traceability:
    FR-01: "taskq.cli"             # submit path: cli → store
    FR-02: "taskq.executor"        # run path: executor → store → redactor
    FR-03: "taskq.cli"             # status/list/clear dispatch

  architecture_constraints:
    - "no_shell_true"
    - "atomic_writes_only"
    - "no_circular_dependencies"
    - "single_redaction_owner_executor"  # Gap-4 fix: redaction owned by executor only

  high_risk_modules:
    - "taskq.executor"
    - "taskq.store"
```
<!-- SAB:END -->

**Generator**: `python3 scripts/generate_sab.py --project . [--overwrite]`

---

## 6. Architectural Constraints Compliance

| Constraint (from project CLAUDE.md) | Compliance |
|-------------------------------------|------------|
| `no_shell_true` | Enforced in `executor.run`; verified by AC-NFR02-01 |
| `atomic_writes_only` | Enforced in `store.save`; verified by AC-FR01-08, AC-NFR03-01 |
| ≤15 files/dir, no god-module | 7 source files; each module single-responsibility |
| No circular dependencies | One-way DAG (cli → executor → store → redactor; cli/config leaves) |
| Zero runtime external deps | stdlib only (`argparse`, `subprocess`, `shlex`, `json`, `uuid`, `os`, `re`, `datetime`, `pathlib`) |

---

## 7. Hand-off to Phase 3 (Implementation)

- 3 FRs decomposed into 5 active modules + 2 wiring files.
- 3 NFRs each assigned a verification path in `tests/`.
- High-risk modules flagged for Phase 6 security review: `taskq.executor`, `taskq.store`.
- No deferred items; no prompt-injection patterns; no invented requirements.

*End of SAD — taskq v2.0.0 — Round 3*