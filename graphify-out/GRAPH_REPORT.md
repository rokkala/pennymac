# Graph Report - pennymac  (2026-11-08)

## Corpus Check
- 214 files · ~423,351 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2307 nodes · 5585 edges · 154 communities (138 shown, 16 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 368 edges (avg confidence: 0.76)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `55b608d0`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

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
- conftest.py
- Rule Registry Lifecycle
- Frontend Cognito Auth
- Glue Job Entry Points
- Local S3 Storage
- test_scheduler.py
- Incremental Row Planner
- File map
- default_rules.py
- profile_of
- Review Focus
- OpenSearchPrecedentIndex
- run_demo_setup
- Change Control Docs
- Backend Dependencies
- Docker Compose Stack
- Platform Architecture Docs
- OIDC Deploy Workflow
- cron.py
- Transform Unit Tests
- Deliveries.jsx
- Signed Glue Config Docs
- CI Workflow Jobs
- Load Test Evidence Docs
- API Auth Hardening
- Schedule CRUD APIs
- shapes.py
- Vendor Sequencing Docs
- compile_tree
- SFTP Scheduler Docs
- React Error Boundary
- Glue Spark Feed Job
- demo_setup
- demo_setup.py
- Glue Feed Job
- Glue Vendor Pull Job
- Console Shell Docs
- Auth Privacy Docs
- Scoped Vendor API
- Backend Package Meta
- canCap
- Demo kit: test data and a ready-to-run demo
- test_security.py
- verify_audit_chain
- run_demo_setup
- start_demo.sh
- conftest.py
- wipe_data_dir
- OpenSearchPrecedentIndex
- DuplicateFileError
- _vendor_call
- profiler.py
- inspect.py
- default_rules.py
- inspect_field_draft
- update_policy
- Review Focus
- progress.md
- security.py
- row_to_dict
- _sched_call
- DynamoRuleStore
- test_vendors.py
- DuplicateFileError
- _sched_call
- ETL Monitor (fleet ops console)
- .runtime_set
- PERSONAS
- Four-team roles Implementation Plan
- list_rules
- Monitor.jsx
- fetch_traces
- helpTipPos.test.js
- update_policy
- File map
- test_api.py
- profile_rows
- replay
- test_persist_partition_file_load_balances_with_exceptions
- _sched_call
- test_concurrency.py
- verify_audit_chain
- file_action
- apply_field
- create_rule
- conftest.py
- run_demo_setup
- Triage
- test_concurrency.py
- test_stage_timing.py

## God Nodes (most connected - your core abstractions)
1. `get_engine()` - 139 edges
2. `get_settings()` - 98 edges
3. `create_batch()` - 83 edges
4. `User` - 68 edges
5. `run_batch()` - 57 edges
6. `useApi()` - 56 edges
7. `now()` - 52 edges
8. `audit()` - 52 edges
9. `api()` - 51 edges
10. `canCap()` - 51 edges

## Surprising Connections (you probably didn't know these)
- `docker-compose api Service` --implements--> `Control-Plane FastAPI`  [INFERRED]
  docker-compose.yml → README.md
- `Schema-Drift Pre-Flight` --semantically_similar_to--> `Snapshot Truncation Guard`  [INFERRED] [semantically similar]
  README.md → docs/INCREMENTAL_AND_SCHEDULING.md
- `CI 100K Throughput Regression` --semantically_similar_to--> `PoC 100K+/1M Throughput Criterion`  [INFERRED] [semantically similar]
  .github/workflows/ci.yml → README.md
- `write_coalesced()` --calls--> `get_settings()`  [INFERRED]
  aws/glue/feed_spark_job.py → backend/lbp/config.py
- `on_file_arrival()` --calls--> `dispatch()`  [INFERRED]
  aws/lambdas/handlers.py → backend/lbp/dispatch.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Glue Data-Plane Job Trio** — docs_architecture_lbp_feed, docs_architecture_lbp_feed_spark, docs_architecture_lbp_vendor_pull [EXTRACTED 1.00]
- **Incremental Change Exception Rules** — docs_incremental_and_scheduling_chg01, docs_incremental_and_scheduling_chg05, docs_incremental_and_scheduling_chg06, docs_incremental_and_scheduling_load_type_incremental [EXTRACTED 1.00]
- **CI Pipeline Job Set** — _github_workflows_ci_backend_job, _github_workflows_ci_frontend_job, _github_workflows_ci_infrastructure_job, _github_workflows_ci_image_job [EXTRACTED 1.00]

## Communities (154 total, 16 thin omitted)

### Community 0 - "AI Mapping Engine"
Cohesion: 0.18
Nodes (22): admin, compliance, monitoring, monReview, applyGuideHash(), defaultMode(), EXECUTION, HowItWorks() (+14 more)

### Community 1 - "SFTP File Pullers"
Cohesion: 0.16
Nodes (15): read_policy(), Exception Manager: AI proposes, human disposes.  Resolution pipeline per failing, effective_policy(), get_policy(), PolicyError, ValueError, Confidence x Risk routing policy (the hard gate).  Thresholds live in the Policy, Live override rate of AI auto-applied fixes (rollbacks + failed QA samples / T1 (+7 more)

### Community 2 - "Delivery Scheduling"
Cohesion: 0.13
Nodes (39): pull(), Vendor delivery scheduling: calendars, expected deliveries, late/missed alerts,, _acquire_leader(), create_schedule(), decide(), effective(), get_schedule(), list_deliveries() (+31 more)

### Community 3 - "FastAPI Route Mounts"
Cohesion: 0.06
Nodes (40): a_ai(), a_ask(), a_dq(), a_exceptions(), a_exec(), a_import(), a_sources(), a_systemic() (+32 more)

### Community 4 - "Frontend Package Deps"
Cohesion: 0.06
Nodes (35): eslint, @eslint/js, eslint-plugin-react, eslint-plugin-react-hooks, dependencies, react, react-dom, devDependencies (+27 more)

### Community 5 - "Boarding Batch Pipeline"
Cohesion: 0.29
Nodes (8): override_preflight(), An SME/Compliance user accepts the drift risk and lets a blocked batch run on th, notify(), _record_pull_error(), audit(), Append-only, hash-chained audit trail (SOX). Each entry commits to the previous, ensure_vendor(), Vendor id for a name, creating it if needed (back-compat for callers that regist

### Community 6 - "Frontend Delivery UI"
Cohesion: 0.13
Nodes (27): _apply_memory(), _detect_composites(), name_similarity(), normalize(), AI-assisted source-to-target mapping with confidence scoring.  Scoring combines, Reuse only the portable part of a remembered transform: its value translations., Run every proposed transform on the sample; demote suggestions that fail on real, Re-rank candidates with what humans approved/rejected for this column name befor (+19 more)

### Community 7 - "Local Scheduler Config"
Cohesion: 0.11
Nodes (18): 10. Risks, 1. Information architecture, 2. Visual / component system (no Tailwind retry), 3. Overview — dual audience home, 4. Page-by-page intent (full rebuild checklist), 5. Interaction rules (product-wide), 6. Data flow and optional API, 7. Accessibility and errors (+10 more)

### Community 8 - "Field Transforms"
Cohesion: 0.11
Nodes (23): _empty(), _num(), _op_cents_to_dollars(), _op_concat(), _op_default(), _op_divide(), _op_lookup(), _op_normalize_rate() (+15 more)

### Community 9 - "Demo Sample Generator"
Cohesion: 0.09
Nodes (43): Pure (no DB writes) triage used inside the pipeline workers' parent process., Triage, persist_stream(), Driver step 3: persist processed rows (ordered by row number) in micro-batches w, replay(), detect_duplicates(), _exception_rows(), _fails_of() (+35 more)

### Community 10 - "CLI Worker DB"
Cohesion: 0.17
Nodes (15): Shadow-style impact estimate: how many recently staged loans would this version, rule_impact(), _cmp(), compile_logic(), _get(), JsonLogicError, _loose_eq(), _num() (+7 more)

### Community 11 - "Governance Rules UI"
Cohesion: 0.10
Nodes (31): ACTION_TXT, clone(), LT, EDITABLE, ROWS, Overview(), ScheduleModal(), ROLE_ORDER (+23 more)

### Community 12 - "Exception Decision APIs"
Cohesion: 0.22
Nodes (13): Attach the live SSE records of the loans in this chunk (fetched just before the, with_current(), apply_closes(), apply_updates(), conflict_failures(), current_rows(), masked_changes(), Apply incremental changes to SSE safely.  Updates write only the fields that cha (+5 more)

### Community 13 - "Mapping Override APIs"
Cohesion: 0.07
Nodes (30): Bulk, bulk_resolve(), demo_setup(), DemoSetupIn, FieldAction, maintenance_create_rule_template(), PersonaResetIn, personas_users_create() (+22 more)

### Community 14 - "Signed Config Store"
Cohesion: 0.15
Nodes (23): Glue job `lbp-feed-load`: COPY clean+dirty S3 parts into Postgres after Spark DB, _bucket(), build(), bundle_json(), _canonical(), ConfigError, FeedConfig, _key() (+15 more)

### Community 15 - "Cron Business Calendar"
Cohesion: 0.09
Nodes (39): begin_bulk(), _clean_add(), _copy_clean_adds(), _csv_cell(), _file_load_on(), _flag_dup(), _materialize_dirty_adds(), _orphan_cleanup() (+31 more)

### Community 16 - "Analytics Charts UI"
Cohesion: 0.16
Nodes (21): exceptionFiltersFromSearch(), fileScopedAllOpen(), groupExceptions(), groupsFromLoads(), hasMoreExceptions(), loadDay(), nextOpenId(), tierForLoads() (+13 more)

### Community 17 - "Rules Exception APIs"
Cohesion: 0.20
Nodes (19): _clean_header(), detect_format(), estimate_rows(), _iter_excel(), iter_rows(), ParsedFile, ParseOptions, Path (+11 more)

### Community 18 - "Vendor Feed Profiles"
Cohesion: 0.20
Nodes (18): next_integer(), acquire(), advance(), apply_out_of_order(), discard(), gate(), is_sequenced(), _load() (+10 more)

### Community 19 - "Preflight Mapping Checks"
Cohesion: 0.05
Nodes (36): publish_all(), Republish every live feed (rule or policy changes affect all of them)., _bucket(), Evaluation, Stateless rule executor (runs in-process, in worker processes, on Lambda or ECS, RuleExecutor, RuleResult, DynamoRuleStore (+28 more)

### Community 20 - "File Sequencing Gate"
Cohesion: 0.29
Nodes (10): is_protected_change(), norm(), Comparable form of a field value (mapped record vs. typed SSE row)., _fail(), plan_row(), Incremental and snapshot row planning (pure; runs inside the pipeline worker pro, (action, code) where action is None for an unrecognised code., Decide the row's action and build the record to validate. Returns     {action, r (+2 more)

### Community 21 - "JSON Logic Rules"
Cohesion: 0.19
Nodes (23): _date(), CronError, _day_matches(), describe(), _field(), is_business_day(), _last_weekday(), local_label() (+15 more)

### Community 22 - "Rule Registry Store"
Cohesion: 0.12
Nodes (53): api(), changedKeys(), DeliveryProfile(), EditModal(), ReviewModal(), ExceptionModal(), FeedConfigChip(), FeedConfigModal() (+45 more)

### Community 23 - "Vendors Imports UI"
Cohesion: 0.16
Nodes (18): buildHtml(), capture(), __dirname, esc(), filesTable(), flowExecute(), flowHighLevel(), flowMonitor() (+10 more)

### Community 24 - "Exception Batch Compare"
Cohesion: 0.06
Nodes (35): allowed_hosts(), fetch_new(), LocalPuller, make_puller(), _ok_name(), Puller, PullError, Path (+27 more)

### Community 25 - "Exception Policy"
Cohesion: 0.05
Nodes (65): AnthropicClient, BedrockClient, get_llm(), LLMClient, LLMMappingReranker, Pluggable LLM access used by mapping re-ranking, rule authoring (English -> DSL), Asks the model to choose among the heuristic top-K for each column., _base_with() (+57 more)

### Community 26 - "Exception Manager Core"
Cohesion: 0.17
Nodes (11): _coerce(), ExceptionActionError, ExceptionManager, ValueError, Distinct file loads that have exceptions — options for vendor / file / date filt, Compliance has investigated outside EM (e.g. OFAC false positive) and records th, Undo a T1 auto-apply inside the rollback window (target < 5 min to execute)., Cast a reviewer-entered string into the SSE type for re-validation. (+3 more)

### Community 27 - "API Enhancement Tests"
Cohesion: 0.18
Nodes (16): maintenance_artifact(), maintenance_artifacts(), get_artifact(), list_artifacts(), MaintenanceError, _notebook_cells(), Exception, Path (+8 more)

### Community 28 - "Lambda Path Tests"
Cohesion: 0.15
Nodes (24): _aws(), _executions(), _load(), The AWS execution path (EventBridge -> Step Functions -> Lambda) exercised again, AWS Finalize owns follower start; Glue process_batch must not also dispatch (dou, moto Step Functions + Glue, LBP in AWS mode (dispatch -> Step Functions, data mo, In AWS the scheduler Lambda never moves files itself: a due pull starts the lbp-, The deploy step: migrations (no-op on a current schema here) + a signed configur (+16 more)

### Community 29 - "File Format Parser"
Cohesion: 0.20
Nodes (15): _alembic_cfg(), check_config(), _demo_setup(), main(), migrate(), Operator commands.      python -m lbp.cli migrate          apply database migrat, Requeue batches whose worker stopped heart-beating (crash, OOM, deploy). They re, recover_stale() (+7 more)

### Community 30 - "Frontend Mock API"
Cohesion: 0.12
Nodes (22): ATTN, filterBatches(), RUNNING, ARTIFACTS, cellsOf(), getMaintenanceArtifact(), listMaintenanceArtifacts(), ApiError (+14 more)

### Community 31 - "Audit History APIs"
Cohesion: 0.31
Nodes (9): _batch(), The Glue data plane: signed feed configurations, the standard job, and the Spark, No pandas: mapPartitions → coalesce Parquet; map-only exits staged., Spark full-tape path: clean adds go through COPY/bulk, not OLTP micro-batches., test_approval_publishes_a_signed_bundle_and_runs_use_it(), test_persist_bulk_boards_clean_adds(), test_spark_job_map_partitions_writes_few_parquet(), test_standard_job_entrypoint() (+1 more)

### Community 32 - "Security Load Tests"
Cohesion: 0.18
Nodes (20): _bulk_load_root(), clean_sse_csv_uris(), _complete_from_staging(), _ensure_kind_part(), finalize_bulk(), _list_kind_part_names(), load_clean_files(), load_dirty_files() (+12 more)

### Community 33 - "Analytics Service"
Cohesion: 0.20
Nodes (15): ai_mapping_insights(), dq_scorecard(), exception_analytics(), executive_summary(), _iso(), _label(), _like_escape(), _names() (+7 more)

### Community 35 - "Frontend Auth Personas"
Cohesion: 0.11
Nodes (29): FALLBACK_CAST, getVendorScope(), mockApi(), setIntent(), setPersona(), setSignedIn(), setVendorScope(), takeIntent() (+21 more)

### Community 36 - "AWS Lambda Handlers"
Cohesion: 0.12
Nodes (15): _api(), demo_setup(), finalize_batch(), migrate(), on_file_arrival(), AWS Lambda entry points: the thin control plane around the Glue data plane.  Lam, EventBridge Scheduler (rate 5 minutes): delivery windows and late/missed alerts., Invoked once per deploy: Alembic migrations, default rule seed, and a signed con (+7 more)

### Community 37 - "Incremental Load Tests"
Cohesion: 0.24
Nodes (11): detect_column_pii(), _norm(), PII detection and dynamic masking.  Two signals are combined: column-name semant, ColumnProfile, infer_type(), profile_column(), Source data profiling: per-column type inference, completeness, cardinality, pat, Collapse a value into a pattern like 'AAA9999' for pattern profiling. (+3 more)

### Community 38 - "Deliveries Schedule UI"
Cohesion: 0.22
Nodes (17): batch_changes(), get_source(), loan_history(), What this file changed (applied) and what it is still holding (pending review)., row_to_dict(), _clean(), create_vendor(), get_vendor() (+9 more)

### Community 39 - "Mapping Field Inspect"
Cohesion: 0.07
Nodes (60): personas_cast(), personas_screens(), personas_screens_put(), personas_users(), Signed-in-as switcher people (local demo cast + enabled directory). Open to any, create(), _directory(), list_for() (+52 more)

### Community 40 - "Change File Apply"
Cohesion: 0.17
Nodes (18): _build_scenario(), Port of export_demo_snapshot scenario; row counts scale for compact/full., canonical_loans(), generate_all(), _inject_defect(), _loan(), Path, Synthetic loan file generator for the four PennyMac boarding sources.  Every sou (+10 more)

### Community 41 - "Sources Mapping UI"
Cohesion: 0.29
Nodes (6): Bulk persist for full Spark tapes, Design, Flag, Goal, Scope, Success

### Community 42 - "Exception RAG Retrieval"
Cohesion: 0.40
Nodes (4): Bulk Persist Full Tapes Implementation Plan, Global Constraints, Review Focus, Task 1: COPY helper + persist_bulk

### Community 43 - "PII Profiling"
Cohesion: 0.19
Nodes (6): consensus(), OpenSearchPrecedentIndex, Precedent retrieval (the 'R' in RAG) over historically resolved exceptions.  Loc, If exact-match precedents agree, return (value, strength)., _shape(), SqlPrecedentIndex

### Community 44 - "Delivery Profile Logic"
Cohesion: 0.50
Nodes (4): emit_metrics(), process_batch(), LBP/Pipeline metrics for the dashboard and the failure-rate alarm (AWS only; cou, Run one standard batch. Does not start followers — Step Functions Finalize (or l

### Community 45 - "Rule Authoring LLM"
Cohesion: 0.29
Nodes (6): Notifications, Out of scope, Peer pool (v1), Roles, Rule review workflow + in-app notifications, UI

### Community 46 - "conftest.py"
Cohesion: 0.08
Nodes (35): _apply_clean_sse_batch(), _dup_hold_row(), _ensure_dirty_part(), _list_dirty_part_names(), _load_dirty_files_body(), mark_staged(), _parse_dt(), prepare_large() (+27 more)

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
Cohesion: 0.07
Nodes (30): add_mapping_field(), ai_suggest(), approve_delivery(), approve_mapping(), checker(), Decision, delete_rule(), DeliveryProfileIn (+22 more)

### Community 51 - "test_scheduler.py"
Cohesion: 0.25
Nodes (11): ai_map(), create_source(), presign(), Path, Stream an upload to disk with size, extension and content-type checks (no execut, Add a feed (a file layout from a vendor) from a sample file; the AI drafts its m, AWS: browser PUTs straight to the raw S3 zone; EventBridge starts the Step Funct, _save_upload() (+3 more)

### Community 52 - "Incremental Row Planner"
Cohesion: 0.12
Nodes (16): 1. Kit layout, 2. Shared module: `backend/lbp/demo_setup.py`, 3. API, 4. CLI and `start_demo.sh`, 5. UI, 6. Security and production, 7. Testing, 8. Docs (+8 more)

### Community 53 - "File map"
Cohesion: 0.13
Nodes (14): App UX Phase A Implementation Plan, Execution handoff, File map, Global Constraints, Review Focus, Spec coverage (self-review), Task 1: Hash helpers, Task 2: Nav model (+6 more)

### Community 54 - "default_rules.py"
Cohesion: 0.11
Nodes (38): feed_config(), What the data plane (Glue) will run for this feed: the current signed publicatio, history(), accept_all(), add_field(), approve(), _columns(), diff_versions() (+30 more)

### Community 55 - "profile_of"
Cohesion: 0.16
Nodes (14): batch_apply_ooo(), batch_discard(), batch_skip_gap(), feed_publish(), lifespan(), Override, override_preflight(), Local single-process mode: tick the delivery scheduler every minute and start wh (+6 more)

### Community 56 - "Review Focus"
Cohesion: 0.22
Nodes (8): Global Constraints, Maintenance · Glue artifacts Implementation Plan, Review Focus, Self-review notes, Task 1: Allowlist + read helpers + tests, Task 2: API routes + ROUTE_ROLES, Task 3: Frontend CAPS + Maintenance page + rail, Task 4: Graphify + smoke

### Community 57 - "OpenSearchPrecedentIndex"
Cohesion: 0.15
Nodes (24): scoped(), HBars(), Lines(), niceMax(), Segments(), Sparkline(), Tip(), VBars() (+16 more)

### Community 58 - "run_demo_setup"
Cohesion: 0.09
Nodes (26): data_is_present(), DemoSetupConflict, Any, Exception, Path, Build the demo-kit sales scenario into a local data dir.  Used by CLI, start_dem, Raised when demo data already exists and force=False., Find demo_kit: LBP_DEMO_KIT → <root>/demo_kit → <root>/demo-kit/demo_kit. (+18 more)

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

### Community 64 - "cron.py"
Cohesion: 0.17
Nodes (10): audit_verify(), Recompute the audit hash chain; any edited, deleted or re-ordered entry breaks i, Data minimisation for staging (GLBA safeguards).  Once a loan is boarded (or the, Operational alerts: always logged and audited; published to SNS when LBP_ALERT_T, check_schema_current(), _entry_hash(), datetime, Relational store (SQLAlchemy Core).  Local: SQLite. AWS: RDS SQL Server (the SSE (+2 more)

### Community 65 - "Transform Unit Tests"
Cohesion: 0.14
Nodes (13): Demo Kit In-App Implementation Plan, Execution handoff, File structure, Global Constraints, Review Focus, Spec coverage check, Task 1: Kit layout + resolver, Task 2: Emptiness check, wipe, `SetupResult` shell (+5 more)

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
Cohesion: 0.33
Nodes (6): authorize(), current_user(), hardening(), Global dependency: authenticate every /api call and apply ROUTE_ROLES., Request id, security headers, no-store caching for API data, structured access l, Request

### Community 71 - "Schedule CRUD APIs"
Cohesion: 0.50
Nodes (3): Files, Plan: Rule review notifications (v1), Tasks

### Community 72 - "shapes.py"
Cohesion: 0.33
Nodes (3): DirtyPartWriter, open_dirty_part_writer(), Stream dirty rows into one dirty/part-NNNNN/ directory (coalesce path: ≤8 parts)

### Community 73 - "Vendor Sequencing Docs"
Cohesion: 0.33
Nodes (6): CHG06 Cross-Vendor Loan Change, Per-Vendor File Sequencing Gate, Vendor, SSE Target Schema, Pipe-Delimited Sub-Servicing Columns, Sub-Servicing Sample Loan Tape

### Community 74 - "compile_tree"
Cohesion: 0.22
Nodes (13): fix_fico(), fix_investor_gnma(), fix_loan_number(), fix_maturity(), fix_occupancy(), fix_rate(), fix_servicing_fee(), fix_state() (+5 more)

### Community 75 - "SFTP Scheduler Docs"
Cohesion: 0.50
Nodes (5): paramiko SFTP Dependency, Glue Job lbp-vendor-pull, Delivery Scheduler, Scheduler Tick, SFTP Pull Connector with Host-Key Pinning

### Community 76 - "React Error Boundary"
Cohesion: 0.19
Nodes (11): import_status(), Analytics grain: vendor and file-load., days uses naive UTC now; until may arrive as Z — must not TypeError on compare., test_attention_not_capped_by_limit(), test_batches_days_with_aware_until_does_not_500(), test_batches_http_filters_status_and_days(), test_import_status_filters_status_days_and_q(), test_import_status_includes_exception_counts_per_batch() (+3 more)

### Community 77 - "Glue Spark Feed Job"
Cohesion: 0.33
Nodes (3): Glue Spark job `lbp-feed-spark`: very large full boarding tapes (> LBP_GLUE_THRE, Thin serialize: clean → CSV, dirty → part dir. Mid-partition S3 sync., write_coalesced()

### Community 78 - "demo_setup"
Cohesion: 0.18
Nodes (10): File map, Global Constraints, Guided Rule Authoring Implementation Plan, Review Focus, Task 1: JSON Logic new operators, Task 2: shapes compiler, Task 3: API + registry, Task 4: Authoring → tree (+2 more)

### Community 79 - "demo_setup.py"
Cohesion: 0.26
Nodes (11): _build_csv(), _ensure_extensions(), _import_aws_s3(), _import_stdin_copy(), _list_sse_keys(), main(), Throwaway spike: JSONL → CSV on S3 → aws_s3.table_import_from_s3 timing.  Job pa, Baseline: download CSV and COPY FROM STDIN (current-style path). (+3 more)

### Community 101 - "canCap"
Cohesion: 0.10
Nodes (27): getPersona(), GROUP_LABEL, GROUP_ORDER, JobsPane(), Maintenance(), TemplateEditor(), ACTION_LABEL, AUTHOR_STEPS (+19 more)

### Community 102 - "Demo kit: test data and a ready-to-run demo"
Cohesion: 0.25
Nodes (7): Demo kit: test data and a ready-to-run demo, How the test data is made, Personas (the "Signed in as" switcher, bottom left), Suggested run of show (about 25 minutes), The pre-loaded state, Two ways to demo, What is in the kit

### Community 103 - "test_security.py"
Cohesion: 0.15
Nodes (11): main(), Throughput test: generate N loans, onboard the source, board through the full pi, _client(), RDS-managed secret is read per connection; Cognito client id comes from SSM (as, _rsa(), test_jwt_mode(), test_npi_never_in_error_messages_and_retention(), test_production_refuses_unsafe_config() (+3 more)

### Community 104 - "verify_audit_chain"
Cohesion: 0.13
Nodes (14): File structure, Frontend UI Design System (Phase 1) Implementation Plan, Global Constraints, Review Focus, Self-review notes (author), Task 1: Tailwind scaffold + `cn` + token bridge, Task 2: shadcn primitives + `ui.jsx` façade (Panel, Kpis, Status, Button classes, Toast), Task 3: Shell rewrite (`App.jsx`) (+6 more)

### Community 105 - "run_demo_setup"
Cohesion: 0.18
Nodes (10): APIs, Approval, Architecture, Guided Rule Authoring — Design Spec, In scope, Intent, Out of scope (explicit), Persistence (+2 more)

### Community 107 - "conftest.py"
Cohesion: 0.29
Nodes (6): APIs, Intent, Out of scope, Persistence, Rule Template Maintenance — Design Spec, UI

### Community 108 - "wipe_data_dir"
Cohesion: 0.18
Nodes (9): _apply_ssm(), db_secret(), Runtime configuration. Every setting can be overridden with an LBP_* environment, RDS-managed secret {username, password}. Cached briefly; refreshed after rotatio, Overlay settings published by Terraform under LBP_SSM_PREFIX (e.g. the Cognito c, Used by tests after changing environment variables., Settings that must hold outside a developer laptop. The API refuses to start oth, reset_settings() (+1 more)

### Community 111 - "_vendor_call"
Cohesion: 0.33
Nodes (7): move_feed(), MoveFeed, _vendor_call(), VendorIn, vendors_create(), vendors_get(), vendors_update()

### Community 112 - "profiler.py"
Cohesion: 0.13
Nodes (19): profile_rows(), compile_mapping(), Return a fast row -> (record, errors) function for the active fields of a mappin, _active_fields(), check_file(), _critical(), _feeds(), Path (+11 more)

### Community 113 - "inspect.py"
Cohesion: 0.26
Nodes (14): mapping_dq_rules(), describe_step(), field_inspect(), _load(), mapping_dq(), Field-level inspection for the Mapping UI.  For one SSE target attribute in a ma, Every rule in the registry against this mapping's sample: fail counts and field, Every distinct source value for a field, what it becomes in SSE and whether that (+6 more)

### Community 115 - "inspect_field_draft"
Cohesion: 0.24
Nodes (12): BATCH_ATTENTION, BATCH_SEV, buildAttentionRows(), buildLoadHealth(), calendarDay(), dayKey(), DELIVERY_OPEN, DELIVERY_SEV (+4 more)

### Community 116 - "update_policy"
Cohesion: 0.10
Nodes (23): accept_all(), batch_snapshot_reviews(), compliance_clear(), demo_seed(), escalate(), list_notifications(), list_rules(), maintenance_delete_rule_template() (+15 more)

### Community 117 - "Review Focus"
Cohesion: 0.17
Nodes (11): App UX Phases B–D Implementation Plan, Global Constraints, Review Focus, Spec coverage, Task 1: Phase B — Imports, Task 2: Phase B — Exceptions, Task 3: Phase B — Analytics + Deliveries, Task 4: Phase C — Sources / Vendors / DeliveryProfile / FeedConfig chrome (+3 more)

### Community 118 - "progress.md"
Cohesion: 0.53
Nodes (5): _board_one(), Exceptions are filterable/groupable by vendor, file, and load date., test_exception_list_filters_by_loaded_on_and_batch(), test_exception_list_includes_filename_and_loaded_at(), test_exception_loads_endpoint()

### Community 120 - "security.py"
Cohesion: 0.15
Nodes (12): Current state (baseline), Data layout, Design, Flags, Goal, Job 1 — `lbp-*-feed-spark` (compute only), Job 2 — `lbp-*-feed-load` (DB only), Non-goals / honesty (+4 more)

### Community 122 - "row_to_dict"
Cohesion: 0.25
Nodes (7): Cognito / `ROLES`, Demo cast (6), Four teams + in-team reviewers, Intent, Legacy aliases (dev / old headers / leftover data), Non-goals, Ownership

### Community 123 - "_sched_call"
Cohesion: 0.24
Nodes (12): CELL, cronFrom(), Deliveries(), DOW, HistoryStrip(), OPEN, presetOf(), ScheduleEditor() (+4 more)

### Community 124 - "DynamoRuleStore"
Cohesion: 0.18
Nodes (10): Files, Global Constraints, Review Focus, Self-review (done inline), Spark / Load Job Split Implementation Plan, Task 1: DB-free persist writes clean + dirty parts (no Postgres COPY), Task 2: `mark_staged` + Spark job stops before load, Task 3: `load_clean_files` + DUP02 divert + `run_load_bulk` (+2 more)

### Community 125 - "test_vendors.py"
Cohesion: 0.36
Nodes (7): _feed(), _incremental(), Vendors own feeds; operations are scoped and protected at vendor level., _sse(), test_change_file_cannot_touch_another_vendors_loans(), test_snapshot_compares_the_vendors_whole_portfolio(), test_vendor_crud_roles_and_rollups()

### Community 126 - "DuplicateFileError"
Cohesion: 0.29
Nodes (6): Intent, Layout, Locked decisions, Non-goals, Overview as boarding load desk, Success

### Community 127 - "_sched_call"
Cohesion: 0.10
Nodes (32): create_batch(), file_sha256(), Path, Register an arriving file. With strict=False (unattended S3/scheduler arrivals), Regression tests for DB-free bulk load data-loss / duplicate bugs., Clean then dirty for the same loan must not unique-violate or double-insert., Boarded dirty adds live in loans.jsonl; load must COPY them into sse_loans., Dirty load must not wipe oltp/ — finalize_bulk / run_load_bulk still need those (+24 more)

### Community 128 - "ETL Monitor (fleet ops console)"
Cohesion: 0.15
Nodes (12): API, Error handling, ETL Monitor (fleet ops console), Frontend touchpoints, `GET /api/batches` (extend), Intent, Locked decisions, Monitor layout (+4 more)

### Community 129 - ".runtime_set"
Cohesion: 0.50
Nodes (3): File map, Overview load desk Implementation Plan, Tasks

### Community 133 - "list_rules"
Cohesion: 0.29
Nodes (6): Bulk file load for dirty Spark rows, Files, Flag, Flow, Goal, Tasks

### Community 134 - "Monitor.jsx"
Cohesion: 0.20
Nodes (17): batchStep(), buildBatchesPath(), deskOrder(), LIVE_STATUSES, LOCAL_STEP, localDetail(), splitDetail(), splitLiveAndHistory() (+9 more)

### Community 135 - "fetch_traces"
Cohesion: 0.31
Nodes (8): current_principal(), _jwks_client(), Principal, principal_from_claims(), Authentication and role-based authorization.  Modes (LBP_AUTH_MODE):   dev  - id, FastAPI dependency: the caller must hold one of `roles` (admin always passes)., require(), verify_token()

### Community 136 - "helpTipPos.test.js"
Cohesion: 0.29
Nodes (6): helpTipFixedPos(), mid, nearBottom, nearRight, roomBelow, HelpTip()

### Community 137 - "update_policy"
Cohesion: 0.31
Nodes (9): _batch(), test_bulk_resolve(), test_pause_and_resume_from_checkpoint(), test_pipeline_reconciles(), test_routing_matrix(), test_t2_resolution_boards_loan(), test_t4_maker_checker(), test_t5_only_compliance() (+1 more)

### Community 138 - "File map"
Cohesion: 0.18
Nodes (10): ETL Monitor Implementation Plan, File map, Global Constraints, Review Focus, Self-review notes, Task 1: `import_status` filters + `attention`, Task 2: Wire `GET /api/batches` query params, Task 3: Nav, personas, screen copy (+2 more)

### Community 139 - "test_api.py"
Cohesion: 0.12
Nodes (22): BatchBusyError, _chunks(), DuplicateFileError, Exception, RuntimeError, ValueError, Error text for storage/UI: first line only, never the SQL parameters (they can c, run_batch() (+14 more)

### Community 140 - "profile_rows"
Cohesion: 0.46
Nodes (14): _boarded_pcg(), _pick(), Incremental / snapshot loads, change control and per-vendor sequencing (end to e, A reviewer corrected a value at boarding; the vendor's next snapshot re-sends th, _run(), _set_profile(), _sse(), test_incremental_sparse_updates_closes_and_change_control() (+6 more)

### Community 141 - "replay"
Cohesion: 0.31
Nodes (8): audit(), Re-run held loans through the source's current mapping and rules (dry_run previe, replay(), schedules_pull(), aws_mode(), Start processing of a batch, wherever the platform runs.      local  a backgroun, Control-plane actions that move data (replay, vendor pull) run as Glue jobs in A, start_glue()

### Community 142 - "test_persist_partition_file_load_balances_with_exceptions"
Cohesion: 0.29
Nodes (7): _batch(), Glue writes dirty rows to files; one load step COPYs staging + exceptions., Force reopen: leftover sse_loans must die even if staging was already cleared., Dirty path must not OLTP-insert; files + load_dirty_files still balance., test_begin_bulk_checkpoint_zero_wipes_sse_without_staging(), test_copy_insert_exceptions_roundtrip(), test_persist_partition_file_load_balances_with_exceptions()

### Community 143 - "_sched_call"
Cohesion: 0.29
Nodes (8): deliveries_waive(), _sched_call(), ScheduleIn, schedules_approve(), schedules_create(), schedules_status(), schedules_update(), StatusIn

### Community 144 - "test_concurrency.py"
Cohesion: 0.27
Nodes (10): _load_clean_csv_part(), _normalize_staging_csv_rows(), Reject anything that isn't a plain SQL identifier before interpolating into DDL., True if aws_s3.table_import_from_s3 loaded rows into `table`. False → caller use, Return (staging_rows, sse_rows) from CSV part — aws_s3 into temp when possible,, Load one clean SSE CSV via aws_s3 when possible, else local DictReader., _read_csv(), _read_sse_csv_file() (+2 more)

### Community 145 - "verify_audit_chain"
Cohesion: 0.29
Nodes (5): batch_loans(), Field-by-field comparison of an incoming duplicate with the loan already in SSE., mask_record(), mask_value(), partial: keep last 4 (SSN/phone) or first letter (name); hash: deterministic tok

### Community 146 - "file_action"
Cohesion: 0.24
Nodes (8): get_batch(), _brief(), fetch_traces(), Step Functions history for a batch, reduced to the steps and short returns the d, Turn GetExecutionHistory events into ordered steps. Choice states are skipped., Latest execution for each batch id. Empty when this process is not on AWS., summarize_events(), test_summarize_events_keeps_each_step_and_its_return()

### Community 147 - "apply_field"
Cohesion: 0.38
Nodes (6): apply_field(), Apply one field mapping to a raw source row. Raises TransformError., test_casts_and_lookups(), test_composite_split_and_concat(), test_default_injection(), test_jsonlogic_ops()

### Community 148 - "create_rule"
Cohesion: 0.40
Nodes (5): create_rule(), edit_rule(), _materialize_rule(), Prefer tree → expression; keep legacy expression path., RuleBody

### Community 149 - "conftest.py"
Cohesion: 0.67
Nodes (3): Turn the drift report into a draft mapping version (renames + date formats) for, Remap, remap_batch()

### Community 150 - "run_demo_setup"
Cohesion: 0.15
Nodes (22): get_delivery(), list_sources(), How a file named like this would be treated: load type, file-level action, seque, test_filename(), incremental_context(), Per-batch context for change files (from the published feed configuration): effe, decide_profile(), DeliveryError (+14 more)

### Community 151 - "Triage"
Cohesion: 0.19
Nodes (14): Public settings the web app needs to sign users in (no secrets)., web_config(), get_settings(), Flush local handles and overwrite S3 objects (mid-partition progress)., is_s3(), local_path(), persist_upload(), Path (+6 more)

## Knowledge Gaps
- **308 isolated node(s):** `lbp`, `start_demo.sh script`, `__dirname`, `ROOT`, `SHOTS` (+303 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `Triage` to `Delivery Scheduling`, `FastAPI Route Mounts`, `Boarding Batch Pipeline`, `fetch_traces`, `Demo Sample Generator`, `test_api.py`, `Mapping Override APIs`, `replay`, `Signed Config Store`, `Cron Business Calendar`, `test_concurrency.py`, `file_action`, `Preflight Mapping Checks`, `test_persist_partition_file_load_balances_with_exceptions`, `Exception Batch Compare`, `Exception Policy`, `File Format Parser`, `Audit History APIs`, `Security Load Tests`, `Mapping Field Inspect`, `Change File Apply`, `Delivery Profile Logic`, `conftest.py`, `test_scheduler.py`, `default_rules.py`, `profile_of`, `run_demo_setup`, `cron.py`, `shapes.py`, `Glue Spark Feed Job`, `wipe_data_dir`, `profiler.py`, `update_policy`, `_sched_call`?**
  _High betweenness centrality (0.087) - this node is a cross-community bridge._
- **Why does `get_engine()` connect `default_rules.py` to `SFTP File Pullers`, `Delivery Scheduling`, `FastAPI Route Mounts`, `Boarding Batch Pipeline`, `Demo Sample Generator`, `CLI Worker DB`, `test_api.py`, `Exception Decision APIs`, `replay`, `Signed Config Store`, `Cron Business Calendar`, `test_concurrency.py`, `verify_audit_chain`, `file_action`, `Preflight Mapping Checks`, `Rules Exception APIs`, `conftest.py`, `run_demo_setup`, `Vendor Feed Profiles`, `Triage`, `Exception Policy`, `File Format Parser`, `Security Load Tests`, `Analytics Service`, `Deliveries Schedule UI`, `Mapping Field Inspect`, `Change File Apply`, `conftest.py`, `profile_of`, `run_demo_setup`, `cron.py`, `React Error Boundary`, `wipe_data_dir`, `inspect.py`, `update_policy`, `_sched_call`?**
  _High betweenness centrality (0.045) - this node is a cross-community bridge._
- **Why does `create_batch()` connect `_sched_call` to `Delivery Scheduling`, `Boarding Batch Pipeline`, `Demo Sample Generator`, `update_policy`, `test_api.py`, `profile_rows`, `test_persist_partition_file_load_balances_with_exceptions`, `Rules Exception APIs`, `run_demo_setup`, `Triage`, `test_concurrency.py`, `Exception Batch Compare`, `Lambda Path Tests`, `Audit History APIs`, `AWS Lambda Handlers`, `Change File Apply`, `default_rules.py`, `run_demo_setup`, `React Error Boundary`, `test_security.py`, `progress.md`, `test_vendors.py`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._
- **Are the 14 inferred relationships involving `get_settings()` (e.g. with `write_coalesced()` and `run()`) actually correct?**
  _`get_settings()` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 60 inferred relationships involving `create_batch()` (e.g. with `on_file_arrival()` and `main()`) actually correct?**
  _`create_batch()` has 60 INFERRED edges - model-reasoned connections that need verification._
- **Are the 28 inferred relationships involving `run_batch()` (e.g. with `main()` and `test_batches_http_filters_status_and_days()`) actually correct?**
  _`run_batch()` has 28 INFERRED edges - model-reasoned connections that need verification._
- **What connects `lbp`, `start_demo.sh script`, `__dirname` to the rest of the system?**
  _308 weakly-connected nodes found - possible documentation gaps or missing edges._