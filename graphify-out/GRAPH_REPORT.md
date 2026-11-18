# Graph Report - pennymac  (2026-11-18)

## Corpus Check
- 305 files · ~1,519,463 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 102 file(s) not represented in the graph (top: .csv 83, .pptx 7, (none) 2)
- WARNING: 102 of 450 files seen (23%) have no supported extractor and are missing from this graph entirely. It may look complete while representing only part of the codebase.

## Summary
- 3523 nodes · 11422 edges · 149 communities (124 shown, 25 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 845 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `522b11e9`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- FeedLayout.jsx
- test_feed_lifecycle.py
- Delivery Scheduling
- get
- Frontend Package Deps
- batch.py
- Frontend Delivery UI
- Local Scheduler Config
- Field Transforms
- loader.py
- CLI Worker DB
- ui.jsx
- loadDesk.js
- main.py
- json
- glue_jobs.py
- Exceptions.jsx
- ParseOptions
- Vendor Feed Profiles
- Preflight Mapping Checks
- test_multifile_fileset.py
- JSON Logic Rules
- Rule Registry Store
- Vendors Imports UI
- pullers.py
- compile_tree
- audit
- API Enhancement Tests
- Lambda Path Tests
- pathlib
- Frontend Mock API
- test_multifile_onboard.py
- canCap
- Analytics Service
- fileset.py
- api.js
- handlers.py
- lbp/demo_setup.py
- profile_of
- Mapping Field Inspect
- test_join_scale.py
- persist_bulk
- joiner.py
- OpenSearchPrecedentIndex
- test_multifile_intake.py
- Rule Authoring LLM
- create_batch
- Rule Registry Lifecycle
- Frontend Cognito Auth
- Glue Job Entry Points
- Task 1: DB-free persist writes clean + dirty parts (no Postgres COPY)
- get_settings
- Design
- PageHeader
- default_rules.py
- persist_stream
- test_multifile_run.py
- Imports.jsx
- pytest
- Change Control Docs
- Backend Dependencies
- Docker Compose Stack
- Platform Architecture Docs
- GitHub OIDC Deploy Credential Hygiene
- get_engine
- run_demo_setup
- join_files
- Signed Glue Config Docs
- validate_layout
- Load Test Evidence Docs
- create_multifile_feed
- Schedule CRUD APIs
- Multi-file feeds: master/detail file sets, joins and child records
- Vendor Sequencing Docs
- compile_tree
- SFTP Scheduler Docs
- import_status
- demo_setup
- sweep_sets
- sqlalchemy
- time
- f
- normalize_part
- test_lifecycle_and_onboarding_e2e.py
- ETL Monitor Implementation Plan
- LayoutError
- Console Shell Docs
- Auth Privacy Docs
- test_join_aggregate.py
- tick
- api
- test_multifile_preview.py
- _batches
- ai.py
- _join
- test_sftp_pull.py
- Backend Package Meta
- canCap
- LBP PoC — AWS deployments inventory
- File map
- Frontend UI Design System (Phase 1) Implementation Plan
- run_demo_setup
- start_demo.sh
- conftest.py
- wipe_data_dir
- template_store.py
- DuplicateFileError
- fingerprint
- conftest.py
- test_glue_jobs.py
- onboard.py
- User
- stage.py
- Demo Kit In-App Implementation Plan
- authoring.py
- security.py
- MergeMode
- _like_escape
- feed_layout
- Spark / Load Job Split Implementation Plan
- tmproot
- DuplicateFileError
- get_settings
- ETL Monitor (fleet ops console)
- join_files
- attach_file
- test_stage_timing.py
- finalize_bulk
- Monitor.jsx
- Signed Feed Configuration
- test_exception_loads.py
- profile_rows
- file_action
- 05_atlas_bulk_99145794.md
- DuplicateFileError
- local_path
- run_batch
- atlas_bulk_202611_5755a18d.md
- atlas_bulk_202611_e190a147.md
- bulk_acquisition_sample_077e3920.md
- bulk_acquisition_sample_be797c55.md
- bulk_acquisition_sample_d78ab9e8.md
- progress.md

## God Nodes (most connected - your core abstractions)
1. `get_engine()` - 344 edges
2. `get_settings()` - 116 edges
3. `run_batch()` - 112 edges
4. `create_batch()` - 102 edges
5. `audit()` - 90 edges
6. `User` - 79 edges
7. `now()` - 79 edges
8. `canCap()` - 69 edges
9. `api()` - 67 edges
10. `useApi()` - 66 edges

## Surprising Connections (you probably didn't know these)
- `Two ways to demo` --references--> `demo_setup()`  [INFERRED]
  demo_kit/DEMO_GUIDE.md → backend/lbp/api/main.py
- `Review Focus` --references--> `_persist_chunk()`  [INFERRED]
  docs/superpowers/plans/2026-11-07-bulk-persist-full-tapes.md → backend/lbp/pipeline/batch.py
- `Flag` --references--> `_persist_chunk()`  [INFERRED]
  docs/superpowers/plans/2026-11-08-bulk-file-load-dirty.md → backend/lbp/pipeline/batch.py
- `Review Focus` --references--> `_persist_chunk()`  [INFERRED]
  docs/superpowers/plans/2026-11-08-spark-load-split.md → backend/lbp/pipeline/batch.py
- `Design` --references--> `_persist_chunk()`  [INFERRED]
  docs/superpowers/specs/2026-11-07-bulk-persist-full-tapes-design.md → backend/lbp/pipeline/batch.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Incremental Change Exception Rules** — docs_incremental_and_scheduling_chg01, docs_incremental_and_scheduling_chg05, docs_incremental_and_scheduling_chg06, docs_incremental_and_scheduling_load_type_incremental [EXTRACTED 1.00]
- **Glue Data-Plane Job Trio** — docs_architecture_lbp_feed, docs_architecture_lbp_feed_spark, docs_architecture_lbp_vendor_pull [EXTRACTED 1.00]

## Communities (149 total, 25 thin omitted)

### Community 0 - "FeedLayout.jsx"
Cohesion: 0.08
Nodes (66): Review Focus, Task 4: Multi-file onboarding UI, Task 5: Docs, demo and end-to-end check, createMultiFileFeed(), inspectMultiFiles(), previewMultiFiles(), roleForm(), addDetail() (+58 more)

### Community 1 - "test_feed_lifecycle.py"
Cohesion: 0.11
Nodes (60): archive_feed(), delete_feed(), discard_mapping(), FeedArchivedError, LifecycleError, _lock_feed(), _need(), _public() (+52 more)

### Community 2 - "Delivery Scheduling"
Cohesion: 0.13
Nodes (29): schedule(), pull(), describe(), local_label(), create_schedule(), decide(), effective(), get_schedule() (+21 more)

### Community 3 - "get"
Cohesion: 0.05
Nodes (40): a_ai(), a_dq(), a_exceptions(), a_exec(), a_import(), a_sources(), a_systemic(), analytics_vendors() (+32 more)

### Community 4 - "Frontend Package Deps"
Cohesion: 0.08
Nodes (33): dependencies, react@18.3.1, react-dom@18.3.1, devDependencies, eslint@^9.17.0, @eslint/js@^9.17.0, eslint-plugin-react@^7.37.2, eslint-plugin-react-hooks@^5.1.0 (+25 more)

### Community 5 - "batch.py"
Cohesion: 0.05
Nodes (42): batch_snapshot_reviews(), read_policy(), _str(), Triage, effective_policy(), get_policy(), PolicyError, route() (+34 more)

### Community 6 - "Frontend Delivery UI"
Cohesion: 0.12
Nodes (18): _apply_memory(), _detect_composites(), name_similarity(), normalize(), score_pair(), _self_check(), suggest_mappings(), suggest_transform() (+10 more)

### Community 7 - "Local Scheduler Config"
Cohesion: 0.11
Nodes (17): 10. Risks, 1. Information architecture, 3. Overview — dual audience home, 4. Page-by-page intent (full rebuild checklist), 5. Interaction rules (product-wide), 6. Data flow and optional API, 7. Accessibility and errors, 8. Testing and verification (+9 more)

### Community 8 - "Field Transforms"
Cohesion: 0.09
Nodes (27): apply_field(), compile_mapping(), run(), _date(), _empty(), _num(), _op_cents_to_dollars(), _op_concat() (+19 more)

### Community 9 - "loader.py"
Cohesion: 0.06
Nodes (23): batch_loans(), mask_record(), mask_value(), submit_next(), with_current(), apply_closes(), apply_updates(), conflict_failures() (+15 more)

### Community 10 - "CLI Worker DB"
Cohesion: 0.09
Nodes (28): mapping_dq_rules(), describe_step(), field_inspect(), _load(), mapping_dq(), _runtime_rules(), _schema_checks(), _trace_row() (+20 more)

### Community 11 - "ui.jsx"
Cohesion: 0.09
Nodes (24): File structure, Task 1: Tailwind scaffold + `cn` + token bridge, Task 2: shadcn primitives + `ui.jsx` façade (Panel, Kpis, Status, Button classes, Toast), Task 3: Shell rewrite (`App.jsx`), Task 4: Modal restyle (behaviour-preserving), Task 6: Imports presentation pass, Task 7: Exceptions presentation pass, Task 9: Legacy CSS trim + docs + graphify (+16 more)

### Community 12 - "loadDesk.js"
Cohesion: 0.16
Nodes (16): File map, Overview load desk Implementation Plan, Tasks, BATCH_ATTENTION, BATCH_SEV, buildAttentionRows(), buildLoadHealth(), calendarDay() (+8 more)

### Community 13 - "main.py"
Cohesion: 0.05
Nodes (60): a_ask(), Ask, author_rule(), AuthorReq, Bulk, bulk_resolve(), compose_rule(), ComposeReq (+52 more)

### Community 14 - "json"
Cohesion: 0.16
Nodes (24): _bucket(), build(), bundle_json(), _canonical(), ConfigError, FeedConfig, _key(), load() (+16 more)

### Community 15 - "glue_jobs.py"
Cohesion: 0.09
Nodes (28): _apply_clean_sse_batch(), _copy_clean_adds(), _csv_cell(), _dup_hold_row(), _ensure_dirty_part(), _ensure_kind_part(), _list_dirty_part_names(), _load_clean_csv_part() (+20 more)

### Community 16 - "Exceptions.jsx"
Cohesion: 0.08
Nodes (40): File map, Task 1: Hash helpers, Task 2: Nav model, Task 3: Work-today cards, Task 4: Layout primitives + CSS, Task 5: Grouped shell in App.jsx, Task 6: Overview dual home, Task 7: How it works deep links (+32 more)

### Community 17 - "ParseOptions"
Cohesion: 0.08
Nodes (28): _clean_header(), detect_format(), estimate_rows(), _iter_excel(), fmt_cell(), gen(), ParsedFile, read_bytes_sample() (+20 more)

### Community 18 - "Vendor Feed Profiles"
Cohesion: 0.09
Nodes (26): get_delivery(), list_sources(), test_filename(), incremental_context(), _lock_source(), _register_batch(), display_sequence(), extract_sequence() (+18 more)

### Community 19 - "Preflight Mapping Checks"
Cohesion: 0.07
Nodes (23): lifespan(), publish_all(), DynamoRuleStore, RuleError, RuleRegistry, RuleStore, signature(), _undecimal() (+15 more)

### Community 20 - "test_multifile_fileset.py"
Cohesion: 0.10
Nodes (24): expire_sets(), pairing_key(), route_file(), _alerts(), _attach(), _configure(), _consumed_meanwhile(), _fail_arrival_for() (+16 more)

### Community 21 - "JSON Logic Rules"
Cohesion: 0.20
Nodes (15): CronError, _day_matches(), _field(), val(), is_business_day(), _last_weekday(), next_after(), next_business_day() (+7 more)

### Community 22 - "Rule Registry Store"
Cohesion: 0.10
Nodes (64): Task 6: Frontend — Load demo scenario modal, Task 8: Vendors & Mapping presentation pass, Task 2: Feed lifecycle UI, api(), archiveFeed(), deleteFeed(), discardMapping(), restoreFeed() (+56 more)

### Community 23 - "Vendors Imports UI"
Cohesion: 0.12
Nodes (18): buildHtml(), capture(), __dirname, esc(), filesTable(), flowExecute(), flowHighLevel(), flowMonitor() (+10 more)

### Community 24 - "pullers.py"
Cohesion: 0.10
Nodes (14): allowed_hosts(), fetch_new(), LocalPuller, make_puller(), _ok_name(), Puller, PullError, RemoteFile (+6 more)

### Community 25 - "compile_tree"
Cohesion: 0.11
Nodes (30): test_rule(), apply(), validate(), _base_with(), catalog(), _compile_node(), compile_tree(), decompile() (+22 more)

### Community 26 - "audit"
Cohesion: 0.11
Nodes (22): _coerce(), ExceptionActionError, ExceptionManager, _is_join(), audit(), test_resent_tape_is_flagged_not_overwritten(), _insert(), joins() (+14 more)

### Community 27 - "API Enhancement Tests"
Cohesion: 0.13
Nodes (20): maintenance_artifact(), maintenance_artifacts(), get_artifact(), list_artifacts(), MaintenanceError, _notebook_cells(), _repo_root(), _resolve() (+12 more)

### Community 28 - "Lambda Path Tests"
Cohesion: 0.10
Nodes (20): _aws(), _executions(), _load(), test_api_lambda_handler_requires_auth(), test_api_uploads_dispatch_to_step_functions_not_inline(), test_file_arrival_starts_pipeline_once(), test_glue_runs_emit_pipeline_metrics(), test_mark_failed_does_not_kill_running_batch() (+12 more)

### Community 29 - "pathlib"
Cohesion: 0.14
Nodes (13): _alembic_cfg(), check_config(), _demo_setup(), main(), migrate(), reset_settings(), reset_engine(), main() (+5 more)

### Community 30 - "Frontend Mock API"
Cohesion: 0.07
Nodes (33): ATTN, filterBatches(), RUNNING, ARTIFACTS, cellsOf(), getMaintenanceArtifact(), listMaintenanceArtifacts(), ApiError (+25 more)

### Community 31 - "test_multifile_onboard.py"
Cohesion: 0.13
Nodes (46): OnboardError, master_detail_layout(), master_detail_readiness(), _counts(), _files(), _layout_txt(), _mapping(), _merge_case() (+38 more)

### Community 32 - "canCap"
Cohesion: 0.13
Nodes (33): admin, compliance, monitoring, monReview, archived(), archivedLine(), canArchive(), canDelete() (+25 more)

### Community 33 - "Analytics Service"
Cohesion: 0.26
Nodes (9): ai_mapping_insights(), ask(), dq_scorecard(), exception_analytics(), executive_summary(), _label(), _names(), source_performance() (+1 more)

### Community 34 - "fileset.py"
Cohesion: 0.14
Nodes (19): _accept_or_discard(), _captures(), _config(), create_batch_for_set(), _evaluate(), evaluate_set(), _expire_one(), FileSetError (+11 more)

### Community 35 - "api.js"
Cohesion: 0.08
Nodes (34): 7. Error handling and a11y, decideLayout(), DEMO, EXT_TYPE, FALLBACK_CAST, getLayout(), getVendorScope(), listFileSets() (+26 more)

### Community 36 - "handlers.py"
Cohesion: 0.13
Nodes (10): api(), _api(), demo_setup(), finalize_batch(), mark_failed(), migrate(), route_batch(), scheduler_tick() (+2 more)

### Community 37 - "lbp/demo_setup.py"
Cohesion: 0.13
Nodes (23): _build_master_detail_feed(), decide_layout(), known_columns(), LayoutPublishError, LayoutServiceError, propose_layout(), _roles(), _audit_actions() (+15 more)

### Community 38 - "profile_of"
Cohesion: 0.11
Nodes (20): vendors_list(), _build_scenario(), rewrite(), _clean(), create_vendor(), ensure_vendor(), get_vendor(), list_vendors() (+12 more)

### Community 39 - "Mapping Field Inspect"
Cohesion: 0.06
Nodes (57): list_notifications(), create(), _directory(), list_for(), notify_many(), on_rule_transition(), peer_user_ids(), unread_count() (+49 more)

### Community 40 - "test_join_scale.py"
Cohesion: 0.33
Nodes (4): _peak_rss_bytes(), test_join_scale(), _write_details(), _write_master()

### Community 41 - "persist_bulk"
Cohesion: 0.15
Nodes (12): persist_bulk(), test_persist_bulk_boards_clean_adds(), Bulk Persist Full Tapes Implementation Plan, Global Constraints, Review Focus, Task 1: COPY helper + persist_bulk, Bulk persist for full Spark tapes, Design (+4 more)

### Community 42 - "joiner.py"
Cohesion: 0.09
Nodes (8): _batched_insert(), _Exceptions, _fmt_decimal(), _open_db(), _open_rows(), _rate(), _relations(), _Rows

### Community 44 - "test_multifile_intake.py"
Cohesion: 0.09
Nodes (29): _configure(), feed(), legacy(), _no_set_code(), boom(), _rows(), _sftp(), test_legacy_feed_ignores_a_corrupt_config_bundle() (+21 more)

### Community 45 - "Rule Authoring LLM"
Cohesion: 0.29
Nodes (6): Notifications, Out of scope, Peer pool (v1), Roles, Rule review workflow + in-app notifications, UI

### Community 46 - "create_batch"
Cohesion: 0.15
Nodes (22): begin_bulk(), mark_staged(), _orphan_cleanup(), persist_partition(), prepare_large(), run_load_bulk(), create_batch(), test_end_to_end_via_api() (+14 more)

### Community 47 - "Rule Registry Lifecycle"
Cohesion: 0.20
Nodes (9): API, Audience and access, Catalog (allowlist only), Intent, Maintenance · Glue artifacts (in-app viewer), Non-goals (Phase 1), Success, Testing (+1 more)

### Community 48 - "Frontend Cognito Auth"
Cohesion: 0.35
Nodes (11): b64url(), bearer(), decode(), initAuth(), load(), login(), logout(), randomString() (+3 more)

### Community 49 - "Glue Job Entry Points"
Cohesion: 0.13
Nodes (14): 1. Stack and tooling, 2. Design tokens, 5. In-scope pages, 6. Data flow and boundaries, 8. Testing and verification, 9. Phase 2 gate (explicit, not scheduled), Current state (facts), Decisions already locked (+6 more)

### Community 50 - "Task 1: DB-free persist writes clean + dirty parts (no Postgres COPY)"
Cohesion: 0.13
Nodes (13): _clean_add(), _flag_dup(), _part_name_from_rows(), _s3_import_on(), serialize_mapped_rows(), _split_clean_dirty(), _upload_part_dir(), _write_clean_part() (+5 more)

### Community 51 - "get_settings"
Cohesion: 0.07
Nodes (24): ai_map(), _attach_uploads(), _check_upload_content(), create_source(), _extract_zip(), _feed_layout(), hardening(), presign() (+16 more)

### Community 52 - "Design"
Cohesion: 0.11
Nodes (16): 1. Kit layout, 2. Shared module: `backend/lbp/demo_setup.py`, 3. API, 4. CLI and `start_demo.sh`, 5. UI, 6. Security and production, 7. Testing, 8. Docs (+8 more)

### Community 53 - "PageHeader"
Cohesion: 0.15
Nodes (17): App UX Phase A Implementation Plan, Execution handoff, Global Constraints, Review Focus, Spec coverage (self-review), App UX Phases B–D Implementation Plan, Global Constraints, Review Focus (+9 more)

### Community 54 - "default_rules.py"
Cohesion: 0.09
Nodes (37): accept_all(), demo_seed(), field_values_edit(), get_mapping(), mapping_diff(), new_mapping_version(), submit_mapping(), suggest_mapping_pair() (+29 more)

### Community 55 - "persist_stream"
Cohesion: 0.14
Nodes (9): _complete_from_staging(), emit_metrics(), persist_stream(), commit_ready(), run_chunk(), process_batch(), reconcile(), test_reconcile_fails_when_boarded_adds_missing_from_sse() (+1 more)

### Community 56 - "test_multifile_run.py"
Cohesion: 0.10
Nodes (36): _batch(), _configure(), _details(), _feed(), _handlers(), _join_exceptions(), _layout(), _master() (+28 more)

### Community 57 - "Imports.jsx"
Cohesion: 0.10
Nodes (64): Task 5: Overview presentation pass, 4. Shared primitives migration, 2. Visual / component system (no Tailwind retry), overrideFileSet(), scoped(), HBars(), Lines(), niceMax() (+56 more)

### Community 58 - "pytest"
Cohesion: 0.26
Nodes (13): override_set(), _audit(), _set(), test_resent_role_after_consumed_opens_new_set(), test_accept_partial_loads_with_missing_detail_policy_and_audits(), test_discard_waiting_set(), test_override_after_batch_queued_rejected(), test_override_requires_reason_and_role() (+5 more)

### Community 59 - "Change Control Docs"
Cohesion: 0.33
Nodes (6): CHG05 Concurrent Change Conflict, Delivery Profile, Feed, Load Type full, Load Type incremental, Optimistic Concurrency via lbp_version

### Community 60 - "Backend Dependencies"
Cohesion: 0.25
Nodes (7): Dev Dependencies pytest and ruff, fastapi, mangum Lambda Adapter, Backend Runtime Dependencies, SQLAlchemy, AWS Glue Data Plane, Control-Plane FastAPI

### Community 61 - "Docker Compose Stack"
Cohesion: 0.25
Nodes (8): docker-compose api Service, lbp-data Shared Volume, docker-compose worker Service, Load Type snapshot, Snapshot Truncation Guard, Throttled Checkpointed Micro-Batch Pipeline, Re-Board Protection (DUP01/DUP02), Schema-Drift Pre-Flight

### Community 62 - "Platform Architecture Docs"
Cohesion: 0.29
Nodes (7): CHG01 Protected Field Change, SR 11-7 Model Risk Controls, AI-Assisted Mapping Engine, T1–T5 Exception Manager, PennyMac Loan Boarding Platform, Mapping Memory, Rules-as-Code Engine

### Community 64 - "get_engine"
Cohesion: 0.06
Nodes (28): audit(), batch_changes(), feed_config(), get_source(), loan_history(), history(), _shape(), SqlPrecedentIndex (+20 more)

### Community 65 - "run_demo_setup"
Cohesion: 0.10
Nodes (24): data_is_present(), DemoSetupConflict, resolve_kit_dir(), run_demo_setup(), SetupResult, wipe_data_dir(), test_data_is_present_false_on_fresh_env(), test_data_is_present_true_after_source() (+16 more)

### Community 66 - "join_files"
Cohesion: 0.17
Nodes (19): RoleStats, case_ids(), load_case(), npi_layout(), quirks_layout(), read_exceptions(), run_case(), test_duplicate_output_column_checked_before_loading_details() (+11 more)

### Community 67 - "Signed Glue Config Docs"
Cohesion: 0.67
Nodes (3): Glue Job lbp-feed, Glue Job lbp-feed-spark, Step Functions Route→Glue→Finalize

### Community 68 - "validate_layout"
Cohesion: 0.13
Nodes (29): _aggregate_expr_errors(), normalize_layout(), role_name_ok(), validate_layout(), agg_layout(), layout(), test_aggregate_where_and_order_by_shape_validated(), errs_for() (+21 more)

### Community 69 - "Load Test Evidence Docs"
Cohesion: 0.40
Nodes (4): 1M Loan Load Test Evidence, Go-Live Blockers Owned by PennyMac, Ready for UAT, Not Go-Live, PoC 100K+/1M Throughput Criterion

### Community 70 - "create_multifile_feed"
Cohesion: 0.13
Nodes (9): _archived_feed(), authorize(), create_multifile_feed(), current_user(), _form_json(), inspect_multifile(), _multifile_form(), preview_layout() (+1 more)

### Community 71 - "Schedule CRUD APIs"
Cohesion: 0.50
Nodes (3): Files, Plan: Rule review notifications (v1), Tasks

### Community 72 - "Multi-file feeds: master/detail file sets, joins and child records"
Cohesion: 0.06
Nodes (33): 1. Concepts, 2. Layout and readiness reference, 3. Onboard a master/detail vendor, 4. Delivery scenarios, 5. Troubleshooting by exception code, 6. Operations, 7. Behavior notes and limits, 8. Demo (+25 more)

### Community 73 - "Vendor Sequencing Docs"
Cohesion: 0.33
Nodes (6): CHG06 Cross-Vendor Loan Change, Per-Vendor File Sequencing Gate, Vendor, SSE Target Schema, Pipe-Delimited Sub-Servicing Columns, Sub-Servicing Sample Loan Tape

### Community 74 - "compile_tree"
Cohesion: 0.20
Nodes (15): fix_code_lookup(), _fix(), fix_fico(), fix_investor_gnma(), fix_loan_number(), fix_maturity(), fix_occupancy(), fix_rate() (+7 more)

### Community 75 - "SFTP Scheduler Docs"
Cohesion: 0.50
Nodes (5): paramiko SFTP Dependency, Glue Job lbp-vendor-pull, Delivery Scheduler, Scheduler Tick, SFTP Pull Connector with Host-Key Pinning

### Community 76 - "import_status"
Cohesion: 0.17
Nodes (11): import_status(), _iso(), _seq(), test_attention_not_capped_by_limit(), test_batches_days_with_aware_until_does_not_500(), test_batches_http_filters_status_and_days(), test_import_status_includes_exception_counts_per_batch(), test_import_status_q_escapes_like_wildcards() (+3 more)

### Community 78 - "demo_setup"
Cohesion: 0.18
Nodes (10): File map, Global Constraints, Guided Rule Authoring Implementation Plan, Review Focus, Task 1: JSON Logic new operators, Task 2: shapes compiler, Task 3: API + registry, Task 4: Authoring → tree (+2 more)

### Community 79 - "sweep_sets"
Cohesion: 0.12
Nodes (12): _merge_override(), _record_error(), _safe_message(), sweep_sets(), DeliveryError, _audit_all(), boom(), test_persistent_batch_error_is_audited_once_per_message() (+4 more)

### Community 80 - "sqlalchemy"
Cohesion: 0.12
Nodes (8): upgrade(), upgrade(), upgrade(), upgrade(), upgrade(), upgrade(), upgrade(), upgrade()

### Community 81 - "time"
Cohesion: 0.27
Nodes (7): _build_csv(), _ensure_extensions(), _import_aws_s3(), _import_stdin_copy(), _list_sse_keys(), main(), _reuse_or_build()

### Community 82 - "f"
Cohesion: 0.11
Nodes (27): canonical_loans(), generate_master_detail(), _inject_defect(), _loan(), _noisy_ref(), write_bulk_excel(), write_correspondent_csv(), write_pcg_retail() (+19 more)

### Community 83 - "normalize_part"
Cohesion: 0.15
Nodes (14): _Relation, key_text(), normalize_key(), normalize_part(), test_all_zero_becomes_single_zero(), test_blank_with_empty_ops_never_matches_and_values_unchanged(), test_composite_key_text_is_unambiguous(), test_empty_and_null_never_match() (+6 more)

### Community 84 - "test_lifecycle_and_onboarding_e2e.py"
Cohesion: 0.46
Nodes (6): _approve(), _create(), _deliver(), _ids(), test_discard_draft_and_delete_unused_feed(), test_onboard_load_archive_restore_discard_delete()

### Community 85 - "ETL Monitor Implementation Plan"
Cohesion: 0.33
Nodes (5): get_batch(), ETL Monitor Implementation Plan, Global Constraints, Review Focus, Self-review notes

### Community 86 - "LayoutError"
Cohesion: 0.13
Nodes (8): _Acc, AggregateMode, _blank(), _parse_options(), _require_columns(), _sort_value(), _SortKey, LayoutError

### Community 89 - "test_join_aggregate.py"
Cohesion: 0.25
Nodes (13): _dec(), layout(), run(), test_absurd_exponents_are_not_numeric(), test_aggregate_needs_a_spec(), test_aggregate_where_and_order_by(), test_decimal_commas_are_not_numeric_but_thousands_separators_are(), test_join07_not_repeated_for_duplicate_master_keys() (+5 more)

### Community 92 - "tick"
Cohesion: 0.19
Nodes (12): _acquire_leader(), tick(), _alerts(), Clock, clock(), _deliveries(), _schedule(), test_delivery_lifecycle_received_late_missed_and_alerts_once() (+4 more)

### Community 93 - "api"
Cohesion: 0.12
Nodes (18): build, environment, ports, volumes, context, dockerfile, ANTHROPIC_API_KEY, LBP_AI_PROVIDER (+10 more)

### Community 94 - "test_multifile_preview.py"
Cohesion: 0.23
Nodes (13): preview_join(), _onboard(), _counts(), _csv(), _samples(), test_feed_preview_refuses_bad_role_names_and_writes_nothing_outside(), test_preview_blocked_by_min_match_rate(), test_preview_does_not_write_db_or_files_outside_tmp() (+5 more)

### Community 96 - "_batches"
Cohesion: 0.18
Nodes (15): file_sha256(), calls(), _suspend(), test_pull_now_skips_failed_scheduled_pull_batch(), test_tick_endpoint_skips_swept_failed_set_batch(), test_tick_endpoint_still_dispatches_queued_batch(), _batches(), _members() (+7 more)

### Community 97 - "ai.py"
Cohesion: 0.20
Nodes (5): AnthropicClient, BedrockClient, get_llm(), LLMClient, LLMMappingReranker

### Community 98 - "_join"
Cohesion: 0.16
Nodes (11): _block(), _block_values(), _blocked_result(), _insert_join_exceptions(), _join(), _joined_dir(), _record(), _reuse() (+3 more)

### Community 99 - "test_sftp_pull.py"
Cohesion: 0.18
Nodes (4): _serve(), _Server, _SFTP, sftp_server()

### Community 101 - "canCap"
Cohesion: 0.12
Nodes (34): getPersona(), GROUP_LABEL, GROUP_ORDER, JobsPane(), Maintenance(), NotebookView(), TemplateEditor(), ACTION_LABEL (+26 more)

### Community 102 - "LBP PoC — AWS deployments inventory"
Cohesion: 0.05
Nodes (35): Demo kit: test data and a ready-to-run demo, How the test data is made, Personas (the "Signed in as" switcher, bottom left), Suggested run of show (about 27 minutes), The pre-loaded state, Two ways to demo, What is in the kit, 10. Security, IAM, monitoring (+27 more)

### Community 103 - "File map"
Cohesion: 0.40
Nodes (6): list_batches(), _parse_batch_instant(), File map, Task 2: Wire `GET /api/batches` query params, Task 3: Nav, personas, screen copy, Task 5: Mock API filter parity + Overview link

### Community 104 - "Frontend UI Design System (Phase 1) Implementation Plan"
Cohesion: 0.40
Nodes (4): Frontend UI Design System (Phase 1) Implementation Plan, Global Constraints, Review Focus, Self-review notes (author)

### Community 105 - "run_demo_setup"
Cohesion: 0.18
Nodes (10): APIs, Approval, Architecture, Guided Rule Authoring — Design Spec, In scope, Intent, Out of scope (explicit), Persistence (+2 more)

### Community 107 - "conftest.py"
Cohesion: 0.33
Nodes (5): APIs, Intent, Out of scope, Rule Template Maintenance — Design Spec, UI

### Community 108 - "wipe_data_dir"
Cohesion: 0.13
Nodes (11): _apply_ssm(), db_secret(), Settings, _inject_password(), _client(), _rsa(), test_jwt_mode(), test_production_refuses_unsafe_config() (+3 more)

### Community 109 - "template_store.py"
Cohesion: 0.21
Nodes (13): create_template(), delete_template(), get_template(), list_templates(), _row(), seed_builtins(), set_hidden(), _slug() (+5 more)

### Community 111 - "fingerprint"
Cohesion: 0.47
Nodes (3): derived_key(), fingerprint(), test_join_key_fingerprint_is_keyed_not_a_plain_hash()

### Community 112 - "conftest.py"
Cohesion: 0.53
Nodes (4): generate_all(), client(), env(), sample_files()

### Community 113 - "test_glue_jobs.py"
Cohesion: 0.10
Nodes (17): partition_processor(), run(), summary(), _fails_of(), process_chunk(), _status_of(), feeds_by_column(), _batch() (+9 more)

### Community 115 - "onboard.py"
Cohesion: 0.12
Nodes (13): role_name_error(), _compensate(), _drop_sample(), inspect_files(), _read(), register_multifile_source(), build_joined_sample(), _first_exceptions() (+5 more)

### Community 116 - "User"
Cohesion: 0.08
Nodes (52): acknowledge(), add_mapping_field(), ai_suggest(), approve_delivery(), approve_mapping(), archive_source(), batch_apply_ooo(), batch_discard() (+44 more)

### Community 117 - "stage.py"
Cohesion: 0.07
Nodes (26): _accept(), _accepted_missing(), check_role_headers(), _detail_columns(), _empty_columns(), _files_by_role(), _header(), joined_pii_cols() (+18 more)

### Community 118 - "Demo Kit In-App Implementation Plan"
Cohesion: 0.33
Nodes (5): Demo Kit In-App Implementation Plan, Execution handoff, Global Constraints, Review Focus, Spec coverage check

### Community 119 - "authoring.py"
Cohesion: 0.23
Nodes (8): _base_with(), draft_from_text(), _heuristic(), resolve_field(), _sample_value(), _r(), t(), run_tests()

### Community 120 - "security.py"
Cohesion: 0.17
Nodes (11): Current state (baseline), Data layout, Design, Flags, Goal, Job 1 — `lbp-*-feed-spark` (compute only), Job 2 — `lbp-*-feed-load` (DB only), Non-goals / honesty (+3 more)

### Community 124 - "Spark / Load Job Split Implementation Plan"
Cohesion: 0.40
Nodes (4): Global Constraints, Review Focus, Self-review (done inline), Spark / Load Job Split Implementation Plan

### Community 126 - "DuplicateFileError"
Cohesion: 0.29
Nodes (6): Intent, Layout, Locked decisions, Non-goals, Overview as boarding load desk, Success

### Community 127 - "get_settings"
Cohesion: 0.09
Nodes (21): write_coalesced(), flush(), upload_csv(), get_settings(), DirtyPartWriter, load_dirty_files(), open_dirty_part_writer(), write_clean_sse_csv() (+13 more)

### Community 128 - "ETL Monitor (fleet ops console)"
Cohesion: 0.15
Nodes (12): API, Error handling, ETL Monitor (fleet ops console), Frontend touchpoints, `GET /api/batches` (extend), Intent, Locked decisions, Monitor layout (+4 more)

### Community 129 - "join_files"
Cohesion: 0.10
Nodes (16): join_files(), master_keys(), JoinResult, _master_problems(), match_rate_gate(), _tracked(), test_gate_skips_only_absent_relations(), test_join_files_exempts_absent_role() (+8 more)

### Community 130 - "attach_file"
Cohesion: 0.18
Nodes (7): attach_file(), feed(), _file(), test_concurrent_arrivals_create_one_set_and_one_batch(), arrive(), test_set_batches_refuse_snapshot_and_incremental(), test_strict_false_records_a_failed_set_batch()

### Community 133 - "finalize_bulk"
Cohesion: 0.16
Nodes (13): _bulk_load_root(), clean_sse_csv_uris(), _file_load_on(), finalize_bulk(), _list_kind_part_names(), load_clean_files(), _spark_db_free_on(), stage_timer() (+5 more)

### Community 134 - "Monitor.jsx"
Cohesion: 0.17
Nodes (21): Task 4: `monitorQuery` helpers + `Monitor.jsx`, uploadSet(), uploadSetZip(), batchStep(), buildBatchesPath(), deskOrder(), LIVE_STATUSES, LOCAL_STEP (+13 more)

### Community 137 - "Signed Feed Configuration"
Cohesion: 0.40
Nodes (5): config_store.publish, Maker-Checker Governance for Schedules, SOX Change Control and Audit Trail, Hash-Chained Audit Log, Signed Feed Configuration

### Community 139 - "test_exception_loads.py"
Cohesion: 0.53
Nodes (4): _board_one(), test_exception_list_filters_by_loaded_on_and_batch(), test_exception_list_includes_filename_and_loaded_at(), test_exception_loads_endpoint()

### Community 140 - "profile_rows"
Cohesion: 0.40
Nodes (13): decide_profile(), _boarded_pcg(), _pick(), _run(), _set_profile(), _sse(), test_incremental_sparse_updates_closes_and_change_control(), test_out_of_order_override_holds_every_change() (+5 more)

### Community 146 - "file_action"
Cohesion: 0.33
Nodes (4): _brief(), fetch_traces(), summarize_events(), test_summarize_events_keeps_each_step_and_its_return()

### Community 150 - "DuplicateFileError"
Cohesion: 0.18
Nodes (5): _attach_arrival(), on_file_arrival(), _reject_arrival(), DuplicateFileSetError, DuplicateFileError

### Community 151 - "local_path"
Cohesion: 0.35
Nodes (6): delete_stored(), is_s3(), local_path(), persist_upload(), _s3(), _split()

### Community 152 - "run_batch"
Cohesion: 0.06
Nodes (34): join_reconciliation(), mark_all_read(), mark_read(), _acquire_lease(), BatchBusyError, _chunks(), _join_stage(), beat() (+26 more)

## Knowledge Gaps
- **21 isolated node(s):** `lbp`, `Hash-Chained Audit Log`, `CHG05 Concurrent Change Conflict`, `Load Type full`, `Dev Dependencies pytest and ruff` (+16 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1078 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **25 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_engine()` connect `get_engine` to `test_feed_lifecycle.py`, `Delivery Scheduling`, `get`, `attach_file`, `batch.py`, `finalize_bulk`, `loader.py`, `CLI Worker DB`, `profile_rows`, `json`, `glue_jobs.py`, `Vendor Feed Profiles`, `Preflight Mapping Checks`, `test_multifile_fileset.py`, `run_batch`, `audit`, `Lambda Path Tests`, `pathlib`, `test_multifile_onboard.py`, `Analytics Service`, `fileset.py`, `lbp/demo_setup.py`, `profile_of`, `Mapping Field Inspect`, `persist_bulk`, `test_multifile_intake.py`, `create_batch`, `Task 1: DB-free persist writes clean + dirty parts (no Postgres COPY)`, `get_settings`, `default_rules.py`, `persist_stream`, `test_multifile_run.py`, `pytest`, `run_demo_setup`, `create_multifile_feed`, `import_status`, `sweep_sets`, `f`, `test_lifecycle_and_onboarding_e2e.py`, `ETL Monitor Implementation Plan`, `tick`, `test_multifile_preview.py`, `_batches`, `_join`, `wipe_data_dir`, `template_store.py`, `conftest.py`, `test_glue_jobs.py`, `onboard.py`, `User`, `stage.py`, `feed_layout`, `get_settings`?**
  _High betweenness centrality (0.165) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `get_settings()` (e.g. with `write_coalesced()` and `upload_csv()`) actually correct?**
  _`get_settings()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `lbp`, `Hash-Chained Audit Log`, `CHG05 Concurrent Change Conflict` to the rest of the system?**
  _21 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `FeedLayout.jsx` be split into smaller, more focused modules?**
  _Cohesion score 0.07660455486542443 - nodes in this community are weakly interconnected._
- **Why does `import_status()` connect `import_status` to `get_engine`, `Analytics Service`, `ETL Monitor (fleet ops console)`, `get`, `File map`, `file_action`, `ETL Monitor Implementation Plan`, `run_batch`, `_like_escape`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `run_batch()` (e.g. with `progress()` and `Multi-file feeds, Phase 1 (Foundation) Implementation Plan`) actually correct?**
  _`run_batch()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Should `test_feed_lifecycle.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10837245696400626 - nodes in this community are weakly interconnected._