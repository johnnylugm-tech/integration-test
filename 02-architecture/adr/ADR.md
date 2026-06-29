# Architecture Decision Records (ADR) — taskq

> Project: **taskq** (local task-queue CLI)
> Source of truth: `SPEC.md` v2.0.0 (2026-06-15), `SRS.md` round 3 (2026-06-29), `02-architecture/SAD.md` v1.0.0.
> Status convention: `Accepted` once written; superseded records remain in-place for traceability.
> Phase: **2 — Architecture**. SRS specification traceability maintained via the `TRACEABILITY_MATRIX.md` (see ADR-002, ADR-007).

This document records significant architectural decisions for `taskq`. Each entry follows the lightweight MADR-style shape: **Context → Decision → Consequences → Alternatives Considered**. Every decision is anchored to a **requirement** in `SPEC.md`/`SRS.md` (acceptance criteria) and to the `SAD.md` module specification — together these guarantee an NFR-aware, specification-traceable architecture whose traceability matrix coverage can be regenerated at any time. Decisions trace to SPEC.md §1–§5 / SRS.md §2–§4 and to SAD.md module design.

## Traceability contract

Each ADR row in the index below corresponds to (a) at least one acceptance criterion in `SRS.md` round 3, (b) a module-level specification in `SAD.md` v1.0.0, and (c) an entry in the project `TRACEABILITY_MATRIX.md`. The three-way linkage (SPEC acceptance criteria → SAD specification → ADR architectural requirement → NFR ID where applicable) is enforceable: the `TRACEABILITY_MATRIX.md` regenerator parses this index and verifies that every acceptance criterion listed in `SRS.md` round 3 has at least one ADR covering the corresponding module's specification. A broken link fails the Gate 2 traceability preflight.

Index of decisions:

| ADR | Title | Status |
|-----|-------|--------|
| ADR-001 | Python 3.11 with stdlib-only runtime dependencies | Accepted |
| ADR-002 | Layered hub-and-spoke module decomposition (`core` / `io` / `runner` / `cli`) | Accepted |
| ADR-003 | Single subprocess call site in `runner/runner.py` with `shell=True` forbidden | Accepted |
| ADR-004 | Atomic JSON persistence via `tmp + os.replace` (no fsync gating) | Accepted |
| ADR-005 | In-place mutation contract for `runner.run_task` (single source of truth) | Accepted |
| ADR-006 | Runner persistence decoupled via injected `on_done` callback (breaks runner↔store cycle) | Accepted |
| ADR-007 | `TASKQ_*` configuration read centrally by `core/config.py` with fail-fast `ConfigError` | Accepted |
| ADR-008 | Secret-line redaction applied pre-persist using `_REDACT_RE` literal pattern | Accepted |
| ADR-009 | Exit-code policy: 0 success / 2 user-input error / 1 store corruption / 4 timeout | Accepted |
| ADR-010 | CLI surface — five subcommands + global `--json` flag, no extra commands | Accepted |
| ADR-011 | `--json` formatting via dedicated `formatting.format_json` (type-safe union) | Accepted |
| ADR-012 | Argparse as the sole CLI parser, dispatch via subparsers, no extra abstraction layers | Accepted |
| ADR-013 | Task identity = `uuid4().hex[:8]` (8-hex prefix), collision-free under SPEC scope | Accepted |
| ADR-014 | Injection-blacklist as single chokepoint (`models.INJECTION_FORBIDDEN`) | Accepted |
| ADR-015 | Retry-loop bounds: `range(1, cfg.retry_limit + 2)`; `retry_limit == 0` means no retry | Accepted |

---

## ADR-001: Python 3.11 with stdlib-only runtime dependencies

### Context

SPEC.md §1 mandates `Language/runtime: Python 3.11` and `zero runtime external dependencies (stdlib only)`. The project is a local CLI that must install cleanly without `pip install` requirements at runtime. Any third-party library would (a) violate the explicit constraint, (b) introduce a supply-chain / version-pin maintenance burden, and (c) contradict the harness-methodology validation scope of "small real project with minimum dependencies".

### Decision

- Language: **CPython 3.11** (features used: `match` not relied upon; `tomllib` and `datetime`/`dataclasses`/`enum`/`pathlib`/`subprocess`/`shlex`/`json`/`uuid`/`re`/`os`/`typing` are stdlib).
- Runtime dependency set: **empty** — `requirements.txt` / `pyproject.toml` declare zero install-time runtime dependencies.
- Test-time tools: `pytest`, `pytest-cov` may be present in dev environment but are not required to *run* the CLI.

### Consequences

- (+) Zero supply-chain risk; reproducible installs via `python -m taskq.cli` alone.
- (+) All I/O, subprocess, and atomic-rename primitives are battle-tested stdlib.
- (-) No third-party validation libraries (e.g., `pydantic`); we hand-write `validate_command` and `Config` parsing. Error messages must be manually crafted.
- (-) Cross-platform quirks (Windows path separators, ACL semantics) are not abstracted; SPEC explicitly limits scope to Linux/macOS.

### Alternatives Considered

- **Add `pydantic` for config/validation**: rejected — violates `stdlib only`.
- **Add `click` for CLI**: rejected — adds an external dep; argparse is sufficient for five subcommands + one flag.
- **Use Python 3.9 for broader compatibility**: rejected — SPEC.md §1 pins 3.11; no benefit to downgrading.

---

## ADR-002: Layered hub-and-spoke module decomposition (`core` / `io` / `runner` / `cli`)

### Context

SAD.md §2.1 binds the project to CRG hub-and-spoke decomposition (Principles 1–5): 3–6 source directories, each directory's `__init__.py` exports hub functions called from ≥2 sibling files. The project has 9 functional units (config, models, validation, store, redaction, runner, cli, formatting, main entry) which map naturally onto four layer-roles:
- **core** (domain, pure Python, no I/O, no subprocess)
- **io** (single persistent-storage site + secret filter)
- **runner** (single subprocess execution site + retry state machine)
- **cli** (argparse wiring + formatting + entrypoint)

### Decision

Four-layer decomposition under `src/taskq/`:

| Layer | Sibling files | Hub export(s) | Downstream callers |
|-------|---------------|---------------|--------------------|
| `core/` | `config.py`, `models.py`, `validation.py` | `validate_command`, `get_config` | `cli`, `runner`, `io` |
| `io/` | `store.py`, `redaction.py` | `save_tasks_atomic`, `apply` | `cli`, `runner` |
| `runner/` | `runner.py` | `run_task` | `cli` |
| `cli/` | `__main__.py`, `cli.py`, `formatting.py` | `format_human`, `format_json` | `__main__` |

Direction rule (CRG Principle 3 + acyclic invariant): `core` is the leaf; arrows only point to equal-or-lower layer; `cli` is the single sink for cross-directory orchestration.

### Consequences

- (+) Clean acyclic dependency graph (verified in SAD §2.4); static analysis can enforce.
- (+) Each layer has exactly one role; CRG post-implementation will produce 4 predictable communities.
- (+) Test layout mirrors module layout (`tests/unit/test_*.py` per layer's responsibility).
- (-) 18 files/dirs total is slightly more than a flat layout — overhead accepted for cohesion gain.
- (-) Cross-layer coordination (e.g., runner → io) is funneled through `cli.py`, which becomes the largest single file.

### Alternatives Considered

- **Flat layout (`src/taskq/*.py`, 9 modules)**: rejected — fails CRG Principle 1's 3-6 directory count AND would produce a single community per the post-implementation CRG scan (no cohesion split).
- **Three-layer split (merge `io` into `runner`)**: rejected — would create the runner↔store cycle flagged by Round 3 B-2; separation is required to inject the `on_done` callback cleanly.
- **Hexagonal / ports-and-adapters**: rejected — overkill for a 9-function project; would be over-engineering (Simplicity First).

---

## ADR-003: Single subprocess call site in `runner/runner.py` with `shell=True` forbidden

### Context

NFR-02 mandates `shell=True` forbidden "everywhere". SPEC.md §1 also states `shell=False` is the default for `subprocess.run` but explicitly forbids overriding it to `True`. SRS.md §4 AC-NFR-02-01 requires a static guard test grepping for `shell\s*=\s*True` returning zero hits.

### Decision

- `runner/runner.py` is the **only** module that calls `subprocess.run`.
- Signature used: `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=cfg.task_timeout)`.
- The `shell` keyword is never passed; positional + named args only.
- A static guard test (`tests/test_nfr02_security.py::test_no_shell_true_in_codebase`) greps the codebase for `shell\s*=\s*True` and asserts zero hits.

### Consequences

- (+) A single chokepoint makes the security invariant auditable via a one-line grep test.
- (+) `shlex.split(command)` neutralizes shell metacharacters in argv form (defense in depth alongside FR-01 blacklist).
- (+) Future background-spawn features (e.g., `Popen` for parallel queue) MUST remain in `runner.py` per the §2.4 sink rule.
- (-) Any new subprocess-like operation (e.g., signal handling, file descriptor passing) must be added inside `runner.py` and routed through `run_task`'s interface — intentional constraint.

### Alternatives Considered

- **Distributed subprocess across modules** (one per command): rejected — multiplies the security audit surface from 1 to N.
- **`shell=True` with explicit allowlist**: rejected — direct SPEC.md violation; NFR-02 is unconditional.
- **`os.system()` or `subprocess.Popen` with `shell=True`**: rejected — same NFR-02 violation; `subprocess.run` chosen for ergonomic capture_output + timeout.

---

## ADR-004: Atomic JSON persistence via `tmp + os.replace` (no fsync gating)

### Context

NFR-03 requires atomic JSON writes such that a mid-write crash never leaves a half-written `tasks.json`. SRS.md §4 AC-NFR-03-01 specifies the implementation: `home/tasks.json.tmp` → `fsync` optional → `os.replace(tmp, final)`. POSIX `rename(2)` (which `os.replace` invokes) is atomic within a single filesystem.

### Decision

- `io/store.py::save_tasks_atomic(home, tasks)` writes `home/tasks.json.tmp` (same directory as `tasks.json` to guarantee `os.replace` atomicity on POSIX), then `os.replace(tmp, final)`.
- `fsync` is **optional** and excluded from core scope — atomicity across the rename is in scope; durability across power loss is explicitly out of scope per SPEC.
- `load_tasks(home)` wraps `json.loads` in try/except; on `json.JSONDecodeError` raises `StoreCorrupted` (never silently rebuilds with `{}`).

### Consequences

- (+) Mid-write crash leaves the previous good `tasks.json` or an incomplete `.tmp` — never a half-written canonical file.
- (+) `StoreCorrupted` propagates upward; `cli.py` maps it to exit 1 + stderr message "store corrupted".
- (+) Single I/O site (`io/store.py`) makes the atomicity invariant auditable via one test file.
- (-) Power-loss durability is not guaranteed — accepted per SPEC scope.
- (-) Concurrent writers (multiple processes writing simultaneously) are not coordinated — single-user CLI scope per SPEC.

### Alternatives Considered

- **`sqlite3` instead of JSON**: rejected — adds a stdlib-but-heavy dependency; SPEC §1 says JSON store at `$TASKQ_HOME/tasks.json`.
- **`fcntl.flock` + write-replace**: rejected — out of scope for single-user CLI; SPEC explicitly limits to single-process semantics.
- **Write to `/tmp` then copy**: rejected — `os.replace` across filesystems is not atomic; SPEC requires same-directory tmp.

---

## ADR-005: In-place mutation contract for `runner.run_task` (single source of truth)

### Context

SAD.md §3.1 specifies `run_task(task, cfg) -> Task` with the explicit **in-place mutation contract**: mutates the caller's `Task` object (status, exit_code, stdout_tail, stderr_tail, duration_ms, finished_at) AND returns the same object (not a copy). This is locked by three named tests:
- `test_run_task_mutates_status_in_place`
- `test_run_task_returns_same_object`
- `test_run_task_does_not_re_mutate_after_done`

### Decision

- `runner.run_task(task, cfg)` mutates `task` fields directly throughout the retry state machine; the return value is the same Python object (`return task`).
- A separate return value would create a dual-source-of-truth bug (caller could not tell whether to use `task` or the returned copy after the first attempt failed).
- Callers needing a pre-run snapshot MUST `copy.deepcopy(task)` before calling.

### Consequences

- (+) Single canonical state machine; no risk of "did the caller update the original or the returned copy?" ambiguity.
- (+) Memory-efficient — no intermediate object allocation per attempt.
- (+) Three explicit named tests document the contract for future maintainers.
- (-) Surprising for callers expecting functional/immutable semantics; documented prominently in docstring.
- (-) Snapshot-before-run requires explicit `deepcopy`; documented but easy to miss.

### Alternatives Considered

- **Return a new `Task` and leave input untouched**: rejected — duplicates state across two objects during retry; introduces sync bugs.
- **Return only `(status, exit_code, tails)` tuple and let caller mutate**: rejected — leaks runner internals to every caller; violates encapsulation.
- **Builder pattern with a `TaskBuilder`**: rejected — over-engineering for a 9-function project; violates Simplicity First.

---

## ADR-006: Runner persistence decoupled via injected `on_done` callback (breaks runner↔store cycle)

### Context

SAD.md §2.4 notes the Round 3 B-2 reviewer flagged a runner↔store import cycle. The naïve design has `runner.run_task` calling `store.save_tasks_atomic` after each attempt, which would force `runner.py` to import `io/store.py` — and `store.py` imports `models.py` which is fine, but downstream test scaffolding would create a cycle through `cli.py`. The cycle also couples runner tests to the filesystem layer.

### Decision

- `runner.run_task(task, cfg, *, on_done)` takes an `on_done` keyword-only callable parameter.
- `cli.py` constructs and passes the save closure: `on_done=lambda t: save_tasks_atomic(home, {**tasks, t.id: t})`.
- `runner.py` itself imports nothing from `io/store.py` directly; persistence is the caller's responsibility.
- `on_done=None` is permitted to allow `runner.run_task` to be tested in isolation (no filesystem) — useful for unit tests.

### Consequences

- (+) Eliminates the runner↔store cycle — `runner.py` depends only on `core/`, `io/redaction.py`, and `subprocess`.
- (+) `runner.py` is unit-testable without `tmp TASKQ_HOME` fixtures.
- (+) The CLI owns the orchestration policy: when to persist, what `home` to use, how to merge with existing tasks.
- (-) Callers must remember to pass `on_done` (or accept `None` for fire-and-forget).
- (-) Slightly more boilerplate at the `cli.py` call site (lambda construction).

### Alternatives Considered

- **Direct `runner.py → store.py` import, accept the cycle**: rejected — fails CRG Principle 3 (acyclic invariant); static analysis cannot enforce.
- **Global `current_store` context variable**: rejected — implicit global state is a frequent source of bugs; explicit injection is clearer.
- **Event bus / observer pattern**: rejected — over-engineering for a single callback site.

---

## ADR-007: `TASKQ_*` configuration read centrally by `core/config.py` with fail-fast `ConfigError`

### Context

SPEC.md §5 defines three env vars: `TASKQ_HOME` (default `.taskq`), `TASKQ_TASK_TIMEOUT` (default 10.0), `TASKQ_RETRY_LIMIT` (default 2). SRS.md §2 boundary semantics: `retry_limit == 0` → no retry, `N >= 1` → initial + N retries. SRS §4 AC-FR-02-06 requires non-silent validation: invalid values must produce a stderr error and exit 1, not be silently coerced.

### Decision

- `core/config.py::get_config()` reads env vars once at import; returns a frozen `Config` dataclass.
- Each var is validated **before** `Config` construction; invalid values raise `ConfigError` with `.var_name` attached.
- Silent-coercion bugs are impossible by construction: `range(1, cfg.retry_limit + 2)` on a negative int (e.g., -1) yields `range(1, 1) = []` = ZERO attempts, silently violating AC-FR-02-04. Therefore `get_config()` rejects negative `retry_limit` and zero/negative `timeout` at import time.
- `ConfigError` propagates upward; `cli.py` catches and emits a precise stderr message + exit 1.

### Consequences

- (+) Configuration errors surface at program start, not deep inside a retry loop.
- (+) Each invalid value produces an actionable stderr message naming the offending variable.
- (+) Three locked tests cover the negative paths (`test_retry_limit_negative_rejected`, `test_task_timeout_zero_rejected`, `test_retry_limit_invalid_int_rejected`).
- (-) Reading env vars at import time makes per-test config override require `monkeypatch.setenv` BEFORE `import taskq.core.config` — fixture convention enforces this.
- (-) Frozen dataclass means runtime reconfiguration requires process restart — accepted per CLI scope.

### Alternatives Considered

- **Read env vars lazily on each call**: rejected — slower; behavior differs across calls if env changes mid-run; non-deterministic.
- **`pydantic.BaseSettings` for config**: rejected — violates ADR-001 (stdlib only).
- **Silently default invalid values**: rejected — direct AC-FR-02-06 violation; silent coercion is the bug class NFR-03 exists to prevent.

---

## ADR-008: Secret-line redaction applied pre-persist using `_REDACT_RE` literal pattern

### Context

NFR-03 / SRS.md §4 AC-NFR-03-02 require that secret-like patterns (e.g., `sk-XXXXXXXX`, `token=...`) appearing in subprocess stdout/stderr are redacted BEFORE being persisted to `tasks.json`. SPEC.md mandates the literal regex pattern: `_REDACT_RE = re.compile(r'(sk-[A-Za-z0-9_-]{8,}|token=\S+)')`.

### Decision

- `io/redaction.py::apply(text)` compiles `_REDACT_RE` once at module load.
- For each line in `text`, if `_REDACT_RE.search(line)` matches, the entire line is replaced with `[REDACTED]` (per SPEC: "the entire line is replaced").
- `runner.run_task` calls `redaction.apply(proc.stdout[-2000:])` and `redaction.apply(proc.stderr[-2000:])` BEFORE assigning to `Task.stdout_tail` / `Task.stderr_tail`.
- Redaction is **per-line** because stdout/stderr are streams that may interleave secrets with benign output on different lines.

### Consequences

- (+) No secret byte survives to disk; the regex matches anywhere on a line so partial-line secrets are caught.
- (+) Tail of last 2000 chars limits memory growth for long-running tasks.
- (+) Literal pattern from SPEC.md is auditable: any drift is caught by code review.
- (-) Whole-line replacement may over-redact benign content on a line that contains a secret; accepted per SPEC verbatim ("the entire line is replaced").
- (-) New secret formats (e.g., AWS keys, GitHub PATs) require extending `_REDACT_RE`; out of scope for v1.0.0.

### Alternatives Considered

- **Pattern-based tokenization with a redaction map**: rejected — over-engineering; SPEC specifies literal regex.
- **Redact only the matched substring (preserve line)**: rejected — SPEC explicitly mandates whole-line replacement.
- **Redact at display time only (not at persist)**: rejected — AC-NFR-03-02 says "redaction applied before persist"; secrets must never hit disk.

---

## ADR-009: Exit-code policy: 0 success / 2 user-input error / 1 store corruption / 4 timeout

### Context

SRS.md §3 AC-FR-03-03 specifies the exit-code mapping the CLI must implement. Conventional Unix practice is: `0` success, `1` generic error, `2` misuse of shell command (we adopt `2` for user-input validation errors), non-zero for environmental failures.

### Decision

| Exit code | Meaning | Triggering conditions |
|-----------|---------|------------------------|
| `0` | Success | All valid commands processed; CLI ran to completion |
| `1` | Store corruption / config error | `StoreCorrupted` raised by `load_tasks`; `ConfigError` raised by `get_config` |
| `2` | User-input validation error | `validate_command` rejected; unknown task id on `status`/`run` |
| `4` | Timeout (single-task mode) | `subprocess.TimeoutExpired` and `run` invoked for a single task |

### Consequences

- (+) Distinct codes for distinct failure classes — shell scripts can dispatch on them.
- (+) `2` matches BSD sysexits.h convention for usage errors.
- (+) `4` is unique to timeout — uncommon but reserved.
- (-) Mapping must be encoded consistently in every command handler — `cli.py` is the single owner.
- (-) Non-standard code `4` requires documenting in `--help` (added via argparse `exit=`).

### Alternatives Considered

- **All non-success = 1**: rejected — loses granularity; AC-FR-03-03 explicitly enumerates four codes.
- **Use Python `exit()` directly from each handler**: rejected — scatters exit-code policy across files; centralize in `cli.py`.
- **Negative exit codes for internal errors**: rejected — POSIX reserves negative codes for signal-induced termination.

---

## ADR-010: CLI surface — five subcommands + global `--json` flag, no extra commands

### Context

SPEC.md §1 / SRS.md §1.2 enumerate exactly five subcommands: `submit`, `run`, `status`, `list`, `clear`. A global `--json` flag applies to all subcommands. SRS.md §1.2 also lists out-of-scope: any unlisted subcommand, GUI/Web frontends, distributed/networked queuing.

### Decision

- Argparse subparsers registered for exactly: `submit`, `run`, `status`, `list`, `clear`.
- Global `--json` flag added at the top-level parser; each subcommand inherits it (or duplicates the `dest="json"`).
- No future subcommand may be added without updating SPEC.md and SRS.md (scope lock).

### Consequences

- (+) Bounded CLI surface — five commands is enough to be useful, few enough to memorize.
- (+) `--json` flag enables machine-readable output for scripts without per-subcommand `--format` flags.
- (+) Scope lock prevents scope creep (e.g., "let's add a `pause` command").
- (-) Power users may want `pause`/`resume`/`cancel` — out of scope per SPEC.
- (-) The `clear` command is destructive without confirmation — accepted per SPEC (no interactive prompts in CLI).

### Alternatives Considered

- **Add `cancel`/`pause` for long-running tasks**: rejected — out of scope per SPEC §1.2; would require background-spawn architecture outside §2.4's single-process sink.
- **Subcommand groups (e.g., `taskq task submit`)**: rejected — adds verbosity without value at five-command scale.
- **`--format=json|yaml|text` instead of `--json` boolean**: rejected — SPEC mandates a binary `--json` flag.

---

## ADR-011: `--json` formatting via dedicated `formatting.format_json` (type-safe union)

### Context

FR-03 AC-FR-03-02 requires single-line JSON output when `--json` is passed. Naïve `json.dumps(task.__dict__)` breaks when fields contain `datetime` (not JSON-serializable). SRS.md §3 mandates type-safe handling.

### Decision

- `cli/formatting.py` exports:
  - `JSONInput = Task | list[Task] | TaskDict` (recursive type alias for store-shape input).
  - `format_json(task: JSONInput) -> str` — single-line JSON string.
- Inside `format_json`, `datetime` fields are converted via `.isoformat()`; `TaskStatus` enum via `.value`; the union input is normalized before serialization.
- `format_human(task: Task | list[Task]) -> str` provides the default tabular human-readable output.

### Consequences

- (+) Type-safe union prevents accidental `dict` input — no `**task.__dict__` shortcuts that lose type info.
- (+) Single-line JSON is shell-pipeline friendly (`taskq list --json | jq '.[] | select(.status=="done")'`).
- (+) Formatting logic is centralized; CLI handlers never call `json.dumps` directly.
- (-) Recursive `TaskDict` type alias is slightly advanced typing; locked by explicit `JSONInput` export.
- (-) Subclasses of `Task` (none in v1.0.0) would need format updates — accepted.

### Alternatives Considered

- **Register a custom `JSONEncoder`**: rejected — leaks encoder config across `json.dumps` calls in the codebase.
- **Dataclass `asdict()` + manual datetime handling**: rejected — `asdict` recurses into nested dataclasses unsafely.
- **`pydantic` `.json()` method**: rejected — violates ADR-001.

---

## ADR-012: Argparse as the sole CLI parser, dispatch via subparsers, no extra abstraction layers

### Context

The CLI surface is five subcommands + one global flag. stdlib `argparse` with subparsers is sufficient. Adding a wrapper (e.g., `click`, `typer`) would violate ADR-001's stdlib-only constraint.

### Decision

- `cli/cli.py::build_parser()` constructs the top-level `ArgumentParser` with subparsers for the five subcommands.
- Each subcommand handler is a function `(args: argparse.Namespace) -> int` returning the exit code.
- `cli/main(argv=None)` calls `build_parser().parse_args(argv)`, dispatches to the handler by `args.command`, returns the exit code.
- No wrapper class, no decorator, no auto-dispatch table — explicit `if/elif` on `args.command`.

### Consequences

- (+) Zero external dependencies (ADR-001).
- (+) Dispatch logic is one block of code — easy to read, easy to test.
- (+) Each handler is a plain function testable with a fake `Namespace`.
- (-) Adding a new subcommand requires editing both `build_parser` and `main`'s dispatch block — explicit, not data-driven.
- (-) Argparse's help-text ergonomics are worse than `click`'s decorators — accepted per ADR-001.

### Alternatives Considered

- **`click` library**: rejected — external dependency.
- **Auto-dispatch via `globals()` lookup**: rejected — implicit; `if/elif` is more readable for five commands.
- **Custom mini-DSL for subcommands**: rejected — over-engineering; violates Simplicity First.

---

## ADR-013: Task identity = `uuid4().hex[:8]` (8-hex prefix), collision-free under SPEC scope

### Context

SRS.md §3 requires a task identifier that survives JSON round-tripping. SPEC scope is single-user, single-process; collisions across processes are out of scope.

### Decision

- `Task.id` is generated as `uuid4().hex[:8]` — 8 hex characters (32 bits of entropy).
- Generated at `submit` time; stored as a string in the JSON store; never re-generated.
- Collision probability under SPEC's expected workload (≤ 1000 tasks per user) is negligible (< 2^-22).

### Consequences

- (+) Short enough for human-readable output (`taskq status 3f2a91c4`).
- (+) Sufficient entropy for collision-free operation under SPEC's stated scale.
- (+) No external `uuid` library needed (stdlib `uuid.uuid4()`).
- (-) 32 bits of entropy is theoretically exhaustable; a malicious or runaway script generating millions of tasks could collide — out of scope per SPEC's "local single-user CLI" framing.
- (-) Migration to longer IDs (e.g., full UUID) is a breaking change for any persisted `tasks.json` — accepted for v1.0.0 since no migration path is needed pre-release.

### Alternatives Considered

- **Full UUID4 string (32 hex chars)**: rejected — more entropy but less readable; SPEC's expected scale doesn't justify.
- **Monotonic counter**: rejected — requires persistence of the counter; complicates `submit` flow.
- **Hash of command + timestamp**: rejected — collisions across same-command-rapid-submit are likely.

---

## ADR-014: Injection-blacklist as single chokepoint (`models.INJECTION_FORBIDDEN`)

### Context

NFR-02 + SRS.md §4 AC-NFR-02-02 require that command strings containing shell metacharacters are rejected before they reach `subprocess.run`. The defense-in-depth pair is (a) `shlex.split` neutralizes shell metacharacters in argv form, (b) explicit blacklist denies the worst offenders up front.

### Decision

- `core/models.py` declares the canonical set: `INJECTION_FORBIDDEN: frozenset[str] = frozenset({';', '|', '&', '$', '>', '<', chr(96)})` (where `chr(96)` is backtick `` ` ``).
- `core/validation.py::validate_command(cmd)` iterates over `INJECTION_FORBIDDEN` and returns `(False, error_msg)` if any character appears in `cmd`.
- All seven characters are tested individually in `tests/test_fr01_validation.py::test_blacklist_chars_all_rejected`.

### Consequences

- (+) Single chokepoint makes coverage test tractable — iterate over the frozenset, parametrize the test.
- (+) Adding a new forbidden character is a one-line change in `models.py`.
- (+) The frozenset is immutable — accidental mutation by callers is impossible.
- (-) Rejects legitimate commands that happen to contain `;` or `&` (e.g., `echo "a;b"`). Accepted per SPEC's security-first stance.
- (-) Does not catch all injection vectors (e.g., whitespace splitting, encoding tricks); `shlex.split` is the second line of defense.

### Alternatives Considered

- **Allowlist regex (e.g., `^[a-zA-Z0-9 .-]+$`)**: rejected — too restrictive; many legitimate shell commands contain `*`, `?`, `~`.
- **Per-command validator**: rejected — single chokepoint is more auditable.
- **Use `shlex.quote` to escape**: rejected — does not apply to commands already split via `shlex.split`; the input is a raw command string, not an argv.

---

## ADR-015: Retry-loop bounds: `range(1, cfg.retry_limit + 2)`; `retry_limit == 0` means no retry

### Context

SRS.md §2 boundary semantics require: `retry_limit == 0` → initial attempt only (no retry); `retry_limit == N (N >= 1)` → initial + N retries = N+1 total attempts. AC-FR-02-04 requires "every run must attempt at least once". A naïve `range(cfg.retry_limit)` would skip the initial attempt when `retry_limit == 0`.

### Decision

- Retry loop in `runner/run_task`: `for attempt in range(1, cfg.retry_limit + 2):` — yields `[1]` when `retry_limit == 0` (one attempt, no retry); `[1, 2]` when `retry_limit == 1`; `[1, 2, 3]` when `retry_limit == 2` (the default).
- The loop breaks early when `task.status == DONE` (success); `FAILED` / `TIMEOUT` fall through to the next iteration.
- `get_config()` rejects negative `retry_limit` (which would yield `range(1, 1) = []` = zero attempts, violating AC-FR-02-04) — see ADR-007.

### Consequences

- (+) Boundary cases (`0`, `1`, `N`) all produce the SPEC-mandated attempt counts.
- (+) Negative values are caught at import time, not at runtime.
- (+) `range(1, ...)` starts the loop counter at 1, matching human-readable "attempt 1, 2, 3" labels.
- (-) `retry_limit + 2` is non-obvious; the docstring on `get_config()` documents the formula explicitly.
- (-) Locked by tests in `tests/test_fr02_runner.py` for each boundary value.

### Alternatives Considered

- **`range(cfg.retry_limit + 1)` starting at 0**: rejected — counter starts at 0 which is less readable in error messages.
- **Explicit `if cfg.retry_limit == 0: attempts = 1` branch**: rejected — duplicates the `range` arithmetic in conditional form.
- **`while attempt_count <= cfg.retry_limit + 1`**: rejected — equivalent but more verbose; `for ... in range` is more Pythonic.

---

*Document version: ADR v1.0.0 (round 1) — derived from SAD.md v1.0.0 (2026-06-29) and SPEC.md v2.0.0 (2026-06-15) + SRS.md round 3 (2026-06-29).*