# Feed Lifecycle and Multi-File Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Let a user create a multi-file feed from the UI by uploading sample files (master + details), defining the layout, and getting a draft mapping drafted from the joined columns. (2) Let users archive/restore feeds, discard draft mapping versions, and permanently delete never-used feeds.

**Architecture:** (1) A new onboarding service profiles every sample file, runs the existing join on capped samples to produce one joined sample CSV, registers the feed from that CSV with the existing `register_source` (so the mapping is drafted from the joined columns), then proposes the layout through the existing maker-checker `propose_layout`. The existing layout editor is split into a reusable controlled `LayoutEditor` that the new "Add feed → several files" modal also uses. (2) Archive is a status (`sources.status = "retired"`) plus audit columns; guards and filters are added where feeds are listed or receive files. Mapping discard is a new mapping status `discarded`. Permanent delete is admin-only and only for feeds with no history.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy / Alembic (SQLite + PostgreSQL), React + Vite, node:test, pytest.

**Spec:** This document's "Approved design" section (design agreed with the owner in conversation 2026-11-18). Builds on `docs/superpowers/specs/2026-11-17-multi-file-feeds-design.md` and `docs/MULTI_FILE_FEEDS.md`.

## Approved design (owner-confirmed 2026-11-18)

- **Onboarding:** "Add feed" gets a choice "One file" / "Several files". Several files: one sample per role (master + detail roles), layout defined in the same editor used on the File layout tab, a "Check the join" preview, then "Create feed and draft mapping". The mapping is drafted from the joined sample's columns (master columns, aggregate outputs, `role.column` merge columns). The layout is created as a maker-checker proposal (a second approver publishes it) exactly like today.
- **Archive, not hard delete** for anything that has history. Feed: Archive (reason required) / Restore. Archived feed disappears from lists, accepts no new files (upload, zip set, S3 arrival, scheduled pull all refuse), its schedules are paused. Refused while a batch is in progress or a file set is waiting/ready. Mapping version: Discard (reason required) only for `draft` or `rejected`. Permanent delete only by `admin`, only for a feed with no batches, file sets, loans, or exceptions.
- **Who:** archive/restore/discard: `onboarding`, `onboarding_reviewer`, `admin`; a feed with an approved mapping (status `live`) needs `onboarding_reviewer` or `admin`. Permanent delete: `admin`.

## Global Constraints

- Branch: `feature/feed-lifecycle-multifile-onboarding` (cut from `feature/multi-file-feeds`). Commit per task; commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Run Python via `arch -arm64 backend/.venv/bin/python -m pytest ...` from `backend/` (the venv is arm64; plain x86 invocation fails to import sqlalchemy).
- Known pre-existing failures that are NOT yours: `tests/test_analytics.py::test_batches_days_with_aware_until_does_not_500`, two in `tests/test_bulk_load_fixes.py` (`test_prepare_large_unknown_batch_raises`, `test_begin_bulk_unknown_batch_raises`). Everything else must stay green. Frontend: `cd frontend && npm test && npm run lint` must stay 75+/0 failures, lint clean.
- DB changes only via a new Alembic revision `0008_feed_lifecycle` (down_revision `0007_multifile`) plus `backend/lbp/store/db.py`; must work on SQLite and PostgreSQL, upgrade and downgrade (follow `backend/migrations/versions/0007_multifile.py` and its test).
- Every state change writes `db.audit(c, actor, "<event>", "source"|"mapping", id, {...})`. Reasons are required (min 5 chars) for archive, restore, discard, delete.
- API role gating is the table at the top of `backend/lbp/api/main.py` (`("POST", "/api/...")` → roles). New routes MUST be added there. Error mapping uses the existing `_err(e)` helper.
- Frontend capability gating is `canCap(persona, "<cap>")`; add new caps next to `editVendors`/`editDelivery`. Reason prompts use the existing `useDialog` `kind: "reason"` pattern (see `FeedLayout.jsx` `decide`).
- Do not touch the Glue/Spark path. Do not change behavior for single-file feeds.
- Public copy: plain language, no jargon; match the tone of existing UI strings.

## Review Focus

- Archiving a feed that is mid-load or whose file set is waiting/ready: refused with a clear message; nothing partially archived.
- Any intake path to an archived feed (upload, `/api/upload/set`, S3 arrival, scheduled pull, `pull-now`): refused with 409 (HTTP) or a recorded rejection, never silently accepted or queued.
- Multi-file onboarding with a wrong key, zero matching rows, a missing master, a duplicate role, a non-CSV/empty file, or an unreadable file: clear error and NO source/mapping row left behind.
- Detail columns with spaces or dots; two roles sharing a column name; header-only detail file.
- Discarding the only draft then creating a new version; restoring an archived feed whose name a newer feed of the same vendor now uses; permanent delete of a feed that has any history (must refuse).

---

### Task 1: Feed archive/restore, mapping discard, permanent delete (backend)

**Files:**
- Create: `backend/migrations/versions/0008_feed_lifecycle.py`, `backend/lbp/lifecycle.py`, `backend/tests/test_feed_lifecycle.py`
- Modify: `backend/lbp/store/db.py` (sources: `retired_at DateTime`, `retired_by String(80)`, `retired_reason Text`, `retired_from_status String(20)`; mappings.status comment adds `discarded`), `backend/lbp/api/main.py`, `backend/lbp/mapping/service.py` (`new_version` base), `backend/lbp/vendors.py` (summaries), `backend/lbp/scheduling/service.py`, `backend/lbp/multifile/fileset.py`, `backend/lbp/analytics/service.py` (only if it lists feeds), `aws/lambdas/handlers.py` (S3 arrival)
- Test: `backend/tests/test_feed_lifecycle.py`

**Interfaces:**
- Produces (`backend/lbp/lifecycle.py`):
  - `class LifecycleError(ValueError)`; `class FeedArchivedError(LifecycleError)` (HTTP 409)
  - `archive_feed(source_id: str, actor: str, roles: list[str], reason: str) -> dict`
  - `restore_feed(source_id: str, actor: str, roles: list[str], reason: str) -> dict`
  - `discard_mapping(mapping_id: str, actor: str, roles: list[str], reason: str) -> dict`
  - `delete_feed(source_id: str, actor: str, roles: list[str], reason: str) -> dict`
  - `assert_not_archived(source_id: str) -> None` (raises `FeedArchivedError`; call at every intake path)
- Routes (all in the role table): `POST /api/sources/{source_id}/archive` and `/restore` (body `{reason}`; roles `onboarding`, `onboarding_reviewer`, `admin`, with the `live`-feed reviewer rule enforced in the service), `POST /api/mappings/{mapping_id}/discard` (same roles), `DELETE /api/sources/{source_id}?reason=` (`admin`).
- `GET /api/sources` gains `include_archived: bool = False`; rows carry `status`, `retired_at`, `retired_reason`; archived feeds are excluded unless requested. `GET /api/vendors` summaries: archived feeds are not counted in `feeds`/`live_feeds`; add `archived_feeds` count.

- [ ] **Step 1: Write failing tests** in `backend/tests/test_feed_lifecycle.py` (use the same fixtures/helpers other API tests use; create feeds with `mapping_svc.register_source` on a sample CSV): `test_archive_hides_feed_and_pauses_schedule`, `test_archive_refused_while_batch_in_progress`, `test_archive_refused_while_fileset_waiting`, `test_archive_requires_reason_min_5`, `test_live_feed_archive_needs_reviewer_role` (role `onboarding` gets `LifecycleError`, `onboarding_reviewer` succeeds), `test_restore_returns_previous_status_and_unarchives`, `test_restore_name_clash_refused`, `test_upload_to_archived_feed_409`, `test_zip_set_upload_to_archived_feed_409`, `test_scheduler_tick_skips_archived_feed`, `test_pull_now_archived_409`, `test_attach_file_archived_rejected` (`fileset.attach_file` / `route_file` raises `FeedArchivedError`), `test_discard_draft_ok_approved_refused_in_review_refused`, `test_new_version_after_discarding_only_draft_uses_last_non_discarded_or_errors_clearly`, `test_delete_feed_admin_only`, `test_delete_feed_with_batch_refused`, `test_delete_never_used_feed_removes_mappings_schedules_and_keeps_audit`, `test_list_sources_default_excludes_archived_and_flag_includes`, `test_vendor_summary_excludes_archived`, `test_migration_0008_roundtrip` (follow the 0007 test).
- [ ] **Step 2: Run, verify they fail** (`arch -arm64 .venv/bin/python -m pytest tests/test_feed_lifecycle.py -q` → import/attribute errors).
- [ ] **Step 3: Implement** the migration + `db.py` columns, `lifecycle.py`, the four routes, `include_archived`, vendor summary counts, scheduler skip, `assert_not_archived` calls at: `/api/upload`, `/api/upload/set`, `/api/schedules/{id}/pull-now`, `scheduling.service` pull, `multifile.fileset.route_file/attach_file`, S3 arrival in `aws/lambdas/handlers.py` (record as a rejection like other unroutable files). Archive effects: `status="retired"`, `retired_from_status` = prior status, `retired_at/by/reason`, all `delivery_schedules` of the source with status `active` → `paused`; call `config_store.publish_all(actor, reason)` as `move_feed` does. Busy set = batch statuses `running, claimed, pausing, waiting, queued, staged, paused` and file sets `waiting, ready`. `delete_feed` removes mappings, schedules, the source row only when there are no rows in `batches`, `file_sets`, `exceptions`, or `sse_loans` for it. `register_source` name-clash error should say "archived" when the clashing feed is retired. `mapping.service.new_version` bases the new draft on the latest non-`discarded` mapping (error "no mapping to base a new version on" if none).
- [ ] **Step 4: Run** the new tests plus `tests/test_multifile_*.py tests/test_scheduling*.py tests/test_vendors*.py -q`; all pass.
- [ ] **Step 5: Commit** `feat(lifecycle): archive/restore feeds, discard draft mappings, delete unused feeds`.

---

### Task 2: Feed lifecycle UI

**Files:**
- Modify: `frontend/src/pages/Vendors.jsx` (feed cards: Archive…; "Archived feeds (n)" section with Restore and Delete permanently…), `frontend/src/pages/Sources.jsx` (mapping header: "Discard this draft…" for `draft`/`rejected`), `frontend/src/api.js` (`archiveFeed`, `restoreFeed`, `discardMapping`, `deleteFeed`), the file defining `canCap` (new caps `archiveFeed`, `deleteFeed`), `frontend/src/mock/mockApi.js` only if the demo build needs the new endpoints.
- Test: `frontend/src/lifecycleModel.test.js` for any pure helper you add (e.g. `canArchive(persona, feed)` encoding the live-feed reviewer rule).

**Interfaces:**
- Consumes: Task 1 routes and `include_archived`.
- Produces: `api.js` functions `archiveFeed(sourceId, reason)`, `restoreFeed(sourceId, reason)`, `discardMapping(mappingId, reason)`, `deleteFeed(sourceId, reason)`; each returns the parsed JSON or throws like the other api helpers.

- [ ] **Step 1: Write failing node tests** for the pure helper(s): `canArchive` is true for `onboarding` on a non-live feed, false for `onboarding` on a `live` feed, true for `onboarding_reviewer`/`admin`; `canDelete` only for `admin` and only when the feed has no history flag.
- [ ] **Step 2: Run** `cd frontend && npm test` → the new tests fail.
- [ ] **Step 3: Implement** the helpers, api functions, caps, and UI: reason dialog via `useDialog` (`kind: "reason"`, `required: true`, `minLength: 5`); archived section loads `/api/sources?vendor_id=…&include_archived=true`; archived feeds show an "Archived" pill, reason, who/when; refusals from the server (409/400) surface through the existing `useAction` toast. Delete permanently shows a second confirm that says it cannot be undone.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build` → all pass. Restart is not required; verify in the running app at http://localhost:8000 only if a rebuilt bundle is served (`demo_kit/start_demo.sh` is how it is served; the implementer must not leave extra servers running).
- [ ] **Step 5: Commit** `feat(ui): archive/restore feeds, discard draft mappings, delete unused feeds`.

---

### Task 3: Multi-file feed onboarding (backend)

**Files:**
- Create: `backend/lbp/multifile/onboard.py`, `backend/tests/test_multifile_onboard.py`
- Modify: `backend/lbp/multifile/preview.py` (extract a reusable capped-sample join), `backend/lbp/multifile/service.py` (`known_columns`, `propose_layout`), `backend/lbp/api/main.py` (3 routes + role table)

**Interfaces:**
- Produces (`preview.py`): `build_joined_sample(layout: dict, readiness: dict | None, inputs: dict[str, Path], parse_options: dict[str, dict], out_dir: Path) -> tuple[Path, dict]` — runs the same sampling and `joiner.join_files` as `preview_join` and returns `(joined_csv_path, summary)` where `summary` has the per-role counts and match rates; `preview_join` keeps its behavior and is refactored to use it.
- Produces (`onboard.py`):
  - `class OnboardError(ValueError)`
  - `inspect_files(files: dict[str, tuple[bytes, str]]) -> dict[str, dict]` → `{role: {"columns": [...], "rows_sampled": int, "format": str}}` (no DB, no persistence)
  - `register_multifile_source(name: str, files: dict[str, Path], layout: dict, readiness: dict, actor: str, roles: list[str], description: str = "", vendor_id: str | None = None) -> dict` → same shape as `register_source` plus `"layout_draft"` and `"role_columns"`.
- `known_columns(profile)` in `service.py` returns `profile["role_columns"]` when present (else master columns as today). `register_multifile_source` stores `role_columns` ({role: [columns]}) in the source's `profile` JSON.
- Routes (role table: `EDIT_MAPPING`): `POST /api/multi-file-feeds/inspect` (multipart: one part per role, named by role → inspect_files), `POST /api/multi-file-feeds/preview` (multipart: role parts + `layout`, `readiness` JSON fields → `preview_join` with no source; same `errors`-as-200 contract as the existing preview), `POST /api/multi-file-feeds` (multipart: `name`, `description`, `vendor_id`, `layout`, `readiness`, role parts → `register_multifile_source`; errors → 400 via `_err`).

- [ ] **Step 1: Write failing tests** in `backend/tests/test_multifile_onboard.py` using `samples.generate_master_detail` and `samples.master_detail_layout()` / `master_detail_readiness()`: `test_inspect_returns_columns_per_role`, `test_register_creates_feed_mapping_and_pending_layout` (source exists, mapping v1 `draft`, `layout_draft` set, `layout` still null, mapping fields include the aggregate output `tax_total` and no unmapped crash), `test_register_then_full_flow_loads_a_set` (accept_all → submit → approve by a different user → `decide_layout` approve → `attach_file` master and details → `run_batch` → batch `completed`, `loaded > 0`, `join_summary` present), `test_wrong_key_no_rows_leaves_no_source_behind`, `test_missing_master_role_rejected`, `test_duplicate_role_rejected`, `test_empty_or_header_only_detail_clear_error`, `test_detail_columns_with_spaces_and_dots`, `test_same_column_name_in_two_roles`, `test_snapshot_or_incremental_delivery_not_possible_at_onboarding` (new feeds are `full`), `test_endpoints_role_gating` (analyst without EDIT_MAPPING gets 403), `test_preview_endpoint_without_source_masks_pii_like_existing_preview`.
- [ ] **Step 2: Run, verify failing.**
- [ ] **Step 3: Implement.** Order inside `register_multifile_source`: validate layout against each role's real columns (`validate_layout(layout, readiness, known)`), build the joined sample in a temp dir (so zero-match/wrong-key/duplicate-master problems raise `OnboardError` BEFORE any DB write), persist the joined CSV with `persist_upload(..., "samples")`, call `mapping_svc.register_source(name, joined_path, actor, description, vendor_id=vendor_id)`, set `profile["role_columns"]`, then `propose_layout(sid, layout, readiness, actor, roles)`. If anything after `register_source` fails, delete the created source/mapping rows (compensate) and re-raise. Joined-sample columns drive the mapping, so suggestions cover aggregate outputs and `role.column` names; verify the mapping engine accepts dotted names and fix there only if the full-flow test proves a defect.
- [ ] **Step 4: Run** `tests/test_multifile_*.py tests/test_join_*.py tests/test_feed_lifecycle.py -q` → pass (plus the Task 1 suite unchanged).
- [ ] **Step 5: Commit** `feat(multifile): create a multi-file feed and its draft mapping from sample files`.

---

### Task 4: Multi-file onboarding UI

**Files:**
- Modify: `frontend/src/pages/FeedLayout.jsx` (extract controlled `LayoutEditor`; `PreviewPanel` takes a `previewUrl` prop), `frontend/src/pages/Vendors.jsx` (`FeedModal` mode switch + several-files wizard), `frontend/src/api.js` (`inspectMultiFiles`, `previewMultiFiles`, `createMultiFileFeed`), `frontend/src/layoutModel.js` (`guessPattern`, `starterLayout`), `frontend/src/mock/mockApi.js` (only if the demo build needs it)
- Test: `frontend/src/layoutModel.test.js`

**Interfaces:**
- Consumes: Task 3 routes.
- Produces: `layoutModel.guessPattern(filename: string) -> string` (e.g. `loans_20261117.csv` → `loans_(?P<date>\\d{8})\\.csv`; a name without a date → an escaped exact-name regex); `layoutModel.starterLayout(roles: {role: string, filename: string, columns: string[]}[], masterRole: string) -> layout` (master with `required: true` and `key` guessed as the first column matching `/(^|_)id$/i` else first column; each detail role with a `name_pattern`, a left `many` relation to the master with `on` guessed from identical column names else empty, mode `merge`).
- `LayoutEditor` props: `{ layout, setLayout, ready, setReady, disabled, columnsByRole }` — it renders Files, How the files join, and readiness cards (extracted from `Editor` with no behavior change for the File layout tab).

- [ ] **Step 1: Write failing tests** in `layoutModel.test.js`: `guessPattern` for dated and undated names and for names with regex metacharacters; `starterLayout` picks `LoanID` as the master key, builds one relation per detail, and guesses `on` from a shared column name.
- [ ] **Step 2: Run** `npm test` → fail.
- [ ] **Step 3: Implement** the helpers, extract `LayoutEditor` (File layout tab must look and behave exactly as before), and the wizard: in `FeedModal`, a "One file / Several files" switch; "Several files": feed name, a master file picker, "+ Add a detail file" rows (role name + file picker), on each file selection call `inspectMultiFiles` and show the detected columns as chips under it; then the layout via `LayoutEditor` prefilled with `starterLayout`; a "Check the join" button (uses `previewMultiFiles`, shows the same counts/exception table as `PreviewPanel`); primary button "Create feed and draft mapping" calls `createMultiFileFeed` and on success calls `onCreated(mapping_id)` and shows "Feed created. The layout needs a second person's approval before files use it." Disable create until the preview has run without errors.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build` → pass.
- [ ] **Step 5: Commit** `feat(ui): add a multi-file feed from sample files`.

---

### Task 5: Docs, demo and end-to-end check

**Files:**
- Modify: `docs/MULTI_FILE_FEEDS.md` (onboarding walkthrough replaces "propose after creating a single-file feed"; add an "Archiving and deleting" section covering archive/restore/discard/delete, who can do what, what an archived feed refuses), `README.md` feature table row, `docs/ARCHITECTURE.md` only if it lists the API groups, `demo_kit/DEMO_GUIDE.md` (one short scenario: create a two-file feed in the UI, archive it)
- Create: `backend/tests/test_lifecycle_and_onboarding_e2e.py`

- [ ] **Step 1: Write the e2e test** that drives the HTTP API with `TestClient`: onboard a two-file feed via `POST /api/multi-file-feeds` as `onboarding`, approve mapping and layout as a reviewer, deliver both files with `/api/upload/set`, run the batch, archive the feed as reviewer, assert a further upload is 409 and `GET /api/sources` hides it, restore, assert upload accepted again.
- [ ] **Step 2: Run, make it pass** (fix real defects found in Tasks 1–4 as small commits; do not weaken assertions).
- [ ] **Step 3: Update the docs** listed above.
- [ ] **Step 4: Run the full suite**: backend `arch -arm64 .venv/bin/python -m pytest -q` (only the 3 known failures may remain), frontend `npm test && npm run lint && npm run build`.
- [ ] **Step 5: Commit** `docs+test: lifecycle and multi-file onboarding end to end`.
