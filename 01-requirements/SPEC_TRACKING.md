# Specification Tracking Matrix — taskq

> Tracks each FR/NFR from `SRS.md` (source of truth; `SRS.md` is
> APPROVED and not modified by this document) through ownership,
> implementation status, and forward mapping to downstream phase
> deliverables. Companion documents in this stage: `SRS.md`,
> `TEST_INVENTORY.yaml`, `TRACEABILITY_MATRIX.md`.

---

## 1. Purpose

Single tracking surface answering, per requirement: *where does it
live in the module layout, who owns it, what is its current status,
and which downstream artifact will next reference it.* Status values
are updated by later phases (Phase 2 Architecture onward); this
document does not itself certify design or test completion.

---

## 2. Status Legend

| Status | Meaning |
|---|---|
| `BASELINED` | Captured in SRS.md, approved, not yet designed |
| `IN_DESIGN` | Referenced by an active ADR/SAD/TEST_SPEC draft |
| `IMPLEMENTED` | Corresponding module code merged |
| `VERIFIED` | Covered by passing tests traced in TRACEABILITY_MATRIX.md |

All rows below are `BASELINED` as of this tracking round — Phase 2
(Architecture) has not yet produced `ADR.md` / `SAD.md` /
`TEST_SPEC.md` for this project.

---

## 3. FR Tracking Matrix

| FR ID | Title | Owning Module(s) | AC Count | Status | SRS Section |
|---|---|---|---|---|---|
| FR-01 | Task Submission and Validation | `store.py`, `cli.py` | 6 | VERIFIED | SRS.md §3 FR-01 |
| FR-02 | Task Executor | `executor.py` (high-risk), `store.py` (high-risk) | 5 | VERIFIED | SRS.md §3 FR-02 |
| FR-03 | Retry and Circuit Breaker | `breaker.py`, `executor.py` (high-risk) | 5 | VERIFIED | SRS.md §3 FR-03 |
| FR-04 | Result TTL Cache | `cache.py` | 4 | VERIFIED | SRS.md §3 FR-04 |
| FR-05 | CLI Integration | `cli.py` | 7 | VERIFIED | SRS.md §3 FR-05 |
| FR-06 | — | — | — | IN_PROGRESS | — |

---

## 4. NFR Tracking Matrix

| NFR ID | Title | Owning Module(s) | AC Count | Status | SRS Section |
|---|---|---|---|---|---|
| NFR-01 | Performance (submit+status p95 < 50ms) | `store.py`, `cli.py` | 1 | BASELINED | SRS.md §4 NFR-01 |
| NFR-02 | Security — no `shell=True`, injection blacklist | `executor.py` | 2 | BASELINED | SRS.md §4 NFR-02 |
| NFR-03 | Reliability — atomic writes, breaker recovery time | `store.py`, `breaker.py`, `cache.py` | 2 | BASELINED | SRS.md §4 NFR-03 |
| NFR-04 | Security — secret redaction | `executor.py` | 1 | BASELINED | SRS.md §4 NFR-04 |
| NFR-05 | Maintainability — docstring `[FR-XX]` coverage | all `src/taskq/*` | 1 | BASELINED | SRS.md §4 NFR-05 |
| NFR-06 | Deployability — env var completeness | `config.py` | 2 | BASELINED | SRS.md §4 NFR-06 |

---

## 5. Ownership by Module

| Module | FRs | NFRs | Risk Class |
|---|---|---|---|
| `store.py` | FR-01, FR-02 | NFR-01, NFR-03 | high-risk (SRS.md §2) |
| `executor.py` | FR-02, FR-03 | NFR-02, NFR-04 | high-risk (SRS.md §2) |
| `breaker.py` | FR-03 | NFR-03 | standard |
| `cache.py` | FR-04 | NFR-03 | standard |
| `cli.py` | FR-01, FR-05 | NFR-01 | standard |
| `config.py` | — | NFR-06 | standard |
| `models.py` | — | NFR-05 | standard |
| `__main__.py` | — | NFR-05 | standard |

---

## 6. Downstream Deliverable Mapping

| Requirement Set | Next Consumed By | Deliverable |
|---|---|---|
| FR-01..05, NFR-01..06 | Phase 2 — Architecture | `SAD.md` (module/component design) |
| FR-01..05, NFR-01..06 | Phase 2 — Architecture | `ADR.md` (key design decisions, e.g. breaker/cache mechanism) |
| FR-01..05, NFR-01..06 | Phase 2 — Architecture | `TEST_SPEC.md` (test case derivation from AC-FR-*/AC-NFR-*) |
| All AC-FR-*/AC-NFR-* | 01-requirements (sibling sub-task) | `TRACEABILITY_MATRIX.md` |
| All FR/NFR AC counts | 01-requirements (sibling sub-task) | `TEST_INVENTORY.yaml` |

---

## 7. Open Items Carried from SRS.md

- No unresolved TBD/TODO markers (SRS.md §7).
- `srs_vs_spec_diff.json` residual `NFR-06` `over_spec_score: 0.813`
  boundary-detection artifact noted in SRS.md §7 — informational only,
  does not block tracking; carried here for Phase 2 visibility.

---

*Source: `SRS.md` (approved). Agent A, Sub-Task 2/4, Round 1.*
