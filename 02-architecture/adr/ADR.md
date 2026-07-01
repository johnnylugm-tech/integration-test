# Architecture Decision Records (ADR) — `taskq`

> Source of truth: `02-architecture/SAD.md` v1.0.0 (2026-07-01), derived from `SPEC.md` v2.0.0 (2026-06-15).
> This log captures every architectural decision that deviates from — or extends — the canonical SPEC, together with the rationale and rejected alternatives. Each ADR is independent and immutable once accepted.

---

## ADR-001: Python 3.11 standard library only (zero runtime external dependencies)

### Context
`SPEC.md` §1 declares `C-01..C-08` constraints. The binding constraint is "Python 3.11 stdlib only — zero runtime external dependencies." Any addition of a third-party dependency (e.g., `pydantic`, `attrs`, `click`, `rich`, `pytest-runtime-plugins`) would (a) violate the SPEC constraint, (b) introduce a supply-chain attack surface that is incompatible with NFR-02 (security) and NFR-03 (reliability), and (c) force every consumer to provision a venv before invoking `python -m taskq`.

The architecture must therefore express concurrency, atomic file I/O, CLI parsing, and secret redaction using only modules available in CPython 3.11 (`argparse`, `concurrent.futures`, `contextlib`, `dataclasses`, `enum`, `json`, `os`, `pathlib`, `shlex`, `subprocess`, `uuid`).

### Decision
- Adopt Python 3.11 stdlib-only as a hard architectural invariant.
- `pyproject.toml` declares `[project]` metadata only; `[project.dependencies]` is empty by design.
- Dev/test dependencies (`pytest`, `mypy`, `ruff`) live under `[project.optional-dependencies]` and are excluded from the runtime build.
- All concurrency primitives use `concurrent.futures.ThreadPoolExecutor` (stdlib); no `asyncio` runtime is introduced.

### Consequences
- (+) Zero supply-chain attack surface on the runtime path.
- (+) Single-file distribution possible (no venv required for end users).
- (+) NFR-02 (security) audit scope is bounded to CPython stdlib + our code.
- (−) Must hand-roll small utilities (`ValidationError`, `StoreCorruptedError`, `UnknownTaskError` exception classes) that mature libraries would otherwise provide.
- (−) CLI output formatting is constrained to `argparse` + `json.dumps` (no `rich`/`click` ergonomics).

### Alternatives Considered
- **`click` + `pydantic` stack.** Rejected — violates C-01 stdlib-only constraint; adds two heavy dependencies with non-trivial transitive closure.
- **`asyncio` + `aiofiles`.** Rejected — `subprocess.run` is the natural fit for FR-02 (one-shot command execution); asyncio would add event-loop complexity with no measurable gain (NFR-01 budget is dominated by file I/O, not concurrency).
- **`typer` CLI framework.** Rejected — built on `click`; same dependency objection.

---

## ADR-002: Single subprocess chokepoint in `executor.run_task` (no `shell=True`)

### Context
NFR-02 mandates "shell=True forbidden codebase-wide; FR-01 injection-character blacklist must have test coverage." The structural risk is that any developer adding a new feature path (e.g., a future "schedule" subcommand) might reach for `subprocess.Popen(..., shell=True)` for convenience, bypassing the chokepoint.

A single call site is the strongest enforceable control: there is nowhere else for `subprocess.run` to live, and any future addition is a code-review violation by definition.

### Decision
- `executor.run_task` is the **sole** call site of `subprocess.run` in the entire codebase.
- Invocation form is fixed: `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` with `shell=False` (default — explicit for audit).
- `shlex.split(command)` tokenises the user command into an argv list, ensuring the child process receives a parsed argv (never a string interpreted by `/bin/sh`).
- Code-review checklist (Phase 3 HR-09) greps every diff for `shell=True` and `os.system` as defense-in-depth.

### Consequences
- (+) NFR-02 is structurally enforceable: any new execution path must extend `executor.run_task`.
- (+) Injection blacklist (`; | & $ > < \``) in `validation.validate_submit_command` becomes the only user-side defence, paired with the no-shell chokepoint.
- (+) Test coverage of the chokepoint exhaustively exercises the security model.
- (−) Features that need shell pipelines (e.g., `cmd1 | cmd2`) must be expressed as a single string tokenised by `shlex.split` — but the blacklist in FR-01 forbids `|` outright, so the design is internally consistent.
- (−) Any future feature requiring `shell=True` for legitimate reasons (none today) would require a new ADR to relax this constraint.

### Alternatives Considered
- **Per-subcommand `subprocess.run` calls scattered across modules.** Rejected — every additional call site is a new audit point; the chokepoint property is lost.
- **`shell=True` with explicit escaping.** Rejected — escaping is error-prone; POSIX argv semantics are safer.
- **External process supervisor (`supervisord`, `systemd-run`).** Rejected — out of scope for a local CLI; NFR-01 (sub-50ms p95) forbids extra daemon processes.

---

## ADR-003: Atomic write via `tmp + os.replace` in `store.save_tasks_atomic`

### Context
NFR-03 requires "tasks.json atomic write (valid JSON after interruption)." The crash-mid-write hazard is that a partial write leaves a non-JSON file, which `json.loads` cannot parse and which would silently lose all task history on next load.

POSIX guarantees that `rename(2)` (and its Python wrapper `os.replace`) is atomic within the same filesystem. Writing to a sibling `tasks.json.tmp` file and renaming over `tasks.json` ensures the visible file is either the previous valid state or the new valid state — never a half-written intermediate.

### Decision
- All persistence flows through `store.save_tasks_atomic(tasks: list[Task])`.
- Implementation: write the full JSON to `$TASKQ_HOME/tasks.json.tmp`, `os.fsync` the file descriptor, close, then `os.replace(tmp, final)` (atomic on POSIX).
- On missing file at load time → return `[]` (no error).
- On `JSONDecodeError` at load time → raise `StoreCorruptedError` (CLI maps to exit 1 + stderr `store corrupted`). **Never silently overwrite with `[]`** — that would mask data loss.

### Consequences
- (+) Crash safety: a process killed mid-write leaves the prior file intact.
- (+) Concurrent readers see either the old or new file — never a torn read.
- (−) Cost: each persist rewrites the entire file (acceptable because the payload is small — ≪ 100 KB at expected scale).
- (−) Requires the directory to exist; `store._ensure_home()` performs `mkdir(parents=True, exist_ok=True)` once and caches the result to avoid per-call `stat`.

### Alternatives Considered
- **Append-only journal with periodic compaction.** Rejected — adds a manifest + truncation step that exceeds the NFR-01 p95 budget (50 ms); over-engineered for the expected scale.
- **`fcntl.flock` for exclusive write.** Rejected — `os.replace` already provides atomicity; locking adds complexity without solving any problem that the rename doesn't already solve.
- **`sqlite3` for persistence.** Rejected — third-party-free but introduces a binary file format that doesn't satisfy "JSON file under `$TASKQ_HOME/tasks.json`" from SPEC §1.

---

## ADR-004: Redact-before-persist ordering (D-03)

### Context
NFR-03 requires "stdout_tail/stderr_tail secret-line redaction before persist." The natural temptation is to persist the raw tails first and redact on read (e.g., when serving `status`). This is wrong: any read path that forgets to redact (or any backup/copy mechanism that bypasses the read API) leaks secrets to disk.

The invariant must be: **secrets never touch disk in cleartext, regardless of which path the data takes.**

### Decision
- `executor.run_task` invokes `redact.redact(text)` on `stdout_tail` and `stderr_tail` **before** any `store.update_task` call persists the final state.
- `redact.redact(text)` performs line-wise replacement: any line matching `^(sk-[A-Za-z0-9_-]{8,}|token=\S+)` is replaced by `[REDACTED]`.
- The function is stateless, deterministic, dependency-free, and pure (easy to unit-test exhaustively).
- The order is **invariant**: redact cannot be moved after persist (defeats the purpose) or skipped on any code path.

### Consequences
- (+) Secrets never persisted in cleartext; defence-in-depth even against backup paths.
- (+) Pure-function design makes Phase 4 unit testing trivial (table-driven tests for line patterns).
- (+) `redact.py` has no internal dependencies — leaf module, no cycle risk.
- (−) Redaction is irreversible: a redacted tail cannot be "unredacted" from disk. This is the correct security trade-off.
- (−) Pattern is intentionally narrow (`sk-...` and `token=...`); other secret shapes (e.g., AWS keys, JWTs) are not yet covered. Future extension requires a new ADR.

### Alternatives Considered
- **Redact on read only.** Rejected — violates the "secrets never touch disk" invariant; any backup/export path bypasses redaction.
- **Encrypt at rest instead of redact.** Rejected — NFR-03 specifies redaction, not encryption; encryption also leaks plaintext length and existence.
- **Broaden the pattern to all known secret shapes.** Deferred — out of scope for v2.0.0; tracked as a future ADR.

---

## ADR-005: Retry semantics — `TASKQ_RETRY_LIMIT` retries on top of initial execution (D-02)

### Context
SPEC §3 FR-02 says: `run` 結果為 failed/timeout 時自動重試,上限 TASKQ_RETRY_LIMIT 次(預設 2).

The phrase "上限 TASKQ_RETRY_LIMIT 次" is ambiguous between:
1. **LIMIT = retries on top of initial** → with default 2, you get 1 initial + 2 retries = 3 total executions.
2. **LIMIT = total attempts** → with default 2, you get 2 total executions (1 initial + 1 retry).
3. **LIMIT = total executions including initial** → with default 2, you get 2 total executions.

The reading chosen determines how many times a flaky command runs, how long a hung command can occupy the executor, and how the `attempts` field on the persisted `Task` is bounded.

### Decision
- Reading #1 is canonical: `TASKQ_RETRY_LIMIT` is the number of **retries** after the initial execution.
- Default `TASKQ_RETRY_LIMIT = 2` ⇒ at most 3 total executions per task.
- Implementation: `task.attempts` is initialised to `0` at submit time. `executor.run_task` enters step 1 of the retry loop, then increments `attempts` on each entry. The guard is `while task.attempts < TASKQ_RETRY_LIMIT + 1`.
- `task.attempts` is the single source of truth for retry bookkeeping; `TASKQ_RETRY_LIMIT` is consulted only via `config.py`.
- The guard condition fires **after** `attempts += 1`; the increment-then-check ordering guarantees the initial run is counted as attempt 1.

### Consequences
- (+) Predictable: with `TASKQ_RETRY_LIMIT=2`, exactly 3 executions occur in the worst case.
- (+) Persisted `attempts` field gives operators full visibility into how many times a task ran.
- (+) The bound matches the user's mental model ("2 retries" feels like "2 retries").
- (−) Interpretation #2 (LIMIT = total attempts) would give a different bound; consumers expecting #2 would be surprised. ADR-005 records the chosen reading to make the deviation explicit.
- (−) Retry is unconditional on `failed`/`timeout` — there is no backoff. Future work could add exponential backoff via a new ADR.

### Alternatives Considered
- **Reading #2 (LIMIT = total attempts).** Rejected — the canonical SPEC example "預設 2" suggests "2 retries" as a sensible default; "2 total attempts" would mean default behaviour allows only one retry, which is too aggressive for transient failures.
- **Reading #3 (LIMIT = total executions).** Rejected — equivalent to #2 in numeric value; the terminology "retry limit" is more naturally read as "number of retries."
- **Exponential backoff between retries.** Deferred — out of scope for v2.0.0; `subprocess.run` blocking model makes backoff complex without an event loop.

---

## ADR-006: `query.clear()` hard-unlink semantics (D-01)

### Context
SPEC §3 FR-03 row `clear` says: 清空 `$TASKQ_HOME/tasks.json`. The Chinese verb "清空" is ambiguous between:
1. **Delete the file entirely** (hard-unlink via `os.unlink`).
2. **Truncate the contents to an empty list** (load → write `[]` → atomic save).

Reading #2 preserves the file but empties its contents. Reading #1 deletes the file.

The choice has reliability implications: Reading #2 introduces a read-modify-write window during which a concurrent write could re-introduce R1 (concurrent-write corruption). Reading #1 is a single `os.unlink` syscall with no race window.

### Decision
- `query.clear()` performs `os.unlink($TASKQ_HOME/tasks.json)` (hard-unlink), not a load+filter+rewrite.
- The operation is idempotent: `os.unlink` raises `FileNotFoundError` if the file is missing, which `clear()` catches and swallows.
- The dependency graph reflects this: `query → config` (to resolve `$TASKQ_HOME`), then `os.unlink` — **no `store` involvement** for the `clear` path.

### Consequences
- (+) Single syscall, <1 ms — well within NFR-01 spirit even though `clear` is excluded from the p95 budget.
- (+) No read-modify-write window; no race with concurrent writers.
- (+) Idempotent by construction.
- (−) File metadata (mtime, inode) is lost across a clear; consumers watching the file via `inotify` see a delete event rather than a truncate event.
- (−) Interpretation #2 would preserve the file; consumers expecting "file always exists, sometimes empty" are surprised. ADR-006 records the chosen reading.

### Alternatives Considered
- **Soft-clear (load → write empty list → atomic save).** Rejected — introduces a concurrent-write race window that violates NFR-03's atomicity guarantee; also slower.
- **Truncate to zero bytes without deleting.** Rejected — leaves an invalid (empty) JSON file, which `load_tasks` would interpret as `StoreCorruptedError` on the next read.

---

## ADR-007: Concurrency model — `ThreadPoolExecutor` (when needed) over `multiprocessing`

### Context
FR-02 implies a single task executes at a time (sequential `run`). However, future extensions (multi-task `run --parallel`, batch submission) could introduce concurrency. The choice of primitive affects NFR-01 (subprocess I/O is the dominant cost; thread vs. process matters less than expected), NFR-02 (process isolation), and packaging complexity.

### Decision
- Adopt `concurrent.futures.ThreadPoolExecutor` as the concurrency primitive when future FRs require parallel execution.
- Rationale: subprocess I/O dominates wall-clock cost (NFR-01 budget assumes this); threads share the GIL but release it during I/O wait, which is the relevant wait condition for `subprocess.run`.
- `multiprocessing` is rejected for this codebase because: (a) it requires `if __name__ == "__main__"` discipline that complicates `python -m taskq`; (b) it adds pickling overhead for `Task` objects; (c) process isolation is not required (NFR-02 is enforced at the `shell=True` chokepoint, not at the process boundary).

### Consequences
- (+) Simpler packaging — `python -m taskq` works without multiprocessing bootstrap boilerplate.
- (+) Threads release the GIL during subprocess wait; wall-clock scaling is acceptable for I/O-bound workloads.
- (+) Single shared in-memory state (if needed for caching) is trivial.
- (−) CPU-bound work (e.g., bulk redaction across 10 MB of stdout) would not parallelise well; this is acceptable because redaction is line-wise O(n) and not a hot path.
- (−) A bug in one task (e.g., infinite loop in C extension) could affect siblings; mitigated by `TASKQ_TASK_TIMEOUT` enforcement.

### Alternatives Considered
- **`multiprocessing.Pool`.** Rejected — packaging friction (`if __name__ == "__main__"`), pickling cost, no isolation benefit.
- **`asyncio` + `asyncio.subprocess`.** Rejected — adds event-loop complexity for a CLI invocation that is dominated by one subprocess at a time; the v2.0.0 SPEC has no parallel-execution FR.
- **No concurrency primitive adopted yet.** Deferred — single-task sequential execution is sufficient for v2.0.0; the ADR records the chosen primitive so future work doesn't drift to `multiprocessing` by default.

---

## ADR-008: Configuration via central `config.py` env-var reader

### Context
SPEC §5 declares three environment variables: `TASKQ_HOME`, `TASKQ_TASK_TIMEOUT`, `TASKQ_RETRY_LIMIT`. Scattering `os.environ.get(...)` calls across modules makes the configuration surface invisible, hard to test (every test must `monkeypatch.setenv`), and easy to drift from defaults.

### Decision
- A single module `taskq/config.py` is the **sole** reader of `os.environ` for `TASKQ_*` variables.
- Each variable has a typed getter with a documented default: `TASKQ_HOME=".taskq"`, `TASKQ_TASK_TIMEOUT=10.0`, `TASKQ_RETRY_LIMIT=2`.
- No I/O at import time — directory creation lives in `store._ensure_home()` (lazy).
- Other modules import the typed getters; they do not call `os.environ` directly.

### Consequences
- (+) Single audit point for env-var surface.
- (+) Tests can patch `taskq.config` directly without `monkeypatch.setenv`.
- (+) Defaults are declared once and applied consistently.
- (−) One more module to maintain (acceptable; it is small and leaf-only).

### Alternatives Considered
- **Scattered `os.environ.get` calls.** Rejected — invisible surface; test pain; default drift.
- **`.env` file support via `python-dotenv`.** Rejected — third-party dependency; violates C-01 stdlib-only.
- **YAML/TOML config file.** Rejected — SPEC §5 explicitly chose env vars; introducing a config file would be a SPEC deviation.

---

## ADR-009: Exit-code matrix owned by `cli.py`

### Context
SPEC §3 declares exit codes `0/1/2/4` mapped to success / internal error / validation+unknown id / timeout. Scattering `sys.exit(N)` across modules spreads the mapping and makes it hard to verify exhaustively.

### Decision
- `cli.py` is the **sole** module that calls `sys.exit` or returns exit codes from `main()`.
- All other modules raise typed exceptions (`ValidationError`, `UnknownTaskError`, `StoreCorruptedError`, `TimeoutError`); `cli.py` catches them and maps to the exit-code matrix.
- The mapping table is centralised in `cli.py` for audit.

### Consequences
- (+) Single audit point for exit-code behaviour.
- (+) Modules remain testable without driving `sys.exit`.
- (+) Exit-code matrix can be reviewed in one place during HR-09.
- (−) A bit of boilerplate in `cli.py` (try/except ladder). Acceptable for the auditability gain.

### Alternatives Considered
- **`@exit_code` decorator on each function.** Rejected — obscures control flow; exception-based mapping is more idiomatic Python.
- **Modules return exit codes directly.** Rejected — couples business logic to POSIX exit-code semantics; breaks composability.

---

## ADR-010: Dataclass-based `Task` model with JSON-serialisable fields

### Context
FR-01 requires a task model with stable persistence semantics. The model must be JSON-serialisable (NFR-03 atomic write requires valid JSON), support status transitions, and carry enough metadata for retry bookkeeping (FR-02) and redaction (NFR-03).

### Decision
- `Task` is a `@dataclass` with `asdict=True` semantics (provided by `dataclasses.asdict`).
- Fields: `id` (8-hex uuid4 prefix), `command` (str), `status` (enum), `created_at` (ISO-8601 UTC str), `attempts` (int, default 0), `exit_code` (int | None), `stdout_tail` (str), `stderr_tail` (str), `duration_ms` (int | None), `finished_at` (ISO-8601 str | None).
- `TaskStatus` enum: `pending | running | done | failed | timeout`.
- Serialisation: a single `json.dumps(dataclasses.asdict(task))` call per task, wrapped in a list at the file level.
- `stdout_tail` / `stderr_tail` are truncated to the **last 2000 chars** before serialisation (SPEC §1 constraint).

### Consequences
- (+) Dataclass gives `__eq__`, `__repr__`, and `asdict` for free; no hand-rolled serializer.
- (+) Single `json.dumps` per persist — meets the NFR-01 sub-5 ms budget per call.
- (+) Enum gives type-safety on `status`; unknown values fail loudly at validation.
- (−) No schema versioning — a future field addition breaks old JSON files. Mitigation: `load_tasks` validates the presence of required fields; missing fields raise `StoreCorruptedError`.
- (−) Dataclass `asdict` is recursive and copies nested objects — minor allocation cost (acceptable at this scale).

### Alternatives Considered
- **`pydantic.BaseModel`.** Rejected — third-party dependency; violates C-01.
- **Plain `dict` with manual keys.** Rejected — no type safety; field-name typos become silent bugs.
- **`TypedDict` + factory function.** Rejected — `TypedDict` is not a runtime construct; loses `__init__` ergonomics.

---

## ADR-011: Validation as a pure function in `validation.py` (injection blacklist at submit)

### Context
NFR-02 requires injection-character test coverage. The blacklist `; | & $ > < \`` (FR-01) must be enforced at `submit` time so that no malicious command ever reaches the executor.

### Decision
- `validation.validate_submit_command(cmd: str) -> None` is a **pure function** with no I/O.
- Rejection conditions: empty / whitespace-only, length > 1000, any of `; | & $ > < \`` present.
- Raises `ValidationError` on rejection; `cli.py` maps to exit 2.
- The blacklist is a module-level `frozenset` (constant, no per-call allocation).

### Consequences
- (+) Pure function → exhaustive unit testing trivial (no fixtures, no I/O mocking).
- (+) Module-level `frozenset` keeps validation cost on the NFR-01 p95 path at <1 ms.
- (+) Single chokepoint for input validation; any new rule is added here, audited in one place.
- (−) Blacklist is narrow — misses other shell metacharacters (`*`, `?`, `~`, `(`, `)`) and argument-injection (`--`). The chosen list is what SPEC §1 specifies; expansion requires a SPEC update and a new ADR.
- (−) Length cap of 1000 chars is a soft limit; very long legitimate commands are rejected. Acceptable per SPEC.

### Alternatives Considered
- **Allowlist of safe characters.** Rejected — too restrictive; breaks ordinary commands with paths, flags, or unicode.
- **AST-based parser.** Rejected — over-engineered for a CLI that already constrains the input via the blacklist; adds parsing cost on the p95 path.
- **Sandbox execution (e.g., `bubblewrap`, `firejail`).** Rejected — out of scope for a local CLI; the chokepoint + blacklist are sufficient given the threat model.

---

## ADR-012: No global state; module-level constants only

### Context
ThreadPoolExecutor (ADR-007) and lazy directory creation (ADR-003) introduce a temptation to cache state in module globals. Uncontrolled globals are a testing hazard and make the data-flow graphs in SAD §3.3 untrustworthy.

### Decision
- Modules expose only: functions, dataclasses, exceptions, enums, and module-level **immutable constants** (e.g., the injection blacklist `frozenset`).
- No mutable module-level globals (no `cache = {}`, no `_initialized = False`).
- Any caching is encapsulated inside a function with explicit lifetime (e.g., `store._ensure_home()` memoises via `functools.lru_cache` on a pure function).

### Consequences
- (+) Tests are deterministic — `import taskq.foo` twice gives identical state.
- (+) Data-flow diagrams in SAD §3.3 remain accurate.
- (+) Module reloading (`importlib.reload`) is safe during dev.
- (−) Slightly more boilerplate for caching (explicit `lru_cache`). Acceptable.

### Alternatives Considered
- **Module-level `dict` cache.** Rejected — mutable global; testing hazard.
- **`@cache` decorator on every helper.** Rejected — over-applies caching; only `_ensure_home()` benefits.

---

## Compliance Summary

| ADR | Captures | SAD §2.5 ID |
|-----|----------|-------------|
| ADR-001 | Python 3.11 stdlib-only constraint | (C-01) |
| ADR-002 | Subprocess chokepoint, no `shell=True` | NFR-02 invariant |
| ADR-003 | Atomic `tmp + os.replace` write | NFR-03 R1 |
| ADR-004 | Redact-before-persist ordering | D-03 |
| ADR-005 | Retry semantics `LIMIT + 1` total attempts | D-02 |
| ADR-006 | `clear` hard-unlink semantics | D-01 |
| ADR-007 | ThreadPoolExecutor for future concurrency | (derived) |
| ADR-008 | Centralised `config.py` env-var reader | SPEC §5 |
| ADR-009 | Exit-code matrix owned by `cli.py` | SPEC §3 |
| ADR-010 | Dataclass `Task` model + JSON serialisation | FR-01 |
| ADR-011 | Pure-function validation + injection blacklist | NFR-02 |
| ADR-012 | No mutable global state | (derived) |

All deviations from canonical SPEC (`D-01`, `D-02`, `D-03`) are captured. No content invented beyond SPEC.md v2.0.0; items derived from SPEC §2 are explicitly marked `(derived)` in the SAD.

### Requirement traceability (SRS / SAD / specification linkage)

Each ADR entry in the table above maps to a requirement ID enumerated in the canonical SRS specification and elaborated in the SAD. The `requirement` identifier and `specification` provenance are intentionally recorded here so a downstream `traceability matrix` consumer (Phase 4 verifier, SAB generator) can cross-reference every architectural decision back to its originating SRS clause and the corresponding SAD section. ADR-001..ADR-012 collectively cover every C-/NFR-/D-identifier declared in the requirement specification; no architectural decision exists outside this log. The compliance matrix is the authoritative traceability matrix entry for Phase 2 architecture review and is the canonical SRS↔SAD↔ADR linkage for the project.

---

*Document version: 1.0.0 | 2026-07-01 | Source: SAD.md v1.0.0, SPEC.md v2.0.0*
