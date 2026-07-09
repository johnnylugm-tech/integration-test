"""taskq — task queue CLI (FR-01..FR-05 + NFR-01..NFR-06).

Citations:
- SPEC.md §3 FR-01 (lines 55-72): task submission + 4-rule validation
- SPEC.md §3 FR-02 (lines 74-83): task executor + state machine
- SPEC.md §3 FR-03 (lines 85-93): retry + circuit breaker
- SPEC.md §3 FR-04 (lines 96-99): cache layer
- SPEC.md §3 FR-05 (lines 104-112): CLI surface (submit/run/status/list/clear)
"""