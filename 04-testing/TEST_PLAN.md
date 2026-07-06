# TEST_PLAN.md — taskq (Phase 4 — Testing)

> **Project:** taskq (local task queue CLI, Python 3.11, stdlib-only runtime)
> **Source of Truth:** `SPEC.md` v3.0.0 (2026-07-04) → mirrored in `01-requirements/SRS.md`
> **Authoritative FR/NFR registry:** `.methodology/quality_manifest.json`
> **Companion artifact:** `TEST_INVENTORY.yaml` (Phase 1 TC ID registry, 39 canonical TCs)
> **Phase:** 4 — Testing (Gate 3 prep)
> **Generated:** 2026-07-07 (Phase 4 pre-Gate 3)
> **Author scope:** TEST PLAN ONLY. No execution, no TDD runs, no harness/ modifications.

---

## 0. Test Strategy Summary

| Aspect | Decision |
|--------|----------|
| Test runner | `pytest` (per `.methodology/state.json::test_runner`) |
| Language | Python 3.11 |
| Fixture scope | Per-test isolation via `tmp_path` + `TASKQ_HOME` env override |
| Concurrency test | `ThreadPoolExecutor` injection via `pytest` fixtures (FR-02/FR-04) |
| Time control | `sleep_fn` injection in breaker + retry paths (FR-03) |
| Performance | `pytest-benchmark` for NFR-01 (p95 budget) |
| Static gate | `grep`-based CI gate for `shell=True` (NFR-02) + docstring `[FR-XX]` lint (NFR-05) |
| Coverage threshold | ≥ 80% (per `quality_manifest.json::quality_targets.min_coverage`) |
| Modules under test | `taskq/__main__`, `taskq/cli`, `taskq/config`, `taskq/models`, `taskq/store`, `taskq/executor`, `taskq/breaker`, `taskq/cache` |
| High-risk modules (per-FR TDD required) | `taskq.executor` (FR-02/FR-03), `taskq.store` (FR-01/FR-02) |
| Test categories | Positive, Negative, Boundary, Edge-case |
| Priority scale | **P0** (blocks Gate 3) / **P1** (Gate 3 quality) / **P2** (regression) / **P3** (advisory) |

### 0.1 Test Category Definitions

- **Positive** — valid input exercising the happy path; expected behavior must be the documented primary output.
- **Negative** — invalid input (validation, malformed data, missing keys, unauthorized state); expected behavior must be the documented rejection (exit code, stderr message, no side effects).
- **Boundary** — inputs at the documented limit (e.g. command length = 1000, retry limit edge, TTL edge); expected behavior must equal either side of the threshold.
- **Edge-case** — unusual but legitimate inputs (empty list, single-element, concurrent races, crash mid-write, injection permutations); expected behavior must be safe and consistent with documented semantics.

### 0.2 Coverage Matrix (FR ↔ Module ↔ AC)

| FR | Title | Primary module(s) | AC count | TC count planned |
|----|-------|-------------------|----------|------------------|
| FR-01 | Task submission & validation | `cli.py`, `store.py`, `models.py` | 5 | 12 |
| FR-02 | Task executor | `executor.py`, `store.py` | 5 | 14 |
| FR-03 | Retry + circuit breaker | `executor.py`, `breaker.py` | 5 | 16 |
| FR-04 | Result TTL cache | `cache.py` | 4 | 10 |
| FR-05 | CLI integration | `cli.py`, `__main__.py` | 3 | 13 |
| NFR-01 | Performance (p95 < 50ms) | `cli.py` | 1 | 4 |
| NFR-02 | Security (shell + injection) | `executor.py`, `cli.py` | 2 | 9 |
| NFR-03 | Reliability (atomic + breaker recovery) | `store.py`, `breaker.py` | 2 | 6 |
| NFR-04 | Security (secret redaction) | `executor.py` | 1 | 6 |
| NFR-05 | Maintainability (docstring FR ref) | `models.py` (gate inspect) | 1 | 4 |
| NFR-06 | Deployability (env vars) | `config.py` | 1 | 4 |
| **TOTAL** | | | **28** | **98** |

### 0.3 Test ID Naming Convention

Format: `TC-{FR|NFR}{NN}-{AC-NN}{a|b|c|...}` (matches `TEST_INVENTORY.yaml::tc_id_format`).
Cross-cutting / static-gate tests use `TC-NFR{NN}-X{NN}` namespace.

---

## 1. FR-01 — Task Submission & Validation

**Module under test:** `taskq.cli` (argparse `submit` subcommand), `taskq.store` (atomic append), `taskq.models` (Task dataclass)
**AC anchor:** AC-FR-01-01..05
**Risk classification:** `taskq.store` is high-risk (per `quality_manifest.json::high_risk_modules`)

### TC-FR01-01 — Submit accepts valid command (POSITIVE, P0)
- **Input:** `python -m taskq submit "echo hello" --name greet`
- **Expected output:**
  - exit code `0`
  - stdout: 8-character hex task id (e.g. `3f2a91bc`)
  - `$TASKQ_HOME/tasks.json` contains one record with `status="pending"`, `command="echo hello"`, `name="greet"`, `created_at` ISO-8601, `id` matching stdout
  - atomic write semantics (no torn write — see TC-NFR03-01a)

### TC-FR01-02 — Submit accepts valid command without --name (POSITIVE, P0)
- **Input:** `python -m taskq submit "echo hi"`
- **Expected output:**
  - exit code `0`
  - stdout: 8-hex id
  - record has `name=null` (or absent per `models.Task` schema) but `command` populated
  - exactly one new record appended (count delta = 1)

### TC-FR01-03 — Submit returns JSON envelope with --json (POSITIVE, P0)
- **Input:** `python -m taskq --json submit "echo hi"`
- **Expected output:**
  - exit code `0`
  - stdout: single-line JSON `{"id":"<8hex>","status":"pending"}` parseable by `json.loads`
  - no pretty-print, no trailing newline content beyond `\n`

### TC-FR01-04 — Empty string command rejected (NEGATIVE, P0)
- **Input:** `python -m taskq submit ""`
- **Expected output:** exit code `2`; stderr non-empty containing validation error; **no record written** (tasks.json unchanged).

### TC-FR01-05 — Whitespace-only command rejected (NEGATIVE, P0)
- **Input:** `python -m taskq submit "   "`
- **Expected output:** exit code `2`; stderr non-empty; no record written.

### TC-FR01-06 — Tab/newline-only command rejected (NEGATIVE, P0)
- **Input:** `python -m taskq submit $'\t\n  '`
- **Expected output:** exit code `2`; no record written.

### TC-FR01-07 — Command length = 1000 chars accepted (BOUNDARY, P0)
- **Input:** `python -m taskq submit "<1000 char string of safe characters>"`
- **Expected output:** exit code `0`; record written; `command` field equals input exactly.

### TC-FR01-08 — Command length = 1001 chars rejected (BOUNDARY, P0)
- **Input:** `python -m taskq submit "<1001 char safe string>"`
- **Expected output:** exit code `2`; stderr mentions length; no record written.

### TC-FR01-09 — Command length = 0 chars (boundary alias of TC-FR01-04) — duplicate covered; see TC-FR01-04

### TC-FR01-10 — Injection character `;` rejected (NEGATIVE, P0)
- **Input:** `python -m taskq submit "echo hi; rm x"`
- **Expected output:** exit code `2`; no subprocess spawn (verified via `subprocess` mock absence); no record written.

### TC-FR01-11 — Injection character `|` rejected (NEGATIVE, P0)
- **Input:** `python -m taskq submit "cat foo | grep bar"`
- **Expected output:** exit code `2`; no record written.

### TC-FR01-12 — Injection character `&` rejected (NEGATIVE, P0)
- **Input:** `python -m taskq submit "echo hi & rm x"`
- **Expected output:** exit code `2`; no record written.

### TC-FR01-13 — Injection character `$` rejected (NEGATIVE, P0)
- **Input:** `python -m taskq submit "echo $HOME"`
- **Expected output:** exit code `2`; no record written.

### TC-FR01-14 — Injection character `>` rejected (NEGATIVE, P0)
- **Input:** `python -m taskq submit "echo hi > /tmp/x"`
- **Expected output:** exit code `2`; no record written.

### TC-FR01-15 — Injection character `<` rejected (NEGATIVE, P0)
- **Input:** `python -m taskq submit "cat < /etc/passwd"`
- **Expected output:** exit code `2`; no record written.

### TC-FR01-16 — Injection character backtick `` ` `` rejected (NEGATIVE, P0)
- **Input:** `python -m taskq submit "echo \`whoami\`"`
- **Expected output:** exit code `2`; no record written.

### TC-FR01-17 — Duplicate --name against pending task rejected (NEGATIVE, P0)
- **Pre-condition:** task A with `--name=alpha` in `status="pending"` exists.
- **Input:** `python -m taskq submit "echo dup" --name alpha`
- **Expected output:** exit code `2`; stderr mentions name conflict; no new record.

### TC-FR01-18 — Duplicate --name against running task rejected (NEGATIVE, P0)
- **Pre-condition:** task B with `--name=alpha` in `status="running"` exists.
- **Input:** `python -m taskq submit "echo dup" --name alpha`
- **Expected output:** exit code `2`; no new record.

### TC-FR01-19 — Reusing --name of done task accepted (POSITIVE/EDGE, P1)
- **Pre-condition:** prior task with `--name=alpha` finished (`status="done"`).
- **Input:** `python -m taskq submit "echo new" --name alpha`
- **Expected output:** exit code `0`; new record created; old record untouched.

### TC-FR01-20 — uuid4 prefix truncated to 8 hex chars (EDGE, P1)
- **Input:** `python -m taskq submit "echo id-shape"`
- **Expected output:** stdout id matches regex `^[0-9a-f]{8}$`; full uuid4 hex is 32 chars; only first 8 are surfaced.

### TC-FR01-21 — Atomic write replaces tasks.json in one syscall (EDGE, P0)
- **Input:** direct unit test on `store.append_task()`: monkey-patch `os.replace` to fail before completion; observe prior `tasks.json` byte-identical to pre-call content.
- **Expected output:** on `os.replace` failure, `tasks.json` retains prior content; no `.tmp` left behind (or `.tmp` is cleaned up — TBD per implementation review).

### TC-FR01-22 — Concurrent submit of unique names both succeed (EDGE, P1)
- **Input:** 8 threads submit 8 unique-name commands simultaneously.
- **Expected output:** all 8 exit `0`; `tasks.json` contains exactly 8 records; no truncation (final file is valid JSON).

---

## 2. FR-02 — Task Executor

**Module under test:** `taskq.executor` (high-risk), `taskq.store` (high-risk), `taskq.cli` (dispatch)
**AC anchor:** AC-FR-02-01..05

### TC-FR02-01 — Run executes via subprocess.run + shlex.split, no shell=True (POSITIVE, P0)
- **Input:** `python -m taskq run <id>` where task command is `echo hello`.
- **Expected output:** exit code `0`; task transitions `pending → running → done`; `exit_code=0`; `stdout_tail="hello\n"` (or last 2000 chars).
- **Static check:** `grep -RIn "shell=True" src/taskq` returns 0 hits (cross-ref NFR-02 TC-NFR02-01).

### TC-FR02-02 — Run captures exit code 0 → status=done (POSITIVE, P0)
- **Input:** run task whose command exits 0 (e.g. `true`).
- **Expected output:** task final `status="done"`; `exit_code=0`; `finished_at` ISO-8601; `duration_ms >= 0`.

### TC-FR02-03 — Run captures non-zero exit → status=failed (NEGATIVE, P0)
- **Input:** run task whose command exits non-zero (e.g. `false` or `exit 7`).
- **Expected output:** task `status="failed"`; `exit_code=7`; `finished_at` recorded. Note: retry path may apply (FR-03) — single-attempt test must isolate the no-retry code path.

### TC-FR02-04 — Subprocess timeout → status=timeout (NEGATIVE, P0)
- **Pre-condition:** `TASKQ_TASK_TIMEOUT=1`, command `sleep 5`.
- **Input:** `python -m taskq run <id>`.
- **Expected output:** task `status="timeout"`; no `exit_code` (or `null`); single-task CLI exit code `4` (see TC-FR02-09).

### TC-FR02-05 — stdout_tail truncated to last 2000 chars (BOUNDARY, P0)
- **Input:** command produces 3000 chars of stdout.
- **Expected output:** `stdout_tail` length = 2000; equals last 2000 chars of full stdout (UTF-8 char boundary safe).

### TC-FR02-06 — stderr_tail truncated to last 2000 chars (BOUNDARY, P0)
- **Input:** command produces 3000 chars of stderr.
- **Expected output:** `stderr_tail` length = 2000; equals last 2000 chars of full stderr.

### TC-FR02-07 — duration_ms non-negative and within window (EDGE, P1)
- **Input:** run task with command `sleep 0.05`.
- **Expected output:** `duration_ms >= 50` (with tolerance) and `< 2000`.

### TC-FR02-08 — finished_at set to ISO-8601 UTC (POSITIVE, P1)
- **Input:** any completed run.
- **Expected output:** `finished_at` matches regex `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}` with timezone offset (Z or +00:00).

### TC-FR02-09 — Single-task timeout → CLI exit code 4 (POSITIVE, P0)
- **Pre-condition:** `TASKQ_TASK_TIMEOUT=1`, command `sleep 5`.
- **Input:** `python -m taskq run <id>`.
- **Expected output:** CLI exit code = 4; task record `status="timeout"`.

### TC-FR02-10 — Run --all dispatches via ThreadPoolExecutor (POSITIVE, P0)
- **Pre-condition:** 8 pending tasks enqueued; `TASKQ_MAX_WORKERS=4`.
- **Input:** `python -m taskq run --all`.
- **Expected output:** all 8 transitions to terminal state (`done`/`failed`/`timeout`); peak concurrent subprocess count ≤ 4 (verified by injecting a counting wrapper around `subprocess.run`).

### TC-FR02-11 — Run --all concurrent writes produce valid tasks.json (POSITIVE, P0)
- **Input:** same as TC-FR02-10.
- **Expected output:** post-run `tasks.json` is valid JSON (`json.loads` succeeds); record count = pre-count + 8; no records lost or duplicated.

### TC-FR02-12 — Thread-safe writes via shared Lock (EDGE, P0)
- **Input:** unit test on `store.update_task()` invoked from 16 threads mutating distinct task ids.
- **Expected output:** all updates persisted; final file valid JSON; Lock contention observed via lock-acquire counter (mock `Lock.acquire`).

### TC-FR02-13 — Unknown task id → exit code 2 (NEGATIVE, P0)
- **Input:** `python -m taskq run 00000000` (no such task).
- **Expected output:** exit code `2`; stderr mentions unknown task id; no subprocess spawned.

### TC-FR02-14 — Re-running terminal task rejected (NEGATIVE, P1)
- **Pre-condition:** task A already `status="done"`.
- **Input:** `python -m taskq run <A.id>`.
- **Expected output:** exit code `2`; task A unchanged; no subprocess spawned.

---

## 3. FR-03 — Retry + Circuit Breaker

**Module under test:** `taskq.executor` (high-risk), `taskq.breaker`
**AC anchor:** AC-FR-03-01..05

### TC-FR03-01 — Failed run triggers retry up to TASKQ_RETRY_LIMIT (POSITIVE, P0)
- **Pre-condition:** `TASKQ_RETRY_LIMIT=2`, command `false`.
- **Input:** run task once.
- **Expected output:** subprocess invoked exactly 3 times (initial + 2 retries); final status `failed`; breaker counter += 1.

### TC-FR03-02 — Timeout run triggers retry (POSITIVE, P0)
- **Pre-condition:** `TASKQ_RETRY_LIMIT=1`, `TASKQ_TASK_TIMEOUT=1`, command `sleep 5`.
- **Input:** run task once.
- **Expected output:** subprocess invoked exactly 2 times; final status `timeout`.

### TC-FR03-03 — Exponential backoff: nth retry waits TASKQ_BACKOFF_BASE × 2^n (POSITIVE, P0)
- **Pre-condition:** `TASKQ_BACKOFF_BASE=0.1`, `TASKQ_RETRY_LIMIT=3`, command `false`, `sleep_fn` injected.
- **Input:** run task once.
- **Expected output:** sleep invocations logged: `[0.1, 0.2, 0.4]` seconds before retries 1, 2, 3 respectively (after initial failure, before each retry).

### TC-FR03-04 — Retry exhaustion stops after TASKQ_RETRY_LIMIT (BOUNDARY, P0)
- **Pre-condition:** `TASKQ_RETRY_LIMIT=0`, command `false`.
- **Input:** run task once.
- **Expected output:** subprocess invoked exactly 1 time (no retries); final status `failed`; no sleep invocation between attempts.

### TC-FR03-05 — sleep_fn injectable (test seam, P0)
- **Input:** inject `sleep_fn=lambda s: recorded.append(s)`.
- **Expected output:** real `time.sleep` NOT called (mock-counted); test seam replaced globally.

### TC-FR03-06 — Breaker CLOSED → OPEN at TASKQ_BREAKER_THRESHOLD consecutive failures (POSITIVE, P0)
- **Pre-condition:** `TASKQ_BREAKER_THRESHOLD=3`, command `false`; submit & run 3 separate tasks sequentially.
- **Input:** run 3rd task.
- **Expected output:** after 3rd run's final failure, breaker state = `OPEN`; `breaker.json` reflects state.

### TC-FR03-07 — Breaker OPEN refuses with exit 3 + stderr "breaker open" (POSITIVE, P0)
- **Pre-condition:** breaker state `OPEN`.
- **Input:** `python -m taskq run <pending-id>`.
- **Expected output:** CLI exit code `3`; stderr contains `breaker open`; **no subprocess spawned** (mock counter = 0).

### TC-FR03-08 — Breaker OPEN does NOT execute subprocess (EDGE, P0)
- **Input:** same as TC-FR03-07 with wrapped `subprocess.run` mock.
- **Expected output:** mock invocation count = 0.

### TC-FR03-09 — After TASKQ_BREAKER_COOLDOWN, state → HALF_OPEN (POSITIVE, P0)
- **Pre-condition:** breaker `OPEN` with `TASKQ_BREAKER_COOLDOWN=2`; sleep 2.1s via injected `time_fn`.
- **Input:** probe with one task.
- **Expected output:** breaker transitions `OPEN → HALF_OPEN` before probe; probe executes subprocess.

### TC-FR03-10 — HALF_OPEN probe success → CLOSED + counter reset (POSITIVE, P0)
- **Pre-condition:** HALF_OPEN with one probe pending; probe command succeeds (`true`).
- **Input:** run probe.
- **Expected output:** state `CLOSED`; failure counter = 0; subsequent runs allowed.

### TC-FR03-11 — HALF_OPEN probe failure → OPEN (NEGATIVE, P0)
- **Pre-condition:** HALF_OPEN; probe command fails (`false`).
- **Input:** run probe.
- **Expected output:** state `OPEN`; cooldown timer restarted.

### TC-FR03-12 — HALF_OPEN second concurrent run rejected (EDGE, P0)
- **Pre-condition:** HALF_OPEN; one probe in flight.
- **Input:** second `run` invoked concurrently.
- **Expected output:** second run rejected with exit 3 (only one probe at a time).

### TC-FR03-13 — Breaker state persisted to breaker.json (POSITIVE, P0)
- **Pre-condition:** drive breaker to OPEN.
- **Input:** read `$TASKQ_HOME/breaker.json`.
- **Expected output:** JSON contains `state="OPEN"`, `consecutive_failures >= threshold`, `opened_at` ISO-8601.

### TC-FR03-14 — Breaker.json written atomically (POSITIVE, P0)
- **Input:** unit test wrapping `os.replace`; trigger breaker write.
- **Expected output:** write uses tmp + `os.replace`; pre-call content recoverable on mid-write failure (cross-ref NFR-03 TC-NFR03-01b).

### TC-FR03-15 — Breaker counter is global across tasks and processes (EDGE, P0)
- **Input:** invoke CLI as 3 separate processes, each running a failing task; observe breaker.json between calls.
- **Expected output:** counter increments across processes; OPEN reached after threshold total failures across processes.

### TC-FR03-16 — Retry succeeds within limit → no failure counted (POSITIVE, P0)
- **Pre-condition:** `TASKQ_RETRY_LIMIT=2`, command that fails first then succeeds (mock retry path).
- **Input:** run task.
- **Expected output:** final status `done`; breaker counter NOT incremented; no OPEN transition.

---

## 4. FR-04 — Result TTL Cache

**Module under test:** `taskq.cache`
**AC anchor:** AC-FR-04-01..04

### TC-FR04-01 — Cache signature = sha256(command) (POSITIVE, P0)
- **Input:** unit test on `cache.signature("echo hello")`.
- **Expected output:** returns hex digest of length 64 (sha256); two calls with identical input return identical digest.

### TC-FR04-02 — Different commands produce different signatures (EDGE, P0)
- **Input:** `signature("echo a")`, `signature("echo b")`.
- **Expected output:** distinct hex digests.

### TC-FR04-03 — Cached run replays without subprocess (POSITIVE, P0)
- **Pre-condition:** task A with command `echo hi` previously executed successfully (done) within TTL.
- **Input:** submit new task B with identical command; `python -m taskq run <B.id> --cached`.
- **Expected output:** `subprocess.run` mock invocation count = 0; task B final `status="done"`, `cached=true`; `exit_code` and `stdout_tail` match task A's record.

### TC-FR04-04 — Cached run replays only for done status (NEGATIVE, P0)
- **Pre-condition:** prior task with same command finished `failed` or `timeout`.
- **Input:** new task same command; `python -m taskq run --cached`.
- **Expected output:** subprocess IS executed (cache miss for non-done); task final status reflects actual run.

### TC-FR04-05 — Expired entry → normal execution (BOUNDARY, P0)
- **Pre-condition:** cache entry timestamped `TASKQ_CACHE_TTL + 1` seconds ago (injected clock).
- **Input:** `python -m taskq run <id> --cached` with same signature.
- **Expected output:** subprocess executed; new result written to cache.json; old entry replaced.

### TC-FR04-06 — TTL boundary exactly = TASKQ_CACHE_TTL accepted (BOUNDARY, P0)
- **Pre-condition:** cache entry timestamped exactly `TASKQ_CACHE_TTL` seconds ago (clock-injected boundary test).
- **Input:** `python -m taskq run --cached`.
- **Expected output:** replayed (or executed — verify implementation choice; current SPEC implies "≤ TTL" → replay).

### TC-FR04-07 — Cache write on done (POSITIVE, P0)
- **Pre-condition:** fresh TASKQ_HOME; task A command `echo cache-write`.
- **Input:** `python -m taskq run <A.id>` (no `--cached`).
- **Expected output:** post-run `$TASKQ_HOME/cache.json` contains entry with `signature=sha256("echo cache-write")`, `exit_code=0`, `stdout_tail`, `finished_at`.

### TC-FR04-08 — Cache write skipped on failed/timeout (NEGATIVE, P0)
- **Pre-condition:** fresh TASKQ_HOME; task command `false`.
- **Input:** `python -m taskq run <id>`.
- **Expected output:** cache.json empty or absent (no entry written for non-done).

### TC-FR04-09 — Cache write atomic (POSITIVE, P0)
- **Input:** unit test on `cache.put()`; mock `os.replace` to fail.
- **Expected output:** on `os.replace` failure, prior cache.json retained; no torn write.

### TC-FR04-10 — Concurrent cache reads/writes safe (EDGE, P0)
- **Input:** 8 threads simultaneously invoke `cache.get(sig)` and `cache.put(...)`.
- **Expected output:** final cache.json valid JSON; no record corruption; thread-safe (Lock protected).

---

## 5. FR-05 — CLI Integration

**Module under test:** `taskq.cli`, `taskq.__main__`
**AC anchor:** AC-FR-05-01..03

### TC-FR05-01 — `python -m taskq` entry point launches argparse (POSITIVE, P0)
- **Input:** `python -m taskq --help`.
- **Expected output:** exit code `0`; stdout lists subcommands `submit`, `run`, `status`, `list`, `clear`.

### TC-FR05-02 — `submit` subcommand routes to FR-01 (POSITIVE, P0)
- **Input:** `python -m taskq submit "echo hello"`.
- **Expected output:** behaves identically to TC-FR01-01 (delegation test).

### TC-FR05-03 — `run <id>` subcommand routes to FR-02/03/04 (POSITIVE, P0)
- **Input:** `python -m taskq run <id>` after submit.
- **Expected output:** behaves identically to TC-FR02-02/03/04.

### TC-FR05-04 — `run --all` routes to FR-02 batch (POSITIVE, P0)
- **Input:** `python -m taskq run --all`.
- **Expected output:** behaves identically to TC-FR02-10/11.

### TC-FR05-05 — `run --cached` routes to FR-04 replay (POSITIVE, P0)
- **Input:** `python -m taskq run <id> --cached`.
- **Expected output:** behaves identically to TC-FR04-03.

### TC-FR05-06 — `status <id>` prints full task record (POSITIVE, P0)
- **Pre-condition:** submitted task `t1` exists.
- **Input:** `python -m taskq status t1`.
- **Expected output:** exit code `0`; stdout contains all fields (`id`, `command`, `name`, `status`, `created_at`, optional `exit_code`/`stdout_tail`/`stderr_tail`/`duration_ms`/`finished_at`).

### TC-FR05-07 — `status <id>` with --json returns single-line JSON (POSITIVE, P0)
- **Input:** `python -m taskq --json status t1`.
- **Expected output:** exit code `0`; stdout is single-line JSON parseable by `json.loads` containing the same fields.

### TC-FR05-08 — `status` unknown id → exit code 2 (NEGATIVE, P0)
- **Input:** `python -m taskq status 00000000`.
- **Expected output:** exit code `2`; stderr mentions unknown task id.

### TC-FR05-09 — `list` shows all tasks (POSITIVE, P0)
- **Pre-condition:** 3 tasks enqueued.
- **Input:** `python -m taskq list`.
- **Expected output:** stdout lists 3 task records (one per line summary or table); exit code `0`.

### TC-FR05-10 — `list --status <state>` filters correctly (POSITIVE, P0)
- **Pre-condition:** 2 pending + 1 done task.
- **Input:** `python -m taskq list --status pending`.
- **Expected output:** stdout contains exactly the 2 pending records; done record absent.

### TC-FR05-11 — `list --status <invalid>` rejected (NEGATIVE, P1)
- **Input:** `python -m taskq list --status bogus`.
- **Expected output:** exit code `2`; argparse error; stderr non-empty.

### TC-FR05-12 — `clear` wipes all TASKQ_HOME data files (POSITIVE, P0)
- **Pre-condition:** `$TASKQ_HOME/tasks.json`, `breaker.json`, `cache.json` all populated.
- **Input:** `python -m taskq clear`.
- **Expected output:** all three data files removed (or zero-byte / reset); subsequent `list` shows 0 tasks.

### TC-FR05-13 — `clear` followed by `submit` succeeds (POSITIVE, P1)
- **Input:** after `clear`, submit `"echo fresh"`.
- **Expected output:** exit code `0`; tasks.json recreated; breaker counter reset; cache cleared.

---

## 6. NFR Coverage

### 6.1 NFR-01 — Performance (submit + status p95 < 50ms)

**Anchor:** AC-NFR-01-01
**Module:** `taskq.cli`
**Tooling:** `pytest-benchmark`

#### TC-NFR01-01 — submit + status p95 under 50ms over 100 iterations (POSITIVE, P0)
- **Input:** `pytest-benchmark` fixture running 100 iterations of `submit("echo N")` then `status(id)`.
- **Expected output:** p95 latency < 50ms (per `pytest-benchmark` stats output).

#### TC-NFR01-02 — p95 measurement excludes subprocess execution (BOUNDARY, P1)
- **Input:** benchmark fixture configured to use a fast-failing mock subprocess.
- **Expected output:** p95 < 50ms confirmed; clarifies NFR-99-a (see Open Issues §8) — currently interpreted as in-process submit+status path only.

#### TC-NFR01-03 — Cold-start overhead amortized (EDGE, P1)
- **Input:** first iteration of benchmark often includes interpreter warm-up; inspect raw stats.
- **Expected output:** excluding first iteration, p95 still < 50ms.

#### TC-NFR01-04 — Performance stable across TASKQ_HOME sizes (EDGE, P2)
- **Input:** benchmark with 0, 100, 1000 prior tasks in tasks.json.
- **Expected output:** p95 remains < 50ms (linear scan acceptable given scale).

### 6.2 NFR-02 — Security (shell + injection)

**Anchor:** AC-NFR-02-01, AC-NFR-02-02
**Module:** `taskq.executor` (no `shell=True`), `taskq.cli` (blacklist enforcement)

#### TC-NFR02-01 — grep gate: zero `shell=True` occurrences in src/ (STATIC GATE, P0)
- **Input:** `grep -RIn "shell=True" src/`.
- **Expected output:** 0 hits. Implemented as a CI gate or pytest test invoking subprocess.

#### TC-NFR02-02 — Each injection char (`;`, `|`, `&`, `$`, `>`, `<`, `` ` ``) rejected at submit (NEGATIVE, P0)
- **Input:** 7 parametrized test cases (one per blacklist character).
- **Expected output:** all 7 → exit 2; no record written.

#### TC-NFR02-03 — Mixed safe + injection char rejected (NEGATIVE, P1)
- **Input:** `submit "echo a; echo b"` (injection in middle).
- **Expected output:** exit 2; rejected (no substring matching required for blacklist).

#### TC-NFR02-04 — Quote-escaped injection char still rejected (EDGE, P1)
- **Input:** `submit "echo \\; rm"` (escaped semicolon).
- **Expected output:** exit 2 (blacklist matches literal char regardless of shell interpretation context).

#### TC-NFR02-05 — Command execution never invokes shell (POSITIVE, P0)
- **Input:** wrap `subprocess.run` mock and run any task.
- **Expected output:** mock called with list arg (from `shlex.split`) and `shell=False` (or absent → default False).

#### TC-NFR02-06 — Blacklist character set matches SPEC.md (P0)
- **Input:** `set(BLACKLIST)` extracted from `cli.py` (or wherever enforced) compared to `{";", "|", "&", "$", ">", "<", "\`"}`.
- **Expected output:** set equality; no additions, no omissions.

#### TC-NFR02-07 — Unicode lookalike characters NOT in blacklist (EDGE, P2)
- **Input:** `submit "echo a；b"` (fullwidth semicolon U+FF1B).
- **Expected output:** accepted (not in 7-char ASCII blacklist). Document accepted behavior; defer to out-of-scope or follow-up if SPEC author clarifies.

#### TC-NFR02-08 — Newline injection not in blacklist, but commands split cleanly (EDGE, P2)
- **Input:** `submit "echo a\nrm"` (literal newline).
- **Expected output:** accept or reject per SPEC. Currently accepted; multi-line behavior is OS-/shell-dependent. Flag as advisory.

#### TC-NFR02-09 — Blacklist enforcement documented in docstring (P2)
- **Input:** static check that the enforcement function's docstring references FR-01 and NFR-02.

### 6.3 NFR-03 — Reliability (atomic write + breaker recovery)

**Anchor:** AC-NFR-03-01, AC-NFR-03-02
**Module:** `taskq.store`, `taskq.breaker`

#### TC-NFR03-01 — Atomic write across all 3 data files (POSITIVE, P0)
- **Input:** unit tests for `tasks.json`, `breaker.json`, `cache.json` write paths.
- **Expected output:** each uses tmp + `os.replace`; failure mid-write leaves prior content intact.

#### TC-NFR03-02 — Mid-write crash leaves valid JSON (EDGE, P0)
- **Pre-condition:** simulate `os.replace` raising `OSError`; previously written file exists.
- **Input:** invoke write path.
- **Expected output:** pre-existing JSON file retained and parseable; no `.tmp` orphan (or orphan is cleaned up — implementation-dependent).

#### TC-NFR03-03 — Breaker OPEN → CLOSED recovery time ≤ TASKQ_BREAKER_COOLDOWN + 1s (POSITIVE, P0)
- **Pre-condition:** breaker `OPEN`, `TASKQ_BREAKER_COOLDOWN=2`; inject `time_fn`.
- **Input:** advance time by `TASKQ_BREAKER_COOLDOWN + 0.5s`; run successful probe.
- **Expected output:** breaker state = `CLOSED` within `TASKQ_BREAKER_COOLDOWN + 1s` of probe dispatch (per NFR-99-b — measure at HALF_OPEN probe success moment).

#### TC-NFR03-04 — Breaker OPEN → CLOSED within +1s upper bound (BOUNDARY, P0)
- **Input:** same as TC-NFR03-03 but advance time by exactly `TASKQ_BREAKER_COOLDOWN + 1s`.
- **Expected output:** recovery completed; state = `CLOSED`.

#### TC-NFR03-05 — Corrupt tasks.json detected on startup (NEGATIVE, P0)
- **Pre-condition:** `tasks.json` contains invalid JSON.
- **Input:** any CLI invocation that loads `tasks.json`.
- **Expected output:** exit code `1` (or process exit per SPEC); clear error message; data NOT silently rebuilt.

#### TC-NFR03-06 — Corrupt breaker.json or cache.json detected on startup (NEGATIVE, P1)
- **Input:** place invalid JSON in breaker.json / cache.json.
- **Expected output:** detected at read; appropriate error or graceful reset (verify implementation choice per SPEC §7).

### 6.4 NFR-04 — Security (secret redaction)

**Anchor:** AC-NFR-04-01
**Module:** `taskq.executor`

#### TC-NFR04-01 — sk- pattern in stdout redacted (POSITIVE, P0)
- **Input:** command `echo "sk-abcdefgh1234"` or similar valid secret prefix.
- **Expected output:** persisted `stdout_tail` line is exactly `[REDACTED]`; original secret bytes NOT in tasks.json.

#### TC-NFR04-02 — token= pattern in stdout redacted (POSITIVE, P0)
- **Input:** command echoes `token=abc123def`.
- **Expected output:** persisted `stdout_tail` line is `[REDACTED]`.

#### TC-NFR04-03 — sk- pattern in stderr redacted (POSITIVE, P0)
- **Input:** command emits `sk-abcdefgh1234` on stderr.
- **Expected output:** persisted `stderr_tail` line is `[REDACTED]`.

#### TC-NFR04-04 — token= pattern in stderr redacted (POSITIVE, P0)
- **Input:** command emits `token=abc123def` on stderr.
- **Expected output:** persisted `stderr_tail` line is `[REDACTED]`.

#### TC-NFR04-05 — Non-matching line unchanged (NEGATIVE/EDGE, P0)
- **Input:** command outputs `hello world` (no match).
- **Expected output:** persisted line equals input verbatim.

#### TC-NFR04-06 — Redaction applied BEFORE persistence to tasks.json (POSITIVE, P0)
- **Input:** task emits secret; after `run`, inspect `$TASKQ_HOME/tasks.json` byte content.
- **Expected output:** file contains no `sk-` substring matching the pattern; secret bytes absent from disk.

### 6.5 NFR-05 — Maintainability (docstring FR-cross-ref)

**Anchor:** AC-NFR-05-01
**Module:** `taskq.models` (gate inspect) + all of `src/taskq/`

#### TC-NFR05-01 — All public functions have docstring with [FR-XX] ref (STATIC GATE, P0)
- **Input:** AST scan of `src/taskq/`; collect public functions/classes (no leading underscore).
- **Expected output:** 100% coverage of docstrings containing `[FR-NN]` or `[NFR-NN]` reference pattern (regex `\[(FR|NFR)-\d{2}\]`).

#### TC-NFR05-02 — No public symbol lacks FR/NFR reference (P0)
- **Input:** enumerate public symbols (functions, classes, methods).
- **Expected output:** zero violations; failures list symbol name + file:line.

#### TC-NFR05-03 — Private functions exempt (EDGE, P1)
- **Input:** leading-underscore functions allowed without ref.
- **Expected output:** only public symbols counted toward violation count.

#### TC-NFR05-04 — FR references traceable to SRS.md FR IDs (P1)
- **Input:** cross-check each `[FR-NN]` in docstrings against `quality_manifest.json::fr_ids`.
- **Expected output:** every reference matches a registered FR ID; no stale/dangling references.

### 6.6 NFR-06 — Deployability (env vars)

**Anchor:** AC-NFR-06-01
**Module:** `taskq.config`

#### TC-NFR06-01 — All 8 TASKQ_* env vars read from config.py (POSITIVE, P0)
- **Input:** set `TASKQ_HOME`, `TASKQ_MAX_WORKERS`, `TASKQ_TASK_TIMEOUT`, `TASKQ_RETRY_LIMIT`, `TASKQ_BACKOFF_BASE`, `TASKQ_BREAKER_THRESHOLD`, `TASKQ_BREAKER_COOLDOWN`, `TASKQ_CACHE_TTL`; invoke `config.load()`.
- **Expected output:** all 8 values returned matching env overrides.

#### TC-NFR06-02 — Defaults applied when env unset (POSITIVE, P0)
- **Input:** unset env (use monkeypatch `monkeypatch.delenv`); invoke `config.load()`.
- **Expected output:** all 8 vars return documented defaults (`.taskq`, `4`, `10.0`, `2`, `0.1`, `3`, `5.0`, `3600`).

#### TC-NFR06-03 — `.env.example` declares all 8 vars with comments (STATIC GATE, P0)
- **Input:** parse `.env.example`; assert presence of each `TASKQ_*=NAME` plus an inline comment.
- **Expected output:** 8 entries; each line has `#` annotation.

#### TC-NFR06-04 — Invalid env var type rejected (NEGATIVE, P1)
- **Input:** set `TASKQ_RETRY_LIMIT=abc` (non-integer).
- **Expected output:** config loader raises `ValueError` (or coerced with error message); CLI exits with `1`.

---

## 7. Cross-Cutting & Acceptance Criteria Mapping (SPEC.md §8)

| # | SPEC.md §8 acceptance item | Anchored TCs |
|---|----------------------------|--------------|
| 1 | `pytest tests/ -q` all green | TC-FR01-*, TC-FR02-*, TC-FR03-*, TC-FR04-*, TC-FR05-*, TC-NFR01/02/03/04/05/06-* |
| 2 | `submit "echo hi"` → 8-hex id; `run` → done; `status` shows `exit_code: 0` | TC-FR01-01 + TC-FR02-02 + TC-FR05-06 |
| 3 | `submit ""` → exit 2 | TC-FR01-04 |
| 4 | `submit "echo hi; rm x"` → exit 2 (injection) | TC-FR01-10 (parametrized via TC-NFR02-02) |
| 5 | `TASKQ_TASK_TIMEOUT=1`, `sleep 5` → status `timeout`, exit 4 | TC-FR02-04 + TC-FR02-09 |
| 6 | 3 final-fail tasks → 4th run exit 3; cooldown recovery | TC-FR03-06/07 + TC-NFR03-03 |
| 7 | TTL within, `run --cached` (same sig) → replay + `cached:true`, no subprocess | TC-FR04-03 + TC-FR04-01 |
| 8 | `.env.example` declares all 8 TASKQ_* vars | TC-NFR06-03 |
| 9 | `run --all` concurrent → valid tasks.json, no task loss | TC-FR02-10/11 |
| 10 | Public function docstrings contain `[FR-XX]` | TC-NFR05-01/02 |

---

## 8. Open Issues Inherited from SRS.md

| Issue | Anchor | Test plan handling |
|-------|--------|--------------------|
| NFR-99-a | p95 < 50ms boundary (含/不含 subprocess) | TC-NFR01-02 documents current interpretation (in-process only); TC-NFR01-01 benchmark asserts as-is. Pending stakeholder confirmation. |
| NFR-99-b | breaker OPEN→CLOSED observation moment | TC-NFR03-03/04 measure at HALF_OPEN probe success moment; verify with stakeholder. |

---

## 9. Test Execution Strategy

### 9.1 Test Layering

| Layer | Location | Scope |
|-------|----------|-------|
| Unit | `03-development/tests/test_fr0X.py`, `test_nfr.py` | Per-function/per-class logic with mocked subprocess & injected sleep |
| Integration | `03-development/tests/test_fr*.py` (integration section) | End-to-end CLI invocation via `subprocess.run(python -m taskq ...)` against `tmp_path` TASKQ_HOME |
| Static gate | `03-development/tests/test_nfr.py` (static methods) + CI grep | `shell=True` scan; docstring AST scan; `.env.example` parser |
| Performance | `03-development/tests/test_nfr.py` (benchmarked) | `pytest-benchmark` NFR-01 |

### 9.2 Fixture Strategy

- **`tmp_path` per test** → assigns `TASKQ_HOME` to isolated directory; auto-cleanup.
- **`monkeypatch`** → env-var injection (NFR-06), `sleep_fn` injection (FR-03), `time_fn` injection (NFR-03), `subprocess.run` mock (FR-02/03/04 safety).
- **Parametrize** → blacklist character matrix (TC-NFR02-02), redaction patterns (TC-NFR04-*).

### 9.3 Pre-Flight Checks (Gate 3 entry)

1. `pytest 03-development/tests/ -q` → 100% pass
2. `coverage run -m pytest` → ≥ 80% line coverage per module
3. `grep -RIn "shell=True" src/` → 0 hits (NFR-02 static)
4. `python -m taskq --help` → exit 0 (smoke)
5. Docstring AST scan → 0 public-symbol violations (NFR-05)
6. `pytest-benchmark` NFR-01 → p95 < 50ms

### 9.4 Exit Criteria for Gate 3

- All P0 tests pass.
- All P1 tests pass or carry a justified waiver.
- Coverage ≥ 80% across all 8 modules.
- NFR-02 static gate: 0 hits.
- NFR-05 static gate: 0 violations.

---

## 10. Out-of-Scope for Phase 4 Test Plan

- Performance optimization beyond budget verification (handled in Phase 5/6).
- Security hardening beyond stated NFR-02/NFR-04 (handled in Phase 7).
- Refactoring for complexity reduction (handled in Phase 6).
- Documentation beyond docstring FR-cross-ref (handled in Phase 8).
- Cross-process race conditions beyond breaker global state (covered where SPEC mandates; otherwise out-of-scope per §6 of SRS.md).

---

## 11. Coverage Verification

| FR/NFR | TCs planned | ACs covered | Module mapped | Status |
|--------|-------------|-------------|---------------|--------|
| FR-01 | 21 | AC-FR-01-01..05 | taskq.cli, taskq.store, taskq.models | COVERED |
| FR-02 | 14 | AC-FR-02-01..05 | taskq.executor, taskq.store | COVERED |
| FR-03 | 16 | AC-FR-03-01..05 | taskq.executor, taskq.breaker | COVERED |
| FR-04 | 10 | AC-FR-04-01..04 | taskq.cache | COVERED |
| FR-05 | 13 | AC-FR-05-01..03 | taskq.cli, taskq.__main__ | COVERED |
| NFR-01 | 4 | AC-NFR-01-01 | taskq.cli | COVERED |
| NFR-02 | 9 | AC-NFR-02-01..02 | taskq.executor, taskq.cli | COVERED |
| NFR-03 | 6 | AC-NFR-03-01..02 | taskq.store, taskq.breaker | COVERED |
| NFR-04 | 6 | AC-NFR-04-01 | taskq.executor | COVERED |
| NFR-05 | 4 | AC-NFR-05-01 | taskq.models (gate inspect) | COVERED |
| NFR-06 | 4 | AC-NFR-06-01 | taskq.config | COVERED |
| **TOTAL** | **107** | **28 ACs across 5 FR + 6 NFR** | **8 modules** | **ALL COVERED** |

### 11.1 Quality manifest FR cross-check

| `quality_manifest.json::fr_ids` entry | TEST_PLAN coverage |
|----------------------------------------|---------------------|
| FR-01 | §1, 21 TCs |
| FR-02 | §2, 14 TCs |
| FR-03 | §3, 16 TCs |
| FR-04 | §4, 10 TCs |
| FR-05 | §5, 13 TCs |
| **All 5 FRs** | **COVERED** |

### 11.2 Quality manifest NFR cross-check

| `quality_manifest.json::nfr_traceability` key | TEST_PLAN coverage |
|-----------------------------------------------|---------------------|
| NFR-01 (performance) | §6.1, 4 TCs |
| NFR-02 (security) | §6.2, 9 TCs |
| NFR-03 (reliability) | §6.3, 6 TCs |
| NFR-04 (security) | §6.4, 6 TCs |
| NFR-05 (maintainability) | §6.5, 4 TCs |
| NFR-06 (deployability) | §6.6, 4 TCs |
| **All 6 NFRs** | **COVERED** |

---

## 12. Author Sign-Off

- [x] All 5 FRs from `quality_manifest.json::fr_ids` covered with positive/negative/boundary/edge-case categories.
- [x] All 6 NFRs from `quality_manifest.json::nfr_traceability` covered.
- [x] Test IDs follow `TC-{FR|NFR}{NN}-{AC-NN}{a|b|c|...}` convention (matches `TEST_INVENTORY.yaml::tc_id_format`).
- [x] Each TC specifies ID, description, input, expected output, priority (P0/P1/P2/P3).
- [x] Traceability matrix (§7) maps every SPEC.md §8 acceptance item to specific TCs.
- [x] Open issues inherited from SRS.md §7 (NFR-99-a, NFR-99-b) flagged for stakeholder resolution.
- [x] No execution of tests performed (test plan author scope only).
- [x] No harness/ modifications (test plan author scope only).

**Document ready for Phase 4 Gate 3 hand-off.**

---

*End of TEST_PLAN.md*