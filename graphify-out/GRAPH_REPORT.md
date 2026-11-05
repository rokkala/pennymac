# Graph Report - pennymac  (2026-11-05)

## Corpus Check
- 166 files · ~387,751 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1845 nodes · 4572 edges · 116 communities (102 shown, 14 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 287 edges (avg confidence: 0.75)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `d1c1a1f2`
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
- Rule Executor
- Rule Registry Lifecycle
- Frontend Cognito Auth
- Glue Job Entry Points
- Local S3 Storage
- Incremental Row Planner
- Exceptions Console UI
- Source Upload APIs
- Review Focus
- OpenSearchPrecedentIndex
- Change Control Docs
- Backend Dependencies
- Docker Compose Stack
- Platform Architecture Docs
- OIDC Deploy Workflow
- Transform Unit Tests
- __init__.py
- Signed Glue Config Docs
- CI Workflow Jobs
- Load Test Evidence Docs
- API Auth Hardening
- Schedule CRUD APIs
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
- progress.md
- _sched_call

## God Nodes (most connected - your core abstractions)
1. `get_engine()` - 124 edges
2. `get_settings()` - 73 edges
3. `User` - 68 edges
4. `useApi()` - 55 edges
5. `run_batch()` - 52 edges
6. `create_batch()` - 50 edges
7. `audit()` - 50 edges
8. `api()` - 50 edges
9. `RuleRegistry` - 47 edges
10. `useAction()` - 47 edges

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

## Communities (116 total, 14 thin omitted)

### Community 0 - "AI Mapping Engine"
Cohesion: 0.14
Nodes (28): accept_all(), add_field(), approve(), _columns(), diff_versions(), get_mapping(), MappingError, memory_stats() (+20 more)

### Community 1 - "SFTP File Pullers"
Cohesion: 0.06
Nodes (35): allowed_hosts(), fetch_new(), LocalPuller, make_puller(), _ok_name(), Puller, PullError, Path (+27 more)

### Community 2 - "Delivery Scheduling"
Cohesion: 0.14
Nodes (35): describe(), local_label(), Short human description for common shapes; falls back to the expression., Vendor delivery scheduling: calendars, expected deliveries, late/missed alerts,, create_schedule(), decide(), effective(), get_schedule() (+27 more)

### Community 3 - "FastAPI Route Mounts"
Cohesion: 0.05
Nodes (42): a_ai(), a_ask(), a_dq(), a_exceptions(), a_exec(), a_import(), a_sources(), a_systemic() (+34 more)

### Community 4 - "Frontend Package Deps"
Cohesion: 0.06
Nodes (34): eslint, @eslint/js, eslint-plugin-react, eslint-plugin-react-hooks, dependencies, react, react-dom, devDependencies (+26 more)

### Community 5 - "Boarding Batch Pipeline"
Cohesion: 0.09
Nodes (29): partition_processor(), What each Spark partition runs: the same mapping + rule code as every other path, _acquire_lease(), _fails_of(), incremental_context(), process_chunk(), Exception, Micro-batch boarding pipeline: parse -> map/transform -> validate -> triage -> l (+21 more)

### Community 6 - "Frontend Delivery UI"
Cohesion: 0.27
Nodes (11): CELL, cronFrom(), Deliveries(), DOW, HistoryStrip(), OPEN, presetOf(), ScheduleEditor() (+3 more)

### Community 7 - "Local Scheduler Config"
Cohesion: 0.22
Nodes (9): profile_rows(), load_memory(), Path, Register a feed. `vendor_id` places it under a vendor; without one, a vendor of, register_source(), test_auto_map_rate_and_accuracy(), test_composites_and_units(), test_one_source_many_targets_and_retarget() (+1 more)

### Community 8 - "Field Transforms"
Cohesion: 0.05
Nodes (62): fix_fico(), fix_investor_gnma(), fix_loan_number(), fix_maturity(), fix_occupancy(), fix_rate(), fix_servicing_fee(), fix_state() (+54 more)

### Community 9 - "Demo Sample Generator"
Cohesion: 0.14
Nodes (3): RuleStore, SqlRuleStore, Protocol

### Community 10 - "CLI Worker DB"
Cohesion: 0.29
Nodes (5): _bucket(), Evaluation, Stateless rule executor (runs in-process, in worker processes, on Lambda or ECS, RuleExecutor, RuleResult

### Community 11 - "Governance Rules UI"
Cohesion: 0.15
Nodes (17): Overview(), Personas(), ROLE_ORDER, Bar(), fmtCompact(), fmtMoney(), Kpis(), Loading() (+9 more)

### Community 12 - "Exception Decision APIs"
Cohesion: 0.14
Nodes (26): _apply_memory(), _detect_composites(), name_similarity(), normalize(), AI-assisted source-to-target mapping with confidence scoring.  Scoring combines, Reuse only the portable part of a remembered transform: its value translations., Run every proposed transform on the sample; demote suggestions that fail on real, Re-rank candidates with what humans approved/rejected for this column name befor (+18 more)

### Community 13 - "Mapping Override APIs"
Cohesion: 0.07
Nodes (30): add_mapping_field(), DeliveryProfileIn, demo_setup(), DemoSetupIn, maintenance_create_rule_template(), NewField, Override, override_preflight() (+22 more)

### Community 14 - "Signed Config Store"
Cohesion: 0.18
Nodes (20): _bucket(), build(), bundle_json(), _canonical(), ConfigError, FeedConfig, _key(), _local_root() (+12 more)

### Community 15 - "Cron Business Calendar"
Cohesion: 0.09
Nodes (34): BatchBusyError, _chunks(), create_batch(), DuplicateFileError, file_sha256(), override_preflight(), Path, RuntimeError (+26 more)

### Community 16 - "Analytics Charts UI"
Cohesion: 0.13
Nodes (32): scoped(), HBars(), heatColor(), Lines(), niceMax(), Segments(), Sparkline(), Tip() (+24 more)

### Community 17 - "Rules Exception APIs"
Cohesion: 0.29
Nodes (7): _draft(), In-app notifications for rule peer review., Fail closed: missing author must not allow self-approve; submitter is also block, test_author_cannot_approve_peer_can_and_author_notified(), test_delete_rule_removes_all_versions(), test_submit_notifies_peer_pool_not_author(), test_submitter_cannot_approve_even_if_author_field_cleared()

### Community 18 - "Vendor Feed Profiles"
Cohesion: 0.20
Nodes (18): batch_snapshot_reviews(), A snapshot flagged as truncated: after checking with the vendor, an SME raises t, profile_of(), Effective profile: stored values over defaults (nested one level)., _clean(), create_vendor(), ensure_vendor(), get_vendor() (+10 more)

### Community 19 - "Preflight Mapping Checks"
Cohesion: 0.05
Nodes (63): AnthropicClient, BedrockClient, get_llm(), LLMClient, LLMMappingReranker, Pluggable LLM access used by mapping re-ranking, rule authoring (English -> DSL), Asks the model to choose among the heuristic top-K for each column., _base_with() (+55 more)

### Community 20 - "File Sequencing Gate"
Cohesion: 0.16
Nodes (21): request_pause(), next_integer(), acquire(), advance(), apply_out_of_order(), discard(), gate(), is_sequenced() (+13 more)

### Community 21 - "JSON Logic Rules"
Cohesion: 0.16
Nodes (17): Shadow-style impact estimate: how many recently staged loans would this version, rule_impact(), _cmp(), compile_logic(), _get(), JsonLogicError, _loose_eq(), _num() (+9 more)

### Community 22 - "Rule Registry Store"
Cohesion: 0.17
Nodes (7): publish_all(), Republish every live feed (rule or policy changes affect all of them)., DynamoRuleStore, r"""Versioned, signed Rule Registry with HITL lifecycle gates.      draft -> in_, AWS backend. Table: pk rule_id (S), sk version (N), GSI 'status-index' on status, Hard-delete every version of a rule. Republishes live feeds if any version was r, _undecimal()

### Community 23 - "Vendors Imports UI"
Cohesion: 0.16
Nodes (18): buildHtml(), capture(), __dirname, esc(), filesTable(), flowExecute(), flowHighLevel(), flowMonitor() (+10 more)

### Community 24 - "Exception Batch Compare"
Cohesion: 0.29
Nodes (8): ACTION_TXT, changedKeys(), clone(), DeliveryProfile(), EditModal(), LT, ReviewModal(), Panel()

### Community 25 - "Exception Policy"
Cohesion: 0.23
Nodes (17): _clean_header(), detect_format(), estimate_rows(), _iter_excel(), iter_rows(), ParsedFile, ParseOptions, Path (+9 more)

### Community 26 - "Exception Manager Core"
Cohesion: 0.14
Nodes (17): batch_loans(), _coerce(), ExceptionActionError, ExceptionManager, ValueError, Field-by-field comparison of an incoming duplicate with the loan already in SSE., Compliance has investigated outside EM (e.g. OFAC false positive) and records th, Undo a T1 auto-apply inside the rollback window (target < 5 min to execute). (+9 more)

### Community 27 - "API Enhancement Tests"
Cohesion: 0.18
Nodes (16): maintenance_artifact(), maintenance_artifacts(), get_artifact(), list_artifacts(), MaintenanceError, _notebook_cells(), Exception, Path (+8 more)

### Community 28 - "Lambda Path Tests"
Cohesion: 0.11
Nodes (28): current_principal(), _jwks_client(), Principal, principal_from_claims(), Authentication and role-based authorization.  Modes (LBP_AUTH_MODE):   dev  - id, FastAPI dependency: the caller must hold one of `roles` (admin always passes)., require(), verify_token() (+20 more)

### Community 29 - "File Format Parser"
Cohesion: 0.33
Nodes (9): _active_fields(), check_file(), _critical(), _feeds(), Path, Schema-drift pre-flight: compare an incoming file with the source's approved map, sparse=True for incremental change files: vendors may send only the loan number, _rename_guess() (+1 more)

### Community 30 - "Frontend Mock API"
Cohesion: 0.15
Nodes (19): ARTIFACTS, cellsOf(), getMaintenanceArtifact(), listMaintenanceArtifacts(), ApiError, clone(), createMockApi(), fail() (+11 more)

### Community 31 - "Audit History APIs"
Cohesion: 0.11
Nodes (25): _alembic_cfg(), check_config(), _demo_setup(), main(), migrate(), Operator commands.      python -m lbp.cli migrate          apply database migrat, Requeue batches whose worker stopped heart-beating (crash, OOM, deploy). They re, recover_stale() (+17 more)

### Community 32 - "Security Load Tests"
Cohesion: 0.15
Nodes (11): main(), Throughput test: generate N loans, onboard the source, board through the full pi, _client(), RDS-managed secret is read per connection; Cognito client id comes from SSM (as, _rsa(), test_jwt_mode(), test_npi_never_in_error_messages_and_retention(), test_production_refuses_unsafe_config() (+3 more)

### Community 33 - "Analytics Service"
Cohesion: 0.12
Nodes (32): ai_mapping_insights(), dq_scorecard(), exception_analytics(), executive_summary(), import_status(), _iso(), _label(), _names() (+24 more)

### Community 34 - "Builtin Rule Validators"
Cohesion: 0.14
Nodes (18): is_protected_change(), norm(), Comparable form of a field value (mapped record vs. typed SSE row)., _fail(), plan_row(), Incremental and snapshot row planning (pure; runs inside the pipeline worker pro, (action, code) where action is None for an unrecognised code., Decide the row's action and build the record to validate. Returns     {action, r (+10 more)

### Community 35 - "Frontend Auth Personas"
Cohesion: 0.21
Nodes (14): getVendorScope(), mockApi(), PERSONAS, setPersona(), setSignedIn(), setVendorScope(), takeIntent(), vendorScope (+6 more)

### Community 36 - "AWS Lambda Handlers"
Cohesion: 0.13
Nodes (13): _api(), finalize_batch(), migrate(), on_file_arrival(), AWS Lambda entry points: the thin control plane around the Glue data plane.  Lam, EventBridge Scheduler (rate 5 minutes): delivery windows and late/missed alerts., Invoked once per deploy: Alembic migrations, default rule seed, and a signed con, API Gateway (HTTP API, payload v2) -> FastAPI. The bearer token is passed throug (+5 more)

### Community 37 - "Incremental Load Tests"
Cohesion: 0.36
Nodes (8): _batch(), test_bulk_resolve(), test_pipeline_reconciles(), test_routing_matrix(), test_t2_resolution_boards_loan(), test_t4_maker_checker(), test_t5_only_compliance(), test_triage_proposals()

### Community 38 - "Deliveries Schedule UI"
Cohesion: 0.11
Nodes (21): read_policy(), Exception Manager: AI proposes, human disposes.  Resolution pipeline per failing, effective_policy(), get_policy(), PolicyError, ValueError, Confidence x Risk routing policy (the hard gate).  Thresholds live in the Policy, Live override rate of AI auto-applied fixes (rollbacks + failed QA samples / T1 (+13 more)

### Community 39 - "Mapping Field Inspect"
Cohesion: 0.08
Nodes (52): personas_my_screens(), personas_screens(), personas_users(), create(), _directory(), list_for(), mark_all_read(), mark_read() (+44 more)

### Community 40 - "Change File Apply"
Cohesion: 0.22
Nodes (13): Attach the live SSE records of the loans in this chunk (fetched just before the, with_current(), apply_closes(), apply_updates(), conflict_failures(), current_rows(), masked_changes(), Apply incremental changes to SSE safely.  Updates write only the fields that cha (+5 more)

### Community 41 - "Sources Mapping UI"
Cohesion: 0.11
Nodes (34): decide_profile(), DeliveryError, extract_sequence(), _norm_seq(), propose_profile(), ValueError, Vendor delivery profiles: how a source sends data, and what each row of a file m, Sortable sequence for a file, or None when the source is not sequenced. (+26 more)

### Community 42 - "Exception RAG Retrieval"
Cohesion: 0.67
Nodes (3): Confidence and a proposed transform for an analyst-chosen source -> target pair., suggest_mapping_pair(), SuggestReq

### Community 43 - "PII Profiling"
Cohesion: 0.24
Nodes (11): detect_column_pii(), _norm(), PII detection and dynamic masking.  Two signals are combined: column-name semant, ColumnProfile, infer_type(), profile_column(), Source data profiling: per-column type inference, completeness, cardinality, pat, Collapse a value into a pattern like 'AAA9999' for pattern profiling. (+3 more)

### Community 44 - "Delivery Profile Logic"
Cohesion: 0.67
Nodes (3): Turn the drift report into a draft mapping version (renames + date formats) for, Remap, remap_batch()

### Community 45 - "Rule Authoring LLM"
Cohesion: 0.29
Nodes (6): Notifications, Out of scope, Peer pool (v1), Roles, Rule review workflow + in-app notifications, UI

### Community 46 - "Rule Executor"
Cohesion: 0.17
Nodes (19): mapping_dq_rules(), describe_step(), field_inspect(), _load(), mapping_dq(), Field-level inspection for the Mapping UI.  For one SSE target attribute in a ma, Every rule in the registry against this mapping's sample: fail counts and field, Every distinct source value for a field, what it becomes in SSE and whether that (+11 more)

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
Cohesion: 0.09
Nodes (28): ai_suggest(), approve_delivery(), approve_mapping(), batch_apply_ooo(), batch_discard(), batch_skip_gap(), checker(), Decision (+20 more)

### Community 52 - "Incremental Row Planner"
Cohesion: 0.12
Nodes (16): 1. Kit layout, 2. Shared module: `backend/lbp/demo_setup.py`, 3. API, 4. CLI and `start_demo.sh`, 5. UI, 6. Security and production, 7. Testing, 8. Docs (+8 more)

### Community 54 - "Exceptions Console UI"
Cohesion: 0.15
Nodes (23): admin, lee, maria, ACTION_LABEL, CHANGE_RULES, ChangeControl(), ExceptionModal(), Exceptions() (+15 more)

### Community 55 - "Source Upload APIs"
Cohesion: 0.25
Nodes (11): ai_map(), create_source(), presign(), Path, Stream an upload to disk with size, extension and content-type checks (no execut, Add a feed (a file layout from a vendor) from a sample file; the AI drafts its m, AWS: browser PUTs straight to the raw S3 zone; EventBridge starts the Step Funct, _save_upload() (+3 more)

### Community 56 - "Review Focus"
Cohesion: 0.22
Nodes (8): Global Constraints, Maintenance · Glue artifacts Implementation Plan, Review Focus, Self-review notes, Task 1: Allowlist + read helpers + tests, Task 2: API routes + ROUTE_ROLES, Task 3: Frontend CAPS + Maintenance page + rail, Task 4: Graphify + smoke

### Community 57 - "OpenSearchPrecedentIndex"
Cohesion: 0.13
Nodes (39): api(), setIntent(), FeedConfigChip(), FeedConfigModal(), AuditModal(), DemoSetupModal(), EDITABLE, Governance() (+31 more)

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

### Community 65 - "Transform Unit Tests"
Cohesion: 0.14
Nodes (13): Demo Kit In-App Implementation Plan, Execution handoff, File structure, Global Constraints, Review Focus, Spec coverage check, Task 1: Kit layout + resolver, Task 2: Emptiness check, wipe, `SetupResult` shell (+5 more)

### Community 66 - "__init__.py"
Cohesion: 0.10
Nodes (23): accept_all(), Bulk, bulk_resolve(), compliance_clear(), demo_seed(), escalate(), list_notifications(), list_rules() (+15 more)

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

### Community 73 - "Vendor Sequencing Docs"
Cohesion: 0.33
Nodes (6): CHG06 Cross-Vendor Loan Change, Per-Vendor File Sequencing Gate, Vendor, SSE Target Schema, Pipe-Delimited Sub-Servicing Columns, Sub-Servicing Sample Loan Tape

### Community 74 - "Preflight Override Path"
Cohesion: 0.06
Nodes (46): Used by tests after changing environment variables., reset_settings(), _build_scenario(), data_is_present(), DemoSetupConflict, Any, Exception, Path (+38 more)

### Community 75 - "SFTP Scheduler Docs"
Cohesion: 0.50
Nodes (5): paramiko SFTP Dependency, Glue Job lbp-vendor-pull, Delivery Scheduler, Scheduler Tick, SFTP Pull Connector with Host-Key Pinning

### Community 78 - "demo_setup"
Cohesion: 0.18
Nodes (10): File map, Global Constraints, Guided Rule Authoring Implementation Plan, Review Focus, Task 1: JSON Logic new operators, Task 2: shapes compiler, Task 3: API + registry, Task 4: Authoring → tree (+2 more)

### Community 79 - "remap_batch"
Cohesion: 0.09
Nodes (29): audit(), lifespan(), Local single-process mode: tick the delivery scheduler every minute and start wh, Re-run held loans through the source's current mapping and rules (dry_run previe, replay(), resume_batch(), schedules_pull(), _start_local_scheduler() (+21 more)

### Community 101 - "canCap"
Cohesion: 0.09
Nodes (31): getPersona(), GROUP_LABEL, GROUP_ORDER, JobsPane(), Maintenance(), TemplateEditor(), TemplatesPane(), ACTION_LABEL (+23 more)

### Community 102 - "Demo kit: test data and a ready-to-run demo"
Cohesion: 0.25
Nodes (7): Demo kit: test data and a ready-to-run demo, How the test data is made, Personas (the "Signed in as" switcher, bottom left), Suggested run of show (about 25 minutes), The pre-loaded state, Two ways to demo, What is in the kit

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
Cohesion: 0.19
Nodes (14): ValueError, Rules the executor needs: active, plus canary and shadow candidates., RuleError, RuleRegistry, run_tests(), signature(), _draft(), test_default_rules_pass_clean_loan() (+6 more)

### Community 111 - "_vendor_call"
Cohesion: 0.33
Nodes (7): move_feed(), MoveFeed, _vendor_call(), VendorIn, vendors_create(), vendors_get(), vendors_update()

### Community 112 - "authorize"
Cohesion: 0.67
Nodes (3): inspect_field_draft(), Same, for an unsaved edit: test a transform chain before saving it., TraceReq

### Community 113 - "_safe_error"
Cohesion: 0.40
Nodes (5): create_rule(), edit_rule(), _materialize_rule(), Prefer tree → expression; keep legacy expression path., RuleBody

### Community 115 - "inspect_field_draft"
Cohesion: 0.67
Nodes (3): PolicyChange, Called by the Compliance approver; requested_by is the analyst who proposed the, update_policy()

### Community 116 - "update_policy"
Cohesion: 0.10
Nodes (34): load(), The feed's current published configuration, signature-verified., emit_metrics(), persist_stream(), prepare_large(), process_batch(), pull(), Entry points for the AWS Glue data plane (thin wrappers in aws/glue/ call these) (+26 more)

### Community 120 - "_sched_call"
Cohesion: 0.29
Nodes (8): deliveries_waive(), _sched_call(), ScheduleIn, schedules_approve(), schedules_create(), schedules_status(), schedules_update(), StatusIn

## Knowledge Gaps
- **193 isolated node(s):** `lbp`, `start_demo.sh script`, `__dirname`, `ROOT`, `SHOTS` (+188 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `remap_batch` to `SFTP File Pullers`, `Delivery Scheduling`, `FastAPI Route Mounts`, `Boarding Batch Pipeline`, `Demo Sample Generator`, `Mapping Override APIs`, `Signed Config Store`, `Cron Business Calendar`, `Preflight Mapping Checks`, `File Sequencing Gate`, `Rule Registry Store`, `Lambda Path Tests`, `Audit History APIs`, `Analytics Service`, `Builtin Rule Validators`, `Mapping Field Inspect`, `Rule Executor`, `Source Upload APIs`, `__init__.py`, `Preflight Override Path`, `update_policy`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Why does `get_engine()` connect `Analytics Service` to `AI Mapping Engine`, `Delivery Scheduling`, `FastAPI Route Mounts`, `Boarding Batch Pipeline`, `Local Scheduler Config`, `Signed Config Store`, `Cron Business Calendar`, `Vendor Feed Profiles`, `Preflight Mapping Checks`, `File Sequencing Gate`, `JSON Logic Rules`, `Rule Registry Store`, `Exception Policy`, `Exception Manager Core`, `Audit History APIs`, `Deliveries Schedule UI`, `Mapping Field Inspect`, `Change File Apply`, `Sources Mapping UI`, `Delivery Profile Logic`, `Rule Executor`, `__init__.py`, `Preflight Override Path`, `remap_batch`, `update_policy`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Why does `RuleRegistry` connect `wipe_data_dir` to `AI Mapping Engine`, `Security Load Tests`, `FastAPI Route Mounts`, `Boarding Batch Pipeline`, `Deliveries Schedule UI`, `Demo Sample Generator`, `Preflight Override Path`, `Signed Config Store`, `remap_batch`, `Rule Executor`, `Cron Business Calendar`, `Rules Exception APIs`, `update_policy`, `Rule Registry Store`, `Exception Policy`, `Exception Manager Core`, `Audit History APIs`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `get_settings()` (e.g. with `run()` and `test_wipe_data_dir_clears_presence()`) actually correct?**
  _`get_settings()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `run_batch()` (e.g. with `main()` and `test_end_to_end_via_api()`) actually correct?**
  _`run_batch()` has 23 INFERRED edges - model-reasoned connections that need verification._
- **What connects `lbp`, `start_demo.sh script`, `__dirname` to the rest of the system?**
  _193 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `AI Mapping Engine` be split into smaller, more focused modules?**
  _Cohesion score 0.14285714285714285 - nodes in this community are weakly interconnected._