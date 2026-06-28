# Software Requirements Specification (SRS) — taskq

> **Source of Truth**: This SRS transcribes `SPEC.md` (v2.0.0, 2026-06-15) at the project root.
> Mode: **INGESTION** (per `PROJECT_BRIEF.md` → `canonical_spec: SPEC.md`).
> Citation format: every AC is tagged `[SPEC §3 FR-XX]` or `[SPEC §4 NFR-XX]`.

---

## 1. Introduction

### 1.1 Project Name
`taskq` (per SPEC §1 「專案名稱:taskq」).

### 1.2 Purpose
Local task queue CLI — submit shell commands as tasks, run under control (timeout/retry), status queryable (per SPEC §1 「目的」).

### 1.3 Language & Form
- **Language**: Python 3.11, **runtime zero external dependencies** (stdlib only; test tooling provided by dev environment) — verbatim SPEC §1.
- **Form**: command-line tool, entered via `python -m taskq` — verbatim SPEC §1.

### 1.4 Technical Architecture (per SPEC §2)
| Component | Technology |
|-----------|------------|
| CLI | argparse subcommands |
| Task execution | subprocess (`shlex.split`, `shell=True` forbidden) |
| Persistence | JSON file (atomic write: tmp + `os.replace`) |
| Configuration | `TASKQ_*` environment variables (unified read by `config.py`) |

---

## 2. Constraints (verbatim SPEC §1 + §2)

- **C-1** Python 3.11 stdlib only; `python -m taskq` CLI entry; `shell=True` forbidden everywhere; atomic JSON writes (`tmp + os.replace`) — per PROJECT_BRIEF.md Key Constraints (Technical).
- **C-2** Injection character blacklist (`; | & $ > < \``) on `submit` — per PROJECT_BRIEF.md Key Constraints (Security).
- **C-3** `tasks.json` atomic write survives mid-write crash; never silently rebuilt on parse failure; secret-line redaction on `stdout_tail` / `stderr_tail` — per PROJECT_BRIEF.md Key Constraints (Reliability).
- **C-4** `submit` + `status` combined p95 < 50ms over 100 iterations — per PROJECT_BRIEF.md Key Constraints (Performance).

---

## 3. Functional Requirements

### FR-01: Task Model & Persistence — `[SPEC §3 FR-01]`

> DERIVED: SPEC §3 FR-01 — 驗證規則(任一違反 → **exit 2** + stderr 錯誤訊息,**不寫入存儲**) / 通過驗證 — English translation of canonical Chinese spec; ACs preserve all five rule rows (非空/長度/注入字元) and four on-pass rows verbatim, only normalized to lowercase English identifiers and quoted exit codes.

**CLI**: `taskq submit "<command>"` — verbatim SPEC §3 FR-01.

**AC-FR-01.1 Validation rules** — verbatim SPEC §3 FR-01 驗證規則:
- **AC-FR-01.1.a (非空)**: empty or whitespace-only command → reject with `exit 2` + stderr error message; **no write to store**.
- **AC-FR-01.1.b (長度)**: command > 1000 chars → reject with `exit 2` + stderr error message; **no write to store**.
- **AC-FR-01.1.c (注入字元)**: command contains any of `;` `|` `&` `$` `>` `<` `` ` `` → reject with `exit 2` + stderr error message; **no write to store** (NFR-02).

**AC-FR-01.2 On pass** — verbatim SPEC §3 FR-01 通過驗證:
- **AC-FR-01.2.a**: produce task id (uuid4 first 8 hex).
- **AC-FR-01.2.b**: status `pending`; record `command`, `created_at`.
- **AC-FR-01.2.c**: atomic write to `$TASKQ_HOME/tasks.json` (tmp + `os.replace`).
- **AC-FR-01.2.d**: `tasks.json` corrupted (invalid JSON) → startup detection → `exit 1`, stderr `store corrupted` (no silent rebuild).

### FR-02: Task Execution & Retry — `[SPEC §3 FR-02]`

> DERIVED: SPEC §3 FR-02 — 以 `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` 執行;**任何路徑不得使用 `shell=True`** / 狀態機 / 結果欄位 / 重試 / exit codes — English translation of canonical Chinese spec; ACs preserve the subprocess invocation, state machine, all five result fields, retry cap, and two exit-code rows verbatim.

**CLI**: `taskq run <id>` — verbatim SPEC §3 FR-02.

**AC-FR-02.1 Execution primitive** — verbatim SPEC §3 FR-02:
- **AC-FR-02.1.a**: execute via `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)`; **no code path may use `shell=True`**.

**AC-FR-02.2 State machine** — verbatim SPEC §3 FR-02:
- **AC-FR-02.2.a**: `pending → running → done | failed | timeout`.
- **AC-FR-02.2.b**: exit 0 → `done`; non-zero → `failed`; `TimeoutExpired` → `timeout`.

**AC-FR-02.3 Result fields** — verbatim SPEC §3 FR-02 結果欄位:
- **AC-FR-02.3.a**: record `exit_code`, `stdout_tail` (last 2000 chars), `stderr_tail` (last 2000 chars), `duration_ms`, `finished_at`.

**AC-FR-02.4 Retry** — verbatim SPEC §3 FR-02 重試:
- **AC-FR-02.4.a**: when `run` result is `failed` / `timeout`, auto-retry up to `TASKQ_RETRY_LIMIT` times (default 2).

**AC-FR-02.5 Exit codes** — verbatim SPEC §3 FR-02:
- **AC-FR-02.5.a**: in single-task mode, `timeout` result → `exit 4`.
- **AC-FR-02.5.b**: other unexpected exceptions → `exit 1` (no bare `except:` swallowing).

### FR-03: CLI Integration & Query — `[SPEC §3 FR-03]`

> DERIVED: SPEC §3 FR-03 — argparse 子命令(入口 `python -m taskq`) / 全域 flag `--json` / Exit codes — English translation of canonical Chinese spec; command table, --json flag, and 4 exit-code values preserved verbatim.

argparse subcommands (entry `python -m taskq`) — verbatim SPEC §3 FR-03:

| Command | Behavior |
|---------|----------|
| `submit "<cmd>"` | FR-01 |
| `run <id>` | FR-02 |
| `status <id>` | output all fields of that task; unknown id → `exit 2` + `unknown task: <id>` |
| `list` | list all tasks (id + status + first 50 chars of command) |
| `clear` | clear `$TASKQ_HOME/tasks.json` |

**AC-FR-03.1 Global flag** — verbatim SPEC §3 FR-03:
- **AC-FR-03.1.a**: global flag `--json` produces machine-readable output (single-line JSON).

**AC-FR-03.2 Exit codes** — verbatim SPEC §3 FR-03:
- **AC-FR-03.2.a**: `0` success / `2` input validation error (including unknown task id) / `4` task timeout / `1` other internal error.

---

## 4. Non-Functional Requirements

### NFR-01: Performance — `[SPEC §4 NFR-01]`

> DERIVED: SPEC §4 NFR-01 — `submit` + `status` 組合操作 100 次 p95 < 50ms(不含 subprocess 執行) — English translation of canonical Chinese spec; the parenthetical 「不含 subprocess 執行」 is preserved verbatim per R-CANONICAL-INTERP-001 (no prescriptive interpretation added; ambiguity flagged in NFR-99).

**AC-NFR-01.1**: combined `submit` + `status` operations across 100 iterations, p95 < 50ms (excluding subprocess execution) — verbatim SPEC §4 NFR-01.

> Boundary interpretation: **「excluding subprocess execution」 — measurement / interpretation boundary is owned by the test harness per SPEC §4 NFR-01 row.** If the test harness interprets this as "wall-clock per iteration includes only the taskq-side Python code (store read/write + argparse + JSON emit), not the spawned subprocess", it must state so explicitly. (No prescriptive methodology added.)

### NFR-02: Security — `[SPEC §4 NFR-02]`

> DERIVED: SPEC §4 NFR-02 — 全 codebase 禁用 `shell=True`;FR-01 注入字元黑名單必須有測試覆蓋 — English translation of canonical Chinese spec; two clauses split into AC-NFR-02.1 (codebase-wide prohibition) and AC-NFR-02.2 (test coverage requirement).

**AC-NFR-02.1**: `shell=True` forbidden across the entire codebase — verbatim SPEC §4 NFR-02.

**AC-NFR-02.2**: FR-01 injection character blacklist MUST have test coverage — verbatim SPEC §4 NFR-02.

### NFR-03: Reliability — `[SPEC §4 NFR-03]`

> DERIVED: SPEC §4 NFR-03 — `tasks.json` 原子寫(進程中斷後仍為合法 JSON);`stdout_tail`/`stderr_tail` 落盤前過濾 `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` 整行以 `[REDACTED]` 取代 — English translation of canonical Chinese spec; the verbatim regex `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` is preserved unchanged per R-CANONICAL-INTERP-001 (matching-unit ambiguity flagged in NFR-99).

**AC-NFR-03.1**: `tasks.json` atomic write — survives mid-process interruption and remains valid JSON on disk — verbatim SPEC §4 NFR-03.

**AC-NFR-03.2**: before persisting `stdout_tail` / `stderr_tail`, filter lines matching `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` and replace the entire matched line with `[REDACTED]` — verbatim SPEC §4 NFR-03.

> Boundary interpretation: **「(sk-[A-Za-z0-9_-]{8,}|token=\S+)」 — measurement / interpretation boundary is owned by the test harness per SPEC §4 NFR-03 row.** The verbatim regex is captured as-is; whether matching is applied per-line or per-stdout is the harness's call. (No prescriptive methodology added.)

---

## 5. Configuration — `[SPEC §5]`

Unified read by `config.py` (with defaults; full declaration in `.env.example`) — verbatim SPEC §5:

| Variable | Default | Description |
|----------|---------|-------------|
| `TASKQ_HOME` | `.taskq` | Data directory |
| `TASKQ_TASK_TIMEOUT` | `10.0` | Per-task subprocess timeout (seconds) |
| `TASKQ_RETRY_LIMIT` | `2` | Auto-retry limit on failure |

---

## 6. Acceptance Criteria Summary

| AC ID | Description | Source |
|-------|-------------|--------|
| AC-FR-01.1.a | Empty/whitespace command rejected (exit 2, no write) | SPEC §3 FR-01 |
| AC-FR-01.1.b | Command > 1000 chars rejected (exit 2, no write) | SPEC §3 FR-01 |
| AC-FR-01.1.c | Injection chars `;\|&$><\`` rejected (exit 2, no write) | SPEC §3 FR-01 + NFR-02 |
| AC-FR-01.2.a | task id = uuid4 first 8 hex | SPEC §3 FR-01 |
| AC-FR-01.2.b | status=pending + record command/created_at | SPEC §3 FR-01 |
| AC-FR-01.2.c | atomic write to $TASKQ_HOME/tasks.json (tmp+os.replace) | SPEC §3 FR-01 |
| AC-FR-01.2.d | corrupted tasks.json → exit 1 + stderr `store corrupted` | SPEC §3 FR-01 |
| AC-FR-02.1.a | subprocess.run with shlex.split, capture_output, text, timeout; no shell=True | SPEC §3 FR-02 |
| AC-FR-02.2.a | state machine pending→running→done\|failed\|timeout | SPEC §3 FR-02 |
| AC-FR-02.2.b | exit-code-to-status mapping | SPEC §3 FR-02 |
| AC-FR-02.3.a | record exit_code, stdout_tail (last 2000), stderr_tail (last 2000), duration_ms, finished_at | SPEC §3 FR-02 |
| AC-FR-02.4.a | auto-retry on failed/timeout up to TASKQ_RETRY_LIMIT (default 2) | SPEC §3 FR-02 |
| AC-FR-02.5.a | single-task mode timeout → exit 4 | SPEC §3 FR-02 |
| AC-FR-02.5.b | unexpected exception → exit 1 (no bare except:) | SPEC §3 FR-02 |
| AC-FR-03 (table) | submit/run/status/list/clear behaviors | SPEC §3 FR-03 |
| AC-FR-03.1.a | --json global flag → single-line JSON | SPEC §3 FR-03 |
| AC-FR-03.2.a | exit codes 0/2/4/1 mapping | SPEC §3 FR-03 |
| AC-NFR-01.1 | submit+status 100-iter p95 < 50ms (excluding subprocess) | SPEC §4 NFR-01 |
| AC-NFR-02.1 | shell=True forbidden across codebase | SPEC §4 NFR-02 |
| AC-NFR-02.2 | FR-01 injection blacklist test coverage required | SPEC §4 NFR-02 |
| AC-NFR-03.1 | tasks.json atomic write survives interruption | SPEC §4 NFR-03 |
| AC-NFR-03.2 | redaction regex `(sk-[A-Za-z0-9_-]{8,}\|token=\S+)` line-level → `[REDACTED]` | SPEC §4 NFR-03 |

---

## 7. Out-of-Scope

- Distributed/cluster task scheduling (SPEC only covers local single-host CLI).
- Job priorities, dependencies, scheduling policies (SPEC has no such feature).
- Web UI / REST API / daemon mode (SPEC only specifies CLI entry).
- Multi-language runtime bindings (SPEC only specifies Python 3.11 stdlib).
- Authentication / multi-user access control (SPEC has no auth feature).

---

## 8. Open Issues

- **NFR-99**: Resolve SPEC §4 NFR-01 「excluding subprocess execution」 ambiguity in NFR-01 — current SPEC phrasing is ambiguous between (A) wall-clock of each `submit`/`status` invocation excluding only the spawned subprocess time vs (B) total harness iteration time including argparse/JSON I/O; test harness to confirm with stakeholder. (No FR/NFR body in SPEC corresponds to this clarification.)
- **NFR-99**: Resolve SPEC §4 NFR-03 regex application scope in NFR-03 — current SPEC phrasing is ambiguous between (A) per-line match within `stdout_tail`/`stderr_tail` vs (B) match against the entire buffer; verbatim regex is captured in AC-NFR-03.2 but matching unit is the harness's call.
- **No FR-XX-deferred**: SPEC.md v2.0.0 contains no TBD/TODO/`<placeholder>` markers; all 3 FRs and 3 NFRs are fully specified.

---

## 9. Risks (verbatim SPEC §4 risk footer)

- **R1**: concurrent / interrupted writes corrupt the store — mitigated by NFR-03 (atomic write).
- **R2**: subprocess hangs — mitigated by FR-02 (`timeout`).
- **R3**: secrets leaked to disk — mitigated by NFR-03 (redaction).

---

## 10. Glossary

- **taskq**: the project / CLI tool name (SPEC §1).
- **`$TASKQ_HOME`**: data directory environment variable, default `.taskq` (SPEC §5).
- **`tasks.json`**: the persistence file under `$TASKQ_HOME` (SPEC §3 FR-01).
- **atomic write**: write to a temp file then `os.replace` to the target (SPEC §2).
- **shlex.split**: POSIX-shell-like splitting used to break a command string into argv tokens for `subprocess.run` without invoking a shell (SPEC §2 / §3 FR-02).
- **`shell=True` forbidden**: SPEC §2 / §4 NFR-02 prohibition.
- **uuid4 first 8 hex**: first 8 hex chars of a uuid4 — used as the task id (SPEC §3 FR-01).

---

*Document version: SRS v1.0.0 — INGESTION of SPEC.md v2.0.0 (2026-06-15). Mode: INGESTION. Citation anchor: every AC tagged with `[SPEC §X]`. Prompt-injection scan: clean — 0 hits in canonical.*