# Maintenance · Glue artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SME/Admin can open a Maintenance page and read allowlisted Glue job scripts, `glue_jobs.py`, and Glue notebooks inside the console (read-only).

**Architecture:** Fixed allowlist module resolves repo-relative paths safely; FastAPI exposes list + get; frontend CAPS-gates a new Maintenance page that renders Python as `<pre>` and notebooks as cell stacks. Demo mock mirrors the same catalog.

**Tech Stack:** FastAPI, pathlib, React (existing ui.jsx Panel/Loading), roles.js CAPS, mockApi.js

**Spec:** `docs/superpowers/specs/2026-11-03-maintenance-glue-artifacts-design.md`

## Global Constraints

- Read-only; no edit/run/deploy from UI.
- Allowlist only: ids `feed-job`, `feed-spark-job`, `vendor-pull-job`, `glue-jobs`, `nb-feed-workbench`, `nb-rule-lab` with paths exactly as in the spec table.
- Roles: `sme`, `admin` via `ROUTE_ROLES` and `canCap(..., "readMaintenance")`.
- Same visual language (no new design system / Tailwind).
- Callout copy: `Read-only. Production runs Glue jobs started by Step Functions or the API; notebooks are development-only and never board loans.`

## Review Focus

- Unknown artifact id → 404 / fail, never read arbitrary paths.
- Path containing `..` or absolute escape → rejected even if somehow injected into the allowlist entry.
- Missing file on disk → clear 404/error, not empty 200.
- Reviewer persona → no Maintenance nav item.
- Notebook with large outputs → responses omit outputs (cells only).

---

### Task 1: Allowlist + read helpers + tests

**Files:**
- Create: `backend/lbp/maintenance.py`
- Create: `backend/tests/test_maintenance.py`

**Interfaces:**
- Produces: `ARTIFACTS: list[dict]` with keys `id`, `title`, `path`, `kind` (`python`|`notebook`)
- Produces: `list_artifacts() -> list[dict]` (id/title/path/kind only)
- Produces: `get_artifact(id: str) -> dict` with `id`, `title`, `path`, `kind`, `content`
  - python: `content` is `str`
  - notebook: `content` is `list[{"cell_type": str, "source": str}]` (joined source lines; no outputs)
- Produces: `MaintenanceError` for unknown id / missing file / unsafe path
- Repo root: `Path(__file__).resolve().parents[2]` (pennymac root from `backend/lbp/`)

- [ ] **Step 1: Write failing tests** in `backend/tests/test_maintenance.py`

```python
def test_list_includes_feed_job():
    ids = {a["id"] for a in list_artifacts()}
    assert "feed-job" in ids and "nb-feed-workbench" in ids

def test_get_feed_job_returns_python_source():
    a = get_artifact("feed-job")
    assert a["kind"] == "python" and "lbp-feed" in a["content"] and "glue_jobs" in a["content"]

def test_unknown_id_raises():
    with pytest.raises(MaintenanceError):
        get_artifact("not-a-real-id")

def test_notebook_strips_outputs():
    a = get_artifact("nb-feed-workbench")
    assert a["kind"] == "notebook" and isinstance(a["content"], list)
    assert all("outputs" not in c for c in a["content"])
    assert any(c["cell_type"] == "markdown" for c in a["content"])
```

- [ ] **Step 2: Run tests — expect FAIL** (`MaintenanceError` / import missing)

Run: from `backend/` with the project venv that has pytest: `pytest tests/test_maintenance.py -v`

- [ ] **Step 3: Implement `backend/lbp/maintenance.py`**

`list_artifacts`, `get_artifact`, resolve path under repo root, reject if resolved path is not under root, read UTF-8; for `.ipynb` load JSON and map cells to `{cell_type, source}` with `source` as a single string.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit** (only if the user asked for commits)

---

### Task 2: API routes + ROUTE_ROLES

**Files:**
- Modify: `backend/lbp/api/main.py` (ROUTE_ROLES + two GET handlers)
- Modify: `backend/tests/test_maintenance.py` (optional HTTP tests if the suite already has a TestClient pattern; otherwise keep module-level tests from Task 1 and add one client test only if `env` / client fixture exists)

**Interfaces:**
- Consumes: `list_artifacts`, `get_artifact`, `MaintenanceError` from Task 1
- Produces: `GET /api/maintenance/artifacts` → `{ "artifacts": [...] }`
- Produces: `GET /api/maintenance/artifacts/{id}` → artifact dict from `get_artifact`
- ROUTE_ROLES: both GETs → `("sme", "admin")`
- Map `MaintenanceError` → 404 via existing `_err` / HTTPException pattern used for similar not-found errors

- [ ] **Step 1: Add ROUTE_ROLES entries and handlers** calling Task 1 helpers

- [ ] **Step 2: Manual or TestClient check** — authenticated sme gets 200; unknown id 404

- [ ] **Step 3: Commit** (if requested)

---

### Task 3: Frontend CAPS + Maintenance page + rail

**Files:**
- Modify: `frontend/src/roles.js` — add `readMaintenance: ["sme", "admin"]`
- Modify: `frontend/scripts/check-can.mjs` — assert `canCap(dan, "readMaintenance")` true, `canCap(lee, "readMaintenance")` false
- Create: `frontend/src/pages/Maintenance.jsx`
- Modify: `frontend/src/App.jsx` — import page; add `{ id: "maintenance", label: "Maintenance", el: Maintenance }` after governance; only render nav link when `canCap(persona, "readMaintenance")` (or render link always but page shows empty — prefer **hide nav**)
- Modify: `frontend/src/mock/mockApi.js` — GET list + GET by id using same catalog; for demo, read content from hardcoded stubs **or** fetch from relative imports if available; prefer calling the same file texts inlined for the six artifacts (can truncate notebook stubs to first ~3 cells if size is painful, but prefer full stripped cells)

**Interfaces:**
- Consumes: `/api/maintenance/artifacts`, `/api/maintenance/artifacts/{id}`
- `Maintenance({ persona })` page: list + viewer; notebook cells rendered as markdown text blocks + `<pre className="code">` for code; python as one `<pre className="code">`
- Page-head eyebrow: `Platform · data plane`; h1 `Maintenance`
- Spec callout verbatim in a `callout` under the head

- [ ] **Step 1: Extend check-can.mjs and run** `node frontend/scripts/check-can.mjs` — expect fail until CAPS added

- [ ] **Step 2: Add CAPS + Maintenance.jsx + App.jsx nav gate + mock routes**

- [ ] **Step 3: Run** `node frontend/scripts/check-can.mjs` and `cd frontend && npm run build` — expect PASS / clean build

- [ ] **Step 4: Commit** (if requested)

---

### Task 4: Graphify + smoke

**Files:** none required beyond graph update

- [ ] **Step 1:** `graphify update .` from repo root
- [ ] **Step 2:** Smoke: as Dan, open `#maintenance`, open `feed-job` and `nb-feed-workbench`; as Lee, Maintenance absent from rail

---

## Self-review notes

- Spec catalog, CAPS, API shapes, notebook strip, callout, and nav placement each map to Tasks 1–3.
- Review Focus items covered by Task 1 unknown-id / path resolve, Task 3 CAPS nav, Task 1 notebook strip.
