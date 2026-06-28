# Specification Tracking Matrix — taskq

> Phase 1 deliverable. Derives per-FR tracking rows from `01-requirements/SRS.md` (APPROVED).
> Source: SPEC.md v2.0.0 (2026-06-15). Date: 2026-06-29.
> Agent A scope: assign **status** + **owner (role)** + **gate link** per FR/NFR. No invention, no silent omission of FR-01..FR-03 / NFR-01..NFR-03.

---

## 1. Purpose

This document is the **per-FR tracking layer** between `SRS.md` (requirements) and downstream engineering artifacts (`TRACEABILITY_MATRIX.md`, `TEST_INVENTORY.yaml`, implementation phases P3–P8).

For each FR / NFR registered in `SRS.md`:

- one row is created here with a stable tracker id (`FR-01`, `NFR-01`, …),
- the **status** reflects the latest known artifact state (P1 → P8),
- the **owner (role)** indicates which role is accountable for the artifact set,
- the **gate** indicates which Phase-Exit Gate (Gate 1/2/3/4) the FR participates in.

This file is the source of truth for the *registry*; `TRACEABILITY_MATRIX.md` is the source of truth for *coverage links*.

---

## 2. Status Vocabulary

Single canonical status vocabulary (mixed-case, UPPERCASE keyword + descriptor). Downstream tools MUST match these tokens exactly.

| Status | Meaning | Allowed transitions |
|--------|---------|---------------------|
| `DRAFT` | Authored in SRS, not yet peer-approved | → `APPROVED` |
| `APPROVED` | Peer-reviewed (Agent B = BUSINESS_ANALYST) and accepted; P1 exit | → `IN_PROGRESS` |
| `IN_PROGRESS` | Implementation underway (P3 author alive) | → `IMPLEMENTED` |
| `IMPLEMENTED` | Code merged to `main`; Gate 1 not yet run | → `GATE1_PASS` |
| `GATE1_PASS` | Per-FR Gate 1 (quality dim score ≥ 85) cleared | → `VERIFIED` |
| `VERIFIED` | Phase 5 acceptance criteria exercised + recorded | → `GATE2_PASS` / `GATE3_PASS` / `GATE4_PASS` |
| `GATE2_PASS` | Phase 3 exit gate cleared (G2) | terminal |
| `GATE3_PASS` | Phase 4 exit gate cleared (G3) | terminal |
| `GATE4_PASS` | Phase 6 final quality gate cleared (G4, 14 dims, score ≥ 85) | terminal |
| `DEFERRED` | Logged as NFR-99 / FR-deferred in SRS §7; not in active scope | → `APPROVED` (re-promotion) |
| `REJECTED` | Peer review rejected — Agent A to remediate and resubmit | → `DRAFT` / `APPROVED` |

Forbidden transition: any backward step from a terminal `*_PASS` state (regression requires a new peer-review round).

---

## 3. Functional Requirements (FR) Tracking

One row per FR registered in `SRS.md` §3. The FR IDs are **stable cross-phase handles** referenced by `TRACEABILITY_MATRIX.md` and `TEST_INVENTORY.yaml`.

| FR ID | Title | Source | Owner (Role) | Status | Gate | Test IDs | Notes |
|-------|-------|--------|--------------|--------|------|----------|-------|
| FR-01 | Task Model & Persistence | SPEC.md §3 FR-01 | REQUIREMENTS_ENGINEER + IMPLEMENTATION_ENGINEER | `DRAFT` | Gate 1 + Gate 3 | FR-01.AC-1..AC-5 (5 ACs) | Atomic JSON write via `tmp + os.replace`; corrupt-store detection at startup |
| FR-02 | Task Execution & Retry | SPEC.md §3 FR-02 | IMPLEMENTATION_ENGINEER | `DRAFT` | Gate 1 + Gate 3 | FR-02.AC-1..AC-5 (5 ACs) | `subprocess.run(shlex.split(...))`; `shell=True` forbidden; retry on `failed`/`timeout` |
| FR-03 | CLI Integration & Query | SPEC.md §3 FR-03 | IMPLEMENTATION_ENGINEER + CLI_ENGINEER | `DRAFT` | Gate 1 + Gate 3 | FR-03.AC-1..AC-6 (6 ACs) | `python -m taskq`; argparse subcommands `submit`/`run`/`status`/`list`/`clear`; `--json` |

---

## 4. Non-Functional Requirements (NFR) Tracking

One row per NFR registered in `SRS.md` §4.

| NFR ID | Title | Source | Owner (Role) | Status | Gate | Test IDs | Notes |
|--------|-------|--------|--------------|--------|------|----------|-------|
| NFR-01 | Performance | SPEC.md §4 NFR-01 | QUALITY_ENGINEER | `DRAFT` | Gate 1 + Gate 3 | NFR-01.AC-1 (1 AC) | submit+status ×100 p95 < 50ms; subprocess exec excluded |
| NFR-02 | Security | SPEC.md §4 NFR-02 | SECURITY_ENGINEER + IMPLEMENTATION_ENGINEER | `DRAFT` | Gate 4 | NFR-02.AC-1..AC-2 (2 ACs) | (AC-1) zero `shell=True` codebase-wide static check; (AC-2) per-char injection-blacklist tests |
| NFR-03 | Reliability | SPEC.md §4 NFR-03 | IMPLEMENTATION_ENGINEER + SECURITY_ENGINEER | `DRAFT` | Gate 4 | NFR-03.AC-1..AC-2 (2 ACs) | (AC-1) atomic write survives SIGKILL mid-write; (AC-2) `(sk-…|token=…)` whole-line redaction to `[REDACTED]` |

---

## 5. Deferred / Out-of-Scope Items (NFR-99 Tracked)

Row exists iff SRS §7 declares any deferred item. If empty, this section is intentionally **empty** (no row invented) — match the SRS §7 NFR-99 verdict verbatim.

| Tag | Title | Source | Owner (Role) | Status | Notes |
|-----|-------|--------|--------------|--------|-------|
| NFR-99 (none) | No deferred items — SPEC.md v2.0.0 3-FR compact form has no TBD/TODO/`<placeholder>` markers | SRS.md §7 (verbatim); SPEC.md full text scan | n/a | n/a | This row is a meta-row documenting the absence of deferred items; not an actionable FR. **Do not assign a gate.** |

---

## 6. Owner Role Legend

The `Owner (Role)` column references the following canonical roles. A row may list multiple roles (comma-separated) when the FR spans disciplines.

| Role | Phase Range | Responsibility |
|------|-------------|----------------|
| REQUIREMENTS_ENGINEER | P1 | Authors SRS, SPEC_TRACKING, TRACEABILITY_MATRIX, TEST_INVENTORY |
| BUSINESS_ANALYST | P1 (peer review only) | Statutory peer reviewer (Agent B) for P1 deliverables |
| IMPLEMENTATION_ENGINEER | P3 | Authors code satisfying FR-01..FR-03 |
| CLI_ENGINEER | P3 | Implements `argparse` subcommand surface (FR-03) |
| SECURITY_ENGINEER | P5 + P6 | Owns NFR-02 (shell=True static check) + NFR-03 (redaction) verification |
| QUALITY_ENGINEER | P5 + P6 | Owns perf (NFR-01) measurement; orchestrates Gate 3 / Gate 4 |

---

## 7. Gate Mapping Summary

| Gate | Trigger | FRs in scope | NFRs in scope |
|------|---------|--------------|---------------|
| Gate 1 | P3 / P5 / P7 / P8 per-FR | FR-01, FR-02, FR-03 | NFR-01 |
| Gate 2 | P3 exit | (architecture + implementation) | (architecture-level) |
| Gate 3 | P4 exit | FR-01, FR-02, FR-03 | NFR-01 |
| Gate 4 | P6 full | (cross-FR) | NFR-02, NFR-03 |

Rationale (per `phase1_plan.md` Hard Rules):

- NFR-01 (performance) is exercised per-FR via micro-bench, so it participates in Gate 1 and Gate 3.
- NFR-02 (security) and NFR-03 (reliability) are **cross-cutting** concerns and only become gating at Gate 4 (final quality gate), where the 14-dimension rubric and `nfr-2-static-checks` baseline are applied.

---

## 8. Acceptance Criteria Coverage (Cross-Reference Index)

Total ACs registered in SRS.md §5 = 5 (FR-01) + 5 (FR-02) + 6 (FR-03) + 1 (NFR-01) + 2 (NFR-02) + 2 (NFR-03) = **21 ACs**.

| FR / NFR | AC Count | AC IDs |
|----------|----------|--------|
| FR-01 | 5 | FR-01.AC-1, FR-01.AC-2, FR-01.AC-3, FR-01.AC-4, FR-01.AC-5 |
| FR-02 | 5 | FR-02.AC-1, FR-02.AC-2, FR-02.AC-3, FR-02.AC-4, FR-02.AC-5 |
| FR-03 | 6 | FR-03.AC-1, FR-03.AC-2, FR-03.AC-3, FR-03.AC-4, FR-03.AC-5, FR-03.AC-6 |
| NFR-01 | 1 | NFR-01.AC-1 |
| NFR-02 | 2 | NFR-02.AC-1, NFR-02.AC-2 |
| NFR-03 | 2 | NFR-03.AC-1, NFR-03.AC-2 |
| **Total** | **21** | — |

Computation rule: AC count is derived **strictly** from `SRS.md` §5. If `SRS.md` §5 changes, recompute and update this section in the same edit.

---

## 9. Completeness Checks

These checks are **validators**, not FR rows. They enforce that the tracking matrix matches SRS.md (the APPROVED source of truth). Run after authoring and after every SRS.md change.

| # | Check | Rule | Pass criterion |
|---|-------|------|----------------|
| C1 | FR completeness | Every FR ID in `SRS.md` §3 has a row in §3 of this file | 3 / 3 (FR-01, FR-02, FR-03) |
| C2 | NFR completeness | Every NFR ID in `SRS.md` §4 has a row in §4 of this file | 3 / 3 (NFR-01, NFR-02, NFR-03) |
| C3 | AC count consistency | Sum of `AC Count` column in §8 == `SRS.md` §5 row count | 21 == 21 |
| C4 | Deferred row fidelity | §5 row count == `SRS.md` §7 NFR-99 row count (incl. `(none)` meta-row if SRS says none) | 1 == 1 |
| C5 | Stable handle uniqueness | No duplicate FR/NFR id across §3, §4, §5 | 0 duplicates |
| C6 | Status token validity | Every `Status` cell is a token from §2 vocabulary | 100% match |
| C7 | Gate link validity | Every `Gate` cell is one of `{Gate 1, Gate 2, Gate 3, Gate 4}` | 100% match |

If any check fails → re-edit this file. Do **not** edit `SRS.md` to satisfy the matrix; SRS is APPROVED.

---

## 10. Change Log

| Date | Round | Change | Author |
|------|-------|--------|--------|
| 2026-06-29 | 1 (initial) | Authored SPEC_TRACKING.md from `SRS.md` (APPROVED, derived from SPEC.md v2.0.0). Established FR-01/FR-02/FR-03 + NFR-01/NFR-02/NFR-03 + 21 ACs. Per-FR status set to `DRAFT` (P1 mid-execution; await B review to advance to `APPROVED`). | REQUIREMENTS_ENGINEER (Agent A) |

---

*End of SPEC_TRACKING.md — Phase 1 deliverable. Awaiting BUSINESS_ANALYST (Agent B) peer review for status `DRAFT → APPROVED` transition.*
