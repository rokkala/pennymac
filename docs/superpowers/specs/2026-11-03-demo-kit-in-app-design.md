# Demo kit in the application

**Date:** 2026-11-03  
**Status:** approved — implemented  
**Classification:** architectural

## Intent

Put the **demo-kit sales scenario** into the running Loan Boarding Platform so a presenter can walk `DEMO_GUIDE.md` without hand-assembling state.

**Success criteria**

- `start_demo.sh` (or equivalent) boots the app into the kit scenario.
- An in-app **admin** action can load/reload the same scenario while the server runs.
- Default scale is **compact** (same story beats, fewer rows); **full** scale is opt-in for sales demos.
- Existing data is **not wiped** unless the operator confirms (`force`) or the script passes `--force`.
- Demo paths stay behind `enable_demo` / local only — never available when production fail-safes apply.

**Non-goals**

- Replacing Cognito / production onboarding.
- Perfect byte-identity with every historical snapshot export.
- Shipping a multi-GB prebuilt DB image as the primary path.
- Changing the offline `npm run build:demo` mock unless it falls out naturally from shared setup.

## Decisions already locked

| Decision | Choice |
|---|---|
| Entry points | **Both** — startup script + in-app reload |
| Existing data | **C** — refuse by default; wipe only after confirm / `--force` |
| Scale | **C** — compact default in-app; full via script / flag |
| Architecture approach | **1** — shared setup module + extend demo API surface |

## Current state (facts)

- Thin seed today: `POST /api/demo/seed` → `samples.generate_all` → register/approve/board four sources (`backend/lbp/api/main.py`).
- Richer programmatic scenario already lives in `backend/scripts/export_demo_snapshot.py` (vendors, day-2 boards, exception activity, R015 canary, schedules, etc.) but is export-only.
- Kit assets exist under `demo-kit/demo_kit/` (nested) with `MANIFEST.csv`, `files/1_preloaded`, `files/2_upload_live`, `DEMO_GUIDE.md`, `start_demo.sh`.
- **`backend/scripts/demo_setup.py` is missing**; `start_demo.sh` will fail as written.
- Kit paths assume repo-root `demo_kit/` beside `backend/` / `frontend/`.
- No frontend UI currently calls demo seed.

## Design

### 1. Kit layout

Canonical path: **`demo_kit/`** at the repo root (un-nest `demo-kit/demo_kit/` → `demo_kit/`).

Resolver (shared helper): look for kit in order:

1. `LBP_DEMO_KIT` env (absolute or relative)
2. `<repo>/demo_kit`
3. `<repo>/demo-kit/demo_kit` (compat while migrating)

`MANIFEST.csv` remains the inventory of preloaded vs upload-live files. Setup **reads** the manifest; it does not invent filenames.

### 2. Shared module: `backend/lbp/demo_setup.py`

Single builder used by API, CLI, and scripts.

```text
run_demo_setup(*, data_dir, kit_dir, scale="compact"|"full", force=False) -> SetupResult
```

**Behaviour**

1. If DB/data already has sources (or SSE loans) and `force` is false → raise `DemoSetupConflict` (mapped to HTTP 409).
2. If `force` → wipe `data_dir` contents the platform owns (SQLite DB, uploads, samples, config pubs under that dir) and re-init schema / defaults the same way lifespan/migrate does locally.
3. Build scenario:
   - Prefer **kit files** from `1_preloaded` when present and listed in the manifest.
   - Where a beat needs generated content (e.g. large row counts, defects), use `lbp.samples` writers with seeds — same patterns as `export_demo_snapshot.py`.
   - Compact vs full: scale row counts and optional secondary day boards; **do not drop** vendors, feeds, sequence-gap, drift, Westside draft, or canary beats.
4. Return a structured result: vendors created, batches, exception tier counts, scale, duration, kit path used.

**Refactor note:** Extract the scenario orchestration currently embedded in `export_demo_snapshot.py` into this module (or call it from the exporter) so export and live setup do not diverge. Keep the exporter as a thin “run setup → hit APIs → write snapshot.json”.

**Scales (initial targets — tune in implementation, document in DEMO_GUIDE)**

| Beat | Compact | Full |
|---|---|---|
| Primary tape rows / feed | ~200–400 | ~3000 (manifest) |
| Day-2 / secondary boards | yes, smaller | yes, per guide |
| Change-file / drift / duplex files | use kit files as-is | use kit files as-is |
| Wall time (local, heuristic AI) | under ~1–2 min goal | ~3 min as guide states |

### 3. API

Keep `POST /api/demo/seed` for the **simple** four-source path (unchanged contract).

Add:

```http
POST /api/demo/setup
Authorization / X-User + X-Roles: admin (same ROUTE_ROLES gate as seed)
Body JSON: { "force": false, "scale": "compact" }
```

| Condition | Response |
|---|---|
| `enable_demo` false | 404 |
| Non-admin | 403 |
| Data present, `force` false | **409** `{ "code": "demo_data_exists", "message": "...", "hint": "pass force=true after confirm" }` |
| Success | 200 `SetupResult` |
| Missing kit when required files absent | 500/400 with clear message (do not silent-fallback to empty) |

Optional query/body later: `async=true` + job poll — **out of v1** unless wall time forces it; v1 may run synchronously with a long client timeout and a UI busy state.

Expose on `GET /api/config` (already has `demo: bool`):

```json
"demo_setup": { "available": true, "scales": ["compact", "full"], "default_scale": "compact" }
```

so the UI only shows the control when the server supports it.

### 4. CLI and `start_demo.sh`

- `python -m lbp.cli demo-setup [--data-dir PATH] [--kit PATH] [--scale compact|full] [--force]`
- Thin wrapper `backend/scripts/demo_setup.py` that calls the module (keeps guide commands working).
- Fix `demo_kit/start_demo.sh`:
  - `cd` to **repo root** (parent of `demo_kit/`), not the hyphenated nest.
  - Use backend venv/`python3.11+` consistently.
  - Flags: `--keep` (reuse data dir), `--force` (wipe), `--full` (scale=full). Default: wipe data dir unless `--keep`, then setup compact unless `--full`, then `uvicorn` with `LBP_DATA_DIR` and `LBP_SCHEDULER_ENABLED=false`.

### 5. UI

Surface only when `config.demo === true` and caller is **Platform Admin** (or roles include `admin`).

**Placement:** Policy & Audit page footer/actions (governance / lab controls), with a secondary link from Overview for discoverability — one shared modal component.

**Flow**

1. Button: “Load demo scenario…”
2. Modal: explain wipe; scale select (default Compact); primary disabled until “Wipe existing data and load” checkbox checked **if** server previously returned 409 or a cheap `GET`/probe says data exists. Simpler v1: always require checkbox + call with `force: false` first; on 409, show confirm and retry with `force: true`.
3. Busy state (no fake progress bar required in v1).
4. On success: toast with summary + `window.location.reload()` (or bump app nonce).

Do **not** show this control for non-admin personas used in the talk track (Priya/Dan/…).

### 6. Security and production

- All new routes gated by existing `enable_demo` and `ROUTE_ROLES` (admin for setup, same as seed).
- `Settings.validate_for_production` already refuses `enable_demo` outside local — no change required beyond ensuring setup cannot run if seed cannot.
- Kit paths are read-only inputs; never accept arbitrary upload paths from the client (server resolves kit dir).

### 7. Testing

- Unit/integration: `demo_setup` compact + `force` false → 409 when sources exist; `force` true rebuilds.
- One test that kit resolver finds fixtures (temp dir with minimal MANIFEST + one file) OR skip-if-no-kit marker for full kit.
- API test via TestClient mirroring seed tests.
- Manual: start_demo.sh smoke + UI modal once.

### 8. Docs

- Update `demo_kit/DEMO_GUIDE.md` paths and “how to start”.
- Short note in root `README.md` under “Run it locally” pointing at kit + in-app reload.
- After implementation: `graphify update .` so the new module is in the graph.

## Data flow

```text
start_demo.sh ──┐
lbp.cli demo-setup ──┼──► lbp.demo_setup.run_demo_setup ──► vendors / mappings / batches / rules / schedules
POST /api/demo/setup ──┘              │
                                      ├── reads demo_kit (MANIFEST + files)
                                      └── uses lbp.samples where generation needed

UI (admin) ──► POST /api/demo/setup {force, scale} ──► toast + reload
```

## Open points (resolve during implementation, not blockers)

- Exact compact row numbers vs wall-clock on the demo laptop.
- Whether wipe deletes only SQLite or the entire `LBP_DATA_DIR` tree (prefer entire managed data dir for determinism).
- Whether `export_demo_snapshot.py` should call `run_demo_setup` in the same PR or a fast follow — **prefer same PR** if the extract is clean; otherwise leave a `ponytail:` comment and a follow-up.

## Out of scope for this change

- Playwright E2E of the 25-minute talk track.
- Auto-running setup on every API boot without an explicit script/button.
- AWS/Glue live demo packaging.
