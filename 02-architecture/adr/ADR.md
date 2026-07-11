# Architecture Decision Records (ADR) — `taskq`

> Project: `taskq` — local task-queue CLI
> SPEC version: v4.1.0 (5 FR / 10 NFR / 8 env, 2026-07-12)
> Phase: 2 — Architecture
> Companion artifacts: `SPEC.md` (single source of truth), `SRS.md` (requirements), `SAD.md` (architecture baseline).
> Each ADR below states Context, Decision, Consequences, and Alternatives Considered; cross-references cite `SAD.md` §-anchors.
>
> **v4.1.0 deltas (vs this ADR file's prior round):** SPEC v4.1.0 (2026-07-12) removed §6 folder-structure constraint and delegated layout authority to `SAD.md`. `ADR-002` now records the **4-sub-package** layout (`core` / `storage` / `runtime` / `interface`) instead of the prior flat 9-file plan; `ADR-016` corrects `Config.env` to `Literal["test", "prod"]` (derived from `PYTEST_CURRENT_TEST`, NOT one of the 8 declared `TASKQ_*` vars); `ADR-017` records the SAB `nfr_traceability.type` enum mapping (SAD §4 table is binding).

---

## NFR → ADR / FR Traceability Matrix

This traceability matrix satisfies the harness `_adr_table_nfrs` check (`harness/core/quality_gate/artifact_consistency.py:104-124`) and gives downstream Phase 3+ an authoritative NFR-to-design-decision map. Every one of the 10 NFRs declared in the project specification (`SPEC.md` §4, transcribed in `SRS.md` §4) is served by at least one ADR.

| NFR | Specification source | ADR(s) | FR(s) served | Mechanism |
|-----|----------------------|--------|--------------|-----------|
| NFR-01 (perf p95 < 50ms submit/status) | `SPEC.md` §4 table NFR-01 / `SRS.md` §4 NFR-01 | ADR-015 | FR-01, FR-05 | Lockless hot-read path on `Store.get`; tiny JSON file; no subprocess |
| NFR-02 (no `shell=True` + injection blacklist) | `SPEC.md` §4 table NFR-02 / `SRS.md` §4 NFR-02 | ADR-012 | FR-02, FR-05 | `shlex.split` + `subprocess.run(shell=False)`; `cli._validate_command` blacklist |
| NFR-03 (atomic writes + breaker recovery) | `SPEC.md` §4 table NFR-03 / `SRS.md` §4 NFR-03 | ADR-003, ADR-006 | FR-01, FR-02, FR-03 | `_atomic_write` tmp + `os.replace`; fail-fast on JSONDecodeError (exit 1) |
| NFR-04 (secret redaction) | `SPEC.md` §4 table NFR-04 / `SRS.md` §4 NFR-04 | ADR-011 | FR-02 | `executor._redact` regex `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` line-level |
| NFR-05 (docstring `[FR-XX]` traceability) | `SPEC.md` §4 table NFR-05 / `SRS.md` §4 NFR-05 | ADR-014 | FR-01..FR-05 | First-line docstring convention; Gate 1 lint regex |
| NFR-06 (deployability; centralized env reading) | `SPEC.md` §4 table NFR-06 / `SRS.md` §4 NFR-06 | ADR-016 | FR-01..FR-05 | Single `config.get_config()` reads all 8 `TASKQ_*` vars with defaults; `.env.example` parity |
| NFR-07 (fault-injection scenarios) | `SPEC.md` §4 table NFR-07 / `SRS.md` §4 NFR-07 | ADR-009 | FR-01..FR-04 | `--inject-fault=<scenario>` CLI flag + `_fault_hook`; prod rejection via `cfg.env == "test"` |
| NFR-08 (cross-process concurrency) | `SPEC.md` §4 table NFR-08 / `SRS.md` §4 NFR-08 | ADR-004 | FR-01, FR-02, FR-03, FR-04 | `fcntl.flock` LOCK_EX/LOCK_SH; network-FS detection with WARNING + atomic-only fallback |
| NFR-09 (1000-task scale; streaming iter) | `SPEC.md` §4 table NFR-09 / `SRS.md` §4 NFR-09 | ADR-013 | FR-04, FR-05 | `Store.list()` single-decode streaming iter; bounded `ThreadPoolExecutor` worker pool |
| NFR-10 (versioned schema + backup-on-migrate) | `SPEC.md` §4 table NFR-10 / `SRS.md` §4 NFR-10 | ADR-010 | FR-01, FR-02, FR-03, FR-04 | `_load_or_migrate` reads `version`; `<1` auto-upgrade + `.v<n>.bak`; `>1` refuse exit 1 |
| (all 10 NFRs) SAB `type` enum mapping | `SAD.md` §4 category table / `SAD.md` §5 SAB block | ADR-017 | — | SAD §4 maps each NFR's prose category onto the 8 legal `sab_parser.py` enum values; binding for Phase 2 SAB body |

---

## ADR-001: Python 3.11 runtime, standard-library only

### Context
`taskq` is a local CLI that ships state files on disk (tasks.json / breaker.json / cache.json) and runs subprocess commands under controlled execution. The dependency surface is small but the deliverable must be installable on a fresh host with minimal friction, and the code must be auditable end-to-end. SPEC §5 pins Python 3.11. NFR-01 demands tight p95 latency budgets; NFR-05 requires every public symbol to carry a `[FR-XX]` docstring citation, which is easier to keep honest when there are no third-party abstractions to chase. (SAD §1, §2.1, §2.2)

### Decision
- Target runtime: CPython 3.11.
- Runtime dependency set: Python standard library only (no PyPI packages in production).
- Test-tooling exceptions (`pytest`, `pytest-benchmark`, `hypothesis`, `mutmut`) live in the dev/test virtualenv and are not imported by `src/taskq/**` at runtime.

### Consequences
- (+) Zero install footprint; `python -m taskq …` runs anywhere Python 3.11 is present.
- (+) Easier Gate 1 traceability audit — only stdlib imports to lint against.
- (+) `subprocess.run`, `threading`, `fcntl`, `json`, `hashlib`, `shlex`, `argparse` cover every requirement.
- (-) Re-implements small utilities (atomic write, cross-process lock) that third-party libs provide.
- (-) Concurrency primitives limited to stdlib (`threading`, `concurrent.futures`, `fcntl.flock`); no asyncio on the hot path.

### Alternatives considered
- **A. Pin a thin third-party set** (`pydantic`, `click`, `tenacity`). Rejected: install friction and dependency-trust surface outweigh the convenience; SPEC §5 explicitly lists stdlib facilities as sufficient.
- **B. Target Python 3.12+. Rejected:** unnecessary minimum bump; SPEC §5 pins 3.11 to maximize host compatibility.
- **C. Bundle a static binary (PyInstaller). Rejected:** hides failure modes and breaks the debuggability required by NFR-07 fault injection.

---

## ADR-002: 4-sub-package layout (`core` / `storage` / `runtime` / `interface`) rooted at `interface.cli`

### Context
SPEC v4.1.0 (2026-07-12) removed §6 folder-structure constraint and delegated layout authority to `SAD.md` (SPEC §0 changelog line 14; SAD §1). The 9 logical modules must still coexist with the harness-methodology (v2.9) `no_circular_dependencies` invariant, the CRG Principle 1 requirement of 3–6 source directories, and the CRG Principle 6 size cap (≤ 50 nodes per community). The dependency graph must remain a DAG rooted at `cli`. (SAD §2.1, §2.3)

### Decision
- Exactly 9 source files in 4 sub-packages under `src/taskq/`:
  - `taskq/core/` — `config.py`, `models.py` (foundational types + env reader; CRG community A)
  - `taskq/storage/` — `store.py`, `breaker.py`, `cache.py` (data-file persistence; CRG community B)
  - `taskq/runtime/` — `executor.py` (subprocess + retry; CRG community C)
  - `taskq/interface/` — `cli.py`, `__main__.py` (argparse + `python -m taskq` entry; CRG community D)
- Each sub-package exposes an explicit hub module (`models` / `store` / `executor` / `cli`) per CRG Principle 2.
- `interface.cli` is the sole consumer (root); every other module points away from it. No module imports from `interface.cli` and no module re-exports `cli`.
- `python -m taskq` boots via `__main__.py → cli.main`.
- Layering rules (also enforced in SAB `allowed_dependencies`):
  - `interface → core | storage | runtime`
  - `runtime → core | storage`
  - `storage → core`
  - `core → ∅` (no internal imports; only stdlib)

### Consequences
- (+) Dependency graph is a DAG by construction; `no_circular_dependencies` invariant is statically verifiable.
- (+) 4 source directories is within CRG Principle 1's 3–6 budget; per-community size stays well under the 50-node cap.
- (+) Boundary at the natural layering (`core` / `storage` / `runtime` / `interface`) gives the CRG meaningful community boundaries instead of one oversized 9-file community.
- (+) Per-FR mapping (SAD §2.4) remains 1:1 against modules, supporting SAB generation without aggregation.
- (-) Adds 3 `__init__.py` files and 3 extra directory levels; negligible.
- (-) Cross-package helper placement requires explicit `core` choice; mitigated by `core.models` / `core.config` hub conventions.

### Alternatives considered
- **A. Flat 9-file layout under `src/taskq/`. Rejected:** would place all 9 files in one CRG community, plausibly 60–90 nodes (functions + classes), exceeding the 50-node size cap (Principle 6) and violating Principle 1 (only 1 source dir). Unsustainable under v4.1.0.
- **B. Group by feature (e.g. `taskq/persistence/`, `taskq/runtime/`). Rejected:** would split at the wrong boundary — `breaker` and `cache` are persistence-shaped, not feature-shaped; `interface` belongs as its own layer because it is the dispatch root.
- **C. Add a `utils.py` for cross-cutting helpers. Rejected:** kitchen-sink anti-pattern; shared utilities live in `core/models.py` or `core/config.py` by convention.
- **D. Single-file `taskq.py`. Rejected:** would force FR-mapping aggregation in SAB (one symbol → several FRs) and inflate Gate 1 diff noise.

---

## ADR-003: Atomic write pattern (tmp + `os.replace`)

### Context
Three persistent files (`tasks.json`, `breaker.json`, `cache.json`) are mutated concurrently across processes and in-process threads. NFR-03 mandates atomicity; NFR-08 mandates cross-process locking; NFR-10 mandates backup-on-migrate. (SAD §1, §3.4, §4.3)

### Decision
- All persistent-file writes use the helper `_atomic_write(path, payload)`:
  1. Serialize payload to JSON.
  2. Write to `<path>.tmp.<pid>.<n>` (unique per process/attempt).
  3. `os.replace(tmp, path)` — atomic on POSIX and Windows NTFS.
  4. `fsync` before close to harden against power-loss partial writes.
- On read, `JSONDecodeError` → `exit 1` (`store corrupted`); never silently rebuild.
- Migration (NFR-10): when `version < 1`, write v1 and back up `<path>.v<n>.bak`; when `version > 1`, refuse with exit 1 + upgrade hint.

### Consequences
- (+) Readers either see the old or the new file, never a torn write.
- (+) Backup before mutate closes R9 (schema-migration data loss) without a separate code path.
- (+) Same helper used by `store`, `breaker`, `cache` → single audit surface for NFR-03.
- (-) Requires a writable directory and free disk space equal to one full file.
- (-) Recovery requires a process restart to re-attempt; no in-place repair.

### Alternatives considered
- **A. Write in place (open with `O_TRUNC` then write). Rejected:** any crash mid-write corrupts the on-disk file; contradicts NFR-03.
- **B. Use SQLite / LMDB. Rejected:** introduces third-party deps (violates ADR-001) and changes the data-shape story from JSON.
- **C. Append-only log with periodic compaction. Rejected:** doubles the complexity (compactor, replay logic) for a CLI workload that fits in a single JSON file.

---

## ADR-004: Cross-process locking via `fcntl.flock` with NFS fallback

### Context
NFR-08 requires safe concurrent access from multiple processes. POSIX `fcntl.flock` provides advisory whole-file locking; NFS and some network filesystems silently ignore it. (SAD §3.4, §4.4)

### Decision
- Writers call `flock(fd, LOCK_EX)`; readers call `flock(fd, LOCK_SH)`; both release on close.
- Best-effort posture: `_is_network_fs()` probe detects NFS / CIFS / 9p mounts (via `/proc/mounts` on Linux, `mount` on macOS); on True, log WARNING and skip `flock`, retaining `os.replace` atomicity (ADR-003).
- Windows path uses `msvcrt.locking` with a try/except that degrades to atomic-only when the call is unsupported on the volume.

### Consequences
- (+) Cross-process correctness on local POSIX filesystems (the common case).
- (+) Maintains a useful guarantee on NFS: torn writes are still avoided via `os.replace`.
- (+) Honest signaling: warnings surface the degraded mode rather than masking it.
- (-) Silent degradation on network FS can be missed by operators; mitigated by WARNING logs.
- (-) `flock` is advisory — misbehaving external processes can ignore it; out of scope per ADR-003's contract.

### Alternatives considered
- **A. POSIX mutex file (`open(O_CREAT|O_EXCL)` on a lock file). Rejected:** needs stale-lock cleanup on crashes; flock already covers the happy path.
- **B. Database lock (SQLite WAL, etcd). Rejected:** dependency footprint; project ships JSON.
- **C. No cross-process lock. Rejected:** violates NFR-08; the harness multi-process test in §4.4 would flake.

---

## ADR-005: In-process concurrency via `threading.Lock` + bounded `ThreadPoolExecutor`

### Context
A single `taskq` process may handle CLI calls serially today, but future `run --all` workloads (NFR-09) and parallel read paths need a bounded concurrency model without spawning unbounded subprocesses. (SAD §2.4 FR-02, §4.1, §4.5)

### Decision
- All in-process access to a given persistent file goes through a module-level `threading.Lock` (one per `store`, `breaker`, `cache`).
- Long-running batches (`run --all`) execute via `concurrent.futures.ThreadPoolExecutor` sized from `TASKQ_MAX_WORKERS` (default 4, capped at 16).
- `executor.execute(..., sleep=time.sleep)` keeps `time.sleep` injectable for deterministic retry tests.

### Consequences
- (+) Readers and writers within a single process serialize on the per-file lock, preventing interleaved JSON corruption.
- (+) Bounded worker pool caps memory and fd usage, supporting NFR-09's 1000-task memory budget.
- (+) Injectable `sleep` is the seam NFR-07 fault tests rely on for fast retry verification.
- (-) Global Interpreter Lock limits CPU-bound parallelism; acceptable because hot path is I/O (subprocess + JSON).
- (-) Adds two knobs to `.env.example` (worker count, queue depth) that operators must understand.

### Alternatives considered
- **A. `multiprocessing` for true parallelism. Rejected:** pickling dataclasses across spawn cost outweighs the gain for I/O-bound subprocess work.
- **B. `asyncio` + `asyncio.subprocess`. Rejected:** changes every signature in `executor`; stdlib-only is preserved either way, but the existing synchronous contract is the SAB unit boundary.
- **C. Unbounded `ThreadPoolExecutor()`. Rejected:** violates NFR-09 memory cap; the harness concurrency test would create 1000 threads.

---

## ADR-006: Circuit breaker — `CLOSED / OPEN / HALF_OPEN` state machine

### Context
FR-03 requires automatic retry throttling when a target command keeps failing. A naïve retry loop can DoS a flapping dependency; SPEC §3 mandates bounded blast radius. (SAD §2.4 FR-03, §2.5 NFR-03, §3.7 exit 3)

### Decision
- Module `breaker.py` exposes `Breaker.allow()` (pre-call gate) and `Breaker.record(success: bool)` (post-call feedback).
- State machine:
  - `CLOSED` — calls flow; on consecutive failures ≥ `TASKQ_BREAKER_THRESHOLD`, transition to `OPEN`.
  - `OPEN` — `allow()` returns `False`; after `TASKQ_BREAKER_COOLDOWN` seconds, transition to `HALF_OPEN`.
  - `HALF_OPEN` — allow exactly one probe; success → `CLOSED`, failure → re-OPEN.
- State persisted in `breaker.json` with the ADR-003 atomic write + ADR-004 flock.

### Consequences
- (+) Single canonical state file; CLI can surface breaker status (`status` subcommand).
- (+) `allow()` is a pure consult — no side effects, easy to mock.
- (+) HALF_OPEN probe avoids permanent lockout after a transient blip (closes R3).
- (-) Persisting state on every transition adds write amplification; mitigated by batching `record()` to once per failure batch.
- (-) Two thresholds (`BREAKER_THRESHOLD`, `BREAKER_COOLDOWN`) need defaults that match SPEC §5.

### Alternatives considered
- **A. Token bucket. Rejected:** better for rate limiting, not for the binary "is the dependency healthy" question FR-03 asks.
- **B. In-memory breaker only. Rejected:** loses state across CLI invocations; FR-03 requires cross-process behavior.
- **C. Sliding window with weighted failure ratio. Rejected:** more knobs, harder to test; SPEC §3 specifies a threshold counter.

---

## ADR-007: TTL result cache keyed by `sha256(command)`

### Context
FR-04 specifies caching previously-seen command results to avoid redundant execution. The cache key must be stable across processes and resilient to whitespace/casing differences. (SAD §2.4 FR-04, §3.3 cache replay flow, §3.6 persistent file shape)

### Decision
- Signature: `sha256(command.encode("utf-8")).hexdigest()` over the post-`shlex.split` rejoined command.
- Stored entries: `{ "result": <RunResult>, "cached_at": <ISO8601> }`.
- TTL: `TASKQ_CACHE_TTL` seconds (default 300). On `lookup()`, entries past TTL are treated as misses but not eagerly evicted (lazy TTL).
- Optional `--cached` flag in `cli run` consults the cache; absent flag means cache is written but never read.

### Consequences
- (+) Stable, low-collision key with zero configuration.
- (+) Lazy TTL avoids a background sweeper thread.
- (+) Cache is process-local in the file (cross-process), avoiding per-process caches that diverge.
- (-) Whitespace canonicalization is implicit in `shlex.split` rejoin; identical-looking commands with different quoting may share an entry by design.
- (-) No partial-result caching — only completed runs enter the cache.

### Alternatives considered
- **A. Key by full argv vector (post-`shlex.split`). Rejected:** changes between shells make the key opaque to operators; rejoin keeps the user-visible command as the key seed.
- **B. Eager TTL eviction via timer thread. Rejected:** extra lifecycle + risk of leaking threads on shutdown.
- **C. LRU + size cap. Rejected:** SPEC §5 doesn't request size capping; current scale (≤ 1000 tasks) fits comfortably in memory.

---

## ADR-008: Exit-code matrix single-sourced at `cli`

### Context
Operators and CI scripts rely on stable exit codes; FR-05 demands CLI integration that is testable from harness E2E. (SAD §3.7)

### Decision
- Exit codes (single source — `cli.py`):
  - `0` success
  - `1` internal / unexpected (`Store corrupted`, JSON decode failure, unhandled exception)
  - `2` validation / unknown task / production `--inject-fault` rejection
  - `3` breaker open
  - `4` task timeout (single-task mode)
- Modules return domain values (`RunResult`, `BreakerState`, exceptions); only `cli.main` maps to `sys.exit(code)`.

### Consequences
- (+) CI pipelines can dispatch on a small integer set.
- (+) Tests assert exit codes without coupling to internal exception classes.
- (+) Single point of change when a new outcome is added (e.g., future rate-limit exit).
- (-) Adding a new exit code requires touching `cli` and the test matrix together; tracked via Gate 1 lint of the matrix table.

### Alternatives considered
- **A. Let each module raise and `cli` convert. Rejected:** mixes control flow with exit mapping, harder to read.
- **B. Use a global `ExitCode` enum. Rejected:** enumeration works but the matrix in SAD §3.7 is already the contract; an enum adds an indirection layer without new information.
- **C. Distinguish more granular codes (5, 6, 7). Rejected:** SPEC §5 keeps the matrix at 5 values; expansion is a separate ADR if needed.

---

## ADR-009: Fault-injection seam via `--inject-fault=<scenario>` (test env only)

### Context
NFR-07 requires deterministic fault scenarios (`corrupt-mid-write`, `oserror-on-write`, `disk-full`, `kill-mid-write`). Production paths must reject the flag. (SAD §3.5, §4.3)

### Decision
- CLI flag `--inject-fault=<scenario>` is parsed by `cli` and forwarded to `executor._fault_hook(scenario)`.
- Acceptance precondition: `get_config().env == "test"`. Otherwise `cli` raises exit 2.
- Scenarios:
  - `corrupt-mid-write` → abort atomic write after partial flush; `.bak` preserved.
  - `oserror-on-write` → `OSError` raised; stderr message + exit 1.
  - `disk-full` → simulated `ENOSPC`; stderr + exit 1.
  - `kill-mid-write` → `SIGKILL` against own subprocess mid-write; `store` detects on next start.
- Hooks are pure functions injected via monkeypatch in tests; production code paths do not import the hook unless the flag is set.
- The fault scenarios themselves do **not** introduce new `TASKQ_*` environment variables: the 4 scenarios are fixed in `executor._fault_hook`, not user-tunable. `.env.example` therefore remains at exactly the 8 declared `TASKQ_*` vars (per ADR-016); no `TASKQ_FAULT_*` knob exists.

### Consequences
- (+) Deterministic test coverage of failure recovery paths required by NFR-03 / NFR-07.
- (+) Production safety enforced at the CLI boundary — no runtime hook activation without `env=test`.
- (+) Fault scenarios mirror real failure modes operators have reported.
- (+) Zero new env-var surface: scenario choice is positional (`--inject-fault=<scenario>`), not declarative, so ADR-016's 8-var inventory and `.env.example` parity lint are unaffected.
- (-) Test-only code paths risk drifting from production; mitigated by Gate 1 lint that asserts the hook is reachable from both.

### Alternatives considered
- **A. Unconditional fault hooks enabled by env var only. Rejected:** weaker guardrail; an env var alone is easier to leak into prod than a CLI flag.
- **B. Chaos-style random fault scheduler. Rejected:** non-deterministic; breaks test reproducibility and contradicts NFR-07.
- **C. Out-of-process chaos proxy (e.g., `toxiproxy`). Rejected:** adds infrastructure; FR-04 / FR-02 expect in-process determinism.

---

## ADR-010: Versioned schema with backup-on-migrate

### Context
NFR-10 requires the on-disk schema to evolve without data loss or silent corruption. Three persistent files share the same migration rules. (SAD §4.6, §3.6)

### Decision
- Every persistent file root has a `version: int` field; current schema is v1.
- `_load_or_migrate(path)`:
  - Reads `version`; if `< 1` → write v1 and back up to `<path>.v<n>.bak`.
  - If `> 1` → refuse with exit 1 + upgrade hint (operator action required).
  - If file missing → initialize at v1.
- Backup retention: a single `.v<n>.bak` is kept per file; subsequent migrations overwrite the older backup.

### Consequences
- (+) Forward-compatible refusal surfaces unsupported versions explicitly.
- (+) Single backup per file keeps disk usage predictable.
- (+) Same helper applies to all three files — one audit surface for NFR-10.
- (-) Silent overwrite of `.v<n>.bak` loses older history; mitigated by manual `cp` if multi-step migration history is needed.
- (-) Refusing `version > 1` blocks naive downgrades too — acceptable because downgrades are unsafe.

### Alternatives considered
- **A. Migration log per file. Rejected:** doubles the file count for marginal benefit at current scale.
- **B. Silent schema auto-evolve across versions. Rejected:** violates NFR-03 fail-fast posture; silent rebuilds hide bugs.
- **C. Per-file version per data block. Rejected:** the schema is shallow enough that a single root version is sufficient.

---

## ADR-011: Secret redaction regex in `executor`

### Context
NFR-04 requires scrubbing secret-shaped substrings (API keys, bearer tokens) from `stdout_tail` and `stderr_tail` before persisting them to `tasks.json`. The redaction must be deterministic and unit-testable. (SAD §2.5 NFR-04, §4.2)

### Decision
- `executor._redact(text)` applies the regex `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` line-by-line, replacing matching lines with `[REDACTED]`.
- Applied at the boundary — after `subprocess.run` collects output, before `store.update_status` writes tails.
- The regex lives in a single module-level constant; tests assert on canonical sample inputs.

### Consequences
- (+) Single point of enforcement: every persisted tail passes through the same filter.
- (+) Regex is permissive enough to catch `sk-…` (OpenAI-style) and `token=…` (HTTP bearer / query).
- (+) Line-level replacement avoids partial-line edits that could leave fragments.
- (-) Heuristic-based — a brand-new secret shape needs a regex update; documented as an explicit risk in SRS.
- (-) Over-redaction may scrub legitimate output that incidentally matches; tunable via tests.

### Alternatives considered
- **A. Block-list of entire words. Rejected:** brittle; misses context (`token=` with various separators).
- **B. Pipe output through a structured logger with secret schemas. Rejected:** subprocess output is unstructured by nature.
- **C. Allow users to opt out of redaction. Rejected:** the safe default must always apply; opt-out would defeat the NFR.

---

## ADR-012: `subprocess.run([...], shell=False)` with `shlex.split`

### Context
NFR-02 forbids `shell=True` and demands an injection blacklist. Operators pass arbitrary command strings that must execute safely. (SAD §2.4 FR-02, §4.2)

### Decision
- `cli._validate_command(cmd)` rejects injection metacharacters: `; | & $ > < \` backtick.
- `executor.execute` calls `shlex.split(cmd)` and runs `subprocess.run([...], shell=False, check=False, timeout=...)`.
- Backpressure / no shell semantics — argv must be parsed by `shlex.split`, not the kernel.

### Consequences
- (+) Eliminates shell metacharacter injection at the OS boundary.
- (+) Static gate `grep -R "shell=True" src/` is a one-line CI lint.
- (+) Errors surface as Python exceptions, not opaque shell exit codes.
- (-) Users cannot rely on shell features (`~`, `*` glob, `&&`) — by design.
- (-) Quoting semantics depend on `shlex.split` POSIX mode; documented in `--help`.

### Alternatives considered
- **A. Allow `shell=True` with a deny-list. Rejected:** too many bypass vectors; SPEC §4.2 forbids.
- **B. Custom argv parser. Rejected:** re-implementing `shlex.split` invites bugs.
- **C. Run inside a container/sandbox. Rejected:** violates stdlib-only (ADR-001) and complicates install.

---

## ADR-013: Streaming iterator for `Store.list()` (no full-task load)

### Context
NFR-09 demands peak memory < 100 MB on 1000 tasks and `run --all` correctness on 100 tasks. A naive `json.load → list[Task]` would inflate memory and serialize on read. (SAD §4.1, §4.5)

### Decision
- `Store.list(status: TaskStatus | None = None) -> Iterator[Task]` yields one task at a time.
- Implementation: `json.load` once, then iterate `tasks.values()` — full-file decode is unavoidable for JSON, but no second in-memory copy is materialized beyond the decoded dict.
- Cache module reuses the same shape: load once, iterate lazily.

### Consequences
- (+) Bounds peak memory to one decoded JSON tree, not two.
- (+) Single decode pass keeps `list()` p95 < 100 ms at 1000 tasks per NFR-09.
- (+) Caller can `break` early without decoding the rest.
- (-) JSON's whole-file decode means a 10 MB tasks.json still costs one full parse; accepted per SPEC §5.

### Alternatives considered
- **A. SAX/streaming JSON parser (`ijson`). Rejected:** third-party dependency (ADR-001).
- **B. SQLite-backed store. Rejected:** see ADR-003 §C; JSON shape is the contract.
- **C. Buffered line-delimited JSON. Rejected:** shape change ripples to schema migration (ADR-010).

---

## ADR-014: Docstring `[FR-XX]` / `[NFR-YY]` traceability convention

### Context
NFR-05 requires every public function/class docstring to cite the requirements it implements. Gate 1 lint enforces this convention; SAB generation relies on it. (SAD §1, §4.7)

### Decision
- Every public symbol in `src/taskq/**` carries a docstring whose first line begins with a single `[FR-XX]` or `[NFR-YY]` citation. Multiple citations are not allowed on the first line — pick the dominant FR/NFR; secondary citations go in the prose body.
- Private helpers (`_atomic_write`, `_redact`) carry `[NFR-XX]` only if their behavior closes a NFR; otherwise plain docstrings are allowed.
- Gate 1 lint regex: `^\s*"""\[(FR|NFR)-\d+` against every public name in the AST (single leading citation, no trailing comma-list on the first line).

### Consequences
- (+) Single convention keeps audit time low.
- (+) SAB generation can parse citations mechanically without a separate manifest.
- (+) Drift between code and requirements becomes visible in code review.
- (-) Verbose on tiny helpers; mitigation: use `[NFR-XX]` only when closing a non-functional requirement.

### Alternatives considered
- **A. Per-symbol decorator `@fr("FR-01")`. Rejected:** metadata lives separately from the prose; harder to keep in sync.
- **B. External traceability spreadsheet. Rejected:** falls out of date immediately.
- **C. Tag comments only (`# FR-01`). Rejected:** not visible in `help()` output; convention is for human + lint readers.

---

## ADR-015: Lockless hot-read path for `Store.get` to meet NFR-01 p95 < 50ms

### Context
NFR-01 commits to a p95 latency under 50 ms over 100 iterations of `submit` + `status` (SRS §4 NFR-01 lines 207-211; SAD §4.1 lines 305-310). The `status` subcommand (`Store.get(id)`) is the highest-frequency read in the system — repeatedly invoked by CI, watchers, and the eventual `run --all` orchestrator. A naïve read that re-acquires the module-level `threading.Lock` and re-decodes the JSON file on every call will not meet the budget once the file holds > 100 tasks. (SAD §4.1 NFR-01, §4.5 NFR-09)

### Decision
- `Store.get(task_id)` performs an in-process read against a cached `dict[str, Task]` snapshot, refreshed only when the on-disk `mtime` changes (lazy file watch) or the in-process `threading.Lock` writer signals an update.
- Reads are lockless at the Python level: the cached snapshot is an immutable mapping replaced atomically (single `dict` reassignment, which is GIL-atomic for the reference).
- The file is loaded exactly once per `taskq` process invocation when stale; no per-call `json.load`.
- A miss on `task_id` returns `None` rather than triggering a re-load — keeps the common-case read at O(1) dict lookup.
- `Store.submit()` is the only mutating path and goes through the full ADR-003 atomic write + ADR-004 flock; it invalidates the in-process cache pointer on success.

### Consequences
- (+) `Store.get` reduces to a dict lookup; p95 budget becomes dependent only on dict size and cache-pointer swap, not on file I/O.
- (+) Single decode per process per stale-file state keeps the 100-iter benchmark well under 50 ms even at 1000 tasks.
- (+) Read path cannot observe a torn write because atomic-write (ADR-003) guarantees the file is whole on disk before the mtime advance.
- (-) Stale cache window: a separate process that writes through the flock will not be visible until this process re-checks mtime; mitigated by lazy re-read on every `get` call (constant-time `stat().st_mtime_ns`).
- (-) Adds a module-level cache state (`_snapshot`, `_mtime_ns`) to `store.py`; small extra surface but no public API change.

### Alternatives considered
- **A. Re-decode the JSON on every `get`. Rejected:** would re-parse on every CI poll, easily blowing the 50 ms budget at 100+ tasks and pushing p95 into the hundreds of ms range.
- **B. Hold the `threading.Lock` for the whole read. Rejected:** serialized reads defeat the latency target and create contention with concurrent `submit`.
- **C. Shared-memory cache (`mmap`). Rejected:** cross-platform semantics diverge (Windows + macOS differ from Linux); violates the stdlib-only posture (ADR-001) and the simplicity budget for a 1-file JSON store.

---

## ADR-016: Centralized configuration via `config.get_config()` (NFR-06)

### Context
NFR-06 mandates a single audit surface for the 8 declared `TASKQ_*` environment variables (SPEC §5.1; SRS §2.6 / Appendix B), `.env.example` parity enforced by CI lint, and predictable defaults when a var is unset. Scattered `os.environ.get` calls across modules produce a shotgun-read pattern: missing-default drift, silently ignored typos, and divergent behavior between test and production. (SAD §2.2 `Config` dataclass, §4.7 NFR-06)

### Decision
- `config.py` exposes exactly one public function: `get_config() -> Config` returning a typed `Config` dataclass.
- The 8 declared `TASKQ_*` variables are read at first call (`functools.lru_cache(maxsize=1)`), with defaults drawn from SPEC §5.1. No module under `src/taskq/` other than `config.py` calls `os.environ.get` or `os.getenv`.
- `Config.env` is a **computed** field, `Literal["test", "prod"]`:
  - **NOT** one of the 8 declared `TASKQ_*` variables (the NFR-06 8-var inventory is unaffected).
  - **NOT** in `.env.example` — must not be user-overridable, or ADR-009's `--inject-fault` production lockout would be defeatable by setting an env var.
  - Derived internally as `"test" if "PYTEST_CURRENT_TEST" in os.environ else "prod"`. Pytest sets `PYTEST_CURRENT_TEST` automatically for the duration of each test, so production process invocations never carry that variable and `--inject-fault` is refused unconditionally outside of pytest.
- `Config.env` is the single guard consulted by ADR-009 (`--inject-fault` acceptance precondition).
- `.env.example` lists exactly the 8 `TASKQ_*` vars; CI lint asserts parity against what `get_config()` reads.
- The `Config` dataclass is `frozen=True` so accidental mutation raises `dataclasses.FrozenInstanceError` at the call site, not at a downstream assertion.

### Consequences
- (+) One file (`config.py`) is the SSOT for the 8 declared `TASKQ_*` vars; Gate 1 lint greps for stray `os.environ` references across `src/taskq/**` and fails on any hit.
- (+) `.env.example` parity is mechanically enforceable; CI fails the build on drift.
- (+) `Config.env` is unfakeable: production paths cannot masquerade as test to unlock `--inject-fault`, because the trigger is `PYTEST_CURRENT_TEST`, which pytest owns.
- (+) `get_config()` is mockable in tests via `unittest.mock.patch("taskq.config.get_config")` — no monkeypatching of `os.environ` required.
- (+) Typed `Config` makes the 8 vars discoverable in IDEs and the type-checker; typos become `AttributeError` at import time.
- (-) Caching the `Config` instance means tests that mutate the environment must call `config.get_config.cache_clear()`; documented as a one-liner in the test fixture module.
- (-) Tests that need a non-default `Config` must patch the function, not the environment — slight ergonomic tax for a strict invariant.

### Alternatives considered
- **A. Scattered `os.environ.get` calls per module. Rejected:** shotgun reads are exactly what NFR-06 exists to prevent; any drift between modules becomes a silent bug.
- **B. `Config.env` as a 9th `TASKQ_*` var. Rejected:** makes the production lockout defeatable by setting one var; SAD §2.2 explicitly forbids.
- **C. `pydantic.BaseSettings`. Rejected:** third-party dependency, violates ADR-001 stdlib-only.
- **D. `dynaconf` / `python-decouple`. Rejected:** same reason; introduces install friction for a 60-LoC feature.
- **E. Re-read environment on every `get_config()` call. Rejected:** makes the function non-deterministic across a single process, breaks ADR-009's `cfg.env == "test"` precondition contract (a runtime flip would mid-process re-arm fault injection).

---

## ADR-017: SAB `nfr_traceability.type` enum mapping (SAD §4 → 8 legal parser values)

### Context
The harness SAB parser (`harness/core/quality_gate/sab_parser.py`) accepts exactly 8 `nfr_traceability.<NFR>.type` enum values: `performance`, `security`, `maintainability`, `reliability`, `testability`, `deployability`, `scalability`, `usability`. SAD §4 uses 8 SPEC §4 category headings (performance, security, reliability, concurrency, scalability, evolvability, maintainability, deployability) which **do not** map 1:1 onto that enum set:

- SAD categories with **no matching enum**: `concurrency`, `evolvability`.
- Enum values with **no matching SAD category**: `testability`, `usability`.

If the SAD headings were emitted verbatim into SAB YAML, the parser would reject `concurrency` and `evolvability` outright. The mapping must therefore be fixed at architecture time (not deferred to SAB generation), so that the SAB body can be emitted mechanically from SAD §4 prose without case-by-case judgement. (SAD §4 prose table, §5 SAB block)

### Decision
The per-NFR `nfr_traceability.<NFR>.type` value to use when the SAB YAML body is emitted:

| NFR | SAD §4 category | SAB `type` |
|-----|------------------|------------|
| NFR-01 | performance | `performance` |
| NFR-02 | security | `security` |
| NFR-03 | reliability | `reliability` |
| NFR-04 | security | `security` |
| NFR-05 | maintainability | `maintainability` |
| NFR-06 | deployability | `deployability` |
| NFR-07 | resilience (umbrella term) | `reliability` |
| NFR-08 | concurrency | `reliability` (data-integrity guarantee under concurrent access; closest legal value) |
| NFR-09 | scalability | `scalability` |
| NFR-10 | evolvability | `maintainability` (schema/version-migration upkeep; closest legal value) |

Rationale per mapping edge case:
- `NFR-07` is presented in SAD §4.3 as a resilience concern but the harness enum has no `resilience` value; the binding target is `reliability` (its semantic neighbor: fault tolerance is a reliability sub-discipline).
- `NFR-08` is a concurrency concern; the harness enum has no `concurrency` value. The binding target is `reliability` because the underlying guarantee being asserted is data-integrity under concurrent access (the same posture as NFR-03).
- `NFR-10` is an evolvability concern; the harness enum has no `evolvability` value. The binding target is `maintainability` because schema migration is a maintainability concern (schema/version upkeep).
- The unused enum values `testability` and `usability` correspond to no NFR in this project and are not emitted.

### Consequences
- (+) SAD §4 prose stays readable (uses the SPEC §4 categories) while the SAB YAML is parser-legal — the mapping table bridges the two.
- (+) Two NFRs (NFR-07, NFR-08) collapse onto `reliability`; this is intentional and surfaces in the SAB body so reviewers can audit the mapping rather than discover it implicitly.
- (+) The mapping is decided at architecture time, not at SAB-generation time, so the Phase 2 → Phase 4 hand-off is mechanical.
- (-) Reviewers who grep SAB for `concurrency` or `evolvability` will not find them — this ADR is the index.
- (-) Future NFRs that genuinely require `testability` or `usability` enum values would need a separate decision; the harness enum set is fixed.

### Alternatives considered
- **A. Use the SAD heading verbatim and let the parser reject the SAB. Rejected:** makes the SAB body un-emittable; the parser rejection is an error, not a soft warning.
- **B. Loosen the parser to accept `concurrency` / `evolvability`. Rejected:** out of scope (parser is a harness invariant, not a project decision); would create an upstream fork we don't maintain.
- **C. Drop NFR-07 / NFR-08 / NFR-10 from the SAB. Rejected:** violates the requirement that every NFR appears in `nfr_traceability`.
- **D. Defer the mapping to SAB-generation time. Rejected:** the SAD prose and the SAB body would drift; reviewers would need two reading passes to reconcile the categories.

---

*Author: Architect Agent A (Round 1, 2026-07-12) | Phase 2*
*Refers: `SPEC.md` v4.1.0 (2026-07-12) §0–§10, `SRS.md` (5 FR / 10 NFR), `SAD.md` §1–§5 (companion baseline).*
*Round 1 deltas vs prior round: SPEC v4.1.0 alignment — `ADR-002` switched from flat 9-file to **4-sub-package layout** (`core` / `storage` / `runtime` / `interface`) per SAD §2.1 (SPEC §6 constraint removed); `ADR-016` corrected `Config.env` to `Literal["test", "prod"]` derived from `PYTEST_CURRENT_TEST` (NOT a `TASKQ_*` var, NOT in `.env.example`); new `ADR-017` records the SAB `nfr_traceability.type` enum mapping (SAD §4 → 8 legal parser values); coverage matrix now references ADR-017.*