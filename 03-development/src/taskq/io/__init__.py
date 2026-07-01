"""[FR-01] taskq.io subpackage — persistence layer (atomic JSON store).

Citations:
- SPEC.md §3 FR-01 (tasks.json atomic write via tmp + os.replace)
- SPEC.md §3 FR-01 corruption clause (exit 1 + stderr "store corrupted")
"""
