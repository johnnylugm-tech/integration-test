# SPEC_TRACKING.md

> Source of Truth: `SPEC.md` (project root) — INGESTION MODE.
> All FR/NFR rows transcribe verbatim from SPEC.md sections 3 and 4.

## Project Info
- Project Name: taskq
- Version: v1.0.0
- Created: 2026-06-20
- Source spec: SPEC.md (single source of truth)

## Specification Status

| FR ID | Spec Description | Intent Class | Decision Framework | Status | Notes |
|-------|-----------------|--------------|-------------------|--------|-------|
| FR-01 | Task submission and validation (`taskq submit "<command>" [--name NAME]`). Validation: non-empty; ≤1000 chars; injection-char blacklist `;` `|` `&` `$` `>` `< `` ` ``; name uniqueness vs pending/running. Violation → exit 2 + stderr, no storage write. Pass → uuid4 first-8-hex id, status `pending`, atomic write `$TASKQ_HOME/tasks.json`, stdout id (`--json` prints `{"id":..., "status":"pending"}`). | Behavior (input validation + persistence) | argparse subcommand → store atomic write (tmp + os.replace) | DRAFT | FR-01 + NFR-02; validation gate before any I/O |
| FR-02 | Task executor (`taskq run <id>` / `taskq run --all`). `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` — `shell=True` forbidden. State machine `pending → running → done|failed|timeout` (exit 0 → done; non-0 → failed; TimeoutExpired → timeout). Records `exit_code`, `stdout_tail` (last 2000 chars), `stderr_tail` (last 2000 chars), `duration_ms`, `finished_at`. `--all`: `ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS)`; storage writes thread-safe via shared Lock. Single-task timeout → exit 4. | Behavior (process orchestration) | subprocess without shell=True + ThreadPoolExecutor + Lock | DRAFT | FR-02 + NFR-02 + NFR-03 (thread-safe writes) |
| FR-03 | Retry + circuit breaker. Retry: on `failed`/`timeout` auto-retry up to `TASKQ_RETRY_LIMIT`; nth retry waits `TASKQ_BACKOFF_BASE × 2^n` seconds (sleep injectable for tests). Breaker (global, cross-task, cross-process): consecutive final failures ≥ `TASKQ_BREAKER_THRESHOLD` → `OPEN`; OPEN period any `run` rejected immediately (exit 3 + stderr `breaker open`, no subprocess); after `TASKQ_BREAKER_COOLDOWN` seconds → `HALF_OPEN` (one trial — success → CLOSED + counter zeroed; fail → re-OPEN). Persisted in `$TASKQ_HOME/breaker.json` (atomic write). | Behavior (resilience) | exponential backoff + FSM (CLOSED/OPEN/HALF_OPEN) + atomic persist | DRAFT | FR-03 + NFR-03 |
| FR-04 | Result TTL cache. Signature = `sha256(command)`. `taskq run <id> --cached`: same signature with `done` result within `TASKQ_CACHE_TTL` seconds → replay (`exit_code`/`stdout_tail`) without subprocess, task marked `done` with `cached: true`. Cache miss/expired → normal execution, write to `$TASKQ_HOME/cache.json` on `done`. Cache read/write: atomic + thread-safe (coexists with FR-02). | Behavior (memoization) | sha256 key + TTL check + atomic persist | DRAFT | FR-04; replay must skip subprocess |
| FR-05 | CLI integration. argparse subcommands: `submit "<cmd>" [--name N]` (FR-01); `run <id> [--cached]` / `run --all` (FR-02/03/04); `status <id>`; `list [--status S]`; `clear`. Global `--json` flag (machine-readable). Exit codes: 0 success / 2 input validation (incl. unknown task id) / 3 breaker open / 4 task timeout / 1 other internal error. Entry `python -m taskq`. | Behavior (CLI dispatch) | argparse subparsers + exit code mapping | DRAFT | FR-05; exit code matrix is acceptance gate |
| NFR-01 | Performance: `submit` + `status` combined (excluding subprocess execution) — 100 iterations p95 < 50ms. | Performance | pytest-benchmark on CLI loop | DRAFT | no-subprocess measurement only |
| NFR-02 | Security: `shell=True` forbidden codebase-wide; FR-01 injection-char blacklist must have test coverage. | Security | grep audit + rejection-table unit test | DRAFT | grep must fail-build on regression |
| NFR-03 | Reliability: all three data files atomically written (tmp + `os.replace`); JSON remains valid after process interrupt; breaker `OPEN → CLOSED` recovery ≤ `TASKQ_BREAKER_COOLDOWN` + 1s. | Reliability | crash simulation + breaker recovery timing test | DRAFT | R1 mitigation |
| NFR-04 | Security: before `stdout_tail`/`stderr_tail` persistence, lines matching `(sk-[A-Za-z0-9_-]{8,}\|token=\S+)` are fully replaced with `[REDACTED]`. | Security | regex unit test with positive + negative fixtures | DRAFT | redaction applied at persist boundary |
| NFR-05 | Maintainability: all public functions/classes in `src/taskq` carry docstrings containing `[FR-XX]` references. | Maintainability | AST docstring + `[FR-XX]` lint | DRAFT | required for review |
| NFR-06 | Deployability: all 8 `TASKQ_*` parameters read from env vars (`config.py` unified reader with defaults); `.env.example` declares each with comments. | Deployability | env-var unit test + `.env.example` line-count == 8 check | DRAFT | TASKQ_HOME, TASKQ_MAX_WORKERS, TASKQ_TASK_TIMEOUT, TASKQ_RETRY_LIMIT, TASKQ_BACKOFF_BASE, TASKQ_BREAKER_THRESHOLD, TASKQ_BREAKER_COOLDOWN, TASKQ_CACHE_TTL |
