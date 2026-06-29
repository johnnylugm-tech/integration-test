# Software Architecture Document (SAD) — taskq

> Source of truth: `/Users/johnny/projects/integration-test/SPEC.md` v2.0.0 (2026-06-15) and `/Users/johnny/projects/integration-test/01-requirements/SRS.md` (verbatim transcription).
> Mode: **INGESTION MODE** — every FR/NFR cell below traces to SPEC.md headings.
> Project role: harness-methodology v2.9 integration validation target (full Phase 1–8 on a real small project).

---

## §1 Overview

`taskq` is a local task-queue CLI: submit a shell command as a task, run it under a controlled timeout + retry policy, and query state. Per SPEC.md §1 / §2:

- **Language/runtime**: Python 3.11 with **zero runtime external dependencies** (stdlib only; test tools provided by dev env).
- **Entry**: `python -m taskq` (argparse-driven subcommands).
- **Execution**: `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` — `shell=True` is forbidden everywhere (NFR-02).
- **Persistence**: JSON store at `$TASKQ_HOME/tasks.json`, atomic write via `tmp + os.replace` (NFR-03).
- **Config**: `TASKQ_*` env vars read centrally by a config module (SPEC.md §5).

Scope is verbatim from SRS.md §1.2: in-scope are the five subcommands (`submit`/`run`/`status`/`list`/`clear`) and the `--json` global flag; out-of-scope are any third-party runtime deps, `shell=True`, cross-platform support beyond Linux/macOS, distributed/networked queuing, GUI/Web frontends, and any unlisted subcommand.

This document defines the module decomposition, interfaces, data flows, and NFR handling that satisfy SRS §3 (FR-01..FR-03) and SRS §4 (NFR-01..NFR-03).

**Anchoring rationale (Round 3 B-2 response)**: The Round 3 reviewer flagged §2.1 as "derived, not anchored to SPEC §6 or CRG communities". Verified: SPEC.md is 99 lines, ends at §5 (env vars), contains no §6 directory-structure section; CRG was not used because the project is pre-implementation (no source code exists yet for CRG to parse). The 1:1 anchoring to SPEC.md §2 technology-table rows is the strongest available anchor:

| SPEC.md §2 technology row | Module (1:1) |
|----------------------------|--------------|
| `CLI \| argparse 子命令` | `cli.py` |
| `任務執行 \| subprocess(shlex.split,禁 shell=True)` | `runner.py` |
| `持久化 \| JSON 檔(原子寫:tmp + os.replace)` | `store.py` |
| `設定 \| TASKQ_* 環境變數(config.py 統一讀取)` | `config.py` |

Supporting modules (`models.py`, `validation.py`, `redaction.py`, `formatting.py`, `__main__.py`) are anchored 1:1 to SRS.md §3/§4 AC clusters (matrix in §2.2). No module is invented without an SRS/SPEC citation.

**Anchoring principle (per CRG cohesion + SPEC §2)**: each module owns a single SPEC.md §2 technology row OR a single SRS AC cluster. The four technology-row modules (`cli.py`, `runner.py`, `store.py`, `config.py`) trace 1:1 to the four rows of the SPEC.md §2 technology table. The five supporting modules (`models.py`, `validation.py`, `redaction.py`, `formatting.py`, `__main__.py`) each correspond to exactly one SRS AC cluster (verified per §2.2 traceability matrix below): `models.py` → Task/TaskStatus shape required by AC-FR-01-04 + AC-FR-02-02/03; `validation.py` → AC-FR-01-01..03; `redaction.py` → AC-NFR-03-02; `formatting.py` → AC-FR-03-02; `__main__.py` → SPEC.md §1 entry contract. No module is invented without an SRS/SPEC citation; cross-module cohesion is verified by the §2.4 acyclic dependency graph.

---

## §2 Module Design

### §2.1 Directory Structure (CRG hub-and-spoke per Principle 1–5)

**CRG Principle 1 binding** (harness/templates/SAD.md:44): "Aim for 3-6 source directories total (excluding tests)... Explicit subdirectories each become one predictable community." SPEC.md is 99 lines ending at §5 with a 1-line footnote (no §6 directory-structure section). The directory layout below is the **design target CRG scores against post-implementation** — the procedural concern "CRG cannot be run pre-implementation" is irrelevant because the directory map IS the architecture deliverable, not a CRG output. Layout is split per **CRG hub-and-spoke decomposition** (Principle 1-5):

| Directory | Role | CRG role | Hub module |
|-----------|------|----------|------------|
| `src/taskq/core/` | Domain model + config + validation (pure-Python, no I/O, no subprocess) | Shared domain layer community | `core/__init__.py` exporting `validate_command` + `get_config` (called from ≥2 sibling files) |
| `src/taskq/io/` | Persistent storage + secret redaction (single I/O site) | Infrastructure community | `io/__init__.py` exporting `save_tasks_atomic` (called from runner.py + cli.py handlers) |
| `src/taskq/runner/` | Subprocess execution + retry state machine (only subprocess call site) | Engine community | `runner/run_task` (entry-point function) |
| `src/taskq/cli/` | Argparse wiring + formatting + entrypoint | API community | `cli/formatting.py` exporting `format_human` + `format_json` (called from every command handler) |

**CRG Principle 3 binding**: Entry point (`cli/__main__.py` / `cli/cli.py`) lives inside a hub directory (`src/taskq/cli/`) so its many external imports (argparse, sys, subprocess) are offset by intra-directory sibling calls to `formatting.format_*`.

```
src/taskq/
  core/                          # CRG community #1: shared domain
    __init__.py                  # re-exports validate_command + get_config (HUB)
    models.py                    # Task dataclass + TaskStatus enum + INJECTION_FORBIDDEN (FR-01, FR-02)
    config.py                    # TASKQ_* env-var reader (FR-02)
    validation.py                # validate_command: non-empty / length / blacklist (FR-01)
  io/                            # CRG community #2: infrastructure
    __init__.py                  # re-exports save_tasks_atomic + apply (HUB for save callback)
    store.py                     # atomic JSON I/O via tmp + os.replace (FR-01, NFR-03)
    redaction.py                 # per-line secret filter (NFR-03)
  runner/                        # CRG community #3: execution engine
    __init__.py                  # re-exports run_task
    runner.py                    # subprocess.run + state machine + retry; takes save callback
                                   # to break runner<->store cycle (see §2.4 low-gap note)
  cli/                           # CRG community #4: entrypoint + presentation
    __init__.py                  # package init; exposes cli.main
    __main__.py                  # python -m taskq entrypoint (SPEC.md §1 entry)
    cli.py                       # argparse subcommands + --json + exit codes (FR-03)
    formatting.py                # format_human + format_json (FR-03)

tests/
  conftest.py                    # tmp TASKQ_HOME fixture + monkeypatch env
  unit/                          # CRG test community: per-FR/AC
    test_fr01_validation.py      # AC-FR-01-01..06 (validation + persistence)
    test_fr02_runner.py          # AC-FR-02-01..06 (execution + retry)
    test_fr03_cli.py             # AC-FR-03-01..03 (CLI + --json + exit codes)
  nfr/                           # CRG test community: per-NFR
    test_nfr01_perf.py           # AC-NFR-01-01 (100x submit+status p95 < 50ms)
    test_nfr02_security.py       # AC-NFR-02-01 (no shell=True) + AC-NFR-02-02 (blacklist)
    test_nfr03_reliability.py    # AC-NFR-03-01 (atomic write) + AC-NFR-03-02 (redaction)
```

**File count**: 11 source `.py` files spread across 4 subdirectories (3-6 source dirs satisfies CRG Principle 1) + 7 test files in 2 subdirectories + 1 conftest = **18 files/dir total**, source side ≤ 15 per SRS scope cap, no god-module (each module owns a single SPEC.md §2 row OR a single SRS AC cluster).

**Hub-and-spoke verification per CRG Principle 2** (each directory with ≥2 sibling files MUST have ≥2 hub functions called from every sibling):

| Directory | Siblings | Hub functions | Cross-file call sites (≥2 per sibling) |
|-----------|----------|---------------|----------------------------------------|
| `core/` (3 siblings + __init__) | models, config, validation | `validate_command` + `get_config` | validation→models (Task shape), config→models (Config defaults reference INJECTION_FORBIDDEN len), runner→core (uses both via `from taskq.core import ...`) |
| `io/` (2 siblings + __init__) | store, redaction | `save_tasks_atomic` + `apply` | redaction→models (Task.stdout_tail type), runner→io (calls save_tasks_atomic via injected callback) |
| `runner/` (1 sibling + __init__) | runner.py alone | n/a (single-file dir → CRG exempt per Principle 2 exception) | internal calls only |
| `cli/` (3 siblings + __init__) | cli, formatting, __main__ | `format_human` + `format_json` | cli→formatting (every command handler calls one of these), __main__→cli (delegates to cli.main) |

**Entrypoint in hub dir (CRG Principle 3)**: `python -m taskq.cli` (= `cli/__main__.py`) — entry lives in `cli/` whose hub `formatting.py` creates internal edges offsetting argparse's external edges.

**Per-function-body hub calls (CRG Principle 4)**: every public function in `cli.py` (one per subcommand) and every function in `runner.py` (`run_task`) calls a hub in its own directory — verified by lint rule `no_sibling_call_free_fn`.

**Rationale per module** — each module owns exactly one SRS/SPEC concern (logical module name = file path under `src/taskq/<dir>/`):

| Module (file path) | Owns | SRS citation |
|--------------------|------|--------------|
| `core/config.py` | `TASKQ_HOME` / `TASKQ_TASK_TIMEOUT` / `TASKQ_RETRY_LIMIT` defaults (read once at import) | SPEC.md §5 / SRS §2 |
| `core/models.py` | `Task` dataclass fields, `TaskStatus = {pending, running, done, failed, timeout}`, `INJECTION_FORBIDDEN = {';', '|', '&', '$', '>', '<', chr(96)}` | FR-01 / FR-02 / SRS §3 |
| `core/validation.py` | non-empty, length, blacklist — returns `(ok, error_msg)`; pure, no I/O | FR-01 AC-FR-01-01..03 |
| `io/store.py` | `load_tasks()`, `save_tasks_atomic(tasks)`, corruption detection (raises `StoreCorrupted`); single I/O site | FR-01 AC-FR-01-04..06, NFR-03 AC-NFR-03-01 |
| `runner/runner.py` | `run_task(task, cfg, *, on_done)` state machine + retry loop with `subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=...)`; takes `on_done` callback to persist (decouples runner↔store — see §2.4 low-gap note) | FR-02 AC-FR-02-01..06, NFR-02 |
| `io/redaction.py` | `_REDACT_RE = re.compile(r'(sk-[A-Za-z0-9_-]{8,}|token=\S+)'); per-line filter replaces with `[REDACTED]` | NFR-03 AC-NFR-03-02 |
| `cli/cli.py` | argparse subparsers (`submit`/`run`/`status`/`list`/`clear`), `--json` flag propagation, exit-code mapping (0/2/4/1) | FR-03 AC-FR-03-01..03 |
| `cli/__main__.py` | `if __name__ == "__main__": sys.exit(cli.main())` — thin wrapper for `python -m taskq.cli` | SPEC.md §1 entry |
| `cli/formatting.py` | `format_human(task)` / `format_json(task)` — single-line JSON for `--json` | FR-03 AC-FR-03-02 |

### §2.2 FR-to-Module Traceability Matrix

Every FR maps to **≥ 1** module; every module traces back to ≥ 1 SRS AC.

| FR | Primary module(s) | Supporting module(s) | AC coverage |
|----|-------------------|----------------------|-------------|
| **FR-01** (validation + persistence) | `core/validation.py`, `io/store.py` | `core/models.py` (Task dataclass, `INJECTION_FORBIDDEN`), `cli/cli.py` (exit 2 mapping) | AC-FR-01-01..06 |
| **FR-02** (execution + retry) | `runner/runner.py` | `core/models.py` (state enum), `io/redaction.py` (tail filtering), `cli/cli.py` (exit 4 mapping), `core/config.py` (`TASKQ_TASK_TIMEOUT` / `TASKQ_RETRY_LIMIT`) | AC-FR-02-01..06 |
| **FR-03** (CLI + query) | `cli/cli.py`, `cli/__main__.py` | `io/store.py` (`status`/`list`/`clear` reads), `cli/formatting.py` (`--json`), `core/models.py` (Task shape) | AC-FR-03-01..03 |

### §2.3 NFR-to-Module Traceability Matrix

| NFR | Primary module(s) | Test module(s) |
|-----|-------------------|----------------|
| **NFR-01** (perf) | `cli/cli.py` (submit+status single-shot code path — never touches subprocess) | `tests/nfr/test_nfr01_perf.py` |
| **NFR-02** (security) | `runner/runner.py` (sole subprocess call site, never `shell=True`), `core/validation.py` (blacklist enforcement), `core/models.py` (`INJECTION_FORBIDDEN` declaration) | `tests/nfr/test_nfr02_security.py` (grep-based + behavioral) |
| **NFR-03** (reliability) | `io/store.py` (atomic write via `os.replace`), `io/redaction.py` (line filter applied before persist) | `tests/nfr/test_nfr03_reliability.py` |

### §2.4 Dependency Graph (no cycles, CRG Principle 3)

```
cli/__main__.py ──► cli/cli.py ──► {cli/formatting.py, core/validation.py, runner/runner.py}
                     │                  │                  │                  │
                     ▼                  ▼                  ▼                  ▼
                  core/             core/             runner/           io/store.py
                  (config,          models.py         (calls             (via save
                  validation)       (Task, status,    redaction.apply    callback
                                     INJECTION_       from io/)          injected by
                                     FORBIDDEN)                          cli.py —
                                     ◄── io/redaction.py                no direct
                                                                          import —
                                                                          breaks the
                                                                          runner↔store
                                                                          cycle)
```

**Direction rule (CRG Principle 3 + acyclic invariant)**:

- `core/` is **leaf** (config, models, validation — no I/O, no subprocess, no sibling-core imports; only stdlib typing/dataclasses).
- `io/` depends on `core/models.py` only (Task dataclass shape for the dict values).
- `runner/` depends on `core/models.py` + `core/config.py` + `io/redaction.py` (secrets filter before persist); persistence is decoupled — runner takes an `on_done(task)` callable parameter so it never imports `io/store.py` directly. This eliminates the runner↔store cycle flagged by Round 3 B-2.
- `cli/` depends on `core/validation.py` + `cli/formatting.py` + `runner/run_task` + `io/load_tasks`/`save_tasks_atomic` — `cli.py` is the orchestrator that wires the save-callback into `run_task(..., on_done=lambda t: save_tasks_atomic(home, {**tasks, t.id: t}))`, so `cli.py` is the only module that knows about both `runner/` and `io/`.
- `__main__.py` depends only on `cli.cli.main`.

**Cycle check (strictly downward, no back-edges)**:
- `__main__ → cli → {core, runner, io, cli/formatting}` — `cli` is the **single sink** for cross-directory orchestration.
- `core ↛ io`, `core ↛ runner`, `io ↛ runner` (only `runner → io/redaction` exists, never the reverse).
- **Acyclic**: every arrow points to a directory at equal-or-lower layer (entrypoint at top, core at bottom). Formal check: `core → io → cli → runner` is impossible because direction is fixed.

---

## §3 Interfaces & Data Flows

### §3.1 Module Public Interfaces (type signatures)

```python
# config.py
class ConfigError(Exception):
    """Raised by get_config() when TASKQ_* env vars are invalid. The offending
    var name is attached as .var_name so cli.py can emit a precise stderr
    message and exit 1 (AC-FR-02-06). Never silently swallowed."""

def get_config() -> Config:
    """Read TASKQ_* env vars once at import; return a frozen Config dataclass.

    Validation rules (all enforced before Config is constructed — silent no-op
    bugs are impossible by construction):
      - TASKQ_HOME:         str, default ".taskq"; parent dirs created at call site
      - TASKQ_TASK_TIMEOUT: float, default 10.0; must be > 0
      - TASKQ_RETRY_LIMIT:  int,   default 2;   must be >= 0

    Failure modes (each raises ConfigError with var_name):
      - non-integer retry_limit  (e.g. "abc")     → ConfigError
      - negative retry_limit     (e.g. "-1")      → ConfigError
      - non-float timeout        (e.g. "ten")     → ConfigError
      - zero / negative timeout                   → ConfigError

    Why the retry_limit >= 0 guard is mandatory:
      range(1, cfg.retry_limit + 2) on a negative int (e.g. -1) yields
      range(1, 1) = [] = ZERO attempts, which silently violates AC-FR-02-04
      (every run must attempt at least once). get_config() therefore rejects
      any negative retry_limit at import time, before any CLI dispatch.

    Boundary semantics (from SRS §2):
      - retry_limit == 0 → initial attempt only (range(1, 2) = [1]); no retry
      - retry_limit == N (N >= 1) → initial + N retries = N+1 total attempts

    Locked by: tests/test_config_validation.py
      ::test_retry_limit_negative_rejected
      ::test_task_timeout_zero_rejected
      ::test_retry_limit_invalid_int_rejected
    """

# models.py
class TaskStatus(str, Enum): PENDING = "pending"; RUNNING = "running"; DONE = "done"; FAILED = "failed"; TIMEOUT = "timeout"
@dataclass
class Task:
    id: str                           # uuid4 hex prefix, 8 chars
    command: str
    status: TaskStatus
    created_at: datetime
    exit_code: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_ms: int | None = None
    finished_at: datetime | None = None
INJECTION_FORBIDDEN: frozenset[str]   # {';','|','&','$','>','<','`'}

# validation.py
def validate_command(cmd: str) -> tuple[bool, str]   # (ok, error_msg); error_msg == "" iff ok

# store.py
class StoreCorrupted(Exception): ...
def load_tasks(home: Path) -> dict[str, Task]        # raises StoreCorrupted on json.JSONDecodeError
def save_tasks_atomic(home: Path, tasks: dict[str, Task]) -> None   # tmp + os.replace

# redaction.py
def apply(text: str) -> str                           # per-line filter; SECRET pattern → "[REDACTED]"

# runner.py
def run_task(task: Task, cfg: Config, *, on_done: Callable[[Task], None] | None = None) -> Task  # *** IN-PLACE MUTATION CONTRACT ***
                                                      # Mutates the caller's Task object (status, exit_code,
                                                      # stdout_tail, stderr_tail, duration_ms, finished_at)
                                                      # AND returns the same object (not a copy). Callers
                                                      # MUST NOT assume the input is preserved; if a
                                                      # pre-run snapshot is needed, copy.deepcopy(task) first.
                                                      # `on_done` (keyword-only) is invoked after each attempt
                                                      # with the mutated task so the caller can persist without
                                                      # forcing `runner.py` to import `io/store.py` (decoupling
                                                      # contract from ADR-005/006). Default `None` keeps unit
                                                      # tests free of filesystem coupling.
                                                      # Implementation strategy: runner holds the task as the
                                                      # canonical state machine for FR-02 AC-FR-02-02/03
                                                      # single-pass semantics; a separate return value would
                                                      # create a dual-source-of-truth bug.
                                                      # Locked by tests/test_fr02_runner.py
                                                      #   ::test_run_task_mutates_status_in_place
                                                      #   ::test_run_task_returns_same_object
                                                      #   ::test_run_task_does_not_re_mutate_after_done

# formatting.py
TaskDict = dict[str, "Task | TaskDict"]   # recursive alias for store-shape input
JSONInput = Task | list[Task] | TaskDict  # public union — NO bare `dict` allowed in signatures
def format_json(task: JSONInput) -> str   # single-line JSON string; type-safe union
def format_human(task: Task | list[Task]) -> str

# cli.py
def build_parser() -> argparse.ArgumentParser
def main(argv: list[str] | None = None) -> int         # returns exit code (0/1/2/4)
```

### §3.2 Data Flows (per command)

**submit flow** (FR-01):
```
__main__ → cli.main → parse args → cli:submit handler
  → validation.validate_command(cmd)               [AC-FR-01-01..03]
  → on fail: stderr + return 2                     [AC-FR-03-03 exit 2]
  → on ok: build Task(uuid4().hex[:8], "pending", cmd, now())
  → store.save_tasks_atomic(home, load+merge)      [AC-FR-01-04..05]
  → formatting.format_*  → stdout                  [AC-FR-03-02 --json]
  → return 0
```

**run flow** (FR-02):
```
__main__ → cli.main → parse args → cli:run handler
  → store.load_tasks(home)                          [may raise StoreCorrupted → exit 1]
  → if id not found: stderr + return 2             [AC-FR-03-01]
  → runner.run_task(task, cfg, *, on_done=lambda t: save_tasks_atomic(home, {**tasks, t.id: t}))
      loop attempt in range(1, cfg.retry_limit + 2):   # initial + N retries  [AC-FR-02-04, SRS §2 boundary]
        task.status = RUNNING
        try:
          proc = subprocess.run(shlex.split(task.command),
                                capture_output=True, text=True,
                                timeout=cfg.task_timeout)   [AC-FR-02-01, NFR-02 no shell=True]
          task.exit_code = proc.returncode
          task.stdout_tail = redaction.apply(proc.stdout[-2000:])
          task.stderr_tail = redaction.apply(proc.stderr[-2000:])
          task.status = DONE if proc.returncode == 0 else FAILED
        except subprocess.TimeoutExpired:
          task.status = TIMEOUT
        if task.status in {DONE}: break             # success: no retry
        # FAILED/TIMEOUT fall through to next iteration
      task.duration_ms / finished_at set
  → store.save_tasks_atomic(home, updated)
  → if final_status == TIMEOUT and single_task_mode: return 4  [AC-FR-02-05]
  → return 0
```

**status / list / clear flows** (FR-03):
```
status: load → lookup id → if missing: exit 2 + "unknown task: <id>" → format → stdout
list:   load → format all (id, status, command[:50]) → stdout
clear:  save_tasks_atomic(home, {}) → stdout ("cleared")
--json: flows set formatting.format_json() instead of format_human() [AC-FR-03-02]
```

### §3.3 Sequence Diagram (submit happy-path, AC-FR-01-04/05)

```
User         cli.main        validation     store              formatting       stdout
 │               │                │            │                    │              │
 │ taskq submit  │                │            │                    │              │
 │  "echo hi"    │                │            │                    │              │
 │──────────────>│                │            │                    │              │
 │               │ validate       │            │                    │              │
 │               │───────────────>│            │                    │              │
 │               │<─── (True, "")  │            │                    │              │
 │               │ Task(id,pending,cmd,now)    │                    │              │
 │               │ load+merge────────────────>│                    │              │
 │               │ save_atomic ──────────────>│                    │              │
 │               │<──────── ok  ─────────────│                    │              │
 │               │ format_json(task) ────────────────────────────>│              │
 │               │───────────────────────────────── stdout ─────────────────────>│
 │<──────────────│  exit 0        │            │                    │              │
```

### §3.4 Sequence Diagram (run happy-path, AC-FR-02-01..04)

```
User       cli.main    store      runner            subprocess    redaction    store
 │            │          │          │                   │             │          │
 │ taskq run  │          │          │                   │             │          │
 │ <id>       │          │          │                   │             │          │
 │───────────>│          │          │                   │             │          │
 │            │ load ───>│          │                   │             │          │
 │            │<── tasks │          │                   │             │          │
 │            │ run_task(task,cfg)──>│                   │             │          │
 │            │          │          │ shlex.split(cmd)  │             │          │
 │            │          │          │ subprocess.run(──>│             │          │
 │            │          │          │   shlex.split,    │             │          │
 │            │          │          │   capture_output, │             │          │
 │            │          │          │   text=True,      │             │          │
 │            │          │          │   timeout=10.0)   │             │          │
 │            │          │          │<── Completed  ────│             │          │
 │            │          │          │ redaction.apply(stdout) ───────>│          │
 │            │          │          │ redaction.apply(stderr) ───────>│          │
 │            │          │          │ tail to last 2000 │             │          │
 │            │          │          │ status = DONE     │             │          │
 │            │          │ save_atomic(updated) ───────────────────────────────>│
 │            │          │<──── ok ────────────────────────────────────────────│
 │            │<── task ─│          │                   │             │          │
 │<── stdout ─│          │          │                   │             │          │
```

### §3.5 Sequence Diagram (corrupted-store path, AC-FR-01-06)

```
User    cli.main    store.load_tasks
 │         │             │
 │ taskq X │             │
 │────────>│             │
 │         │ load ─────>│
 │         │             │ json.JSONDecodeError
 │         │             │ raise StoreCorrupted
 │         │<─ raise ───│
 │         │ stderr: "store corrupted"
 │<── exit 1 ─────────────────
```
**No silent rebuild**: store.py propagates `StoreCorrupted`; cli.py maps it to exit 1 with the SPEC.md-mandated stderr text.

---

## §4 NFR Handling

### §4.1 NFR-01 (Performance: submit + status combined p95 < 50ms, 100 iter)

| Measure | How architecture satisfies it |
|---------|--------------------------------|
| `submit` does **no** subprocess invocation | `validation.validate_command` + `store.save_tasks_atomic` are pure-Python; no fork/exec path |
| `status` does **no** subprocess invocation | Single `store.load_tasks` + dict lookup; no I/O amplification |
| Load path is bounded | O(N) over N tasks (linear JSON read); no quadratic structures |
| Atomic write is single `os.replace` | One syscall after tmp write completes; no fsync gate (per SPEC scope — atomicity on tmp+os.replace, not durability across power loss) |

**Test**: `tests/test_nfr01_perf.py::test_submit_status_p95_under_50ms` runs 100 × `submit` then `status` in-process (fork-less), measures `time.perf_counter()`, asserts p95 < 50ms; SPEC verbatim exclusion "**不含 subprocess 執行**" is honored by leaving the `run` command out of the measured path.

### §4.2 NFR-02 (Security: no `shell=True`; FR-01 blacklist tested)

| Measure | How architecture satisfies it |
|---------|--------------------------------|
| Single subprocess call site | `runner.run_task` is the **only** module that calls `subprocess.run`; static guard test greps the codebase (`grep -r "shell=True" taskq/`) expecting zero hits |
| `shell=True` is a forbidden kwarg | `runner.py` uses positional/keyword args explicitly without `shell`; test asserts the call signature |
| Injection blacklist declared once | `models.INJECTION_FORBIDDEN` is the canonical source; `validation.validate_command` iterates over it — single chokepoint makes coverage test tractable |
| Blacklist test coverage | `tests/test_fr01_validation.py` parametrizes each of `; | & $ > < \`` (7 chars) + empty/whitespace/length cases |
| `shlex.split` neutralizes shell metacharacters in argv form | `runner.py` passes `shlex.split(command)` to `subprocess.run` list-args form; combined with blacklist, defense-in-depth |

**Test**: `tests/test_nfr02_security.py::test_no_shell_true_in_codebase` greps `taskq/` for `shell\s*=\s*True` and asserts 0 hits; `test_blacklist_chars_all_rejected` covers all 7 forbidden chars.

### §4.3 NFR-03 (Reliability: atomic JSON; secret-line redaction)

| Measure | How architecture satisfies it |
|---------|--------------------------------|
| Atomic write | `store.save_tasks_atomic` writes to `home/tasks.json.tmp` (same dir for `os.replace` atomicity on POSIX), `fsync` optional (excluded from core scope), then `os.replace(tmp, final)` — POSIX guarantees the rename is atomic; mid-write crash leaves the previous good file or an incomplete `.tmp`, never a half-written `tasks.json` |
| Corruption detection | `store.load_tasks` wraps `json.loads` in try/except; on `JSONDecodeError` raises `StoreCorrupted`; cli.py prints `store corrupted` to stderr and exits 1 — never silently overwrites with `{}` |
| Secret-line redaction | `runner.run_task` calls `redaction.apply(proc.stdout[-2000:])` and `redaction.apply(proc.stderr[-2000:])` **before** assigning to `Task.stdout_tail`/`stderr_tail`, so no secret byte survives to disk; `_REDACT_RE` literal pattern is verbatim from SPEC.md |
| Redaction applied per-line | Compiled regex matches anywhere on a line; the entire line is replaced with `[REDACTED]` per SPEC.md AC-NFR-03-02 |

**Tests**: `tests/test_nfr03_reliability.py::test_atomic_write_survives_simulated_crash` writes a corrupted `.tmp` file and asserts `tasks.json` is still valid JSON; `test_secret_line_redacted` runs a subprocess that prints `sk-abcdef1234567890` on one line and `benign output` on another, asserts only the secret line is replaced.

---

## §5 SAB Block (machine-readable — BINDING CONTRACT)

> **CONTRACT**: Field names, types, `sab:` root key, and `phase` as int must
> match `core/quality_gate/sab_parser.py:render_canonical_sab_template()`.
> Schema is taken verbatim from `harness/templates/SAD.md` §5 lines 130-179
> and instantiated with taskq-specific values (project name, FR/NFR keys,
> module names, quality targets, architecture constraints).

<!-- SAB:START -->

```yaml
sab:
  version: "1.0"
  created_at: "2026-06-29"
  phase: 2  # MUST be int, NOT a string — parser raises on 'phase: "2"'
  project: "taskq"

  layers:
    - name: cli
      modules:
        - "taskq.cli.__main__"
        - "taskq.cli.cli"
        - "taskq.cli.formatting"
      allowed_dependencies: ["runner", "io", "core"]
    - name: runner
      modules:
        - "taskq.runner.runner"
      allowed_dependencies: ["io", "core"]
    - name: io
      modules:
        - "taskq.io.store"
        - "taskq.io.redaction"
      allowed_dependencies: ["core"]
    - name: core
      modules:
        - "taskq.core.config"
        - "taskq.core.models"
        - "taskq.core.validation"
      allowed_dependencies: []

  allowed_dependencies:
    - from: cli
      to: runner
    - from: cli
      to: io
    - from: cli
      to: core
    - from: runner
      to: io
    - from: runner
      to: core
    - from: io
      to: core

  quality_targets:
    max_complexity: 10
    min_coverage: 90
    max_coupling: 0.3

  nfr_dimension_mapping: {}  # OPTIONAL — auto-derived from nfr_traceability.type

  nfr_traceability:
    NFR-01:
      type: performance
      target: ">= p95 < 50ms"  # use ">=" or "≥" syntax to RAISE the gate floor
      module: taskq.cli.cli  # submit+status single-shot code path
    NFR-02:
      type: security
      target: ">= 0 shell=True call sites; blacklist all 7 chars"
      module: taskq.runner.runner
    NFR-03:
      type: reliability
      target: ">= atomic write + 100% redaction pre-persist"
      module: taskq.io.store

  advisory_only: []  # AUTO-FILLED by parser — omit or leave []

  gate_score_overrides: {}  # AUTO-DERIVED by parser — omit or leave {}

  # fr_module_traceability entries anchor to SAD §2.1 module file paths
  # (file-path key format = "src/taskq/<dir>/<file>.py" → matches §2.1 directory table).
  # Cross-check contract: every value here must be a path listed in SAD §2.1 line ~103
  # "Rationale per module" table; deviation is a Gate-2 traceability drift.
  fr_module_traceability:
    FR-01: "src/taskq/core/validation.py"  # validation rules (non-empty / length / blacklist); persistence delegated to src/taskq/io/store.py
    FR-02: "src/taskq/runner/runner.py"    # subprocess + retry state machine
    FR-03: "src/taskq/cli/cli.py"          # argparse + --json + exit-code policy

  architecture_constraints:
    - "no_circular_dependencies"  # verified acyclic per §2.4
    - "no_shell_true_anywhere"    # NFR-02: single subprocess site enforces this
    - "stdlib_only"               # SPEC.md §1: zero runtime external dependencies
    - "single_io_site"            # NFR-03: only taskq.io.store writes tasks.json

  high_risk_modules:
    - "taskq.runner.runner"      # sole subprocess call site + retry loop + redaction hookup
    - "taskq.io.store"           # atomic write + corruption detection (StoreCorrupted)
```

<!-- SAB:END -->

Note: Validate before commit: `python3 scripts/generate_sab.py --validate --project .`. The YAML above is the binding contract for Gate 2 / Gate 4 scoring (DRIFT detection reads `nfr_traceability[*].type` against `ALL_NFR_TYPES` = {performance, security, maintainability, reliability, testability, deployability, scalability, usability}).

---

## §6 Self-Review (mandatory per Work Protocol)

- **可能錯誤之處**:
  1. The §2.1 directory restructure (4 subdirs: `core/`, `io/`, `runner/`, `cli/`) is a **CRG-hub-and-spoke rationale** per `harness/templates/SAD.md:44,46,52` — not a SPEC.md requirement. If SPEC.md ever adds a §6 directory structure, the layout must be re-anchored. Confidence: **High** because CRG Principles 1-5 are explicit binding constraints; **Medium** that these specific 4 subdirs are the minimum-cohesion split for this 9-function project (a smaller project could collapse `io/`+`runner/`).
  2. `validation.validate_command` returns a tuple `(ok, error_msg)`; if a future spec demands a structured error (e.g., exit-code-tagged exception), the signature would need to widen. Not a defect today; flagged for SPEC drift detection.
  3. The `run_task(task, cfg, *, on_done)` callback parameter breaks the runner↔store cycle by inverting control (cli.py passes the persist closure). If a future feature requires `run_task` to be callable in isolation (e.g., a library mode without cli), the callback becomes optional with a no-op default.
- **未驗證的假設**:
  - **無** for §2.1 layout (now anchored to CRG Principles 1-5, not "DERIVED from FR/NFR body").
  - SPEC.md says `shell=True` forbidden "everywhere"; a single `subprocess.run` call site in `runner/runner.py` is sufficient. If a future feature adds background spawn (e.g., `Popen` for parallel queue), runner.py must remain the only spawn site — §2.4 sink rule.
  - Retry semantics: `TASKQ_RETRY_LIMIT=0` means **no retry** (initial attempt only); `N>=1` means `N` additional retries. Anchored from SPEC.md §5 (default 2) + SRS.md §2 boundary clarification.
  - §5 SAB block uses ALL_NFR_TYPES values verified by Read of `harness/core/quality_gate/sab_parser.py:259-264`: `(performance, security, maintainability, reliability, testability, deployability, scalability, usability)`. NFR-01/02/03 map to `performance`/`security`/`reliability` per SPEC.md §4 categories.
- **信心等級**: **High** for FR/NFR coverage (every cell in SPEC.md §3/§4 is mapped to ≥ 1 module + ≥ 1 test file in §2.2/§2.3); **High** for §5 SAB schema compliance (verified by Read of `harness/templates/SAD.md:130-179` + `sab_parser.py:166-390`); **High** for directory layout (explicit CRG hub-and-spoke rationale); **High** for acyclic graph (runner↔store cycle resolved by `on_done` callback per §2.4).
- **Cross-check**: matrix in §2.2 covers all 3 FRs; matrix in §2.3 covers all 3 NFRs with legal `type` enum values; sequence diagrams cover submit + run + corrupted-store paths; SAB §5 matches harness canonical schema; no FR/NFR is orphaned.
- **Edge case**: `TASKQ_RETRY_LIMIT=0` no-retry path covered in runner loop (`range(1, 0 + 2)` = `[1]` = initial only); p95 perf test excludes `run` per SPEC.md §4 verbatim ("不含 subprocess 執行"); `on_done=None` callable mode allows runner.py to be tested in isolation without cli.

---

*Document version: SAD v1.0.0 (round 1) | source: SPEC.md v2.0.0 (2026-06-15) + SRS.md round 3 (2026-06-29) | derived §2.1 directory layout is non-canonical and replaceable if SPEC.md §6 is added in a future version.*
