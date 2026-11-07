# ETL Monitor (fleet ops console)

**Date:** 2026-11-07  
**Status:** approved  
**Classification:** architectural  
**Related:** `2026-11-05-overview-load-desk-design.md` (Overview stays the *today* attention desk; this spec adds durable fleet history + infra steps)

## Intent

Give Monitoring ops an ETL-style console: **what’s running** (progress, ETA, pipeline steps), **what happened** (searchable history), and **drill into a batch to act** — without inventing a second batch detail UI or renaming the Monitoring persona.

## Locked decisions

| Decision | Choice |
|---|---|
| Primary ops console | New Run page **`monitor`** labeled **Monitor** (not “Monitoring”) |
| Batch actions / workbench | Existing **File loads** (`imports`) + shared **`BatchModal`** |
| Today’s attention | **Overview** unchanged in role; optional “See all on Monitor” link from attention |
| Infra visibility | Step Functions / Glue **step pills** via existing `pipeline/trace` on batch payloads |
| API shape | Extend `GET /api/batches` / `import_status()` — **no** `/api/monitor` |
| Access | Same as File loads: `monitoring`, `monitoring_reviewer`, `admin` |
| Real-time | HTTP poll (~2s), same as File loads today — no websockets in v1 |

## Screen ownership

Run rail order: `Overview` → **`Monitor`** → `File loads` → `Exceptions` → `Analytics`

| Screen | Owns | Does not own |
|---|---|---|
| Overview | Today’s late / stuck / queues | Full history, date-range archaeology |
| Monitor | Live fleet progress, history filters, KPIs, pipeline step pills | Upload/remap/preflight/pause UI (opens BatchModal) |
| File loads | Upload + BatchModal workbench | Fleet history console |
| Deliveries | Schedules / pull windows | Row-level boarding progress |
| Maintenance → Jobs | Glue *code* artifacts | Live run status |

## Monitor layout

1. **PageHeader** — eyebrow `Run`, title `Monitor`, sub: live loads, history, and pipeline steps; open a batch to act. Primary: **Upload file** (reuse Imports upload modal). Secondary text link to File loads.
2. **KPI strip (4)** — batches running; current throughput vs target; attention count (failed + blocked + waiting + paused + out_of_order in range); completed in selected range (with loan count).
3. **Live zone** — only when any `queued` / `running` / `pausing` / `paused` exist. Dense rows: file, vendor·feed, **progress bar** (`processed/total` + %), ETA, loans/s, pipeline step pills. Poll ~2s.
4. **History table** — other statuses (and live rows may appear only in Live, not duplicated). Filters: status (multi), vendor (existing scope chip), date range (Today / 7d / 30d / custom), search (`q` on filename or batch_id). Default range: **Today**, with attention statuses visually elevated.
5. **Row click** → shared `BatchModal` (same as Overview / File loads).
6. **Empty** — no rows in range → Upload / Deliveries / Guide. Live empty + history nonempty → omit Live section (no empty Live card).

## API

### `GET /api/batches` (extend)

Existing: `limit` (default 25), vendor scope.

Add:

| Param | Meaning |
|---|---|
| `status` | Comma-separated statuses |
| `days` | `1` \| `7` \| `30` (mutually preferred with since/until for UI presets) |
| `since` / `until` | ISO timestamps for custom range |
| `q` | Case-insensitive substring on `filename` or `batch_id` |
| `limit` | Default **50**, max **200** |

Response: keep `batches`, `running`, `current_throughput_lps`, `target_lps`; add **`attention`**: count of batches matching the same filters (status/date/q/vendor) whose status is in `failed`, `blocked`, `waiting`, `paused`, `out_of_order`, **before** applying `limit` (so the KPI is not capped by the page size).

Continue attaching `pipeline` via `fetch_traces` for returned batch ids.

Mock API (`frontend/src/mock/mockApi.js`) implements the same query params.

### Out of scope (v1)

- Websockets / SSE progress push  
- CloudWatch / Glue log tail  
- Deep links into AWS consoles beyond step summaries already in `pipeline`  
- Compliance roles on Monitor  
- Renaming the Monitoring persona  
- Second batch detail page  

## Frontend touchpoints

- `navModel.js` — insert `monitor` in Run after `overview`
- `App.jsx` — register page; include in `RUN_PAGES`
- `screenCopy.js` — label/sub for Monitor; lightly refresh File loads sub if it still reads as the fleet console
- `backend/lbp/personas.py` `DEFAULT_ACCESS` + frontend mock matrix — `monitor` like `imports`
- New `frontend/src/pages/Monitor.jsx`
- Export / share `BatchModal` + `UploadModal` from `Imports.jsx` (or a tiny shared module if export is awkward — prefer export from Imports to avoid drive-by refactors)
- Overview: optional link to Monitor from attention / health strip
- How-it-works / guide copy only if a step already points at File loads for “watch progress” — point at Monitor for fleet, File loads for upload/actions
- Tests: nav visibility, `import_status` filters, Monitor filter→request wiring (smallest assert-based / existing test style)

## Error handling

- Trace fetch failures stay soft (batch list still returns; missing `pipeline` is OK — already the pattern).
- Invalid `since`/`until`/`days` → 400 with clear detail.
- `q` / filters never bypass vendor scope.

## Success criteria

1. Monitoring persona opens **Monitor** and sees live progress bars + history without hunting Overview or File loads.
2. Opening a run uses the **same** BatchModal actions as File loads (pause, preflight, replay, etc.).
3. History supports at least Today / 7d / 30d and status + filename search against extended `/api/batches`.
4. Pipeline step pills show when Step Functions history is available; local/demo without SF still shows row progress from DB counters.

## Supersedes (partial)

`2026-11-05-overview-load-desk-design.md` locked “monitoring lives on Overview only.” That remains true for **today’s attention**. **Fleet history + ETL progress console** now live on **Monitor**; Overview does not grow into a history browser.
