# Project Brief — taskq

## canonical_spec
SPEC.md

## Project Domain
Local task queue CLI tool for submitting shell commands as tasks and running them under control (timeout + retry).

## Stakeholders
- Project owner / product manager: johnnylugm-tech
- Integration test target: harness-methodology v2.9 pipeline validation

## Business Goals
- Provide a small, reliable local task queue CLI (`taskq`) — submit, run, status, list, clear
- Demonstrate full Phase 1–8 harness-methodology development pipeline on a real small project
- Zero runtime external dependencies (Python 3.11 stdlib only)

## Key Constraints
- **Technical**: Python 3.11 stdlib only; `python -m taskq` CLI entry; `shell=True` is forbidden everywhere; atomic JSON writes (`tmp + os.replace`)
- **Security**: Injection character blacklist (`; | & $ > < \``) on `submit` (NFR-02)
- **Reliability**: `tasks.json` atomic write survives mid-write crash; never silently rebuilt on parse failure; secret-line redaction on `stdout_tail` / `stderr_tail` (NFR-03)
- **Performance**: `submit` + `status` combined p95 < 50ms over 100 iterations (NFR-01)

## Source of Truth
All functional and non-functional requirements are fully specified in `SPEC.md` (v2.0.0, 2026-06-15) at the project root.
Agent A must operate in INGESTION MODE: transcribe 100% of `### FR-01..FR-03` and `### NFR-01..NFR-03` headings from SPEC.md — no invention, no omission.
TBD / TODO / `<placeholder>` markers from SPEC.md must be captured as `NFR-99` or `FR-XX-deferred` (not silently dropped).
