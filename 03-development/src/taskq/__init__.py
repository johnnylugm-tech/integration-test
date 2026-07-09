"""taskq — task queue CLI (FR-01..FR-05 + NFR-01..NFR-06).

This package exposes the modules required by SPEC.md §3 + SAD.md §2.1:
  - [FR-01] task submission + 4-rule validation (cli + store + models + config)
  - [FR-02] task executor + state machine
  - [FR-03] retry + circuit breaker
  - [FR-04] TTL cache layer
  - [FR-05] full CLI surface (submit/run/status/list/clear)

Citations:
- SPEC.md §3 FR-01 (lines 55-72): task submission + 4-rule validation
- SPEC.md §3 FR-02 (lines 74-83): task executor + state machine
- SPEC.md §3 FR-03 (lines 85-93): retry + circuit breaker
- SPEC.md §3 FR-04 (lines 96-99): cache layer
- SPEC.md §3 FR-05 (lines 104-112): CLI surface (submit/run/status/list/clear)
"""