"""taskq.cli — argparse front-end for the taskq runtime.

[FR-03] Citations:
- SPEC.md §3 FR-03 子命令表 — submit / run / status / list / clear.
- SPEC.md §3 FR-03 全域 flag --json — 單行 JSON, stdout 不可含換行.
- SPEC.md §3 FR-03 Exit codes — 0 成功 / 2 驗證 / 4 timeout / 1 內部.
"""