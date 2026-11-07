# Graph Report - pennymac  (2026-11-07)

## Corpus Check
- 199 files · ~407,690 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2070 nodes · 5044 edges · 151 communities (137 shown, 14 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 308 edges (avg confidence: 0.75)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a77dab6a`
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
- run_batch
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
- test_incremental.py
- row_to_dict
- DeliveryProfile.jsx
- DynamoRuleStore
- test_vendors.py
- DuplicateFileError
- ._finalize_loan
- ETL Monitor (fleet ops console)
- .runtime_set
- PERSONAS
- Four-team roles Implementation Plan
- list_rules
- Monitor.jsx
- local_path
- helpTipPos.test.js
- config.py
- File map
- mask_value
- test_routing_exceptions.py
- apply_field
- fetch_traces
- demo_setup.py
- get_settings
- worker.py
- run
- test_sequencing_gate_is_atomic_across_workers
- create_rule
- demo_setup

## God Nodes (most connected - your core abstractions)
1. `get_engine()` - 124 edges
2. `get_settings()` - 76 edges
3. `User` - 68 edges
4. `create_batch()` - 56 edges
5. `run_batch()` - 56 edges
6. `useApi()` - 56 edges
7. `canCap()` - 51 edges
8. `audit()` - 50 edges
9. `api()` - 50 edges
10. `RuleRegistry` - 47 edges

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

## Communities (151 total, 14 thin omitted)

### Community 0 - "AI Mapping Engine"
Cohesion: 0.17
Nodes (24): prepare_large(), Driver step 1: config, lease and pre-flight. Returns (cfg, batch) or (None, stat, approve(), override_preflight(), An SME/Compliance user accepts the drift risk and lets a blocked batch run on th, acquire(), advance(), apply_out_of_order() (+16 more)

### Community 1 - "SFTP File Pullers"
Cohesion: 0.06
Nodes (35): allowed_hosts(), fetch_new(), LocalPuller, make_puller(), _ok_name(), Puller, PullError, Path (+27 more)

### Community 2 - "Delivery Scheduling"
Cohesion: 0.12
Nodes (40): describe(), Short human description for common shapes; falls back to the expression., Vendor delivery scheduling: calendars, expected deliveries, late/missed alerts,, _acquire_leader(), create_schedule(), decide(), effective(), get_schedule() (+32 more)

### Community 3 - "FastAPI Route Mounts"
Cohesion: 0.04
Nodes (54): a_ai(), a_ask(), a_dq(), a_exceptions(), a_exec(), a_import(), a_sources(), a_systemic() (+46 more)

### Community 4 - "Frontend Package Deps"
Cohesion: 0.06
Nodes (35): eslint, @eslint/js, eslint-plugin-react, eslint-plugin-react-hooks, dependencies, react, react-dom, devDependencies (+27 more)

### Community 5 - "Boarding Batch Pipeline"
Cohesion: 0.12
Nodes (25): _fails_of(), process_chunk(), Micro-batch boarding pipeline: parse -> map/transform -> validate -> triage -> l, Map + validate one micro-batch. With `incr` (incremental / snapshot loads) each, Compile mapping + rules once per worker process per (mapping version, rule set)., Authoritative change counts from the database (used where chunks run in parallel, _status_of(), summarize_changes() (+17 more)

### Community 6 - "Frontend Delivery UI"
Cohesion: 0.20
Nodes (7): AnthropicClient, BedrockClient, get_llm(), LLMClient, LLMMappingReranker, Pluggable LLM access used by mapping re-ranking, rule authoring (English -> DSL), Asks the model to choose among the heuristic top-K for each column.

### Community 7 - "Local Scheduler Config"
Cohesion: 0.11
Nodes (18): 10. Risks, 1. Information architecture, 2. Visual / component system (no Tailwind retry), 3. Overview — dual audience home, 4. Page-by-page intent (full rebuild checklist), 5. Interaction rules (product-wide), 6. Data flow and optional API, 7. Accessibility and errors (+10 more)

### Community 8 - "Field Transforms"
Cohesion: 0.12
Nodes (21): _empty(), _num(), _op_cents_to_dollars(), _op_concat(), _op_default(), _op_divide(), _op_lookup(), _op_normalize_rate() (+13 more)

### Community 9 - "Demo Sample Generator"
Cohesion: 0.23
Nodes (11): _base_with(), draft_from_text(), _heuristic(), LLM-assisted rule authoring: SME types English -> JSON Logic DSL + test cases., Returns {"draft": rule body | None, "source": "llm"|"heuristic", "test_results":, resolve_field(), _sample_value(), _r() (+3 more)

### Community 10 - "CLI Worker DB"
Cohesion: 0.38
Nodes (4): _bucket(), Evaluation, Stateless rule executor (runs in-process, in worker processes, on Lambda or ECS, RuleResult

### Community 11 - "Governance Rules UI"
Cohesion: 0.11
Nodes (28): ACTION_TXT, clone(), LT, AuditModal(), EDITABLE, ROWS, Overview(), ROLE_ORDER (+20 more)

### Community 12 - "Exception Decision APIs"
Cohesion: 0.22
Nodes (13): Attach the live SSE records of the loans in this chunk (fetched just before the, with_current(), apply_closes(), apply_updates(), conflict_failures(), current_rows(), masked_changes(), Apply incremental changes to SSE safely.  Updates write only the fields that cha (+5 more)

### Community 13 - "Mapping Override APIs"
Cohesion: 0.08
Nodes (24): add_mapping_field(), DeliveryProfileIn, FieldAction, inspect_field_draft(), NewField, Purge, put_delivery(), QA (+16 more)

### Community 14 - "Signed Config Store"
Cohesion: 0.23
Nodes (16): build(), bundle_json(), _canonical(), ConfigError, FeedConfig, _key(), load(), publish() (+8 more)

### Community 15 - "Cron Business Calendar"
Cohesion: 0.11
Nodes (39): admin, compliance, monitoring, monReview, EXCEPTION_TAB_HELP, helpForExceptionTab(), IDS, ACTION_LABEL (+31 more)

### Community 16 - "Analytics Charts UI"
Cohesion: 0.12
Nodes (28): scoped(), setIntent(), HBars(), Lines(), niceMax(), Segments(), Sparkline(), Tip() (+20 more)

### Community 17 - "Rules Exception APIs"
Cohesion: 0.20
Nodes (14): compile_mapping(), Return a fast row -> (record, errors) function for the active fields of a mappin, _active_fields(), check_file(), _critical(), _feeds(), Path, Schema-drift pre-flight: compare an incoming file with the source's approved map (+6 more)

### Community 18 - "Vendor Feed Profiles"
Cohesion: 0.24
Nodes (16): _clean(), create_vendor(), ensure_vendor(), get_vendor(), list_vendors(), move_feed(), ValueError, Vendors: the counterparty that owns one or more feeds.      Vendor (Cornerstone (+8 more)

### Community 19 - "Preflight Mapping Checks"
Cohesion: 0.21
Nodes (19): apply(), compile_tree(), decompile(), Compile AST → draft body fields (expression, field, fields, tests, summary, cate, Best-effort expression → tree. Returns None when unrecognized., summarize(), Guided rule shapes: compile / summarize / autotest / decompile., test_compile_date_order_uses_date_ops() (+11 more)

### Community 20 - "File Sequencing Gate"
Cohesion: 0.26
Nodes (12): _base_with(), catalog(), _compile_node(), _field(), _leaf_expr(), Any, ValueError, Typed rule shapes + condition trees for SME-guided authoring.  Leaves are catalo (+4 more)

### Community 21 - "JSON Logic Rules"
Cohesion: 0.16
Nodes (17): Shadow-style impact estimate: how many recently staged loans would this version, rule_impact(), _cmp(), compile_logic(), _get(), JsonLogicError, _loose_eq(), _num() (+9 more)

### Community 22 - "Rule Registry Store"
Cohesion: 0.23
Nodes (9): _get_bucket(), load_records(), SSE target loader: micro-batched, throttled upserts into the typed SSE loan tabl, Upsert [(sse_record, dq_status)] by loan_number. Returns rows written.      With, Insert, or replace a whole record (a full tape re-boarding an existing loan afte, to_sse_row(), TokenBucket, _write() (+1 more)

### Community 23 - "Vendors Imports UI"
Cohesion: 0.16
Nodes (18): buildHtml(), capture(), __dirname, esc(), filesTable(), flowExecute(), flowHighLevel(), flowMonitor() (+10 more)

### Community 24 - "Exception Batch Compare"
Cohesion: 0.14
Nodes (26): _apply_memory(), _detect_composites(), name_similarity(), normalize(), AI-assisted source-to-target mapping with confidence scoring.  Scoring combines, Reuse only the portable part of a remembered transform: its value translations., Run every proposed transform on the sample; demote suggestions that fail on real, Re-rank candidates with what humans approved/rejected for this column name befor (+18 more)

### Community 25 - "Exception Policy"
Cohesion: 0.23
Nodes (17): _clean_header(), detect_format(), estimate_rows(), _iter_excel(), iter_rows(), ParsedFile, ParseOptions, Path (+9 more)

### Community 26 - "Exception Manager Core"
Cohesion: 0.18
Nodes (11): _coerce(), ExceptionActionError, ExceptionManager, ValueError, Distinct file loads that have exceptions — options for vendor / file / date filt, Field-by-field comparison of an incoming duplicate with the loan already in SSE., Compliance has investigated outside EM (e.g. OFAC false positive) and records th, Undo a T1 auto-apply inside the rollback window (target < 5 min to execute). (+3 more)

### Community 27 - "API Enhancement Tests"
Cohesion: 0.18
Nodes (16): maintenance_artifact(), maintenance_artifacts(), get_artifact(), list_artifacts(), MaintenanceError, _notebook_cells(), Exception, Path (+8 more)

### Community 28 - "Lambda Path Tests"
Cohesion: 0.17
Nodes (20): _aws(), _executions(), _load(), The AWS execution path (EventBridge -> Step Functions -> Lambda) exercised again, In AWS the scheduler Lambda never moves files itself: a due pull starts the lbp-, moto Step Functions + Glue, LBP in AWS mode (dispatch -> Step Functions, data mo, The deploy step: migrations (no-op on a current schema here) + a signed configur, LBP/Pipeline metrics (dashboard + failure-rate alarm) come from the Glue jobs no (+12 more)

### Community 29 - "File Format Parser"
Cohesion: 0.09
Nodes (6): DynamoRuleStore, AWS backend. Table: pk rule_id (S), sk version (N), GSI 'status-index' on status, RuleStore, SqlRuleStore, _undecimal(), Protocol

### Community 30 - "Frontend Mock API"
Cohesion: 0.15
Nodes (19): ARTIFACTS, cellsOf(), getMaintenanceArtifact(), listMaintenanceArtifacts(), ApiError, clone(), createMockApi(), fail() (+11 more)

### Community 31 - "Audit History APIs"
Cohesion: 0.26
Nodes (11): _alembic_cfg(), check_config(), _demo_setup(), main(), migrate(), Operator commands.      python -m lbp.cli migrate          apply database migrat, publish_all(), Republish every live feed (rule or policy changes affect all of them). (+3 more)

### Community 32 - "Security Load Tests"
Cohesion: 0.11
Nodes (28): audit(), batch_changes(), batch_snapshot_reviews(), feed_config(), get_source(), loan_history(), A snapshot flagged as truncated: after checking with the vendor, an SME raises t, What this file changed (applied) and what it is still holding (pending review). (+20 more)

### Community 33 - "Analytics Service"
Cohesion: 0.29
Nodes (11): ai_mapping_insights(), dq_scorecard(), exception_analytics(), executive_summary(), _label(), _names(), Pillar 2 - analytics over the processed zone.  Six dashboards from the PoV (Impo, Group open exceptions into likely root causes.      Many exceptions on the same (+3 more)

### Community 34 - "Builtin Rule Validators"
Cohesion: 0.11
Nodes (25): emit_metrics(), partition_processor(), persist_stream(), process_batch(), pull(), Entry points for the AWS Glue data plane (thin wrappers in aws/glue/ call these), What each Spark partition runs: the same mapping + rule code as every other path, Driver step 3: persist processed rows (ordered by row number) in micro-batches w (+17 more)

### Community 35 - "Frontend Auth Personas"
Cohesion: 0.15
Nodes (20): FALLBACK_CAST, getVendorScope(), mockApi(), setPersona(), setVendorScope(), takeIntent(), vendorScope, App() (+12 more)

### Community 36 - "AWS Lambda Handlers"
Cohesion: 0.13
Nodes (13): _api(), demo_setup(), finalize_batch(), on_file_arrival(), AWS Lambda entry points: the thin control plane around the Glue data plane.  Lam, EventBridge Scheduler (rate 5 minutes): delivery windows and late/missed alerts., Load the compact demo scenario into RDS. Invoked directly; not exposed on the AP, API Gateway (HTTP API, payload v2) -> FastAPI. The bearer token is passed throug (+5 more)

### Community 37 - "Incremental Load Tests"
Cohesion: 0.11
Nodes (22): import_status(), _iso(), create_batch(), DuplicateFileError, file_sha256(), Path, ValueError, Register an arriving file. With strict=False (unattended S3/scheduler arrivals) (+14 more)

### Community 38 - "Deliveries Schedule UI"
Cohesion: 0.23
Nodes (12): create(), _directory(), list_for(), mark_all_read(), mark_read(), notify_many(), on_rule_transition(), peer_user_ids() (+4 more)

### Community 39 - "Mapping Field Inspect"
Cohesion: 0.10
Nodes (48): personas_cast(), personas_my_screens(), personas_screens(), personas_users(), Signed-in-as switcher people (local demo cast + enabled directory). Open to any, _admin_count(), cast_for_switcher(), _cognito() (+40 more)

### Community 40 - "Change File Apply"
Cohesion: 0.28
Nodes (14): _build_scenario(), Port of export_demo_snapshot scenario; row counts scale for compact/full., canonical_loans(), generate_all(), _inject_defect(), _loan(), Path, Synthetic loan file generator for the four PennyMac boarding sources.  Every sou (+6 more)

### Community 41 - "Sources Mapping UI"
Cohesion: 0.16
Nodes (15): read_policy(), Exception Manager: AI proposes, human disposes.  Resolution pipeline per failing, effective_policy(), get_policy(), PolicyError, ValueError, Confidence x Risk routing policy (the hard gate).  Thresholds live in the Policy, Live override rate of AI auto-applied fixes (rollbacks + failed QA samples / T1 (+7 more)

### Community 42 - "Exception RAG Retrieval"
Cohesion: 0.27
Nodes (14): templates(), create_template(), delete_template(), get_template(), list_templates(), ValueError, Persisted rule templates for SME maintenance + Author catalog., Insert missing built-in templates from shapes.templates(). Idempotent. (+6 more)

### Community 43 - "PII Profiling"
Cohesion: 0.19
Nodes (6): consensus(), OpenSearchPrecedentIndex, Precedent retrieval (the 'R' in RAG) over historically resolved exceptions.  Loc, If exact-match precedents agree, return (value, strength)., _shape(), SqlPrecedentIndex

### Community 44 - "Delivery Profile Logic"
Cohesion: 0.31
Nodes (8): current_principal(), _jwks_client(), Principal, principal_from_claims(), Authentication and role-based authorization.  Modes (LBP_AUTH_MODE):   dev  - id, FastAPI dependency: the caller must hold one of `roles` (admin always passes)., require(), verify_token()

### Community 45 - "Rule Authoring LLM"
Cohesion: 0.29
Nodes (6): Notifications, Out of scope, Peer pool (v1), Roles, Rule review workflow + in-app notifications, UI

### Community 46 - "conftest.py"
Cohesion: 0.33
Nodes (4): env(), onboarded(), All four sources onboarded and approved., sample_files()

### Community 47 - "Rule Registry Lifecycle"
Cohesion: 0.20
Nodes (9): API, Audience and access, Catalog (allowlist only), Intent, Maintenance · Glue artifacts (in-app viewer), Non-goals (Phase 1), Success, Testing (+1 more)

### Community 48 - "Frontend Cognito Auth"
Cohesion: 0.18
Nodes (18): setSignedIn(), b64url(), bearer(), decode(), initAuth(), load(), login(), logout() (+10 more)

### Community 49 - "Glue Job Entry Points"
Cohesion: 0.11
Nodes (17): 1. Stack and tooling, 2. Design tokens, 3. Shell, 4. Shared primitives migration, 5. In-scope pages, 6. Data flow and boundaries, 7. Error handling and a11y, 8. Testing and verification (+9 more)

### Community 50 - "Local S3 Storage"
Cohesion: 0.09
Nodes (25): ai_suggest(), approve_delivery(), approve_mapping(), checker(), Decision, delete_rule(), _err(), field_values() (+17 more)

### Community 51 - "test_scheduler.py"
Cohesion: 0.27
Nodes (10): create_source(), presign(), Path, Stream an upload to disk with size, extension and content-type checks (no execut, Add a feed (a file layout from a vendor) from a sample file; the AI drafts its m, AWS: browser PUTs straight to the raw S3 zone; EventBridge starts the Step Funct, _save_upload(), upload() (+2 more)

### Community 52 - "Incremental Row Planner"
Cohesion: 0.12
Nodes (16): 1. Kit layout, 2. Shared module: `backend/lbp/demo_setup.py`, 3. API, 4. CLI and `start_demo.sh`, 5. UI, 6. Security and production, 7. Testing, 8. Docs (+8 more)

### Community 53 - "File map"
Cohesion: 0.13
Nodes (14): App UX Phase A Implementation Plan, Execution handoff, File map, Global Constraints, Review Focus, Spec coverage (self-review), Task 1: Hash helpers, Task 2: Nav model (+6 more)

### Community 54 - "default_rules.py"
Cohesion: 0.14
Nodes (24): accept_all(), add_field(), _columns(), diff_versions(), load_memory(), MappingError, memory_stats(), Path (+16 more)

### Community 55 - "profile_of"
Cohesion: 0.14
Nodes (23): _seq(), get_delivery(), list_sources(), How a file named like this would be treated: load type, file-level action, seque, test_filename(), incremental_context(), Per-batch context for change files (from the published feed configuration): effe, decide_profile() (+15 more)

### Community 56 - "Review Focus"
Cohesion: 0.22
Nodes (8): Global Constraints, Maintenance · Glue artifacts Implementation Plan, Review Focus, Self-review notes, Task 1: Allowlist + read helpers + tests, Task 2: API routes + ROUTE_ROLES, Task 3: Frontend CAPS + Maintenance page + rail, Task 4: Graphify + smoke

### Community 57 - "OpenSearchPrecedentIndex"
Cohesion: 0.10
Nodes (44): api(), changedKeys(), DeliveryProfile(), EditModal(), ReviewModal(), FeedConfigChip(), DemoSetupModal(), PolicyModal() (+36 more)

### Community 58 - "run_demo_setup"
Cohesion: 0.18
Nodes (11): data_is_present(), Find demo_kit: LBP_DEMO_KIT → <root>/demo_kit → <root>/demo-kit/demo_kit., resolve_kit_dir(), Demo kit setup: resolver, wipe/conflict, run_demo_setup, API., test_data_is_present_false_on_fresh_env(), test_data_is_present_true_after_source(), test_resolve_kit_dir_env_override(), test_resolve_kit_dir_falls_back_to_hyphen_nest() (+3 more)

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
Cohesion: 0.18
Nodes (23): _date(), _op_to_date(), _parse_date(), CronError, _day_matches(), _field(), is_business_day(), _last_weekday() (+15 more)

### Community 65 - "Transform Unit Tests"
Cohesion: 0.14
Nodes (13): Demo Kit In-App Implementation Plan, Execution handoff, File structure, Global Constraints, Review Focus, Spec coverage check, Task 1: Kit layout + resolver, Task 2: Emptiness check, wipe, `SetupResult` shell (+5 more)

### Community 66 - "Deliveries.jsx"
Cohesion: 0.18
Nodes (21): CELL, cronFrom(), Deliveries(), DOW, HistoryStrip(), OPEN, presetOf(), ScheduleEditor() (+13 more)

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
Cohesion: 0.18
Nodes (10): notify(), Operational alerts: always logged and audited; published to SNS when LBP_ALERT_T, _record_pull_error(), check_schema_current(), _ensure_chain_head(), _entry_hash(), datetime, Relational store (SQLAlchemy Core).  Local: SQLite. AWS: RDS SQL Server (the SSE (+2 more)

### Community 73 - "Vendor Sequencing Docs"
Cohesion: 0.33
Nodes (6): CHG06 Cross-Vendor Loan Change, Per-Vendor File Sequencing Gate, Vendor, SSE Target Schema, Pipe-Delimited Sub-Servicing Columns, Sub-Servicing Sample Loan Tape

### Community 74 - "run_batch"
Cohesion: 0.15
Nodes (20): BatchBusyError, _chunks(), Exception, RuntimeError, In-process runner (local API mode): run the batch, then any files it released fr, Error text for storage/UI: first line only, never the SQL parameters (they can c, _run_and_follow(), run_batch() (+12 more)

### Community 75 - "SFTP Scheduler Docs"
Cohesion: 0.50
Nodes (5): paramiko SFTP Dependency, Glue Job lbp-vendor-pull, Delivery Scheduler, Scheduler Tick, SFTP Pull Connector with Host-Key Pinning

### Community 78 - "demo_setup"
Cohesion: 0.18
Nodes (10): File map, Global Constraints, Guided Rule Authoring Implementation Plan, Review Focus, Task 1: JSON Logic new operators, Task 2: shapes compiler, Task 3: API + registry, Task 4: Authoring → tree (+2 more)

### Community 79 - "remap_batch"
Cohesion: 0.15
Nodes (15): batch_apply_ooo(), batch_discard(), batch_skip_gap(), feed_publish(), lifespan(), Override, override_preflight(), Local single-process mode: tick the delivery scheduler every minute and start wh (+7 more)

### Community 101 - "canCap"
Cohesion: 0.10
Nodes (26): getPersona(), GROUP_LABEL, GROUP_ORDER, JobsPane(), Maintenance(), TemplateEditor(), ACTION_LABEL, AUTHOR_STEPS (+18 more)

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
Cohesion: 0.16
Nodes (15): RuleExecutor, ValueError, Rules the executor needs: active, plus canary and shadow candidates., Hard-delete every version of a rule. Republishes live feeds if any version was r, RuleError, RuleRegistry, signature(), _draft() (+7 more)

### Community 111 - "_vendor_call"
Cohesion: 0.33
Nodes (7): move_feed(), MoveFeed, _vendor_call(), VendorIn, vendors_create(), vendors_get(), vendors_update()

### Community 112 - "profiler.py"
Cohesion: 0.18
Nodes (13): ai_map(), ColumnProfile, infer_type(), profile_column(), profile_rows(), Source data profiling: per-column type inference, completeness, cardinality, pat, Collapse a value into a pattern like 'AAA9999' for pattern profiling., Returns (dtype, date_format). (+5 more)

### Community 113 - "inspect.py"
Cohesion: 0.26
Nodes (14): mapping_dq_rules(), describe_step(), field_inspect(), _load(), mapping_dq(), Field-level inspection for the Mapping UI.  For one SSE target attribute in a ma, Every rule in the registry against this mapping's sample: fail counts and field, Every distinct source value for a field, what it becomes in SSE and whether that (+6 more)

### Community 115 - "inspect_field_draft"
Cohesion: 0.24
Nodes (12): BATCH_ATTENTION, BATCH_SEV, buildAttentionRows(), buildLoadHealth(), calendarDay(), dayKey(), DELIVERY_OPEN, DELIVERY_SEV (+4 more)

### Community 116 - "update_policy"
Cohesion: 0.10
Nodes (28): accept_all(), compliance_clear(), deliveries_waive(), demo_seed(), escalate(), list_notifications(), list_rules(), maintenance_delete_rule_template() (+20 more)

### Community 117 - "Review Focus"
Cohesion: 0.17
Nodes (11): App UX Phases B–D Implementation Plan, Global Constraints, Review Focus, Spec coverage, Task 1: Phase B — Imports, Task 2: Phase B — Exceptions, Task 3: Phase B — Analytics + Deliveries, Task 4: Phase C — Sources / Vendors / DeliveryProfile / FeedConfig chrome (+3 more)

### Community 118 - "progress.md"
Cohesion: 0.53
Nodes (5): _board_one(), Exceptions are filterable/groupable by vendor, file, and load date., test_exception_list_filters_by_loaded_on_and_batch(), test_exception_list_includes_filename_and_loaded_at(), test_exception_loads_endpoint()

### Community 120 - "test_incremental.py"
Cohesion: 0.46
Nodes (14): _boarded_pcg(), _pick(), Incremental / snapshot loads, change control and per-vendor sequencing (end to e, A reviewer corrected a value at boarding; the vendor's next snapshot re-sends th, _run(), _set_profile(), _sse(), test_incremental_sparse_updates_closes_and_change_control() (+6 more)

### Community 122 - "row_to_dict"
Cohesion: 0.25
Nodes (7): Cognito / `ROLES`, Demo cast (6), Four teams + in-team reviewers, Intent, Legacy aliases (dev / old headers / leftover data), Non-goals, Ownership

### Community 123 - "DeliveryProfile.jsx"
Cohesion: 0.29
Nodes (7): _draft(), In-app notifications for rule peer review., Fail closed: missing author must not allow self-approve; submitter is also block, test_author_cannot_approve_peer_can_and_author_notified(), test_delete_rule_removes_all_versions(), test_submit_notifies_peer_pool_not_author(), test_submitter_cannot_approve_even_if_author_field_cleared()

### Community 124 - "DynamoRuleStore"
Cohesion: 0.19
Nodes (13): Used by tests after changing environment variables., reset_settings(), DemoSetupConflict, Exception, Path, Raised when demo data already exists and force=False., Delete managed contents under data_dir and reset the SQLAlchemy engine., Build the DEMO_GUIDE scenario into the current LBP_DATA_DIR. (+5 more)

### Community 125 - "test_vendors.py"
Cohesion: 0.36
Nodes (7): _feed(), _incremental(), Vendors own feeds; operations are scoped and protected at vendor level., _sse(), test_change_file_cannot_touch_another_vendors_loans(), test_snapshot_compares_the_vendors_whole_portfolio(), test_vendor_crud_roles_and_rollups()

### Community 126 - "DuplicateFileError"
Cohesion: 0.29
Nodes (6): Intent, Layout, Locked decisions, Non-goals, Overview as boarding load desk, Success

### Community 127 - "._finalize_loan"
Cohesion: 0.23
Nodes (8): Apply resolved values, re-validate, board to SSE when no blocking exceptions rem, Pure (no DB writes) triage used inside the pipeline workers' parent process., Triage, Classify/propose/route every failure; apply T1 fixes and re-validate. Pure (no D, Change-control routing on top of confidence x risk: a protected-field change alw, _route_change_rule(), _triage_results(), risk_of()

### Community 128 - "ETL Monitor (fleet ops console)"
Cohesion: 0.15
Nodes (12): API, Error handling, ETL Monitor (fleet ops console), Frontend touchpoints, `GET /api/batches` (extend), Intent, Locked decisions, Monitor layout (+4 more)

### Community 129 - ".runtime_set"
Cohesion: 0.50
Nodes (3): File map, Overview load desk Implementation Plan, Tasks

### Community 133 - "list_rules"
Cohesion: 0.22
Nodes (13): fix_fico(), fix_investor_gnma(), fix_loan_number(), fix_maturity(), fix_occupancy(), fix_rate(), fix_servicing_fee(), fix_state() (+5 more)

### Community 134 - "Monitor.jsx"
Cohesion: 0.27
Nodes (8): buildBatchesPath(), LIVE_STATUSES, splitLiveAndHistory(), BatchRows(), DAY_OPTS, Monitor(), STATUS_OPTS, STEP_PILL

### Community 135 - "local_path"
Cohesion: 0.27
Nodes (10): is_s3(), local_path(), persist_upload(), Path, File storage: local paths in development, S3 in AWS (ECS task disks are ephemera, Store an uploaded file durably and return its URI (S3 in AWS, the local path oth, _s3(), _split() (+2 more)

### Community 136 - "helpTipPos.test.js"
Cohesion: 0.29
Nodes (6): helpTipFixedPos(), mid, nearBottom, nearRight, roomBelow, HelpTip()

### Community 137 - "config.py"
Cohesion: 0.22
Nodes (7): _apply_ssm(), db_secret(), Runtime configuration. Every setting can be overridden with an LBP_* environment, RDS-managed secret {username, password}. Cached briefly; refreshed after rotatio, Overlay settings published by Terraform under LBP_SSM_PREFIX (e.g. the Cognito c, Settings that must hold outside a developer laptop. The API refuses to start oth, Settings

### Community 138 - "File map"
Cohesion: 0.18
Nodes (10): ETL Monitor Implementation Plan, File map, Global Constraints, Review Focus, Self-review notes, Task 1: `import_status` filters + `attention`, Task 2: Wire `GET /api/batches` query params, Task 3: Nav, personas, screen copy (+2 more)

### Community 139 - "mask_value"
Cohesion: 0.27
Nodes (8): detect_column_pii(), mask_record(), mask_value(), _norm(), PII detection and dynamic masking.  Two signals are combined: column-name semant, partial: keep last 4 (SSN/phone) or first letter (name); hash: deterministic tok, _mask_raw(), Data minimisation for staging (GLBA safeguards).  Once a loan is boarded (or the

### Community 140 - "test_routing_exceptions.py"
Cohesion: 0.31
Nodes (9): _batch(), test_bulk_resolve(), test_pause_and_resume_from_checkpoint(), test_pipeline_reconciles(), test_routing_matrix(), test_t2_resolution_boards_loan(), test_t4_maker_checker(), test_t5_only_compliance() (+1 more)

### Community 141 - "apply_field"
Cohesion: 0.28
Nodes (8): apply_field(), Any, Apply one field mapping to a raw source row. Raises TransformError., test_casts_and_lookups(), test_composite_split_and_concat(), test_default_injection(), test_jsonlogic_guided_authoring_ops(), test_jsonlogic_ops()

### Community 142 - "fetch_traces"
Cohesion: 0.28
Nodes (7): _brief(), fetch_traces(), Step Functions history for a batch, reduced to the steps and short returns the d, Turn GetExecutionHistory events into ordered steps. Choice states are skipped., Latest execution for each batch id. Empty when this process is not on AWS., summarize_events(), test_summarize_events_keeps_each_step_and_its_return()

### Community 143 - "demo_setup.py"
Cohesion: 0.25
Nodes (4): Any, Build the demo-kit sales scenario into a local data dir.  Used by CLI, start_dem, SetupResult, Builds a realistic platform state and exports API responses for the web app's de

### Community 144 - "get_settings"
Cohesion: 0.38
Nodes (7): Public settings the web app needs to sign users in (no secrets)., web_config(), get_settings(), _bucket(), _local_root(), Path, _write()

### Community 145 - "worker.py"
Cohesion: 0.43
Nodes (6): Requeue batches whose worker stopped heart-beating (crash, OOM, deploy). They re, recover_stale(), claim_next(), main(), Long-running processing worker (ECS Fargate 'worker' task, or `python -m lbp.wor, _sigterm()

### Community 146 - "run"
Cohesion: 0.33
Nodes (5): migrate(), Invoked once per deploy: Alembic migrations, default rule seed, and a signed con, Alembic environment: schema is defined in lbp.store.db.metadata; URL from LBP se, run(), test_transform_errors_are_captured_not_raised()

### Community 147 - "test_sequencing_gate_is_atomic_across_workers"
Cohesion: 0.33
Nodes (4): Multi-writer safety. Meaningful on a real RDBMS (set LBP_TEST_DATABASE_URL); SQL, 8 workers race for two change files of one vendor (sequence 1 and 2): exactly on, test_only_one_worker_wins_a_lease(), test_sequencing_gate_is_atomic_across_workers()

### Community 148 - "create_rule"
Cohesion: 0.40
Nodes (5): create_rule(), edit_rule(), _materialize_rule(), Prefer tree → expression; keep legacy expression path., RuleBody

### Community 149 - "demo_setup"
Cohesion: 0.67
Nodes (3): demo_setup(), DemoSetupIn, Load the demo-kit sales scenario (vendors, schedules, exceptions). Admin + enabl

## Knowledge Gaps
- **276 isolated node(s):** `lbp`, `start_demo.sh script`, `__dirname`, `ROOT`, `SHOTS` (+271 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `get_settings` to `SFTP File Pullers`, `Delivery Scheduling`, `FastAPI Route Mounts`, `Boarding Batch Pipeline`, `Frontend Delivery UI`, `local_path`, `config.py`, `Mapping Override APIs`, `Signed Config Store`, `demo_setup.py`, `fetch_traces`, `worker.py`, `run`, `demo_setup`, `Rule Registry Store`, `JSON Logic Rules`, `File Format Parser`, `Audit History APIs`, `Security Load Tests`, `Builtin Rule Validators`, `Incremental Load Tests`, `Mapping Field Inspect`, `Change File Apply`, `Delivery Profile Logic`, `test_scheduler.py`, `run_demo_setup`, `shapes.py`, `run_batch`, `remap_batch`, `update_policy`, `DynamoRuleStore`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._
- **Why does `RuleRegistry` connect `wipe_data_dir` to `FastAPI Route Mounts`, `Boarding Batch Pipeline`, `Signed Config Store`, `demo_setup.py`, `worker.py`, `JSON Logic Rules`, `Exception Policy`, `File Format Parser`, `Audit History APIs`, `Incremental Load Tests`, `Change File Apply`, `Sources Mapping UI`, `conftest.py`, `default_rules.py`, `run_demo_setup`, `remap_batch`, `test_security.py`, `inspect.py`, `DeliveryProfile.jsx`, `DynamoRuleStore`, `._finalize_loan`?**
  _High betweenness centrality (0.045) - this node is a cross-community bridge._
- **Why does `get_engine()` connect `Security Load Tests` to `AI Mapping Engine`, `Delivery Scheduling`, `FastAPI Route Mounts`, `config.py`, `Exception Decision APIs`, `Mapping Override APIs`, `Signed Config Store`, `get_settings`, `worker.py`, `Vendor Feed Profiles`, `JSON Logic Rules`, `Exception Policy`, `Audit History APIs`, `Analytics Service`, `Builtin Rule Validators`, `Incremental Load Tests`, `Deliveries Schedule UI`, `Mapping Field Inspect`, `Change File Apply`, `Sources Mapping UI`, `Exception RAG Retrieval`, `default_rules.py`, `profile_of`, `run_demo_setup`, `shapes.py`, `run_batch`, `remap_batch`, `inspect.py`, `update_policy`, `DynamoRuleStore`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `get_settings()` (e.g. with `run()` and `test_wipe_data_dir_clears_presence()`) actually correct?**
  _`get_settings()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `create_batch()` (e.g. with `on_file_arrival()` and `main()`) actually correct?**
  _`create_batch()` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `run_batch()` (e.g. with `main()` and `test_batches_http_filters_status_and_days()`) actually correct?**
  _`run_batch()` has 27 INFERRED edges - model-reasoned connections that need verification._
- **What connects `lbp`, `start_demo.sh script`, `__dirname` to the rest of the system?**
  _276 weakly-connected nodes found - possible documentation gaps or missing edges._