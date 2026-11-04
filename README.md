# PennyMac Loan Boarding Platform

This is a working build of the *Loan Boarding Modernization PoV (v1.2)*. It ingests loan tapes from different sources, maps them to the SSE schema with AI-assisted confidence scoring, and validates them with a versioned rules-as-code engine. It boards them in throttled, checkpointed micro-batches. Every failure is routed to a T1–T5 Exception Manager with human-in-the-loop guardrails. Analytics cover the six dashboards in the deck.

The application is a **React web app** over a thin control-plane API, and **all loan data integration runs on AWS Glue**, driven by what people configure in the web app. A mapping, delivery profile or rule change takes effect only after it is approved: approval compiles it into a signed **feed configuration** that the Glue jobs read. The same Python package runs on a laptop (SQLite, in-process worker) and on AWS (Glue, Lambda, Step Functions, RDS SQL Server, DynamoDB, Bedrock). See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

```
backend/            Python package `lbp` + FastAPI service + tests + scripts
  lbp/schema/       SSE target schema (~110 attributes, 5 modules, risk tiers, code lists)
  lbp/ingestion/    CSV / TXT / Excel parsing, profiling, PII detection and masking
  lbp/mapping/      AI mapping engine, no-code transform library, onboarding workflow
  lbp/rules/        JSON Logic engine, signed versioned registry, executor (canary/shadow), NL authoring
  lbp/exceptions/   classify → retrieve (RAG) → propose → route, T1–T5 policy, maker-checker
  lbp/pipeline/     micro-batch pipeline, SSE loader with throttling, reconciliation
  lbp/config_store.py  approved settings -> signed feed configuration bundles (the only config Glue reads)
  lbp/glue_jobs.py  entry points the Glue jobs call (standard, Spark, replay, vendor pull)
  lbp/analytics/    six dashboards + natural-language "ask"
  lbp/api/          REST API (all /api routes from the deck)
aws/
  terraform/        VPC, S3 zones, KMS, RDS, DynamoDB, Glue jobs + VPC connection, Lambda, Step Functions,
                    EventBridge, API Gateway + Cognito, CloudFront + WAF, Athena, Redshift Serverless,
                    OpenSearch (k-NN), CloudWatch, CloudTrail
  glue/             lbp-feed (Glue 5.0), lbp-feed-spark (large tapes), lbp-vendor-pull; notebooks/ for development
  lambdas/          control plane only: file arrival, route, finalize, scheduler tick, migrate, API (Mangum)
  stepfunctions/    route -> Glue (.sync) -> finalize -> notify
frontend/           React web app: list pages with detail, review and approval in pop-up dialogs
sample_data/        synthetic tapes for the 4 sources (no real borrower data)
```

## Run it locally

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest                          # add LBP_TEST_DATABASE_URL to run on PostgreSQL
uvicorn lbp.api.main:app --port 8000      # API on :8000

# in another shell, build the web app (served by the API at http://localhost:8000)
cd frontend && npm install && npm run lint && npm run build

# thin seed: 4 sample sources, one file each
curl -X POST "localhost:8000/api/demo/seed?rows_per_source=2000" -H "X-User: admin" -H "X-Roles: admin"
```

**Full demo-kit scenario** (vendors, schedules, change files, talk-track state):

```bash
./demo_kit/start_demo.sh          # compact scale; open http://localhost:8000
./demo_kit/start_demo.sh --full   # sales scale (~3k rows/feed)
```

Or, with the API already running as Platform Admin: **Policy & Audit → Load demo scenario…** (`POST /api/demo/setup`). Pass `force: true` to wipe existing data. Live upload files land under `$LBP_DATA_DIR/demo_uploads/2_upload_live`. See `demo_kit/DEMO_GUIDE.md`.

Or run `docker compose up --build` from the repo root.

Use the "Signed in as" switcher in the web app to act as different roles. Most guardrails only show when two people are involved: an SME approving an analyst's mapping, a checker approving a T4 maker, Compliance clearing a T5 block.

**AI provider.** The default is `LBP_AI_PROVIDER=heuristic`, which makes no model calls. Set `bedrock` (with AWS credentials) or `anthropic` (with `ANTHROPIC_API_KEY`) to have an LLM re-rank mappings, draft rules from English, and suggest exception fixes. Every model call has a deterministic fallback. PII is never sent to a model.

**Clickable demo.** `npm run build:demo` produces `frontend/dist-demo/index.html`. It is one file that runs with no backend, using a snapshot produced by `backend/scripts/export_demo_snapshot.py`.

## How the deck maps to the code

| Deck | Where |
|---|---|
| Config-driven ingestion (CSV/TXT/Excel), format auto-detect | `ingestion/parser.py` |
| Profiling, AI PII detection, dynamic masking | `ingestion/profiler.py`, `ingestion/pii.py` |
| AI mapping, semantic name match, confidence scores | `mapping/engine.py` (+ `ai.py` LLM re-rank) |
| No-code transforms: casts, lookups, N:1 composites, defaults | `mapping/transforms.py` (24 ops) |
| SME approval workflow | `mapping/service.py` (analyst ≠ approver, SME role) |
| Change any mapping: re-point to another target, add a target, remove; one source → many targets (1:N) | `mapping/service.py` (`retarget_field`, `add_field`, `suggest_for`), curated 1:N suggestions in `mapping/engine.py` |
| Mapping UI: per-field transformation steps, sample trace, DQ checks, test-before-save | `mapping/inspect.py` (`/api/mappings/{id}/fields/{target}/inspect`, `/api/mappings/{id}/dq`) |
| Micro-batches 10K–50K, parallel workers, throttling, checkpoint/resume, reconciliation | `pipeline/batch.py`, `pipeline/loader.py` |
| Rules-as-code, registry, lifecycle Author → Review → Deploy → Monitor → Retire | `rules/` (tests must pass; Compliance gate for regulated rules; canary and shadow) |
| LLM-assisted rule authoring (English → DSL + tests) | `rules/authoring.py` |
| Exception pipeline: Classify → Retrieve → Propose → Route | `exceptions/manager.py`, `retrieval.py`, `fixers.py` |
| Confidence × risk routing T1–T5, thresholds in policy store | `exceptions/policy.py` |
| Six dashboards + QuickSight Q-style questions | `analytics/service.py` |
| AWS services table (slide 13) | `aws/terraform/*.tf` |
| Vendors own feeds (vendor → feed → mapping versions); every page can be scoped to one vendor; vendor-level integrity (a vendor's file changes only its loans, snapshots cover the whole vendor portfolio, suspension stops processing) | `lbp/vendors.py`, Vendors & Mapping page, vendor selector in the side bar |
| Incremental and snapshot files from many vendors, per-vendor ordering, delivery scheduler | `pipeline/delivery.py`, `incremental.py`, `changes.py`, `sequencing.py`, `scheduling/` (see [docs/INCREMENTAL_AND_SCHEDULING.md](docs/INCREMENTAL_AND_SCHEDULING.md)) |

## Security and operations

The detail is in **[docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md)**: verification evidence, compliance controls, runbooks and the go-live checklist. In short:

* **Auth.** Outside local, Cognito JWTs are verified in-process. `ROUTE_ROLES` in `lbp/api/main.py` is the single role matrix, deny-by-default for writes. The web app signs users in with the Cognito hosted UI (PKCE).
* **Fail-safe config.** The API refuses to start in AWS with dev auth, SQLite, demo routes, wildcard CORS or an un-migrated schema (`python -m lbp.cli check-config`).
* **Database.** Schema changes go through Alembic migrations (`python -m lbp.cli migrate`). Credentials come from the RDS-managed, rotating secret and are read on each new connection.
* **Integrity.** Micro-batch data and checkpoints commit atomically. Batch leases with heartbeats recover crashed workers. Identical files are refused unless a reason is given. SSE schema violations and database rejections become exceptions, never crashed batches.
* **Audit.** The audit log is hash-chained (`python -m lbp.cli verify-audit`). An NPI retention purge is available (`python -m lbp.cli purge`).
* **Signed configuration.** Glue boards loans only from a feed configuration that was approved and signed (HMAC, key in Secrets Manager). A draft, a hand-edited bundle or a stale one is refused. Safety switches (T1 kill switch, vendor suspension) stay live and act immediately.
* **CI/CD.** `.github/workflows/ci.yml` runs ruff, tests on SQLite and PostgreSQL, the migration round trip, a Glue wheel build, a 100K throughput check, ESLint, the web and demo builds, npm audit, tofu validate, checkov, the image build and a Trivy scan. `deploy.yml` uses OIDC, builds the Lambda image and the Glue wheel, applies, sets the signing key once, runs migrations through the `migrate` Lambda, publishes the web app and ends with a smoke test.

## Production safeguards

These protect SSE once the platform runs daily rather than in a demo:

| Safeguard | What it does | Where |
|---|---|---|
| Schema-drift pre-flight | Every batch is checked against the approved mapping before any row loads. Missing or renamed columns, date-format changes, new columns and sudden blanks are detected. It runs the approved transforms on a sample and blocks only when a required or high-risk SSE field would break. Rename and date-format fixes become a draft mapping version for SME approval. The batch resumes on it, or an SME or Compliance user overrides with a recorded reason. | `pipeline/preflight.py`, Import Monitor |
| Re-board protection | A loan already in SSE (DUP02) or repeated in the file (DUP01) is never silently overwritten. It goes to dual control with a field-by-field comparison against the boarded record. | `pipeline/batch.py::detect_duplicates` |
| Value translation | For coded fields, every distinct source value is shown with its SSE value and row count, and untranslated codes are flagged. Fixing a code once adds a source-specific value map to the mapping. | `mapping/inspect.py::value_coverage` |
| Mapping memory | SME approvals and rejections are remembered per source column name. Familiar columns on a new source start pre-mapped, rejected pairs are suppressed, and value translations carry over. Formats are always re-derived from the new file. | `mapping/service.py::record_memory`, `mapping/engine.py` |
| Suggestion self-check | Every proposed transform is run on the sample. Any that fail on more than 5% of rows are demoted to review. | `mapping/engine.py::_self_check` |
| Root-cause grouping | Open exceptions are grouped by source, rule and field into likely mapping or source defects. Each group gets a recommended fix and a link into the mapping. | `analytics/service.py::systemic_issues` |
| Replay | After a fix, held loans are re-run on the current mapping and rules. Reviewer corrections carry over, and in-file duplicates stay blocked. Old exceptions are superseded but kept for audit. You can preview a replay before writing anything. | `pipeline/replay.py` |
| Mapping versions | A live mapping is edited as v2, with a field-level diff against v1. It only replaces v1 after SME approval. | `mapping/service.py::diff_versions` |
| Change files | Each vendor delivers full tapes, incremental change files (add / update / close) or full snapshots. Updates merge onto the live SSE record and write only changed fields, under optimistic concurrency, so a newer value is never overwritten. Protected fields go to dual control, closes never delete, and a snapshot that looks truncated cannot close loans. | `pipeline/incremental.py`, `pipeline/changes.py` |
| File order | Change files apply in the vendor's sequence. A file waits for missing numbers; an older file is held as out of order. | `pipeline/sequencing.py` |
| Delivery scheduler | Each vendor's due times run in the vendor's timezone on the Fed business calendar. Late and missed files raise alerts, and SFTP/S3 pulls serve vendors that don't push files. Schedules go through maker-checker. | `scheduling/`, Vendor Deliveries page |

## PoC success criteria (slide 14), measured on synthetic data

| Criterion | Result |
|---|---|
| LDS running on AWS | Terraform, the Glue jobs and the Lambda image are written; `tofu validate` and checkov pass. **Not yet applied to a real account** (see below). |
| > 70% auto-mapped, human review < 30 min | 100% of columns auto-mapped at ≥ 0.80 confidence on all 4 sample sources. Composite name/address splits and cents→dollars are detected. |
| Clear Pass/Warn/Fail with actionable exceptions | 22 rules migrated. Every failure carries a tier, a proposal with rationale, and precedents. |
| 100K+ loans through the full pipeline, proves 1M/24h | 100,000 loans in 29 s on a 2-core sandbox with SQLite (about 3,400 loans/s, roughly 296M per 24h). Run `python scripts/load_test.py --rows 100000`. |
| Real-time pipeline visibility | Import Monitor with live progress, throughput, ETA and per-micro-batch timing. |

The throughput figure measures the platform itself. In production the ceiling will be what SSE can absorb, which is why `glue_feed_concurrency` (concurrent Glue runs) and `LBP_SSE_THROTTLE_RPS` exist.

## What still needs PennyMac input or real infrastructure

- **SSE data dictionary.** `schema/sse_target.py` is a realistic stand-in. Replace it with the confirmed ~100 attributes and code lists.
- **The real ~100 stored-procedure rules.** 22 representative rules are migrated. The rest need to be extracted from the Hangfire `JobStepsXML` and stored procedures.
- **LDS IntelliMap.** The mapping, DQ and PII engine here is a self-contained stand-in behind the same responsibilities. It can be swapped for, or wrapped around, the real accelerator.
- **AWS deployment.** `tofu validate` passes and checkov reports 0 failures, but nothing has been planned or applied against a real account. The Glue jobs are verified locally (standard engine directly, Spark engine on a local Spark 4 cluster through a stand-in `awsglue` module, orchestration against mocked AWS); they have not run on the Glue service itself. The SQL Server (pyodbc) path is untested; PostgreSQL is verified. See the go-live checklist.
- **QuickSight.** Dashboards are served by the API and the web app. Building them as embedded QuickSight analyses over the Redshift views is not done yet.
- **Bedrock / Anthropic paths.** These are implemented but not exercised against a live model in this build.

All sample data is synthetic and generated by `lbp/samples.py`.
