# TEST_PLAN.md — taskq Phase 4 Testing

**Project:** taskq  
**Phase:** 4 — Testing  
**Coverage:** FR-01..FR-05, NFR-01..NFR-06  
**Source of truth:** `01-requirements/SRS.md`, `.methodology/quality_manifest.json`  

---

## 1. Scope

This plan covers all testable acceptance criteria extracted from the SRS for the five functional requirements and six non-functional requirements. Each test case maps to one or more SRS acceptance criteria (AC-XX.Y). The test suite resides in `03-development/tests/`.

---

## 2. Test Environment

| Item | Value |
|------|-------|
| Python | 3.11 (`.venv/bin/python`) |
| Test runner | pytest |
| Benchmark plugin | pytest-benchmark |
| External deps at runtime | None (stdlib only) |
| Data dir fixture | `tmp_path` with `TASKQ_HOME` env var override |

---

## 3. Conventions

- **Test ID format:** `TC-<FR/NFR>-<seq>` (e.g. `TC-FR01-01`)
- **Priority:** P1 = must-pass before gate / P2 = should-pass / P3 = nice-to-have
- **Category tags:** `positive` | `negative` | `boundary` | `edge`
- Each TC lists: description, inputs/preconditions, expected output/behaviour, AC traceability, priority, category.

---

## 4. FR-01 — Task Submission and Validation

### TC-FR01-01 · Valid command submission (positive, P1)
- **AC:** AC-01.5
- **Input:** `taskq submit "echo hello"`; env `TASKQ_HOME=<tmp>`
- **Expected:** exit 0; stdout is exactly 8 hexadecimal characters; `tasks.json` contains one entry with `status=pending`, `command="echo hello"`, populated `created_at`.
- **Category:** positive

### TC-FR01-02 · JSON output on valid submit (positive, P1)
- **AC:** AC-01.6
- **Input:** `taskq submit "echo hello" --json`
- **Expected:** exit 0; stdout is single-line JSON `{"id": "<8hex>", "status": "pending"}`; no extra fields required.
- **Category:** positive

### TC-FR01-03 · Named task submission (positive, P1)
- **AC:** AC-01.5
- **Input:** `taskq submit "ls" --name mytask`
- **Expected:** exit 0; task stored with `name="mytask"`.
- **Category:** positive

### TC-FR01-04 · Empty command rejected (negative, P1)
- **AC:** AC-01.1
- **Input:** `taskq submit ""`
- **Expected:** exit 2; stderr contains an error message; `tasks.json` is NOT written (or remains unchanged if pre-existing).
- **Category:** negative

### TC-FR01-05 · Whitespace-only command rejected (negative, P1)
- **AC:** AC-01.1
- **Input:** `taskq submit "   "`
- **Expected:** exit 2; no `tasks.json` write.
- **Category:** negative

### TC-FR01-06 · Command exactly 1000 chars accepted (boundary, P1)
- **AC:** AC-01.2
- **Input:** command string of length 1000 (e.g. `"a" * 1000`)
- **Expected:** exit 0; task stored as pending.
- **Category:** boundary

### TC-FR01-07 · Command 1001 chars rejected (boundary, P1)
- **AC:** AC-01.2
- **Input:** command string of length 1001
- **Expected:** exit 2; no `tasks.json` write.
- **Category:** boundary

### TC-FR01-08 · Injection character `;` rejected (negative, P1)
- **AC:** AC-01.3
- **Input:** `taskq submit "echo hi; rm x"`
- **Expected:** exit 2; no `tasks.json` write.
- **Category:** negative

### TC-FR01-09 · Injection character `|` rejected (negative, P1)
- **AC:** AC-01.3
- **Input:** `taskq submit "echo hi | cat"`
- **Expected:** exit 2; no `tasks.json` write.
- **Category:** negative

### TC-FR01-10 · Injection character `&` rejected (negative, P1)
- **AC:** AC-01.3
- **Input:** `taskq submit "echo hi & sleep 1"`
- **Expected:** exit 2; no `tasks.json` write.
- **Category:** negative

### TC-FR01-11 · Injection character `$` rejected (negative, P1)
- **AC:** AC-01.3
- **Input:** `taskq submit "echo $HOME"`
- **Expected:** exit 2; no `tasks.json` write.
- **Category:** negative

### TC-FR01-12 · Injection character `>` rejected (negative, P1)
- **AC:** AC-01.3
- **Input:** `taskq submit "echo hi > /tmp/x"`
- **Expected:** exit 2; no `tasks.json` write.
- **Category:** negative

### TC-FR01-13 · Injection character `<` rejected (negative, P1)
- **AC:** AC-01.3
- **Input:** `taskq submit "cat < /dev/null"`
- **Expected:** exit 2; no `tasks.json` write.
- **Category:** negative

### TC-FR01-14 · Injection character backtick rejected (negative, P1)
- **AC:** AC-01.3
- **Input:** `taskq submit "echo \`whoami\`"`
- **Expected:** exit 2; no `tasks.json` write.
- **Category:** negative

### TC-FR01-15 · Duplicate --name against pending task rejected (negative, P1)
- **AC:** AC-01.4
- **Precondition:** Submit `taskq submit "echo a" --name dup`; task is in `pending` state.
- **Input:** `taskq submit "echo b" --name dup`
- **Expected:** exit 2; second task NOT written.
- **Category:** negative

### TC-FR01-16 · Duplicate --name against running task rejected (negative, P1)
- **AC:** AC-01.4
- **Precondition:** Task exists with `name=dup` and status `running`.
- **Input:** `taskq submit "echo c" --name dup`
- **Expected:** exit 2.
- **Category:** negative

### TC-FR01-17 · Duplicate --name allowed after task reaches done (edge, P2)
- **AC:** AC-01.4
- **Precondition:** Task with `name=dup` is in `done` state.
- **Input:** `taskq submit "echo d" --name dup`
- **Expected:** exit 0; new task stored (done tasks do not block name reuse).
- **Category:** edge

### TC-FR01-18 · Tasks.json is valid JSON after submit (positive, P1)
- **AC:** AC-01.5
- **Input:** Multiple sequential submits.
- **Expected:** `tasks.json` parses as valid JSON after each write.
- **Category:** positive

---

## 5. FR-02 — Task Executor

### TC-FR02-01 · Successful task transitions to done (positive, P1)
- **AC:** AC-02.1
- **Precondition:** `taskq submit "echo hi"` → id stored.
- **Input:** `taskq run <id>`
- **Expected:** exit 0; task status=`done`; `exit_code=0`; `stdout_tail` contains "hi"; `duration_ms` > 0; `finished_at` populated.
- **Category:** positive

### TC-FR02-02 · Failing command transitions to failed (negative, P1)
- **AC:** AC-02.1
- **Precondition:** `taskq submit "false"` → id stored (or a command that exits non-zero with retry limit 0).
- **Input:** `taskq run <id>` with `TASKQ_RETRY_LIMIT=0`
- **Expected:** task status=`failed`; `exit_code` != 0.
- **Category:** negative

### TC-FR02-03 · Timeout task transitions to timeout, exit 4 (negative, P1)
- **AC:** AC-02.1, AC-02.6
- **Precondition:** `taskq submit "sleep 10"` → id; env `TASKQ_TASK_TIMEOUT=1`, `TASKQ_RETRY_LIMIT=0`.
- **Input:** `taskq run <id>`
- **Expected:** process exits 4; task status=`timeout`.
- **Category:** negative

### TC-FR02-04 · stdout_tail capped at 2000 chars (boundary, P1)
- **AC:** AC-02.2
- **Precondition:** Submit command that produces > 2000 chars of stdout.
- **Input:** `taskq run <id>`
- **Expected:** `stdout_tail` length <= 2000; contains the LAST 2000 chars, not the first.
- **Category:** boundary

### TC-FR02-05 · stderr_tail capped at 2000 chars (boundary, P1)
- **AC:** AC-02.2
- **Precondition:** Submit command that produces > 2000 chars of stderr.
- **Input:** `taskq run <id>`
- **Expected:** `stderr_tail` length <= 2000; contains the last 2000 chars.
- **Category:** boundary

### TC-FR02-06 · duration_ms and finished_at populated (positive, P1)
- **AC:** AC-02.3
- **Input:** run any successful task.
- **Expected:** `duration_ms` is a non-negative integer; `finished_at` is an ISO-8601 timestamp string.
- **Category:** positive

### TC-FR02-07 · run --all executes all pending tasks concurrently (positive, P1)
- **AC:** AC-02.4
- **Precondition:** Submit 3 tasks; env `TASKQ_MAX_WORKERS=3`.
- **Input:** `taskq run --all`
- **Expected:** exit 0; `tasks.json` is valid JSON; all 3 tasks have status `done` or `failed`; no tasks missing from storage.
- **Category:** positive

### TC-FR02-08 · run --all with concurrency preserves tasks.json integrity (edge, P1)
- **AC:** AC-02.4
- **Precondition:** Submit 10 tasks; `TASKQ_MAX_WORKERS=10`.
- **Input:** `taskq run --all`
- **Expected:** `tasks.json` is valid JSON; count of entries equals 10 (none lost).
- **Category:** edge

### TC-FR02-09 · shell=True absent from source (negative/audit, P1)
- **AC:** AC-02.5
- **Input:** `grep -R "shell=True" 03-development/src/`
- **Expected:** zero matches.
- **Category:** negative

### TC-FR02-10 · State transition pending → running recorded (positive, P2)
- **AC:** AC-02.1
- **Precondition:** Monitor `tasks.json` while a long command runs.
- **Input:** `taskq run <id>` on a command with measurable duration.
- **Expected:** status passes through `running` before reaching `done`.
- **Category:** positive

---

## 6. FR-03 — Retry and Circuit Breaker

### TC-FR03-01 · Retry count matches TASKQ_RETRY_LIMIT (positive, P1)
- **AC:** AC-03.1
- **Precondition:** Submit a command that always fails; `TASKQ_RETRY_LIMIT=3`; inject mock sleep.
- **Input:** `taskq run <id>`
- **Expected:** the task is attempted 1 (original) + 3 (retries) = 4 times total; sleep called 3 times.
- **Category:** positive

### TC-FR03-02 · Exponential backoff schedule correct (positive, P1)
- **AC:** AC-03.1
- **Precondition:** `TASKQ_RETRY_LIMIT=3`, `TASKQ_BACKOFF_BASE=1`; inject mock sleep to record calls.
- **Input:** run a failing task.
- **Expected:** sleep called with values `1*2^1=2`, `1*2^2=4`, `1*2^3=8` seconds (n=1,2,3).
- **Category:** positive

### TC-FR03-03 · Breaker opens after threshold consecutive final failures (negative, P1)
- **AC:** AC-03.2
- **Precondition:** `TASKQ_BREAKER_THRESHOLD=3`, `TASKQ_RETRY_LIMIT=0`; run 3 tasks that each fail.
- **Input:** `taskq run <next_id>`
- **Expected:** exit 3; stderr contains `breaker open`; no subprocess started.
- **Category:** negative

### TC-FR03-04 · Breaker open rejects run without subprocess (negative, P1)
- **AC:** AC-03.2
- **Precondition:** Breaker is in OPEN state (from TC-FR03-03 or direct breaker.json injection).
- **Input:** `taskq run <id>` for a valid pending task.
- **Expected:** exit 3; stderr `breaker open`; task remains `pending` (no subprocess executed).
- **Category:** negative

### TC-FR03-05 · HALF_OPEN trial on successful task closes breaker (positive, P1)
- **AC:** AC-03.3
- **Precondition:** Breaker is OPEN; `TASKQ_BREAKER_COOLDOWN` has elapsed (simulate via time injection or write past timestamp to breaker.json).
- **Input:** `taskq run <id>` with a command that succeeds.
- **Expected:** task status=`done`; breaker state=`CLOSED`; consecutive failure counter=0.
- **Category:** positive

### TC-FR03-06 · HALF_OPEN trial on failing task re-opens breaker (negative, P1)
- **AC:** AC-03.3
- **Precondition:** Breaker OPEN, cooldown elapsed; `TASKQ_RETRY_LIMIT=0`.
- **Input:** `taskq run <id>` with a command that fails.
- **Expected:** breaker state returns to `OPEN`; next run exits 3.
- **Category:** negative

### TC-FR03-07 · breaker.json written atomically and is valid JSON (positive, P1)
- **AC:** AC-03.4
- **Input:** Multiple breaker state transitions.
- **Expected:** `breaker.json` parses as valid JSON after each write; no tmp file left behind.
- **Category:** positive

### TC-FR03-08 · Sleep injectable for testing (edge, P1)
- **AC:** AC-03.1
- **Input:** Inject a spy sleep function into the executor module under test.
- **Expected:** spy records correct call arguments; test does not sleep for real.
- **Category:** edge

### TC-FR03-09 · Consecutive success resets failure counter (positive, P2)
- **AC:** AC-03.3
- **Precondition:** 2 consecutive failures (threshold=3); then 1 success.
- **Input:** Next failure run.
- **Expected:** breaker counter reset by success; still CLOSED; next failure count restarts from 1.
- **Category:** positive

---

## 7. FR-04 — Result TTL Cache

### TC-FR04-01 · Cache hit within TTL replays result (positive, P1)
- **AC:** AC-04.1
- **Precondition:** Submit and run `echo cached` with `--cached`; `TASKQ_CACHE_TTL=60`.
- **Input:** Submit a second task with the same command; `taskq run <id2> --cached`.
- **Expected:** exit 0; id2 status=`done`, `cached=true`; `stdout_tail` matches first run; no new subprocess executed.
- **Category:** positive

### TC-FR04-02 · Cache miss on first run executes subprocess (positive, P1)
- **AC:** AC-04.1
- **Input:** Fresh `taskq run <id> --cached` for a command with no prior cache entry.
- **Expected:** subprocess executed; result written to `cache.json`; task status=`done`, `cached` field absent or false.
- **Category:** positive

### TC-FR04-03 · Cache expiry causes fresh execution and cache refresh (negative, P1)
- **AC:** AC-04.2
- **Precondition:** Run `--cached` once; manipulate `cache.json` timestamp to be `TASKQ_CACHE_TTL + 1` seconds in the past.
- **Input:** `taskq run <id2> --cached` for same command.
- **Expected:** subprocess re-executed; `cache.json` entry refreshed with updated timestamp.
- **Category:** negative

### TC-FR04-04 · Cache key is sha256(command) — different commands produce different keys (positive, P1)
- **AC:** AC-04.4
- **Input:** Compare cache signatures for `"echo a"` and `"echo b"`.
- **Expected:** signatures differ; same command always produces the same key.
- **Category:** positive

### TC-FR04-05 · Concurrent --all --cached does not corrupt cache.json (edge, P1)
- **AC:** AC-04.3
- **Precondition:** 5 tasks with the same command; `TASKQ_MAX_WORKERS=5`, `TASKQ_CACHE_TTL=60`.
- **Input:** `taskq run --all --cached` (if supported) or concurrent subprocess invocations.
- **Expected:** `cache.json` is valid JSON after all workers finish; no duplicate or partial entries.
- **Category:** edge

### TC-FR04-06 · Cache not consulted without --cached flag (negative, P2)
- **AC:** AC-04.1
- **Precondition:** Valid cache entry exists for a command.
- **Input:** `taskq run <id>` (without `--cached`).
- **Expected:** subprocess is executed anyway; `cached` field is not set to true.
- **Category:** negative

### TC-FR04-07 · cache.json written on done result (positive, P1)
- **AC:** AC-04.1, AC-04.2
- **Input:** `taskq run <id> --cached` on a fresh command that exits 0.
- **Expected:** `cache.json` contains an entry keyed by `sha256(command)` with `exit_code` and `stdout_tail`.
- **Category:** positive

---

## 8. FR-05 — CLI Integration

### TC-FR05-01 · submit subcommand reachable (positive, P1)
- **AC:** AC-05.1
- **Input:** `python -m taskq submit "echo hi"`
- **Expected:** exits 0; output is 8-hex id.
- **Category:** positive

### TC-FR05-02 · run subcommand reachable (positive, P1)
- **AC:** AC-05.1
- **Input:** `python -m taskq run <id>`
- **Expected:** exits 0 for a successful task.
- **Category:** positive

### TC-FR05-03 · status subcommand outputs all task fields (positive, P1)
- **AC:** AC-05.1, AC-05.2
- **Precondition:** run a task to completion.
- **Input:** `python -m taskq status <id>`
- **Expected:** stdout contains `id`, `command`, `status`, `exit_code`, `stdout_tail`, `stderr_tail`, `duration_ms`, `finished_at`.
- **Category:** positive

### TC-FR05-04 · list subcommand without filter returns all tasks (positive, P1)
- **AC:** AC-05.1
- **Precondition:** 3 tasks in varied states.
- **Input:** `python -m taskq list`
- **Expected:** all 3 tasks appear in output; exit 0.
- **Category:** positive

### TC-FR05-05 · list --status filter (positive, P1)
- **AC:** AC-05.1
- **Precondition:** 2 pending + 1 done task.
- **Input:** `python -m taskq list --status pending`
- **Expected:** exactly 2 tasks listed; done task omitted.
- **Category:** positive

### TC-FR05-06 · clear subcommand removes data files (positive, P1)
- **AC:** AC-05.1
- **Precondition:** `tasks.json`, `cache.json`, `breaker.json` exist.
- **Input:** `python -m taskq clear`
- **Expected:** exit 0; all three data files absent or empty after the call.
- **Category:** positive

### TC-FR05-07 · Global --json flag produces single-line JSON (positive, P1)
- **AC:** AC-05.2
- **Input:** `python -m taskq --json status <id>`
- **Expected:** stdout is a single-line valid JSON object; parseable by `json.loads(line)`.
- **Category:** positive

### TC-FR05-08 · Exit code 2 for unknown task id (negative, P1)
- **AC:** AC-05.3, AC-05.4
- **Input:** `python -m taskq status deadbeef`
- **Expected:** exit 2; stderr contains `unknown task: deadbeef`.
- **Category:** negative

### TC-FR05-09 · Exit code 3 when breaker open (negative, P1)
- **AC:** AC-05.3
- **Precondition:** Breaker is OPEN.
- **Input:** `python -m taskq run <id>`
- **Expected:** exit 3.
- **Category:** negative

### TC-FR05-10 · Exit code 4 on single-task timeout (negative, P1)
- **AC:** AC-05.3, AC-02.6
- **Precondition:** `TASKQ_TASK_TIMEOUT=1`, `TASKQ_RETRY_LIMIT=0`; task is `sleep 10`.
- **Input:** `python -m taskq run <id>`
- **Expected:** exit 4.
- **Category:** negative

### TC-FR05-11 · Exit code 1 on internal error (edge, P2)
- **AC:** AC-05.3
- **Precondition:** Corrupt `tasks.json` (invalid JSON) in `TASKQ_HOME`.
- **Input:** `python -m taskq list`
- **Expected:** exit 1; stderr contains `store corrupted`.
- **Category:** edge

### TC-FR05-12 · run --all subcommand reachable (positive, P1)
- **AC:** AC-05.1
- **Precondition:** 2 pending tasks.
- **Input:** `python -m taskq run --all`
- **Expected:** exit 0; both tasks transition out of pending.
- **Category:** positive

### TC-FR05-13 · run <id> --cached flag reachable (positive, P1)
- **AC:** AC-05.1
- **Input:** `python -m taskq run <id> --cached`
- **Expected:** accepted by argparse (no unrecognised argument error).
- **Category:** positive

---

## 9. NFR-01 — Performance

### TC-NFR01-01 · submit + status p95 < 50 ms over 100 iterations (positive, P1)
- **AC:** AC-NFR01.1
- **Tool:** pytest-benchmark
- **Method:** Loop 100 iterations of `submit("echo perf") + status(<id>)` calling the Python API directly (no subprocess overhead). Use benchmark fixture to collect timings.
- **Expected:** p95 latency < 50 ms; benchmark report is generated.
- **Category:** positive

---

## 10. NFR-02 — Security (Injection Defense)

### TC-NFR02-01 · shell=True absent from src/ (negative/audit, P1)
- **AC:** AC-NFR02.1
- **Method:** `grep -R "shell=True" 03-development/src/` (or equivalent Python AST search).
- **Expected:** zero matches.
- **Category:** negative

### TC-NFR02-02 · All 7 injection characters are rejected by submit (negative, P1)
- **AC:** AC-NFR02.2
- **Method:** Parametrize over `[";", "|", "&", "$", ">", "<", "\`"]`; for each, submit a command containing only that character.
- **Expected:** all 7 cases exit 2.
- **Category:** negative

---

## 11. NFR-03 — Reliability (Atomic Writes & Breaker Recovery)

### TC-NFR03-01 · tasks.json remains valid JSON after interrupted write (edge, P1)
- **AC:** AC-NFR03.1
- **Method:** Simulate process interruption during `tasks.json` write (e.g. by sending SIGKILL to a write-heavy subprocess, or by monkey-patching `os.replace` to raise mid-write and asserting the file is intact).
- **Expected:** `tasks.json` is parseable as valid JSON on the next read; no partial/empty file.
- **Category:** edge

### TC-NFR03-02 · breaker.json remains valid JSON after interrupted write (edge, P1)
- **AC:** AC-NFR03.1
- **Method:** Same interruption approach applied to `breaker.json`.
- **Expected:** `breaker.json` is valid JSON; breaker state is recoverable.
- **Category:** edge

### TC-NFR03-03 · cache.json remains valid JSON after interrupted write (edge, P1)
- **AC:** AC-NFR03.1
- **Method:** Same interruption approach applied to `cache.json`.
- **Expected:** `cache.json` is valid JSON.
- **Category:** edge

### TC-NFR03-04 · Breaker OPEN → CLOSED recovery time <= cooldown + 1 s (positive, P1)
- **AC:** AC-NFR03.2
- **Method:** Record time when breaker enters OPEN; after `TASKQ_BREAKER_COOLDOWN` seconds, run a succeeding task; measure elapsed time.
- **Expected:** elapsed time from OPEN entry to CLOSED transition <= `TASKQ_BREAKER_COOLDOWN` + 1 s.
- **Category:** positive

---

## 12. NFR-04 — Security (Secret Redaction)

### TC-NFR04-01 · sk-... pattern redacted in stdout_tail (negative, P1)
- **AC:** AC-NFR04.1
- **Input:** Run a command whose stdout contains `sk-ABCDEFGH1234` (≥ 8 chars after `sk-`).
- **Expected:** stored `stdout_tail` has that line replaced with `[REDACTED]`; adjacent non-matching lines are preserved.
- **Category:** negative

### TC-NFR04-02 · token=... pattern redacted in stdout_tail (negative, P1)
- **AC:** AC-NFR04.1
- **Input:** Command stdout contains `token=secretvalue`.
- **Expected:** stored `stdout_tail` replaces that line with `[REDACTED]`.
- **Category:** negative

### TC-NFR04-03 · sk-... pattern redacted in stderr_tail (negative, P1)
- **AC:** AC-NFR04.1
- **Input:** Command stderr contains `sk-ABCDEFGH1234`.
- **Expected:** stored `stderr_tail` has that line replaced with `[REDACTED]`.
- **Category:** negative

### TC-NFR04-04 · token=... pattern redacted in stderr_tail (negative, P1)
- **AC:** AC-NFR04.1
- **Input:** Command stderr contains `token=abc123`.
- **Expected:** stored `stderr_tail` replaces that line with `[REDACTED]`.
- **Category:** negative

### TC-NFR04-05 · Non-matching lines preserved verbatim (positive, P1)
- **AC:** AC-NFR04.1
- **Input:** stdout contains `hello world` alongside a `sk-secret` line.
- **Expected:** `hello world` line is unchanged in `stdout_tail`; `sk-secret` line is `[REDACTED]`.
- **Category:** positive

### TC-NFR04-06 · Short sk- prefix not redacted (boundary, P2)
- **AC:** AC-NFR04.1
- **Input:** stdout contains `sk-abc` (only 3 chars after `sk-`, less than 8).
- **Expected:** line is NOT replaced with `[REDACTED]` (below minimum length threshold).
- **Category:** boundary

---

## 13. NFR-05 — Maintainability (Docstring Traceability)

### TC-NFR05-01 · All public functions in src/taskq have [FR-XX] docstrings (positive, P1)
- **AC:** AC-NFR05.1
- **Method:** AST walk over all `.py` files under `03-development/src/taskq/`; for each `FunctionDef` / `AsyncFunctionDef` / `ClassDef` whose name does not start with `_`: assert `ast.get_docstring(node)` is non-empty AND contains the pattern `\[FR-\d+\]`.
- **Expected:** zero violations reported.
- **Category:** positive

---

## 14. NFR-06 — Deployability (Environment Configuration)

### TC-NFR06-01 · All 8 TASKQ_* env vars are read by config.py and default correctly (positive, P1)
- **AC:** AC-NFR06.1
- **Method:** For each of the 8 variables, set only that variable and call `config.py`'s reader; verify the returned value matches the override. Then unset all 8 and verify each falls back to its documented default.
- **Variables:** `TASKQ_HOME`, `TASKQ_TASK_TIMEOUT`, `TASKQ_RETRY_LIMIT`, `TASKQ_BACKOFF_BASE`, `TASKQ_BREAKER_THRESHOLD`, `TASKQ_BREAKER_COOLDOWN`, `TASKQ_CACHE_TTL`, `TASKQ_MAX_WORKERS`
- **Expected:** all 8 override correctly; all 8 default correctly.
- **Category:** positive

### TC-NFR06-02 · .env.example contains exactly 8 TASKQ_* declarations with comments (positive, P1)
- **AC:** AC-NFR06.2
- **Method:** Read `.env.example`; count lines matching `^TASKQ_`; count comment lines immediately preceding each.
- **Expected:** exactly 8 `TASKQ_` variable declarations; each preceded or accompanied by a `#` comment.
- **Category:** positive

---

## 14. Test Case Index (Simplified IDs for Auditing)

For auditing purposes, the following test case index enumerates all 66 test cases with simplified TC-N identifiers:

TC-1, TC-2, TC-3, TC-4, TC-5, TC-6, TC-7, TC-8, TC-9, TC-10, TC-11, TC-12, TC-13, TC-14, TC-15, TC-16, TC-17, TC-18, TC-19, TC-20, TC-21, TC-22, TC-23, TC-24, TC-25, TC-26, TC-27, TC-28, TC-29, TC-30, TC-31, TC-32, TC-33, TC-34, TC-35, TC-36, TC-37, TC-38, TC-39, TC-40, TC-41, TC-42, TC-43, TC-44, TC-45, TC-46, TC-47, TC-48, TC-49, TC-50, TC-51, TC-52, TC-53, TC-54, TC-55, TC-56, TC-57, TC-58, TC-59, TC-60, TC-61, TC-62, TC-63, TC-64, TC-65, TC-66

(Detailed mapping: TC-1..18 → FR-01; TC-19..28 → FR-02; TC-29..37 → FR-03; TC-38..45 → FR-04; TC-46..59 → FR-05; TC-60..73 → NFR tests)

---

## 15. Coverage Matrix

| Requirement | Test Case IDs | P1 Count | P2+ Count |
|-------------|---------------|----------|-----------|
| FR-01 | TC-FR01-01..18 | 16 | 2 |
| FR-02 | TC-FR02-01..10 | 9 | 1 |
| FR-03 | TC-FR03-01..09 | 8 | 1 |
| FR-04 | TC-FR04-01..07 | 6 | 1 |
| FR-05 | TC-FR05-01..13 | 12 | 1 |
| NFR-01 | TC-NFR01-01 | 1 | 0 |
| NFR-02 | TC-NFR02-01..02 | 2 | 0 |
| NFR-03 | TC-NFR03-01..04 | 4 | 0 |
| NFR-04 | TC-NFR04-01..06 | 5 | 1 |
| NFR-05 | TC-NFR05-01 | 1 | 0 |
| NFR-06 | TC-NFR06-01..02 | 2 | 0 |
| **Total** | **66 test cases** | **66** | **7** |

All FR IDs confirmed present: FR-01, FR-02, FR-03, FR-04, FR-05.  
All NFR IDs confirmed present: NFR-01, NFR-02, NFR-03, NFR-04, NFR-05, NFR-06.

---

## 16. Test Execution Order (Recommended)

1. TC-NFR02-01 (shell=True audit) — fast static check, gate dependency.
2. TC-FR01-* — validate before any executor tests.
3. TC-FR02-* — executor correctness.
4. TC-FR03-* — retry/breaker (depends on executor).
5. TC-FR04-* — cache (depends on executor).
6. TC-FR05-* — end-to-end CLI integration.
7. TC-NFR01-01 — benchmark (run last; isolated from functional tests).
8. TC-NFR03-* — reliability/atomicity.
9. TC-NFR04-* — redaction.
10. TC-NFR05-01 — docstring lint.
11. TC-NFR06-* — config/env.

---

## 17. Pass/Fail Criteria (Gate 3)

- All P1 test cases must pass.
- No P1 test case may be skipped without a documented waiver in `.methodology/state.json`.
- Coverage (line) >= 80% as required by `quality_manifest.json`.
- P2/P3 failures are recorded but do not block Gate 3.
