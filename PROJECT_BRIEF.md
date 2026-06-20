# Project Brief — taskq

## canonical_spec
SPEC.md

## Project Domain
Local task queue CLI tool for controlled shell command execution.

## Stakeholders
- Project owner / product manager: johnnylugm-tech
- Integration test target: harness-methodology v2.9 pipeline validation

## Business Goals
- Provide a reliable local task queue CLI (`taskq`) that submits, executes, retries, and caches shell commands
- Demonstrate full Phase 1–8 harness-methodology development pipeline on a real small project
- Zero runtime external dependencies (Python 3.11 stdlib only)

## Key Constraints
- **Technical**: Python 3.11, stdlib only at runtime; `shell=True` is forbidden everywhere
- **Security**: Injection character blacklist (`;|&$><\`` ); secret redaction in stdout/stderr tails (NFR-04)
- **Reliability**: All three data files (`tasks.json`, `breaker.json`, `cache.json`) must be atomically written
- **Performance**: `submit` + `status` p95 < 50ms for 100 iterations (NFR-01)

## Source of Truth
All functional and non-functional requirements are fully specified in `SPEC.md` at the project root.
Agent A must operate in INGESTION MODE: transcribe 100% of FR-01 through FR-05 and NFR-01 through NFR-06 from SPEC.md — no invention, no omission.
