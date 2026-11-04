# Graph Report - pennymac  (2026-11-04)

## Corpus Check
- 164 files · ~457,047 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1740 nodes · 4343 edges · 119 communities (104 shown, 15 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 270 edges (avg confidence: 0.74)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- AI Mapping Engine
- SFTP File Pullers
- Delivery Scheduling
- FastAPI Route Mounts
- Frontend Package Deps
- Boarding Batch Pipeline
- Frontend Delivery UI
- Local Scheduler Config
- Field Transforms
- Demo Sample Generator
- CLI Worker DB
- Governance Rules UI
- Exception Decision APIs
- Mapping Override APIs
- Signed Config Store
- Cron Business Calendar
- Analytics Charts UI
- Rules Exception APIs
- Vendor Feed Profiles
- Preflight Mapping Checks
- File Sequencing Gate
- JSON Logic Rules
- Rule Registry Store
- Vendors Imports UI
- Exception Batch Compare
- Exception Policy
- Exception Manager Core
- API Enhancement Tests
- Lambda Path Tests
- File Format Parser
- Frontend Mock API
- Audit History APIs
- Security Load Tests
- Analytics Service
- Builtin Rule Validators
- Frontend Auth Personas
- AWS Lambda Handlers
- Incremental Load Tests
- Deliveries Schedule UI
- Mapping Field Inspect
- Change File Apply
- Sources Mapping UI
- Exception RAG Retrieval
- PII Profiling
- Delivery Profile Logic
- Rule Authoring LLM
- Rule Executor
- Rule Registry Lifecycle
- Frontend Cognito Auth
- Glue Job Entry Points
- Local S3 Storage
- Glue Job Tests
- Incremental Row Planner
- SSE Target Loader
- Exceptions Console UI
- Source Upload APIs
- Review Focus
- OpenSearchPrecedentIndex
- retention_purge
- Change Control Docs
- Backend Dependencies
- Docker Compose Stack
- Platform Architecture Docs
- OIDC Deploy Workflow
- Vendor CRUD APIs
- Transform Unit Tests
- __init__.py
- Signed Glue Config Docs
- CI Workflow Jobs
- Load Test Evidence Docs
- API Auth Hardening
- Schedule CRUD APIs
- test_concurrency.py
- Vendor Sequencing Docs
- Preflight Override Path
- SFTP Scheduler Docs
- React Error Boundary
- Glue Spark Feed Job
- demo_setup
- remap_batch
- Glue Feed Job
- Glue Vendor Pull Job
- Console Shell Docs
- Auth Privacy Docs
- Scoped Vendor API
- Backend Package Meta
- canCap
- Demo kit: test data and a ready-to-run demo
- OpenSearchPrecedentIndex
- verify_audit_chain
- run_demo_setup
- start_demo.sh
- conftest.py
- wipe_data_dir
- OpenSearchPrecedentIndex
- DuplicateFileError
- _vendor_call
- authorize
- _safe_error
- default_rules.py
- inspect_field_draft
- update_policy
- retention_purge
- progress.md

## God Nodes (most connected - your core abstractions)
1. `get_engine()` - 113 edges
2. `get_settings()` - 73 edges
3. `User` - 58 edges
4. `useApi()` - 53 edges
5. `run_batch()` - 52 edges
6. `create_batch()` - 50 edges
7. `audit()` - 46 edges
8. `api()` - 46 edges
9. `canCap()` - 46 edges
10. `fmt()` - 44 edges

## Surprising Connections (you probably didn't know these)
- `docker-compose api Service` --implements--> `Control-Plane FastAPI`  [INFERRED]
  docker-compose.yml → README.md
- `Schema-Drift Pre-Flight` --semantically_similar_to--> `Snapshot Truncation Guard`  [INFERRED] [semantically similar]
  README.md → docs/INCREMENTAL_AND_SCHEDULING.md
- `CI 100K Throughput Regression` --semantically_similar_to--> `PoC 100K+/1M Throughput Criterion`  [INFERRED] [semantically similar]
  .github/workflows/ci.yml → README.md
- `on_file_arrival()` --calls--> `dispatch()`  [INFERRED]
  aws/lambdas/handlers.py → backend/lbp/dispatch.py
- `on_file_arrival()` --calls--> `create_batch()`  [INFERRED]
  aws/lambdas/handlers.py → backend/lbp/pipeline/batch.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Glue Data-Plane Job Trio** — docs_architecture_lbp_feed, docs_architecture_lbp_feed_spark, docs_architecture_lbp_vendor_pull [EXTRACTED 1.00]
- **Incremental Change Exception Rules** — docs_incremental_and_scheduling_chg01, docs_incremental_and_scheduling_chg05, docs_incremental_and_scheduling_chg06, docs_incremental_and_scheduling_load_type_incremental [EXTRACTED 1.00]
- **CI Pipeline Job Set** — _github_workflows_ci_backend_job, _github_workflows_ci_frontend_job, _github_workflows_ci_infrastructure_job, _github_workflows_ci_image_job [EXTRACTED 1.00]

## Communities (119 total, 15 thin omitted)

### Community 0 - "AI Mapping Engine"
Cohesion: 0.15
Nodes (27): accept_all(), add_field(), approve(), _columns(), diff_versions(), get_mapping(), MappingError, new_version() (+19 more)

### Community 1 - "SFTP File Pullers"
Cohesion: 0.13
Nodes (18): allowed_hosts(), fetch_new(), LocalPuller, make_puller(), _ok_name(), Puller, PullError, Path (+10 more)

### Community 2 - "Delivery Scheduling"
Cohesion: 0.13
Nodes (41): notify(), Operational alerts: always logged and audited; published to SNS when LBP_ALERT_T, _acquire_leader(), create_schedule(), decide(), effective(), get_schedule(), list_deliveries() (+33 more)

### Community 3 - "FastAPI Route Mounts"
Cohesion: 0.06
Nodes (37): a_ai(), a_ask(), a_dq(), a_exceptions(), a_exec(), a_import(), a_sources(), a_systemic() (+29 more)

### Community 4 - "Frontend Package Deps"
Cohesion: 0.06
Nodes (34): eslint, @eslint/js, eslint-plugin-react, eslint-plugin-react-hooks, dependencies, react, react-dom, devDependencies (+26 more)

### Community 5 - "Boarding Batch Pipeline"
Cohesion: 0.08
Nodes (45): Pure (no DB writes) triage used inside the pipeline workers' parent process., Triage, emit_metrics(), partition_processor(), persist_stream(), process_batch(), pull(), Entry points for the AWS Glue data plane (thin wrappers in aws/glue/ call these) (+37 more)

### Community 6 - "Frontend Delivery UI"
Cohesion: 0.27
Nodes (11): CELL, cronFrom(), Deliveries(), DOW, HistoryStrip(), OPEN, presetOf(), ScheduleEditor() (+3 more)

### Community 7 - "Local Scheduler Config"
Cohesion: 0.27
Nodes (10): is_s3(), local_path(), persist_upload(), Path, File storage: local paths in development, S3 in AWS (ECS task disks are ephemera, Store an uploaded file durably and return its URI (S3 in AWS, the local path oth, _s3(), _split() (+2 more)

### Community 8 - "Field Transforms"
Cohesion: 0.11
Nodes (22): _empty(), _num(), _op_cents_to_dollars(), _op_concat(), _op_default(), _op_divide(), _op_lookup(), _op_normalize_rate() (+14 more)

### Community 9 - "Demo Sample Generator"
Cohesion: 0.10
Nodes (27): _build_scenario(), data_is_present(), DemoSetupConflict, Any, Exception, Path, Build the demo-kit sales scenario into a local data dir.  Used by CLI, start_dem, Port of export_demo_snapshot scenario; row counts scale for compact/full. (+19 more)

### Community 10 - "CLI Worker DB"
Cohesion: 0.14
Nodes (22): audit(), batch_snapshot_reviews(), lifespan(), Override, override_preflight(), Local single-process mode: tick the delivery scheduler every minute and start wh, Public settings the web app needs to sign users in (no secrets)., Re-run held loans through the source's current mapping and rules (dry_run previe (+14 more)

### Community 11 - "Governance Rules UI"
Cohesion: 0.12
Nodes (27): HBars(), heatColor(), Lines(), niceMax(), Segments(), Sparkline(), Tip(), VBars() (+19 more)

### Community 12 - "Exception Decision APIs"
Cohesion: 0.13
Nodes (27): _apply_memory(), _detect_composites(), name_similarity(), normalize(), AI-assisted source-to-target mapping with confidence scoring.  Scoring combines, Reuse only the portable part of a remembered transform: its value translations., Run every proposed transform on the sample; demote suggestions that fail on real, Re-rank candidates with what humans approved/rejected for this column name befor (+19 more)

### Community 13 - "Mapping Override APIs"
Cohesion: 0.08
Nodes (26): demo_setup(), DemoSetupIn, inspect_field_draft(), PersonaResetIn, personas_screens_put(), personas_users_reset(), PolicyChange, Purge (+18 more)

### Community 14 - "Signed Config Store"
Cohesion: 0.17
Nodes (22): _bucket(), build(), bundle_json(), _canonical(), ConfigError, FeedConfig, _key(), load() (+14 more)

### Community 15 - "Cron Business Calendar"
Cohesion: 0.15
Nodes (20): BatchBusyError, _chunks(), Exception, RuntimeError, In-process runner (local API mode): run the batch, then any files it released fr, Error text for storage/UI: first line only, never the SQL parameters (they can c, _run_and_follow(), run_batch() (+12 more)

### Community 16 - "Analytics Charts UI"
Cohesion: 0.11
Nodes (40): scoped(), takeIntent(), AIDash(), ExceptionsDash(), SourcesDash(), VendorsDash(), ACTION_LABEL, CHANGE_RULES (+32 more)

### Community 17 - "Rules Exception APIs"
Cohesion: 0.17
Nodes (20): get_delivery(), list_sources(), How a file named like this would be treated: load type, file-level action, seque, test_filename(), incremental_context(), Per-batch context for change files (from the published feed configuration): effe, decide_profile(), DeliveryError (+12 more)

### Community 18 - "Vendor Feed Profiles"
Cohesion: 0.24
Nodes (16): _clean(), create_vendor(), ensure_vendor(), get_vendor(), list_vendors(), move_feed(), ValueError, Vendors: the counterparty that owns one or more feeds.      Vendor (Cornerstone (+8 more)

### Community 19 - "Preflight Mapping Checks"
Cohesion: 0.12
Nodes (28): apply(), _base_with(), catalog(), _compile_node(), compile_tree(), decompile(), _field(), _leaf_expr() (+20 more)

### Community 20 - "File Sequencing Gate"
Cohesion: 0.17
Nodes (21): prepare_large(), Driver step 1: config, lease and pre-flight. Returns (cfg, batch) or (None, stat, _acquire_lease(), Atomically move a batch into 'running' for one worker. False if another worker h, next_integer(), acquire(), advance(), apply_out_of_order() (+13 more)

### Community 21 - "JSON Logic Rules"
Cohesion: 0.16
Nodes (18): Shadow-style impact estimate: how many recently staged loans would this version, rule_impact(), _cmp(), compile_logic(), _get(), JsonLogicError, _loose_eq(), _num() (+10 more)

### Community 22 - "Rule Registry Store"
Cohesion: 0.07
Nodes (26): Classify/propose/route every failure; apply T1 fixes and re-validate. Pure (no D, _triage_results(), _bucket(), Evaluation, Stateless rule executor (runs in-process, in worker processes, on Lambda or ECS, RuleExecutor, RuleResult, DynamoRuleStore (+18 more)

### Community 23 - "Vendors Imports UI"
Cohesion: 0.16
Nodes (18): buildHtml(), capture(), __dirname, esc(), filesTable(), flowExecute(), flowHighLevel(), flowMonitor() (+10 more)

### Community 24 - "Exception Batch Compare"
Cohesion: 0.24
Nodes (11): _alerts(), Clock, _deliveries(), Delivery scheduler: cron + calendars, delivery lifecycle, alerts once, maker-che, _schedule(), test_delivery_lifecycle_received_late_missed_and_alerts_once(), test_leader_lease_and_idempotent_materialize(), test_local_pull_fetches_once_and_registers_batches() (+3 more)

### Community 25 - "Exception Policy"
Cohesion: 0.20
Nodes (7): AnthropicClient, BedrockClient, get_llm(), LLMClient, LLMMappingReranker, Pluggable LLM access used by mapping re-ranking, rule authoring (English -> DSL), Asks the model to choose among the heuristic top-K for each column.

### Community 26 - "Exception Manager Core"
Cohesion: 0.17
Nodes (11): _coerce(), ExceptionActionError, ExceptionManager, ValueError, Field-by-field comparison of an incoming duplicate with the loan already in SSE., Compliance has investigated outside EM (e.g. OFAC false positive) and records th, Undo a T1 auto-apply inside the rollback window (target < 5 min to execute)., On-demand LLM suggestion with masked context; stored as proposal, never auto-app (+3 more)

### Community 27 - "API Enhancement Tests"
Cohesion: 0.18
Nodes (16): maintenance_artifact(), maintenance_artifacts(), get_artifact(), list_artifacts(), MaintenanceError, _notebook_cells(), Exception, Path (+8 more)

### Community 28 - "Lambda Path Tests"
Cohesion: 0.17
Nodes (20): _aws(), _executions(), _load(), The AWS execution path (EventBridge -> Step Functions -> Lambda) exercised again, In AWS the scheduler Lambda never moves files itself: a due pull starts the lbp-, moto Step Functions + Glue, LBP in AWS mode (dispatch -> Step Functions, data mo, The deploy step: migrations (no-op on a current schema here) + a signed configur, LBP/Pipeline metrics (dashboard + failure-rate alarm) come from the Glue jobs no (+12 more)

### Community 29 - "File Format Parser"
Cohesion: 0.10
Nodes (36): _clean_header(), detect_format(), estimate_rows(), _iter_excel(), iter_rows(), ParsedFile, ParseOptions, Path (+28 more)

### Community 30 - "Frontend Mock API"
Cohesion: 0.15
Nodes (19): ARTIFACTS, cellsOf(), getMaintenanceArtifact(), listMaintenanceArtifacts(), ApiError, clone(), createMockApi(), fail() (+11 more)

### Community 31 - "Audit History APIs"
Cohesion: 0.17
Nodes (17): _alembic_cfg(), check_config(), _demo_setup(), main(), migrate(), Operator commands.      python -m lbp.cli migrate          apply database migrat, publish_all(), Republish every live feed (rule or policy changes affect all of them). (+9 more)

### Community 32 - "Security Load Tests"
Cohesion: 0.19
Nodes (9): _client(), RDS-managed secret is read per connection; Cognito client id comes from SSM (as, _rsa(), test_jwt_mode(), test_npi_never_in_error_messages_and_retention(), test_production_refuses_unsafe_config(), test_proposals_never_leak_npi_in_list_or_detail(), test_rotating_db_secret_and_ssm_settings() (+1 more)

### Community 33 - "Analytics Service"
Cohesion: 0.24
Nodes (14): ai_mapping_insights(), dq_scorecard(), exception_analytics(), executive_summary(), import_status(), _iso(), _label(), _names() (+6 more)

### Community 34 - "Builtin Rule Validators"
Cohesion: 0.27
Nodes (8): _get_bucket(), load_records(), SSE target loader: micro-batched, throttled upserts into the typed SSE loan tabl, Upsert [(sse_record, dq_status)] by loan_number. Returns rows written.      With, Insert, or replace a whole record (a full tape re-boarding an existing loan afte, to_sse_row(), TokenBucket, _write()

### Community 35 - "Frontend Auth Personas"
Cohesion: 0.22
Nodes (14): getPersona(), getVendorScope(), mockApi(), PERSONAS, setPersona(), setSignedIn(), setVendorScope(), vendorScope (+6 more)

### Community 36 - "AWS Lambda Handlers"
Cohesion: 0.13
Nodes (13): _api(), finalize_batch(), migrate(), on_file_arrival(), AWS Lambda entry points: the thin control plane around the Glue data plane.  Lam, EventBridge Scheduler (rate 5 minutes): delivery windows and late/missed alerts., Invoked once per deploy: Alembic migrations, default rule seed, and a signed con, API Gateway (HTTP API, payload v2) -> FastAPI. The bearer token is passed throug (+5 more)

### Community 37 - "Incremental Load Tests"
Cohesion: 0.26
Nodes (11): is_protected_change(), norm(), Comparable form of a field value (mapped record vs. typed SSE row)., _fail(), feeds_by_column(), plan_row(), Incremental and snapshot row planning (pure; runs inside the pipeline worker pro, (action, code) where action is None for an unrecognised code. (+3 more)

### Community 38 - "Deliveries Schedule UI"
Cohesion: 0.12
Nodes (22): read_policy(), effective_policy(), get_policy(), PolicyError, ValueError, Confidence x Risk routing policy (the hard gate).  Thresholds live in the Policy, Live override rate of AI auto-applied fixes (rollbacks + failed QA samples / T1, Configured policy plus automatic controls: T1 is suspended when its override rat (+14 more)

### Community 39 - "Mapping Field Inspect"
Cohesion: 0.12
Nodes (39): personas_screens(), personas_users(), _admin_count(), _cognito(), _cognito_create(), _cognito_groups_for(), _cognito_list(), _cognito_primary_role() (+31 more)

### Community 40 - "Change File Apply"
Cohesion: 0.13
Nodes (21): batch_loans(), Exception Manager: AI proposes, human disposes.  Resolution pipeline per failing, consensus(), If exact-match precedents agree, return (value, strength)., mask_record(), mask_value(), PII detection and dynamic masking.  Two signals are combined: column-name semant, partial: keep last 4 (SSN/phone) or first letter (name); hash: deterministic tok (+13 more)

### Community 41 - "Sources Mapping UI"
Cohesion: 0.46
Nodes (14): _boarded_pcg(), _pick(), Incremental / snapshot loads, change control and per-vendor sequencing (end to e, A reviewer corrected a value at boarding; the vendor's next snapshot re-sends th, _run(), _set_profile(), _sse(), test_incremental_sparse_updates_closes_and_change_control() (+6 more)

### Community 42 - "Exception RAG Retrieval"
Cohesion: 0.13
Nodes (19): batch_changes(), feed_config(), get_batch(), get_source(), list_rules(), loan_history(), Readiness for the load balancer: database reachable and schema current, rule set, What the data plane (Glue) will run for this feed: the current signed publicatio (+11 more)

### Community 43 - "PII Profiling"
Cohesion: 0.27
Nodes (10): detect_column_pii(), _norm(), ColumnProfile, infer_type(), profile_column(), Source data profiling: per-column type inference, completeness, cardinality, pat, Collapse a value into a pattern like 'AAA9999' for pattern profiling., Returns (dtype, date_format). (+2 more)

### Community 44 - "Delivery Profile Logic"
Cohesion: 0.17
Nodes (25): _date(), _parse_date(), CronError, _day_matches(), describe(), _field(), is_business_day(), _last_weekday() (+17 more)

### Community 45 - "Rule Authoring LLM"
Cohesion: 0.23
Nodes (11): _base_with(), draft_from_text(), _heuristic(), LLM-assisted rule authoring: SME types English -> JSON Logic DSL + test cases., Returns {"draft": rule body | None, "source": "llm"|"heuristic", "test_results":, resolve_field(), _sample_value(), _r() (+3 more)

### Community 46 - "Rule Executor"
Cohesion: 0.26
Nodes (13): mapping_dq_rules(), describe_step(), field_inspect(), _load(), mapping_dq(), Field-level inspection for the Mapping UI.  For one SSE target attribute in a ma, Every rule in the registry against this mapping's sample: fail counts and field, Every distinct source value for a field, what it becomes in SSE and whether that (+5 more)

### Community 47 - "Rule Registry Lifecycle"
Cohesion: 0.20
Nodes (9): API, Audience and access, Catalog (allowlist only), Intent, Maintenance · Glue artifacts (in-app viewer), Non-goals (Phase 1), Success, Testing (+1 more)

### Community 48 - "Frontend Cognito Auth"
Cohesion: 0.35
Nodes (11): b64url(), bearer(), decode(), initAuth(), load(), login(), logout(), randomString() (+3 more)

### Community 49 - "Glue Job Entry Points"
Cohesion: 0.11
Nodes (17): 1. Stack and tooling, 2. Design tokens, 3. Shell, 4. Shared primitives migration, 5. In-scope pages, 6. Data flow and boundaries, 7. Error handling and a11y, 8. Testing and verification (+9 more)

### Community 50 - "Local S3 Storage"
Cohesion: 0.08
Nodes (42): accept_all(), add_mapping_field(), ai_suggest(), approve_delivery(), approve_mapping(), batch_apply_ooo(), batch_discard(), batch_skip_gap() (+34 more)

### Community 51 - "Glue Job Tests"
Cohesion: 0.13
Nodes (18): create_batch(), DuplicateFileError, file_sha256(), override_preflight(), Path, ValueError, Register an arriving file. With strict=False (unattended S3/scheduler arrivals), An SME/Compliance user accepts the drift risk and lets a blocked batch run on th (+10 more)

### Community 52 - "Incremental Row Planner"
Cohesion: 0.12
Nodes (16): 1. Kit layout, 2. Shared module: `backend/lbp/demo_setup.py`, 3. API, 4. CLI and `start_demo.sh`, 5. UI, 6. Security and production, 7. Testing, 8. Docs (+8 more)

### Community 53 - "SSE Target Loader"
Cohesion: 0.18
Nodes (10): audit_verify(), Recompute the audit hash chain; any edited, deleted or re-ordered entry breaks i, Data minimisation for staging (GLBA safeguards).  Once a loan is boarded (or the, check_schema_current(), _ensure_chain_head(), _entry_hash(), datetime, Relational store (SQLAlchemy Core).  Local: SQLite. AWS: RDS SQL Server (the SSE (+2 more)

### Community 54 - "Exceptions Console UI"
Cohesion: 0.17
Nodes (16): admin, lee, maria, defaultMode(), EXECUTION, HowItWorks(), isYourStep(), SETUP (+8 more)

### Community 55 - "Source Upload APIs"
Cohesion: 0.25
Nodes (11): ai_map(), create_source(), presign(), Path, Stream an upload to disk with size, extension and content-type checks (no execut, Add a feed (a file layout from a vendor) from a sample file; the AI drafts its m, AWS: browser PUTs straight to the raw S3 zone; EventBridge starts the Step Funct, _save_upload() (+3 more)

### Community 56 - "Review Focus"
Cohesion: 0.22
Nodes (8): Global Constraints, Maintenance · Glue artifacts Implementation Plan, Review Focus, Self-review notes, Task 1: Allowlist + read helpers + tests, Task 2: API routes + ROUTE_ROLES, Task 3: Frontend CAPS + Maintenance page + rail, Task 4: Graphify + smoke

### Community 57 - "OpenSearchPrecedentIndex"
Cohesion: 0.13
Nodes (34): api(), setIntent(), FeedConfigChip(), FeedConfigModal(), AuditModal(), DemoSetupModal(), EDITABLE, Governance() (+26 more)

### Community 58 - "retention_purge"
Cohesion: 0.36
Nodes (7): _feed(), _incremental(), Vendors own feeds; operations are scoped and protected at vendor level., _sse(), test_change_file_cannot_touch_another_vendors_loans(), test_snapshot_compares_the_vendors_whole_portfolio(), test_vendor_crud_roles_and_rollups()

### Community 59 - "Change Control Docs"
Cohesion: 0.22
Nodes (9): CHG05 Concurrent Change Conflict, Delivery Profile, Feed, Load Type full, Load Type incremental, Maker-Checker Governance for Schedules, Optimistic Concurrency via lbp_version, SOX Change Control and Audit Trail (+1 more)

### Community 60 - "Backend Dependencies"
Cohesion: 0.29
Nodes (8): Dev Dependencies pytest and ruff, fastapi, mangum Lambda Adapter, Backend Runtime Dependencies, SQLAlchemy, Control Plane vs Glue Data Plane Split, AWS Glue Data Plane, Control-Plane FastAPI

### Community 61 - "Docker Compose Stack"
Cohesion: 0.25
Nodes (8): docker-compose api Service, lbp-data Shared Volume, docker-compose worker Service, Load Type snapshot, Snapshot Truncation Guard, Throttled Checkpointed Micro-Batch Pipeline, Re-Board Protection (DUP01/DUP02), Schema-Drift Pre-Flight

### Community 62 - "Platform Architecture Docs"
Cohesion: 0.29
Nodes (8): Live Safety Switches Outside Bundle, CHG01 Protected Field Change, SR 11-7 Model Risk Controls, AI-Assisted Mapping Engine, T1–T5 Exception Manager, PennyMac Loan Boarding Platform, Mapping Memory, Rules-as-Code Engine

### Community 63 - "OIDC Deploy Workflow"
Cohesion: 0.29
Nodes (7): Deploy Glue Wheel Build and Upload, Deploy Migrate Lambda Step, Deploy OIDC to AWS, Deploy Smoke Test, Deploy Workflow, Same lbp Wheel Everywhere, GitHub OIDC Deploy Credential Hygiene

### Community 64 - "Vendor CRUD APIs"
Cohesion: 0.22
Nodes (13): fix_fico(), fix_investor_gnma(), fix_loan_number(), fix_maturity(), fix_occupancy(), fix_rate(), fix_servicing_fee(), fix_state() (+5 more)

### Community 65 - "Transform Unit Tests"
Cohesion: 0.14
Nodes (13): Demo Kit In-App Implementation Plan, Execution handoff, File structure, Global Constraints, Review Focus, Spec coverage check, Task 1: Kit layout + resolver, Task 2: Emptiness check, wipe, `SetupResult` shell (+5 more)

### Community 66 - "__init__.py"
Cohesion: 0.33
Nodes (7): deliveries_waive(), _sched_call(), ScheduleIn, schedules_create(), schedules_status(), schedules_update(), StatusIn

### Community 67 - "Signed Glue Config Docs"
Cohesion: 0.38
Nodes (7): config_store.publish, HMAC-SHA256 Tamper-Evident Config Bundles, Glue Job lbp-feed, Glue Job lbp-feed-spark, Reject Glue Python Shell Runtime, Step Functions Route→Glue→Finalize, Signed Feed Configuration

### Community 68 - "CI Workflow Jobs"
Cohesion: 0.40
Nodes (6): CI Backend Job, CI Frontend Job, CI Image Build and Trivy Scan, CI Infrastructure Job, CI PostgreSQL 16 Test Service, CI Workflow

### Community 69 - "Load Test Evidence Docs"
Cohesion: 0.33
Nodes (6): CI 100K Throughput Regression, SSE Intake as Production Throughput Ceiling, 1M Loan Load Test Evidence, Go-Live Blockers Owned by PennyMac, Ready for UAT, Not Go-Live, PoC 100K+/1M Throughput Criterion

### Community 70 - "API Auth Hardening"
Cohesion: 0.17
Nodes (14): authorize(), current_user(), hardening(), Global dependency: authenticate every /api call and apply ROUTE_ROLES., Request id, security headers, no-store caching for API data, structured access l, current_principal(), _jwks_client(), Principal (+6 more)

### Community 71 - "Schedule CRUD APIs"
Cohesion: 0.50
Nodes (4): field_values_edit(), get_mapping(), Preview (save=false) or save (save=true) a source-specific value map for this fi, ValuesReq

### Community 72 - "test_concurrency.py"
Cohesion: 0.22
Nodes (6): SFTP pull connector against a real in-process SFTP server: host-key pinning, pas, _serve(), _Server, _SFTP, sftp_server(), test_sftp_pull_pins_host_key_and_fetches_once()

### Community 73 - "Vendor Sequencing Docs"
Cohesion: 0.33
Nodes (6): CHG06 Cross-Vendor Loan Change, Per-Vendor File Sequencing Gate, Vendor, SSE Target Schema, Pipe-Delimited Sub-Servicing Columns, Sub-Servicing Sample Loan Tape

### Community 74 - "Preflight Override Path"
Cohesion: 0.32
Nodes (12): canonical_loans(), generate_all(), _inject_defect(), _loan(), Path, Synthetic loan file generator for the four PennyMac boarding sources.  Every sou, Canonical (SSE-shaped) loan; each source writer renames/reformats it., write_bulk_excel() (+4 more)

### Community 75 - "SFTP Scheduler Docs"
Cohesion: 0.50
Nodes (5): paramiko SFTP Dependency, Glue Job lbp-vendor-pull, Delivery Scheduler, Scheduler Tick, SFTP Pull Connector with Host-Key Pinning

### Community 78 - "demo_setup"
Cohesion: 0.18
Nodes (10): File map, Global Constraints, Guided Rule Authoring Implementation Plan, Review Focus, Task 1: JSON Logic new operators, Task 2: shapes compiler, Task 3: API + registry, Task 4: Authoring → tree (+2 more)

### Community 79 - "remap_batch"
Cohesion: 0.18
Nodes (9): _apply_ssm(), db_secret(), Runtime configuration. Every setting can be overridden with an LBP_* environment, RDS-managed secret {username, password}. Cached briefly; refreshed after rotatio, Overlay settings published by Terraform under LBP_SSM_PREFIX (e.g. the Cognito c, Used by tests after changing environment variables., Settings that must hold outside a developer laptop. The API refuses to start oth, reset_settings() (+1 more)

### Community 101 - "canCap"
Cohesion: 0.17
Nodes (15): ACTION_LABEL, AuthorModal(), blankLeaf(), EditRuleModal(), ensureTree(), GroupEditor(), LeafEditor(), NEXT (+7 more)

### Community 102 - "Demo kit: test data and a ready-to-run demo"
Cohesion: 0.25
Nodes (7): Demo kit: test data and a ready-to-run demo, How the test data is made, Personas (the "Signed in as" switcher, bottom left), Suggested run of show (about 25 minutes), The pre-loaded state, Two ways to demo, What is in the kit

### Community 103 - "OpenSearchPrecedentIndex"
Cohesion: 0.24
Nodes (4): OpenSearchPrecedentIndex, Precedent retrieval (the 'R' in RAG) over historically resolved exceptions.  Loc, _shape(), SqlPrecedentIndex

### Community 104 - "verify_audit_chain"
Cohesion: 0.13
Nodes (14): File structure, Frontend UI Design System (Phase 1) Implementation Plan, Global Constraints, Review Focus, Self-review notes (author), Task 1: Tailwind scaffold + `cn` + token bridge, Task 2: shadcn primitives + `ui.jsx` façade (Panel, Kpis, Status, Button classes, Toast), Task 3: Shell rewrite (`App.jsx`) (+6 more)

### Community 105 - "run_demo_setup"
Cohesion: 0.18
Nodes (10): APIs, Approval, Architecture, Guided Rule Authoring — Design Spec, In scope, Intent, Out of scope (explicit), Persistence (+2 more)

### Community 107 - "conftest.py"
Cohesion: 0.33
Nodes (7): ACTION_TXT, changedKeys(), clone(), DeliveryProfile(), EditModal(), LT, ReviewModal()

### Community 108 - "wipe_data_dir"
Cohesion: 0.38
Nodes (6): apply_field(), Any, Apply one field mapping to a raw source row. Raises TransformError., test_casts_and_lookups(), test_composite_split_and_concat(), test_default_injection()

### Community 109 - "OpenSearchPrecedentIndex"
Cohesion: 0.33
Nodes (4): env(), onboarded(), All four sources onboarded and approved., sample_files()

### Community 111 - "_vendor_call"
Cohesion: 0.33
Nodes (7): move_feed(), MoveFeed, _vendor_call(), VendorIn, vendors_create(), vendors_get(), vendors_update()

### Community 112 - "authorize"
Cohesion: 0.33
Nodes (4): Multi-writer safety. Meaningful on a real RDBMS (set LBP_TEST_DATABASE_URL); SQL, 8 workers race for two change files of one vendor (sequence 1 and 2): exactly on, test_only_one_worker_wins_a_lease(), test_sequencing_gate_is_atomic_across_workers()

### Community 113 - "_safe_error"
Cohesion: 0.40
Nodes (5): create_rule(), edit_rule(), _materialize_rule(), Prefer tree → expression; keep legacy expression path., RuleBody

## Knowledge Gaps
- **178 isolated node(s):** `lbp`, `start_demo.sh script`, `__dirname`, `ROOT`, `SHOTS` (+173 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **15 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `CLI Worker DB` to `SFTP File Pullers`, `Delivery Scheduling`, `FastAPI Route Mounts`, `Boarding Batch Pipeline`, `Local Scheduler Config`, `Demo Sample Generator`, `Mapping Override APIs`, `Signed Config Store`, `Cron Business Calendar`, `JSON Logic Rules`, `Rule Registry Store`, `Exception Policy`, `File Format Parser`, `Audit History APIs`, `Builtin Rule Validators`, `Mapping Field Inspect`, `Exception RAG Retrieval`, `Local S3 Storage`, `Glue Job Tests`, `SSE Target Loader`, `Source Upload APIs`, `API Auth Hardening`, `remap_batch`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Why does `get_engine()` connect `Exception RAG Retrieval` to `AI Mapping Engine`, `Delivery Scheduling`, `FastAPI Route Mounts`, `Boarding Batch Pipeline`, `Demo Sample Generator`, `CLI Worker DB`, `Mapping Override APIs`, `Signed Config Store`, `Cron Business Calendar`, `Rules Exception APIs`, `Vendor Feed Profiles`, `File Sequencing Gate`, `JSON Logic Rules`, `File Format Parser`, `Audit History APIs`, `Analytics Service`, `Deliveries Schedule UI`, `Mapping Field Inspect`, `Change File Apply`, `Rule Executor`, `Glue Job Tests`, `SSE Target Loader`, `remap_batch`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Why does `create_batch()` connect `Glue Job Tests` to `Security Load Tests`, `Delivery Scheduling`, `AWS Lambda Handlers`, `Boarding Batch Pipeline`, `Deliveries Schedule UI`, `Local Scheduler Config`, `Demo Sample Generator`, `Exception RAG Retrieval`, `Sources Mapping UI`, `Cron Business Calendar`, `authorize`, `Rules Exception APIs`, `Exception Batch Compare`, `retention_purge`, `Lambda Path Tests`, `File Format Parser`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `get_settings()` (e.g. with `run()` and `test_wipe_data_dir_clears_presence()`) actually correct?**
  _`get_settings()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `run_batch()` (e.g. with `main()` and `test_end_to_end_via_api()`) actually correct?**
  _`run_batch()` has 23 INFERRED edges - model-reasoned connections that need verification._
- **What connects `lbp`, `start_demo.sh script`, `__dirname` to the rest of the system?**
  _178 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `SFTP File Pullers` be split into smaller, more focused modules?**
  _Cohesion score 0.13068181818181818 - nodes in this community are weakly interconnected._