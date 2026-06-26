# Harness-Methodology Improvement Proposal — 2026-06-27

> Generated from E2E phase1-requirements workflow run (2026-06-26 to 2026-06-27):
> 17 agents / 596,922 tokens / 717s / 1 sub-task completed before HR-12 escalate.

---

## TL;DR

| Issue | Mitigation shipped (v12, v13) | Status |
|-------|-------------------------------|--------|
| B reviewer hallucination (R5 R4.5+): rejects valid content on fabricated premises | v12: fresh-disk view + summary embedding + `safePrevB2` reason strip | Partial: improved citation accuracy, did NOT prevent R3 hallucination |
| B reviewer interpretation conflict: rejects reasonable author interpretation | v13: X1 B self-verification (observability layer) | Partial: surfaces B instability to log, no hard veto |
| Plan §B-1 STATELESS assumption obsolete (B is general-purpose with Bash/Read) | v12: rewrote §B-1 as FRESH-DISK VIEW | ✓ |

---

## Findings (Root Cause)

### 1. B Reviewer Hallucination — Two Failure Modes

**(a) Pure hallucination**: B ignores disk content and rejects on fabricated premises.
Example from latest run R3: B claimed "SRS describes a Node.js job queue library but SPEC mandate a Python 3.11 stdlib CLI" — the SRS on disk was a faithful Python transcription (line 1: `# SRS — Software Requirements Specification: taskq`). B completely ignored the file content.

**(b) Interpretation conflict**: B rejects reasonable author interpretation as "fabrication".
Example from R5: B claimed "AC-FR02-09/10/11 over-split" and "FR-02-deferred-c fabricated" — but the SRS author had explicitly annotated these as deferred items with verbatim SPEC.md citations (`*[Per SPEC.md FR-02 verbatim ...; multi-task interaction with exit 4 is NOT specified — see FR-02-deferred-c.]*`). The annotations were transparent; B's reject conflated "interpretive" with "fabricated".

These are different bugs. (a) is unrecoverable from the prompt layer (LLM model instability); (b) is recoverable with better grounding instructions.

### 2. Plan §B-1 STATELESS Sandbox Assumption Obsolete

Plan wrote (v2.7.0):
> STATELESS SANDBOX: Agent B has ZERO access to local files or /tmp.
> NEVER write 'read 01-requirements/SRS.md' in the prompt — it will fail silently.
> ALL context must be pasted verbatim into the prompt text. This is mandatory.

But B is dispatched as a `general-purpose` agent with FULL Bash/Read tool access. The verbatim-DOC-embedding pattern pushes B's prompt past 80k tokens (4 docs × full content), dispersing B's attention. This is the **context overload** path to hallucination.

### 3. Premise Persistence Across Rounds

`prevB2.reason` is free-text and re-embedded verbatim each round. If R1 B produced a hallucinated premise, R2-R5 B extend it rather than forming fresh judgment from disk. The verbatim-DOC-embedding pattern amplifies this.

---

## Mitigations Applied

### v12 (commit 7acbd40) — Fresh-Disk View

**Workflow JS changes**:
- `buildBPrompt`: tell B to USE Bash/Read for fresh disk view; embedded docs are SUMMARY snapshot, not sole source of truth.
- `safePrevB2(prevB2)`: strip `reason`; only `review_status` + `gaps` survive forward.
- `makeDocSummary(content)`: APPROVED upstream docs embedded as heading summary + line count (~200 chars) instead of full content.
- All 4 buildBDocs updated; peer-review loadedDocs updated.

**Plan §B-1**: rewritten as FRESH-DISK VIEW with rationale.

**Observed effect**: B's citation accuracy improved (real line numbers); R5 still hallucinated but with better grounding.

### v13 (commit 4510e05) — X1 B Self-Verification

**Plan §B-2.5 added**: After B-2 returns, dispatch B (fresh STATELESS context, fresh prompt) to verify its OWN citations and atomic claims via Bash (sed/grep). Returns `b2.verify = {verified_gaps, unverified_reason_claims, recalibrated_review, confidence}`.

**Workflow JS additions**:
- `runBSelfVerify(cfg, b2, round)`: dispatches verify prompt.
- `summarizeVerify(b2, verify)`: log line shows `verify=N/M gaps_verified | K unverified_reason_claims`.
- When ratio < 0.5, log warns `[X1: B UNSTABLE — majority unverified]`.

**Critical**: verify is **observability layer only** — does NOT change `b2.review_status` or veto B's REJECT. HR-12 escalation rules in §B-2 remain unchanged. Humans reading the workflow log get an early signal to HITL before round 5.

**Cost**: 1 additional agent call per round (~10k tokens). 5-round loop = ~50k extra tokens.

---

## Survey-Backed Best Practices Not Yet Implemented

From arxiv 2509.18970 (LLM-based Agents Hallucinations Survey), arxiv 2510.24476 (Mitigating Hallucination in LLMs: RAG, Reasoning, Agentic Systems), MasterOfCode 2026:

| Technique | 3-source consensus | Cost | Recommend |
|-----------|--------------------|------|-----------|
| Cross-validation (2+ B consensus) | ✔ | High (2x B calls) | Phase 2+, when more budget |
| Self-consistency (multi-sample vote) | ✔ | High (3x B calls) | NOT recommended — diminishing returns vs cost |
| HITL escalation gate at HR-12 | ✔ (MasterOfCode + arxiv) | Low | **High priority** |
| Few-shot examples in B prompt | ✔ (MasterOfCode) | Low | Phase 2+ |
| Confidence scoring in B output | ✔ | Low | Easy add |
| Post-hoc consistency check (SELF-RAG) | ✔ (arxiv 2510.24476) | Medium | Phase 3+ |
| Symbolic verification (Logic-LM, SymbCoT) | ✔ | High | NOT for free-text reviews |

---

## Recommended Next Steps (Priority Order)

### Priority 1: HITL Escalation Gate (X3) — High value, Low cost

When HR-12 triggers (5 round REJECT), auto-generate a human-readable summary file (e.g. `01-requirements/HR12_ESCALATE_<sub-task>.md`) with:
- A's last JSON
- B's last JSON (all 5 rounds)
- b2.verify summary (X1 metadata)
- Recommended human action (accept-as-is / specify-edit / reject-and-revert)

**Workflow pause** at this gate — no auto-advance. Johnny reviews the summary and decides.

**Why**: X3 is the only mitigation that gives humans authoritative final judgment. The cost is minimal (1 file write + workflow pause). Without X3, even X1 self-verification just warns "B is unstable" but doesn't act on it.

### Priority 2: Confidence Scoring in B Output — Easy add, helps X1

Add a `confidence: "high"|"medium"|"low"` field to B-2 output schema. B reflects on its own certainty. Low confidence + X1 unverified majority = strong HITL signal even before round 5.

Cost: 0 extra calls (just prompt instruction + JSON field).

### Priority 3: Few-Shot Examples in B Prompt — Reduces R3-type hallucination

Add 2-3 example reviews (one good APPROVE, one good REJECT, one hallucinated REJECT) to `buildBPrompt`. Calibrate B's interpretation of "fabrication" vs "interpretation" before it reviews.

Cost: prompt grows by ~1k tokens; no extra calls.

### Priority 4: Cross-Validation (2B Consensus) — Phase 2+ only

When budget allows, dispatch 2 independent B agents per round. Compare REJECT reasons:
- Both REJECT same items → high confidence
- One REJECT, one APPROVE → unstable, escalate
- Both REJECT but different items → conflicting, escalate

Cost: 2x B calls. Skip until v13 X1 is validated.

---

## Open Questions

1. **Should the harness submodule (harness-methodology v1.0) be updated to mirror v12/v13?** The submodule HEAD is 0803c12 (v1.0-1023-g0803c12) and the workflow JS lives in integration-test, not in the submodule. Submodule's `.methodology/phase1_plan.md` is v2.7.0 — 132 lines behind integration-test's v2.12.0. If the submodule's plan is meant to be the canonical reference, it needs a sync PR. If integration-test's `.methodology/` is canonical, the submodule is stale.

2. **Is the 4-deliverable phase1 (SRS + SPEC_TRACKING + TRACEABILITY + TEST_INVENTORY) the right granularity?** Each is its own sub-task with its own A/B loop — total 4 × 5 = 20 round maximum. The late rounds consistently hallucinate (R3-R5). Consider:
   - (a) Reducing deliverable count (collapse SPEC_TRACKING into SRS appendices)
   - (b) Earlier HR-12 (e.g. 3 rounds instead of 5) with mandatory HITL
   - (c) Single-phase atomic workflow (A → B → A → B all-in-one)

3. **Should workflow resume mechanism preserve agent() results?** Currently each workflow invocation re-runs all sub-tasks from scratch. v13 X1 doubles B calls per round — without resume, a phase1 retry now costs ~600k tokens vs ~300k before. Resume mechanism (Workflow tool's `resumeFromRunId`) preserves results, but our runSubTask doesn't use it.

---

## Self-Audit

- **What I got right**: Identified B hallucination as two distinct failure modes (pure hallucination vs interpretation conflict); matched each to the right mitigation (fresh-disk view vs X1 verification); maintained plan-faithful principle throughout (X1 is observability, not veto).
- **What I got wrong**: Initially proposed validateBGaps as a "real fix" — that was a workaround. X1 + eventual X3 (HITL) are the genuine plan-faithful mitigations.
- **What I'm uncertain about**: Whether v12+v13 actually converges workflow in <5 rounds. Need a validation run.
- **Confidence**: Medium. Survey-backed techniques are well-evidenced; specific token costs / wall-clock savings are estimates.

---

## References

1. arxiv 2509.18970: "LLM-based Agents Suffer from Hallucinations: A Survey of Taxonomy, Methods, and Directions" — https://arxiv.org/html/2509.18970v1
2. arxiv 2510.24476: "Mitigating Hallucination in Large Language Models (LLMs): An Application-Oriented Survey on RAG, Reasoning, and Agentic Systems" — https://arxiv.org/html/2510.24476v1
3. MasterOfCode (2026): "Stop LLM Hallucinations: Reduce Errors by 60-80%" — https://masterofcode.com/blog/hallucinations-in-llms-what-you-need-to-know-before-integration
4. MDPI 16/7/517: "Mitigating LLM Hallucinations Using a Multi-Agent Framework" — https://www.mdpi.com/2078-2489/16/7/517

---

## Changelog

- 2026-06-27: v13 (X1) shipped; v12 (fresh-disk view) shipped; this proposal drafted.
- 2026-06-26: B hallucination identified; survey research began.