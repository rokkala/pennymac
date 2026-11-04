# Demo Kit In-App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the demo-kit sales scenario loadable via `start_demo.sh` / CLI and an in-app admin “Load demo scenario…” action (compact by default, full opt-in, wipe only with force).

**Architecture:** Extract the scenario builder already proven in `backend/scripts/export_demo_snapshot.py` into `backend/lbp/demo_setup.py`. Resolve `demo_kit/` (with legacy path fallback), copy `2_upload_live` for the talk track, expose `POST /api/demo/setup` + CLI, fix `start_demo.sh`, add admin UI on Policy & Audit. Keep thin `POST /api/demo/seed` unchanged.

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy SQLite (local), React + Vite frontend, existing persona headers (`X-User` / `X-Roles`).

**Spec:** `docs/superpowers/specs/2026-11-03-demo-kit-in-app-design.md`

## Global Constraints

- Demo APIs only when `enable_demo` is true (same as seed); production validate already refuses demo.
- `POST /api/demo/setup` requires role `admin` (add to `ROUTE_ROLES` like seed).
- Scales: `compact` default rows **200**; `full` rows **3000** (env override `LBP_DEMO_ROWS` allowed).
- Existing data + `force=False` → conflict (HTTP **409**, CLI non-zero); wipe only with `force=True` / `--force` / UI confirm.
- Kit canonical path: repo-root `demo_kit/`; also accept `demo-kit/demo_kit` and `LBP_DEMO_KIT`.
- Do not invent demo filenames; prefer kit + existing export scenario beats.
- Commits: only if the user explicitly asked to commit; otherwise skip commit steps.
- After code changes: `graphify update .` once at the end (not every task).

## Review Focus

- Setup called twice without force → second call must 409 / raise, not silently append vendors.
- `enable_demo=false` → setup endpoint 404 (same as seed).
- Non-admin persona → 403 on setup.
- Missing kit directory → setup still builds generator scenario; `upload_live_dir` in result is null/absent with a clear warning field (do not crash).
- Wipe (`force=True`) must not leave a half-open SQLite engine pointing at deleted files (reset engine + settings after wipe).

---

## File structure

| File | Responsibility |
|---|---|
| `backend/lbp/demo_setup.py` | Kit resolve, emptiness check, wipe, `run_demo_setup`, `SetupResult` |
| `backend/scripts/demo_setup.py` | Thin CLI wrapper → module |
| `backend/scripts/export_demo_snapshot.py` | Call `run_demo_setup` then export JSON (thin) |
| `backend/lbp/api/main.py` | `POST /api/demo/setup`, config.demo_setup, ROUTE_ROLES |
| `backend/lbp/cli.py` | `demo-setup` command |
| `backend/tests/test_demo_setup.py` | Unit/API tests for setup |
| `demo_kit/` | Un-nested kit (from `demo-kit/demo_kit/`) |
| `demo_kit/start_demo.sh` | Fixed boot script |
| `frontend/src/pages/Governance.jsx` (+ small modal component if needed) | Admin Load demo UI |
| `frontend/src/pages/Overview.jsx` | Optional secondary link when demo+admin |
| `README.md`, `demo_kit/DEMO_GUIDE.md` | Doc paths |

---

### Task 1: Kit layout + resolver

**Files:**
- Move: `demo-kit/demo_kit/*` → `demo_kit/` (repo root); leave or remove empty `demo-kit/` nest
- Create: `backend/lbp/demo_setup.py` (resolver + types only in this task)
- Test: `backend/tests/test_demo_setup.py`

**Interfaces:**
- Produces: `resolve_kit_dir(repo_root: Path | None = None) -> Path | None`
- Produces: `ROWS = {"compact": 200, "full": 3000}`

- [ ] **Step 1: Write the failing test**

```python
def test_resolve_kit_dir_finds_demo_kit(tmp_path, monkeypatch):
    kit = tmp_path / "demo_kit"
    (kit / "files").mkdir(parents=True)
    (kit / "MANIFEST.csv").write_text("stage,vendor,feed,file,rows,what_it_shows,expected_outcome\n")
    assert resolve_kit_dir(tmp_path) == kit.resolve()

def test_resolve_kit_dir_falls_back_to_hyphen_nest(tmp_path):
    kit = tmp_path / "demo-kit" / "demo_kit"
    (kit / "files").mkdir(parents=True)
    assert resolve_kit_dir(tmp_path) == kit.resolve()

def test_resolve_kit_dir_env_override(tmp_path, monkeypatch):
    kit = tmp_path / "custom"
    kit.mkdir()
    monkeypatch.setenv("LBP_DEMO_KIT", str(kit))
    assert resolve_kit_dir(tmp_path) == kit.resolve()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_demo_setup.py::test_resolve_kit_dir_finds_demo_kit -v`  
Expected: FAIL import / not defined

- [ ] **Step 3: Implement `resolve_kit_dir` + move kit to `demo_kit/`**

Move files with `git mv` or filesystem move preserving `files/`, `MANIFEST.csv`, `DEMO_GUIDE.md`, `start_demo.sh`. Implement resolver order: env → `repo/demo_kit` → `repo/demo-kit/demo_kit`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_demo_setup.py -k resolve_kit -v`  
Expected: PASS

- [ ] **Step 5: Commit** (skip unless user asked)

---

### Task 2: Emptiness check, wipe, `SetupResult` shell

**Files:**
- Modify: `backend/lbp/demo_setup.py`
- Test: `backend/tests/test_demo_setup.py`

**Interfaces:**
- Consumes: `env` fixture pattern from `tests/conftest.py` (`LBP_DATA_DIR`, reset settings/engine)
- Produces: `class DemoSetupConflict(Exception)`
- Produces: `def data_is_present() -> bool` — true if any row in `sources` (or SSE loans if sources empty but loans exist)
- Produces: `def wipe_data_dir(data_dir: Path) -> None` — delete managed contents; call `db.reset_engine()` + `config.reset_settings()` after
- Produces: `SetupResult` dataclass/TypedDict with at least: `scale`, `rows`, `vendors`, `batches`, `kit_dir`, `upload_live_dir`, `warnings`, `seconds`

- [ ] **Step 1: Write the failing tests**

```python
def test_data_is_present_false_on_fresh_env(env):
    assert data_is_present() is False

def test_data_is_present_true_after_source(env, sample_files):
    from lbp.mapping import service as ms
    path = next(iter(sample_files.values()))
    ms.register_source("T", path, "analyst.demo", "t")
    assert data_is_present() is True

def test_wipe_data_dir_clears_presence(env, sample_files):
    from lbp.config import get_settings
    from lbp.mapping import service as ms
    ms.register_source("T", next(iter(sample_files.values())), "a", "t")
    wipe_data_dir(get_settings().data_dir)
    from lbp.rules.registry import RuleRegistry
    RuleRegistry().seed_defaults()
    assert data_is_present() is False
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `cd backend && .venv/bin/python -m pytest tests/test_demo_setup.py -k "data_is_present or wipe" -v`

- [ ] **Step 3: Implement `data_is_present`, `wipe_data_dir`, `DemoSetupConflict`, `SetupResult`**

Wipe: remove files under `data_dir` (keep directory); reset engine/settings; next `get_engine(create=True)` / migrate path as used elsewhere in tests.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit** (skip unless user asked)

---

### Task 3: `run_demo_setup` — extract scenario from export script

**Files:**
- Modify: `backend/lbp/demo_setup.py` — move scenario body from `export_demo_snapshot.py` (~vendors through Westside / Harbor staging)
- Modify: `backend/scripts/export_demo_snapshot.py` — call `run_demo_setup` then keep snapshot HTTP scrape
- Test: `backend/tests/test_demo_setup.py`

**Interfaces:**
- Produces: `def run_demo_setup(*, scale: str = "compact", force: bool = False, kit_dir: Path | None = None, rows: int | None = None) -> SetupResult`
- Behaviour: if `data_is_present()` and not force → raise `DemoSetupConflict`; if force → wipe then rebuild; set `ROWS` from scale; build same vendors/feeds/beats as current export script; if kit resolved, copy `files/2_upload_live` to `data_dir / "demo_uploads" / "2_upload_live"` and set `upload_live_dir`; publish configs for live feeds (reuse `publish_all` / existing export end steps that matter for live app)

- [ ] **Step 1: Write the failing tests**

```python
def test_run_demo_setup_compact_creates_vendors_and_batches(env):
    result = run_demo_setup(scale="compact", force=False)
    assert result["scale"] == "compact"
    assert result["rows"] == 200
    from lbp import vendors as vs
    assert len(vs.list_vendors()["vendors"]) >= 4
    from lbp.pipeline import batch as pipeline
    assert len(pipeline.list_batches()["batches"]) >= 4  # use whatever list helper exists — mirror export expectations

def test_run_demo_setup_conflict_without_force(env):
    run_demo_setup(scale="compact")
    with pytest.raises(DemoSetupConflict):
        run_demo_setup(scale="compact", force=False)

def test_run_demo_setup_force_rebuilds(env):
    run_demo_setup(scale="compact")
    run_demo_setup(scale="compact", force=True)  # must not raise
```

Use real list APIs from the codebase (`vendors.list_*`, batches list via store or API helpers already used in tests). Adjust assertion helpers to match existing modules — do not invent APIs.

- [ ] **Step 2: Run tests — expect FAIL** (`run_demo_setup` missing or incomplete)

- [ ] **Step 3: Implement `run_demo_setup` by extracting from `export_demo_snapshot.py`**

Keep personas (`priya.analyst`, `dan.sme`, `maria.ops`, …) identical to the export script. Parameterize `ROWS`. Prefer calling internal services (mapping, pipeline, scheduling) as the export script does — not HTTP — so API and CLI share one path. Leave snapshot JSON collection in the export script only.

- [ ] **Step 4: Point `export_demo_snapshot.py` at `run_demo_setup(scale="full", force=True)` (or env rows) then scrape**

- [ ] **Step 5: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_demo_setup.py -v --tb=short`  
Expected: PASS (compact only in CI; full is optional/slow — mark full `@pytest.mark.slow` if added)

- [ ] **Step 6: Commit** (skip unless user asked)

---

### Task 4: API `POST /api/demo/setup` + config flag

**Files:**
- Modify: `backend/lbp/api/main.py` (`ROUTE_ROLES`, `/api/config`, new route near `demo_seed`)
- Test: `backend/tests/test_demo_setup.py` (TestClient)

**Interfaces:**
- Consumes: `run_demo_setup`, `DemoSetupConflict`
- Produces: `POST /api/demo/setup` body `{ "force": bool, "scale": "compact"|"full" }`
- Produces: config key `demo_setup: { available: bool, scales: ["compact","full"], default_scale: "compact" }` when `enable_demo`

- [ ] **Step 1: Write the failing tests**

```python
def test_demo_setup_api_requires_admin(client, env):
    r = client.post("/api/demo/setup", json={"force": False, "scale": "compact"},
                    headers={"X-User": "priya.analyst", "X-Roles": "analyst"})
    assert r.status_code == 403

def test_demo_setup_api_409_then_force(client, env):
    h = {"X-User": "admin", "X-Roles": "admin"}
    assert client.post("/api/demo/setup", json={"force": False, "scale": "compact"}, headers=h).status_code == 200
    assert client.post("/api/demo/setup", json={"force": False, "scale": "compact"}, headers=h).status_code == 409
    assert client.post("/api/demo/setup", json={"force": True, "scale": "compact"}, headers=h).status_code == 200

def test_config_exposes_demo_setup(client, env):
    cfg = client.get("/api/config").json()
    assert cfg["demo"] is True
    assert cfg["demo_setup"]["default_scale"] == "compact"
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement route + ROUTE_ROLES entry `("POST", "/api/demo/setup"): ("admin",)` + config fields**

Map `DemoSetupConflict` → `HTTPException(409, detail={...})`. Invalid scale → 400.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit** (skip unless user asked)

---

### Task 5: CLI + `start_demo.sh`

**Files:**
- Modify: `backend/lbp/cli.py`
- Create: `backend/scripts/demo_setup.py`
- Modify: `demo_kit/start_demo.sh`
- Update: `demo_kit/DEMO_GUIDE.md` paths (`./demo_kit/start_demo.sh` from repo root)

**Interfaces:**
- Produces: `python -m lbp.cli demo-setup [--scale compact|full] [--force] [--kit PATH] [--data-dir PATH]`
- Produces: script exit 0 on success; non-zero on conflict without `--force`

- [ ] **Step 1: Implement CLI command calling `run_demo_setup`; print JSON `SetupResult`**

- [ ] **Step 2: Thin `scripts/demo_setup.py` argparse → same**

- [ ] **Step 3: Rewrite `start_demo.sh`**

Must: `cd` to repo root (parent of `demo_kit`); use `backend/.venv/bin/python` if present else `python3`; `npm ci` + `npm run build` in frontend; run demo-setup with `--force` unless `--keep`; `--full` → scale full; then `LBP_DATA_DIR=... LBP_SCHEDULER_ENABLED=false uvicorn lbp.api.main:app --port 8000` from `backend`.

- [ ] **Step 4: Smoke**

Run: `cd backend && .venv/bin/python -m lbp.cli demo-setup --scale compact --force` (with `LBP_DATA_DIR` temp)  
Expected: JSON with vendors/batches; exit 0

- [ ] **Step 5: Commit** (skip unless user asked)

---

### Task 6: Frontend — Load demo scenario modal

**Files:**
- Modify: `frontend/src/pages/Governance.jsx`
- Optionally create: `frontend/src/components/DemoSetupModal.jsx` (only if Governance grows awkward)
- Modify: `frontend/src/pages/Overview.jsx` — secondary button when `config.demo && persona.roles.includes("admin")`
- Consumes: `GET /api/config` → `demo` / `demo_setup`; `POST /api/demo/setup`

**Interfaces:**
- UI copy: button “Load demo scenario…”; modal explains wipe; scale select default Compact; on 409 show confirm then retry `force: true`; success toast + full reload

- [ ] **Step 1: Add modal + admin-only button on Policy & Audit**

Use existing `Modal` / `useDialog` / `useAction` / `api()` patterns from Governance.

- [ ] **Step 2: Overview admin link** that navigates to `#governance` or opens the same modal via shared export

Prefer navigate to governance with a hash/query if sharing modal state is messy — YAGNI: button only on Governance is enough if Overview link says “Policy & Audit → Load demo”. Spec asked for secondary discoverability — a link to `#governance` with helper text satisfies.

- [ ] **Step 3: `npm run lint`**

Run: `cd frontend && npm run lint`  
Expected: clean

- [ ] **Step 4: Manual check against running API** (admin persona → Load → compact → reload → vendors match guide names)

- [ ] **Step 5: Commit** (skip unless user asked)

---

### Task 7: Docs + graphify

**Files:**
- Modify: `README.md` (Run it locally — point to `demo_kit/start_demo.sh` and in-app load)
- Modify: `demo_kit/DEMO_GUIDE.md` (paths, compact vs full, force semantics)
- Update status line in `docs/superpowers/specs/2026-11-03-demo-kit-in-app-design.md` to approved/implemented when done

- [ ] **Step 1: Doc edits**

- [ ] **Step 2: `cd /Users/rokkala/Desktop/pennymac && graphify update .`**

- [ ] **Step 3: Final verification**

Run:  
`cd backend && .venv/bin/python -m pytest tests/test_demo_setup.py -v --tb=short`  
`cd frontend && npm run lint`  
Expected: all pass

---

## Spec coverage check

| Spec item | Task |
|---|---|
| Both entry points | 5 (script), 6 (UI), 4 (API) |
| Soft wipe / force | 2, 3, 4, 6 |
| Compact / full | 3, 4, 5, 6 |
| Shared `demo_setup` module | 3 |
| Kit path un-nest + resolve | 1 |
| Keep `/api/demo/seed` | untouched |
| Config expose | 4 |
| export script reuse | 3 |
| Docs | 7 |
| enable_demo / admin gates | 4 + Review Focus tests |

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-03-demo-kit-in-app.md`. Please review the plan. Which execution approach would you prefer?

- **Subagent-driven** — A fresh subagent implements each task and a fresh reviewer checks it before the next one starts, then a whole-branch review at the end. Most thorough; costs a fresh context per task and per review.
- **Native** — I implement every task myself in this session, then one fresh reviewer on the most capable model checks the whole branch. Cheapest and fastest; no independent review until the end.

**For this plan I recommend Native**, because tasks are tightly sequential (extract → API → CLI → UI) and a single session will keep the large `export_demo_snapshot` extract coherent. Does the plan capture what you want, and which approach should we use?
