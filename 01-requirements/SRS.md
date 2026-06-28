# Software Requirements Specification (SRS) — taskq

> Ingestion mode deliverable. Canonical source: `SPEC.md` v2.0.0 (2026-06-15).
> Agent A scope: transcribe FR-01..FR-03 / NFR-01..NFR-03 from SPEC.md verbatim — no invention, no silent omission.
> TBD / `<placeholder>` markers in SPEC.md: none observed (v2.0.0 3-FR compact form).
> Prompt-injection scan: clean — 0 hits in canonical.

---

## 1. Introduction

### 1.1 Purpose
Local task queue CLI — submit shell commands as tasks and run them under control (timeout + retry); status queryable. (SPEC.md §1)

### 1.2 Project Name
`taskq` (SPEC.md §1)

### 1.3 Form & Entry
Command-line tool, entered via `python -m taskq`. (SPEC.md §1, §2)

### 1.4 Language & Dependency
Python 3.11, runtime zero external dependencies (standard library only; test tooling provided by development environment). (SPEC.md §1, §2)

### 1.5 Role in Pipeline
Integration validation target for harness-methodology v2.9 — exercising Phase 1–8 development pipeline on a real small project. (SPEC.md §1, PROJECT_BRIEF.md)

---

## 2. Constraints

Technical, security, reliability and performance constraints transcribed verbatim from SPEC.md §2 + PROJECT_BRIEF.md:

- **Technical**: Python 3.11 stdlib only; `python -m taskq` CLI entry; `shell=True` forbidden everywhere; atomic JSON writes (`tmp + os.replace`). (SPEC.md §2; PROJECT_BRIEF.md)
- **Security**: Injection character blacklist (`; | & $ > < \``) on `submit` (NFR-02). (SPEC.md §3 FR-01)
- **Reliability**: `tasks.json` atomic write survives mid-write crash; never silently rebuilt on parse failure; secret-line redaction on `stdout_tail` / `stderr_tail` (NFR-03). (PROJECT_BRIEF.md; SPEC.md §3 FR-01, §4 NFR-03)
- **Performance**: `submit` + `status` combined p95 < 50ms over 100 iterations (NFR-01). (SPEC.md §4 NFR-01; PROJECT_BRIEF.md)
- **Architecture components** (SPEC.md §2):
  - CLI: argparse subcommands
  - Task execution: `subprocess` with `shlex.split`, `shell=True` forbidden
  - Persistence: JSON file (atomic write: `tmp + os.replace`)
  - Configuration: `TASKQ_*` environment variables (read uniformly by `config.py`)

---

## 3. Functional Requirements

### 3.1 FR-01 — Task Model & Persistence

**Source**: SPEC.md §3 FR-01

**Command**: `taskq submit "<command>"` (SPEC.md §3 FR-01)

**Validation rules** — any violation → **exit 2** + stderr error message, **no write to storage** (SPEC.md §3 FR-01):

| Rule | Condition |
|------|-----------|
| Non-empty | Command empty or all whitespace → reject |
| Length | Command > 1000 chars → reject |
| Injection chars | Command contains any of `;` `|` `&` `$` `>` `<` `` ` `` → reject (NFR-02) |

**On pass** (SPEC.md §3 FR-01):
- Generate task id (uuid4 first 8 hex)
- Status `pending`, record `command`, `created_at`
- Atomic write to `$TASKQ_HOME/tasks.json` (tmp + `os.replace`)
- `tasks.json` corrupt (invalid JSON) → detected at startup → **exit 1**, stderr `store corrupted` (no silent rebuild)

**Acceptance Criteria**:

- **FR-01.AC-1** `submit` with empty command (or whitespace-only) returns exit code 2 with stderr error message and does not create a task in `tasks.json`.
  Citation: SPEC.md §3 FR-01 「命令為空或全空白 → 拒絕」.

- **FR-01.AC-2** `submit` with command length > 1000 characters returns exit code 2 with stderr error message and does not create a task in `tasks.json`.
  Citation: SPEC.md §3 FR-01 「命令 > 1000 字元 → 拒絕」.

- **FR-01.AC-3** `submit` with command containing any of `;` `|` `&` `$` `>` `<` `` ` `` returns exit code 2 with stderr error message and does not create a task in `tasks.json`.
  Citation: SPEC.md §3 FR-01 「注入字元」table row 3 + NFR-02.

- **FR-01.AC-4** `submit` with a valid command generates a task id equal to the first 8 hex chars of a uuid4, sets status `pending`, records `command` and `created_at`, and atomically writes `$TASKQ_HOME/tasks.json` via `tmp + os.replace` (so a crash mid-write leaves a parseable prior or new file, never a half-written one).
  Citation: SPEC.md §3 FR-01 「通過驗證」bullets.

- **FR-01.AC-5** On startup, if `$TASKQ_HOME/tasks.json` is corrupt (invalid JSON), the process exits with code 1 and emits `store corrupted` to stderr; the file is NOT silently rebuilt.
  Citation: SPEC.md §3 FR-01 「tasks.json 損壞」bullet.

### 3.2 FR-02 — Task Execution & Retry

**Source**: SPEC.md §3 FR-02

**Command**: `taskq run <id>` (SPEC.md §3 FR-02)

**Execution** (SPEC.md §3 FR-02):
- Run via `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)`.
- **No path may use `shell=True`** (verbatim SPEC.md §3 FR-02).

**State machine** (SPEC.md §3 FR-02):
`pending → running → done | failed | timeout`
- exit 0 → `done`
- non-zero → `failed`
- `TimeoutExpired` → `timeout`

**Result fields** (SPEC.md §3 FR-02):
- `exit_code`
- `stdout_tail` (last 2000 chars)
- `stderr_tail` (last 2000 chars)
- `duration_ms`
- `finished_at`

**Retry** (SPEC.md §3 FR-02):
- When `run` result is `failed`/`timeout`, automatically retry up to `TASKQ_RETRY_LIMIT` times (default 2).

**Exit codes** (SPEC.md §3 FR-02):
- Single-task mode, `timeout` result → **exit 4**
- Other unexpected exceptions → exit 1 (must NOT be swallowed by a bare `except:`).

**Acceptance Criteria**:

- **FR-02.AC-1** `run <id>` invokes the task command via `subprocess.run` with `shlex.split(command)`, `capture_output=True`, `text=True`, `timeout=TASKQ_TASK_TIMEOUT`, and `shell=False` (i.e. `shell=True` is never used anywhere in the codebase, verified by static check).
  Citation: SPEC.md §3 FR-02 「subprocess.run(...)」 + 「任何路徑不得使用 shell=True」 + NFR-02.

- **FR-02.AC-2** `run <id>` records `exit_code`, `stdout_tail` (last 2000 chars of stdout), `stderr_tail` (last 2000 chars of stderr), `duration_ms`, and `finished_at` on the task.
  Citation: SPEC.md §3 FR-02 「結果欄位」bullet.

- **FR-02.AC-3** When a single run returns `failed` (non-zero exit) or `timeout` (`TimeoutExpired`), `run` automatically retries up to `TASKQ_RETRY_LIMIT` times (default 2).
  Citation: SPEC.md §3 FR-02 「重試」bullet.

- **FR-02.AC-4** In single-task mode, when the final result of `run <id>` is `timeout`, the CLI exits with code 4.
  Citation: SPEC.md §3 FR-02 「單一任務模式下 timeout 結果 → exit 4」.

- **FR-02.AC-5** Any unexpected exception raised by `run` propagates to exit code 1 and is NOT swallowed by a bare `except:` (i.e. no naked `except:` clause exists in the run path).
  Citation: SPEC.md §3 FR-02 「其他未預期例外 → exit 1（不得裸 except: 吞噬）」.

### 3.3 FR-03 — CLI Integration & Query

**Source**: SPEC.md §3 FR-03

**Entry**: `python -m taskq` — argparse subcommands (SPEC.md §3 FR-03).

| Subcommand | Behavior |
|------------|----------|
| `submit "<cmd>"` | FR-01 |
| `run <id>` | FR-02 |
| `status <id>` | Output all fields of that task; unknown id → **exit 2** + `unknown task: <id>` |
| `list` | List all tasks (id + status + first 50 chars of command) |
| `clear` | Clear `$TASKQ_HOME/tasks.json` |

- Global flag `--json`: machine-readable output (single-line JSON) (SPEC.md §3 FR-03).
- **Exit codes**: `0` success / `2` input validation error (incl. unknown task id) / `4` task timeout / `1` other internal error (SPEC.md §3 FR-03).

**Acceptance Criteria**:

- **FR-03.AC-1** The CLI is reachable via `python -m taskq` and exposes the subcommands `submit`, `run`, `status`, `list`, `clear` via argparse.
  Citation: SPEC.md §3 FR-03 「argparse 子命令」.

- **FR-03.AC-2** `status <id>` outputs all task fields for a known id; for an unknown id it exits with code 2 and emits `unknown task: <id>` to stderr (stdout format owned by the test harness per SPEC.md §3 FR-03 `status` row).
  Citation: SPEC.md §3 FR-03 「status」row — verbatim canonical phrase transcribed.

- **FR-03.AC-3** `list` outputs one line per task containing id, status, and the first 50 chars of the command — measurement / interpretation boundary is owned by the test harness per SPEC.md §3 FR-03 `list` row.
  Citation: SPEC.md §3 FR-03 「list」row.

- **FR-03.AC-4** `clear` removes the contents of `$TASKQ_HOME/tasks.json` (so that a subsequent `list` returns no tasks) — measurement / interpretation boundary is owned by the test harness per SPEC.md §3 FR-03 `clear` row.
  Citation: SPEC.md §3 FR-03 「clear」row.

- **FR-03.AC-5** The global flag `--json` is accepted by all subcommands and produces single-line JSON output (instead of human-formatted output) — measurement / interpretation boundary is owned by the test harness per SPEC.md §3 FR-03 「全域 flag --json」.
  Citation: SPEC.md §3 FR-03 「全域 flag --json」bullet.

- **FR-03.AC-6** Exit codes follow the matrix `0` success / `2` input validation error (incl. unknown task id) / `4` task timeout / `1` other internal error.
  Citation: SPEC.md §3 FR-03 「Exit codes」bullet.

---

## 4. Non-Functional Requirements

### 4.1 NFR-01 — Performance

**Source**: SPEC.md §4 NFR-01

**Requirement**: `submit` + `status` combined operation 100 iterations, p95 < 50ms (excluding subprocess execution).

**Acceptance Criteria**:

- **NFR-01.AC-1** Over 100 iterations of `submit` (valid command) + `status` (the returned id), the 95th-percentile wall-clock latency is < 50ms; subprocess execution time is excluded from the measurement — measurement / interpretation boundary is owned by the test harness per SPEC.md §4 NFR-01 「不含 subprocess 執行」.
  Citation: SPEC.md §4 NFR-01 「submit + status 組合操作 100 次 p95 < 50ms（不含 subprocess 執行）」.

### 4.2 NFR-02 — Security

**Source**: SPEC.md §4 NFR-02

**Requirement** (verbatim): codebase MUST NOT use `shell=True` anywhere; FR-01 injection-character blacklist MUST have test coverage.

**Acceptance Criteria**:

- **NFR-02.AC-1** A static check (regex/AST) over the entire codebase finds zero occurrences of `shell=True` in any `subprocess.*` invocation.
  Citation: SPEC.md §4 NFR-02 「全 codebase 禁用 shell=True」.

- **NFR-02.AC-2** The FR-01 injection-character blacklist (`;` `|` `&` `$` `>` `<` `` ` ``) is exercised by at least one test per character (or per equivalence class) that verifies FR-01 rejection.
  Citation: SPEC.md §4 NFR-02 「FR-01 注入字元黑名單必須有測試覆蓋」+ §3 FR-01 「注入字元」row.

### 4.3 NFR-03 — Reliability

**Source**: SPEC.md §4 NFR-03

**Requirement** (verbatim): `tasks.json` atomic write (file remains valid JSON after process interruption); before persistence, `stdout_tail` / `stderr_tail` lines matching `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` are replaced wholesale with `[REDACTED]`.

**Acceptance Criteria**:

- **NFR-03.AC-1** `tasks.json` is written atomically via the `tmp + os.replace` pattern; killing the writer process mid-write (SIGKILL during write) leaves the file either in its pre-write or post-write state — never half-written / unparseable JSON.
  Citation: SPEC.md §4 NFR-03 「tasks.json 原子寫（進程中斷後仍為合法 JSON）」.

- **NFR-03.AC-2** Before `stdout_tail` / `stderr_tail` are persisted, any line matching `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` is replaced verbatim by `[REDACTED]`; the matcher applies to whole lines — measurement / interpretation boundary is owned by the test harness per SPEC.md §4 NFR-03 「過濾 (...) 整行以 [REDACTED] 取代」.
  Citation: SPEC.md §4 NFR-03 「stdout_tail/stderr_tail 落盤前過濾 (...) 整行以 [REDACTED] 取代」.

---

## 5. Acceptance Criteria Summary

| ID | Source | One-line |
|----|--------|----------|
| FR-01.AC-1 | SPEC.md §3 FR-01 | `submit` rejects empty / whitespace-only command with exit 2 and no store write |
| FR-01.AC-2 | SPEC.md §3 FR-01 | `submit` rejects command > 1000 chars with exit 2 and no store write |
| FR-01.AC-3 | SPEC.md §3 FR-01 | `submit` rejects any of `;\|&$><\`` with exit 2 and no store write |
| FR-01.AC-4 | SPEC.md §3 FR-01 | Valid `submit` writes uuid4-8hex id + pending + atomic write |
| FR-01.AC-5 | SPEC.md §3 FR-01 | Corrupt `tasks.json` → exit 1 + `store corrupted`, no silent rebuild |
| FR-02.AC-1 | SPEC.md §3 FR-02 | `run` uses `subprocess.run(shlex.split(...))`; never `shell=True` |
| FR-02.AC-2 | SPEC.md §3 FR-02 | `run` records exit_code, stdout_tail(2000), stderr_tail(2000), duration_ms, finished_at |
| FR-02.AC-3 | SPEC.md §3 FR-02 | `run` auto-retries failed/timeout up to `TASKQ_RETRY_LIMIT` (default 2) |
| FR-02.AC-4 | SPEC.md §3 FR-02 | Single-task mode `timeout` result → exit 4 |
| FR-02.AC-5 | SPEC.md §3 FR-02 | Unexpected exception → exit 1, never swallowed by bare `except:` |
| FR-03.AC-1 | SPEC.md §3 FR-03 | `python -m taskq` exposes submit/run/status/list/clear via argparse |
| FR-03.AC-2 | SPEC.md §3 FR-03 | `status` unknown id → exit 2 + `unknown task: <id>` |
| FR-03.AC-3 | SPEC.md §3 FR-03 | `list` outputs id + status + first 50 chars of command per task |
| FR-03.AC-4 | SPEC.md §3 FR-03 | `clear` empties `$TASKQ_HOME/tasks.json` |
| FR-03.AC-5 | SPEC.md §3 FR-03 | `--json` flag accepted by all subcommands, single-line JSON output |
| FR-03.AC-6 | SPEC.md §3 FR-03 | Exit codes: 0 / 2 (input) / 4 (timeout) / 1 (internal) |
| NFR-01.AC-1 | SPEC.md §4 NFR-01 | submit+status ×100 p95 < 50ms (excluding subprocess exec) |
| NFR-02.AC-1 | SPEC.md §4 NFR-02 | Static check: zero `shell=True` in codebase |
| NFR-02.AC-2 | SPEC.md §4 NFR-02 | Injection blacklist covered by tests (one+ per char / class) |
| NFR-03.AC-1 | SPEC.md §4 NFR-03 | Atomic write survives SIGKILL mid-write (always parseable JSON) |
| NFR-03.AC-2 | SPEC.md §4 NFR-03 | Lines matching `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` → `[REDACTED]` on persist |

---

## 6. Out-of-Scope

- Multi-process / distributed task queue semantics (SPEC.md specifies a local single-store CLI only).
- Network access, remote submission, or authn/authz (no SPEC.md clause; not part of `taskq`).
- Privileged / root operations, system service / daemon mode (no SPEC.md clause).
- Cross-platform packaging distribution beyond `python -m taskq` invocation.
- Schema migration / versioning of `tasks.json` beyond the v2.0.0 layout in SPEC.md §3 FR-01.
- Schema migration is currently unspecified; see §7 (NFR-99 deferred items).

---

## 7. Open Issues / Deferred Items

| Tag | Description | Reference |
|-----|-------------|-----------|
| NFR-99 (none) | No TBD / TODO / `<placeholder>` markers present in SPEC.md v2.0.0; nothing to defer. | SPEC.md full text scan |

Note (verbatim canonical interpretation): SPEC.md §4 NFR-03 「過濾 (sk-[A-Za-z0-9_-]{8,}\|token=\S+) 整行以 [REDACTED] 取代」 is transcribed verbatim into NFR-03.AC-2 — measurement / interpretation boundary (what counts as a "line"; whether trailing newline handling matters) is owned by the test harness per SPEC.md phrasing.

---

## 8. Risks

Risk roll-up transcribed from SPEC.md §4 footer + PROJECT_BRIEF.md:

| ID | Risk | Mitigation in SPEC |
|----|------|--------------------|
| R1 | Concurrent / interrupted write corrupting `tasks.json` | NFR-03 (atomic write) |
| R2 | Subprocess hang | FR-02 timeout |
| R3 | Secret leakage to disk via stdout/stderr tails | NFR-03 (line redaction) |

---

## 9. Glossary

| Term | Definition |
|------|------------|
| taskq | Local task queue CLI; project name (SPEC.md §1) |
| task id | uuid4 first 8 hex chars (SPEC.md §3 FR-01) |
| atomic write | tmp + `os.replace` write pattern (SPEC.md §2, §3 FR-01) |
| shlex split | Tokenize command safely without invoking shell (SPEC.md §3 FR-02) |
| redaction | Whole-line replacement of secret-matching lines with `[REDACTED]` (SPEC.md §4 NFR-03) |
| TASKQ_HOME | Environment variable: data directory (default `.taskq`) (SPEC.md §5) |
| TASKQ_TASK_TIMEOUT | Env var: per-subprocess timeout seconds (default `10.0`) (SPEC.md §5) |
| TASKQ_RETRY_LIMIT | Env var: retry cap on failed/timeout (default `2`) (SPEC.md §5) |

---

*Document version: derived from SPEC.md v2.0.0 (2026-06-15).*
*Mode: INGESTION — 100% transcription of FR-01..FR-03 / NFR-01..NFR-03.*