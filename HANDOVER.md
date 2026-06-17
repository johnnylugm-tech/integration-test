# Harness Methodology — Session Handover

**Checkpoint**: `P4-entry-20260617`  
**Phase**: P4 — Testing  
**Generated**: 2026-06-17T20:17:22Z

> ⚠️  **開始下一個工作階段前，請先執行 `/compact` 壓縮上下文**，再從「接下來的工作」繼續。

---

## ▶ 立即開始（兩步）

```bash
# 1. Clone (if working directory cleared)
git clone --recurse-submodules https://github.com/johnnylugm-tech/integration-test && cd integration-test

# 2. Read plan and continue Phase 4
cat .methodology/phase4_plan.md
# Follow the active plan and continue from where you left off
```

---

## 快速接手指令（詳細）

```bash
# Clone (--recurse-submodules required for harness submodule)
git clone --recurse-submodules https://github.com/johnnylugm-tech/integration-test /tmp/integration-test && cd /tmp/integration-test

# Confirm latest commits
git log --oneline -3

# Confirm FSM state
cat .methodology/state.json   # expected: phase=4 state=RUNNING

# Read active plan
cat .methodology/phase4_plan.md
```

| 欄位 | 值 |
|------|----|
| Remote | `https://github.com/johnnylugm-tech/integration-test` |
| Branch | `main` |
| State | `phase=4 state=RUNNING` |
| Plan | `.methodology/phase4_plan.md` |

---

## 任務背景

Phase 3 complete (0/1 FRs Gate 1 PASS). Gate None. Advancing to Phase 4.

## 目前執行狀況

Phase 3: 0/1 FRs Gate 1 PASS. Gate None — quality_complete. Ready to begin Phase 4.

## 接下來的工作

1. Follow SKILL.md §0.1 Phase 4 entry checklist
2. Read the Phase 4 plan and execute

## 注意事項

- 100% follow SKILL.md
- Do NOT commit `.sessi-work/` or `.methodology/` runtime artifacts
- Git failures are warnings — they never block the pipeline

---
*由 `HandoverGenerator` 自動生成。下次 push 時此檔案將被覆寫。*
