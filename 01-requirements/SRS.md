# SRS — taskq (Software Requirements Specification)

> Source of Truth: `SPEC.md` (project root) — INGESTION MODE.
> This document transcribes FR-01..FR-05 and NFR-01..NFR-06 from SPEC.md verbatim.
> No invention, no omission. Deferral tags (NFR-99, FR-XX-deferred) are used only if SPEC.md itself marks an item as TBD/TODO.

---

## 1. Introduction

### 1.1 Purpose
`taskq` is a local task queue CLI tool for controlled shell command execution. It submits shell commands as tasks, executes them under timeout/retry/circuit-breaker/cache controls, and exposes their status. This SRS is the software requirements specification derived verbatim from `SPEC.md`.

### 1.2 Scope
In scope: CLI tool `python -m taskq` with subcommands `submit`, `run`, `status`, `list`, `clear`; the executor, circuit breaker, TTL cache, and atomic JSON file store; configuration via `TASKQ_*` environment variables.

### 1.3 Definitions, Acronyms, Abbreviations
See §9 Glossary.

### 1.4 References
- `SPEC.md` (project root) — single source of truth.
- `PROJECT_BRIEF.md` — project brief with `canonical_spec: SPEC.md`.

### 1.5 Overview
The remainder of this document enumerates functional requirements (§2), non-functional requirements (§3), constraints (§4), acceptance criteria summary (§5), out-of-scope items (§6), open issues (§7), risks (§8), and glossary (§9).

---

## 2. Functional Requirements

### FR-01 — Task submission and validation
**SPEC citation:** `SPEC.md` §3 FR-01

**Command form:** `taskq submit "<command>" [--name NAME]`

**Validation rules** (any violation → **exit 2** + stderr error, no storage write):

| Rule | Condition |
|------|-----------|
| Non-empty | Empty or whitespace-only command → reject |
| Length | Command > 1000 characters → reject |
| Injection characters | Command contains any of `;` `|` `&` `$` `>` `<` `` ` `` → reject (NFR-02) |
| Name uniqueness | `--name` collides with existing pending/running task → reject |

**On pass:**
- Generate task id (uuid4 first 8 hex chars).
- Status `pending`; record `command`, `name`, `created_at`.
- Atomic write to `$TASKQ_HOME/tasks.json`.
- stdout outputs task id (with `--json`, output `{"id": ..., "status": "pending"}`).

**Testable acceptance criteria:**
- AC-01.1: Empty command → exit 2, no `tasks.json` write.
- AC-01.2: Command length 1001 → exit 2.
- AC-01.3: Each of `; | & $ > < \`` causes exit 2.
- AC-01.4: Duplicate `--name` against pending/running task → exit 2.
- AC-01.5: Valid command → stdout prints 8-hex id; `tasks.json` contains entry with status `pending`.
- AC-01.6: With `--json`, stdout prints single-line `{"id": "<8-hex>", "status": "pending"}`.

---

### FR-02 — Task executor
**SPEC citation:** `SPEC.md` §3 FR-02

**Command forms:** `taskq run <id>` or `taskq run --all`

**Execution:**
- `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)`. **`shell=True` is forbidden in any code path.**
- State machine: `pending → running → done | failed | timeout`.
  - exit 0 → `done`; non-zero → `failed`; `TimeoutExpired` → `timeout`.
- Recorded result fields: `exit_code`, `stdout_tail` (last 2000 chars), `stderr_tail` (last 2000 chars), `duration_ms`, `finished_at`.
- `--all` runs all `pending` tasks concurrently via `ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS)`; storage writes must be thread-safe via a shared `Lock`.
- In single-task mode, a `timeout` result returns **exit 4**.

**Testable acceptance criteria:**
- AC-02.1: `run <id>` for a `pending` task transitions it to `done` (exit 0), `failed` (non-0), or `timeout` (TimeoutExpired).
- AC-02.2: `stdout_tail` and `stderr_tail` each contain at most the last 2000 chars of the corresponding stream.
- AC-02.3: `duration_ms` and `finished_at` are populated on completion.
- AC-02.4: `run --all` invokes all `pending` tasks via `ThreadPoolExecutor`; resulting `tasks.json` is valid JSON with no lost tasks.
- AC-02.5: `grep -R "shell=True" src/` returns no hits (audit).
- AC-02.6: Single-task `timeout` → process exit 4.

---

### FR-03 — Retry and circuit breaker
**SPEC citation:** `SPEC.md` §3 FR-03

**Retry:**
- On `failed` / `timeout`, auto-retry up to `TASKQ_RETRY_LIMIT` times.
- Before the n-th retry, wait `TASKQ_BACKOFF_BASE × 2^n` seconds (exponential backoff). The sleep function must be injectable for testing.

**Circuit breaker** (global, cross-task, cross-process):
- Consecutive final failures (i.e. retries exhausted and still `failed`/`timeout`) ≥ `TASKQ_BREAKER_THRESHOLD` → state `OPEN`.
- During `OPEN`, any `run` is rejected immediately: **exit 3** + stderr `breaker open`, no subprocess executed.
- After `TASKQ_BREAKER_COOLDOWN` seconds → state `HALF_OPEN`: one trial is admitted. Success → state `CLOSED` and counter zeroed. Failure → state re-`OPEN`.
- State is persisted to `$TASKQ_HOME/breaker.json` (atomic write).

**Testable acceptance criteria:**
- AC-03.1: A `failed` task is retried up to `TASKQ_RETRY_LIMIT` times; before the n-th retry, the injected sleep receives `TASKQ_BACKOFF_BASE × 2^n`.
- AC-03.2: After `TASKQ_BREAKER_THRESHOLD` consecutive final failures, the next `run` exits 3 with stderr `breaker open` and does not start a subprocess.
- AC-03.3: After `TASKQ_BREAKER_COOLDOWN` seconds elapse, the next `run` is admitted (`HALF_OPEN`); success closes the breaker (counter zeroed), failure re-opens it.
- AC-03.4: `breaker.json` is written atomically and remains valid JSON after process interruption.

---

### FR-04 — Result TTL cache
**SPEC citation:** `SPEC.md` §3 FR-04

- Cache signature = `sha256(command)`.
- `taskq run <id> --cached`: same signature with a `done` result within `TASKQ_CACHE_TTL` seconds → replay (`exit_code` / `stdout_tail`) without executing a subprocess; task is marked `done` with `cached: true`.
- Cache miss or expired → normal execution; on `done`, write to `$TASKQ_HOME/cache.json`.
- Cache reads/writes are atomic and thread-safe (coexist with FR-02 concurrency).

**Testable acceptance criteria:**
- AC-04.1: First `run --cached` for a command executes the subprocess (or misses); a second `run --cached` for the same command within `TASKQ_CACHE_TTL` replays the cached `exit_code` and `stdout_tail` and sets `cached: true`, with no new subprocess.
- AC-04.2: After `TASKQ_CACHE_TTL` seconds elapse, `run --cached` falls back to normal execution and refreshes `cache.json`.
- AC-04.3: Concurrent `--all` runs with `--cached` do not corrupt `cache.json` (atomic write + thread-safe).
- AC-04.4: Cache key is `sha256(command)`; different commands produce different keys.

---

### FR-05 — CLI integration
**SPEC citation:** `SPEC.md` §3 FR-05

argparse subcommands (entry point: `python -m taskq`):

| Command | Behavior |
|---------|----------|
| `submit "<cmd>" [--name N]` | FR-01 |
| `run <id> [--cached]` / `run --all` | FR-02 / FR-03 / FR-04 |
| `status <id>` | Output all task fields |
| `list [--status S]` | List tasks (optionally filtered by status) |
| `clear` | Clear all `$TASKQ_HOME` data files |

- Global flag `--json`: machine-readable single-line JSON output.
- **Exit codes:** `0` success / `2` input validation error (incl. unknown task id) / `3` breaker open / `4` task timeout / `1` other internal error.

**Testable acceptance criteria:**
- AC-05.1: Each of `submit`, `run`, `status`, `list`, `clear` is reachable as an argparse subcommand.
- AC-05.2: Global `--json` causes subcommand output to be emitted as a single-line JSON object.
- AC-05.3: Exit code matrix: 0 success, 2 unknown task id, 3 breaker open, 4 single-task timeout, 1 other internal error.
- AC-05.4: `status <id>` for an unknown id exits 2 with stderr `unknown task: <id>` (SPEC §7 錯誤處理).

---

## 3. Non-Functional Requirements

### NFR-01 — Performance
**SPEC citation:** `SPEC.md` §4 NFR-01

**Requirement:** `submit` + `status` combined operation (excluding subprocess execution) for 100 iterations: **p95 < 50 ms** (measured with pytest-benchmark).

**Measurable acceptance criterion:**
- AC-NFR01.1: A pytest-benchmark test executes 100 iterations of `submit` followed by `status`; p95 latency < 50 ms.

---

### NFR-02 — Security (injection defense)
**SPEC citation:** `SPEC.md` §4 NFR-02

**Requirement:** `shell=True` is forbidden codebase-wide; FR-01 injection-character blacklist must have test coverage.

**Measurable acceptance criterion:**
- AC-NFR02.1: A static audit (e.g. `grep -R "shell=True" src/`) returns zero matches.
- AC-NFR02.2: Unit tests cover rejection of each injection character in the FR-01 table.

---

### NFR-03 — Reliability (atomic writes & breaker recovery)
**SPEC citation:** `SPEC.md` §4 NFR-03

**Requirement:** All three data files (`tasks.json`, `breaker.json`, `cache.json`) are atomically written (tmp file + `os.replace`); JSON remains valid after process interruption; breaker `OPEN → CLOSED` recovery time ≤ `TASKQ_BREAKER_COOLDOWN` + 1 s.

**Measurable acceptance criterion:**
- AC-NFR03.1: A crash-simulation test (e.g. SIGKILL during write) leaves each of the three data files as valid JSON on next start.
- AC-NFR03.2: A timing test measures the interval from `OPEN` entry to a successful `CLOSED` transition and asserts it is ≤ `TASKQ_BREAKER_COOLDOWN` + 1 s.

---

### NFR-04 — Security (secret redaction)
**SPEC citation:** `SPEC.md` §4 NFR-04

**Requirement:** Before `stdout_tail` / `stderr_tail` are persisted, any line matching the regex `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` is fully replaced with `[REDACTED]`.

**Measurable acceptance criterion:**
- AC-NFR04.1: Unit tests with redaction fixtures verify that lines containing `sk-XXXXXXXX...` and `token=...` are replaced by `[REDACTED]`, and that non-matching lines are preserved verbatim.

---

### NFR-05 — Maintainability (docstring traceability)
**SPEC citation:** `SPEC.md` §4 NFR-05

**Requirement:** All public functions/classes in `src/taskq` carry docstrings containing `[FR-XX]` references.

**Measurable acceptance criterion:**
- AC-NFR05.1: An AST-based lint verifies that every public function/class under `src/taskq` has a docstring and that the docstring contains at least one `[FR-XX]` reference (e.g. `[FR-01]`).

---

### NFR-06 — Deployability (configuration via environment)
**SPEC citation:** `SPEC.md` §4 NFR-06

**Requirement:** All 8 `TASKQ_*` parameters are read from environment variables (config.py unified reader with defaults); `.env.example` declares each with comments.

**Measurable acceptance criterion:**
- AC-NFR06.1: A unit test sets each `TASKQ_*` variable and verifies that `config.py` returns the overridden value, and that unset variables fall back to the documented defaults (SPEC §5.1).
- AC-NFR06.2: `.env.example` contains exactly 8 `TASKQ_*` declarations, each with a comment.

---

## 4. Constraints
**SPEC citation:** `SPEC.md` §1 (概述) and §2 (技術架構)

- Python 3.11; **runtime zero external dependencies** (standard library only; test tooling provided by development environment).
- Form: command-line tool entered via `python -m taskq`.
- CLI: argparse subcommands.
- Task execution: `subprocess` with `shlex.split`; **`shell=True` is forbidden**.
- Concurrency: `concurrent.futures.ThreadPoolExecutor`.
- Persistence: JSON files (atomic write: tmp + `os.replace`).
- Thread safety: `threading.Lock` protecting shared storage.
- Configuration: `TASKQ_*` environment variables, read centrally by `config.py`.
- Injection character blacklist: `; | & $ > < \``.
- Secret redaction in `stdout_tail` / `stderr_tail` (NFR-04).
- `submit` + `status` p95 < 50 ms for 100 iterations (NFR-01).
- All three data files (`tasks.json`, `breaker.json`, `cache.json`) must be atomically written.
- `tasks.json` corruption detection: on startup, if the file is invalid JSON, exit 1 with stderr `store corrupted` (do not silently rebuild) (SPEC §7).

---

## 5. Acceptance Criteria Summary
**SPEC citation:** `SPEC.md` §8 (驗收標準)

- [ ] `pytest tests/ -q` all green.
- [ ] `python -m taskq submit "echo hi"` outputs 8-hex id; `run <id>` → `done`; `status <id>` shows `exit_code: 0`.
- [ ] `python -m taskq submit ""` → exit 2.
- [ ] `python -m taskq submit "echo hi; rm x"` → exit 2 (injection character).
- [ ] With `TASKQ_TASK_TIMEOUT=1`, `run` on a `sleep 5` task → status `timeout`, exit 4.
- [ ] After 3 consecutive final-failure tasks, the 4th `run` → exit 3 (breaker OPEN); after cooldown, runs recover.
- [ ] Within TTL, `run <id> --cached` (same command signature) → replay with `cached: true`, no subprocess execution.
- [ ] `.env.example` declares all 8 `TASKQ_*` variables.
- [ ] After `run --all` concurrent execution, `tasks.json` is valid JSON and no task is lost.
- [ ] Public function docstrings contain `[FR-XX]` references.

---

## 6. Out-of-Scope

- Cross-process distributed coordination beyond the single-`$TASKQ_HOME` atomic JSON store (no remote queue, no database).
- Network-based task submission (no daemon, no HTTP API).
- Container/sandbox isolation of executed commands (relies on host OS permissions and timeout).
- Windows-specific compatibility (SPEC targets Python 3.11 stdlib without platform-specific guarantees beyond what the stdlib provides).
- A web UI / dashboard (CLI only).
- Per-user multi-tenancy in the data store (single `$TASKQ_HOME` per process tree).
- Observability beyond stdout/stderr tails and exit codes (no metrics endpoint, no tracing).
- Authentication / authorization (local tool; assumes trusted local user).

---

## 7. Open Issues

> Items that would be deferred or marked TBD if SPEC.md contained such markers. SPEC.md does **not** mark any FR or NFR as TBD/TODO at the time of this transcription; therefore no `FR-XX-deferred` or `NFR-99` items are emitted in this round.
>
- `NFR-99` (placeholder for any future TBD non-functional requirement): **not emitted** — none found in SPEC.md.
- `FR-XX-deferred` (placeholder for any future TBD functional requirement): **not emitted** — none found in SPEC.md.

**Process note** (process log, not part of requirements): the source document `SPEC.md` was scanned for prompt-injection patterns (e.g. "ignore previous instructions", instruction-override directives) prior to ingestion. No such patterns were detected; all FRs and NFRs are ingested as written.

---

## 8. Risks
**SPEC citation:** `SPEC.md` §9 (風險矩陣)

| ID | Risk | Impact | Likelihood | Mitigation |
|----|------|--------|------------|------------|
| R1 | Concurrent writes corrupt `tasks.json` | High | Medium | Lock + atomic write (NFR-03) |
| R2 | subprocess hang / zombie | Medium | Medium | Mandatory timeout (FR-02) |
| R3 | Breaker falsely latches open | Medium | Low | Cooldown + HALF_OPEN (FR-03) |
| R4 | Cache replay returns stale result | Low | Medium | TTL expiry triggers re-execution (FR-04) |

---

## 9. Glossary

| Term | Definition |
|------|------------|
| `TASKQ_HOME` | Directory holding the three data files; default `.taskq` (env `TASKQ_HOME`). |
| task id | uuid4 first-8-hex (8 hex characters); used as the dictionary key in `tasks.json`. |
| `pending` / `running` / `done` / `failed` / `timeout` | Task lifecycle states defined in FR-02. |
| `OPEN` / `HALF_OPEN` / `CLOSED` | Circuit breaker states defined in FR-03. |
| atomic write | Write to `*.tmp` then `os.replace` to final path; survives process interruption (NFR-03). |
| `cached: true` | Flag recorded on task when result was replayed from TTL cache (FR-04). |
| injection character | Any of `;` `|` `&` `$` `>` `<` `` ` `` — task is rejected if command contains any (FR-01, NFR-02). |
| TTL | Time-to-live; in this codebase the cache expiry interval `TASKQ_CACHE_TTL` (seconds). |
| exponential backoff | Retry sleep schedule of `TASKQ_BACKOFF_BASE × 2^n` seconds before the n-th retry (FR-03). |
| `--json` | Global flag forcing single-line machine-readable JSON output (FR-05). |

---

## 10. FR Block (machine-readable)

<!-- FR:START -->
```json
{
  "version": "1.0",
  "created_at": "2026-06-20",
  "phase": 1,
  "project": "taskq",
  "functional_requirements": [
    {
      "id": "FR-01",
      "description": "Task submission and validation. `taskq submit \"<command>\" [--name NAME]`. Validate non-empty, length<=1000, no injection chars `;` `|` `&` `$` `>` `<` backtick, and name uniqueness vs pending/running. Reject => exit 2 + stderr, no storage write. Accept => uuid4 first-8-hex id, status pending, atomic write to $TASKQ_HOME/tasks.json, stdout id (--json => {\"id\":..,\"status\":\"pending\"}).",
      "implementation_functions": ["cli.submit_cmd", "store.add_task", "executor._validate_command"],
      "verification_method": "unit test validation rules + e2e exit code matrix"
    },
    {
      "id": "FR-02",
      "description": "Task executor. `taskq run <id>` or `taskq run --all`. Uses subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT). shell=True forbidden. State machine pending->running->done|failed|timeout. Records exit_code, stdout_tail (last 2000 chars), stderr_tail (last 2000 chars), duration_ms, finished_at. --all uses ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS); storage writes thread-safe via shared Lock. Single-task timeout => exit 4.",
      "implementation_functions": ["executor.run_task", "executor.run_all", "store.add_task"],
      "verification_method": "unit test state transitions + threading concurrency test"
    },
    {
      "id": "FR-03",
      "description": "Retry and circuit breaker. Retry: failed/timeout auto-retry up to TASKQ_RETRY_LIMIT; nth retry waits TASKQ_BACKOFF_BASE*2^n seconds (exponential; sleep must be injectable). Breaker: global, cross-task, cross-process. Consecutive final failures >= TASKQ_BREAKER_THRESHOLD => OPEN. OPEN period: any run rejected immediately (exit 3 + stderr 'breaker open', no subprocess). After TASKQ_BREAKER_COOLDOWN seconds => HALF_OPEN: one trial; success => CLOSED + counter zeroed; fail => re-OPEN. Persisted in $TASKQ_HOME/breaker.json (atomic write).",
      "implementation_functions": ["executor.run_task", "breaker.Breaker", "breaker.BreakerState"],
      "verification_method": "unit test breaker FSM transitions + retry backoff injection"
    },
    {
      "id": "FR-04",
      "description": "Result TTL cache. Signature = sha256(command). `taskq run <id> --cached`: same signature with done result within TASKQ_CACHE_TTL seconds => replay (exit_code/stdout_tail) without subprocess, task marked done with cached=true. Cache miss/expired => normal execution, write to $TASKQ_HOME/cache.json on done. Cache read/write atomic + thread-safe (coexists with FR-02).",
      "implementation_functions": ["cache.signature", "cache.get", "cache.set", "executor.run_task"],
      "verification_method": "unit test TTL hit/miss/expiry + thread-safe concurrent test"
    },
    {
      "id": "FR-05",
      "description": "CLI integration. argparse subcommands: submit <cmd> [--name N] (FR-01), run <id> [--cached] / run --all (FR-02/03/04), status <id>, list [--status S], clear. Global --json flag for machine-readable output. Exit codes: 0 success / 2 input validation (incl unknown task id) / 3 breaker open / 4 task timeout / 1 other internal error. Entry: python -m taskq.",
      "implementation_functions": ["cli.main", "cli.submit_cmd", "cli.run_cmd", "cli.status_cmd", "cli.list_cmd", "cli.clear_cmd"],
      "verification_method": "e2e exit code matrix for all subcommands + --json flag shape test"
    }
  ],
  "non_functional_requirements": [
    {
      "id": "NFR-01",
      "type": "performance",
      "description": "submit + status combined (excluding subprocess execution) for 100 iterations p95 < 50ms",
      "test_method": "pytest-benchmark measuring submit+status 100x loop"
    },
    {
      "id": "NFR-02",
      "type": "security",
      "description": "shell=True forbidden codebase-wide; FR-01 injection-char blacklist must have test coverage",
      "test_method": "grep audit (negative test for shell=True) + unit test of rejection table"
    },
    {
      "id": "NFR-03",
      "type": "reliability",
      "description": "All three data files atomically written (tmp + os.replace); JSON remains valid after process interrupt; breaker OPEN -> CLOSED recovery <= TASKQ_BREAKER_COOLDOWN + 1s",
      "test_method": "crash simulation (SIGKILL during write) + breaker recovery timing test"
    },
    {
      "id": "NFR-04",
      "type": "security",
      "description": "Before stdout_tail/stderr_tail persistence, lines matching (sk-[A-Za-z0-9_-]{8,}|token=\\S+) are fully replaced with [REDACTED]",
      "test_method": "unit test with redaction regex fixtures (positive + negative cases)"
    },
    {
      "id": "NFR-05",
      "type": "maintainability",
      "description": "All public functions/classes in src/taskq carry docstrings containing [FR-XX] references",
      "test_method": "AST-based docstring + [FR-XX] reference lint"
    },
    {
      "id": "NFR-06",
      "type": "deployability",
      "description": "All 8 TASKQ_* parameters read from environment variables (config.py unified reader with defaults); .env.example declares each with comments",
      "test_method": "env-var unit test + .env.example line count == 8 check"
    }
  ]
}
```
<!-- FR:END -->

