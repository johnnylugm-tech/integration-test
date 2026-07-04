# RELEASE_CHECKLIST

## Pre-Release Checks
- [ ] All P1-P7 phases completed and artifacts generated.
- [ ] CI pipeline fully passed.
- [ ] Final Sign Off approved.
- [ ] Production environment provisioned.
- [ ] Rollback plan documented.

## Human Context (P8 append)

> Human-authored runbook context appended to the framework-generated checklist above. Do NOT regenerate above sections; this block supplements deployment / rollback / comms info.

### Deployment Runbook
- **URL**: `https://runbooks.example.internal/integration-test/release` (rendered from `runbooks/release.md` in ops repo)
- **Pre-deploy**: verify Gate 4 PASS in `.methodology/manifests/quality_manifest.json` (composite_score ≥ 85); confirm `git tag vgate4-20260703-score96-8-g8f5211c` is the release ref.
- **Deploy command**: `make deploy ENV=prod REF=8f5211c` (see runbook for full sequence: drain → deploy → warm → health-check → unblock)
- **Estimated deploy window**: 15 min drain + 10 min rolling restart + 5 min warm-up.

### Rollback Owner + On-Call
- **Primary rollback owner**: taskq-platform on-call (PagerDuty schedule `taskq-platform-p1`)
- **Escalation**: SRE on-call → Eng manager → VP-Eng
- **Rollback trigger**: any P0 / SEV-1 within first 30 min post-deploy, OR composite health-check failure (error rate > 1% sustained 5 min)
- **Rollback command**: `make rollback ENV=prod TO_REF=<previous-good-tag>` (see Section 7 of CONFIG_RECORDS for SOP)
- **Communication**: rollback owner opens `#incident` thread within 5 min of trigger.

### Post-Release Monitoring Dashboard
- **Primary dashboard**: `https://grafana.example.internal/d/integration-test-release` (panels: deploy marker, taskq throughput, error rate, p99 latency, executor pool saturation, store connection health)
- **SLO watch**: p99 < 500ms, error rate < 0.1%, executor queue depth < 1000 sustained 15 min
- **Watch window**: 0-60 min "active watch" (deploy owner present), 1-24 h "passive watch" (on-call paged on alert)
- **Alert routing**: P2 → `#integration-test-alerts`; P1/P0 → PagerDuty `taskq-platform-p1`

### Customer Comms Template
```
Subject: [integration-test] Release v<tag> deployed to production — <date>

Hi customers,

We have rolled out release v<tag> to production for integration-test.
Release highlights:
- <bullet 1>
- <bullet 2>

Status: deploy completed at <timestamp>; all health checks green.
No customer action required.

If you observe issues: please open a support ticket or reply to this thread.

— <deploy owner name>, on behalf of the integration-test team
```
- **Send-to**: customer-announce@example.internal (mailing list)
- **Send-when**: within 30 min post-deploy success (active watch window)
- **Owner**: deploy owner drafts; product-eng lead approves; SRE sends.

### Notes
- Framework-generated Pre-Release Checks above are the deterministic output of the P7→P8 advance-phase doc-gen pipeline and MUST NOT be edited by hand.
- This Human Context block is the operational overlay maintained by the named owners; update when runbooks / on-call schedules / dashboards change.
