# SRS — Software Requirements Specification: taskq

> **Mode**: INGESTION MODE (canonical_spec = SPEC.md)
> **Source of truth**: `SPEC.md` v2.0.0 (2026-06-15) at repo root
> **Project role**: harness-methodology v2.9 integration validation target
> **Date**: 2026-06-26

---

## 1. Introduction

### 1.1 Purpose
This Software Requirements Specification (SRS) is the authoritative statement of requirements for **`taskq`**, a local task queue CLI tool. It is derived entirely (INGESTION MODE) from `SPEC.md` v2.0.0 (2026-06-15), the project's canonical spec identified by `PROJECT_BRIEF.md`.

### 1.2 Scope
- **Project name**: `taskq`
- **Purpose**: Local task queue CLI — submit shell commands as tasks, run them under control (timeout/retry), query status.
- **Language**: Python 3.11, **runtime zero external dependencies** (stdlib only; test tooling is provided by the dev environment)
- **Form**: Command-line tool, entered via `python -m taskq`

### 1.3 Definitions, Acronyms, Abbreviations
See §9 Glossary.

### 1.4 References
- `SPEC.md` v2.0.0 (2026-06-15) — canonical spec
- `PROJECT_BRIEF.md` — project brief, identifies canonical_spec
- `CLAUDE.md` (project) — harness/methodology instructions

### 1.5 Document Mode Statement
This SRS is in **INGESTION MODE**. Every functional and non-functional requirement below is a faithful transcription of the corresponding section in `SPEC.md`. No requirements have been invented, paraphrased substantively, or silently dropped. TBD/TODO/placeholder markers (none present in v2.0.0) would be captured under `NFR-99` or `FR-XX-deferred` (§7 Open Issues).

---

## 2. Constraints

### 2.1 Technical Constraints
- Python 3.11 stdlib only; no runtime external dependencies.
- CLI entry point: `python -m taskq`.
- `shell=True` is **forbidden everywhere** in the codebase.
- All task persistence uses JSON file with atomic write semantics: `tmp + os.replace`.

### 2.2 Security Constraints
- FR-01 injection character blacklist (`; | & $ > < \``) enforced on `submit`.
- Codebase must be free of `shell=True` (cross-referenced by NFR-02).

### 2.3 Reliability Constraints
- `tasks.json` must remain valid JSON even on mid-write crash (atomic write semantics).
- Corrupted `tasks.json` must NOT be silently rebuilt on startup — detect → exit 1, stderr `store corrupted`.
- Secret-line redaction applied to `stdout_tail` / `stderr_tail` before persisting (NFR-03).

### 2.4 Performance Constraints
- `submit` + `status` combined p95 < 50ms over 100 iterations (NFR-01; excludes subprocess execution time).

### 2.5 Configuration Constraints
- All config read via `config.py` using `TASKQ_*` env vars with documented defaults.
- `.env.example` must fully declare every `TASKQ_*` variable.

### 2.6 Architectural Constraints (from project CLAUDE.md)
- `no_shell_true`
- `atomic_writes_only`

### 2.7 High-Risk Modules (from project CLAUDE.md)
- `taskq.executor`
- `taskq.store`

---

## 3. Functional Requirements

### FR-01: 任務模型與持久化 (Task Model and Persistence)

**Source**: SPEC.md §3 FR-01
**Command**: `taskq submit "<command>"`

#### Validation Rules (any violation → exit 2 + stderr error, no storage write)

| Rule | Condition |
|------|-----------|
| Non-empty | Command is empty or all whitespace → reject |
| Length | Command > 1000 characters → reject |
| Injection chars | Command contains any of `;` `|` `&` `$` `>` `<` `` ` `` → reject (cross-ref NFR-02) |

#### On Successful Validation
- Generate task id (uuid4 first 8 hex chars).
- Status `pending`; record `command` and `created_at`.
- Atomically write to `$TASKQ_HOME/tasks.json` (tmp + `os.replace`).
- If `tasks.json` is corrupted (invalid JSON) → detect on startup → **exit 1**, stderr `store corrupted` (must NOT silently rebuild).

#### Acceptance Criteria
- AC-FR01-01: Empty command → exit 2, stderr error, no write to `tasks.json`.
- AC-FR01-02: All-whitespace command → exit 2, stderr error, no write.
- AC-FR01-03: Command of exactly 1000 chars → accepted (boundary inclusive).
- AC-FR01-04: Command of 1001 chars → exit 2, stderr error, no write.
- AC-FR01-05: Command containing any of `; | & $ > < \` ` → exit 2, stderr error, no write (testable per character, 7 cases).
- AC-FR01-06: Valid command → task id is exactly 8 lowercase hex chars (uuid4 prefix).
- AC-FR01-07: Task record contains `status: "pending"`, `command`, `created_at` (ISO-8601 UTC).
- AC-FR01-08: Successful submit persists to `$TASKQ_HOME/tasks.json` via tmp + `os.replace` (verify tmp file deleted/replaced, no partial writes observable).
- AC-FR01-09: When `tasks.json` is corrupted (e.g. truncated, garbage bytes) → startup exit 1, stderr contains `store corrupted`; `tasks.json` content is NOT replaced.

---

### FR-02: 任務執行與重試 (Task Execution and Retry)

**Source**: SPEC.md §3 FR-02
**Command**: `taskq run <id>`

#### Execution
- Execute via `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)`.
- **`shell=True` is forbidden on any code path.**

#### State Machine
```
pending → running → done | failed | timeout
```
- exit 0 → `done`
- non-zero exit → `failed`
- `TimeoutExpired` → `timeout`

#### Result Fields
- `exit_code`
- `stdout_tail` (last 2000 chars)
- `stderr_tail` (last 2000 chars)
- `duration_ms`
- `finished_at`

#### Retry Policy
- On `run` result of `failed` or `timeout`, automatically retry up to `TASKQ_RETRY_LIMIT` times (default 2).

#### Exit Codes
- `timeout` result in single-task mode → **exit 4**.
- Other unexpected exceptions → exit 1 (no bare `except:` swallowing).

#### Acceptance Criteria
- AC-FR02-01: Successful command (exit 0) → task status `done`, `exit_code == 0`, stdout/stderr captured in tail fields.
- AC-FR02-02: Command with non-zero exit → task status `failed`, `exit_code` matches subprocess.
- AC-FR02-03: Command exceeding `TASKQ_TASK_TIMEOUT` → task status `timeout`, exit code 4 from CLI.
- AC-FR02-04: `stdout_tail` / `stderr_tail` are each at most 2000 chars (truncate from the head; preserve last 2000).
- AC-FR02-05: `duration_ms` is a non-negative integer representing elapsed milliseconds.
- AC-FR02-06: `finished_at` is recorded.
- AC-FR02-07: After `failed`, automatic retry up to `TASKQ_RETRY_LIMIT` (default 2) attempts; final recorded result is the last attempt.
- AC-FR02-08: After `timeout`, automatic retry up to `TASKQ_RETRY_LIMIT` attempts.
- AC-FR02-09: Unexpected exception path → exit 1 (no bare `except:`).
- AC-FR02-10: `shell=True` is never invoked (verified by codebase grep + AC NFR-02-02).

---

### FR-03: CLI 整合與查詢 (CLI Integration and Query)

**Source**: SPEC.md §3 FR-03
**Entry**: `python -m taskq`
**Parser**: argparse subcommands

#### Subcommands

| Command | Behavior |
|---------|----------|
| `submit "<cmd>"` | FR-01 |
| `run <id>` | FR-02 |
| `status <id>` | Output all fields for the task; unknown id → **exit 2** + `unknown task: <id>` |
| `list` | List all tasks (id + status + first 50 chars of command) |
| `clear` | Clear `$TASKQ_HOME/tasks.json` |

#### Global Flag
- `--json`: machine-readable single-line JSON output.

#### Exit Codes (global)
| Code | Meaning |
|------|---------|
| 0 | success |
| 2 | input validation error (including unknown task id) |
| 4 | task timeout |
| 1 | other internal errors |

#### Acceptance Criteria
- AC-FR03-01: `taskq submit "echo hi"` succeeds per FR-01 (round-trip).
- AC-FR03-02: `taskq status <valid-id>` outputs all task fields; exits 0.
- AC-FR03-03: `taskq status <unknown-id>` → exit 2, stderr contains `unknown task: <id>`.
- AC-FR03-04: `taskq list` outputs one line per task containing id, status, and first 50 chars of command.
- AC-FR03-05: `taskq list` on empty store → empty list output, exit 0.
- AC-FR03-06: `taskq clear` empties `$TASKQ_HOME/tasks.json`; subsequent `list` shows no tasks.
- AC-FR03-07: `--json` flag on `status` and `list` produces single-line JSON output, valid JSON parseable.
- AC-FR03-08: Exit codes match table for each defined condition.

---

## 4. Non-Functional Requirements

### NFR-01: Performance

**Source**: SPEC.md §4 NFR-01
**Category**: performance

**Statement**: `submit` + `status` combined operation 100 times, p95 < 50ms (excluding subprocess execution time).

#### Acceptance Criteria
- AC-NFR01-01: Measured over 100 iterations of `submit` immediately followed by `status` of the just-submitted task, the 95th-percentile latency is < 50ms (cold path and warm path both qualify; subprocess execution is excluded from the measurement window).
- AC-NFR01-02: Measurement methodology and raw timings must be reproducible from a documented script/benchmark.

---

### NFR-02: Security

**Source**: SPEC.md §4 NFR-02
**Category**: security

**Statement**:
- `shell=True` is forbidden throughout the entire codebase.
- FR-01 injection character blacklist must have test coverage.

#### Acceptance Criteria
- AC-NFR02-01: Codebase-wide grep for `shell=True` returns zero matches in `taskq/` source tree (excluding test data, comments, and third-party).
- AC-NFR02-02: Test suite contains at least one test case for each of the 7 blacklist characters: `;`, `|`, `&`, `$`, `>`, `<`, `` ` `` — verifying FR-01 rejection.
- AC-NFR02-03: No execution path invokes a shell to interpret user-supplied `command` (defense-in-depth on top of AC-NFR02-01).

---

### NFR-03: Reliability

**Source**: SPEC.md §4 NFR-03
**Category**: reliability

**Statement**:
- `tasks.json` atomic write — remains valid JSON after process interruption.
- `stdout_tail` / `stderr_tail` are filtered before persistence: any line matching `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` is replaced entirely with `[REDACTED]`.

#### Acceptance Criteria
- AC-NFR03-01: `tasks.json` is always valid JSON immediately after any process state (including SIGKILL mid-write, simulated by injecting pre-write trap).
- AC-NFR03-02: Persisted `stdout_tail` / `stderr_tail` contain `[REDACTED]` in place of any line matching `sk-[A-Za-z0-9_-]{8,}` (e.g. `sk-abcdefgh1234`).
- AC-NFR03-03: Persisted `stdout_tail` / `stderr_tail` contain `[REDACTED]` in place of any line matching `token=\S+` (e.g. `token=secretvalue`).
- AC-NFR03-04: Lines not matching the regex are preserved verbatim.
- AC-NFR03-05: No silent rebuild of a corrupted `tasks.json` (cross-ref FR-01 AC-FR01-09).

---

## 5. Acceptance Criteria Summary

| ID | Summary | Maps to |
|----|---------|---------|
| AC-FR01-01 | Empty command rejected | FR-01 |
| AC-FR01-02 | Whitespace-only command rejected | FR-01 |
| AC-FR01-03 | 1000-char command accepted (boundary) | FR-01 |
| AC-FR01-04 | 1001-char command rejected | FR-01 |
| AC-FR01-05 | 7-char blacklist coverage (7 sub-cases) | FR-01 |
| AC-FR01-06 | Task id = 8 lowercase hex | FR-01 |
| AC-FR01-07 | Pending record fields present | FR-01 |
| AC-FR01-08 | Atomic write via tmp + os.replace | FR-01 |
| AC-FR01-09 | Corrupted store → exit 1, no silent rebuild | FR-01 |
| AC-FR02-01 | exit 0 → done | FR-02 |
| AC-FR02-02 | non-zero exit → failed | FR-02 |
| AC-FR02-03 | timeout → timeout, exit 4 | FR-02 |
| AC-FR02-04 | Tail truncation at 2000 chars | FR-02 |
| AC-FR02-05 | duration_ms non-negative int | FR-02 |
| AC-FR02-06 | finished_at recorded | FR-02 |
| AC-FR02-07 | failed → auto retry ≤ TASKQ_RETRY_LIMIT | FR-02 |
| AC-FR02-08 | timeout → auto retry ≤ TASKQ_RETRY_LIMIT | FR-02 |
| AC-FR02-09 | Unexpected exception → exit 1, no bare except | FR-02 |
| AC-FR02-10 | shell=True never invoked | FR-02/NFR-02 |
| AC-FR03-01 | submit round-trip | FR-03 |
| AC-FR03-02 | status on valid id | FR-03 |
| AC-FR03-03 | status on unknown id → exit 2 | FR-03 |
| AC-FR03-04 | list output format | FR-03 |
| AC-FR03-05 | list on empty store | FR-03 |
| AC-FR03-06 | clear empties store | FR-03 |
| AC-FR03-07 | --json single-line JSON | FR-03 |
| AC-FR03-08 | Exit code table adherence | FR-03 |
| AC-NFR01-01 | p95 < 50ms over 100 iter | NFR-01 |
| AC-NFR01-02 | Reproducible benchmark | NFR-01 |
| AC-NFR02-01 | No shell=True in codebase | NFR-02 |
| AC-NFR02-02 | 7 blacklist test cases | NFR-02 |
| AC-NFR02-03 | No shell exec for user input | NFR-02 |
| AC-NFR03-01 | JSON valid post-interrupt | NFR-03 |
| AC-NFR03-02 | sk-… redaction | NFR-03 |
| AC-NFR03-03 | token=… redaction | NFR-03 |
| AC-NFR03-04 | Non-matching lines preserved | NFR-03 |
| AC-NFR03-05 | No silent rebuild | NFR-03 |

**Total**: 36 testable acceptance criteria (AC-FR01: 9; AC-FR02: 10; AC-FR03: 8; AC-NFR01: 2; AC-NFR02: 3; AC-NFR03: 5).

---

## 6. Out-of-Scope

The following are explicitly **out of scope** for `taskq` v2.0.0:
- Multi-host / distributed task execution (single-host local CLI only).
- Persistent background daemon / scheduler (`taskq run` is invoked on-demand).
- Authentication / multi-user support (single local user, file-based store).
- Web UI or HTTP API (CLI only).
- Task dependencies / DAG execution (no inter-task ordering).
- Concurrent execution of multiple tasks within a single `run` invocation (sequential per invocation).
- Log streaming / live progress (only post-run fields persisted).
- Cancellation of an in-flight task from outside the CLI process.
- Windows-specific shell semantics (POSIX `shlex` only; Windows is not targeted).
- External dependency installation at runtime (zero-dep mandate).

---

## 7. Open Issues

No TBD / TODO / `<placeholder>` markers were detected in `SPEC.md` v2.0.0. Therefore **no `NFR-99` or `FR-XX-deferred` items are emitted** in this round.

- **NFR-99 slots**: 0 used, 0 reserved.
- **FR-XX-deferred slots**: 0 used, 0 reserved.

If future SPEC.md revisions introduce deferred markers, they will be captured here with verbatim citation.

---

## 8. Risks

The following risks are explicitly enumerated in `SPEC.md` §4 and recorded here:

| ID | Risk | Mitigation |
|----|------|------------|
| R1 | Concurrent or interrupted write corrupts `tasks.json` | NFR-03 atomic write (`tmp + os.replace`) |
| R2 | Subprocess hangs indefinitely | FR-02 `timeout=TASKQ_TASK_TIMEOUT` |
| R3 | Secret leakage via persisted stdout/stderr tails | NFR-03 line-level redaction before persistence |

Additional risks noted from this SRS review (not in SPEC.md):
- **R4**: Boundary semantics of `> 1000` (FR-01) — interpreted as strictly greater; spec ambiguity on inclusive vs exclusive. **Resolution**: AC-FR01-03 / AC-FR01-04 adopt "≤ 1000 accepted, > 1000 rejected" (1000 inclusive). If SPEC.md disagrees, AC must be revised.
- **R5**: Retry counter visibility — SPEC.md does not state whether intermediate retry attempts are persisted separately or overwritten. **Resolution (assumed)**: AC-FR02-07/08 assume the final attempt's result is persisted; intermediate attempts may be logged but not required as separate records.

---

## 9. Glossary

| Term | Definition |
|------|------------|
| `taskq` | The CLI tool name; also the Python package name. |
| `task id` | First 8 hex characters of a uuid4. |
| `tasks.json` | JSON file at `$TASKQ_HOME/tasks.json` containing the persistent task store. |
| `TASKQ_HOME` | Env var; directory containing `tasks.json`. Default `.taskq`. |
| `TASKQ_TASK_TIMEOUT` | Env var; subprocess timeout in seconds. Default `10.0`. |
| `TASKQ_RETRY_LIMIT` | Env var; max retries after `failed`/`timeout`. Default `2`. |
| atomic write | Write to a sibling tmp file, then `os.replace` onto the target path; guarantees target is either old contents or new contents, never partial. |
| `stdout_tail` / `stderr_tail` | Last 2000 chars of the respective subprocess streams, captured at run time and redacted before persistence. |
| `done` / `failed` / `timeout` | Terminal task statuses reached from `running`. |
| `pending` / `running` | Pre-terminal task statuses. |
| INGESTION MODE | SRS authoring mode where every FR/NFR is transcribed verbatim from the canonical spec; no invention, no silent omission. |
| Elicitation Mode | Alternative SRS authoring mode where requirements are elicited from a brief without a canonical spec. |
| prompt-injection pattern | Adversarial text in the canonical spec attempting to alter SRS authoring behavior; flagged with high-severity citation and Elicitation fallback. None detected in SPEC.md v2.0.0. |

---

## 10. Configuration Reference (informational, from SPEC.md §5)

| Variable | Default | Description |
|----------|---------|-------------|
| `TASKQ_HOME` | `.taskq` | Data file directory |
| `TASKQ_TASK_TIMEOUT` | `10.0` | Per-task subprocess timeout (seconds) |
| `TASKQ_RETRY_LIMIT` | `2` | Max automatic retries on failure |

---

## 11. Document Provenance

- **Authoring mode**: INGESTION MODE (canonical_spec = SPEC.md, single file)
- **Canonical spec version**: v2.0.0 (2026-06-15)
- **FR count transcribed**: 3 (FR-01, FR-02, FR-03)
- **NFR count transcribed**: 3 (NFR-01, NFR-02, NFR-03)
- **Env vars transcribed**: 3 (TASKQ_HOME, TASKQ_TASK_TIMEOUT, TASKQ_RETRY_LIMIT)
- **Deferred items**: 0
- **Prompt-injection patterns detected**: 0
- **Citations**: see SPEC.md §1–§5 (every FR and NFR section heading is a 1:1 mapping).

*End of SRS — taskq v2.0.0*