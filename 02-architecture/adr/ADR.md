# ADR — Architecture Decision Records: taskq

> **Project**: taskq v2.0.0
> **Author**: Architect (Agent A — Sub-Task 2/3)
> **Round**: 2 (template-alignment pass — added Status + Rationale sections; restructured Consequences to Positive/Negative format per `harness/templates/ADR.md`)
> **Date**: 2026-06-27
> **Source**: `02-architecture/SAD.md` Round 3 (2026-06-27) + `SPEC.md` v2.0.0 + `01-requirements/SRS.md`
> **Adjacency**: hand-off from Phase 1; companion to `SAD.md`; consumed by Phase 3
> **Template**: `harness/templates/ADR.md` — sections per ADR: Status / Context / Decision / Rationale / Consequences (Positive / Negative). Alternatives Considered retained as supplemental.

This document records the key architectural decisions made for `taskq` v2.0.0. Each ADR captures **Status → Context → Decision → Rationale → Consequences → Alternatives**, grounded in the SAD and SRS.

---

## ADR-001 — Python 3.11 stdlib-only runtime

### Status
Accepted (Phase 2 Round 2; binding per SPEC §2 + SAD §1.4)

### Context
`taskq` is a local task-queue CLI tool. The deployment target is a developer workstation; there is no network, no daemon, and no IPC. SPEC §2 mandates "Python 3.11" with no third-party runtime packages. The team must ship a tool that runs immediately on a fresh Python install without `pip install`, and the security posture (NFR-02: `shell=True` forbidden) prefers a small attack surface.

### Decision
- **Language**: Python 3.11 (per SPEC §2).
- **Runtime dependencies**: **zero**. Stdlib only.
- **Allowed stdlib modules**: `argparse`, `subprocess`, `shlex`, `json`, `uuid`, `os`, `re`, `datetime`, `pathlib`.

### Rationale
Stdlib-only is the smallest viable substrate that (a) satisfies SPEC §2 verbatim, (b) removes the supply-chain attack surface that contradicts NFR-02's small-surface preference, and (c) lets the tool run on any Python 3.11 environment with zero install ceremony. The 9 named stdlib modules cover every operation the spec requires (CLI dispatch, subprocess invocation, JSON persistence, env-var config, path resolution, ISO-8601 timestamps). No third-party library provides functionality that is not already present in stdlib for this scope.

### Consequences
- **Positive**:
  - Install-free distribution: `python -m taskq` works on any Python 3.11 environment.
  - Minimal attack surface (no supply-chain runtime risk; aligns with NFR-02).
  - Deterministic module set simplifies review and gate scoring.
- **Negative**:
  - Cannot use richer libraries (`pydantic`, `click`, `rich`, `tenacity`); custom code for retry loop, redaction regex, and CLI dispatch.
  - Project stays pegged to CPython 3.11 semantics (e.g., `subprocess.run` timeout behavior, `os.replace` atomicity on POSIX).
  - Any stdlib-only feature that later becomes necessary (e.g., structured concurrency) requires upstream adoption.

### Alternatives Considered
- **A1. Python + `click` + `pydantic`** — rejected: violates zero-deps; adds supply-chain risk; redundant given CLI is five subcommands.
- **A2. Python + a task-queue library (`huey`, `rq`)** — rejected: introduces a worker/daemon model that contradicts the "single-process file-based" style (SAD §1.3); requires broker setup.
- **A3. Go / Rust binary** — rejected: out of scope for SPEC §2; violates the language-binding in the spec; loses the "runs anywhere Python 3.11 is installed" property.

---

## ADR-002 — Layered architecture with strict top-down dependencies

### Status
Accepted (Phase 2 Round 2; binding per SAD §1.3, §2.5, §5 SAB `allowed_dependencies`)

### Context
The system must be small (≤15 files/dir; no god-module per project constraint) and acyclic. SPEC §2 names four logical components (CLI, 任務執行, 持久化, 設定). SRS §2.7 pre-names three modules (`taskq.executor`, `taskq.store`, `taskq.config`) so the layering cannot be arbitrary.

### Decision
Adopt a **layered** architecture (SAD §1.3) with **one-way dependencies**:
```
cli  ──► executor ──► store
 │        │            │
 │        ├─► redactor └─► config
 │        └─► config
 ├──► store
 └──► config
```
- `redactor` and `config` are **leaf modules** (no outgoing deps).
- `store` does **not** depend on `redactor` (verified against SAB `allowed_dependencies`; SAD §2.5).
- `executor` never imports `cli` (no upward edges).

### Rationale
Layering with strict top-down edges is the smallest discipline that delivers four requirements at once: (a) enforces single-responsibility per module so SAB `max_coupling: 0.3` (SAD §5) is achievable, (b) lets Drift Detection in `render_canonical_sab_template` catch accidental cycles at gate time, (c) maps each FR cleanly to one or two modules (SAD §2.3), and (d) eliminates the "no god-module" risk inherent to flat single-file designs. The dependency graph above is acyclic by construction because every edge points downward (cli → executor → store → config; executor → redactor).

### Consequences
- **Positive**:
  - Enforces single-responsibility per module; gates `max_coupling: 0.3` (SAB §5) are achievable.
  - Drift Detection (parser `render_canonical_sab_template`) catches accidental cycles at gate time.
  - Each FR maps cleanly to one or two modules (SAD §2.3).
- **Negative**:
  - Adds ceremony for what is essentially a small CLI; acceptable because the layering is documented as a binding contract.
  - Future extension (e.g., adding a remote-store adapter) requires revisiting `allowed_dependencies`.

### Alternatives Considered
- **A1. Flat single-module design (`taskq.py` with everything)** — rejected: violates "no god-module" and FR/NFR traceability expectations; raises `max_complexity` risk.
- **A2. Event-driven / plugin architecture** — rejected: overkill for five subcommands and three FRs; complicates testing.
- **A3. Hexagonal (ports & adapters)** — rejected: no second adapter exists; abstraction would be speculative.

---

## ADR-003 — `subprocess.run` + `shlex.split`, `shell=False` mandatory (no `shell=True`)

### Status
Accepted (Phase 2 Round 2; binding per NFR-02 + SAD §4.2 + architecture_constraint `no_shell_true`)

### Context
NFR-02 mandates that user-supplied commands never be interpreted by a shell, because the CLI accepts arbitrary shell-syntax strings for `submit`. SPEC §2 forbids `shell=True`. The risk is shell-injection via metacharacters (`; | & $ > < \``), addressed by a 7-character blacklist (AC-NFR02-02).

### Decision
- All subprocess invocations go through `taskq.executor.run`.
- Signature pattern:
  ```
  sp = subprocess.run(shlex.split(cmd), capture_output=True,
                     text=True, timeout=TASK_TIMEOUT)
  ```
- `shell=True` is **never** used; the codebase-wide static rule `tests/test_nfr02_no_shell.py` greps for the substring and asserts zero hits (AC-NFR02-01).
- `validate()` in `cli.submit` rejects empty / whitespace-only / `len>1000` / blacklist chars **before** any persistence.

### Rationale
Layered defense: the validate-time blacklist rejects obviously hostile inputs at the CLI boundary, and `shell=False` is the second line that ensures metacharacters are never interpreted even if a hostile string slips past validate. `shlex.split` provides POSIX-compatible tokenization without requiring an external lib. The static grep test (AC-NFR02-01) makes the constraint machine-checkable — a future regression that introduces `shell=True` is caught by CI before merge.

**Cross-reference to NFR-03 redaction ordering** (SAD §3.5 pipeline): the `subprocess.run(..., shell=False)` call also defines a hard ordering constraint with the NFR-03 redaction pipeline. Because `shell=False` returns the captured `stdout` / `stderr` as already-tokenized lists (no shell interpolation), the executor receives byte strings that are the literal command output — there is no shell-expanded path by which a secret can be re-injected into the output AFTER redaction runs. The pipeline is therefore strictly:

1. `subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=TASK_TIMEOUT)` — returns literal output (this ADR).
2. Truncate `stdout` / `stderr` to last 2000 chars in `executor` (BEFORE redaction, so the `[REDACTED]` marker cannot be evicted by truncation — see ADR-006).
3. `redactor.redact(stdout_tail)` and `redactor.redact(stderr_tail)` — sole owner is `taskq.executor` (ADR-006; SAD §3.5).
4. `store.save(...)` — redaction-AGNOSTIC; persists the dict it receives without field inspection.

Without `shell=False` (step 1), the shell could expand variables or perform command substitution (`$SECRET`, `$(cat key)`) AFTER redaction ran, producing a secret-bearing tail that bypasses the NFR-03 pipeline. This is the ordering interaction: `shell=False` is the precondition that makes NFR-03 redaction-before-persist (SAD §3.5) actually close the leak; violating this ADR would re-open NFR-03 even with a correct redactor. The AC-NFR02-03 defense-in-depth assertion (hostile string bypasses `validate` → still no shell interpretation) is therefore jointly owned by this ADR (NFR-02) and by the NFR-03 pipeline (SAD §3.5).

### Consequences
- **Positive**:
  - Defense-in-depth: even if `validate()` is bypassed, `shell=False` prevents shell metacharacter interpretation (AC-NFR02-03).
  - Blacklist is testable as 7 parametrized cases.
  - Static `tests/test_nfr02_no_shell.py` makes the rule machine-checkable.
- **Negative**:
  - `shlex.split` tokenizes POSIX-shell-style; commands using Windows-only quoting are not supported (out of scope; SPEC targets POSIX).
  - Blacklist is necessarily incomplete; future hardening may move to allow-list or full AST parsing — deferred.

### Alternatives Considered
- **A1. Allow-list tokenizer (full shell-parser)** — rejected: out of scope; would require `shlex` mode customization or external lib.
- **A2. Run inside a sandbox (Docker, firejail)** — rejected: violates single-process, zero-deps model.
- **A3. Use `os.system` or `subprocess.Popen(shell=True)`** — rejected: directly violates NFR-02 and AC-NFR02-01.

---

## ADR-004 — Atomic JSON store via `tmp + os.replace`

### Status
Accepted (Phase 2 Round 2; binding per NFR-03 + SAD §2.6, §3.3, §4.3)

### Context
NFR-03 mandates that `tasks.json` never appears half-written on disk, including across SIGKILL. The data is small (<1 KB per task) and structured; JSON is the lowest-friction format that supports the `status <id>` O(1) lookup required by FR-03 and NFR-01.

### Decision
- **Persistence layer**: `taskq.store` (SAD §2.2).
- **Write path** (`store.save`):
  1. Write serialized JSON to `<tasks.json>.tmp`.
  2. `os.replace(tmp, tasks.json)` — POSIX-atomic rename.
- **Read path** (`store.load`):
  - `json.loads` on the file; on `JSONDecodeError` raise `StoreCorrupted` → `cli.main` exits 1 with stderr `store corrupted`.
  - **No silent rebuild** (AC-FR01-09 / AC-NFR03-05).
- **Top-level shape**: dict-of-task keyed by `task_id` (uuid4().hex[:8], lowercase hex).

### Rationale
`tmp + os.replace` is the simplest POSIX-portable construct that delivers atomicity without locking or journaling — `os.replace` is atomic on POSIX, so the on-disk file is either the pre-tmp content or the post-replace content, never a partial write. Dict-of-task shape makes `status <id>` an O(1) dict lookup, which is the only way to keep `submit+status` p95 under the NFR-01 budget. `JSONDecodeError` → `StoreCorrupted` → exit 1 keeps corruption loud and operator-actionable (no silent rebuild).

### Consequences
- **Positive**:
  - `os.replace` is atomic on POSIX; partial-write impossible between `tmp` and `replace` (AC-NFR03-01).
  - `status <id>` is O(1) (dict lookup), keeping `submit+status` p95 < 50 ms feasible (NFR-01).
  - Corruption detection is explicit and non-destructive.
- **Negative**:
  - Concurrent-writer semantics are single-writer only; two simultaneous `submit` calls may lose one write (a regression guard exists, but it is not contractual; SAD §3.6).
  - Unbounded file growth (`json.dumps` cost scales with task count) — out of scope per SPEC §6; documented as Risk R1-adjacent.
  - **NFR-01 floor caveat (SAD B-2 review)**: SPEC §4 sets the floor at p95 < 50 ms while the bench `tests/bench/test_nfr01_perf.py` defaults to 100 iterations of `submit+status`. If a CI host is slower than the SPEC author measured, the p95 may approach or exceed 50 ms without any code regression — Phase 4 must keep the bench pinned to a fast host or relax the floor in lockstep with measurement evidence; this is a measurement-environment risk, not an architectural one.

### Alternatives Considered
- **A1. SQLite** — rejected: violates zero-deps and single-file simplicity; introduces driver dependency.
- **A2. Append-only NDJSON / log-structured** — rejected: `status <id>` query requires full scan; breaks NFR-01 budget.
- **A3. `fcntl.flock` for multi-writer safety** — rejected: SPEC does not require multi-writer; SAD §3.6 explicitly documents single-writer assumption.

---

## ADR-005 — Bounded retry loop with explicit exit conditions

### Status
Accepted (Phase 2 Round 2; binding per FR-02 + SAD §3.3)

### Context
FR-02 specifies state machine `pending → running → {done|failed|timeout}` and a retry budget `TASKQ_RETRY_LIMIT` (default 2). The original loop conflated success, retry, and exhaustion, causing Gap-3 in earlier rounds. A timeout in single-task mode must propagate to exit code 4.

### Decision
Use an **explicit-state retry loop** in `taskq.executor.run` (SAD §3.3):
```
attempt = 0
status = None
while attempt <= RETRY_LIMIT:
    attempt += 1
    try:
        sp = subprocess.run(shlex.split(cmd), capture_output=True,
                             text=True, timeout=TASK_TIMEOUT)
        status = "done" if sp.returncode == 0 else "failed"
    except subprocess.TimeoutExpired:
        status = "timeout"
        if single_task_mode: raise TimeoutError → exit(4)
    if status == "done": break
    if status in ("failed", "timeout"):
        if attempt > RETRY_LIMIT: break
        continue
    break  # defensive
```
- `ThreadPoolExecutor` is **not** used (single-process, single-subprocess per `run` call).
- Retry budget is read once at call time from `taskq.config.RETRY_LIMIT`.

### Rationale
Explicit-state enumeration (success / exhausted / timeout) is the smallest form that makes each AC independently testable: AC-FR02-07..08 maps to the exhaustion branch; AC-FR02-03 maps to the `TimeoutError` → exit 4 branch. The original implicit `for _ in range(...)` form conflated the terminal "done" state with the "exhausted retry" state, which caused Gap-3 (pre-Round-3). A pure-Python loop with no executor thread matches the SPEC §1 single-process model and keeps mock-based unit tests trivial.

### Consequences
- **Positive**:
  - Three exit conditions (`done` / exhausted / `TimeoutError`) are explicit and individually testable.
  - AC-FR02-07..08 (retry budget) and AC-FR02-03 (timeout → exit 4) map to distinct code paths.
  - Loop is pure-Python, deterministic, and easy to mock for unit tests.
- **Negative**:
  - Linear backoff only (no jitter, no exponential); out of scope for v2.0.0.
  - Concurrency within a single task is not modeled (intentional; SAD §3.6).

### Alternatives Considered
- **A1. `concurrent.futures.ThreadPoolExecutor` for parallel tasks** — rejected: SPEC §1 single-process; multi-task parallelism would break the single-writer store invariant and is out of scope.
- **A2. Exponential backoff with jitter** — rejected: not specified in SPEC §3 or FR-02; adding it without requirement violates Simplicity First.
- **A3. External retry library (`tenacity`, `retry`)** — rejected: zero-deps constraint (ADR-001).
- **A4. Implicit loop (`for _ in range(RETRY_LIMIT+1): …`)** — rejected: original design (pre-Round-3) conflated terminal and retry states; explicit-state form was the Gap-3 fix.

---

## ADR-006 — Single redactor owner: `taskq.executor` (not `taskq.store`)

### Status
Accepted (Phase 2 Round 2; binding per NFR-03 + SAD §3.5 + architecture_constraint `single_redaction_owner_executor`)

### Context
NFR-03 requires that secret-like strings (`sk-…`, `token=…`) never persist into `tasks.json`. The redaction must happen before the store write. Placing redaction in `store` would couple persistence to content inspection and create two potential paths to leak secrets (the store layer and any pre-store path that forgets to redact).

### Decision
- **Sole redaction owner**: `taskq.executor.run`.
- **Pipeline** (SAD §3.5):
  1. Truncate subprocess stdout/stderr to last **2000 chars** (executor, **before** redaction, so the `[REDACTED]` marker itself cannot be evicted by truncation).
  2. `redactor.redact(stdout_tail)` and `redactor.redact(stderr_tail)`.
  3. Mutate `store[id]` with the redacted tails + terminal fields.
  4. `store.save(...)` — **does not inspect fields**; persists the dict it receives.
- **Redactor** (`taskq.redactor`): pure function `redact(text: str) -> str` implementing line-level regex `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` → `[REDACTED]`. Non-matching lines preserved verbatim.
- **Constraint**: `store` does **not** depend on `redactor` (SAB `allowed_dependencies`; ADR-002). Re-submitting a record through `store.save` (e.g., `submit` updating `pending → running → final`) does not re-redact; redaction is one-shot at executor boundary.

### Rationale
Single-owner redaction is the only discipline that makes "forgot to redact" structurally impossible. If `store.save` also redacted, any other caller of `store.save` (e.g., a future `cli` path that mutates `pending → running`) would have to remember to call the redactor first — a footgun. Pinning the owner at the boundary that produces the bytes (executor) means the secret never enters the in-memory dict in unredacted form before persist. Truncate-before-redact is the ordering that guarantees the `[REDACTED]` marker cannot be evicted by tail truncation.

### Consequences
- **Positive**:
  - Single ownership eliminates "forgot to redact" footgun; the SAB-level `single_redaction_owner_executor` constraint is machine-checkable.
  - Truncate-before-redact keeps `[REDACTED]` markers within the persisted tail.
  - `redactor` is a leaf with zero deps and pure semantics — trivially unit-testable.
- **Negative**:
  - Truncation at 2000 chars could lose context if a long log contains a secret near the head; acceptable per SPEC §3 (tail-only model is documented).
  - Future need to redact other shapes (e.g., bearer tokens, PEM blocks) requires extending the regex — single point of change is a feature, not a cost.

### Alternatives Considered
- **A1. Redact inside `taskq.store.save`** — rejected: violates "single owner" constraint; couples persistence to content; the SAB explicitly forbids `store → redactor`.
- **A2. Redact inside `taskq.cli`** — rejected: `submit` does not capture output (no output to redact); only `run` produces output; logic belongs at the boundary that owns the bytes.
- **A3. Apply redaction on every load (read-time)** — rejected: doubles cost on every read; defeats the O(1) `status <id>` lookup; secret-bearing record may already be on disk if a buggy version wrote it.
- **A4. Use `logging.Filter` / structured-log redaction** — rejected: requires hooking the logging pipeline; persistence path bypasses logging.

---

## ADR-007 — Circuit breaker / corruption detection via `StoreCorrupted` → exit 1

### Status
Accepted (Phase 2 Round 2; binding per NFR-03 + SAD §3.6, §4.3)

### Context
NFR-03 demands reliability: a corrupted `tasks.json` must not be silently rebuilt (AC-FR01-09 / AC-NFR03-05). The failure mode (truncated write, manual edit, disk fault) must surface clearly to the user with a non-zero exit code so automation can detect and stop.

### Decision
- `taskq.store.load()` wraps `json.loads` and raises a domain exception `StoreCorrupted` on `JSONDecodeError`.
- `taskq.cli.main` catches `StoreCorrupted` and exits **1** with `stderr = "store corrupted"`.
- **No automatic recovery / rebuild / migration** is performed in v2.0.0.
- A regression test (`tests/test_nfr03_corruption.py`) injects a truncated `tasks.json` and asserts exit 1.

> Note: "circuit breaker" in this codebase is a **detection-and-fail-closed** pattern, not a multi-state breaker (CLOSED/OPEN/HALF-OPEN). The codebase does not maintain runtime state across invocations (SAD §1.3: stateless), so a true multi-state breaker is not implementable without a daemon. The chosen pattern is the simplest behavior consistent with NFR-03.

### Rationale
NFR-03 mandates no silent rebuild (AC-FR01-09 / AC-NFR03-05). Fail-closed detection (catch → exit 1) is the smallest implementation that satisfies this: corruption surfaces with a non-zero exit code so automation can stop, and there is no auto-recovery path that could silently lose user data. A multi-state breaker would require a persistent state file or daemon, both of which contradict the stateless / single-process model (ADR-008).

### Consequences
- **Positive**:
  - Fail-closed: corruption is loud and operator-actionable.
  - Test asserts behavior end-to-end (CLI → store → exit code).
  - Aligns with "no silent rebuild" (AC-FR01-09 / AC-NFR03-05).
- **Negative**:
  - Users must manually inspect / restore `tasks.json` after corruption; documented in CLI help.
  - Does not auto-heal; acceptable per FR-01 / NFR-03 and SPEC §3.

### Alternatives Considered
- **A1. Auto-quarantine corrupt file (`tasks.json.bad`) and start fresh** — rejected: violates "no silent rebuild"; loses user data without consent.
- **A2. Multi-state breaker (CLOSED/OPEN/HALF-OPEN) with cooldown** — rejected: requires a persistent state file or daemon; the architecture is stateless across invocations (SAD §1.3).
- **A3. Ignore corruption, return empty dict** — rejected: directly violates AC-NFR03-05.

---

## ADR-008 — Stateless, single-process invocation model

### Status
Accepted (Phase 2 Round 2; binding per SPEC §1 + SAD §1.3, §3.6)

### Context
SPEC §1 and SAD §1.3 define the tool as a per-invocation CLI that re-reads `tasks.json`, mutates an in-memory dict, and atomically rewrites. There is no long-running daemon, no socket, no signal handling beyond SIGKILL resilience. This is foundational: every other decision (atomic write, single-writer, no in-memory breaker) flows from it.

### Decision
- **Process model**: each `python -m taskq <subcmd>` is a fresh process.
- **State**: only what is on disk (`tasks.json`) and in environment (`TASKQ_HOME`, `TASKQ_TASK_TIMEOUT`, `TASKQ_RETRY_LIMIT`).
- **No in-process caching** between invocations.
- **No locks** held across invocation boundaries.

### Rationale
The stateless single-process model is the smallest design that satisfies three requirements simultaneously: (a) composes trivially with cron / shell pipelines / CI (each invocation is a clean fork-exec), (b) makes SIGKILL resilience automatic because the only persisted state is the disk file written atomically (ADR-004), and (c) lets tests run in parallel without coordinating against a shared daemon. Every downstream decision (atomic write, single-writer assumption, no in-memory breaker) inherits from this foundation.

### Consequences
- **Positive**:
  - Composes with cron / shell pipelines / CI trivially.
  - Crash mid-invocation leaves the store consistent (atomic write; ADR-004).
  - Tests can run in parallel without coordination against a shared daemon.
- **Negative**:
  - Multi-submit performance is bounded by per-invocation `load + save`; for 1000 tasks/submit, the 50 ms budget (NFR-01) may be tight — measured in `tests/bench/test_nfr01_perf.py` (Phase 3 obligation).
  - Cannot support interactive features (REPL, live status) without changing this decision.

### Alternatives Considered
- **A1. Long-running daemon with a Unix socket / TCP port** — rejected: violates "no network / no IPC" (SAD §1.3) and zero-deps; adds deployment complexity.
- **A2. In-memory cache with periodic flush** — rejected: violates the "single source of truth = disk" model; complicates concurrency.
- **A3. RPC service fronting the CLI** — rejected: out of scope.

---

## ADR-009 — CLI surface via `argparse` with global `--json`

### Status
Accepted (Phase 2 Round 2; binding per FR-03 + SAD §3.1)

### Context
FR-03 specifies five subcommands (`submit`, `run`, `status`, `list`, `clear`) and a `--json` flag that changes the output format (machine-readable vs. human-readable). SPEC §3 mandates a fixed exit-code table (0 / 1 / 2 / 4). The CLI is the only externally visible surface; it must be stable across the contract.

### Decision
- **Parser**: stdlib `argparse`.
- **Dispatch**: `python -m taskq <subcmd> [--json] [args]`.
- **Exit codes**:
  | Code | Condition |
  |------|-----------|
  | 0 | success |
  | 1 | internal error (incl. store corruption) |
  | 2 | validation error OR unknown task id |
  | 4 | task timeout (single-task mode) |
- `--json` is a global flag handled in `cli.main`; each subcommand emits either human or JSON output.
- Entry point: `python -m taskq` → `taskq/__main__.py` → `taskq/cli.main(argv)`.

### Rationale
`argparse` is stdlib and provides structured subcommand dispatch, type coercion, and auto-help without any dependency. The fixed exit-code table (0 / 1 / 2 / 4) is part of the SPEC §3 contract, so each subcommand must map its terminal outcomes deterministically — `argparse` keeps that mapping local to one function (`cli.main`). The global `--json` flag matches FR-03's "scriptable from any language" property.

### Consequences
- **Positive**:
  - Stdlib parser keeps zero-deps (ADR-001).
  - Fixed exit codes are testable end-to-end.
  - `--json` makes the tool scriptable from any language.
- **Negative**:
  - `argparse` help formatting is utilitarian; acceptable per scope.
  - Adding subcommands requires touching `cli.py` dispatch — acceptable because subcommand set is closed (FR-03).

### Alternatives Considered
- **A1. `click`** — rejected: zero-deps (ADR-001).
- **A2. `typer`** — rejected: zero-deps; also requires `typing_extensions`.
- **A3. Hand-rolled argv parser** — rejected: reinvents `argparse`; error handling worse.

---

## ADR-010 — Module tree derives from SPEC §2; no module invented

### Status
Accepted (Phase 2 Round 2; binding per SAD §2.1)

### Context
SPEC §2 enumerates four logical components (CLI, 任務執行, 持久化, 設定). SPEC §6 (directory structure) is **absent** in v2.0.0. The module names `taskq.executor`, `taskq.store`, `taskq.config` are pre-named in SRS §2.7. A faithful derivation is required: no speculative module.

### Decision
Final tree (SAD §2.1):
```
taskq/
├── __init__.py        # version + public API re-exports
├── __main__.py        # argv → cli.main()
├── cli.py             # argparse surface; subcommand dispatch; --json; exit codes
├── config.py          # TASKQ_* env loader
├── store.py           # atomic JSON load/save; redaction-AGNOSTIC
├── executor.py        # subprocess wrapper; state machine; SOLE redaction owner
└── redactor.py        # secret-line regex filter
```
- **7 source files** (≤15 cap; no god-module).
- `redactor.py` is added as a small leaf because the redaction regex deserves its own unit-test surface; no other module is split beyond what the spec demands.

### Rationale
Each module maps to a SPEC §2 component or to a leaf required by a binding constraint: `cli` (CLI), `executor` (任務執行), `store` (持久化), `config` (設定), `redactor` (sub-module extracted so the SAB `single_redaction_owner_executor` constraint refers to a specific named module rather than to a method on `executor`). `__main__.py` and `__init__.py` are wiring files (own no FR) but are required for `python -m taskq` and for packaging metadata respectively.

### Consequences
- **Positive**:
  - Faithful to SPEC §2; every module traces to a component or to a leaf with a clear test surface.
  - FR-to-module mapping (SAD §2.3) is direct; no FR spans more than two modules.
  - Reviewers can verify "no invented module" by inspecting this ADR and SAD §2.1.
- **Negative**:
  - `redactor.py` could have been inlined into `executor.py`; kept separate so the SAB-layer `single_redaction_owner_executor` constraint can refer to a specific named module.
  - **Single-flat-package caveat (SAD B-2 review)**: the 7-file tree uses one flat package `taskq/` with no sub-packages. CRG Principle 1 (community / sub-package cohesion) is satisfied instead by **linear-pipeline layering** (ADR-002 dependency DAG `cli → executor → store → config` with `redactor` as a leaf consumed only by `executor`). The CRG-derived cohesion analysis is therefore structural at the file/method level, not at a sub-package level; future growth past ~15 files would warrant splitting into `taskq.cli`, `taskq.exec`, `taskq.persist`, `taskq.conf` sub-packages, but at the current 7-file scope this is speculative and would violate Simplicity First.

### Alternatives Considered
- **A1. Inline `redactor` into `executor`** — rejected: loses the named, single-owner property that the SAB constraint relies on; makes redaction regex harder to test in isolation.
- **A2. Split `cli` into `cli_submit`, `cli_run`, `cli_query`** — rejected: speculative; subcommand count is 5 and unlikely to grow per SPEC §3.
- **A3. Add a `models.py` (dataclass for `Task`)** — rejected: dict-of-task is sufficient; dataclass would add code without enabling any new FR.

---

## ADR-011 — Task identity: `uuid4().hex[:8]` (lowercase hex)

### Status
Accepted (Phase 2 Round 2; binding per FR-01 + SAD §2.7)

### Context
FR-01 requires a task identifier; FR-03 requires `status <id>` lookup. The id must be collision-resistant for local usage, short enough for CLI ergonomics, and stable across restarts.

### Decision
- `new_id()` returns `uuid4().hex[:8]` — 8 lowercase hex chars (32 bits of entropy).
- Collision risk for typical local usage (<10⁴ tasks) is negligible (birthday bound ≈ 65 k).
- Stored as top-level dict key; mirrored in the record's `id` field.

### Rationale
8-hex-char IDs hit the smallest string length that still gives 32 bits of entropy (birthday-bound ≈ 65 k collisions at 10⁴ records — well outside the local-CLI usage regime). Shorter (e.g., 4 hex) would collide too easily; longer (full 32-hex UUID) hurts CLI ergonomics without adding safety for local usage. Truncating `uuid4().hex` (rather than parsing a UUID object) keeps the implementation a one-liner with zero external dep.

### Consequences
- **Positive**:
  - Short and CLI-friendly (`taskq status 3f2a91c4`).
  - Sufficient entropy for local, single-writer usage.
  - No external id-generation dep.
- **Negative**:
  - At very large task counts (>65 k in one store) collision probability rises; out of scope for v2.0.0.
  - Not a UUID by RFC 4122 sense (truncated); documented behavior.

### Alternatives Considered
- **A1. Full `uuid4()` (32 hex chars)** — rejected: longer CLI ergonomics; no added safety inside the 10⁴-task regime.
- **A2. Monotonic integer** — rejected: not stable across `clear` (id reuse); collides with prior records.
- **A3. Content hash of command** — rejected: deterministic ids leak command content; collisions on identical commands.

---

## ADR-012 — Testability / verification path per FR and NFR

### Status
Accepted (Phase 2 Round 2; binding per SAD §4, §5 `quality_targets`)

### Context
The harness gate scoring (SAD §5 `quality_targets`: `min_coverage: 80`, `max_complexity: 15`, `max_coupling: 0.3`) and the per-FR GATE1-DELTA scoring require that each FR and NFR has a verifiable path. Acceptance Criteria IDs are pre-named in SRS (`AC-FR01-01..09`, `AC-FR02-01..10`, `AC-FR03-01..08`, `AC-NFR01..03-xx`).

### Decision
- Each module is paired with at least one test module that names ACs in `it('test_frNN_xxx')` form (per D4 spec-coverage contract).
- Test layout mirrors the source tree under `tests/`.
- Coverage gate: 80 % minimum; enforced by `pytest --cov` in CI.
- The bench (`tests/bench/test_nfr01_perf.py`) runs 100 iters and asserts p95 < 50 ms.
- The static check `tests/test_nfr02_no_shell.py` greps the source for `shell=True` substring.

### Rationale
The `it('test_frNN_xxx')` naming convention is the smallest discipline that makes D4 spec-coverage matchable: each test name maps to an AC ID one-to-one, so coverage gaps are visible at the file level. Coverage gate (80 %) and complexity gate (15) are inherited from SAD §5 `quality_targets`; pairing each module with at least one test module is the minimum surface that makes the gates achievable.

### Consequences
- **Positive**:
  - Gate scoring is reproducible: each AC maps to one or more test cases.
  - Coverage and complexity are measurable; SAD §5 `quality_targets` are achievable given the small module count.
  - Naming convention (`test_frNN_xxx`) makes D4 spec-coverage matchable.
- **Negative**:
  - Test code adds to repo size; capped at ≤15 files/dir, mirroring source.

### Alternatives Considered
- **A1. Property-based testing (`hypothesis`)** — rejected: zero-deps (ADR-001).
- **A2. Mutation testing (`mutmut`)** — considered for Phase 4 (separate skill); not part of Phase 2 ADR.
- **A3. End-to-end shell scripts only (no unit tests)** — rejected: cannot gate per-FR.

---

## ADR Index

| ID | Title | SAD ref |
|----|-------|---------|
| ADR-001 | Python 3.11 stdlib-only | §1.4, §6 |
| ADR-002 | Layered architecture, strict deps | §1.3, §2.5, §5 SAB |
| ADR-003 | `subprocess.run` + `shlex.split`, no `shell=True` | §4.2, ADR `no_shell_true` |
| ADR-004 | Atomic JSON store (`tmp + os.replace`) | §2.6, §4.3 |
| ADR-005 | Bounded retry loop with explicit exits | §3.3 |
| ADR-006 | Single redactor owner: `executor` | §3.5, SAB `single_redaction_owner_executor` |
| ADR-007 | Corruption detection → exit 1 (fail-closed) | §3.6, §4.3 |
| ADR-008 | Stateless, single-process invocation | §1.3, §3.6 |
| ADR-009 | `argparse` CLI + `--json` + exit codes | §3.1 |
| ADR-010 | Module tree derived from SPEC §2 (no invented module) | §2.1 |
| ADR-011 | Task id: `uuid4().hex[:8]` | §2.7 |
| ADR-012 | Testability per FR/NFR | §4, §5 `quality_targets` |

---

*End of ADR — taskq v2.0.0 — Round 2 (template-aligned: Status + Rationale + structured Positive/Negative Consequences per `harness/templates/ADR.md`)*