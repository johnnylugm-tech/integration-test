"""[FR-01] taskq — 任務提交與驗證 (task submission and verification).

Citations:
  SPEC §3 FR-01 (validation rules + acceptance criteria).
  SAD §2.2, §3.1 (FR-01 module: cli.submit + store.add).
  ADR-002 (storage layout), ADR-011 (id format = uuid4 hex prefix 8).
"""

__all__ = ["cli"]