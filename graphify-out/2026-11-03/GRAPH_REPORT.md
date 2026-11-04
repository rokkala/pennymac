# Graph Report - pennymac  (2026-11-03)

## Corpus Check
- 147 files · ~340,661 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1535 nodes · 3894 edges · 106 communities (93 shown, 13 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 232 edges (avg confidence: 0.73)
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
- JWT Auth Security
- Vendor Isolation Tests
- Routing Exception Tests
- Change Control Docs
- Backend Dependencies
- Docker Compose Stack
- Platform Architecture Docs
- OIDC Deploy Workflow
- Vendor CRUD APIs
- Transform Unit Tests
- Rule Lifecycle Tests
- Signed Glue Config Docs
- CI Workflow Jobs
- Load Test Evidence Docs
- API Auth Hardening
- Schedule CRUD APIs
- Concurrency Lease Tests
- Vendor Sequencing Docs
- Preflight Override Path
- SFTP Scheduler Docs
- React Error Boundary
- Glue Spark Feed Job
- Safe Error Messages
- Glue Feed Job
- Glue Vendor Pull Job
- Console Shell Docs
- Auth Privacy Docs
- Scoped Vendor API
- Backend Package Meta
- Demo kit: test data and a ready-to-run demo
- OpenSearchPrecedentIndex
- verify_audit_chain
- start_demo.sh
- compile_mapping
- progress.md

## God Nodes (most connected - your core abstractions)
1. `get_engine()` - 106 edges
2. `get_settings()` - 70 edges
3. `User` - 53 edges
4. `run_batch()` - 52 edges
5. `create_batch()` - 50 edges
6. `useApi()` - 47 edges
7. `fmt()` - 44 edges
8. `api()` - 43 edges
9. `RuleRegistry` - 41 edges
10. `audit()` - 41 edges

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

## Communities (106 total, 13 thin omitted)

### Community 0 - "AI Mapping Engine"
Cohesion: 0.14
Nodes (28): accept_all(), add_field(), approve(), _columns(), diff_versions(), get_mapping(), MappingError, memory_stats() (+20 more)

### Community 1 - "SFTP File Pullers"
Cohesion: 0.06
Nodes (35): allowed_hosts(), fetch_new(), LocalPuller, make_puller(), _ok_name(), Puller, PullError, Path (+27 more)

### Community 2 - "Delivery Scheduling"
Cohesion: 0.08
Nodes (65): _date(), display_sequence(), notify(), Operational alerts: always logged and audited; published to SNS when LBP_ALERT_T, CronError, _day_matches(), describe(), _field() (+57 more)

### Community 3 - "FastAPI Route Mounts"
Cohesion: 0.06
Nodes (35): a_ai(), a_ask(), a_dq(), a_exceptions(), a_exec(), a_import(), a_sources(), a_systemic() (+27 more)

### Community 4 - "Frontend Package Deps"
Cohesion: 0.06
Nodes (32): eslint, @eslint/js, eslint-plugin-react, eslint-plugin-react-hooks, dependencies, react, react-dom, devDependencies (+24 more)

### Community 5 - "Boarding Batch Pipeline"
Cohesion: 0.18
Nodes (15): _fails_of(), process_chunk(), Micro-batch boarding pipeline: parse -> map/transform -> validate -> triage -> l, Map + validate one micro-batch. With `incr` (incremental / snapshot loads) each, Compile mapping + rules once per worker process per (mapping version, rule set)., Authoritative change counts from the database (used where chunks run in parallel, _status_of(), summarize_changes() (+7 more)

### Community 6 - "Frontend Delivery UI"
Cohesion: 0.15
Nodes (30): setIntent(), CELL, cronFrom(), Deliveries(), DOW, HistoryStrip(), OPEN, presetOf() (+22 more)

### Community 7 - "Local Scheduler Config"
Cohesion: 0.16
Nodes (17): Re-run held loans through the source's current mapping and rules (dry_run previe, replay(), schedules_pull(), _apply_ssm(), db_secret(), get_settings(), Runtime configuration. Every setting can be overridden with an LBP_* environment, RDS-managed secret {username, password}. Cached briefly; refreshed after rotatio (+9 more)

### Community 8 - "Field Transforms"
Cohesion: 0.06
Nodes (41): fix_fico(), fix_investor_gnma(), fix_loan_number(), fix_maturity(), fix_occupancy(), fix_rate(), fix_servicing_fee(), fix_state() (+33 more)

### Community 9 - "Demo Sample Generator"
Cohesion: 0.18
Nodes (16): canonical_loans(), generate_all(), _inject_defect(), _loan(), Path, Synthetic loan file generator for the four PennyMac boarding sources.  Every sou, Canonical (SSE-shaped) loan; each source writer renames/reformats it., write_bulk_excel() (+8 more)

### Community 10 - "CLI Worker DB"
Cohesion: 0.18
Nodes (16): _alembic_cfg(), check_config(), _demo_setup(), main(), migrate(), Operator commands.      python -m lbp.cli migrate          apply database migrat, publish_all(), Republish every live feed (rule or policy changes affect all of them). (+8 more)

### Community 11 - "Governance Rules UI"
Cohesion: 0.09
Nodes (27): AuditModal(), DemoSetupModal(), EDITABLE, PolicyModal(), ROWS, ACTION_LABEL, AuthorModal(), EXAMPLES (+19 more)

### Community 12 - "Exception Decision APIs"
Cohesion: 0.09
Nodes (40): accept_all(), add_mapping_field(), ai_suggest(), approve_delivery(), approve_mapping(), batch_apply_ooo(), batch_discard(), batch_skip_gap() (+32 more)

### Community 13 - "Mapping Override APIs"
Cohesion: 0.07
Nodes (30): create_rule(), DeliveryProfileIn, demo_setup(), DemoSetupIn, FieldAction, inspect_field_draft(), Override, override_preflight() (+22 more)

### Community 14 - "Signed Config Store"
Cohesion: 0.17
Nodes (22): _bucket(), build(), bundle_json(), _canonical(), ConfigError, FeedConfig, _key(), load() (+14 more)

### Community 15 - "Cron Business Calendar"
Cohesion: 0.08
Nodes (30): Used by tests after changing environment variables., reset_settings(), _build_scenario(), data_is_present(), DemoSetupConflict, Any, Exception, Path (+22 more)

### Community 16 - "Analytics Charts UI"
Cohesion: 0.17
Nodes (27): scoped(), HBars(), heatColor(), Lines(), niceMax(), Segments(), Sparkline(), Tip() (+19 more)

### Community 17 - "Rules Exception APIs"
Cohesion: 0.16
Nodes (20): get_delivery(), How a file named like this would be treated: load type, file-level action, seque, test_filename(), incremental_context(), Per-batch context for change files (from the published feed configuration): effe, decide_profile(), DeliveryError, extract_sequence() (+12 more)

### Community 18 - "Vendor Feed Profiles"
Cohesion: 0.24
Nodes (16): _clean(), create_vendor(), ensure_vendor(), get_vendor(), list_vendors(), move_feed(), ValueError, Vendors: the counterparty that owns one or more feeds.      Vendor (Cornerstone (+8 more)

### Community 19 - "Preflight Mapping Checks"
Cohesion: 0.18
Nodes (17): ParseOptions, read_sample(), profile_rows(), preview(), Validation preview: run the draft mapping + live rules over the sample before an, _active_fields(), check_file(), _critical() (+9 more)

### Community 20 - "File Sequencing Gate"
Cohesion: 0.14
Nodes (27): prepare_large(), Driver step 1: config, lease and pre-flight. Returns (cfg, batch) or (None, stat, next_integer(), purge_staging_npi(), Data minimisation for staging (GLBA safeguards).  Once a loan is boarded (or the, acquire(), advance(), apply_out_of_order() (+19 more)

### Community 21 - "JSON Logic Rules"
Cohesion: 0.15
Nodes (20): Shadow-style impact estimate: how many recently staged loans would this version, rule_impact(), apply(), _cmp(), compile_logic(), _get(), JsonLogicError, _loose_eq() (+12 more)

### Community 22 - "Rule Registry Store"
Cohesion: 0.11
Nodes (7): DynamoRuleStore, r"""Versioned, signed Rule Registry with HITL lifecycle gates.      draft -> in_, AWS backend. Table: pk rule_id (S), sk version (N), GSI 'status-index' on status, RuleStore, SqlRuleStore, _undecimal(), Protocol

### Community 23 - "Vendors Imports UI"
Cohesion: 0.19
Nodes (21): _apply_memory(), _detect_composites(), name_similarity(), normalize(), AI-assisted source-to-target mapping with confidence scoring.  Scoring combines, Reuse only the portable part of a remembered transform: its value translations., Run every proposed transform on the sample; demote suggestions that fail on real, Re-rank candidates with what humans approved/rejected for this column name befor (+13 more)

### Community 24 - "Exception Batch Compare"
Cohesion: 0.12
Nodes (29): Pure (no DB writes) triage used inside the pipeline workers' parent process., Triage, emit_metrics(), persist_stream(), process_batch(), pull(), Entry points for the AWS Glue data plane (thin wrappers in aws/glue/ call these), Driver step 3: persist processed rows (ordered by row number) in micro-batches w (+21 more)

### Community 25 - "Exception Policy"
Cohesion: 0.26
Nodes (12): read_policy(), effective_policy(), get_policy(), PolicyError, ValueError, Confidence x Risk routing policy (the hard gate).  Thresholds live in the Policy, Live override rate of AI auto-applied fixes (rollbacks + failed QA samples / T1, Configured policy plus automatic controls: T1 is suspended when its override rat (+4 more)

### Community 26 - "Exception Manager Core"
Cohesion: 0.24
Nodes (9): _coerce(), ExceptionActionError, ExceptionManager, ValueError, Compliance has investigated outside EM (e.g. OFAC false positive) and records th, Undo a T1 auto-apply inside the rollback window (target < 5 min to execute)., On-demand LLM suggestion with masked context; stored as proposal, never auto-app, Cast a reviewer-entered string into the SSE type for re-validation. (+1 more)

### Community 27 - "API Enhancement Tests"
Cohesion: 0.15
Nodes (20): BatchBusyError, _chunks(), Exception, RuntimeError, In-process runner (local API mode): run the batch, then any files it released fr, Error text for storage/UI: first line only, never the SQL parameters (they can c, _run_and_follow(), run_batch() (+12 more)

### Community 28 - "Lambda Path Tests"
Cohesion: 0.11
Nodes (28): current_principal(), _jwks_client(), Principal, principal_from_claims(), Authentication and role-based authorization.  Modes (LBP_AUTH_MODE):   dev  - id, FastAPI dependency: the caller must hold one of `roles` (admin always passes)., require(), verify_token() (+20 more)

### Community 29 - "File Format Parser"
Cohesion: 0.26
Nodes (13): _clean_header(), detect_format(), estimate_rows(), _iter_excel(), iter_rows(), ParsedFile, Path, Config-driven source file parsing (CSV / TXT / Excel) with format auto-detection (+5 more)

### Community 30 - "Frontend Mock API"
Cohesion: 0.17
Nodes (15): ApiError, clone(), createMockApi(), fail(), LIFECYCLE, now(), uid(), err() (+7 more)

### Community 31 - "Audit History APIs"
Cohesion: 0.10
Nodes (27): audit(), batch_changes(), batch_loans(), batch_snapshot_reviews(), feed_config(), get_batch(), get_source(), lifespan() (+19 more)

### Community 32 - "Security Load Tests"
Cohesion: 0.15
Nodes (11): main(), Throughput test: generate N loans, onboard the source, board through the full pi, _client(), RDS-managed secret is read per connection; Cognito client id comes from SSM (as, _rsa(), test_jwt_mode(), test_npi_never_in_error_messages_and_retention(), test_production_refuses_unsafe_config() (+3 more)

### Community 33 - "Analytics Service"
Cohesion: 0.24
Nodes (14): ai_mapping_insights(), dq_scorecard(), exception_analytics(), executive_summary(), import_status(), _iso(), _label(), _names() (+6 more)

### Community 34 - "Builtin Rule Validators"
Cohesion: 0.27
Nodes (8): _get_bucket(), load_records(), SSE target loader: micro-batched, throttled upserts into the typed SSE loan tabl, Upsert [(sse_record, dq_status)] by loan_number. Returns rows written.      With, Insert, or replace a whole record (a full tape re-boarding an existing loan afte, to_sse_row(), TokenBucket, _write()

### Community 35 - "Frontend Auth Personas"
Cohesion: 0.23
Nodes (15): getPersona(), getVendorScope(), PERSONAS, setPersona(), setSignedIn(), setVendorScope(), takeIntent(), vendorScope (+7 more)

### Community 36 - "AWS Lambda Handlers"
Cohesion: 0.15
Nodes (11): _api(), finalize_batch(), on_file_arrival(), AWS Lambda entry points: the thin control plane around the Glue data plane.  Lam, EventBridge Scheduler (rate 5 minutes): delivery windows and late/missed alerts., API Gateway (HTTP API, payload v2) -> FastAPI. The bearer token is passed throug, EventBridge 'Object Created' on the raw bucket, prefix incoming/<feed_id>/., Choose the Glue job. Spark only pays off for very large full tapes in a splittab (+3 more)

### Community 37 - "Incremental Load Tests"
Cohesion: 0.46
Nodes (14): _boarded_pcg(), _pick(), Incremental / snapshot loads, change control and per-vendor sequencing (end to e, A reviewer corrected a value at boarding; the vendor's next snapshot re-sends th, _run(), _set_profile(), _sse(), test_incremental_sparse_updates_closes_and_change_control() (+6 more)

### Community 38 - "Deliveries Schedule UI"
Cohesion: 0.29
Nodes (6): _a(), attributes_for(), SSE (Loan Servicing System) target schema: ~100 attributes across 5 modules.  Ea, Self-consistency of the target dictionary (run at import and in CI)., risk_of(), validate_schema()

### Community 39 - "Mapping Field Inspect"
Cohesion: 0.50
Nodes (4): field_values_edit(), get_mapping(), Preview (save=false) or save (save=true) a source-specific value map for this fi, ValuesReq

### Community 40 - "Change File Apply"
Cohesion: 0.19
Nodes (14): Exception Manager: AI proposes, human disposes.  Resolution pipeline per failing, Attach the live SSE records of the loans in this chunk (fetched just before the, with_current(), apply_closes(), apply_updates(), conflict_failures(), current_rows(), masked_changes() (+6 more)

### Community 42 - "Exception RAG Retrieval"
Cohesion: 0.27
Nodes (10): route(), _batch(), test_bulk_resolve(), test_pause_and_resume_from_checkpoint(), test_pipeline_reconciles(), test_routing_matrix(), test_t2_resolution_boards_loan(), test_t4_maker_checker() (+2 more)

### Community 43 - "PII Profiling"
Cohesion: 0.24
Nodes (11): detect_column_pii(), _norm(), PII detection and dynamic masking.  Two signals are combined: column-name semant, ColumnProfile, infer_type(), profile_column(), Source data profiling: per-column type inference, completeness, cardinality, pat, Collapse a value into a pattern like 'AAA9999' for pattern profiling. (+3 more)

### Community 44 - "Delivery Profile Logic"
Cohesion: 0.22
Nodes (8): FeedConfigChip(), LT, STATUS_HELP, VENDOR_TYPES, VendorDeliveries(), VendorExceptions(), VendorFiles(), VendorModal()

### Community 45 - "Rule Authoring LLM"
Cohesion: 0.24
Nodes (10): _base_with(), draft_from_text(), _heuristic(), LLM-assisted rule authoring: SME types English -> JSON Logic DSL + test cases., Returns {"draft": rule body | None, "source": "llm"|"heuristic", "test_results":, resolve_field(), _sample_value(), _r() (+2 more)

### Community 46 - "Rule Executor"
Cohesion: 0.29
Nodes (5): _bucket(), Evaluation, Stateless rule executor (runs in-process, in worker processes, on Lambda or ECS, RuleExecutor, RuleResult

### Community 47 - "Rule Registry Lifecycle"
Cohesion: 0.23
Nodes (12): ValueError, RuleError, RuleRegistry, run_tests(), signature(), _draft(), test_default_rules_pass_clean_loan(), test_failing_tests_block_review() (+4 more)

### Community 48 - "Frontend Cognito Auth"
Cohesion: 0.35
Nodes (11): b64url(), bearer(), decode(), initAuth(), load(), login(), logout(), randomString() (+3 more)

### Community 49 - "Glue Job Entry Points"
Cohesion: 0.11
Nodes (17): 1. Stack and tooling, 2. Design tokens, 3. Shell, 4. Shared primitives migration, 5. In-scope pages, 6. Data flow and boundaries, 7. Error handling and a11y, 8. Testing and verification (+9 more)

### Community 50 - "Local S3 Storage"
Cohesion: 0.27
Nodes (10): is_s3(), local_path(), persist_upload(), Path, File storage: local paths in development, S3 in AWS (ECS task disks are ephemera, Store an uploaded file durably and return its URI (S3 in AWS, the local path oth, _s3(), _split() (+2 more)

### Community 51 - "Glue Job Tests"
Cohesion: 0.15
Nodes (16): create_batch(), DuplicateFileError, file_sha256(), override_preflight(), Path, ValueError, Register an arriving file. With strict=False (unattended S3/scheduler arrivals), An SME/Compliance user accepts the drift risk and lets a blocked batch run on th (+8 more)

### Community 52 - "Incremental Row Planner"
Cohesion: 0.12
Nodes (16): 1. Kit layout, 2. Shared module: `backend/lbp/demo_setup.py`, 3. API, 4. CLI and `start_demo.sh`, 5. UI, 6. Security and production, 7. Testing, 8. Docs (+8 more)

### Community 53 - "SSE Target Loader"
Cohesion: 0.29
Nodes (10): is_protected_change(), norm(), Comparable form of a field value (mapped record vs. typed SSE row)., _fail(), plan_row(), Incremental and snapshot row planning (pure; runs inside the pipeline worker pro, (action, code) where action is None for an unrecognised code., Decide the row's action and build the record to validate. Returns     {action, r (+2 more)

### Community 54 - "Exceptions Console UI"
Cohesion: 0.16
Nodes (16): admin, lee, maria, ACTION_LABEL, CHANGE_RULES, ChangeControl(), ExceptionModal(), KEY_FIELDS (+8 more)

### Community 55 - "Source Upload APIs"
Cohesion: 0.25
Nodes (11): ai_map(), create_source(), presign(), Path, Stream an upload to disk with size, extension and content-type checks (no execut, Add a feed (a file layout from a vendor) from a sample file; the AI drafts its m, AWS: browser PUTs straight to the raw S3 zone; EventBridge starts the Step Funct, _save_upload() (+3 more)

### Community 56 - "JWT Auth Security"
Cohesion: 0.26
Nodes (13): mapping_dq_rules(), describe_step(), field_inspect(), _load(), mapping_dq(), Field-level inspection for the Mapping UI.  For one SSE target attribute in a ma, Every rule in the registry against this mapping's sample: fail counts and field, Every distinct source value for a field, what it becomes in SSE and whether that (+5 more)

### Community 57 - "Vendor Isolation Tests"
Cohesion: 0.36
Nodes (7): _feed(), _incremental(), Vendors own feeds; operations are scoped and protected at vendor level., _sse(), test_change_file_cannot_touch_another_vendors_loans(), test_snapshot_compares_the_vendors_whole_portfolio(), test_vendor_crud_roles_and_rollups()

### Community 58 - "Routing Exception Tests"
Cohesion: 0.15
Nodes (11): AnthropicClient, BedrockClient, get_llm(), LLMClient, LLMMappingReranker, Pluggable LLM access used by mapping re-ranking, rule authoring (English -> DSL), Asks the model to choose among the heuristic top-K for each column., load_memory() (+3 more)

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
Cohesion: 0.33
Nodes (7): move_feed(), MoveFeed, _vendor_call(), VendorIn, vendors_create(), vendors_get(), vendors_update()

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
Cohesion: 0.40
Nodes (6): _sched_call(), ScheduleIn, schedules_create(), schedules_status(), schedules_update(), StatusIn

### Community 73 - "Vendor Sequencing Docs"
Cohesion: 0.33
Nodes (6): CHG06 Cross-Vendor Loan Change, Per-Vendor File Sequencing Gate, Vendor, SSE Target Schema, Pipe-Delimited Sub-Servicing Columns, Sub-Servicing Sample Loan Tape

### Community 74 - "Preflight Override Path"
Cohesion: 0.16
Nodes (24): api(), mockApi(), Ask(), ACTION_TXT, changedKeys(), clone(), DeliveryProfile(), EditModal() (+16 more)

### Community 75 - "SFTP Scheduler Docs"
Cohesion: 0.50
Nodes (5): paramiko SFTP Dependency, Glue Job lbp-vendor-pull, Delivery Scheduler, Scheduler Tick, SFTP Pull Connector with Host-Key Pinning

### Community 79 - "Safe Error Messages"
Cohesion: 0.24
Nodes (5): Field-by-field comparison of an incoming duplicate with the loan already in SSE., Apply resolved values, re-validate, board to SSE when no blocking exceptions rem, mask_record(), mask_value(), partial: keep last 4 (SSN/phone) or first letter (name); hash: deterministic tok

### Community 102 - "Demo kit: test data and a ready-to-run demo"
Cohesion: 0.25
Nodes (7): Demo kit: test data and a ready-to-run demo, How the test data is made, Personas (the "Signed in as" switcher, bottom left), Suggested run of show (about 25 minutes), The pre-loaded state, Two ways to demo, What is in the kit

### Community 103 - "OpenSearchPrecedentIndex"
Cohesion: 0.15
Nodes (7): consensus(), get_index(), OpenSearchPrecedentIndex, Precedent retrieval (the 'R' in RAG) over historically resolved exceptions.  Loc, If exact-match precedents agree, return (value, strength)., _shape(), SqlPrecedentIndex

### Community 104 - "verify_audit_chain"
Cohesion: 0.13
Nodes (14): File structure, Frontend UI Design System (Phase 1) Implementation Plan, Global Constraints, Review Focus, Self-review notes (author), Task 1: Tailwind scaffold + `cn` + token bridge, Task 2: shadcn primitives + `ui.jsx` façade (Panel, Kpis, Status, Button classes, Toast), Task 3: Shell rewrite (`App.jsx`) (+6 more)

### Community 111 - "compile_mapping"
Cohesion: 0.20
Nodes (10): migrate(), Invoked once per deploy: Alembic migrations, default rule seed, and a signed con, partition_processor(), What each Spark partition runs: the same mapping + rule code as every other path, compile_mapping(), Return a fast row -> (record, errors) function for the active fields of a mappin, Alembic environment: schema is defined in lbp.store.db.metadata; URL from LBP se, run() (+2 more)

## Knowledge Gaps
- **131 isolated node(s):** `lbp`, `start_demo.sh script`, `name`, `private`, `version` (+126 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_settings()` connect `Local Scheduler Config` to `SFTP File Pullers`, `Delivery Scheduling`, `FastAPI Route Mounts`, `Boarding Batch Pipeline`, `CLI Worker DB`, `Exception Decision APIs`, `Mapping Override APIs`, `Signed Config Store`, `Cron Business Calendar`, `File Sequencing Gate`, `Rule Registry Store`, `Exception Batch Compare`, `API Enhancement Tests`, `Lambda Path Tests`, `Audit History APIs`, `Builtin Rule Validators`, `Local S3 Storage`, `Glue Job Tests`, `Source Upload APIs`, `Routing Exception Tests`, `compile_mapping`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Why does `create_batch()` connect `Glue Job Tests` to `SFTP File Pullers`, `Delivery Scheduling`, `Boarding Batch Pipeline`, `Cron Business Calendar`, `Rules Exception APIs`, `Preflight Mapping Checks`, `File Sequencing Gate`, `Exception Batch Compare`, `API Enhancement Tests`, `Lambda Path Tests`, `File Format Parser`, `Audit History APIs`, `Security Load Tests`, `AWS Lambda Handlers`, `Incremental Load Tests`, `Sources Mapping UI`, `Exception RAG Retrieval`, `Local S3 Storage`, `Vendor Isolation Tests`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Why does `get_engine()` connect `Audit History APIs` to `AI Mapping Engine`, `Delivery Scheduling`, `FastAPI Route Mounts`, `Local Scheduler Config`, `CLI Worker DB`, `Mapping Override APIs`, `Signed Config Store`, `Cron Business Calendar`, `Rules Exception APIs`, `Vendor Feed Profiles`, `Preflight Mapping Checks`, `File Sequencing Gate`, `JSON Logic Rules`, `Exception Batch Compare`, `Exception Policy`, `API Enhancement Tests`, `Analytics Service`, `Change File Apply`, `Glue Job Tests`, `JWT Auth Security`, `Routing Exception Tests`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `get_settings()` (e.g. with `run()` and `test_wipe_data_dir_clears_presence()`) actually correct?**
  _`get_settings()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `run_batch()` (e.g. with `main()` and `test_end_to_end_via_api()`) actually correct?**
  _`run_batch()` has 23 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `create_batch()` (e.g. with `on_file_arrival()` and `main()`) actually correct?**
  _`create_batch()` has 27 INFERRED edges - model-reasoned connections that need verification._
- **What connects `lbp`, `start_demo.sh script`, `name` to the rest of the system?**
  _131 weakly-connected nodes found - possible documentation gaps or missing edges._