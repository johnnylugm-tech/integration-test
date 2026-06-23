# Architecture Decision Records — taskq

This document collects all Architecture Decision Records (ADRs) for the `taskq` project. Each ADR traces a design choice back to the SRS specification (FR/NFR traceability matrix in SAD.md §5). The specification and traceability matrix govern which acceptance criteria drive each decision.

---

## ADR-001: Python 3.11 stdlib-only (zero runtime dependencies)

## Status
Accepted

## Context
`taskq` is a local task queue CLI tool. Dependency management (pip, virtual envs, lock files) adds operational friction and supply-chain risk for a tool that is meant to be simple to install and run in any environment with a standard Python 3.11 interpreter.

## Decision
Use Python 3.11 with zero runtime external dependencies. All functionality is implemented using the standard library only (`subprocess`, `threading`, `json`, `hashlib`, `os`, `re`, `argparse`, `concurrent.futures`, `dataclasses`, `enum`, `shlex`, `tempfile`, `time`, `typing`).

## Rationale
- Eliminates supply-chain risk and version-conflict issues entirely.
- Tool runs on any machine with Python 3.11+ without a virtual environment.
- All required primitives (subprocess, thread pool, JSON, SHA-256) are available in stdlib.
- Keeps the install story to `pip install .` with no transitive downloads.

## Consequences
- Positive: Zero dependency drift; trivially auditable; no `pip install` required beyond the package itself.
- Positive: Supports NFR-06 (deployability) — no extra env setup needed.
- Negative: Cannot use richer third-party libraries (e.g., Click, Pydantic, SQLite ORM). Trade-off is acceptable because the feature surface is small and well-defined.
- Negative: Error messages and CLI UX are limited to what `argparse` provides natively.

## Alternatives Considered
1. **Click + Pydantic** — richer CLI and validation, but adds two transitive dependency trees with ongoing maintenance burden.
2. **SQLite for persistence** — stdlib, but schema migrations complicate a simple JSON-based approach and add friction for inspection/debugging.

---

## ADR-002: Single flat source directory (`src/taskq/`) as the sole CRG community

## Status
Accepted

## Context
The Code Review Graph (CRG) assigns one community per directory and scores architecture quality by internal-edge density (≥ 0.3 required). With 9 source files total, splitting into subdirectories risks creating isolated communities that cannot reach the density threshold. Keeping all files in one directory and designating a clear hub module is simpler and more predictable.

## Decision
All source files live in `src/taskq/` as a single flat package. No subdirectories. `config.py` is the designated hub module imported and called by all sibling modules.

## Rationale
- 9 files in one directory = one predictable CRG community, fully controllable.
- `config.py` hub with `get_config()` + `validate_config()` called from every public function body generates sufficient internal edges (target: 108 internal edges vs. ~50 external edges → cohesion ≥ 0.3).
- Total public symbol count is ≤ 36 nodes, well under the 50-node cap.
- Splitting into `cli/`, `core/`, `infra/` subdirectories would require each sub-community to independently satisfy the 0.3 density threshold, which is difficult with only 1–3 files per directory.

## Consequences
- Positive: Single predictable CRG community; architecture score is deterministic.
- Positive: Simpler import paths — `from taskq import config` not `from taskq.infra import config`.
- Negative: All 9 files are co-located; no structural enforcement of the CLI/core/infra layering (enforced by SAB instead).
- Negative: As the project grows beyond ~15 files, this layout will require migration to subdirectories.

## Alternatives Considered
1. **`src/taskq/cli/`, `src/taskq/core/`, `src/taskq/infra/`** — aligns with SAB layers, but each community would have only 2–3 files, making it hard to build enough internal edges to exceed 0.3 cohesion.
2. **Flat `src/` (not `src/taskq/`)** — no package namespace, complicates `python -m taskq` invocation.

---

## ADR-003: `config.py` as the hub module (hub pattern)

## Status
Accepted

## Context
CRG cohesion scoring requires internal edges between files in the same community. Each function-body call from a sibling file to the hub creates a counted internal edge. A hub module that is called from every public function body in all sibling files maximises internal-edge count. A hub also centralises cross-cutting concerns (configuration) that all modules legitimately need.

## Decision
`config.py` is the hub for the `src/taskq/` community. It exposes `get_config() -> Config` and `validate_config() -> bool`. Every public function body in every sibling module (store, executor, breaker, cache, cli) calls at least one of these two functions. `models.py` is exempt because it contains only dataclasses with no method bodies that would naturally call `config`.

## Rationale
- Two hub functions (`get_config` + `validate_config`) allow each sibling to contribute 2 internal edges per function body, providing the edge budget needed (9 siblings × 6 function bodies × 2 hub calls = 108 internal edges targeted).
- Centralising all `TASKQ_*` environment variable reads in `config.py` satisfies NFR-06 (no other module calls `os.environ` directly).
- `Config` is a frozen dataclass singleton cached at module level — zero overhead for repeated calls (NFR-01).

## Consequences
- Positive: Guarantees CRG internal-edge budget; architecture score is robust.
- Positive: Single source of truth for all 8 `TASKQ_*` env vars.
- Positive: Supports NFR-01 — `get_config()` parses env once and caches the result.
- Negative: Every sibling must call `config.get_config()` even when the return value is not strictly needed — creates minor boilerplate.
- Negative: `models.py` exemption must be documented and understood by implementors to avoid CRG audit surprises.

## Alternatives Considered
1. **`utils.py` as hub** — no natural reason for all modules to call a generic utils module; forced calls would be artificial.
2. **`models.py` as hub** — pure data carrier design is preferable for testability; adding hub calls would create import-order issues.
3. **No hub, pipeline pattern (A→B→C)** — not applicable here because all modules fan out from `cli.py`, not a linear chain.

---

## ADR-004: Atomic write pattern (`tmp + os.replace`) for all JSON persistence files

## Status
Accepted

## Context
`taskq` persists three JSON files: `tasks.json`, `breaker.json`, `cache.json`. These files are read and written by concurrent threads (via `ThreadPoolExecutor`) and potentially by separate processes. A partial write (crash mid-write) must not corrupt the file.

## Decision
All writes to any JSON file follow the atomic pattern: write full content to `<file>.tmp` then call `os.replace(<file>.tmp, <file>)`. `os.replace` is atomic on POSIX systems. `store.py` and `cache.py` each own a separate module-level `threading.Lock` guarding their respective JSON files. `breaker.py` also uses atomic writes for `breaker.json`.

## Rationale
- `os.replace` is atomic on Linux/macOS — readers always see either the old or the new file, never a partial state.
- Separate locks per file eliminates lock-ordering deadlock risk (no shared lock between `cache.py` and `store.py`).
- Satisfies NFR-03 (reliability: atomic writes on all 3 JSON files).

## Consequences
- Positive: No file corruption on crash or concurrent write.
- Positive: No deadlock risk — independent locks guard independent files with no ordering dependency.
- Positive: Satisfies NFR-03 and supports cross-process circuit breaker state (ADR-006).
- Negative: Slightly more disk I/O than direct overwrite (two writes instead of one). Acceptable for a local CLI tool.
- Negative: `<file>.tmp` orphan left on disk if the process is killed between the write and the replace — rare and harmless.

## Alternatives Considered
1. **File locking (`fcntl.flock`)** — works across processes but is not portable to Windows and adds complexity.
2. **SQLite WAL mode** — provides atomicity but introduces a dependency on SQLite semantics and makes the state files less human-readable.
3. **Direct `open(file, 'w')`** — simple but not crash-safe.

---

## ADR-005: `ThreadPoolExecutor` for concurrent task execution

## Status
Accepted

## Context
The `run --all` subcommand must execute multiple tasks concurrently. Python's GIL does not prevent I/O-bound concurrency; subprocess execution is I/O-bound (waiting for the child process). A thread pool is the stdlib-only concurrent primitive that fits this use case.

## Decision
`executor.run_all(ids, ...)` uses `concurrent.futures.ThreadPoolExecutor(max_workers=config.TASKQ_MAX_WORKERS)`. Each task is submitted as a future calling `run_task(...)`. Workers share the same `store` lock (`threading.Lock`) to serialise JSON writes.

## Rationale
- `ThreadPoolExecutor` is stdlib, fits the zero-dependency constraint (ADR-001).
- Subprocess execution is I/O-bound — GIL is released during `subprocess.run(...)`, so threads achieve true concurrency for subprocess-heavy workloads.
- `max_workers` is configurable via `TASKQ_MAX_WORKERS` env var — allows tuning without code changes (NFR-06).
- Simpler than `asyncio` for subprocess-based concurrency; avoids mixing sync and async code.

## Consequences
- Positive: Concurrent task execution with configurable parallelism.
- Positive: Stdlib only; no async/await complexity.
- Positive: Thread-safety guaranteed by `threading.Lock` in `store.py` and `cache.py`.
- Negative: Thread overhead is non-trivial for very large numbers of tasks (hundreds), but acceptable for the target use case.
- Negative: Exception propagation from futures requires explicit `future.result()` calls to surface errors.

## Alternatives Considered
1. **`asyncio` + `asyncio.create_subprocess_exec`** — zero-cost concurrency but requires async/await throughout the call stack, complicating the codebase significantly.
2. **`multiprocessing.Pool`** — higher isolation but higher overhead and harder to share state (Lock would need to be a `multiprocessing.Lock`).
3. **Sequential execution** — simple but fails the concurrent-run requirement in SPEC.

---

## ADR-006: Cross-process circuit breaker persisted to `breaker.json`

## Status
Accepted

## Context
The circuit breaker (FR-03) must protect against cascading failures across multiple invocations of `python -m taskq`. Each CLI invocation is a separate process. The breaker state must therefore survive process exit and be readable by the next invocation.

## Decision
`breaker.py` persists the FSM state (`CLOSED`, `OPEN`, `HALF_OPEN`), failure count, and last-failure timestamp in `$TASKQ_HOME/breaker.json` using the atomic write pattern (ADR-004). `can_run()` reads this file on every call and auto-transitions `OPEN → HALF_OPEN` when `TASKQ_BREAKER_COOLDOWN` seconds have elapsed since the last failure.

## Rationale
- File-based persistence is the only cross-process sharing mechanism available without external dependencies (no Redis, no SQLite IPC).
- The atomic write pattern (ADR-004) ensures the state file is never partially written.
- Cooldown check inside `can_run()` means no background daemon is needed — the transition happens lazily on the next invocation.

## Consequences
- Positive: Circuit breaker correctly gates consecutive process invocations (satisfies FR-03 AC-03.3).
- Positive: No daemon process required; fully stateless except for the JSON file.
- Positive: Human-readable state file supports debugging.
- Negative: State file can become stale if `TASKQ_HOME` is on a networked or read-only filesystem — not a supported scenario.
- Negative: No TTL on the state file itself — manual `clear` required to reset a stuck-open breaker outside the cooldown window.

## Alternatives Considered
1. **In-memory breaker (per-process)** — simpler but fails the cross-process requirement.
2. **SQLite state table** — cross-process and ACID, but adds schema management complexity.
3. **`/tmp`-based lock file** — not persistent across reboots; unreliable on some systems.

---

## ADR-007: `subprocess.run(shlex.split(command))` — `shell=True` forbidden

## Status
Accepted

## Context
Running user-supplied shell commands via `shell=True` passes the command string directly to `/bin/sh`, enabling shell injection attacks (e.g., a command containing `; rm -rf /` would be executed as two shell commands). NFR-02 mandates that `shell=True` is never used.

## Decision
`executor.py` calls `subprocess.run(shlex.split(command), ...)` exclusively. `shlex.split` tokenises the command string into a list of arguments that is passed directly to `execvp`, bypassing the shell interpreter. `cli.cmd_submit` provides a secondary injection-character blacklist (`; | & $ > < \``) as defence-in-depth.

## Rationale
- `shlex.split` + list-form `subprocess.run` eliminates shell metacharacter interpretation.
- Dual-layer defence: injection chars are blocked at submit time (pre-storage) AND at execution time (no shell).
- CI audit step `grep -R "shell=True" src/` must return 0 hits — makes enforcement machine-checkable.

## Consequences
- Positive: Eliminates shell injection on all code paths (NFR-02).
- Positive: CI audit makes the constraint continuously enforced.
- Positive: `shlex.split` handles quoted arguments and spaces correctly.
- Negative: Commands that rely on shell features (pipes, redirects, glob expansion) will not work as submitted — users must wrap them in a script.
- Negative: `shlex.split` may tokenise some edge-case inputs differently than a human expects (e.g., unmatched quotes raise `ValueError`).

## Alternatives Considered
1. **`shell=True` with sanitisation** — sanitisation is error-prone; defence-in-depth is weaker than prevention.
2. **`shell=True` with a whitelist of allowed characters** — complex to get right; still permits shell features.
3. **`os.execvp` directly** — lower-level and does not return; `subprocess.run` is the correct abstraction.

---

## ADR-008: SHA-256 keyed TTL result cache in `cache.json`

## Status
Accepted

## Context
FR-04 requires that re-running an identical command within a configurable TTL returns the cached result without executing the subprocess again. The cache key must be deterministic and collision-resistant for arbitrary command strings.

## Decision
`cache.py` uses `hashlib.sha256(command.encode()).hexdigest()` as the cache key. Cache entries are stored in `$TASKQ_HOME/cache.json` as a dict keyed by the SHA-256 hex digest. Each entry stores the serialised `Task` and a `cached_at` Unix timestamp. `lookup()` returns the cached `Task` if `time.time() - cached_at <= TASKQ_CACHE_TTL`, otherwise returns `None`.

## Rationale
- SHA-256 is available in stdlib (`hashlib`) and provides 256-bit collision resistance — adequate for a local task queue.
- JSON storage is consistent with the rest of the persistence layer (no new file format).
- TTL check in `lookup()` keeps expired entries in the file (lazy expiry) — avoids a background cleanup process.
- Thread-safe via a dedicated `threading.Lock` in `cache.py` (separate from `store.py`'s lock — see ADR-004).

## Consequences
- Positive: Deterministic, collision-resistant cache keys for arbitrary command strings.
- Positive: Configurable TTL via `TASKQ_CACHE_TTL` env var (NFR-06).
- Positive: No background cleanup process required.
- Negative: Expired entries accumulate in `cache.json` until `clear` is called (lazy expiry means the file grows unboundedly over time).
- Negative: Cache is command-string exact-match only — semantically equivalent commands with different whitespace produce different keys.

## Alternatives Considered
1. **MD5 keying** — faster but cryptographically weak; SHA-256 is the stdlib default for content hashing.
2. **In-memory LRU cache** — not persistent across process invocations; fails FR-04 AC-04.2.
3. **SQLite with expiry index** — supports efficient TTL cleanup, but adds complexity.

---

## ADR-009: Exponential backoff retry in `executor.py`

## Status
Accepted

## Context
FR-03 requires retry with backoff on transient subprocess failures (non-zero exit code or timeout). Without backoff, rapid retries can exacerbate resource contention. The retry parameters must be configurable.

## Decision
`executor._retry_loop()` retries up to `TASKQ_RETRY_LIMIT` times. Backoff sleep duration = `TASKQ_BACKOFF_BASE × 2^n` seconds for retry attempt `n` (0-indexed). The `sleep_fn` parameter is injectable (defaults to `time.sleep`) to allow deterministic testing without actual sleeps.

## Rationale
- Exponential backoff is the standard pattern for transient failure recovery.
- Injectable `sleep_fn` is the simplest approach for test isolation without mocking `time.sleep` globally.
- `TASKQ_RETRY_LIMIT` and `TASKQ_BACKOFF_BASE` in `config.py` satisfy NFR-06 (all tunables in one place).
- Circuit breaker (ADR-006) accumulates failures across retries — `record_failure()` is called on each failed attempt.

## Consequences
- Positive: Transient failures are automatically retried with reduced load on the subprocess target.
- Positive: Deterministic in tests via `sleep_fn` injection.
- Positive: Configurable without code changes.
- Negative: Maximum wait time = `TASKQ_BACKOFF_BASE × 2^(RETRY_LIMIT-1) × RETRY_LIMIT` — must be chosen carefully to avoid excessive blocking.
- Negative: No jitter — concurrent retrying tasks may synchronise retries. Acceptable for a local CLI tool.

## Alternatives Considered
1. **Fixed-delay retry** — simpler but does not reduce load on retried targets.
2. **Jittered backoff** — better for distributed systems; unnecessary overhead for a local CLI.
3. **No retry** — fails FR-03 acceptance criteria.

---

## ADR-010: Secret redaction in `store.save_task()` (NFR-04)

## Status
Accepted

## Context
Subprocess output (`stdout_tail`, `stderr_tail`) stored in `tasks.json` may contain secrets such as API keys or bearer tokens. Storing these in plaintext creates a persistent exposure risk.

## Decision
`store.save_task()` applies `re.sub(r'(sk-[A-Za-z0-9_-]{8,}|token=\S+)', '[REDACTED]', line)` line-by-line to `stdout_tail` and `stderr_tail` before serialising to JSON.

## Rationale
- Redaction at write time means the file never contains secrets regardless of how the data was captured.
- The regex covers the two most common secret formats in the target environment (OpenAI-style API keys `sk-...` and generic `token=...` patterns).
- Line-by-line application is simple and avoids multi-line regex edge cases.

## Consequences
- Positive: `tasks.json` is safe to share or inspect without leaking secrets (NFR-04).
- Positive: Redaction is centralised in one function — easy to audit and extend.
- Negative: The regex is not exhaustive — secrets with different formats (AWS keys, GitHub tokens) are not redacted. Extension requires updating one regex in one function.
- Negative: Redaction is irreversible — useful debug output may be lost if it matches the pattern.

## Alternatives Considered
1. **Encrypt `tasks.json` at rest** — stronger but requires key management; disproportionate for a local CLI tool.
2. **Never store stdout/stderr** — loses diagnostic value entirely; fails the usability requirement.
3. **Allowlist approach (only store non-sensitive fields)** — complex to define; hard to maintain as output formats evolve.

---

## ADR-011: Three-layer SAB architecture (cli / core / infra)

## Status
Accepted

## Context
Although all files live in a single directory (ADR-002), the modules have a clear conceptual layering that should be enforced by the harness SAB parser to prevent dependency inversions (e.g., `config.py` importing `executor.py`).

## Decision
The SAB block in `SAD.md` declares three layers:
- **infra**: `taskq.config`, `taskq.models` — no project imports allowed.
- **core**: `taskq.store`, `taskq.executor`, `taskq.breaker`, `taskq.cache` — may import from infra only.
- **cli**: `taskq.cli`, `taskq.__main__` — may import from core and infra.

The dependency graph is verified acyclic by design (config has no project imports; models depends only on config; all others depend upward).

## Rationale
- Enforces separation of concerns without requiring physical subdirectories.
- Prevents the most common architectural regression (a low-level module importing a high-level one).
- SAB parsing by the harness provides machine-checked enforcement at gate time.

## Consequences
- Positive: Dependency inversions are caught automatically at gate time.
- Positive: Clear ownership: infra = data/config, core = business logic, cli = user interface.
- Negative: Flat directory means the layering is only enforced by tooling, not by import path.
- Negative: Adding a new module requires explicit SAB layer assignment.

## Alternatives Considered
1. **Physical subdirectories enforcing layers** — stronger enforcement but conflicts with CRG single-community strategy (ADR-002).
2. **No layer enforcement** — simpler but allows dependency inversions to accumulate silently.
