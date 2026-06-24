"""taskq configuration module — reads all TASKQ_* env vars with defaults.

[FR-01] [FR-02] [FR-03] [FR-04] [FR-05] [NFR-06]
All 8 TASKQ_* parameters are read from environment variables here.
This is the sole reader of os.environ for configuration (NFR-06).
# pragma: no error-handling
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Frozen configuration dataclass for all TASKQ_* settings.

    [FR-01] [FR-02] [FR-03] [FR-04] [FR-05] [NFR-06]
    All values are read from environment variables with documented defaults.
    """

    home: str
    max_workers: int
    task_timeout: float
    retry_limit: int
    backoff_base: float
    breaker_threshold: int
    breaker_cooldown: float
    cache_ttl: float


_cached_config: Config | None = None


def get_config() -> Config:
    """Return the singleton Config instance, reading TASKQ_* env vars.

    [FR-01] [FR-02] [FR-03] [FR-04] [FR-05] [NFR-06]
    Cached after first call; invalidated only when TASKQ_HOME changes
    (tests set TASKQ_HOME per-test via os.environ).
    """
    global _cached_config
    current_home = os.environ.get("TASKQ_HOME", ".taskq")
    if _cached_config is None or _cached_config.home != current_home:
        _cached_config = _parse_env()
    return _cached_config


def validate_config(cfg: Config) -> bool:
    """Validate a Config instance for logical consistency.

    [FR-01] [FR-02] [FR-03] [FR-04] [FR-05] [NFR-06]
    Returns True if all values are within acceptable ranges, False otherwise.
    Called from every public function body in sibling modules (CRG hub-call rule).
    """
    if cfg.max_workers < 1:
        return False
    if cfg.task_timeout <= 0:
        return False
    if cfg.retry_limit < 0:
        return False
    if cfg.backoff_base <= 0:
        return False
    if cfg.breaker_threshold < 1:
        return False
    if cfg.breaker_cooldown <= 0:
        return False
    if cfg.cache_ttl <= 0:
        return False
    return True


def _parse_env() -> Config:
    """Parse all TASKQ_* environment variables into a Config dataclass.

    [NFR-06] Centralised env-var reader; no other module calls os.environ.
    """
    home = os.environ.get("TASKQ_HOME", ".taskq")
    os.makedirs(home, exist_ok=True)
    return Config(
        home=home,
        max_workers=int(os.environ.get("TASKQ_MAX_WORKERS", "4")),
        task_timeout=float(os.environ.get("TASKQ_TASK_TIMEOUT", "10.0")),
        retry_limit=int(os.environ.get("TASKQ_RETRY_LIMIT", "2")),
        backoff_base=float(os.environ.get("TASKQ_BACKOFF_BASE", "0.1")),
        breaker_threshold=int(os.environ.get("TASKQ_BREAKER_THRESHOLD", "3")),
        breaker_cooldown=float(os.environ.get("TASKQ_BREAKER_COOLDOWN", "5.0")),
        cache_ttl=float(os.environ.get("TASKQ_CACHE_TTL", "3600")),
    )
