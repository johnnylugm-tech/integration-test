# Project Brief — taskq

## canonical_spec
SPEC.md (v3.0.0, 2026-07-04, 5 FR / 6 NFR / 8 env vars)

## Project Domain
Local task queue CLI tool: submit shell commands as tasks; run with
controlled concurrency, timeout, retry, circuit breaker, and TTL result
cache; query status; clear storage.

## Stakeholders
- Project owner / product manager: johnnylugm-tech
- Integration test target: harness-methodology v2.9 pipeline validation

## Business Goals
- Provide a reliable local task queue CLI (`taskq`) supporting submit,
  run (single / all / cached), status, list (filterable), clear
- Demonstrate full Phase 1–8 harness-methodology development pipeline on
  a real small project with non-trivial functional surface (5 FR covering
  concurrency + circuit breaker + TTL cache)
- Zero runtime external dependencies (Python 3.11 stdlib only)

## Key Constraints
- **Technical**: Python 3.11 stdlib only at runtime; `python -m taskq`
  CLI entry; `shell=True` is forbidden everywhere (NFR-02); `ThreadPoolExecutor`
  for `run --all` with shared `threading.Lock` over store (FR-02)
- **Atomicity**: All three data files (`tasks.json`, `breaker.json`,
  `cache.json`) written via tmp + `os.replace`; mid-write crash must
  leave valid JSON (NFR-03)
- **Security**: Injection character blacklist (`; | & $ > < \``) on
  `submit` (NFR-02); secret-line redaction on `stdout_tail` / `stderr_tail`
  pattern `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` (NFR-04)
- **Reliability**: Circuit breaker opens at consecutive final-failure
  threshold and refuses until cooldown; `tasks.json` corruption is detected
  and surfaced (exit 1) rather than silently rebuilt (NFR-03, FR-03)
- **Performance**: `submit` + `status` combined p95 < 50ms over 100
  iterations (NFR-01)
- **Architecture**: `no_circular_dependencies` among the 8 modules;
  `taskq.executor` and `taskq.store` are framework-classified
  high-risk modules

## FR Inventory (canonical: SPEC.md §3)

| ID | Title | Section |
|----|-------|---------|
| FR-01 | 任務提交與驗證 | submit validation rules (empty / length / injection / name-unique) |
| FR-02 | 任務執行器 | subprocess.run + ThreadPoolExecutor `--all` + thread-safe store |
| FR-03 | 重試與斷路器 | exponential backoff + OPEN/HALF_OPEN/CLOSED state machine |
| FR-04 | 結果 TTL 快取 | sha256(command) cache, atomic + thread-safe write |
| FR-05 | CLI 整合 | argparse subcommands + --json flag + 5 exit codes |

## NFR Inventory (canonical: SPEC.md §4)

| ID | Category | Requirement |
|----|----------|-------------|
| NFR-01 | performance | `submit`+`status` p95 < 50ms over 100 iter |
| NFR-02 | security | 禁用 `shell=True`;注入黑名單須有測試覆蓋 |
| NFR-03 | reliability | 三資料檔全部原子寫;breaker 恢復時間 ≤ cooldown + 1s |
| NFR-04 | security | stdout_tail/stderr_tail 落盤前 redact 敏感行 |
| NFR-05 | maintainability | 公開函式 docstring 全部含 `[FR-XX]` 引用 |
| NFR-06 | deployability | 8 個 `TASKQ_*` 環境變數;`.env.example` 完整宣告 |

## Env Var Inventory (canonical: SPEC.md §5.1 + .env.example)

| Variable | Default | Purpose |
|----------|---------|---------|
| `TASKQ_HOME` | `.taskq` | data file directory |
| `TASKQ_MAX_WORKERS` | `4` | `run --all` concurrent worker count |
| `TASKQ_TASK_TIMEOUT` | `10.0` | per-task subprocess timeout (seconds) |
| `TASKQ_RETRY_LIMIT` | `2` | retry cap on failed/timeout tasks |
| `TASKQ_BACKOFF_BASE` | `0.1` | exponential backoff base (seconds) |
| `TASKQ_BREAKER_THRESHOLD` | `3` | consecutive final failures before breaker OPEN |
| `TASKQ_BREAKER_COOLDOWN` | `5.0` | OPEN → HALF_OPEN cooldown (seconds) |
| `TASKQ_CACHE_TTL` | `3600` | TTL for cached task results (seconds) |

## Data Files (canonical: SPEC.md §5.2)

| File | Content | FR |
|------|---------|----|
| `$TASKQ_HOME/tasks.json` | id → full task fields | FR-01/02 |
| `$TASKQ_HOME/breaker.json` | state / failure_count / opened_at | FR-03 |
| `$TASKQ_HOME/cache.json` | command signature → done result + cached_at | FR-04 |

## Module Layout (canonical: SPEC.md §6)

```
src/taskq/
├── __init__.py
├── __main__.py        # python -m taskq entry
├── config.py          # TASKQ_* env (NFR-06)
├── models.py          # task / status dataclasses
├── store.py           # tasks.json atomic + Lock (FR-01/02) — high-risk
├── executor.py        # subprocess + retry (FR-02/03) — high-risk
├── breaker.py         # circuit breaker (FR-03)
├── cache.py           # TTL cache (FR-04)
└── cli.py             # argparse (FR-05)
```

## Exit Code Map (canonical: SPEC.md §3 / §7)

| Code | Meaning |
|------|---------|
| 0 | success |
| 2 | input validation error (incl. unknown task id) |
| 3 | breaker OPEN |
| 4 | task timeout (single-task mode only) |
| 1 | other internal error |

## Acceptance Criteria (canonical: SPEC.md §8)

10 acceptance items — `pytest -q` green; submit/run/status happy path; 6
negative paths (empty / injection / timeout / breaker-open / cache replay
/ atomic durability under crash); env completeness; concurrent run-all
integrity; docstring FR-cross-ref coverage.

## Risk Matrix (canonical: SPEC.md §9)

| ID | Risk | Mitigation |
|----|------|-----------|
| R1 | concurrent write corruption | Lock + atomic write (NFR-03) |
| R2 | subprocess hangs/zombies | timeout (FR-02) |
| R3 | breaker false-lock | cooldown + HALF_OPEN (FR-03) |
| R4 | cache stale results | TTL expiry forces re-execute (FR-04) |
| R5 | secret-on-disk leak | stdout_tail/stderr_tail redaction (NFR-04) |

## Source of Truth

All functional and non-functional requirements are fully specified in
`SPEC.md` (v3.0.0, 2026-07-04) at the project root — including the §10
framework alignment table and §11 monitoring thresholds.

Phase 1 workflow rules:
- Agent A must operate in INGESTION MODE: transcribe 100% of
  `### FR-01..FR-05` and `### NFR-01..NFR-06` headings from SPEC.md —
  no invention, no omission.
- TBD / TODO / `<placeholder>` markers from SPEC.md must be captured as
  `NFR-99` or `FR-XX-deferred` (not silently dropped).
- §10 framework alignment table is mandatory context for Phase 3 module
  scaffolding (high-risk modules `taskq.executor` / `taskq.store` require
  per-module TDD coverage).
