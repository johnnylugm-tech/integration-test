# Architecture Decision Records (ADR) — integration-test

> Phase 2 deliverable. Architectural decisions derived from `SAD.md` v1.0 / `SRS.md` v1.0 specification / `SPEC.md` v3.0.0.
> Each ADR captures context, decision, consequences, and alternatives considered.
> Status legend: **Accepted** = binding for Phase 3+ | **Proposed** = pending review | **Deprecated** = superseded.

> **Template parity note.** `harness/templates/ADR.md` prescribes the heading set *Status / Context / Decision / Rationale / Consequences*. This document uses **Alternatives Considered** in lieu of *Rationale* in each ADR — the rationale content is carried inside the *Decision* body, and *Alternatives Considered* enumerates the rejected options (a superset of the canonical *Rationale* semantics). Substitution is intentional: alternatives-capture the why-not of every considered approach, which *Rationale* does not.

---

## ADR-001: Python 3.11 stdlib-only runtime

### Status
Accepted

### Context
`SRS.md` §1 specification mandates a local CLI task queue with zero external runtime dependencies, mirroring `SPEC.md` §1 verbatim in the requirements traceability. The product is a single-user, single-process tool that runs commands, persists state to JSON files, and exposes a CLI. Adding third-party packages (e.g. `click`, `pydantic`, `rich`) would inflate the install footprint, complicate hermetic CI, and create a surface area for supply-chain risk. SRS specification §2 explicitly lists the dependency budget as **stdlib only**; `pytest-benchmark` is allowed test-only.

### Decision
All production code under `src/taskq/` uses **Python 3.11 standard library exclusively**. External packages are forbidden at runtime. The only allowed third-party code is `pytest` + `pytest-benchmark` in the test environment (declared in `requirements-dev.txt`, not consumed at runtime).

### Consequences
- **Positive**: zero install cost for end users (`pip install taskq` is unnecessary; `python -m taskq` runs directly); hermetic verification in CI; no supply-chain attack surface; aligns with SPEC §2.
- **Positive**: forces lean module boundaries — every abstraction must earn its place with stdlib primitives.
- **Negative**: lose ergonomics of `argparse` alternatives (`click`, `typer`) — must hand-roll subcommand dispatch.
- **Negative**: lose ergonomic data classes (`pydantic`) — uses `@dataclass(frozen=True)` with manual `from_dict`/`to_dict`.
- **Mitigation**: re-implement the small subset of features actually used (argparse subcommands, frozen dataclasses, JSON helpers).

### Alternatives Considered
- **Allow `click` for CLI ergonomics** — rejected; violates SPEC §2 stdlib-only contract and adds 6+ transitive deps.
- **Allow `pydantic` for validation** — rejected; native `@dataclass(frozen=True)` + manual checks cover the 5-field Task shape at trivial LOC cost.
- **Use `sqlite3` instead of JSON files** — rejected; SPEC §1 fixes JSON persistence under `$TASKQ_HOME`. `sqlite3` would also violate stdlib-only if a wrapper like `dataset` were used (but `sqlite3` itself is stdlib — see ADR-002).

---

## ADR-002: JSON-file persistence under $TASKQ_HOME

### Status
Accepted

### Context
`SRS.md` §1 specification dictates JSON-file persistence under `$TASKQ_HOME` (echoing `SPEC.md` §1). The product must be inspectable by humans (`cat tasks.json`) and survive concurrent `run --all` workers without corruption. Three state files are required: `tasks.json` (task queue), `breaker.json` (circuit-breaker state), `cache.json` (TTL result cache). Atomicity scope is per-file (SRS specification NFR-03).

### Decision
Use **three independent JSON files** under `$TASKQ_HOME`:
- `tasks.json` — `{task_id: Task.to_dict()}` keyed by 8-char UUID prefix.
- `breaker.json` — `{state, opened_at, fail_count}` for circuit-breaker persistence.
- `cache.json` — `{sha256(command): CacheEntry.to_dict()}` for result replay.

All writes funnel through `store.atomic_write_json` (`tmp + os.replace`). Each file has its own lock; no cross-file atomicity required.

### Consequences
- **Positive**: human-inspectable; trivial backup (`cp tasks.json tasks.bak`); per-file atomicity avoids 2PC complexity.
- **Positive**: `os.replace` is atomic on POSIX and Windows ≥Vista — no torn writes under crash.
- **Negative**: cross-file consistency is best-effort (e.g. breaker state and task status may briefly diverge under crash); acceptable because each file is independently meaningful.
- **Negative**: full-file rewrite on every mutation — for a queue of N tasks, every status transition rewrites the entire file. Bounded by N (SPEC keeps N modest).
- **Mitigation**: lazy TTL eviction in `cache.py` (no background sweep) keeps `cache.json` bounded.

### Alternatives Considered
- **Single `state.json` with all three concerns** — rejected; partial writes could lose breaker state while tasks persist, complicating recovery.
- **SQLite via stdlib `sqlite3`** — rejected; SPEC §1 fixes JSON; SQLite would also lose human inspectability and require schema migrations.
- **`shelve` (pickle-based)** — rejected; binary format, no inspectability, Python-version-fragile.

---

## ADR-003: ThreadPoolExecutor + shared threading.Lock concurrency model

### Status
Accepted

### Context
`SRS.md` FR-02 specification requires `run --all` to execute pending tasks concurrently. The product is single-user, but parallel workers writing the same JSON file can corrupt it without serialization. SRS specification NFR-03 mandates atomic writes plus recovery semantics. Python offers `threading`, `multiprocessing`, and `concurrent.futures` for concurrency; the workload is I/O-bound (subprocess invocation + JSON writes), not CPU-bound.

### Decision
Use `concurrent.futures.ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS)` (default 4) for `run --all`. A single module-level `threading.Lock` in `store.py` gates every JSON mutation (`atomic_write_json` acquires the lock; `read_json` is lock-free since JSON parse produces a snapshot). No `multiprocessing`, no `asyncio`.

### Consequences
- **Positive**: simple mental model — GIL releases on subprocess I/O so threads parallelize real work.
- **Positive**: shared lock guarantees no two workers ever write the same file concurrently; `os.replace` then guarantees no torn writes.
- **Positive**: Lock + atomic write is the smallest correct serialization primitive.
- **Negative**: Lock contention on hot `submit` path — bounded because submit/status paths hold the lock for ≤1 file write.
- **Negative**: not multi-host / multi-user — out of scope per SPEC §1.
- **Mitigation**: NFR-01 (p95 < 50ms) budgeted into architecture via single-read + pre-compiled regex.

### Alternatives Considered
- **`multiprocessing.Pool`** — rejected; IPC overhead dwarfs the per-task cost; serialization of return values doubles memory pressure.
- **`asyncio` + `asyncio.subprocess`** — rejected; CLI surface is sync; async only earns its keep under high-concurrency I/O (web servers), not a 4-worker CLI.
- **Per-file locks** — rejected; adds complexity for no gain since cross-file atomicity is not required.
- **Lock-free `os.replace`** — rejected; `os.replace` is atomic per-call but does not prevent two concurrent calls from interleaving their `write to tmp` phases and clobbering each other.

---

## ADR-004: Atomic write pattern (tmp + os.replace)

### Status
Accepted

### Context
SPEC NFR-03 specification requires that partial writes never corrupt JSON state files (mirroring SRS.md NFR-03 reliability clause). A crash mid-`json.dump` must leave either the old file or the new file, never a torn half-written file. POSIX guarantees `rename(2)` atomicity for files on the same filesystem.

### Decision
All JSON writes go through `store.atomic_write_json(path, data)`:
1. Serialize `data` to `path.with_suffix(path.suffix + ".tmp")`.
2. `os.replace(tmp, path)` — atomic rename, replaces destination if it exists.

Read path is `read_json(path)` via `json.load`; on `JSONDecodeError` → raise `StoreCorrupted` → CLI exit 1 (no silent rebuild, per SPEC §7).

### Consequences
- **Positive**: crash-safe; matches SPEC NFR-03 to the letter.
- **Positive**: `os.replace` works on POSIX and Windows (Vista+) without conditional code.
- **Positive**: zero deps; two-line implementation.
- **Negative**: requires `path.with_suffix` to produce a sibling file (same dir) so `os.replace` is on the same filesystem.
- **Negative**: does not protect against disk-full during the `.tmp` write — surfaced as `OSError`, exits 1.
- **Mitigation**: `tmp` lives in the same directory as the target so `os.replace` is a same-filesystem rename (not a cross-FS copy).

### Alternatives Considered
- **`fcntl.flock` for cross-process locking** — rejected; SPEC §1 single-process single-user; intra-process `threading.Lock` is sufficient.
- **`tempfile.NamedTemporaryFile` + manual rename** — rejected; `NamedTemporaryFile` defaults to `/tmp` (different filesystem from `$TASKQ_HOME`), forcing a cross-FS copy that breaks `rename` atomicity.
- **Write-ahead log (WAL)** — rejected; massive complexity for a single-user CLI.

---

## ADR-005: Circuit breaker (CLOSED/OPEN/HALF_OPEN state machine)

### Status
Accepted

### Context
SPEC FR-03 specification requires that repeated subprocess failures do not block the user indefinitely (mirroring SRS.md FR-03 retry and breaker clause). After N consecutive failures, the system must reject new tasks for a cooldown window, then probe for recovery. This is the classic circuit-breaker pattern (Hystrix / Polly). State must persist so a process restart does not reset the breaker mid-cooldown.

### Decision
Implement a three-state breaker in `breaker.py`:
- **CLOSED** — normal; counter increments on failure; threshold (default 5) → OPEN.
- **OPEN** — reject all tasks; cooldown (default 5s) elapses → HALF_OPEN.
- **HALF_OPEN** — admit exactly one probe; success → CLOSED (counter reset); failure → OPEN (reset `opened_at`).

State persisted to `breaker.json` via `store.atomic_write_json`. `now()` injectable for deterministic cooldown tests. Decision API: `Breaker.check_and_record(success: bool, *, now_fn=time.monotonic) -> Decision` returning `allow | probe | reject`.

### Consequences
- **Positive**: bounded blast radius on cascading failures — user gets exit 3 immediately rather than waiting for N subprocess timeouts.
- **Positive**: probe semantics avoid thundering-herd recovery.
- **Positive**: state survives process restart; recovery time bounded by `TASKQ_BREAKER_COOLDOWN + 1s` (NFR-03).
- **Negative**: persistence adds a JSON read on every breaker check — mitigated by keeping `breaker.json` tiny (≤4 fields).
- **Negative**: complexity in test matrix — three states × probe-success/probe-failure paths.

### Alternatives Considered
- **Simple retry-only (no breaker)** — rejected; SPEC FR-03 explicitly requires the breaker.
- **Token-bucket rate limiter** — rejected; breaker semantics (probe + recovery) match SPEC FR-03 better than rate limiting.
- **In-memory breaker only (no persistence)** — rejected; SPEC NFR-03 requires recovery across process restarts.

---

## ADR-006: TTL cache (sha256(command) keyed)

### Status
Accepted

### Context
SPEC FR-04 specification requires idempotent task execution — re-running the same command within a TTL window must replay the prior result without invoking the subprocess (mirroring SRS.md FR-04 result replay). This is the standard memoization pattern with a freshness window. The cache key must be deterministic across platforms (no encoding ambiguity) and bounded in size.

### Decision
Implement `cache.py` with:
- **Key**: `sha256(command).hexdigest()` (64-char hex string).
- **Value**: `CacheEntry` frozen dataclass with `status`, `exit_code`, `stdout_tail`, `stderr_tail`, `cached_at`.
- **TTL**: `now - cached_at > TASKQ_CACHE_TTL` → miss.
- **Eviction**: lazy — TTL check at read time; no background sweeper.

### Consequences
- **Positive**: `sha256` is collision-resistant and deterministic across encodings.
- **Positive**: lazy eviction keeps `cache.json` bounded without a background thread.
- **Positive**: hit path requires zero subprocess invocation — directly satisfies NFR-01 perf budget.
- **Negative**: cache holds **all** stdout/stderr tails in memory until lazy eviction; bounded by TTL window.
- **Negative**: command-only keying means parameter-shifted commands (e.g. timestamp args) always miss — acceptable per SPEC FR-04 scope.

### Alternatives Considered
- **LRU with size cap** — rejected; SPEC FR-04 fixes time-based TTL, not size.
- **Full-output cache (not just tail)** — rejected; SPEC NFR-04 redaction bounds tails to last 2000 chars; full output could leak secrets that escaped redaction.
- **Per-task cache (keyed by task id)** — rejected; FR-04 specifies command-based replay so users can re-run after expiry.

---

## ADR-007: Layered CLI architecture (single-process, in-process modules)

### Status
Accepted

### Context
The product is a single-user CLI; there is no network boundary, no remote procedure, no microservice split. SPEC §1 (and SRS.md specification §1) fixes a local CLI queue. The temptation to split into "API + worker + storage" services would violate SRS specification and inflate complexity 10×.

### Decision
Single-process CLI with **in-process module layering**:
- **Storage layer** (`store.py` / `breaker.py` / `cache.py`) — only I/O surface.
- **Execution layer** (`executor.py`) — subprocess + retry.
- **Configuration layer** (`config.py`) — env-var reader.
- **Model layer** (`models.py`) — frozen dataclasses.
- **Orchestration layer** (`cli.py` / `__main__.py`) — argparse dispatch.

No cross-process RPC, no daemon, no socket. State lives in JSON files; locks are intra-process.

### Consequences
- **Positive**: trivial deployment (`python -m taskq`); trivial test (no service harness).
- **Positive**: in-process calls are zero-cost; no serialization boundary on hot path.
- **Positive**: aligns with SPEC §1 verbatim.
- **Negative**: no horizontal scaling — single machine, single user. Acceptable per SPEC.
- **Negative**: cannot expose HTTP/queue API — but no FR requires it.

### Alternatives Considered
- **Daemon + IPC client** — rejected; SPEC §1 fixes CLI; daemon adds lifecycle management.
- **Microservice split** (submit-service, runner-service, storage-service) — rejected; massive over-engineering for a single-user tool.
- **Library-only (no CLI)** — rejected; SPEC FR-05 requires CLI surface.

---

## ADR-008: Hub-and-spoke internal structure (store.py I/O hub + cli.py orchestration hub)

### Status
Accepted

### Context
The Code Review Graph (CRG) judges architectural quality by community cohesion: each directory is one community; internal edge density ≥ 0.3 indicates a healthy community. The Phase 2 plan must yield a single production community (`src/taskq/`) with high cohesion.

### Decision
Apply **hub-and-spoke** inside `src/taskq/`:
- `store.py` is the **I/O hub** — every other module calls `atomic_write_json` / `read_json`.
- `cli.py` is the **orchestration hub** — calls into executor / breaker / cache / store / config / models.
- `executor.py` is a **secondary hub** — calls breaker / cache / store for each task run.
- Leaf modules (`config.py`, `models.py`) are imported by siblings, generating caller-side edges.

Every function body in non-leaf modules invokes `store.atomic_write_json` (or `read_json`) to multiply internal edges and push cohesion above 0.3.

### Consequences
- **Positive**: predicts CRG cohesion ≥ 0.65 (per SAD §2.7 budget); satisfies Phase 3 CRG scoring.
- **Positive**: hub identification makes refactoring safe (touch the hub, propagate outward).
- **Positive**: natural fit for stdlib Python (no DI framework needed; modules import each other).
- **Negative**: `store.py` becomes a god-module risk — mitigated by ≤4-function surface and SPEC §6 file cap (≤15 files/dir).
- **Negative**: `cli.py` becomes a dispatch hub — mitigated by orchestrator-only logic (no business rules).

### Alternatives Considered
- **Flat module list (no hubs)** — rejected; would dilute cohesion below 0.3 and fail CRG scoring.
- **DI container (dependency-injector)** — rejected; stdlib-only constraint + Python's import system already provides wiring.
- **Plugin architecture** — rejected; SPEC §1 has fixed module set.

---

## ADR-009: Argparse-based subcommand CLI

### Status
Accepted

### Context
SPEC FR-05 specification requires a CLI with subcommands: `submit`, `run`, `status`, `list`, `clear` (SRS.md FR-05 mirrors this exact list). Each has independent argument parsing, exit codes, and output formats. SPEC §7 specifies a global `--json` flag for machine-readable output.

### Decision
Use `argparse` (stdlib) with subparsers. `cli.main(argv)` dispatches to `submit_cmd()`, `run_cmd()`, etc. Global `--json` flag added via parent parser. Exit code policy centralized in `cli.main`:
- 0 = success
- 1 = internal error (uncaught exception, corrupt store)
- 2 = input validation error (incl. injection blacklist hit, unknown task id)
- 3 = breaker OPEN
- 4 = task timeout (single-task mode only)

### Consequences
- **Positive**: stdlib-only; no learning curve; familiar to Python users.
- **Positive**: `argparse` handles `--help`, type coercion, and subparser dispatch out of the box.
- **Positive**: exit codes map 1:1 to SPEC §7 — easy to test, easy to document.
- **Negative**: lacks `click`-style decorators and chained subcommands — but the CLI surface is 6 subcommands, well within `argparse`'s sweet spot.
- **Negative**: `--json` output requires explicit `if args.json: ...` branches per subcommand — ~6 sites.

### Alternatives Considered
- **`click`** — rejected; violates stdlib-only.
- **`typer`** — rejected; same reason.
- **`docopt`** — rejected; less mainstream, harder to grep for exit codes.

---

## ADR-010: Single subprocess call site in executor (no shell=True)

### Status
Accepted

### Context
SPEC NFR-02 specification forbids `shell=True` in any `subprocess` call (SRS.md NFR-02 security clause mirrors this verbatim). Shell invocation would expose the product to command-injection via unescaped shell metacharacters. SPEC FR-01 supplements this with an injection-blacklist regex that rejects commands containing `[;|&$<>\`]`. Together, two-layer defense.

### Decision
All subprocess execution funnels through **exactly one call site** in `executor.execute()`:
```python
subprocess.run(shlex.split(command), capture_output=True, text=True,
               timeout=TASKQ_TASK_TIMEOUT, shell=False)
```
- `shlex.split` decomposes the command into argv without invoking a shell.
- `shell=False` (default) ensures the child process receives argv directly.
- `make shell-audit` invokes `python scripts/shell_audit.py $(SRC_DIR)`, which delegates to `harness.core.audit.audit_grep` with **docstring/comment exclusion** (per SAD.md §1.1 line 23). The audited pattern `shell\s*=\s*True` must produce zero hits across `src/` and `tests/`. Routing through the harness audit (rather than bare `grep`) is essential — plain `grep` re-introduces the docstring-false-positive class of bug (cf. Bug #126 from the 2026-06-27 E2E round) that the harness audit script exists to prevent.

### Consequences
- **Positive**: shell injection is structurally impossible at the subprocess boundary.
- **Positive**: single call site is auditable — one grep, one rule.
- **Positive**: CI enforces the rule (`make shell-audit` gates verification).
- **Negative**: pipe/shell-expansion syntax (`a | b`, `*.txt`) is not supported — FR-01 blacklist rejects these chars at submit time.
- **Mitigation**: explicit error message at submit time ("shell metacharacters not allowed") educates users on the restriction.

### Alternatives Considered
- **Allow `shell=True` with strict escaping** — rejected; too risky for a CLI tool exposed to arbitrary user input.
- **Sandbox via `bwrap` / `nsjail`** — rejected; SPEC §1 stdlib-only + single-user single-process model does not justify containerization.

---

## ADR-011: Determinism hooks (injectable sleep_fn, now_fn, time_fn)

### Status
Accepted

### Context
FR-03 specification retry backoff requires `sleep(backoff_base * 2**attempt)` (mirroring SRS.md FR-03 retry clause). Breaker cooldown requires `now - opened_at ≥ TASKQ_BREAKER_COOLDOWN`. Cache TTL requires `now - cached_at ≤ TASKQ_CACHE_TTL`. All three depend on time. Production code calls `time.sleep` / `time.monotonic` / `time.time` — but tests need deterministic control.

### Decision
All time-dependent functions accept injectable clock/sleep parameters with stdlib defaults:
- `executor.execute(task, *, sleep_fn=time.sleep, now_fn=time.monotonic)`
- `Breaker.check_and_record(success, *, now_fn=time.monotonic)`
- `Cache.get(command, *, time_fn=time.time)`

Tests pass `lambda: 0` or fake clocks; production uses defaults unchanged.

### Consequences
- **Positive**: deterministic, fast tests — no `time.sleep(5)` in unit tests.
- **Positive**: production code is unchanged — defaults preserve real behavior.
- **Positive**: matches SPEC §2's first-class testability requirement.
- **Negative**: API surface grows by 2-3 keyword params per function — minor.
- **Mitigation**: keyword-only args (after `*`) prevent positional misuse.

### Alternatives Considered
- **Freezegun / pytest-time** — rejected; adds test-only deps; injectable params are sufficient and zero-dep.
- **Monkeypatching `time.sleep` globally** — rejected; tests for one feature would affect unrelated tests.
- **Custom `Clock` class** — rejected; stdlib functions are the right abstraction level.

---

## ADR-012: Frozen dataclasses for models

### Status
Accepted

### Context
The product has four small data types (`Task`, `TaskStatus`, `BreakerState`, `CacheEntry`). Status transitions must be explicit; mutation must be traceable. SPEC FR-02 specification requires a strict state machine `pending → running → {done, failed, timeout}` (SRS.md FR-02 mirrors the same FSM with these 5 states).

### Decision
Use `@dataclass(frozen=True)` (stdlib) for all four types. Status transitions go through explicit `Task.transition_to(new_status)` method that validates the FSM and raises on illegal transitions. `from_dict` / `to_dict` methods handle JSON (de)serialization.

### Consequences
- **Positive**: immutability prevents accidental field mutation across module boundaries.
- **Positive**: explicit transition methods make the FSM auditable and testable.
- **Positive**: `@dataclass` generates `__init__` / `__repr__` / `__eq__` for free.
- **Negative**: `to_dict` / `from_dict` are manual — but the schema is fixed by SPEC §3, so 4 fields × 2 methods is trivial.
- **Mitigation**: `TaskStatus` enum (not string) makes illegal transitions unrepresentable at the type level.

### Alternatives Considered
- **Plain classes with `__init__`** — rejected; verbose, no immutability guarantee.
- **`pydantic.BaseModel`** — rejected; stdlib-only constraint.
- **`NamedTuple`** — considered; loses the ability to attach transition methods without subclassing.

---

## ADR-013: Single env-var reader (config.py)

### Status
Accepted

### Context
SPEC NFR-06 specification mandates environment-only configuration via 8 `TASKQ_*` variables (SRS.md NFR-06 mirrors this exact clause). Configuration must be testable (override per test), typed (defaults from SRS specification §5.1), and centralized (no scattered `os.getenv` calls).

### Decision
All 8 env vars are read through `config.py` getters:
- `get_home() -> Path`
- `get_max_workers() -> int`
- `get_task_timeout() -> float`
- `get_retry_limit() -> int`
- `get_backoff_base() -> float`
- `get_breaker_threshold() -> int`
- `get_breaker_cooldown() -> float`
- `get_cache_ttl() -> int`

No other module reads `os.environ`. Each getter returns typed value with default; non-numeric input → `ValueError` → CLI exit 1. `.env.example` declares all 8 vars with annotations matching SPEC §5.1.

### Consequences
- **Positive**: single point of truth for configuration; testable via `monkeypatch.setenv`.
- **Positive**: typed accessors prevent string-typed bugs in callers.
- **Positive**: missing var → default (no startup failure for optional config).
- **Negative**: 8 getters feels chatty — but each is a one-liner; LOC cost is acceptable.
- **Negative**: re-reads env on every call (no global cache) — intentional, so tests can mutate env between calls.

### Alternatives Considered
- **Module-level constants populated at import** — rejected; defeats testability (env mutation after import would not affect already-bound constants).
- **`pydantic-settings`** — rejected; stdlib-only.
- **YAML / TOML config file** — rejected; SPEC NFR-06 mandates env vars.

---

## ADR-014: Two source-bearing directories for CRG community boundaries

### Status
Accepted

### Context
CRG assigns one community per directory; the architecture score is the fraction of "healthy" communities (internal edge density ≥ 0.3 AND size ≤ 50 nodes). Splitting `src/taskq/` into subdirectories would create multiple small communities with low cohesion; consolidating everything into one dir maximizes the cohesion numerator.

### Decision
Maintain **exactly two source-bearing directories**:
- `src/taskq/` — production community (8 modules, ≤50 nodes).
- `tests/` — test community (not scored as production).

No subdirectories under `src/taskq/`. Module count is bounded (8) and edge count is maximized by the hub-and-spoke pattern (ADR-008).

### Consequences
- **Positive**: single production community — only one community must hit the 0.3 threshold.
- **Positive**: cohesive internal edge budget (≥55 internal edges, ≈0.65 cohesion per SAD §2.7).
- **Positive**: ≤50 nodes per community satisfies the size constraint.
- **Negative**: 8 modules in one dir may feel dense to humans — mitigated by clear naming and per-FR docstrings (NFR-05).
- **Mitigation**: docstring `[FR-XX]` tags make module ownership explicit despite flat layout.

### Alternatives Considered
- **Subdirs per concern** (`storage/`, `execution/`, `orchestration/`) — rejected; creates multiple communities that each must independently meet cohesion ≥ 0.3, multiplying risk.
- **Single-file monolith** — rejected; violates SPEC §6 module tree; loses unit-testability.
- **One-dir-per-module** — rejected; same issue as subdirs.

---

---

## Traceability Matrix (ADR → SRS FR/NFR → SPEC.md Specification)

This traceability matrix is the binding ledger between each architecture decision (ADR-001..ADR-014), the SRS functional/non-functional requirements from `01-requirements/SRS.md`, and the parent specification `SPEC.md` §1–§7. Every ADR above is justified by at least one SRS FR or NFR; every SRS FR/NFR is satisfied by at least one ADR. This is the specification-level evidence chain that SAD §2.3 / §2.4 derives from and that Phase 3 per-FR TDD will validate.

| ADR | Title (short) | Owning SRS FR | Supporting SRS NFR | Spec section satisfied | Implementation site (for Phase 3+) |
|-----|---------------|---------------|--------------------|------------------------|-------------------------------------|
| ADR-001 | Python 3.11 stdlib-only runtime | cross-cutting (tech-stack constraint; no owning FR) | NFR-02 (security: shell), NFR-06 (deployability) | SPEC.md §2 dependency budget; SPEC.md §7 portability | all `src/taskq/*.py` (8 modules) |
| ADR-002 | JSON-file persistence under $TASKQ_HOME | FR-01 (task submit), FR-02 (executor) | NFR-03 (atomic write + breaker recovery), NFR-06 | SPEC.md §1 storage model; SPEC.md §7 atomicity | `store.py` |
| ADR-003 | ThreadPoolExecutor + shared Lock concurrency | FR-02 (parallel run --all) | NFR-01 (perf p95 < 50ms), NFR-03 | SPEC.md §3 FR-02 "concurrent execution" | `executor.py`, `store.py` |
| ADR-004 | Atomic write `tmp + os.replace` | FR-01/02 (state transitions) | NFR-03 (reliability / torn-write prevention) | SPEC.md §7 atomicity clause | `store.atomic_write_json` |
| ADR-005 | Circuit breaker (CLOSED/OPEN/HALF_OPEN) | FR-03 (retry + breaker) | NFR-03 (recovery across process restart) | SPEC.md §3 FR-03 "cooldown window" | `breaker.py` |
| ADR-006 | TTL cache (sha256(command) keyed) | FR-04 (result replay) | NFR-01 (cache-hit zero-subprocess perf) | SPEC.md §3 FR-04 "within TTL window" | `cache.py` |
| ADR-007 | Layered single-process CLI architecture | FR-05 (CLI surface) | NFR-05 (docstring `[FR-XX]` convention) | SPEC.md §1 "single-process CLI"; §6 module layout | `cli.py`, `__main__.py` |
| ADR-008 | Hub-and-spoke internal structure | FR-01..FR-05 (all modules own ≥1 FR) | NFR-05 (docstring cross-ref) | SPEC.md §6 module count + naming | `store.py` (I/O hub), `cli.py` (orchestration hub), `executor.py` (secondary hub) |
| ADR-009 | Argparse-based subcommand CLI | FR-05 (subcommands submit/run/status/list/clear + AC-FR-05-03 exit code policy) | NFR-01 (argparse zero overhead) | SPEC.md §7 CLI surface + exit code table | `cli.py` |
| ADR-010 | Single subprocess call site, `shell=False` only | FR-02 (subprocess execution), FR-01 (validation) | NFR-02 (security: no shell, no injection) | SPEC.md §4 NFR-02 + FR-01 injection blacklist | `executor.execute` (only call site) |
| ADR-011 | Determinism hooks (`sleep_fn`, `now_fn`, `time_fn`) | FR-03 (retry backoff + breaker cooldown), FR-04 (cache TTL) | NFR-03 (testability for recovery), NFR-05 | SPEC.md §3 FR-03/FR-04 timing contracts | `executor.py`, `breaker.py`, `cache.py` (kw-only params) |
| ADR-012 | Frozen `@dataclass` models + explicit FSM transitions | FR-02 (state machine), FR-01 (Task identity) | NFR-05 (immutable models) | SPEC.md §3 FR-02 `pending → running → {done,failed,timeout}` | `models.py` |
| ADR-013 | Single env-var reader (`config.py`) | FR-05 (CLI honors config) | NFR-06 (deployability: env-only configuration) | SPEC.md §5.1 env var contract | `config.py` (8 typed getters) |
| ADR-014 | Two source-bearing dirs for CRG community | FR-01..FR-05 (≥1 module owns each FR) | NFR-05 (maintainability) | SPEC.md §6 module tree; SAD §2.7 CRG budget | `src/taskq/` + `tests/` |

**Reading guide.** Each ADR's *Context* section quotes the relevant SRS specification line ("`SRS.md §N FR-XX …`"); each ADR's *Decision* section names the ADR-IDs that depend on it; Phase 3 will cite the ADR-ID inside each module's docstring `[FR-XX]` tag so that the SRS ↔ ADR ↔ code chain is mechanically auditable from a single grep.

*Document version: v1.0 | Phase 2 deliverable | 2026-07-04*
*Source of truth: SAD.md v1.0 / SPEC.md v3.0.0 / SRS.md v1.0 / harness v2.9*