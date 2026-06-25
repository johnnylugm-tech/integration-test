# Configuration Records

> **Project**: integration-test (taskq)
> **Version**: 1.0.0
> **Generated**: 2026-06-25
> **Phase**: 8 — Configuration Author
> **Source SPEC**: `SPEC.md` §4.4, §6, §10 (deployability / NFR-06)
> **Cross-references**: `.env.example`, `03-development/src/taskq/config.py`, `RELEASE_NOTES.md`, `07-risk/RISK_REGISTER.md`

---

## 1. Purpose

This document is the authoritative inventory of every runtime configuration surface for `taskq` v1.0.0. Per NFR-06, **all** runtime configuration is read from the 8 `TASKQ_*` environment variables centralised in `taskq.config`; this file enumerates them, their semantics, defaults, ownership, and the environments in which they apply.

**Scope rule:** `taskq` has zero third-party runtime dependencies (stdlib only — R19 in `07-risk/RISK_REGISTER.md`). Therefore there are **no package-internal secrets, API keys, feature flags, or external service credentials** to manage. The configuration surface is exclusively the 8 `TASKQ_*` env vars plus the persistent state files in `$TASKQ_HOME`.

---

## 2. Environment Variables (TASKQ_*)

All 8 variables are declared in `.env.example` (single source of truth for sample values), parsed in `taskq/config.py::_parse_env` (NFR-06), and validated by `taskq/config.py::validate_config`. Each call site reads them via `Config` dataclass fields populated once per process.

| # | Name | Type | Default | Range / Constraint | Access Method | Owner | Env (dev / staging / prod) |
|---|------|------|---------|--------------------|---------------|-------|----------------------------|
| 1 | `TASKQ_HOME` | str | `.taskq` | Writable directory path; created on first read (`os.makedirs(..., exist_ok=True)`) | `Config.home` (used by `store`, `cache`, `breaker`) | Release Engineering | dev, staging, prod |
| 2 | `TASKQ_MAX_WORKERS` | int | `4` | `>= 1` (validate_config) | `Config.max_workers` (used by `executor.run_all` → `ThreadPoolExecutor(max_workers=...)`) | Release Engineering | dev, staging, prod |
| 3 | `TASKQ_TASK_TIMEOUT` | float (seconds) | `10.0` | `> 0` (validate_config) | `Config.task_timeout` (used by `executor.run_task` → `subprocess.run(..., timeout=cfg.task_timeout)`) | Release Engineering | dev, staging, prod |
| 4 | `TASKQ_RETRY_LIMIT` | int | `2` | `>= 0` (validate_config); 0 = no retries | `Config.retry_limit` (used by `executor.run_task` retry loop bound) | Release Engineering | dev, staging, prod |
| 5 | `TASKQ_BACKOFF_BASE` | float (seconds) | `0.1` | `> 0` (validate_config); sleep = `base * 2^retry_n` | `Config.backoff_base` (used by `executor.run_task`) | Release Engineering | dev, staging, prod |
| 6 | `TASKQ_BREAKER_THRESHOLD` | int | `3` | `>= 1` (validate_config); consecutive final failures to OPEN | `Config.breaker_threshold` (used by `breaker.Breaker.record_failure`) | Release Engineering | dev, staging, prod |
| 7 | `TASKQ_BREAKER_COOLDOWN` | float (seconds) | `5.0` | `> 0` (validate_config); OPEN → HALF_OPEN after cooldown | `Config.breaker_cooldown` (used by `breaker.Breaker.get_current_state`) | Release Engineering | dev, staging, prod |
| 8 | `TASKQ_CACHE_TTL` | float (seconds) | `3600` | `> 0` (validate_config); cache entry expires after TTL | `Config.cache_ttl` (used by `cache.lookup`) | Release Engineering | dev, staging, prod |

**Access method (programmatic):**
```python
from taskq.config import get_config
cfg = get_config()        # singleton; cached after first call (see §5)
cfg.max_workers            # int
cfg.task_timeout           # float
# ...
```

**Cross-reference:** all 8 fields are defined in `03-development/src/taskq/config.py` (`Config` dataclass, lines 14–29) and validated by `validate_config` (lines 49–70). No other module in `03-development/src/taskq/` calls `os.environ` directly — NFR-06 enforcement is grep-verifiable.

---

## 3. Persistent State Files (in $TASKQ_HOME)

| File | Module | Atomic? | Concurrency | Purpose |
|------|--------|---------|-------------|---------|
| `tasks.json` | `taskq.store` | Yes (`atomic_write` / tmp + `os.replace`) | `threading.Lock` | Persisted task records (FR-01, FR-02) |
| `breaker.json` | `taskq.breaker` | Yes (`atomic_write`) | Module-level `_LOCK` | Circuit-breaker FSM + counter + `opened_at` (FR-03) |
| `cache.json` | `taskq.cache` | Yes (`atomic_write`) | Module-level `_LOCK` | SHA-256(command) keyed result cache (FR-04) |

All three are guarded by architecture constraint `atomic_writes_only`. Secret redaction (`sk-*`, `token=*`) is applied to `stdout_tail` / `stderr_tail` before write (NFR-04, `_REDACT_PATTERN` in `store.py:24`).

**Clearing:** `python -m taskq clear` removes all three if present (`cli.cmd_clear`, `cli.py:177-190`).

---

## 4. Secrets / API Keys / Tokens / Feature Flags

| Category | Status | Evidence |
|----------|--------|----------|
| External API keys | None — taskq is stdlib-only and runs local subprocesses; no network calls | `R19` in `07-risk/RISK_REGISTER.md` |
| Database credentials | None — flat-file JSON storage in `$TASKQ_HOME` | SPEC §1 |
| Auth tokens | None — no authentication surface | SPEC §1 |
| Feature flags | None — single-binary CLI with stable subcommand set (`submit` / `run` / `status` / `list` / `clear`) | `cli._dispatch_subcommand` (cli.py:224-239) |
| Runtime toggles | None — all behaviour is controlled by the 8 `TASKQ_*` env vars above | NFR-06 |

**Secret handling:** the only secret-adjacent code path is **outbound redaction** — `taskq.store._redact` replaces any line matching `sk-[A-Za-z0-9_-]{8,}` or `token=\S+` with `[REDACTED]` before persistence (NFR-04). This is **defensive**, not configuration. Pattern is spec-pinned verbatim and verified by `test_fr04` regression tests.

**gitleaks:** clean (`.secrets.baseline` present; `gitleaks detect --source .` returns 0 leaks).

---

## 5. Caching & Invalidation Rules

`taskq.config.get_config()` is a **process-wide singleton** with the following cache-invalidation rule (line 42-46 of `config.py`):

- Cache invalidates **only** when `TASKQ_HOME` changes value (rare in production — local CLI is one-shot).
- Other `TASKQ_*` changes within the same process are **not** picked up after first read.

This is documented as Risk `R10` in `07-risk/RISK_REGISTER.md` (LOW, score 2) and refuted for the product's one-shot CLI usage. Future multi-call consumers would need an explicit `invalidate_config()` helper; not required for v1.0.0.

---

## 6. Environment Matrix

| Env | Recommended values (relative to defaults) | Notes |
|-----|--------------------------------------------|-------|
| **dev** | All defaults (`TASKQ_HOME=.taskq`, `MAX_WORKERS=4`, etc.) | Local machine; `.taskq` dir is gitignored |
| **staging** | `TASKQ_HOME=/var/lib/taskq/staging`; `TASKQ_MAX_WORKERS=8`; `TASKQ_CACHE_TTL=600` (10 min, more aggressive refresh) | Isolated dir per environment to avoid cross-pollution |
| **prod** | `TASKQ_HOME=/var/lib/taskq/prod`; `TASKQ_MAX_WORKERS` tuned to host CPU; `TASKQ_RETRY_LIMIT=3`; `TASKQ_BREAKER_THRESHOLD=5`; `TASKQ_BREAKER_COOLDOWN=30.0`; `TASKQ_CACHE_TTL=3600` | All paths absolute, non-default home, rotation-friendly |

> Production-specific tuning rationale: larger `BREAKER_THRESHOLD` + `BREAKER_COOLDOWN` reduces false-open risk under load (R3); higher `RETRY_LIMIT` accommodates transient subprocess failures; absolute `TASKQ_HOME` allows backup/restore via standard filesystem tooling.

---

## 7. Per-Module Configuration Map

| Module | Reads from `Config` | Reads from `os.environ` directly |
|--------|---------------------|----------------------------------|
| `taskq.config` | (defines it) | **YES — sole reader (NFR-06)** |
| `taskq.cli` | `cfg` (passed in) | No |
| `taskq.store` | `cfg.home`, `validate_config` | No |
| `taskq.cache` | `cfg.home`, `cfg.cache_ttl`, `validate_config` | No |
| `taskq.breaker` | `cfg.home`, `cfg.breaker_threshold`, `cfg.breaker_cooldown` | No |
| `taskq.executor` | `cfg.task_timeout`, `cfg.retry_limit`, `cfg.backoff_base`, `cfg.max_workers`, `validate_config` | No |
| `taskq.parser` | none | No |
| `taskq.models` | none | No |
| `taskq.injection_guard` | none | No |

This table is the **NFR-06 invariant** — verified by `grep -r "os.environ" 03-development/src/` returning hits only in `taskq.config`.

---

## 8. Validation

- **Defaults match `.env.example`**: PASS (8/8 lines identical to `Config` dataclass defaults).
- **validate_config ranges**: PASS (all 7 numeric fields checked; 0/0 sentinel = invalid).
- **NFR-06 sole-reader invariant**: PASS (grep-verified; `taskq.config` is the only `os.environ` reader).
- **No orphan / dead config**: PASS (8 vars declared, 8 read in `_parse_env`, 8 fields in `Config`).
- **Atomic writes on 3 state files**: PASS (`atomic_writes_only` architecture constraint).
- **gitleaks clean**: PASS (`.secrets.baseline` present, no leaks).
- **No third-party deps**: PASS (`R19` in risk register; `pip check` would only validate stdlib).

---

## 9. Cross-References

| Topic | File |
|-------|------|
| All 8 env var sample values | `.env.example` |
| Centralised reader + validator | `03-development/src/taskq/config.py` |
| Per-FR env var usage | `03-development/src/taskq/{store,cache,breaker,executor,cli}.py` |
| Risk R10 (config-cache staleness) | `07-risk/RISK_REGISTER.md` §2 |
| NFR-06 (deployability) verification | `05-verification/VERIFICATION_REPORT.md` |
| Release-level tunings | `RELEASE_NOTES.md` §8 + this file §6 |
| Release gates | `08-config/RELEASE_CHECKLIST.md` |

---

_Generated by P8 Configuration Author · 2026-06-25_
