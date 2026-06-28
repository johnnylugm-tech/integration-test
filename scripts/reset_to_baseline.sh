#!/usr/bin/env bash
# reset_to_baseline.sh
#
# Purpose: from a baseline-v5 (or baseline-v5-clean) checkout, remove all
# Phase 1~3 artifacts and reset harness state so that the 8 phase workflow
# JS files can be re-run from a clean slate.
#
# Use case: verify harness-methodology health by re-running the full
# 8-phase workflow stack against a known-good workflow JS baseline.
#
# Usage:
#   git checkout baseline-v5-clean
#   bash scripts/reset_to_baseline.sh
#
# What it removes (Phase 1~3 deliverables + state):
#   - Phase 1: 01-requirements/, Phase1_STAGE_PASS.md
#   - Phase 2: 02-architecture/, Phase2_STAGE_PASS.md
#   - Phase 3: 03-development/, Phase3_STAGE_PASS.md
#   - All .methodology/agent_b_approvals/*.json
#   - All .methodology/decision_logs/
#   - Phase 3 gate/process artifacts (gate1_result, gate2_result,
#     gate_timestamps, gap_report, quality_manifest, fr_progress,
#     sessions_spawn.log, .gate1_scores.json, effort_metrics.db,
#     improvement-proposal-2026-06-27.md)
#   - State: .methodology/state.json
#   - Trace: .harness/traces/agent_trajectory.jsonl
#
# What it KEEPS (harness config + workflow JS):
#   - .claude/workflows/*.js (8 phase workflow JS — the test subject)
#   - harness/ submodule + harness_cli.py + setup.cfg + .gitignore
#   - CLAUDE.md + HANDOVER.md
#   - .methodology/SAB.json
#   - .methodology/phase{1..8}_plan.md
#   - .methodology/plan_status.md
#   - .methodology/audit/workflow_audit_2026-06-26.md
#   - .methodology/workflow-playbook.md
#   - .methodology/trace/attestation.json
#   - 00-summary/ (will be empty after cleanup)

set -euo pipefail

removed=0
log_remove() {
  for path in "$@"; do
    if [ -e "$path" ]; then
      rm -rf "$path"
      echo "  removed: $path"
      removed=$((removed + 1))
    fi
  done
}

echo "============================================================"
echo " reset_to_baseline.sh — Phase 1~3 artifact removal"
echo "============================================================"

echo ""
echo "[Phase 1] deliverables"
log_remove 01-requirements/
log_remove 00-summary/Phase1_STAGE_PASS.md

echo ""
echo "[Phase 2] deliverables"
log_remove 02-architecture/
log_remove 00-summary/Phase2_STAGE_PASS.md

echo ""
echo "[Phase 3] deliverables"
log_remove 03-development/
log_remove 00-summary/Phase3_STAGE_PASS.md

echo ""
echo "[Agent B approvals] (Phase 1~3 deliverable review records)"
log_remove .methodology/agent_b_approvals/

echo ""
echo "[Phase 3] gate / process artifacts"
log_remove .methodology/decision_logs/
log_remove .methodology/fr_progress.json
log_remove .methodology/gate1_result.json
log_remove .methodology/gate2_result.json
log_remove .methodology/gate_timestamps.jsonl
log_remove .methodology/gap_report.json
log_remove .methodology/quality_manifest.json
log_remove .methodology/sessions_spawn.log
log_remove .methodology/sessions_spawn.log.lock
log_remove .methodology/.gate1_scores.json
log_remove .methodology/effort_metrics.db
log_remove .methodology/improvement-proposal-2026-06-27.md

echo ""
echo "[State + trace] reset"
log_remove .methodology/state.json
log_remove .harness/traces/agent_trajectory.jsonl

echo ""
echo "============================================================"
echo " Cleanup complete: $removed paths removed"
echo "============================================================"
echo ""
echo "Next steps to re-run the 8 phase workflow JS:"
echo "  1. python harness_cli.py init-project --project .   # if not initialized"
echo "  2. claude /workflow phase1-requirements              # or run manually"
echo "  3. ... advance through phase8-config"
echo ""
echo "Workflow JS is the verification subject — DO NOT modify it."
echo "If a workflow JS fails, the bug is in harness-methodology,"
echo "not in your project. Report root cause + fix in harness submodule."