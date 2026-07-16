# Architecture Decision Records (ADR) — taskq

> **Project**: `taskq`(本地任務佇列 CLI,Python 3.11 stdlib-only)
> **Source SSOT**: `02-architecture/SAD.md` Round 1(commit pending, 2026-07-17)
> **Upstream specification**: `01-requirements/SRS.md` Round 1 (LOCKED 2026-07-11) — 5 FR / 10 NFR / 8 env vars
> **Author**: Architect Agent A(Sub-Task 2/3 ADR)
> **Round**: 1
> **Python runtime**: 3.11.15(`.venv/bin/python` → python3.11;stdlib-only)

This document captures the load-bearing architectural decisions for `taskq`.
Each ADR follows the lightweight Context / Decision / Consequences / Alternatives
format. ADRs are append-only; superseded entries are marked, never deleted.

The decisions below are derived from the SRS specification (`01-requirements/SRS.md`)
and reference its requirement IDs directly. The forward traceability matrix (§0)
shows which SRS FR-IDs / NFR-IDs each ADR satisfies; the bidirectional counterpart
lives in `01-requirements/TRACEABILITY_MATRIX.md` §6 (downstream deliverable trace).

---

## 0. Forward Traceability Matrix — ADR → SRS FR/NFR

Every ADR owns at least one SRS requirement (no orphan decision). Each row
cites the SRS specification anchor (§3 = FR / §4 = NFR) and the AC verification
points so a reviewer can confirm traceability without re-reading the prose.

| ADR | Title (short) | SRS FR owned | SRS NFR owned | Verification AC anchor |
|-----|---------------|--------------|---------------|-------------------------|
| ADR-001 | stdlib-only Python 3.11 | — | NFR-05, NFR-06 | AC-NFR05-01/02, AC-NFR06-01/02 |
| ADR-002 | 8-module single-process | FR-01, FR-02, FR-03, FR-04, FR-05 | NFR-05 | AC-FR01-01, AC-FR05-01, AC-NFR05-02 |
| ADR-003 | `ThreadPoolExecutor` for `--all` | FR-02 | NFR-01, NFR-09 | AC-FR02-05/06, AC-NFR09-02/03 |
| ADR-004 | Atomic write (`tmp` + `os.replace`) | — | NFR-03, NFR-07, NFR-10 | AC-NFR03-01/03, AC-NFR07-01/02/03/04, AC-NFR10-02/05 |
| ADR-005 | Cross-process `flock` / `msvcrt` | — | NFR-08 | AC-NFR08-01/02/03 |
| ADR-006 | Circuit breaker state machine | FR-03 | NFR-03 | AC-FR03-04/05/06/07/08, AC-NFR03-02 |
| ADR-007 | TTL cache keyed by `sha256(command)` | FR-04 | NFR-03 | AC-FR04-01/02/03/04/05/06 |
| ADR-008 | `argparse` CLI surface | FR-05 | — | AC-FR05-01/02/03/04/05/06/07 |
| ADR-009 | Env-var freeze at startup | — | NFR-06 | AC-NFR06-01/02 |
| ADR-010 | Schema versioning + `migrate()` | — | NFR-10 | AC-NFR10-01/02/03/04/05 |
| ADR-011 | `shlex.split` + injection blacklist | FR-01, FR-02 | NFR-02 | AC-FR01-06/07, AC-FR02-07, AC-NFR02-01/02/03 |
| ADR-012 | Output redaction for secrets | FR-02 | NFR-04 | AC-NFR04-01/02/03/04 |
| ADR-013 | STRIDE-lite threat model | FR-01, FR-02, FR-05 | NFR-02, NFR-04 | AC-FR01-06/07, AC-NFR04-01/02/03/04 |
| ADR-014 | `--inject-fault` dev/test only | — | NFR-07 | AC-NFR07-01/02/03/04/05 |
| ADR-015 | No-circular-dependency layering | (cross-cutting) | NFR-05 | AC-NFR05-01/02 |

**Coverage check (against `01-requirements/SRS.md` §3/§4)**:

- Every FR (5/5: FR-01 … FR-05) appears in the matrix above (ADR-002/003/006/007/008/011/012/013).
- Every NFR (10/10: NFR-01 … NFR-10) appears in the matrix above (ADR-001/002/003/004/005/006/007/009/010/011/012/013/014/015).
- No orphan ADR — every row points to at least one SRS specification requirement.
- No orphan FR/NFR — every requirement has at least one ADR owner; the same conclusion
  is asserted in `01-requirements/TRACEABILITY_MATRIX.md` §7 (Coverage Validation).

The downstream deliverable trace (which Phase 4 / Phase 5 artifact verifies which
requirement) is documented in `01-requirements/TRACEABILITY_MATRIX.md` §6; this
ADR-side traceability complements it from the architectural-decision direction.

---

## Table of Contents

- ADR-001 — Python 3.11 stdlib-only runtime(no third-party deps)
- ADR-002 — Modular single-process multi-threaded architecture(8 modules)
- ADR-003 — `ThreadPoolExecutor` for `run --all` parallelism
- ADR-004 — Atomic write pattern(`tmp` + `os.replace`)
- ADR-005 — Cross-process file locking(`fcntl.flock` / `msvcrt.locking`)
- ADR-006 — Circuit breaker state machine(`CLOSED` / `OPEN` / `HALF_OPEN`)
- ADR-007 — TTL result cache keyed by `sha256(command)`
- ADR-008 — `argparse` CLI as the sole external interface
- ADR-009 — Environment-variable configuration frozen at startup
- ADR-010 — Schema versioning with `migrate()` and backup rotation
- ADR-011 — Subprocess execution: `shlex.split` + `shell=False` + injection blacklist
- ADR-012 — Output redaction for secrets(`sk-*`, `token=…`)
- ADR-013 — STRIDE-lite threat model with three trust boundaries
- ADR-014 — `--inject-fault` is dev/test only; production path hard-rejects
- ADR-015 — No-circular-dependency module layering

---

## ADR-001: Python 3.11 stdlib-only runtime

**Status**: Accepted

**Context**.
`taskq` is shipped as a local CLI that operators run on diverse hosts(NFR-06 deployability).
The runtime footprint must be predictable, auditable, and reproducible without
`pip install` at deployment time. SPEC §2 commits to "stdlib-only".

**Decision**.
- Target Python version: **3.11**(verified via `.venv/bin/python --version` → `Python 3.11.15`).
- Runtime imports are restricted to the standard library: `argparse`,
  `subprocess`, `shlex`, `json`, `os`, `threading`, `concurrent.futures`,
  `hashlib`, `fcntl` / `msvcrt`, `uuid`, `datetime`, `pathlib`, `dataclasses`.
- All third-party packages are **dev-only**(`pytest`, `pytest-cov`, `pytest-benchmark`,
  `mutmut`, `pyright`, `ruff`); production runtime contains none of them.

**Consequences**.
- (+) Zero-install deployment: drop the package, run `python -m taskq`.
- (+) Audit surface is the Python stdlib itself, not a transitive dep graph.
- (+) Reproducible across machines without `requirements.txt` drift.
- (−) Cannot lean on `httpx`, `pydantic`, `click`, `rich`, etc. — must hand-roll
  equivalent functionality(`shlex.split` instead of an argv parser,
  `dataclasses` instead of pydantic models).
- (−) Newer stdlib conveniences(3.12+ `tomllib`, 3.13 free-threading experiments)
  are unavailable.

**Alternatives considered**.
- *Click + Pydantic*: faster authoring, but introduces two runtime deps and
  licensing surface; rejected for NFR-06 deployability.
- *PyPy / MicroPython*: faster startup / smaller image but breaks stdlib
  assumptions(`fcntl` absent on MicroPython); rejected.
- *Rust rewrite with `pyo3` bindings*: irrelevant — defeats the "local CLI"
  ergonomics; rejected.

---

## ADR-002: Modular single-process multi-threaded architecture(8 modules)

**Status**: Accepted

**Context**.
SPEC §6 mandates a folder structure where every FR maps to ≥ 1 module and
every module owns ≤ 2 primary responsibilities(SAD §2). The system must
remain testable per FR and avoid the "god-module" failure mode.

**Decision**.
Eight modules under `src/taskq/`, each with a narrow public surface:

| Module | Public API | Owns |
|---|---|---|
| `cli` | `main / submit / run / status / list / clear` | argparse + exit codes |
| `executor` | `run_task / run_all / retry` | subprocess + state machine + redaction |
| `breaker` | `Breaker.before_run / record_* / state` | circuit breaker state machine |
| `cache` | `lookup / store` | TTL result cache |
| `store` | `add / get / list_ / update / clear` | tasks.json atomic I/O + locking |
| `models` | `Task / TaskStatus / BreakerState / CacheEntry` | pure data classes |
| `config` | `Config` properties | `TASKQ_*` env-var freeze |
| `__main__` | (none) | `from cli import main; sys.exit(main())` |

File count = 9(including `__init__.py`), well below the 15-file ceiling.

**Consequences**.
- (+) Each FR has a clear owner → test attribution is unambiguous.
- (+) `cli` is the only outward surface; everything else is module-private.
- (+) Refactoring a single module rarely cascades.
- (−) Slightly higher ceremony vs. a single `taskq.py`; accepted for
  testability(NFR-05) and FR ownership clarity.

**Alternatives considered**.
- *Single file*: violates SPEC §6 and NFR-05; rejected.
- *Plugin / entry-point architecture*: overkill for 5 subcommands; rejected.

---

## ADR-003: `ThreadPoolExecutor` for `run --all` parallelism

**Status**: Accepted

**Context**.
FR-02 requires `taskq run --all` to process every `pending` task. NFR-09
requires "1000-task benchmark p95 < 100 ms peak memory < 100 MB", and NFR-01
demands small per-task latency. A naïve sequential loop blocks on each
`subprocess.run` call's timeout.

**Decision**.
- `executor.run_all()` builds a `concurrent.futures.ThreadPoolExecutor` with
  `max_workers = config.max_workers`(`TASKQ_MAX_WORKERS`).
- Each task is submitted as a future that calls `run_task(task_id)`.
- Results are streamed back via `as_completed`; failures in one task do not
  cancel siblings.
- `store.list_()` returns a **streaming generator**(ADR-002 module boundary),
  so the queue is never fully materialized.

**Consequences**.
- (+) I/O-bound subprocess execution overlaps cleanly; CPU stays on the main
  thread for argparse + JSON I/O.
- (+) `max_workers` is the single tuning knob for host capacity.
- (−) Threads share GIL but subprocesses release it via `os.fork` /
  `subprocess.run` syscall; correct for our workload.
- (−) No inter-task coordination — each task is independent; rejected on
  grounds that SPEC does not require ordering or all-or-nothing semantics.

**Alternatives considered**.
- *`multiprocessing.Pool`*: bypasses GIL but adds pickle cost and breaks
  shared `store` state semantics without IPC re-wiring; rejected.
- *`asyncio` + `asyncio.subprocess`*: would force async refactor of the whole
  module graph and complicates `argparse`-driven CLI; rejected.
- *Sequential loop*: simplest, but blows NFR-09 budget; rejected.

---

## ADR-004: Atomic write pattern(`tmp` + `os.replace`)

**Status**: Accepted

**Context**.
NFR-03 reliability requires that `tasks.json`, `breaker.json`, and
`cache.json` survive mid-write interruption(`kill -9`, `OSError`, disk full).
A naïve `json.dump(open(path, 'w'))` leaves a half-written file that
silently corrupts on next startup.

**Decision**.
All three data files are written through a single helper:

```python
def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
```

- Write to `<file>.tmp` first, `fsync`, then `os.replace` (POSIX-atomic on
  same filesystem).
- On `OSError` / `disk-full` → leave `.tmp` in place, raise; `cli` exits 1
  (NFR-07 fail-fast).
- On startup, detect `.tmp` orphan → exit 1 + stderr; **never silently rebuild**.

**Consequences**.
- (+) Readers always see either the old file or the new file — no torn JSON.
- (+) Survives `kill -9` between `json.dump` and `os.replace` because the
  canonical file is untouched until the swap.
- (+) Single helper, used by `store`, `breaker`, `cache` — uniform behavior.
- (−) One extra file lives next to each data file (`.tmp`) during failure
  investigation; operator must understand the convention.

**Alternatives considered**.
- *`renameio` / `atomicwrites`*: third-party; violates ADR-001 stdlib-only.
- *SQLite (`WAL` mode)*: better concurrency guarantees but adds a native
  dep and a binary format operators cannot grep; rejected.
- *Write to a single file + offset journal*: huge complexity for a CLI; rejected.

---

## ADR-005: Cross-process file locking(`fcntl.flock` / `msvcrt.locking`)

**Status**: Accepted

**Context**.
NFR-08 requires concurrent processes running `taskq` to corrupt neither
`tasks.json` / `breaker.json` / `cache.json`. A single-process `threading.Lock`
protects in-process threads but two `python -m taskq` invocations remain a
race.

**Decision**.
- On POSIX: `fcntl.flock(fd, LOCK_EX)` for writers, `LOCK_SH` for readers;
  locked over the `json.dump` + `os.replace` window.
- On Windows: `msvcrt.locking(fd, LK_NBLCK, …)` analogue.
- Cross-platform helper lives in `store` and is reused by `breaker` and `cache`.
- Network filesystem heuristic: at startup, `store` runs `os.statvfs` /
  probe to detect NFS / CIFS. If detected → log WARNING to stderr and
  **degrade** to "atomic write only, no `flock`". Atomic write still
  prevents corruption within one process; concurrent processes on a network
  FS accept best-effort consistency.

**Consequences**.
- (+) Local FS: full cross-process safety, validated by the 4-process test.
- (+) Portable: same code path POSIX / Windows with platform guard.
- (+) Honest degradation on NFS: explicit WARNING rather than silent
  misbehavior.
- (−) NFS users see "no flock" — documented in README.

**Alternatives considered**.
- *`fcntl.fcntl(F_SETLK)` POSIX advisory locks*: portable but `fcntl` does not
  cover Windows; would still need `msvcrt`.
- *SQLite + WAL*: stronger guarantees but ADR-001 + operator-grep constraints;
  rejected.
- *Per-process PID lockfiles (`/run/taskq.lock`)*: race during PID death /
  reboot; rejected.

---

## ADR-006: Circuit breaker state machine(`CLOSED` / `OPEN` / `HALF_OPEN`)

**Status**: Accepted

**Context**.
FR-03 needs a global "stop the bleeding" mechanism when downstream
commands fail repeatedly. Without a breaker, a flapping target command
exhausts retry budget on every task and fills `tasks.json` with `failed`
entries.

**Decision**.
- `breaker.Breaker` implements the canonical three-state machine:
  - `CLOSED` (normal): pass through; count consecutive failures.
  - `OPEN` (tripped): reject all `run` calls with exit 3; auto-transition to
    `HALF_OPEN` after `TASKQ_BREAKER_COOLDOWN` seconds.
  - `HALF_OPEN` (probing): allow exactly one trial; success → `CLOSED`,
    failure → back to `OPEN`.
- Persist state in `breaker.json` (atomic write per ADR-004) so a process
  restart does not "forget" the trip.
- `executor.run_task` calls `breaker.before_run()` first; on rejection,
  task goes `failed` with reason `breaker_open`.

**Consequences**.
- (+) Downstream failures cannot multiply into a log-storm / disk-fill.
- (+) Cooldown is operator-visible (`TASKQ_BREAKER_COOLDOWN`).
- (+) State survives restart — no "forgot we were broken" footgun.
- (−) One extra JSON file to manage; mitigated by atomic-write helper.

**Alternatives considered**.
- *Per-task breaker*: lets one flapping command starve the rest; rejected.
- *In-memory only*: process restart resets state → users re-discover the
  failure; rejected per NFR-03.

---

## ADR-007: TTL result cache keyed by `sha256(command)`

**Status**: Accepted

**Context**.
FR-04 lets operators replay deterministic commands without re-running them.
The cache must be content-addressable (so re-running `ls /tmp` after re-run
of `ls /tmp` is a hit) and respect operator-set TTL.

**Decision**.
- `cache.Cache` stores entries keyed by `sha256(command.encode("utf-8")).hexdigest()`.
- Entry schema: `{"signature", "stdout_tail", "stderr_tail", "exit_code",
  "finished_at", "ttl_seconds"}`.
- `lookup(signature)` returns the cached `Task` if `now - finished_at ≤ ttl`,
  else `None`.
- Persisted in `cache.json` via atomic write (ADR-004) + flock (ADR-005).
- Triggered by `--cached` flag on `taskq run <id>`; otherwise bypass.

**Consequences**.
- (+) Determinism is enforced by the key (not by `task_id`, which is per-run).
- (+) Operators tune freshness with `TASKQ_CACHE_TTL`.
- (+) Cache survives restart; same hit semantics on cold start.
- (−) Argument that "different args should not collide" is **out of scope** —
  the cache is per-`command` string, not per-args; documented behavior.

**Alternatives considered**.
- *Cache key by `(command, env_hash, cwd)`*: stronger but env is unbounded;
  rejected for ADR-001 simplicity.
- *LRU eviction*: adds bookkeeping; rejected — TTL alone is sufficient for
  a CLI.

---

## ADR-008: `argparse` CLI as the sole external interface

**Status**: Accepted

**Context**.
The system must be operable by humans and scripts alike, with stable exit
codes (SPEC §7) and `--json` output for automation.

**Decision**.
- `cli.main(argv=None)` is the only entry point; called by `__main__.py` via
  `sys.exit(main())`.
- Five subcommands: `submit / run / status / list / clear`.
- Global `--json` flag switches stdout shape for every subcommand.
- Exit codes are pinned: `0` success / `2` validation / `3` breaker / `4`
  timeout / `1` internal error.
- `--inject-fault=<scenario>` is recognized at the argparse layer but
  hard-rejected outside dev/test (ADR-014).

**Consequences**.
- (+) Single surface — every code path is reachable from `cli` and only
  `cli`; easier to test and to write `--inject-fault` against.
- (+) Exit codes map cleanly to shell scripting.
- (−) `argparse` is verbose; rejected temptation to wrap in a 3rd-party
  parser per ADR-001.

**Alternatives considered**.
- *Subcommand dispatch table + hand-rolled parser*: more code than argparse;
  rejected.
- *Click / Typer*: ADR-001 forbids runtime deps; rejected.

---

## ADR-009: Environment-variable configuration frozen at startup

**Status**: Accepted

**Context**.
NFR-06 requires 8 `TASKQ_*` variables to configure timeouts, retry limits,
breaker thresholds, cache TTL, parallelism, and `$TASKQ_HOME`. Operators
expect "what I set at start is what I get throughout the run".

**Decision**.
- `config.Config` reads every `TASKQ_*` variable **exactly once** in
  `__init__`, parses types, applies defaults, and freezes the result.
- Subsequent `os.environ` mutations are **ignored** for the lifetime of the
  process.
- `.env.example` enumerates the 8 vars with documented defaults — the
  configuration contract.

**Consequences**.
- (+) No "halfway-through a `run --all` did someone change
  `TASKQ_TASK_TIMEOUT`?" races.
- (+) A single `Config` object is the only place to look up tunables.
- (−) Long-running processes cannot live-reload config; accepted —
  `taskq` runs are short-lived by design.

**Alternatives considered**.
- *Per-call env-var lookup*: race-prone; rejected.
- *YAML / TOML config file*: ADR-001 stdlib-only + `tomllib` is 3.11+ but
  adds a deployment artifact; rejected.

---

## ADR-010: Schema versioning with `migrate()` and backup rotation

**Status**: Accepted

**Context**.
NFR-10 evolvability requires the three JSON files to evolve without forcing
operators to delete state on upgrade.

**Decision**.
- Every data file has root shape `{"version": N, ...}`.
- On read, the module runs `migrate(data)`:
  - `data["version"] < EXPECTED` → upgrade in-memory, **write back atomically**,
    and back up the prior file as `<file>.v<n>.bak`.
  - `data["version"] > EXPECTED` → raise `version_too_new` → `cli` exits 1.
- `migrate` failure leaves the `.bak` in place and raises; never silently
  overwrites the prior version.
- Test fixture: a v0 file (no `version` key) loads as v1 after migration
  with a `.v0.bak` next to it.

**Consequences**.
- (+) Operators upgrade by simply running the new binary; no manual steps.
- (+) Downgrade is blocked loudly — no silent "I downgraded and now data
  is unparseable" mystery.
- (+) `.bak` chain provides a forensic trail.
- (−) Migration code path must be tested for every released version;
  mitigated by fixture-based migration tests.

**Alternatives considered**.
- *No version field*: simplest, but every future shape change is a
  breaking change; rejected.
- *Auto-rebuild on parse error*: violates NFR-07 fail-fast; rejected.

---

## ADR-011: Subprocess execution — `shlex.split` + `shell=False` + injection blacklist

**Status**: Accepted

**Context**.
NFR-02 security requires that operators cannot (1) coerce `taskq` into
running a shell-string with metacharacter injection, and (2) that a
developer never accidentally reintroduces `shell=True`.

**Decision**.
- `executor.run_task` always invokes
  `subprocess.run(shlex.split(command), shell=False, capture_output=True,
  text=True, timeout=…)`.
- `cli.submit` rejects commands containing any of `;`, `|`, `&`, `$`, `>`,
  `<`, `` ` `` (exit code 2) BEFORE writing to `store`.
- CI gate: `grep -rE "shell\s*=\s*True" src/` MUST return empty.
- `shlex.split` keeps the call vector the same on every shell that ships on
  POSIX (no `/bin/sh -c` ever runs).

**Consequences**.
- (+) Injection surface is closed at both ends (parser + runtime).
- (+) CI gate makes regressions visible at PR time.
- (+) Blacklist is a short, testable set.
- (−) Whitelist would be safer but blocks legitimate pipes; rejected for
  operator ergonomics — a `pipe` is exactly the kind of "local task" that
  fits `taskq`'s scope. Documented in SPEC §3.

**Alternatives considered**.
- *Pure whitelist (alnum + space + `/` + `-`)*: too restrictive; rejected.
- *Sandboxing via `setuid` / container*: out of scope for a CLI; rejected.

---

## ADR-012: Output redaction for secrets(`sk-*`, `token=…`)

**Status**: Accepted

**Context**.
NFR-04 information disclosure requires that stdout/stderr captured by
`subprocess.run` and persisted into `tasks.json` does not leak API keys or
session tokens.

**Decision**.
- After `subprocess.run` returns, `executor.run_task` runs a regex over
  `stdout_tail` and `stderr_tail`:
  `(sk-[A-Za-z0-9_-]{8,}|token=\S+)`.
- Matching lines are replaced whole-line with `[REDACTED]` **before**
  atomic write to `tasks.json`.
- The redaction step is mandatory and unconditional — no opt-out.

**Consequences**.
- (+) Persistent state can be safely tailed by an operator or shipped to
  logs without leaking secrets.
- (+) Regex is a focused, reviewable 2-pattern union.
- (−) False-positive risk if a legitimate command happens to print a string
  matching `sk-…` — accepted because such commands are themselves rare and
  the operator can rerun with a stripped token.

**Alternatives considered**.
- *Always redact whole stdout / stderr*: loses debuggability; rejected.
- *Operator-supplied redaction rules*: leaks complexity to ops; rejected for
  ADR-001 simplicity.

---

## ADR-013: STRIDE-lite threat model with three trust boundaries

**Status**: Accepted

**Context**.
SAD §6 enumerates 7 threats across 3 trust boundaries. The threat model is
the contract that downstream testing (Gate 1 / Gate 4) verifies against.

**Decision**.
Three trust boundaries, each with ≥ 1 STRIDE-lite threat:

| Boundary | ID | Owner module |
|---|---|---|
| User CLI argv | TB-01 | `cli` |
| Subprocess execution | TB-02 | `executor` |
| `$TASKQ_HOME` persistence | TB-03 | `store` / `breaker` / `cache` |

Every threat has `owner_module` (a module from ADR-002), `nfr` (from SPEC §4),
and `verified_by` (a test name). No unowned threat, no threat whose
`nfr` is not in SPEC.

**Consequences**.
- (+) Test attribution is mechanical: every `verified_by` becomes a Gate 1
  test name.
- (+) Coverage matrix `Module × NFR` (SAD §4.1) makes gaps visible.
- (+) Adding a future threat means adding a row, not editing prose.
- (−) Requires maintenance discipline — every new feature must update the
  threat model; mitigated by the Gate 4 inspect dimension.

**Alternatives considered**.
- *Full STRIDE per boundary*: overshoots the scope of a local CLI; rejected.
- *No threat model*: rejected by Gate 4 spec-coverage dimension.

---

## ADR-014: `--inject-fault` is dev/test only; production path hard-rejects

**Status**: Accepted

**Context**.
NFR-07 resilience demands fault-injection testing of mid-write corruption,
disk-full, kill-9 scenarios. The same mechanism must never be reachable in
production (would be a denial-of-service knob).

**Decision**.
- `--inject-fault=<scenario>` is parsed by `argparse` and accepted only when
  `TASKQ_ENV ∈ {"dev", "test"}`.
- Production startup (`TASKQ_ENV` unset or "prod") detects the flag at `cli`
  level and exits with code 2 + stderr before any other work.
- Test scenarios are enumerated in `tests/` (P3 scope) and mirror the NFR-07
  injection matrix.

**Consequences**.
- (+) Chaos engineering is first-class, gated by env var, not by a hidden
  flag.
- (+) An attacker reaching the binary cannot trivially flip state via
  `--inject-fault`.
- (−) Tests must set `TASKQ_ENV=test` — documented in test bootstrap.

**Alternatives considered**.
- *No fault injection*: NFR-07 cannot be verified; rejected.
- *Always-on fault flag behind build flag*: makes tests brittle across
  branches; rejected.

---

## ADR-015: No-circular-dependency module layering

**Status**: Accepted

**Context**.
ADR-002 already enumerates 8 modules. The dependency direction must be
enforced to keep the layering legible and the test surface small.

**Decision**.
SAD §2.4 fixes the directed graph:

```
__main__ → cli → executor → store → config / models
                       ├──▶ breaker ──┘
                       └──▶ cache ────┘
         cli → store / breaker / cache / config / models
```

- `models` and `config` are leaf nodes (no business imports).
- `store`, `breaker`, `cache` share only `config` / `models`; never depend
  on each other.
- `executor` is the only module that depends on all three storage modules.
- `cli` depends on everything except `__main__`.
- CI gate: `pyright` or `import-linter` enforces the boundary.

**Consequences**.
- (+) Each module is unit-testable in isolation (inject fakes for the two
  storage neighbors it needs).
- (+) Refactors of `breaker` cannot ripple into `cache` and vice versa.
- (−) Forces some duplication of small helpers (`atomic_write_json` exists
  in `store` and is reused, not re-implemented); accepted.

**Alternatives considered**.
- *Flat module graph with no layering*: refactor danger; rejected.
- *Event bus / pub-sub*: heavy infrastructure for 5 subcommands; rejected.

---

*Document version: ADR Round 1 | 2026-07-17 | Source SSOT: `SAD.md` Round 1 (2026-07-17)*