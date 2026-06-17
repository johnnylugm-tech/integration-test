# SAD - taskq (Software Architecture Document)

> Project: taskq (本地任務佇列 CLI)
> Version: v1.0
> Date: 2026-06-17
> Phase: 2 — Architecture & Design
> Source of truth: SRS.md v2.0.0 (P1 APPROVED 2026-06-17) + TEST_INVENTORY.yaml v1.1
> Authoring mode: INGESTION (architecture derived strictly from P1 FRs/NFRs, no invention)

---

## 1. Architecture Overview

`taskq` is a local task-queue CLI implemented in Python 3.11 standard library only (zero runtime external dependencies). It accepts a shell command as a job, persists it to a JSON store under `$TASKQ_HOME/tasks.json`, and executes it later under a controlled `subprocess.run` call with a timeout and a bounded auto-retry policy. The tool exists to lift batch/retry-style local command execution out of ad-hoc shell scripts, exposing it instead as a uniform command-line surface with consistent exit codes (0/2/4/1), atomic persistence, and secret redaction of subprocess output. The product surface is intentionally narrow — three functional requirements covering model+persistence, controlled execution+retry, and CLI/query integration — and explicitly excludes daemonization, remote execution, and any non-JSON persistence backend.

The architecture is decomposed into **four source modules**, each occupying its own directory under `core/taskq/`:

1. **`taskq.cli/`** — entry point (`python -m taskq`), argparse subcommand dispatch, per-subcommand handlers, and human/JSON output formatting. CLI is the only module that reads `sys.argv` and writes to `sys.stdout`/`sys.stderr`; it is the single import point for `argparse` and is the *only* place that maps domain outcomes to the four exit codes.
2. **`taskq.store/`** — JSON file persistence with atomic-write semantics (tmp + `os.replace`), task-record validation, uuid4 8-hex id generation, and corruption detection. Store is the sole module that reads or writes `tasks.json`; nothing else in the codebase may touch the path.
3. **`taskq.executor/`** — `subprocess.run` wrapper that enforces `shell=False` and `shlex.split`, drives the `pending → running → done | failed | timeout` state machine, applies the retry policy, redacts secret-bearing lines from `stdout_tail` / `stderr_tail`, and records `duration_ms` and `finished_at`.
4. **`taskq.config/`** — `TASKQ_HOME` / `TASKQ_TASK_TIMEOUT` / `TASKQ_RETRY_LIMIT` env-var reader with defaults and per-process snapshot. Config is a pure value layer; it has no I/O of its own and is read once at process start.

The core data flow is a subprocess-orchestrated, JSON-file-mediated pipeline. On `submit`, CLI parses argv, hands the command to `store.submit_task` which validates, generates a uuid4 8-hex id, attaches `created_at`, and writes the store via the atomic-write helper. On `run`, CLI loads the task by id, transitions it to `running` via the store, and delegates to `executor.run_task` which spawns the subprocess, captures output, redacts secrets, transitions the state to `done`/`failed`/`timeout`, and persists the result record. The store is therefore the single point of truth across the whole pipeline; executor and CLI are stateless with respect to long-lived data. The **store is the spine** of the architecture — it owns persistence, ids, validation, and corruption detection — and the **executor is the riskiest module** (subprocess + redaction), with **store a close second** (atomic-write + corruption detection).

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
| Source directories count? | 3-6 |
| Each dir has a hub file? | Yes |
| Hub has ≥2 functions if ≥4 sibling files? | Yes |
| Entry points inside a hub dir? | Yes |
| Each function body calls a hub function? | Yes (not just module-level) |
| Cross-file calls use standalone assignment? | Yes |
| Community size ≤ 50 nodes? | Yes |
| Edge budget: I ≥ 0.4286 × E? | Yes |

**Anti-patterns that produce low scores:**

```
❌ src/__init__.py, src/main.py, src/models.py, src/cli.py, src/audio.py
   → 5 isolated files in flat src/, zero cross-imports → cohesion=0.0

❌ src/cli.py  (imports httpx, argparse, asyncio — all external, no internal sibling calls)
   → pure external edges, no compensation → cohesion near 0

❌ tests/test_fr01.py, tests/test_fr02.py, ... tests/test_fr08.py
   → 80 nodes in one dir, no internal edges → oversized + zero cohesion

✅ src/api/{cli,main,speech,utils}.py with utils imported by all siblings → hub-and-spoke
✅ src/engines/{synthesis,splitter,parser}.py with synthesis calling both → pipeline chain
✅ src/infrastructure/{circuit,health,config,models}.py → shared domain layer
```

**Mapping to taskq's 4 source directories.** `taskq` adopts the 4-directory decomposition with one hub per directory:

- `core/taskq/cli/` — entry point + dispatch + per-subcommand handlers + format helpers
- `core/taskq/store/` — JSON persistence + atomic write + validation
- `core/taskq/executor/` — subprocess.run wrapper + state machine + retry
- `core/taskq/config/` — env var reader + defaults

The 4-directory design satisfies Principle 1 (4 source dirs in the 3-6 sweet spot), Principle 3 (entry point lives in `cli/` alongside the format hub, not at project root), and is sized well under the 50-node cap (Principle 6). Hub function coverage per directory is specified in §2.2 to satisfy Principle 2 / 4.

**Per-function-body hub-call coverage (Principle 4 enforcement plan).** Each sibling file in a 2+ file directory calls its directory's hub from every non-trivial function body, not just at module level. This enumeration satisfies CRG Principle 4 — auditors can verify hub coverage by reading the code without re-deriving the rule.

| Directory | Hub (≥2 fns) | Sibling files (must call hub from every fn body) |
|-----------|-------------|--------------------------------------------------|
| `core/taskq/cli/` | `format.py::render_json`, `format.py::render_human` | `handlers.py` (every `cmd_*` fn body calls `render_*` once for output + once for errors via `render_error`) |
| `core/taskq/store/` | `persistence.py::atomic_write`, `persistence.py::load_store` | `tasks.py` (`submit_task`, `update_task`, `clear_store` all call `atomic_write`; `get_task`, `clear_store`, `load_store` paths call `load_store`) |
| `core/taskq/executor/` | `runner.py::run_subprocess`, `runner.py::transition` | `state_machine.py` (`apply_transition` calls `transition`); `retry.py` (`run_with_retry` calls `run_subprocess` per attempt + `transition` for each attempt's status update) |
| `core/taskq/config/` | `env.py::read_env`, `env.py::coerce` | `paths.py` (`resolve_home` and `tasks_json_path` both call `read_env` to resolve `TASKQ_HOME`; coercion of `TASKQ_TASK_TIMEOUT`/`TASKQ_RETRY_LIMIT` calls `coerce` once per process) |

For directories with <4 siblings, **one hub function is sufficient** — `config/` has only 2 sibling files (`env.py`, `paths.py`) so the 2-fn minimum is comfortably met without artificial splitting.

---

### 2.2 Module Specifications

#### 2.2.1 `core/taskq/cli/` — CLI entry + dispatch

| Attribute | Value |
|-----------|-------|
| Responsibility | argparse subcommand dispatch; parse argv; delegate to store/executor; map domain outcomes to exit codes 0/2/4/1; render human and `--json` output |
| External Interface | `main(argv: list[str] \| None = None) -> int` (returns exit code); per-subcommand handlers `cmd_submit`, `cmd_run`, `cmd_status`, `cmd_list`, `cmd_clear` |
| Dependencies | `taskq.store` (submit / load / save), `taskq.executor` (run_task), `taskq.config` (TASKQ_HOME for store path resolution) — must NOT be called by store or executor |
| Hub module | `format.py` (≥2 hub functions: `render_json`, `render_human` — called from every handler body to satisfy Principle 4) |

**File layout:**
- `__init__.py` — re-exports `main` for `python -m taskq`
- `main.py` — `argparse` setup, global `--json` flag, dispatch to per-subcommand handler, exit-code mapping
- `handlers.py` — `cmd_submit`, `cmd_run`, `cmd_status`, `cmd_list`, `cmd_clear`
- `format.py` — `render_json(payload)`, `render_human(subcommand, payload)`, `render_error(exit_code, msg)` — hub
- `exitcodes.py` — module-level constants `EXIT_OK=0`, `EXIT_VALIDATION=2`, `EXIT_TIMEOUT=4`, `EXIT_INTERNAL=1`

**Logical Constraints:**
- `cli` is the **only** module that imports `argparse` and `sys` (per Principle 3 entry-point pattern).
- `cli` is the **only** module that writes to `sys.stdout` / `sys.stderr`.
- `cli` MUST NOT use `try/except` to swallow `StoreCorrupted`; the corruption path must propagate to `sys.exit(EXIT_INTERNAL)` with a stderr line `store corrupted` (FR-01 / NFR-03 contract).
- `cli` MUST map `executor.TimeoutExpired`-equivalent results to exit 4 only when running in single-task mode (`run`); for `submit`/`status`/`list`/`clear` the timeout classification is unreachable.
- `--json` output MUST be a single line of valid JSON written to `stdout`, with human messages suppressed.

---

#### 2.2.2 `core/taskq/store/` — JSON persistence + atomic write + validation

| Attribute | Value |
|-----------|-------|
| Responsibility | Validate command input (non-empty / length ≤ 1000 / injection char blacklist); generate uuid4 8-hex task id; atomic write of `tasks.json` via tmp + `os.replace`; corruption detection; CRUD over the task record |
| External Interface | `submit_task(command: str) -> str` (returns task id), `load_store() -> dict[str, Task]`, `save_store(store: dict) -> None` (atomic), `get_task(task_id: str) -> Task \| None`, `update_task(task_id: str, **fields) -> Task`, `clear_store() -> None` |
| Dependencies | `taskq.config` (read `TASKQ_HOME` to resolve `tasks.json` path) — must NOT import cli or executor |
| Hub module | `persistence.py` (≥2 hub functions: `atomic_write`, `load_store` — both called from `submit_task`, `update_task`, `clear_store`, and the corruption-detection entry point) |

**File layout:**
- `__init__.py` — re-exports public API
- `models.py` — `Task` dataclass, `StoreCorrupted` exception
- `validation.py` — `validate_command(command: str) -> None` (raises `ValidationError` on rule violation), `INJECTION_CHARS = ";|&$><`"`, `MAX_COMMAND_LENGTH = 1000`
- `persistence.py` — `atomic_write(path, payload)`, `load_store()`, `save_store(store)` — hub
- `tasks.py` — `submit_task`, `get_task`, `update_task`, `clear_store` (thin orchestration over hub)
- `ids.py` — `generate_task_id() -> str` (uuid4 hex prefix 8)

**Logical Constraints:**
- `store` is the **only** module that imports `json`, `os.replace`, and writes to `tasks.json`.
- Atomic write contract: write to `tasks.json.tmp` first, then `os.replace(tmp, final)`; on partial write the original remains valid (NFR-03 / R1).
- `load_store()` MUST raise `StoreCorrupted` on `json.JSONDecodeError` — **no silent rebuild** (FR-01 / NFR-03). The CLI maps `StoreCorrupted` to exit 1.
- `validate_command` MUST be called *before* id generation; a validation failure MUST NOT mutate the store.
- The injection char set is exactly `;`, `|`, `&`, `$`, `>`, `<`, `` ` `` — six characters, no more, no fewer (NFR-02 contract; parametrized test must cover all six).
- `Task.id` format constraint: 8 lowercase hex characters (uuid4 `hex[:8]`).

---

#### 2.2.3 `core/taskq/executor/` — subprocess.run wrapper + state machine + retry

| Attribute | Value |
|-----------|-------|
| Responsibility | Drive the `pending → running → done | failed | timeout` state machine; invoke `subprocess.run(shlex.split(command), shell=False, capture_output=True, text=True, timeout=...)`; redact `stdout_tail` / `stderr_tail` before persist; auto-retry up to `TASKQ_RETRY_LIMIT` on `failed`/`timeout`; record `duration_ms` and `finished_at` |
| External Interface | `run_task(task: Task) -> RunResult` (mutates store via `taskq.store.update_task`), `RunResult` dataclass: `{status: Literal['done','failed','timeout'], exit_code: int, stdout_tail: str, stderr_tail: str, duration_ms: int, finished_at: str}` |
| Dependencies | `taskq.store` (load task by id, persist result fields), `taskq.config` (read `TASKQ_TASK_TIMEOUT`, `TASKQ_RETRY_LIMIT`) — must NOT import cli |
| Hub module | `runner.py` (≥2 hub functions: `run_subprocess`, `transition` — both called from every retry/state-machine path to satisfy Principle 4) |

**File layout:**
- `__init__.py` — re-exports `run_task`
- `runner.py` — `run_subprocess(command, timeout) -> CompletedProcess` wrapper (enforces `shell=False`, `shlex.split`); `transition(task_id, **fields)` — hub
- `state_machine.py` — `apply_transition(task, event) -> Task`; transitions: `pending → running → {done, failed, timeout}`; rejects illegal transitions
- `retry.py` — `run_with_retry(task, max_attempts) -> RunResult`; calls `runner.run_subprocess` up to `1 + TASKQ_RETRY_LIMIT` times on `failed`/`timeout`
- `redaction.py` — `redact(text: str) -> str`; replaces any line matching `sk-[A-Za-z0-9_-]{8,}` or `token=\S+` with `[REDACTED]`; preserves non-matching lines — hub for NFR-03 secret redaction
- `result.py` — `RunResult` dataclass; `tail(text, n=2000) -> str` helper for stdout/stderr cap

**Logical Constraints:**
- `executor` is the **only** module that imports `subprocess` and `shlex`.
- `shell=False` is a hard invariant. Any use of `shell=True` in `core/taskq/` violates NFR-02 and fails the codebase-wide static scan (`test_redteam_shell_true_absent_in_codebase`).
- State machine MUST reject `running → pending` (regression) and any direct `pending → done` (must go through `running`).
- `run_with_retry` MUST bound total attempts at `1 + TASKQ_RETRY_LIMIT` (FR-02 contract; `test_fr02_run_retry_limit_respected`).
- `redact` MUST be called on `stdout_tail` and `stderr_tail` *before* `store.update_task` persists them — the on-disk store MUST NEVER contain an unredacted secret line (NFR-03 / R3).
- `tail` MUST cap each side at 2000 characters (`test_fr02_run_captures_stdout_tail_under_2000_chars` / `..._stderr_tail_under_2000_chars`).
- `TimeoutExpired` MUST be classified as `status='timeout'` and surfaced to caller as a `Timeout` result type that CLI maps to exit 4 in single-task mode (FR-02 / `test_fr02_run_timeout_yields_timeout_and_exit_four`).

---

#### 2.2.4 `core/taskq/config/` — env var reader + defaults

| Attribute | Value |
|-----------|-------|
| Responsibility | Read three `TASKQ_*` env vars with their declared defaults; resolve `$TASKQ_HOME` to an absolute path; produce a per-process immutable snapshot consumed by store and executor |
| External Interface | `Config` dataclass with fields `taskq_home: Path`, `task_timeout: float`, `retry_limit: int`; factory `load_config() -> Config`; `tasks_json_path() -> Path` helper |
| Dependencies | None (must remain a leaf module with zero internal edges) |
| Hub module | `env.py` (≥2 hub functions: `read_env`, `coerce` — both called from `paths.py` and from any caller-side snapshot) |

**File layout:**
- `__init__.py` — re-exports `Config`, `load_config`
- `env.py` — `read_env(name: str, default: str) -> str`; `coerce(name: str, raw: str, kind: type, default)` — hub
- `paths.py` — `resolve_home(raw: str) -> Path` (handles relative `.taskq`); `tasks_json_path(cfg: Config) -> Path`

**Logical Constraints:**
- `config` is the **only** module that imports `os.environ` and `pathlib`.
- `load_config()` MUST be called exactly once per process; the snapshot is passed to store/executor as a parameter (no global mutable state).
- Default values are fixed: `TASKQ_HOME='.taskq'`, `TASKQ_TASK_TIMEOUT=10.0`, `TASKQ_RETRY_LIMIT=2` (SPEC §5 / SRS §6).
- `TASKQ_TASK_TIMEOUT` MUST be coerced to `float`; `TASKQ_RETRY_LIMIT` to `int`. Invalid coercions raise `ConfigError` → CLI maps to exit 1.
- The three env var names MUST be declared in `.env.example` (config liveness — `test_config_env_keys_declared_in_env_example`).

---

## 3. Data Flow

The store is the single point of truth. CLI parses argv and dispatches; store owns the JSON file; executor owns subprocess lifecycle; config owns the env snapshot. All four flows below begin at `python -m taskq ...` and end at `sys.exit(<code>)`.

### 3.1 Successful `submit` flow (exit 0)

```
user → cli.main(["submit", "echo hi"])
  → argparse parses → cmd_submit("echo hi")
  → store.submit_task("echo hi")
      → validation.validate_command("echo hi")   # non-empty, len<=1000, no injection chars
      → ids.generate_task_id()                    # uuid4 hex[:8] → e.g. "a1b2c3d4"
      → Task(id, command="echo hi", status="pending", created_at=<iso8601>)
      → persistence.atomic_write(tasks.json, {id: task})
          → write tasks.json.tmp
          → os.replace(tasks.json.tmp, tasks.json)
  → format.render_human("submit", {"id": "a1b2c3d4", "status": "pending"})
  → sys.exit(0)
```

Key invariants: validation runs *before* id generation; atomic write succeeds before any return; `tasks.json` is never in a partial state.

### 3.2 Successful `run` flow (exit 0, status='done')

```
user → cli.main(["run", "a1b2c3d4"])
  → cmd_run("a1b2c3d4")
  → store.get_task("a1b2c3d4")            # exists; status=pending
  → store.update_task(id, status="running")
  → executor.run_task(task)
      → state_machine.apply_transition(task, RUN)
      → runner.run_subprocess("echo hi", timeout=10.0)
          → subprocess.run(shlex.split("echo hi"), shell=False, capture_output=True, text=True, timeout=10.0)
          → returns CompletedProcess(returncode=0, stdout="hi\n", stderr="")
      → redaction.redact(stdout_tail)     # "hi\n" → "hi\n" (no secret)
      → redaction.redact(stderr_tail)     # "" → ""
      → result.RunResult(status="done", exit_code=0, stdout_tail="hi\n", stderr_tail="", duration_ms=N, finished_at=<iso8601>)
      → state_machine.apply_transition(task, DONE)
  → store.update_task(id, status="done", exit_code=0, stdout_tail=..., stderr_tail=..., duration_ms=N, finished_at=...)  # atomic_write #2
  → format.render_human("run", {...})    # or render_json if --json
  → sys.exit(0)
```

Key invariants: `pending → running` write happens *before* subprocess spawn; `running → done` write happens *after* redaction; secrets are scrubbed *before* persistence (NFR-03 / R3).

### 3.3 `run` timeout + retry flow (exit 0 if all attempts fail in retry budget, exit 4 if final attempt is timeout in single-task mode)

```
user → cli.main(["run", "deadbeef"])
  → cmd_run → store.get_task → status=pending
  → store.update_task(id, status="running")
  → executor.run_task(task)
      → retry.run_with_retry(task, max_attempts=1+TASKQ_RETRY_LIMIT=3)
          attempt 1: runner.run_subprocess(...)  # sleeps 12s, hits timeout=10.0
                     → subprocess.TimeoutExpired
                     → state_machine → status=timeout
          attempt 2: runner.run_subprocess(...)  # same
                     → status=timeout
          attempt 3 (final): runner.run_subprocess(...) # same
                     → status=timeout
      → final RunResult(status="timeout", exit_code=-1, stdout_tail="", stderr_tail="[REDACTED] some stderr", duration_ms=10000, finished_at=...)
  → store.update_task(id, status="timeout", exit_code=-1, ..., finished_at=...)
  → if final status == "timeout" and single-task mode: cli maps → sys.exit(4)
  → else (e.g. background, future): sys.exit(0)
```

Key invariants: retry budget is `1 + TASKQ_RETRY_LIMIT` attempts; each attempt's result is captured independently; only the final result is persisted. `test_fr02_run_retry_limit_respected` asserts no attempt is made beyond the cap.

### 3.4 Corruption detection flow (exit 1)

```
user → cli.main(["list"])     # or any subcommand
  → handler → store.load_store()
      → open(tasks.json).read() → '{"a1b2c3d4": {"id": ...'   # truncated / malformed
      → json.loads(...)  →  raises json.JSONDecodeError
      → store wraps and raises StoreCorrupted("invalid JSON in tasks.json")
  → cli catches StoreCorrupted at the top level
      → writes "store corrupted" to sys.stderr
      → sys.exit(1)   # EXIT_INTERNAL
```

Key invariants: NO silent rebuild (FR-01 / NFR-03); the corrupted file is left on disk for forensic recovery; the process exits with code 1; subsequent runs MUST re-detect corruption and not auto-recover.

---

## 4. Error Handling

| Exit code | Symbol | Cause | Handler location | User-visible message | Recovery |
|-----------|--------|-------|------------------|----------------------|----------|
| **0** | `EXIT_OK` | Success — submit / run / status / list / clear all completed without validation or timeout | `cli.main` after handler returns normally | normal output (human or `--json`) | n/a |
| **2** | `EXIT_VALIDATION` | (a) FR-01 validation rule violated: empty command, whitespace-only command, `len(cmd)>1000`, or any of `;\|&$><\`` present; (b) unknown task id in `status` or `run` | `validation.validate_command` raises `ValidationError` → `cli.cmd_submit` exits 2; `store.get_task` returns `None` → `cli.cmd_status` / `cmd_run` exit 2 | `error: <rule>` to stderr (e.g. `error: command contains forbidden character ';'`) or `unknown task: <id>` | user fixes input; no store mutation |
| **4** | `EXIT_TIMEOUT` | Final `run` attempt in single-task mode produced `status='timeout'` (subprocess exceeded `TASKQ_TASK_TIMEOUT`) | `executor.retry.run_with_retry` returns final `RunResult(status='timeout')`; `cli.cmd_run` checks the result and exits 4 only in single-task mode | `error: task timed out after 10.0s` to stderr | user raises `TASKQ_TASK_TIMEOUT` or fixes the hung command; no store rebuild (timeout records remain) |
| **1** | `EXIT_INTERNAL` | (a) `tasks.json` corrupted (non-JSON); (b) unexpected exception (e.g. `OSError` on atomic write); (c) env-var coercion failure | `store.load_store` raises `StoreCorrupted` → `cli.main` top-level catch exits 1; uncaught exceptions caught at `cli.main` top level; `ConfigError` from `config.load_config` exits 1 | `store corrupted` to stderr (corruption path); `internal error: <type>` to stderr (unexpected exception path) | corruption: file is left on disk for manual recovery; user inspects + deletes `.taskq/tasks.json` to reset (intentional, NOT automatic) |

**Anti-silencing rule (binding, no exceptions).** No `try/except` block in `core/taskq/` may use a bare `except:` or a broad `except Exception:` to swallow an error without re-raising or mapping it to a documented exit code. Specifically:
- `StoreCorrupted` MUST propagate to `cli.main` and exit 1 — never rebuild silently.
- `ValidationError` MUST propagate to `cli.cmd_submit` and exit 2 — never partially mutate the store.
- `TimeoutExpired` (subprocess) MUST be caught and classified as `status='timeout'` — never mapped to `failed` and never suppressed.
- Unexpected exceptions MUST surface as exit 1 with the exception class name in stderr (no `except: pass`).

This rule is enforced by `test_redteam_shell_true_absent_in_codebase` (static scan for `shell=True` only) and by inspection in code review for the four patterns above.

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
  created_at: "2026-06-17"
  phase: 2  # MUST be int, NOT a string — parser raises on 'phase: "2"'
  project: "integration-test"

  layers:  # 4 source modules, each one CRG community
    - name: cli
      modules: ["taskq.cli"]
      allowed_dependencies: ["store", "executor", "config"]
    - name: store
      modules: ["taskq.store"]
      allowed_dependencies: ["config"]
    - name: executor
      modules: ["taskq.executor"]
      allowed_dependencies: ["store", "config"]
    - name: config
      modules: ["taskq.config"]
      allowed_dependencies: []   # leaf; reads os.environ only

  allowed_dependencies:
    - from: cli
      to: store
    - from: cli
      to: executor
    - from: cli
      to: config
    - from: executor
      to: store
    - from: store
      to: config
    - from: executor
      to: config
    # NO circular deps; config is the sink (no outgoing edges to other taskq modules)

  quality_targets:
    max_complexity: 15
    min_coverage: 80
    max_coupling: 0.3

  nfr_dimension_mapping: {}  # OPTIONAL — auto-derived from nfr_traceability.type

  nfr_traceability:
    NFR-01:
      type: performance
      target: "p95 < 50ms"  # submit+status 100 cycles, excluding subprocess (SRS §3)
      module: taskq.store   # latency-critical path: validate_command + atomic_write + load_store live here (Agent B round-2 fix)
    NFR-02:
      type: security
      target: ">=95"  # raise gate floor: codebase shell=True absence (hard zero) + 6/6 injection chars covered
      module: taskq.store  # primary enforcement surface (validation.py blacklist); executor shares shell=False contract
    NFR-03:
      type: reliability
      target: ">=95"  # raise gate floor: atomic write (tmp+os.replace) + redaction (sk-/token=) both must pass
      module: taskq.store  # PRIMARY contract enforcement surface (atomic write lives in store/persistence.py; redaction is *called by* executor but enforced via the store.update_task contract that no RunResult with unredacted secrets is accepted). The redaction IMPLEMENTATION lives in taskq.executor.redaction (see ADR-006); the store is the boundary that guarantees the invariant.

  advisory_only: []  # AUTO-FILLED by parser — omit or leave []

  gate_score_overrides: {}  # AUTO-DERIVED by parser — omit or leave {}

  fr_module_traceability:  # FR-01..FR-03 pre-defined, immutable
    FR-01: "taskq.store"     # model + persistence + corruption detection
    FR-02: "taskq.executor"  # subprocess + state machine + retry
    FR-03: "taskq.cli"       # argparse dispatch + --json + exit codes

  architecture_constraints:
    - "no_circular_dependencies"
    - "stdlib_only"
    - "shell_false_enforced"
    - "atomic_writes_only"

  high_risk_modules:
    - "taskq.executor"   # subprocess lifecycle + redaction (NFR-02 + NFR-03 surface)
    - "taskq.store"      # atomic write + corruption detection (NFR-03 + FR-01 corruption path)
```
<!-- SAB:END -->

Note: Fill in the YAML above — it is used for Drift Detection and gate scoring.
Generate: `python3 scripts/generate_sab.py --project . [--overwrite]`

---

## 6. Technology Choices

| Technology | Rationale |
|------------|-----------|
| **Python 3.11** | Required by SPEC §1 / SRS §1 / PROJECT_BRIEF §1. Provides `subprocess.run(..., text=True, timeout=...)`, `shlex.split`, `pathlib.Path`, `datetime` (timezone-aware ISO 8601), and `match` statements used in the state machine. |
| **stdlib `subprocess`** | Required by FR-02; `shell=False` enforced to satisfy NFR-02; `capture_output=True` + `text=True` + `timeout=` provide the three required behaviors in a single call. |
| **stdlib `shlex`** | Required by FR-02 to safely split the user-supplied command into argv (no shell parsing) before `subprocess.run`. |
| **stdlib `json`** | Required by NFR-03 (atomic write target is JSON); `json.loads` raises `json.JSONDecodeError` on corruption (the trigger for `StoreCorrupted` → exit 1). |
| **stdlib `os.replace`** | Required by NFR-03 for atomic rename within the same filesystem; tmp + `os.replace` is the canonical POSIX atomic-write pattern. |
| **stdlib `uuid`** | Required by FR-01 (uuid4 → hex[:8] → 8-char task id). |
| **stdlib `argparse`** | Required by FR-03 (subcommand dispatch + `--json` global flag). |
| **stdlib `pathlib`** | Used by `config.paths.resolve_home` and `tasks_json_path`. |
| **stdlib `re`** | Used by `executor.redaction.redact` to match `sk-[A-Za-z0-9_-]{8,}` and `token=\S+` line patterns. |
| **stdlib `datetime`** | Used to produce `created_at` / `finished_at` ISO 8601 timestamps on Task records. |
| **stdlib `time`** | Used by `executor.runner` to measure `duration_ms` via `time.perf_counter()`. |
| **stdlib `dataclasses`** | Used for `Task`, `RunResult`, `Config` records (immutable, type-hinted, equality for testing). |
| **stdlib `sys`** | Used by `cli.main` to read `argv` and write exit codes; restricted to `cli/` (no other module may import it). |
| **No third-party runtime deps** | SPEC §1 / PROJECT_BRIEF §4 hard constraint. The codebase is 100% stdlib at runtime. Test tools (pytest, etc.) are provided by the dev environment and are NOT runtime dependencies. |
| **pytest (dev-only, not runtime)** | Used by `tests/` for the 25-test inventory. Not imported by `core/taskq/`; not present in any wheel/sdist dependency declaration. |

---

## 7. Cross-Reference: 25-Test Inventory → Modules

> Source: SRS.md v2.0.0 §8 (the 25-test inventory) and TEST_INVENTORY.yaml v1.1 (the 45-test authoritative expansion). This SAD uses the 25 from §8 as the primary cross-reference; the 45 in TEST_INVENTORY.yaml are the function-level decomposition used by `harness/build_trace.py` (P3) to map actual `def test_*` to FRs. The 25 below are sufficient to demonstrate FR/NFR coverage; the full 45 are catalogued in TRACEABILITY_MATRIX.md Backward Mapping (P1) and `tests/` (P3 actual).

| # | Test function (SRS §8 authoritative) | FR / NFR | Primary module | Secondary module(s) | Test file (P3 est.) |
|---|----------------------------------------|----------|----------------|----------------------|---------------------|
| 1 | `test_fr01_submit_valid_command_returns_zero` | FR-01 | `taskq.cli` | `taskq.store` | `03-development/tests/test_fr01.py` |
| 2 | `test_fr01_submit_empty_command_returns_two` | FR-01 | `taskq.cli` | `taskq.store.validation` | `03-development/tests/test_fr01.py` |
| 3 | `test_fr01_submit_whitespace_command_returns_two` | FR-01 | `taskq.cli` | `taskq.store.validation` | `03-development/tests/test_fr01.py` |
| 4 | `test_fr01_submit_long_command_returns_two` | FR-01 | `taskq.cli` | `taskq.store.validation` | `03-development/tests/test_fr01.py` |
| 5 | `test_fr01_submit_injection_chars_returns_two` (parametrized: `;` `|` `&` `$` `>` `<` `` ` ``) | FR-01, NFR-02 | `taskq.cli` | `taskq.store.validation` | `03-development/tests/test_fr01.py` |
| 6 | `test_fr01_submit_produces_uuid4_id_format` | FR-01 | `taskq.store` | — | `03-development/tests/test_fr01.py` |
| 7 | `test_fr01_store_corruption_returns_one` | FR-01, NFR-03 | `taskq.store` | `taskq.cli` | `03-development/tests/test_fr01.py` |
| 8 | `test_fr02_run_executes_subprocess_with_shell_false` | FR-02, NFR-02 | `taskq.executor` | `taskq.cli` | `03-development/tests/test_fr02.py` |
| 9 | `test_fr02_run_exit_zero_yields_done` | FR-02 | `taskq.executor` | `taskq.store` | `03-development/tests/test_fr02.py` |
| 10 | `test_fr02_run_nonzero_yields_failed` | FR-02 | `taskq.executor` | `taskq.store` | `03-development/tests/test_fr02.py` |
| 11 | `test_fr02_run_timeout_yields_timeout_and_exit_four` | FR-02 | `taskq.executor` | `taskq.cli` | `03-development/tests/test_fr02.py` |
| 12 | `test_fr02_run_failed_retries_up_to_limit` | FR-02 | `taskq.executor` | `taskq.config` | `03-development/tests/test_fr02.py` |
| 13 | `test_fr02_run_retry_limit_respected` | FR-02 | `taskq.executor` | `taskq.config` | `03-development/tests/test_fr02.py` |
| 14 | `test_fr03_status_unknown_id_returns_two` | FR-03 | `taskq.cli` | `taskq.store` | `03-development/tests/test_fr03.py` |
| 15 | `test_fr03_list_returns_all_tasks` | FR-03 | `taskq.cli` | `taskq.store` | `03-development/tests/test_fr03.py` |
| 16 | `test_fr03_clear_empties_store` | FR-03 | `taskq.cli` | `taskq.store` | `03-development/tests/test_fr03.py` |
| 17 | `test_fr03_json_flag_emits_single_line_json` | FR-03 | `taskq.cli` | `taskq.cli.format` | `03-development/tests/test_fr03.py` |
| 18 | `test_redteam_prompt_injection_via_submit_blocked` (parametrized: 6 chars) | FR-01, NFR-02 | `taskq.cli` | `taskq.store.validation` | `03-development/tests/test_fr03.py` |
| 19 | `test_redteam_secret_in_stdout_redacted_before_persist` | NFR-03 | `taskq.executor` | `taskq.store` | `03-development/tests/test_fr03.py` |
| 20 | `test_redteam_secret_in_stderr_redacted_before_persist` | NFR-03 | `taskq.executor` | `taskq.store` | `03-development/tests/test_fr03.py` |
| 21 | `test_redteam_shell_true_absent_in_codebase` (static scan) | NFR-02 | `taskq.cli` (entry surface) | `taskq.executor` (subprocess surface) | `03-development/tests/test_fr03.py` |
| 22 | `test_kpi_p95_submit_status_under_50ms` | NFR-01 | `taskq.cli` | `taskq.store` | `03-development/tests/test_fr03.py` |
| 23 | `test_reliability_kill_during_write_keeps_valid_json` | NFR-03 | `taskq.store` | — | `03-development/tests/test_fr03.py` |
| 24 | `test_reliability_concurrent_writes_do_not_corrupt` | NFR-03 | `taskq.store` | — | `03-development/tests/test_fr03.py` |
| 25 | `test_config_env_keys_declared_in_env_example` | (config liveness) | `taskq.config` | — | `03-development/tests/test_fr03.py` |

**Module coverage roll-up (25 tests, primary-module attribution):**
- `taskq.cli` (entry / dispatch / format / static scan entry surface): 11 tests (#1–5, 8, 11, 14–18, 21 partial, 22)
- `taskq.store` (persistence / validation / corruption): 4 tests (#6, 7, 23, 24) — plus secondary on most others
- `taskq.executor` (subprocess / state machine / redaction / retry): 6 tests (#9, 10, 12, 13, 19, 20) — plus secondary on #8, 11, 21
- `taskq.config` (env liveness / retry-limit input): 1 test (#25) — plus secondary on #12, 13

Every FR has ≥ 5 primary-or-secondary tests; every NFR has ≥ 1 primary test. NFR-02 has two reinforcing surfaces: parametrized unit (#5) and codebase-wide static scan (#21). NFR-03 has four reinforcing surfaces: redaction unit (#19, #20), atomic write integration (#23, #24), and the implicit "store never silently rebuilds" contract exercised by #7.

**Note on the 25 vs 45 reconciliation.** SRS.md §8 lists 25 tests; the P1 round-2 patch in TEST_INVENTORY.yaml v1.1 expanded the inventory to 45 function-level names (e.g. decomposing FR-02's state-machine row into 10 discrete assertions: `test_fr02_run_captures_stdout_tail_under_2000_chars`, `test_fr02_run_captures_stderr_tail_under_2000_chars`, `test_fr02_run_records_duration_ms_and_finished_at`, `test_fr02_run_unexpected_exception_returns_one`, etc.). The 25 above are the §8 baseline; the additional 20 in TEST_INVENTORY are absorbed by the same primary modules (cli, store, executor, config) and do not change the architecture or SAB. P3 `harness/scripts/build_traceability.py` reconciles by reading the actual `def test_*` definitions.

---

*End of SAD v1.0 — taskq | 2026-06-17 | Phase 2 Architecture & Design*
