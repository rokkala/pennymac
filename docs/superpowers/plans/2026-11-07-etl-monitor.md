# ETL Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Run **Monitor** page (live progress + history + pipeline pills) that drills into the existing BatchModal, backed by filtered `GET /api/batches`.

**Architecture:** Extend `analytics.import_status` / `GET /api/batches` with status, date, and search filters plus an uncapped `attention` KPI. Register a new `monitor` screen with the same access as File loads. Build `Monitor.jsx` as a thin fleet UI that reuses `BatchModal` and `UploadModal` from Imports — no second detail surface.

**Tech Stack:** FastAPI + SQLAlchemy, React SPA (`useApi` poll), existing `.bar` / pipeline pills CSS, node:test + pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-etl-monitor-design.md`

## Global Constraints

- Page id **`monitor`**, rail label **Monitor** (never “Monitoring”).
- Access: `monitoring`, `monitoring_reviewer`, `admin` only (same as `imports`).
- No `/api/monitor` resource; extend `/api/batches` only.
- Reuse `BatchModal` for all actions; poll ~2s; no websockets / log tail in v1.
- `attention` statuses: `failed`, `blocked`, `waiting`, `paused`, `out_of_order` — count **before** `limit`.
- Live zone statuses: `queued`, `running`, `pausing`, `paused`.
- `limit` default **50**, max **200**.
- After code changes: `graphify update .`

## Review Focus

- Vendor-scoped `q` must not return another vendor’s batch — pin in Task 1.
- `attention` with `limit=1` still reports full matching attention count — pin in Task 1.
- Bad `days` / inverted `since`>`until` → HTTP 400 — pin in Task 2.
- Compliance persona’s visible screens exclude `monitor` — pin in Task 3.
- History empty + live empty shows EmptyState; live-only-empty omits Live section — pin in Task 4 helper / UI test.

## File map

| File | Responsibility |
|---|---|
| `backend/lbp/analytics/service.py` | Filter + `attention` in `import_status` |
| `backend/lbp/api/main.py` | Query params + validation on `list_batches` |
| `backend/tests/test_analytics.py` | Filter / attention / scope tests |
| `backend/tests/test_api.py` or analytics | 400 validation for bad params |
| `backend/lbp/personas.py` | `SCREENS` + `DEFAULT_ACCESS` for `monitor` |
| `backend/tests/test_personas.py` | Screen matrix / run-set assertions |
| `frontend/src/navModel.js` + `.test.js` | Run order: overview → monitor → imports → … |
| `frontend/src/screenCopy.js` + `.test.js` | Monitor + File loads copy |
| `frontend/src/App.jsx` | Register page + `RUN_PAGES` |
| `frontend/src/pages/Imports.jsx` | Export `UploadModal` |
| `frontend/src/pages/Monitor.jsx` | Live + History + filters |
| `frontend/src/monitorQuery.js` + `.test.js` | Pure: build query string + split live/history rows |
| `frontend/src/mock/mockApi.js` | Same query filters on GET batches |
| `frontend/src/pages/Overview.jsx` | Optional “See all on Monitor” control |

---

### Task 1: `import_status` filters + `attention`

**Files:**
- Modify: `backend/lbp/analytics/service.py` (`import_status`)
- Test: `backend/tests/test_analytics.py`

**Interfaces:**
- Consumes: existing `db.batches`, `_scope` caller supplies `source_ids`
- Produces: `import_status(limit: int = 50, source_ids: list[str] | None = None, *, statuses: list[str] | None = None, since=None, until=None, q: str | None = None) -> dict` with keys `batches`, `running`, `current_throughput_lps`, `target_lps`, **`attention`**

- [ ] **Step 1: Write failing tests**

```python
def test_import_status_filters_status_days_and_q(client, onboarded, sample_files):
    # create two batches; one completed, one leave failed or use status filter
    data = client.get("/api/batches?status=completed&days=30&limit=50").json()
    assert "attention" in data
    assert all(b["status"] == "completed" for b in data["batches"])

def test_attention_not_capped_by_limit(client, ...):
    # ensure ≥2 attention-status batches exist; GET limit=1
    data = client.get("/api/batches?limit=1&days=30").json()
    assert data["attention"] >= 2
    assert len(data["batches"]) == 1

def test_import_status_q_respects_vendor_scope(client, ...):
    # batch for vendor A; GET with vendor_id=B and q=filename of A → empty or 404 per existing scope rules
    ...
```

Use the same onboarded/sample fixtures as `test_import_status_includes_exception_counts_per_batch`. Prefer hitting `/api/batches` once Task 2 lands; until then call `import_status(...)` directly in-process if the route is not wired.

- [ ] **Step 2: Run tests — expect FAIL**

Run: `cd backend && python -m pytest tests/test_analytics.py -k "import_status_filters or attention_not_capped or q_respects" -v`

- [ ] **Step 3: Implement filters in `import_status`**

Apply `statuses` (IN), `since`/`until` on `created_at`, `q` ILIKE on `filename` or `batch_id`, clamp `limit` to 1..200. Compute `attention` with the same filters but `status IN ATTENTION` and **no** limit. Keep `fetch_traces` on returned rows only.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/lbp/analytics/service.py backend/tests/test_analytics.py
git commit -m "$(cat <<'EOF'
feat(batches): filter import_status and report uncapped attention

EOF
)"
```

---

### Task 2: Wire `GET /api/batches` query params

**Files:**
- Modify: `backend/lbp/api/main.py` (`list_batches`)
- Test: `backend/tests/test_analytics.py` or `backend/tests/test_api.py`

**Interfaces:**
- Consumes: Task 1 `import_status`
- Produces: `list_batches(limit=50, vendor_id=None, status: str | None = None, days: int | None = None, since: str | None = None, until: str | None = None, q: str | None = None)`

- [ ] **Step 1: Write failing validation tests**

```python
def test_batches_bad_days_returns_400(client):
    assert client.get("/api/batches?days=99").status_code == 400

def test_batches_since_after_until_returns_400(client):
    assert client.get("/api/batches?since=2026-11-07T00:00:00Z&until=2026-11-01T00:00:00Z").status_code == 400
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement parsing**

- `status` → split on commas, strip, drop empties  
- `days` in `{1,7,30}` → set `since = now - days`  
- parse ISO `since`/`until`; reject inverted range  
- `limit` default 50, max 200 (FastAPI `Query`)  
- pass into `import_status`; keep `_scope(vendor_id)`

- [ ] **Step 4: Run Task 1 HTTP tests + validation — PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/lbp/api/main.py backend/tests/test_analytics.py backend/tests/test_api.py
git commit -m "$(cat <<'EOF'
feat(api): expose batch history filters on GET /api/batches

EOF
)"
```

---

### Task 3: Nav, personas, screen copy

**Files:**
- Modify: `backend/lbp/personas.py` (`SCREENS`, `DEFAULT_ACCESS`)
- Modify: `backend/tests/test_personas.py` (run-set includes `monitor`; onboarding disjoint)
- Modify: `frontend/src/navModel.js`, `navModel.test.js`
- Modify: `frontend/src/screenCopy.js`, `screenCopy.test.js`
- Modify: `frontend/src/App.jsx` (import Monitor page stub OK if Task 4 not done — prefer register real page in Task 4; this task can add copy/nav/personas first and a placeholder component, **or** fold App registration into Task 4; **decision: personas + nav + copy here; App.jsx page registration in Task 4**)
- Modify: `frontend/src/mock/mockApi.js` access matrix + screen list labels

**Interfaces:**
- Produces: `monitor` in `SCREENS` / `DEFAULT_ACCESS` / `NAV_GROUPS` run pages / `SCREEN.monitor`

- [ ] **Step 1: Failing frontend + persona tests**

```js
// navModel.test.js
assert.deepEqual(NAV_GROUPS.find((g) => g.id === "run").pages,
  ["overview", "monitor", "imports", "exceptions", "analytics"]);

// screenCopy.test.js
assert.equal(SCREEN.monitor.label, "Monitor");
```

```python
# test_personas.py — update run set
run = {"overview", "monitor", "imports", "exceptions", "analytics"}
assert "monitor" in visible_screens(["monitoring"])
assert "monitor" not in visible_screens(["compliance"])
```

- [ ] **Step 2: Run — FAIL**

Frontend: `cd frontend && node --test src/navModel.test.js src/screenCopy.test.js`  
Backend: `cd backend && python -m pytest tests/test_personas.py -k "run_screens or default_matrix" -v`

- [ ] **Step 3: Implement labels/access/nav**

Exact copy from spec: title **Monitor**; sub *Live loads, history, and pipeline steps — open a batch to act.*  
File loads sub refresh to emphasize upload/workbench, e.g. *Upload a file or open a batch to pause, fix schema, or replay.*

- [ ] **Step 4: Tests PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/lbp/personas.py backend/tests/test_personas.py \
  frontend/src/navModel.js frontend/src/navModel.test.js \
  frontend/src/screenCopy.js frontend/src/screenCopy.test.js \
  frontend/src/mock/mockApi.js
git commit -m "$(cat <<'EOF'
feat(nav): add Monitor screen to Run rail and persona access

EOF
)"
```

---

### Task 4: `monitorQuery` helpers + `Monitor.jsx`

**Files:**
- Create: `frontend/src/monitorQuery.js`, `frontend/src/monitorQuery.test.js`
- Create: `frontend/src/pages/Monitor.jsx`
- Modify: `frontend/src/pages/Imports.jsx` — `export function UploadModal`
- Modify: `frontend/src/App.jsx` — import Monitor, add to `PAGES`, add `monitor` to `RUN_PAGES`

**Interfaces:**
- Consumes: `BatchModal`, `UploadModal` from Imports; `scoped` + `useApi`; Task 2 query params
- Produces:
  - `buildBatchesPath({ days, status, q, limit }) -> string` (uses `scoped()` internally or returns path for caller to scope)
  - `splitLiveAndHistory(batches) -> { live, history }`
  - `Monitor` default export page component

- [ ] **Step 1: Failing helper tests**

```js
import assert from "node:assert/strict";
import { buildBatchesPath, splitLiveAndHistory } from "./monitorQuery.js";

assert.match(buildBatchesPath({ days: 7, status: ["failed", "blocked"], q: "pcg" }), /days=7/);
assert.match(buildBatchesPath({ days: 7, status: ["failed"], q: "pcg" }), /status=failed/);
assert.deepEqual(
  splitLiveAndHistory([{ batch_id: "a", status: "running" }, { batch_id: "b", status: "completed" }]).live.map((x) => x.batch_id),
  ["a"],
);
```

- [ ] **Step 2: Run — FAIL** (`node --test src/monitorQuery.test.js`)

- [ ] **Step 3: Implement helpers + Monitor page**

Page structure per spec §2: PageHeader, Kpis (running / throughput / `attention` / completed-in-range), Live rows with `.bar` progress, History table, filters (Today/7d/30d, status multi, search), poll 2000, row → `<BatchModal />`, upload → `<UploadModal />`. Omit Live when `live.length === 0`. EmptyState when both empty.

- [ ] **Step 4: Helpers PASS; smoke App loads Monitor in demo if easy**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/monitorQuery.js frontend/src/monitorQuery.test.js \
  frontend/src/pages/Monitor.jsx frontend/src/pages/Imports.jsx frontend/src/App.jsx
git commit -m "$(cat <<'EOF'
feat(ui): Monitor page with live progress and history filters

EOF
)"
```

---

### Task 5: Mock API filter parity + Overview link

**Files:**
- Modify: `frontend/src/mock/mockApi.js` — GET `/api/batches` applies `status`, `days`/`since`/`until`, `q`, `limit`, returns `attention`
- Modify: `frontend/src/pages/Overview.jsx` — button/link `go("monitor")` near health strip or attention (“See all on Monitor”)
- Optional: HowItWorks step that says watch progress on File loads → mention Monitor for fleet

**Interfaces:**
- Consumes: same query semantics as Task 2
- Produces: demo mode Monitor usable offline

- [ ] **Step 1: Small mock assertion** (node:test against exported filter helper if you extract one; otherwise manual demo check listed in Step 4)

Prefer extracting `filterBatches(rows, query)` next to mock or reusing nothing — keep mock inline but add a 10-line unit if extraction is natural.

- [ ] **Step 2: Implement mock filters + Overview CTA**

- [ ] **Step 3: Manual check** — switch to Monitoring persona, open `#monitor`, confirm live/history and BatchModal open

- [ ] **Step 4: `graphify update .`**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/mock/mockApi.js frontend/src/pages/Overview.jsx
git commit -m "$(cat <<'EOF'
feat(monitor): mock batch filters and Overview link to Monitor

EOF
)"
```

---

## Self-review notes

- Spec coverage: layout, API params, access, BatchModal reuse, Overview link, mock, out-of-scope items left out — OK.
- File loads “light trim” = copy only (Task 3); no KPI strip removal required.
- `get_batch` still uses `import_status(500)` unfiltered — intentional; no change required unless filters break it (they must not when kwargs default).
