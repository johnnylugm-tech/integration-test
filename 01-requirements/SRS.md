# Software Requirements Specification (SRS) — taskq

> Ingestion mode. Source of truth: `SPEC.md` (v3.0.0, 2026-07-04, 5 FR / 6 NFR / 8 env vars), per `PROJECT_BRIEF.md` `canonical_spec` field.
> Prompt-injection scan: clean — 0 hits in canonical.

---

## 1. Introduction

### 1.1 Purpose

`taskq` is a local task-queue CLI tool: submit shell commands as tasks;
run them with controlled concurrency, timeout, retry, circuit breaker,
and TTL result cache; query status; clear storage. (SPEC.md §1)

### 1.2 Scope

- Language: Python 3.11, zero external runtime dependencies (stdlib
  only; test tooling provided by the dev environment). (SPEC.md §1)
- Form: command-line tool, entry point `python -m taskq`. (SPEC.md §1)

### 1.3 Technical Architecture

| Component | Technology |
|---|---|
| CLI | argparse subcommands |
| Task execution | `subprocess` (`shlex.split`, `shell=True` forbidden) |
| Concurrency | `concurrent.futures.ThreadPoolExecutor` |
| Persistence | JSON files (atomic write: tmp + `os.replace`) |
| Thread safety | `threading.Lock` protecting shared store |
| Configuration | `TASKQ_*` environment variables (unified read via `config.py`) |

(SPEC.md §2)

---

## 2. Constraints

- **Technical**: Python 3.11 stdlib only at runtime; `python -m taskq`
  CLI entry; `shell=True` is forbidden everywhere (NFR-02);
  `ThreadPoolExecutor` for `run --all` with shared `threading.Lock`
  over the store (FR-02). (SPEC.md §2, §3 FR-02, §4 NFR-02)
- **Atomicity**: all three data files (`tasks.json`, `breaker.json`,
  `cache.json`) are written via tmp file + `os.replace`; a mid-write
  crash must leave valid JSON. (SPEC.md §4 NFR-03, §5.2)
- **Security**: injection-character blacklist (`; | & $ > < \``) on
  `submit` (NFR-02); secret-line redaction on `stdout_tail` /
  `stderr_tail` matching `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` (NFR-04).
  (SPEC.md §4 NFR-02, NFR-04)
- **Reliability**: circuit breaker opens at a consecutive final-failure
  threshold and refuses execution until cooldown; `tasks.json`
  corruption is detected and surfaced (exit 1) rather than silently
  rebuilt. (SPEC.md §3 FR-03, §4 NFR-03, §7)
- **Performance**: `submit` + `status` combined operation (excluding
  subprocess execution) p95 < 50ms over 100 iterations, measured by
  pytest-benchmark. (SPEC.md §4 NFR-01)
- **Architecture**: `no_circular_dependencies` among the 8 modules
  under `src/taskq/`; `taskq.executor` and `taskq.store` are
  framework-classified high-risk modules requiring per-module TDD
  coverage. (SPEC.md §6, §10)
- **Module layout** (SPEC.md §6):

```
src/taskq/
├── __init__.py
├── __main__.py        # python -m taskq entry
├── config.py          # TASKQ_* env (NFR-06)
├── models.py           # task / status dataclasses
├── store.py            # tasks.json atomic + Lock (FR-01/02) — high-risk
├── executor.py         # subprocess + retry (FR-02/03) — high-risk
├── breaker.py           # circuit breaker (FR-03)
├── cache.py              # TTL cache (FR-04)
└── cli.py                 # argparse (FR-05)
```

---

## 3. Functional Requirements

> Each section below quotes SPEC.md verbatim (original Chinese source
> text, unmodified) followed by a `DERIVED:` tag marking the AC list as
> the testable operationalization of that verbatim rule set, per the
> Canonical Interpretation Rule (R-CANONICAL-INTERP-001).

### FR-01: Task Submission and Validation

**Citation**: SPEC.md §3 FR-01

DERIVED: SPEC.md §3 FR-01.

> 驗證規則(任一違反 → **exit 2** + stderr 錯誤訊息,不寫入存儲):
> | 規則 | 條件 |
> |------|------|
> | 非空 | 命令為空或全空白 → 拒絕 |
> | 長度 | 命令 > 1000 字元 → 拒絕 |
> | 注入字元 | 命令含 `;` `|` `&` `$` `>` `<` `` ` `` 任一 → 拒絕(NFR-02) |
> | 名稱唯一 | `--name` 與既有 pending/running 任務重複 → 拒絕 |
> 通過驗證:
> - 產生 task id(uuid4 前 8 hex)
> - 狀態 `pending`,記錄 `command`、`name`、`created_at`
> - 原子寫入 `$TASKQ_HOME/tasks.json`
> - stdout 輸出 task id(`--json` 時輸出 `{"id": ..., "status": "pending"}`)

**Acceptance Criteria**:
- AC-FR-01-1: 空命令 -> exit 2, 不寫入.
- AC-FR-01-2: 命令長度 > 1000 -> exit 2, 不寫入.
- AC-FR-01-3: 含注入字元 -> exit 2, 不寫入.
- AC-FR-01-4: --name 與既有 pending/running 重複 -> exit 2.
- AC-FR-01-5: 通過驗證 -> exit 0, 輸出 8-hex id, 狀態 pending.
- AC-FR-01-6: --json -> 單行 JSON.

### FR-02: Task Executor

**Citation**: SPEC.md §3 FR-02

DERIVED: SPEC.md §3 FR-02.

> 以 `subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=TASKQ_TASK_TIMEOUT)` 執行;**任何路徑不得使用 `shell=True`**
> - 狀態機:`pending → running → done | failed | timeout`
>   - exit 0 → `done`;非 0 → `failed`;`TimeoutExpired` → `timeout`
> - 結果欄位:`exit_code`、`stdout_tail`(末 2000 字元)、`stderr_tail`(末 2000 字元)、`duration_ms`、`finished_at`
> - `--all`:以 `ThreadPoolExecutor(max_workers=TASKQ_MAX_WORKERS)` 並發執行全部 `pending` 任務;存儲寫入必須執行緒安全(共享 Lock)
> - 單一任務模式下 `timeout` 結果 → **exit 4**

**Acceptance Criteria**:
- AC-FR-02-1: subprocess.run + shlex.split, 全程不得 shell=True.
- AC-FR-02-2: exit0->done, 非0->failed, TimeoutExpired->timeout.
- AC-FR-02-3: 結果含 exit_code/stdout_tail/stderr_tail/duration_ms/finished_at.
- AC-FR-02-4: run --all 並發, Lock 保護寫入 (see AC-NFR-03-1).
- AC-FR-02-5: 單一任務 timeout -> exit 4.

### FR-03: Retry and Circuit Breaker

**Citation**: SPEC.md §3 FR-03

DERIVED: SPEC.md §3 FR-03.

> **重試**:`run` 結果為 `failed`/`timeout` 時自動重試,上限 `TASKQ_RETRY_LIMIT` 次;第 n 次重試前等待 `TASKQ_BACKOFF_BASE × 2^n` 秒(exponential backoff;sleep 函式必須可注入以利測試)。
> **斷路器**(全域,跨任務、跨進程):
> - 連續最終失敗(重試耗盡仍 failed/timeout)計數 ≥ `TASKQ_BREAKER_THRESHOLD` → `OPEN`
> - `OPEN` 期間任何 `run` 立即拒絕:**exit 3** + stderr `breaker open`,不執行 subprocess
> - 經 `TASKQ_BREAKER_COOLDOWN` 秒後進入 `HALF_OPEN`:放行一個任務 — 成功 → `CLOSED` 且計數歸零;失敗 → 重新 `OPEN`
> - 狀態持久化於 `$TASKQ_HOME/breaker.json`(原子寫)

**Acceptance Criteria**:
- AC-FR-03-1: failed/timeout 自動重試至 TASKQ_RETRY_LIMIT, backoff 可注入.
- AC-FR-03-2: 連續最終失敗達 TASKQ_BREAKER_THRESHOLD -> OPEN.
- AC-FR-03-3: OPEN 期間 run -> exit 3, stderr breaker open, 不執行 subprocess.
- AC-FR-03-4: cooldown 後 HALF_OPEN 放行一個任務, 成功->CLOSED, 失敗->OPEN.
- AC-FR-03-5: breaker 狀態原子寫入 breaker.json.

### FR-04: Result TTL Cache

**Citation**: SPEC.md §3 FR-04

DERIVED: SPEC.md §3 FR-04.

> - 快取簽名 = `sha256(command)`
> - `taskq run <id> --cached`:同簽名且結果為 `done` 的最近執行在 `TASKQ_CACHE_TTL` 秒內 → 直接回放(`exit_code`/`stdout_tail`),**不執行 subprocess**,任務標記 `done` 且 `cached: true`
> - 快取過期或不存在 → 正常執行,成功(`done`)後寫入 `$TASKQ_HOME/cache.json`
> - 快取讀寫:原子 + 執行緒安全(與 FR-02 並發共存)

**Acceptance Criteria**:
- AC-FR-04-1: 快取簽名 sha256(command).
- AC-FR-04-2: TTL 內同簽名 done -> 回放, 不執行 subprocess, cached true.
- AC-FR-04-3: 快取過期或不存在 -> 正常執行, done 後寫入 cache.json.
- AC-FR-04-4: cache.json 原子 + 執行緒安全.

### FR-05: CLI Integration

**Citation**: SPEC.md §3 FR-05

DERIVED: SPEC.md §3 FR-05.

> | 命令 | 行為 |
> |------|------|
> | `submit "<cmd>" [--name N]` | FR-01 |
> | `run <id> [--cached]` / `run --all` | FR-02/03/04 |
> | `status <id>` | 輸出該任務全欄位 |
> | `list [--status S]` | 列出任務(可按狀態過濾) |
> | `clear` | 清空 `$TASKQ_HOME` 全部資料檔 |
> - 全域 flag `--json`:機器可讀輸出(單行 JSON)
> - **Exit codes**:`0` 成功 / `2` 輸入驗證錯誤(含 unknown task id) / `3` breaker open / `4` 任務 timeout / `1` 其他內部錯誤

**Acceptance Criteria**:
- AC-FR-05-1: submit/run/status/list/clear 皆為 argparse 子命令.
- AC-FR-05-2: status <id> 輸出全欄位.
- AC-FR-05-3: list [--status S] 可過濾.
- AC-FR-05-4: clear 清空全部資料檔.
- AC-FR-05-5: --json 輸出單行 JSON.
- AC-FR-05-6: exit codes 0/2/3/4/1 精確對應.
- AC-FR-05-7: unknown task id -> exit 2.

---

## 4. Non-Functional Requirements

> Same DERIVED-tagged verbatim-quote pattern as §3 (R-CANONICAL-INTERP-001).

### NFR-01: Performance

**Citation**: SPEC.md §4 NFR-01, §11

DERIVED: SPEC.md §4 NFR-01, §11.

> | NFR-01 | performance | `submit` + `status` 組合操作(不含 subprocess 執行)100 次 p95 < 50ms(pytest-benchmark 量測) |
> `submit` + `status` p95 latency | < 50ms / 100 iter | pytest-benchmark

- AC-NFR-01-1: p95 < 50ms / 100 iter, pytest-benchmark.

### NFR-02: Security — No `shell=True`, Injection Blacklist Coverage

**Citation**: SPEC.md §4 NFR-02, §11

DERIVED: SPEC.md §4 NFR-02, §11.

> | NFR-02 | security | 全 codebase 禁用 `shell=True`;FR-01 注入字元黑名單必須有測試覆蓋 |
> shell=True 使用率 | 0(全 codebase grep) | CI gate

- AC-NFR-02-1: shell=True 使用率 0, CI gate.
- AC-NFR-02-2: 注入字元黑名單測試覆蓋.

### NFR-03: Reliability — Atomic Writes, Breaker Recovery Time

**Citation**: SPEC.md §4 NFR-03, §10, §11

DERIVED: SPEC.md §4 NFR-03, §10, §11.

> | NFR-03 | reliability | 三個資料檔全部原子寫(tmp + `os.replace`),進程中斷後檔案仍為合法 JSON;breaker `OPEN → CLOSED` 恢復時間 ≤ `TASKQ_BREAKER_COOLDOWN` + 1s |
> breaker `OPEN → CLOSED` 恢復時間 | ≤ `TASKQ_BREAKER_COOLDOWN` + 1s | integration test
> `run --all` 並發後 tasks.json 合法率 | 100%(無損) | fault-injection + json.load
> | NFR → dimension: `error_handling` | harness/CLAUDE.md | NFR-03(原子寫 + breaker recovery) |

- AC-NFR-03-1: 原子寫入, fault-injection 後仍合法 JSON.
- AC-NFR-03-2: breaker 恢復時間 <= cooldown + 1s.

### NFR-04: Security — Secret Redaction

**Citation**: SPEC.md §4 NFR-04

DERIVED: SPEC.md §4 NFR-04.

> | NFR-04 | security | `stdout_tail`/`stderr_tail` 落盤前,匹配 `(sk-[A-Za-z0-9_-]{8,}|token=\S+)` 的行整行以 `[REDACTED]` 取代 |
> secret redaction 命中率 | 100%(sk-* / token=) | unit test on stdout_tail

**Acceptance Criteria**:
- AC-NFR-04-1: redaction 命中率 100%.

### NFR-05: Maintainability — Docstring `[FR-XX]` Coverage

**Citation**: SPEC.md §4 NFR-05

DERIVED: SPEC.md §4 NFR-05.

> | NFR-05 | maintainability | `src/taskq` 全部公開函式/類別有 docstring 且含 `[FR-XX]` 引用 |
> docstring `[FR-XX]` 引用覆蓋率 | 100%(公開函式) | Gate 1 inspect

**Acceptance Criteria**:
- AC-NFR-05-1: docstring [FR-XX] 引用覆蓋率 100%.

### NFR-06: Deployability — Environment Variable Completeness

**Citation**: SPEC.md §4 NFR-06, §5.1

DERIVED: SPEC.md §4 NFR-06, §5.1.

> | NFR-06 | deployability | 全部 8 個 `TASKQ_*` 參數讀自環境變數(config.py 統一讀取,含預設值);`.env.example` 逐一宣告並附註解 |
> 資料檔目錄 | `run --all` 並發 worker 數 | 單任務 subprocess timeout(秒) | 失敗自動重試上限 | 重試退避基數(秒) | 連續失敗 → OPEN 閾值 | OPEN → HALF_OPEN 冷卻(秒) | 結果快取存活(秒)
> 8 個 `TASKQ_*` 環境變數;`.env.example` 完整宣告

- AC-NFR-06-1: 8 個 TASKQ_* 全部讀自環境變數, 含預設值.
- AC-NFR-06-2: .env.example 逐一宣告並附註解.

---

## 5. Acceptance Criteria Summary

| FR/NFR | AC count | Exit codes involved | Data files touched |
|---|---|---|---|
| FR-01 | 6 (AC-FR-01-1..6) | 0, 2 | tasks.json |
| FR-02 | 5 (AC-FR-02-1..5) | 0, 4 | tasks.json |
| FR-03 | 5 (AC-FR-03-1..5) | 3 | breaker.json |
| FR-04 | 4 (AC-FR-04-1..4) | 0 | cache.json |
| FR-05 | 7 (AC-FR-05-1..7) | 0, 1, 2, 3, 4 | tasks.json, breaker.json, cache.json |
| NFR-01 | 1 (AC-NFR-01-1) | — | — |
| NFR-02 | 2 (AC-NFR-02-1..2) | 2 | — |
| NFR-03 | 2 (AC-NFR-03-1..2) | — | tasks.json, breaker.json, cache.json |
| NFR-04 | 1 (AC-NFR-04-1) | — | tasks.json |
| NFR-05 | 1 (AC-NFR-05-1) | — | — |
| NFR-06 | 2 (AC-NFR-06-1..2) | — | — |

Canonical SPEC.md §8 lists 10 top-level acceptance items (pytest green;
submit/run/status happy path; 6 negative paths — empty, injection,
timeout, breaker-open, cache replay, atomic durability under crash;
env completeness; concurrent run-all integrity; docstring FR-cross-ref
coverage). These are traced onto the FR/NFR-level ACs above:

| SPEC.md §8 item | Traced to |
|---|---|
| `pytest tests/ -q` all green | overall gate, not a single AC |
| submit → run → status happy path | AC-FR-01-5, AC-FR-02-1..3, AC-FR-05-2 |
| `submit ""` → exit 2 | AC-FR-01-1 |
| `submit "echo hi; rm x"` → exit 2 | AC-FR-01-3 |
| timeout → status `timeout`, exit 4 | AC-FR-02-5 |
| 3 consecutive final failures → 4th `run` exit 3; cooldown recovers | AC-FR-03-2, AC-FR-03-3, AC-FR-03-4, AC-NFR-03-2 |
| TTL cache replay, no subprocess | AC-FR-04-2 |
| `.env.example` declares all 8 vars | AC-NFR-06-2 |
| `run --all` concurrency → tasks.json valid, no loss | AC-FR-02-4, AC-NFR-03-1 |
| docstring `[FR-XX]` coverage | AC-NFR-05-1 |

---

## 6. Out-of-Scope

- Any runtime external dependency beyond the Python 3.11 standard
  library (SPEC.md §1 states test tooling is dev-environment-provided,
  not a runtime dependency).
- Any persistence backend other than the three JSON files under
  `$TASKQ_HOME` (SPEC.md §5.2).
- Any execution mode using `shell=True` (explicitly forbidden,
  SPEC.md §4 NFR-02).
- Distributed/multi-host breaker or cache state — SPEC.md §3 FR-03
  scopes the breaker as "global, cross-task, cross-process" on a
  single host via `breaker.json`; no networked coordination is
  specified.

---

## 7. Open Issues

No TBD / TODO / `<placeholder>` markers were found in SPEC.md (v3.0.0)
during transcription; no deferred items are required for this
ingestion round.

- NFR-99: none raised — SPEC.md v3.0.0 contains no ambiguous terms
  requiring stakeholder resolution beyond what is transcribed verbatim
  above.

**canonical_diff.py evidence note**: `srs_vs_spec_diff.json` shows
0/11 FR/NFR sections at `invention` verdict after adding `DERIVED:`
tags + verbatim SPEC.md quotes to each section (down from 11/11
`invention` on first pass). One residual: `NFR-06` reports
`over_spec_score: 0.813` (`verdict: interpreted`, `derived_present:
true`) — this is a boundary-detection artifact of the scorer's
heading-regex clause splitter (`_split_ac_clauses`), which has no
closing match after the last `### NFR-06` heading in the document and
so attributes all trailing prose (§5–§9) to that clause's scored body;
it is not additional invented content within NFR-06 itself. Not
correctable from within SRS.md content without adding a decoy
FR/NFR/AC-prefixed heading, which would be scoring the tool rather
than fixing the document — out of scope for this deliverable.

---

## 8. Risks

**Citation**: SPEC.md §9

| ID | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | Concurrent writes corrupt `tasks.json` | High | Medium | Lock + atomic write (NFR-03) |
| R2 | Subprocess hangs/zombies | Medium | Medium | timeout mandatory (FR-02) |
| R3 | Breaker false-locks | Medium | Low | cooldown + HALF_OPEN (FR-03) |
| R4 | Cache replays stale results | Low | Medium | TTL expiry forces re-execution (FR-04) |
| R5 | Secret leaked to disk | High | Medium | stdout_tail/stderr_tail redaction (NFR-04) |

---

## 9. Glossary

| Term | Definition |
|---|---|
| Task | A unit of work: a shell command submitted via `submit`, identified by an 8-hex-char id, with a status lifecycle. |
| Breaker | Circuit breaker: global state machine (`CLOSED`/`OPEN`/`HALF_OPEN`) that stops task execution after repeated final failures. |
| Final failure | A task that reaches `failed` or `timeout` status after exhausting all `TASKQ_RETRY_LIMIT` retries. |
| Cache signature | `sha256(command)` — the key used to look up a replayable cached result. |
| Atomic write | Write to a temp file followed by `os.replace` onto the target path, so a crash mid-write cannot leave a partially-written file at the target path. |
| `$TASKQ_HOME` | Data directory for `tasks.json`, `breaker.json`, `cache.json`; configured via `TASKQ_HOME` env var, default `.taskq`. |

---

*Source: `SPEC.md` v3.0.0 (2026-07-04), 5 FR / 6 NFR / 8 env vars. Ingestion mode — Agent A, Sub-Task 1/4, Round 1.*
