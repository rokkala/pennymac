# Multi-file feeds, Phase 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A feed can declare a master file plus detail files; the platform pairs them into a file set, waits until the set is ready, joins them (merge and aggregate modes) and runs the existing pipeline on the joined result.

**Architecture:** A generic `lbp/multifile/` package (layout validation, key normalization, join engine, file-set intake). The join stage materializes one **joined CSV** per batch (`batches.joined_path`), in master file order; `run_batch` then reads that file exactly as it reads a normal file, so checkpoint/resume, pre-flight, mapping, rules and load are unchanged. Layout and readiness live on `sources`, go through the delivery-profile maker-checker, and are compiled into the signed feed bundle. Feeds without a layout take the legacy path with no new code executed.

**Tech Stack:** Python 3.11, SQLAlchemy Core + Alembic, FastAPI, SQLite and PostgreSQL, pytest; React/Vite frontend (`node --test` for helper modules).

**Spec:** `docs/superpowers/specs/2026-11-17-multi-file-feeds-design.md` (phases 2-5 get their own plans after this one lands: flatten; child records; Glue/Spark parity; incremental detail-only and relation trees).

## Global Constraints

- Phase 1 supports **SQLite and PostgreSQL**; SQL Server is not required until phase 4. New tables must still avoid dialect-specific types.
- The local join must handle a detail file **at least 10x the master** (tested at 10M detail rows, marked `slow`), with **bounded memory** (SQLite temp tables, no whole-file dict).
- Joined output follows **master file order**; detail rows keep **detail file order** within a master (needed for checkpoint/resume).
- **No loan-specific names in `lbp/multifile/`** ("loan", "borrower", SSE columns appear only in tests, samples and docs).
- **Single-file feeds are untouched:** no layout means no file-set tables written, no join stage, and a feed bundle whose content hash is unchanged.
- **No silent partial loads:** loading with a missing file or unmatched rows happens only by declared policy or a recorded override with a reason.
- NPI from any role never appears in logs, error messages or unmasked exception rows.
- Layout/readiness changes reuse the delivery-profile maker-checker and roles; set overrides reuse the sequencing-override roles (`onboarding_reviewer`, `compliance_reviewer`, `admin`). No new roles.
- Join semantics (the golden fixtures are the spec of record):
  - `normalize` applies to the join key only; stored values keep their original form. `strip_leading_zeros` on all-zero input yields `"0"`. Empty or null key parts never match.
  - With no `order_by`, `first`/`last`/`concat_distinct` use detail file order; `concat_distinct` joins with `|` in first-seen order.
  - `sum/min/max` ignore nulls and empty strings; a group with no non-null values yields null; `count` counts rows.
  - Two roles producing the same output column is a layout validation error.
  - Master columns keep plain names; detail columns appear as `role.column`; aggregate outputs use their `as` name.
- Pairing value comes from a named capture group in `name_pattern` (or a manifest), never from file contents. A file set counts as **one delivery** and one sequence number.
- `min_match_rate` is checked on a sample in pre-flight and again on the full run, before any load; master-side rate applies unless `on_orphan_detail: exception`, then both sides.

## Review Focus

Input classes the spec implies and no obvious task covers; each has a pinning test in the named task.

1. **Empty or header-only master/detail file** must not crash; every master becomes "missing detail" per policy, and a header-only master yields a zero-row batch with a clear result (Task 5).
2. **Resume after a crash mid-batch** must reuse the same joined file so checkpoints stay valid, never regenerate it with different content (Task 11).
3. **Same file sent twice, or a role re-sent after the set loaded** must dedupe or open a correction set, never double-load (Task 9).
4. **NPI in join exceptions** (orphan detail rows carry raw values) must be masked using the layout's per-role PII columns (Task 11).
5. **Awkward headers**: BOM, different delimiters/encodings per role, duplicate column names inside one file, and detail columns whose names collide with master columns (Tasks 3 and 1).

---

### Task 1: Layout model and validation

**Files:**
- Create: `backend/lbp/multifile/__init__.py`, `backend/lbp/multifile/layout.py`
- Test: `backend/tests/test_multifile_layout.py`

**Interfaces:**
- Produces: `class LayoutError(ValueError)`; `SUPPORTED_MODES = frozenset({"merge", "aggregate"})`; `NORMALIZERS = ("trim", "strip_leading_zeros", "upper")`; `AGG_OPS = ("sum","count","min","max","first","last","any","concat_distinct")`; `DEFAULT_READINESS: dict`; `normalize_layout(layout: dict) -> dict` (fills defaults, never mutates input); `validate_layout(layout: dict, readiness: dict | None, columns: dict[str, list[str]] | None = None) -> list[str]` (list of error strings; empty = valid; `columns` maps role to known column names when available).

- [ ] **Step 1: Write failing tests** in `test_multifile_layout.py` using the spec's layout shape (roles `master`, `details`): `test_valid_minimal_layout_has_no_errors`; `test_exactly_one_master_required` (0 or 2 masters yield an error mentioning "master"); `test_unsupported_mode_rejected` (`flatten` and `child` yield "not yet supported"); `test_duplicate_output_column_rejected` (two aggregate outputs both `as: total`, or aggregate `as` equal to a master column when `columns` given); `test_unknown_normalizer_and_agg_op_rejected`; `test_relation_must_reference_declared_roles`; `test_key_parts_count_must_match`; `test_readiness_timeout_policy_rules` (`on_timeout: load_master_only` invalid when any detail has `required: true`); `test_normalize_layout_fills_defaults_without_mutating`; `test_name_pattern_must_compile_and_named_groups_required_for_pairing` (readiness `pairing: business_date` needs a `(?P<date>...)`-style group in every file's pattern).
- [ ] **Step 2: Run** `cd backend && .venv/bin/python -m pytest tests/test_multifile_layout.py -q`; expect FAIL (module missing).
- [ ] **Step 3: Implement** `layout.py` as pure functions over the spec's layout/readiness dict shape (files, relations, readiness). Defaults: relation `join: left`, `cardinality: many`, `on_orphan_detail: exception`, `on_missing_detail: allow`, `on_duplicate_master: reject_all`, `min_match_rate: 0.0`, `normalize: ["trim"]`; readiness `require: all_required`, `pairing: business_date`, `wait_timeout_minutes: 240`, `on_timeout: alert_only`.
- [ ] **Step 4: Run tests; expect PASS.**
- [ ] **Step 5: Commit** `feat(multifile): layout model and validation`.

### Task 2: Key normalization

**Files:**
- Create: `backend/lbp/multifile/keys.py`
- Test: `backend/tests/test_multifile_keys.py`

**Interfaces:**
- Consumes: `NORMALIZERS` from Task 1.
- Produces: `normalize_part(v: str | None, ops: Sequence[str]) -> str | None` (None when the result is empty); `normalize_key(parts: Sequence[str | None], ops: Sequence[str]) -> tuple[str, ...] | None` (None if any part is None); `key_text(key: tuple[str, ...]) -> str` (stable `\x1f`-joined string used as the SQLite join column).

- [ ] **Step 1: Tests:** `test_trim_upper_strip_zeros` (`" 0012ab "` with all ops gives `"12AB"`); `test_all_zero_becomes_single_zero` (`"000"` gives `"0"`); `test_empty_and_null_never_match` (`""`, `"  "`, `None` give None; a composite key with one empty part gives None); `test_composite_key_text_is_unambiguous` (`("a","bc")` and `("ab","c")` give different `key_text`).
- [ ] **Step 2: Run; FAIL.** **Step 3: Implement.** **Step 4: Run; PASS.**
- [ ] **Step 5: Commit** `feat(multifile): join key normalization`.

### Task 3: Join engine, merge mode, golden-fixture harness

**Files:**
- Create: `backend/lbp/multifile/joiner.py`, `backend/tests/fixtures/joins/merge_basic/{case.json,master.csv,details.csv,expected.csv}`, `backend/tests/test_join_golden.py`
- Modify: none

**Interfaces:**
- Consumes: `normalize_layout`, `normalize_key` (Tasks 1-2); `iter_rows`, `ParseOptions` from `lbp/ingestion/parser.py`.
- Produces:
  - `@dataclass RoleStats: rows_in: int; matched: int; orphaned: int; rejected: int`
  - `@dataclass JoinResult: columns: list[str]; rows_out: int; per_role: dict[str, RoleStats]; exceptions_path: Path; exception_counts: dict[str, int]; master_match_rate: float; detail_match_rate: dict[str, float]; blocked: str | None`
  - `join_files(layout: dict, inputs: dict[str, Path], parse_options: dict[str, dict], out_path: Path, tmp_dir: Path) -> JoinResult`. Writes the joined CSV (UTF-8, header row, master order) and a JSONL exceptions file (`{"code","role","row_number","key","message","raw"}` per line).
  - `ENGINES: dict[str, Callable]` in the test harness, `{"local": join_files}`, so Phase 4 can register Spark.
- `case.json` shape: `{"layout": {...}, "files": {"master": "master.csv", ...}, "parse_options": {...}, "expected_rows": "expected.csv", "expected_exceptions": [{"code","role","row_number"}], "expected_blocked": null}`.

- [ ] **Step 1: Write failing tests** in `test_join_golden.py`: a parametrized `test_golden_case(case_dir, engine)` over every directory in `fixtures/joins/` and every engine in `ENGINES`, asserting joined rows (CSV equality), exception codes/row numbers (as sorted tuples) and `blocked`. Add the `merge_basic` fixture: 3 masters, 1:1 details with leading-zero/case/whitespace key differences, one master without detail (`on_missing_detail: allow`, columns empty). Also in a separate file-level test `test_header_quirks`: a BOM'd master, `;`-delimited detail via per-role `parse_options`, and a detail column named like a master column (output is `details.<col>`, master unchanged).
- [ ] **Step 2: Run** `pytest tests/test_join_golden.py -q`; FAIL.
- [ ] **Step 3: Implement `join_files`.** Approach: pass 1 streams the master into an SQLite temp DB table `master_keys(nkey TEXT PRIMARY KEY-less, cnt)` to count normalized keys; details load into per-role tables `(row_no INTEGER, nkey TEXT, data TEXT[json])` with an index on `nkey` (batched inserts); pass 2 streams the master again in file order, looks up its details by `nkey` ordered by `row_no`, and writes the merged row with detail columns prefixed `role.`. Orphans come from a SQL anti-join of each detail table against `master_keys`. Memory stays bounded by batch size. This task implements `merge` only (aggregate raises `LayoutError` until Task 4).
- [ ] **Step 4: Run; PASS.**
- [ ] **Step 5: Commit** `feat(multifile): local join engine (merge) with golden fixtures`.

### Task 4: Aggregate mode

**Files:**
- Modify: `backend/lbp/multifile/joiner.py`
- Create: fixtures `agg_basic/`, `agg_nulls/` under `backend/tests/fixtures/joins/`
- Test: `backend/tests/test_join_golden.py` (picks them up), `backend/tests/test_join_aggregate.py`

**Interfaces:**
- Consumes: `join_files` and fixture harness (Task 3); `AGG_OPS` (Task 1).
- Produces: aggregate columns on the joined row, named by `as`; `where` and `order_by` evaluated with the existing transform expression machinery in `lbp/mapping/transforms.py` (no new grammar).

- [ ] **Step 1: Tests (fixtures + unit):** `agg_basic` (sum, count, min, max, first, last, any, concat_distinct over a 1:N detail, including file-order `first/last` and `a|b|c` first-seen `concat_distinct`); `agg_nulls` (nulls and empty strings ignored by sum/min/max; all-null group gives empty; count counts rows including null values; master with no detail gives empty/`0`-count per spec: count of no rows is `0`, others empty). `test_aggregate_where_and_order_by` (`where` filters detail rows before aggregation; `order_by` descending changes `first`).
- [ ] **Step 2: Run; FAIL.** **Step 3: Implement** aggregation inside the pass-2 detail lookup; `sum` uses `Decimal`, output formatted without float artifacts. **Step 4: PASS.**
- [ ] **Step 5: Commit** `feat(multifile): aggregate mode`.

### Task 5: Data-problem policies and match rates

**Files:**
- Modify: `backend/lbp/multifile/joiner.py`
- Create: fixtures `orphans/`, `duplicate_master/`, `cardinality_one/`, `inner_join/`, `empty_files/`, `low_match_rate/`
- Test: `backend/tests/test_join_golden.py`

**Interfaces:**
- Produces exception codes (strings, stable): `JOIN01` orphan detail, `JOIN02` required detail missing, `JOIN03` duplicate master key, `JOIN04` cardinality violation (`cardinality: one` with >1 detail), `JOIN05` key unparseable (empty/null key part), `JOIN06` inner-join dropped master. `JoinResult.blocked` is a message when the applicable match rate is below `min_match_rate`, else None.

- [ ] **Step 1: Fixtures/tests** (each asserts rows, exception codes+row numbers, `blocked`): `orphans` (`on_orphan_detail: exception` gives JOIN01 with role and detail row number; `drop` gives none but `per_role.orphaned` counts them); `duplicate_master` (`reject_all`: both rows excluded from output with JOIN03; `first`/`last` keep one; `JOIN03` still logged for the dropped ones); `cardinality_one` (JOIN04 and the master is excluded); `inner_join` (masters without details dropped with JOIN06, never silently); `empty_files` (header-only detail: all masters follow `on_missing_detail`; header-only master: zero rows out, no crash, `rows_out == 0`; a completely empty (0-byte) file raises `LayoutError("...empty file...")`); `low_match_rate` (`min_match_rate: 0.9` with 50% matched gives `blocked` text; the same data with `0.4` does not). Also `test_exceptions_raw_not_logged` (caplog contains no row values from the files).
- [ ] **Step 2: Run; FAIL.** **Step 3: Implement** policies in pass 2; compute `master_match_rate = masters_with_detail / masters_read` and per-role `detail_match_rate = details_with_master / details_read`; apply the spec's rule for which rates the threshold uses. **Step 4: PASS.**
- [ ] **Step 5: Commit** `feat(multifile): join policies, exceptions and match-rate gate`.

### Task 6: Database schema and migration

**Files:**
- Modify: `backend/lbp/store/db.py` (tables: `sources`, `mappings`, `batches`, `exceptions`; new `file_sets`, `batch_files`)
- Create: `backend/migrations/versions/0007_multifile.py`
- Test: `backend/tests/test_migrations.py` (extend), `backend/tests/test_multifile_schema.py`

**Interfaces:**
- Produces columns/tables (all nullable or defaulted so existing rows are valid):
  - `sources`: `layout JSON`, `readiness JSON`, `layout_draft JSON`, `readiness_draft JSON`, `layout_proposed_by String(80)`
  - `mappings`: `entity String(40) default 'loan' not null` (server default `'loan'`)
  - `batches`: `file_set_id String(40) index`, `joined_path String(500)`, `join_summary JSON`
  - `exceptions`: `role String(40)` nullable
  - `file_sets`: `set_id String(40) PK`, `source_id String(40) index`, `pairing_key String(120) index`, `status String(16) index` (`waiting|ready|expired|overridden|consumed|discarded`), `opened_at`, `ready_at`, `expires_at DateTime`, `batch_id String(40)`, `members_sha String(64) index`, `override JSON`
  - `batch_files`: `id Integer PK autoinc`, `set_id String(40) index`, `batch_id String(40) index`, `role String(40)`, `filename String(300)`, `file_path String(500)`, `file_sha256 String(64) index`, `row_count Integer`, `received_at DateTime`, `UniqueConstraint(set_id, role)`

- [ ] **Step 1: Tests:** extend `test_migrations.py`'s upgrade/downgrade round trip to include 0007 and assert the new columns/tables exist after upgrade and are gone after downgrade; `test_multifile_schema.py::test_existing_insert_paths_still_work` (insert a source, mapping, batch, exception using only the pre-existing columns; `mappings.entity` reads back `"loan"`); `test_file_set_role_unique` (second `(set_id, role)` insert raises `IntegrityError`).
- [ ] **Step 2: Run; FAIL.** **Step 3: Implement** the table definitions and the Alembic revision following 0006's style; `down_revision = "0006"`.
- [ ] **Step 4: Run** `pytest tests/test_migrations.py tests/test_multifile_schema.py -q`; PASS (and, with `LBP_TEST_DATABASE_URL` set to a local PostgreSQL, PASS there too).
- [ ] **Step 5: Commit** `feat(multifile): schema for layouts, file sets and joined batches`.

### Task 7: Feed bundle carries layout and readiness

**Files:**
- Modify: `backend/lbp/config_store.py` (`build`, `FeedConfig`, `load`)
- Test: `backend/tests/test_multifile_config.py`

**Interfaces:**
- Consumes: columns from Task 6; `validate_layout`/`normalize_layout` (Task 1).
- Produces: when `sources.layout` is set, `build()` adds `layout` (normalized), `readiness` and `mappings: {"loan": <same object as "mapping">}`; `FeedConfig` gains `layout: dict | None` and `readiness: dict | None` (None for legacy feeds). Layout-less bundles are byte-identical to today's.

- [ ] **Step 1: Tests:** `test_legacy_bundle_unchanged` (build a feed with no layout; assert the dict has no `layout`/`readiness`/`mappings` keys and equals the pre-change structure); `test_layout_in_signed_bundle` (set a layout, `publish`, `load`; `cfg.layout` round-trips and signature verification passes); `test_layout_change_creates_new_version` (changing the layout republishes a new version; an identical republish returns `unchanged`).
- [ ] **Step 2: Run; FAIL.** **Step 3: Implement.** **Step 4: PASS.**
- [ ] **Step 5: Commit** `feat(multifile): publish layout and readiness in the signed bundle`.

### Task 8: Layout maker-checker service and API

**Files:**
- Create: `backend/lbp/multifile/service.py`
- Modify: `backend/lbp/api/main.py` (endpoints beside the delivery-profile ones)
- Test: `backend/tests/test_multifile_service.py`

**Interfaces:**
- Consumes: `validate_layout` (Task 1), columns from Task 6, `config_store.publish`.
- Produces: `propose_layout(source_id, layout: dict, readiness: dict, actor, roles) -> dict`; `decide_layout(source_id, actor, roles, approve: bool, comment=None) -> dict`; `LayoutServiceError(ValueError)`. Endpoints: `GET /api/sources/{id}/layout` (live + draft), `PUT /api/sources/{id}/layout` (propose), `POST /api/sources/{id}/layout/decide`. Roles/behaviour mirror `propose_profile`/`decide_profile` in `pipeline/delivery.py` (propose: `onboarding`, `onboarding_reviewer`, `admin`; decide: `onboarding_reviewer`, `admin`, different user from proposer; approval publishes the bundle with reason "layout approved").

- [ ] **Step 1: Tests:** `test_propose_requires_role`; `test_invalid_layout_rejected_with_errors`; `test_approver_must_differ_from_proposer`; `test_approve_publishes_bundle_and_audits` (bundle `layout` present, audit rows `source.layout_propose`/`source.layout_approve`); `test_reject_clears_draft`; API-level `test_layout_endpoints_roundtrip` via `TestClient` following `test_api.py` conventions.
- [ ] **Step 2: Run; FAIL.** **Step 3: Implement** by following `delivery.py`'s propose/decide structure. **Step 4: PASS.**
- [ ] **Step 5: Commit** `feat(multifile): layout and readiness maker-checker`.

### Task 9: File-set intake and readiness

**Files:**
- Create: `backend/lbp/multifile/fileset.py`
- Modify: `backend/lbp/pipeline/batch.py` (`create_batch`: no signature change; `create_batch_for_set` links the set afterwards)
- Test: `backend/tests/test_multifile_fileset.py`

**Interfaces:**
- Consumes: `FeedConfig.layout/readiness` (Task 7), tables (Task 6), `pipeline.create_batch`, `pipeline.file_sha256`.
- Produces:
  - `route_file(layout: dict, filename: str) -> tuple[str, dict[str, str]] | None` (role and captured groups; first matching `name_pattern`, patterns tried in file order)
  - `pairing_key(readiness: dict, captured: dict[str, str], arrived_at: datetime) -> str`
  - `attach_file(source_id: str, filename: str, file_path: Path, actor: str, role: str | None = None, arrived_at: datetime | None = None) -> dict` returning `{"set_id", "role", "status", "batch_id": str | None}`; raises `FileSetError(ValueError)` for unrouteable names
  - `evaluate_set(set_id: str, now: datetime | None = None) -> str` (new status)
  - `expire_sets(now: datetime | None = None) -> list[str]` (set_ids whose `wait_timeout_minutes` passed; alert via `scheduling.alerts.notify("delivery_late"/"delivery_missed", message naming the missing role)`; apply `on_timeout`)
  - `create_batch_for_set(set_id: str, actor: str) -> str` (creates the batch on the master file through `create_batch`, links `batches.file_set_id`, fills `batch_files`, sets the set `consumed`)
- Behaviour: a file joins the open (`waiting`) set with the equal pairing key, else opens a new one; `window_minutes` pairs arrivals within N minutes of the set's `opened_at`; a set is `ready` when `require` is met, and a batch is created only then. A role arriving twice in a `waiting` set with the same sha256 is ignored (idempotent); with a different sha256 it replaces the file and is audited. A role arriving for a set already `consumed` opens a **new** set (correction). Set identity `members_sha` = sha256 over `role:sha256` pairs sorted by role; a ready set whose `members_sha` matches a non-failed batch raises `DuplicateFileError`. A lone file whose pairing key differs from every open set never joins them.

- [ ] **Step 1: Tests:** `test_route_by_pattern_and_capture`; `test_two_files_same_date_make_one_ready_set_and_one_batch`; `test_master_only_stays_waiting_no_batch`; `test_mismatched_dates_open_separate_sets`; `test_window_minutes_pairing`; `test_same_file_twice_is_idempotent` and `test_resent_role_after_consumed_opens_new_set` (Review Focus 3); `test_duplicate_member_set_rejected`; `test_timeout_alerts_names_missing_role_and_applies_policy` (`alert_only` leaves set waiting, `fail` marks `expired`, `load_master_only` queues a batch, only if details are non-required); `test_two_open_sets_route_independently`.
- [ ] **Step 2: Run; FAIL.** **Step 3: Implement.** Row-lock the open set during attach (`with_for_update`, same pattern as `sequencing.acquire`) so concurrent arrivals cannot both create a batch. The sequence gate sees only the master file (one delivery per set).
- [ ] **Step 4: PASS.**
- [ ] **Step 5: Commit** `feat(multifile): file sets, pairing and readiness`.

### Task 10: Intake wiring (API upload, zip, scheduler, pulls, S3 arrival)

**Files:**
- Modify: `backend/lbp/api/main.py` (`upload`; new `upload_set`), `backend/lbp/scheduling/service.py` (`tick`, pull path near line 408), `aws/lambdas/handlers.py` (S3 arrival near line 53)
- Test: `backend/tests/test_multifile_intake.py`

**Interfaces:**
- Consumes: `attach_file`, `expire_sets` (Task 9).
- Produces: `POST /api/upload` keeps its contract for legacy feeds; for a feed with a layout it calls `attach_file` (optional `role` form field) and returns `{"set_id","role","status","batch_id"}`. New `POST /api/upload/set` takes several `files` plus an optional `manifest` (JSON `{role: filename}`) or one `.zip`, attaches each, returns the list of results. `tick()` calls `expire_sets()` once per run. A scheduled pull delivers each pulled file through `attach_file` when the feed has a layout (one pull pattern per role comes from the layout's `name_pattern`s). The S3 handler does the same for layout feeds.

- [ ] **Step 1: Tests:** `test_upload_legacy_feed_unchanged`; `test_upload_layout_feed_routes_to_set`; `test_upload_set_zip_with_manifest`; `test_upload_set_zip_without_manifest_routes_by_pattern`; `test_zip_rejects_path_traversal_and_oversized_members`; `test_tick_expires_waiting_sets`; `test_pull_attaches_each_role` (reuse `test_sftp_pull.py` fakes); `test_s3_arrival_attaches_role` (reuse `test_lambdas.py` event fixtures).
- [ ] **Step 2: Run; FAIL.** **Step 3: Implement** the branches (`if cfg.layout:` else existing code untouched). Zip extraction writes members to the upload dir with sanitized names and a per-member size cap taken from existing upload limits. **Step 4: PASS.**
- [ ] **Step 5: Commit** `feat(multifile): file-set intake via upload, zip, scheduler, pull and S3`.

### Task 11: Join stage inside `run_batch`

**Files:**
- Modify: `backend/lbp/pipeline/batch.py` (`run_batch`), `backend/lbp/pipeline/preflight.py` (call per role and join pre-check), `backend/lbp/storage.py` only if a helper is needed
- Create: `backend/lbp/multifile/stage.py`
- Test: `backend/tests/test_multifile_run.py`

**Interfaces:**
- Consumes: `join_files` (Tasks 3-5), `batch_files` and `batches.file_set_id/joined_path/join_summary` (Task 6), `FeedConfig.layout` (Task 7).
- Produces: `materialize_join(batch_id: str, cfg: FeedConfig) -> dict` in `stage.py`. It joins once and stores `joined_path` (under `data_dir/joined/<batch_id>.csv`; S3 in AWS via existing `storage` helpers), `join_summary` (`per_role`, `exception_counts`, match rates, `layout_version`), inserts join exceptions into `exceptions` (`rule_id=JOINxx`, `category="join"`, `role`, `blocking` true for JOIN02-04/06 and false for JOIN01, `queue="join"` using existing exception routing conventions), and returns `{"status": "ok" | "blocked", ...}`. `run_batch` calls it before pre-flight when `b.file_set_id` is set and then reads `joined_path` (CSV, header row, UTF-8) in place of `file_path`. If `blocked` the batch is set `blocked` with the message and is resumable through the existing `override_preflight`.

- [ ] **Step 1: Tests:** `test_run_joined_batch_loads_merged_and_aggregated_fields` (master + details through `attach_file`, `run_batch`, then the loan rows contain a column mapped from `details.col` and an aggregate); `test_orphan_exceptions_created_and_pii_masked` (Review Focus 4: raw payload of a JOIN01 exception masks columns flagged PII by profile/mapping per role); `test_low_match_rate_blocks_before_any_load_and_override_resumes`; `test_resume_reuses_same_joined_file` (Review Focus 2: kill the run after the first micro-batch, mutate nothing, rerun; assert `joined_path` unchanged, file sha256 unchanged, no duplicate loans, counters complete); `test_preflight_runs_per_role` (a dropped required detail column blocks with the role named); `test_legacy_batch_never_touches_multifile_code` (monkeypatch `materialize_join` to raise; a legacy batch still completes); `test_reconciliation_reports_per_role_counts`.
- [ ] **Step 2: Run; FAIL.** **Step 3: Implement.** Use `check_file` on the joined file for drift against the feed's mapping, plus a per-role header check against the layout's declared columns. Keep the checkpoint logic untouched (it indexes joined-file rows, which equal master order).
- [ ] **Step 4: PASS.**
- [ ] **Step 5: Commit** `feat(multifile): run joined file sets through the pipeline`.

### Task 12: File-set overrides

**Files:**
- Modify: `backend/lbp/multifile/fileset.py`, `backend/lbp/api/main.py`
- Test: `backend/tests/test_multifile_overrides.py`

**Interfaces:**
- Produces: `override_set(set_id: str, action: Literal["accept_partial","discard","repair"], actor: str, roles: list[str], reason: str, target_pairing_key: str | None = None) -> dict`; `GET /api/file-sets?source_id=&status=`; `POST /api/file-sets/{id}/override`. Roles `onboarding_reviewer`, `compliance_reviewer`, `admin`; reason required; audited `fileset.override`. `accept_partial` queues a batch with the present roles (details missing follow `on_missing_detail`), only for `waiting`/`expired` sets; `discard` sets `discarded`; `repair` moves a member to another waiting set (`target_pairing_key`) only before the batch is queued.

- [ ] **Step 1: Tests:** `test_override_requires_reason_and_role`; `test_accept_partial_loads_with_missing_detail_policy_and_audits`; `test_discard_waiting_set`; `test_repair_moves_member_before_batch_only`; `test_override_after_batch_queued_rejected`.
- [ ] **Step 2: Run; FAIL.** **Step 3: Implement.** **Step 4: PASS.**
- [ ] **Step 5: Commit** `feat(multifile): set overrides`.

### Task 13: Join preview

**Files:**
- Modify: `backend/lbp/multifile/service.py`, `backend/lbp/api/main.py`
- Test: `backend/tests/test_multifile_preview.py`

**Interfaces:**
- Consumes: `join_files` (Tasks 3-5), `read_bytes_sample` from the parser.
- Produces: `preview_join(layout: dict, readiness: dict | None, samples: dict[str, tuple[bytes, str]], parse_options: dict[str, dict], n: int = 10) -> dict` returning `{"columns", "rows" (first n, PII values masked), "per_role", "exception_counts", "master_match_rate", "detail_match_rate", "blocked", "errors": [...]}`; `POST /api/sources/{id}/layout/preview` (multipart: one file per role). Samples are capped (first 2,000 master rows; details filtered to those keys plus up to 2,000 orphans) so preview is fast; nothing is persisted.

- [ ] **Step 1: Tests:** `test_preview_reports_match_rate_and_masked_rows`; `test_preview_invalid_layout_returns_errors_not_500`; `test_preview_does_not_write_db_or_files_outside_tmp`.
- [ ] **Step 2: Run; FAIL.** **Step 3: Implement** with a temp directory. **Step 4: PASS.**
- [ ] **Step 5: Commit** `feat(multifile): join preview`.

### Task 14: Web app

**Files:**
- Create: `frontend/src/pages/FeedLayout.jsx`, `frontend/src/layoutModel.js`, `frontend/src/layoutModel.test.js`
- Modify: `frontend/src/api.js`, `frontend/src/pages/FeedConfig.jsx` (tab/link), `frontend/src/pages/Imports.jsx` and `frontend/src/pages/Deliveries.jsx` (waiting file sets, per-role counts), the mapping screen under `frontend/src/pages/Sources.jsx` (columns grouped by role), `frontend/src/mock/*` (demo snapshot additions)
- Test: `frontend/src/layoutModel.test.js` (run with `npm test`)

**Interfaces:**
- Produces in `layoutModel.js` (pure, unit-tested): `emptyLayout(): object`; `addDetail(layout, role): object`; `validateLayoutForm(layout, readiness): string[]` (client-side mirror of required checks: one master, keys present, aggregate `as` unique); `groupColumnsByRole(columns: string[]): {role: string, columns: string[]}[]` (plain names under `master`, `role.col` grouped by prefix); `setStatusLabel(set): string` ("Waiting for borrowers file", "Ready", ...); `matchRateBadge(rate, threshold): "ok" | "warn" | "block"`.
- API client: `getLayout(sourceId)`, `proposeLayout(sourceId, layout, readiness)`, `decideLayout(sourceId, approve, comment)`, `previewJoin(sourceId, layout, readiness, filesByRole)`, `listFileSets(params)`, `overrideFileSet(id, action, reason, targetKey)`, `uploadSet(sourceId, filesByRole)`.
- UI: layout editor (files with name pattern/key/required/parse options, relations with mode/policies, readiness policy), sample upload per role feeding the preview panel (match rate badge, orphan/missing counts, first 10 joined rows), maker-checker banner like the delivery profile page; file-set status chips in Import Monitor and Vendor Deliveries; mapping source picker grouped by role; exceptions list shows the role.

- [ ] **Step 1: Write failing tests** in `layoutModel.test.js` for each pure function above, including `groupColumnsByRole(["loan_id","details.fee","details.type"])` returning master then `details` groups, and `validateLayoutForm` rejecting zero or two masters.
- [ ] **Step 2: Run** `cd frontend && npm test`; FAIL. **Step 3: Implement** `layoutModel.js`, then the pages following `DeliveryProfile.jsx` for form/maker-checker patterns and `ui.jsx` components. **Step 4:** `npm test && npm run lint && npm run build` pass; open the app (backend on :8000, Vite on :5173), load a feed with a layout (Task 15 demo), and verify the editor, preview, waiting-set chip and grouped mapping by eye.
- [ ] **Step 5: Commit** `feat(multifile): web app layout editor, preview and file-set status`.

### Task 15: End-to-end test, demo scenario and docs

**Files:**
- Create: `backend/tests/test_multifile_e2e.py`, `backend/tests/test_join_scale.py`, `docs/MULTI_FILE_FEEDS.md`
- Modify: `backend/lbp/samples.py` (`generate_master_detail(dir, n) -> dict[str, Path]`), `backend/lbp/demo_setup.py` (one master/detail demo feed), `README.md` and `docs/ARCHITECTURE.md` (links), `backend/pyproject.toml` (register the `slow` marker if missing)

**Interfaces:**
- Consumes: everything above.
- Produces: `generate_master_detail(dir: Path, n: int) -> {"master": Path, "details": Path}` with the master in the SSE-style columns the existing demo feeds use and a 1:N fees-like detail (about 3 rows per master, a few orphans, a few masters without details, key format noise).

- [ ] **Step 1: Tests:** `test_e2e_master_then_detail_loads_joined_loans` (create a feed with approved mapping + layout through the service, upload master (assert `waiting`, no batch), upload detail (assert batch created and runs to `completed`; loan count equals master count; aggregate field correct; orphan exceptions present; `/api/batches` shows per-role counts); `test_e2e_timeout_alert_then_override_accept_partial`; `test_e2e_legacy_feed_regression` (existing sample flow still passes unchanged); `test_join_scale` with `@pytest.mark.slow`: 10,000,000 detail rows against 1,000,000 masters joins within a generous bound while peak RSS stays under 1 GB (measure with `resource.getrusage`); skipped unless `-m slow`.
- [ ] **Step 2: Run; FAIL.** **Step 3: Implement** sample generator, demo feed wiring and docs (`MULTI_FILE_FEEDS.md`: concepts, layout/readiness reference with the spec's example, how to onboard a master/detail vendor, delivery scenarios, troubleshooting by exception code).
- [ ] **Step 4: Run the full suite:** `cd backend && .venv/bin/python -m pytest -q` and `ruff check .`, then `cd ../frontend && npm test && npm run lint && npm run build`; all PASS. Run `pytest -m slow tests/test_join_scale.py` once and record the timing in the commit message.
- [ ] **Step 5: Commit** `feat(multifile): end-to-end tests, demo scenario and docs`.

---

## Self-review notes

- **Spec coverage (Phase 1 scope):** layout model (T1), key normalization (T2), merge + aggregate (T3-4), data problems and match rate (T5), schema/migration (T6), signed bundle (T7), maker-checker (T8), file sets/pairing/readiness/timeouts (T9), all intake paths (T10), join in the pipeline + per-role pre-flight + PII masking + resume (T11), overrides (T12), preview (T13), UI (T14), demo/docs/scale (T15). Phases 2-5 are explicitly out of this plan.
- **Spec item deferred by design:** `mappings` keyed by entity beyond `loan` (Phase 3); the bundle gets the `mappings` key for layout feeds now so Phase 3 extends rather than changes the format.
- **Type consistency:** `join_files` / `JoinResult` / `RoleStats` (T3) are used unchanged by T4, T5, T11, T13; `attach_file` / `create_batch_for_set` (T9) are the only intake entry points used by T10 and T12; `FeedConfig.layout/readiness` (T7) feed T9 and T11.
