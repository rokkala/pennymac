# LBP PoC — AWS deployments inventory

**Account:** `178137476317`  
**Region:** `ap-southeast-2` (Sydney)  
**Code / env name:** `lbp-poc`  
**IaC:** `aws/terraform/` (`env/poc.tfvars`)  
**As of:** 2026-11-09  

> **Credentials:** this document lists *where* secrets live (names / ARNs / usernames).  
> It does **not** contain passwords, signing keys, or temporary tokens.  
> Retrieve secrets with `aws secretsmanager get-secret-value` (authorized operators only).

---

## 1. Quick access

| What | Value |
|------|--------|
| Web (CloudFront) | `https://d1cb8j6s1t2rhm.cloudfront.net` |
| API (HTTP API) | `https://g64hjc163k.execute-api.ap-southeast-2.amazonaws.com` |
| Cognito hosted UI domain | `lbp-poc-178137476317.auth.ap-southeast-2.amazoncognito.com` |
| Cognito user pool | `ap-southeast-2_tyMWAc4f2` (`lbp-poc`) |
| Cognito app client | `lbp-poc-web` / id `2697s2ud51n00r3f8gubhigdlh` (also SSM `/lbp-poc/app/cognito_client_id`) |
| ECR images | `178137476317.dkr.ecr.ap-southeast-2.amazonaws.com/lbp-poc` |
| Boarding state machine | `arn:aws:states:ap-southeast-2:178137476317:stateMachine:lbp-poc-boarding` |

Auth mode for the API: JWT via Cognito (`LBP_AUTH_MODE=jwt`).

---

## 2. Credentials & secrets

| Code name | Type | Purpose | How to use |
|-----------|------|---------|------------|
| `rds!db-e097ef9b-701f-4653-8b3a-86137f0635bc` | Secrets Manager (RDS-managed) | Postgres master password for `lbpadmin` | App Lambdas/Glue read via `LBP_DB_SECRET_ARN` |
| DB user | — | `lbpadmin` | Host `lbp-poc.cf2imkyugyfx.ap-southeast-2.rds.amazonaws.com:5432`, database `lbp` |
| `lbp-poc/config-signing-key` | Secrets Manager | HMAC key for signed feed config bundles | `LBP_CONFIG_SIGNING_SECRET_ARN` |
| `redshift!lbp-poc-lbpadmin` | Secrets Manager | Redshift Serverless admin (if namespace present) | Analytics path; not required for boarding |
| Cognito users | Cognito User Pool | Interactive login for the web/API | Pool `lbp-poc`; client `lbp-poc-web` |
| `/lbp-poc/app/cognito_client_id` | SSM Parameter | App client id | Read by web/config |
| `/lbp-poc/app/cognito_domain` | SSM Parameter | Hosted UI domain | Read by web/config |
| `alias/lbp-poc-data` | KMS | Data encryption key | Trail / data encryption |
| IAM instance/task roles | IAM | Runtime AWS auth | No long-lived access keys in app code |

**Vendor SFTP / pull credentials** (when configured): Secrets Manager prefix from env `LBP_VENDOR_SECRET_PREFIX` (see Lambda env on `lbp-poc-api` / scheduler).

---

## 3. Data plane — Glue jobs

| Code name | Brief description |
|-----------|-------------------|
| `lbp-poc-feed` | Standard boarding job (Glue 5.0, driver-oriented). Map → validate → triage → load for smaller / non-Spark tapes. |
| `lbp-poc-feed-spark` | Spark job for large full CSV/TXT tapes above `LBP_GLUE_THRESHOLD_ROWS` (PoC default 500k). Materializes clean/dirty parts under `bulk-load/`. |
| `lbp-poc-feed-load` | Load job: COPY clean + dirty parts into Postgres, reconcile, complete batch. |
| `lbp-poc-vendor-pull` | Pulls vendor files (SFTP/S3) into the raw bucket so they arrive like push uploads. |

Glue connection: `lbp-poc-vpc` (VPC access to RDS/S3).  
IAM role: `lbp-poc-glue`.

---

## 4. Control plane — Lambdas

All image-based from ECR `lbp-poc` unless noted. Role: `lbp-poc-lambda`.

| Code name | Handler | Brief description |
|-----------|---------|-------------------|
| `lbp-poc-on-file-arrival` | `handlers.on_file_arrival` | EventBridge on `raw/incoming/<feed_id>/…` → `create_batch` → start Step Functions. |
| `lbp-poc-route` | `handlers.route_batch` | Picks standard vs Spark Glue job from rows/format/load type. |
| `lbp-poc-finalize` | `handlers.finalize_batch` | After Glue: read outcome; dispatch queued followers. |
| `lbp-poc-mark-failed` | `handlers.mark_failed` | Marks batch failed (skips active `running`/`pausing` unless force). |
| `lbp-poc-scheduler-tick` | `handlers.scheduler_tick` | Delivery windows / late alerts; may start vendor-pull. |
| `lbp-poc-migrate` | `handlers.migrate` | Deploy step: Alembic migrate, seed rules, publish feed configs. |
| `lbp-poc-api` | `handlers.api` | FastAPI (Mangum) behind API Gateway — config, exceptions, ops UI API. |

---

## 5. Orchestration & events

| Code name | Brief description |
|-----------|-------------------|
| `lbp-poc-boarding` | Step Functions: Route → Glue (feed or spark→load) → Finalize; failure → mark-failed / notify. |
| `lbp-poc-file-arrival` | EventBridge rule: S3 Object Created on raw `incoming/` → `on-file-arrival`. |
| `lbp-poc-glue-failed` | EventBridge rule: Glue job failures → alerting path. |
| `lbp-poc-delivery-tick` | EventBridge Scheduler → `scheduler-tick` (delivery cadence). |
| `lbp-poc-alerts` | SNS topic for pipeline / ops alerts. |

IAM: `lbp-poc-sfn`, `lbp-poc-scheduler`.

---

## 6. Storage

| Code name | Brief description |
|-----------|-------------------|
| `lbp-poc-raw-178137476317` | Vendor landing zone (`incoming/<source_id>/…`, uploads). |
| `lbp-poc-processed-178137476317` | Parquet, `bulk-load/`, signed `config/feeds/`, Glue wheel. |
| `lbp-poc-audit-178137476317` | Audit / CloudTrail-related storage. |
| `lbp-poc-athena-178137476317` | Athena query results. |
| `lbp-poc-web-178137476317` | Static frontend (CloudFront origin). |
| `lbp-poc-rule-registry` | DynamoDB — published business rules. |
| `lbp-poc-policy-store` | DynamoDB — policy / governance store. |

---

## 7. Database & analytics

| Code name | Brief description | Credentials |
|-----------|-------------------|-------------|
| RDS `lbp-poc` | PostgreSQL **16.13**, `db.t4g.medium`, 200 GB, single-AZ. App DB name **`lbp`**. | User `lbpadmin`; password in RDS-managed secret above. Endpoint in §1/§2. |
| Athena workgroup `lbp-poc` | Ad-hoc SQL over processed/audit data. | Uses caller IAM + results bucket. |
| Redshift Serverless namespace/workgroup `lbp-poc` | Analytics warehouse (**AVAILABLE**). IAM `lbp-poc-redshift` + secret `redshift!lbp-poc-lbpadmin`. | Admin user via that secret; not on the boarding hot path. |

---

## 8. Front door & identity

| Code name | Brief description |
|-----------|-------------------|
| API Gateway HTTP API `lbp-poc` (`g64hjc163k`) | Proxies to `lbp-poc-api`; Cognito JWT authorizer on protected routes. |
| CloudFront `E357ZHZMNR3JSH` | SPA + API origins (`lbp-poc-web` S3 + API Gateway). |
| Cognito user pool `lbp-poc` | Users + role groups for the app. |
| Cognito client `lbp-poc-web` | Browser / SPA OAuth client. |

---

## 9. Network

| Code name | Brief description |
|-----------|-------------------|
| VPC `lbp-poc` (`vpc-02ee4461175f5d96b`) | `10.42.0.0/16` |
| Subnets | Public ×2, private ×2, db ×2 (`ap-southeast-2a/b`) |
| SG `lbp-poc-app` | Lambdas / Glue app egress (HTTPS, DB, optional SFTP) |
| SG `lbp-poc-db` | Postgres ingress from app SG |
| NAT `nat-0419b5a1b56295a98` | Private subnet egress |
| IGW `igw-02add634611884378` | Public subnet internet |
| VPC endpoints | S3 + DynamoDB gateway endpoints (Terraform) |

---

## 10. Security, IAM, monitoring

| Code name | Brief description |
|-----------|-------------------|
| IAM `lbp-poc-lambda` | Control-plane Lambdas |
| IAM `lbp-poc-glue` | Glue jobs |
| IAM `lbp-poc-sfn` | Step Functions |
| IAM `lbp-poc-scheduler` | Scheduler invoke path |
| IAM `lbp-poc-rds-monitoring` | RDS Enhanced Monitoring |
| IAM `lbp-poc-rds-s3-import` | `aws_s3` table import into Postgres |
| IAM `lbp-poc-cloudtrail-logs` | CloudTrail → logs |
| IAM `lbp-poc-redshift` | Redshift Serverless access to data |
| KMS `alias/lbp-poc-data` | Data key |
| CloudTrail `lbp-poc-audit` | API audit trail |
| SNS `lbp-poc-alerts` | Alert fan-out |
| CW alarms | SFN failed, Glue failed, RDS CPU, failure rate, scheduler silent/errors (see `monitoring.tf`) |
| CW dashboard | Pipeline dashboard (Terraform `aws_cloudwatch_dashboard.pipeline`) |

---

## 11. Container images

| Code name | Brief description |
|-----------|-------------------|
| ECR `lbp-poc` | Lambda container images (tags such as `lambda-app6`) and related artifacts. |

Deploy flow (typical): build/push image → update Lambda functions → invoke `lbp-poc-migrate`.

---

## 12. Not in permanent stack (scratch / one-shots)

These may leave **log groups** only; functions are deleted after use:

- `lbp-poc-wipe`, `lbp-poc-clear-loads`, `lbp-poc-dbcheck`, `lbp-poc-qsrc`, `lbp-poc-demo-setup` (historical)

Do not treat them as production entry points.

---

## 13. How boarding uses this stack

```
Vendor file → s3://lbp-poc-raw-…/incoming/<source_id>/…
  → EventBridge lbp-poc-file-arrival → Lambda on-file-arrival
  → Step Functions lbp-poc-boarding
       → route → Glue feed OR (feed-spark → feed-load)
       → finalize
  → rows in RDS Postgres `lbp` (staging / sse_loans / exceptions)
```

Threshold for Spark (PoC): `LBP_GLUE_THRESHOLD_ROWS` (Terraform var `glue_threshold_rows`, default `500000`).

---

## 14. Operator cheat-sheet (no secret values)

```bash
# Who am I
aws sts get-caller-identity --region ap-southeast-2

# DB endpoint + secret name (password not printed)
aws rds describe-db-instances --db-instance-identifier lbp-poc --region ap-southeast-2 \
  --query 'DBInstances[0].Endpoint'

aws secretsmanager describe-secret \
  --secret-id 'rds!db-e097ef9b-701f-4653-8b3a-86137f0635bc' --region ap-southeast-2

# Recent boarding runs
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:ap-southeast-2:178137476317:stateMachine:lbp-poc-boarding \
  --region ap-southeast-2 --max-results 5
```
