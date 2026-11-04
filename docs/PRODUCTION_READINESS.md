# Production readiness

**Status: ready for UAT in PennyMac's AWS account. Not ready for go-live.** Go-live needs the items in section 4. They depend on PennyMac systems, data, people or sign-offs that a codebase cannot provide on its own.

Everything in section 1 was executed, not just written. Re-run any of it with the commands shown.

## 1. Verified

| Area | Evidence | How to re-run |
|---|---|---|
| Functional | 86 automated tests covering mapping, rules, exceptions T1–T5, drift, duplicates, replay, memory, versions, analytics, API, incremental/snapshot loads, vendors, feed sequencing and the delivery scheduler | `pytest -q` |
| Real RDBMS | The full suite also passes on PostgreSQL 16. This found and fixed two defects SQLite hides: length enforcement and JSON `NULL` handling. | `LBP_TEST_DATABASE_URL=postgresql+psycopg://… pytest -q` |
| Migrations | Alembic upgrades a fresh database. The models match the migration exactly (no drift), and downgrade works. The API refuses to start on an un-migrated schema. | `LBP_MIGRATION_TEST_URL=… pytest tests/test_migrations.py` |
| Concurrency | 8 parallel audit writers leave one intact hash chain. 8 parallel workers produce exactly one batch lease. | `tests/test_concurrency.py` (Postgres) |
| Crash safety | The worker is killed after a committed micro-batch. Resume re-stages nothing, and reconciliation balances. A stale lease is recovered after the heartbeat timeout. | `tests/test_enhancements.py` |
| AWS execution path | EventBridge arrival → Route → Glue (`lbp-feed` / `lbp-feed-spark`) → Finalize, against mocked S3, Step Functions, Glue and Secrets Manager. API uploads and actions dispatch to Step Functions / Glue, never process inline. A duplicate EventBridge delivery starts one pipeline. The `migrate` Lambda publishes every feed's configuration. Pipeline metrics come from the Glue jobs. The ASL, Terraform and job scripts are checked for consistency. | `tests/test_lambdas.py` |
| Glue data plane | The standard job runs a batch end to end. The Spark job runs on a real local Spark 4 cluster (stand-in `awsglue` module) and produces the same pass / warn / fail counts as the standard engine. A tampered or stale configuration is refused; a rule change republishes every live feed. | `tests/test_glue_jobs.py` |
| Web app | ESLint (undefined names, hook order, unused code) clean. Every review, approval and audited action is a dialog with focus trap, Esc / backdrop close, stacking and keyboard prev / next; walked through in Chromium at desktop and phone width with no console errors. | `npm run lint`, `npm run build:demo` |
| Authentication | Cognito JWT checks: signature, issuer, audience/client, expiry and token_use. Spoofed identity headers are rejected. A user with no group gets 403. Full PKCE browser sign-in was tested end to end. | `tests/test_security.py` |
| Authorization | One reviewable role matrix (`ROUTE_ROLES`) with deny-by-default for writes. A test fails if a write route has no entry. | `tests/test_security.py` |
| Unsafe config | The API refuses to start outside local with dev auth, SQLite, demo routes, wildcard CORS or auto-created schema. | `python -m lbp.cli check-config` |
| NPI | NPI is masked in list and detail views, error messages and logs (no SQL parameters are logged). A retention purge removes raw rows. Uploads are size- and content-checked. | `tests/test_security.py` |
| Audit (SOX) | The audit log is hash-chained. Editing, deleting or reordering an entry is detected. | `python -m lbp.cli verify-audit` |
| Static analysis | ruff with security rules (bandit-equivalent): clean. hadolint: clean. `npm audit` (prod): 0 vulnerabilities. | `ruff check …` |
| Infrastructure | `tofu validate` passes against the real AWS provider schema. checkov: 329 passed, 0 failed, 48 skips, each with a written reason in the code. | `tofu validate`, `checkov -d aws/terraform` |
| Throughput | See section 5 (1M loans on PostgreSQL). Incremental updates run at the same rate (2,713 rows/s). | `scripts/load_test.py --rows 1000000` |
| Incremental loads | Sparse updates write only changed fields, under optimistic concurrency. A newer value is never overwritten: conflicts become CHG05. Protected fields go to dual control. Closes never delete. A truncated snapshot raises no closes. A re-sent defect does not undo a reviewer's correction. | `tests/test_incremental.py` |
| Vendor order | A gap waits, an older file is held out of order, and a skip or override needs a reason. With 8 workers racing on PostgreSQL, the gate admits exactly the next file. | `tests/test_incremental.py`, `tests/test_concurrency.py` |
| Delivery scheduler | Cron in the vendor's timezone across DST, on Fed holidays. Late and missed alerts fire once, under a leader lease. SFTP host-key pinning was tested against a real SFTP server. | `tests/test_scheduler.py`, `tests/test_sftp_pull.py` |

## 2. Security and compliance controls

| Requirement | Control in the product |
|---|---|
| SOX: change control and audit trail | Mapping and rule changes need maker-checker approval. Rule versions are signed. The data plane runs only signed, approved feed configurations, each publication recorded with version, SHA-256, actor and reason. The audit log is hash-chained and mirrored to CloudTrail (multi-region, CloudWatch Logs, validation on). |
| GLBA: NPI safeguards | KMS at rest (RDS, S3, DynamoDB, logs). TLS in transit (CloudFront, API Gateway, S3 TLS-only policies, TLS to RDS). Masking by role. Staging retention purge. No NPI in logs or Step Functions history. |
| SR 11-7: model risk | AI never auto-applies to regulated fields (T4/T5). T1 has a kill switch and is suspended automatically when its override rate breaches 2%. QA sampling, rollback and proposal acceptance are tracked. |
| ECOA, HMDA, TILA, RESPA | Rules carry regulatory tags, and those rules need Compliance approval. HMDA, identity and pricing fields always go to dual control. |
| OFAC / BSA-AML | Hits and fraud flags go to T5: the loan is halted and only Compliance can act. |
| Least privilege | Cognito groups map to roles. The IAM policy for each workload is scoped to its buckets, tables and keys. Network egress is limited to 443 and 1433. |
| Credential hygiene | RDS-managed master secret with rotation. The app reads it on each new connection. No password exists in Terraform state or environment variables. Deploys use GitHub OIDC (no long-lived keys). |
| Vendor segregation | Each feed belongs to one vendor. A vendor's change file cannot alter another vendor's loans: CHG06 sends the change to dual control, which applies only for a documented servicing transfer. A suspended or offboarded vendor's files are recorded but not processed. Moving a feed between vendors needs the SME role and is audited. |
| Vendor connections | A pull schedule needs maker-checker. Hosts and buckets are allow-listed in configuration and in IAM. SFTP host keys are pinned. Credentials stay in Secrets Manager only. Egress on tcp/22 is limited to vendor CIDRs. Remote files are read-only. |
| Edge protection | WAF with managed common rules, known bad inputs (Log4j) and IP reputation, a rate limit, and redacted logging. Geo restriction. Security headers and CSP. |

## 3. Operator runbook (summary)

| Situation | What to do |
|---|---|
| Batch **blocked** by pre-flight | Open the batch in Import Monitor. Either use "Create mapping fix", get SME approval and then "Resume on approved mapping", or have an SME/Compliance user override with a reason. |
| Batch stuck **running** | The worker requeues it automatically after 10 minutes without a heartbeat (`python -m lbp.cli recover` forces this). It resumes from the last committed micro-batch. |
| Reconciliation **mismatch** | An SNS alert fires and the batch is marked failed. Compare `staged / boarded / held / rejected`, and check `LOAD` and `SCHEMA` exceptions. |
| **T1 auto-suspended** | Policy & Audit shows the override rate. Investigate the rolled-back fixes. Re-enabling needs two Compliance users. |
| Emergency stop of AI fixes | One Compliance user sets `t1_enabled=false`. Switching it off is allowed with a single approver; switching it on needs two. |
| Secret rotated | Nothing to do. New connections fetch the current password. |
| Audit integrity check | Run `python -m lbp.cli verify-audit` (schedule it daily). A non-zero exit code means the chain is broken. |
| Retention | Run `python -m lbp.cli purge` (daily; default 30 days after boarding). |
| Deploy | Use the `deploy` workflow: build Lambda image and Glue wheel → plan → upload wheel → apply → signing key (first run) → `migrate` Lambda (migrations + publish configurations) → publish web → smoke test. |
| Glue run **failed** | An EventBridge rule pages on any FAILED / TIMEOUT Glue run, and Step Functions marks the batch failed. Fix the cause and Resume the batch: it restarts from its last checkpoint. A failed Spark run falls back to the standard engine automatically. |
| Batch failed with **configuration** error | The feed's published configuration is missing, unsigned or stale. Open the feed's "Glue config" chip; Republish (SME) if the approved mapping is newer than the publication, then Resume. |
| Vendor file **late / missed** | An SNS alert fires once per state. Chase the vendor, then use Pull now (pull schedules) or Waive with a reason. |
| Change file **waiting** | An earlier file is pending or a number is missing. It is released automatically when the earlier file completes. If the vendor confirms the number never existed, use Skip gap (with a reason). |
| Change file **out of order** | Discard it, or (SME) apply it with every change held for dual control. |
| Snapshot **truncation suspected** | Confirm with the vendor. Request a full resend, or (SME) raise the close reviews anyway. |
| **Scheduler silent** alarm | Check the `scheduler-tick` Lambda and its EventBridge schedule. `python -m lbp.cli tick` runs one pass by hand. |

## 4. Required before go-live (owner: PennyMac / Sonata)

1. **The real SSE data dictionary and rule set.** Replace `schema/sse_target.py` with the confirmed attributes and code lists. Migrate the remaining ~80 Hangfire stored-procedure rules.
2. **Integration with the live SSE load interface.** The platform writes a typed SSE staging table today. It must be connected to SSE's actual intake (stored procedures or API) and tested, including SSE-side constraints and throttling limits.
3. **SQL Server verification.** SQLite and PostgreSQL are verified here. Run the same suite against RDS SQL Server in CI; the `mssql` dialect, `OUTPUT` and pyodbc paths are not yet exercised.
4. **Parallel run.** Run in shadow mode alongside the current Hangfire flow for an agreed period (suggested: 2 weeks of production volume). Reconcile loan by loan before cut-over.
5. **Deployment into PennyMac's AWS account.** This needs ACM certificates, the custom domain, Cognito federated with the corporate IdP (SAML) with group mapping, and VPC/Transit Gateway alignment with PennyMac networking.
6. **Container build in CI.** The Docker registries were blocked in this build environment, so images have not been built here. Pin base images by digest once they are pulled through ECR.
7. **Security sign-off.** Threat model review, penetration test, InfoSec architecture review and a data classification sign-off.
8. **Model risk validation (SR 11-7)** of the AI mapping and exception proposals. Includes a live Bedrock evaluation; the LLM paths are implemented but have not been run against a live model.
9. **Disaster recovery.** Cross-region S3 replication, RDS cross-region snapshots, defined RTO/RPO and a tested restore. The single-region choices are marked in the Terraform skips.
10. **Performance test against real SSE.** Tune `glue_feed_concurrency`, the Spark job's worker cap and `LBP_SSE_THROTTLE_RPS` to the load SSE can absorb. Run the Glue jobs on the Glue service (the local verification uses Spark 4 and a stand-in `awsglue` module).
11. **Vendor delivery onboarding.** For each vendor, confirm with them:
    * load type and action codes
    * file numbering
    * protected-field list
    * due times and timezone
    * SFTP host, host key and credentials (and allow-list the host)
12. **UAT, training and on-call.** UAT with Loan Boarding, Ops, SME and Compliance users. Handover of the runbooks and alarms to the support team.

## 5. Throughput evidence

Load test results are recorded in `docs/load-test-1m.txt`.
