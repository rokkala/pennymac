"""Builds a realistic platform state and exports API responses for the web app's demo mode.

    python scripts/export_demo_snapshot.py ../frontend/src/mock/snapshot.json

The demo build (npm run build:demo) serves these responses from an in-browser mock API so the
UI can be explored with no backend. All data is synthetic.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
tmp = tempfile.mkdtemp(prefix="lbp_demo_")
os.environ["LBP_DATA_DIR"] = tmp
os.environ.setdefault("LBP_WORKERS", "2")
os.environ["LBP_PULL_ALLOWED_HOSTS"] = "sftp.westside-partner.example"
os.environ["LBP_SCHEDULER_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from lbp.api.main import app  # noqa: E402
from lbp.demo_setup import ROWS, run_demo_setup  # noqa: E402

scale = "full"
n_rows = int(os.environ.get("DEMO_ROWS", os.environ.get("LBP_DEMO_ROWS", ROWS[scale])))
out_path = Path(sys.argv[1] if len(sys.argv) > 1 else "snapshot.json")

with TestClient(app) as client:
    run_demo_setup(scale=scale, force=True, rows=n_rows)

    def get(path, **kw):
        r = client.get(path, **kw)
        r.raise_for_status()
        return r.json()

    from sqlalchemy import select as _select

    from lbp.ingestion.parser import ParseOptions, read_sample
    from lbp.ingestion.pii import mask_value
    from lbp.store import db as _db

    snap = {"generated_rows_per_source": n_rows}
    snap["health"] = get("/api/health")
    snap["schema"] = get("/api/schema/target")
    snap["transforms"] = get("/api/meta/transforms")
    snap["sources"] = get("/api/sources")
    snap["mappings"] = {}
    for s in snap["sources"]["sources"]:
        for mm in s["mappings"]:
            snap["mappings"][mm["mapping_id"]] = get(f"/api/mappings/{mm['mapping_id']}")
    snap["source_profiles"] = {s["source_id"]: get(f"/api/sources/{s['source_id']}")["profile"] for s in snap["sources"]["sources"]}
    snap["previews"] = {mid: get(f"/api/mappings/{mid}/preview?n=500") for mid in snap["mappings"]}
    snap["mapping_dq"] = {mid: get(f"/api/mappings/{mid}/dq") for mid in snap["mappings"]}
    snap["column_samples"] = {}
    for mid, mp in snap["mappings"].items():
        with _db.get_engine().connect() as c:
            src = c.execute(_select(_db.sources).where(_db.sources.c.source_id == mp["source_id"])).first()
        _, sample_rows = read_sample(Path(src.sample_file), 400, ParseOptions(**(src.parse_options or {})))
        pii = {col["name"]: col["pii_type"] for col in (src.profile or {}).get("columns", []) if col.get("pii_type")}
        picked = sample_rows[:: max(1, len(sample_rows) // 8)][:8]
        snap["column_samples"][mid] = [{k: (mask_value(v, pii[k]) if k in pii and v else v) for k, v in r.items()} for r in picked]
    snap["field_inspect"] = {mid: {f["target"]: get(f"/api/mappings/{mid}/fields/{f['target']}/inspect") for f in mp["fields"]}
                             for mid, mp in snap["mappings"].items()}
    west = next((s for s in snap["sources"]["sources"] if "Westside" in (s.get("vendor_name") or "")), None)
    snap["new_source_mapping_id"] = (west["mappings"][0]["mapping_id"] if west and west.get("mappings") else None)
    snap["batches"] = get("/api/batches")
    snap["batch_details"] = {b["batch_id"]: get(f"/api/batches/{b['batch_id']}") for b in snap["batches"]["batches"]}
    snap["batch_changes"] = {b["batch_id"]: get(f"/api/batches/{b['batch_id']}/changes?limit=100") for b in snap["batches"]["batches"]
                             if b.get("load_type") not in (None, "full")}
    snap["feed_configs"] = {s_["source_id"]: get(f"/api/sources/{s_['source_id']}/config") for s_ in snap["sources"]["sources"] if s_.get("active_mapping_id")}
    snap["delivery_profiles"] = {s_["source_id"]: get(f"/api/sources/{s_['source_id']}/delivery") for s_ in snap["sources"]["sources"]}
    snap["schedules"] = get("/api/schedules")
    snap["deliveries_board"] = get("/api/deliveries?days_back=2&days_ahead=2")
    snap["deliveries_hist"] = get("/api/deliveries?days_back=30&days_ahead=0")
    snap["generated_at"] = _db.now().isoformat() + "Z"
    snap["vendors"] = get("/api/vendors")
    snap["vendor_details"] = {v["vendor_id"]: get(f"/api/vendors/{v['vendor_id']}") for v in snap["vendors"]["vendors"]}
    snap["by_vendor"] = {v["vendor_id"]: {
        "exceptions_summary": get(f"/api/exceptions/summary?vendor_id={v['vendor_id']}"),
        "analytics": {k: get(f"/api/analytics/{k}?vendor_id={v['vendor_id']}") for k in
                      ("import-status", "exceptions", "dq-scorecard", "source-performance", "ai-mapping", "executive", "vendors", "systemic")},
    } for v in snap["vendors"]["vendors"]}
    ex_items = []
    for tier, status, n in [("T1", "auto_applied", 15), ("T2", "open", 60), ("T3", "open", 50), ("T4", "open", 50), ("T4", "pending_checker", 15),
                            ("T5", "escalated", 25), ("T2", "resolved", 20), ("T4", "resolved", 8)]:
        ex_items += get(f"/api/exceptions?status={status}&tier={tier}&limit={n}")["items"]
    seen_ids = {e["exception_id"] for e in ex_items}
    for rule_id in ("DUP02", "R016", "TRANSFORM", "CHG01", "CHG02", "CHG04", "CHG05", "CHG06", "ACT01"):
        ex_items += [e for e in get(f"/api/exceptions?status=open&rule_id={rule_id}&limit=25")["items"] if e["exception_id"] not in seen_ids]
    snap["exceptions"] = ex_items
    snap["exception_details"] = {e["exception_id"]: get(f"/api/exceptions/{e['exception_id']}", headers={"X-Roles": "reviewer"}) for e in ex_items}
    snap["exception_totals"] = {s: get(f"/api/exceptions?status={s}&limit=1")["total"] for s in
                                ("open", "auto_applied", "pending_checker", "escalated", "resolved", "rejected")}
    snap["exceptions_summary"] = get("/api/exceptions/summary")
    snap["rules"] = get("/api/rules")
    snap["rule_versions"] = {r["rule_id"]: get(f"/api/rules/{r['rule_id']}") for r in snap["rules"]["rules"]}
    snap["policy"] = get("/api/policy")
    snap["analytics"] = {k: get(f"/api/analytics/{k}") for k in
                         ("import-status", "exceptions", "dq-scorecard", "source-performance", "ai-mapping", "executive", "vendors")}
    snap["ask_examples"] = {q: client.post("/api/analytics/ask", json={"question": q}).json() for q in [
        "How many loans were boarded?", "What are the top exception rules?", "Which vendor has the worst success rate?",
        "What is our projected 24h capacity?", "How many open exceptions by tier?", "What is the straight-through rate?"]}
    snap["author_examples"] = {t: client.post("/api/rules/author", json={"text": t}).json() for t in [
        "Interest rate must be between 0.5 and 15", "Borrower SSN is required", "Occupancy must be one of P, S, I",
        "If loan type is FHA, investor category must be GNMA", "Credit score must be at least 580",
        "Maturity date must be after note date", "Warn if DTI must not exceed 45"]}
    snap["audit"] = get("/api/audit?limit=150")
    snap["systemic"] = get("/api/analytics/systemic")
    snap["replay_previews"] = {}
    snap["mapping_memory"] = get("/api/mapping-memory")
    snap["diffs"] = {mid: get(f"/api/mappings/{mid}/diff") for mid, mp in snap["mappings"].items() if mp["version"] > 1}
    snap["value_coverage"] = {}
    for mid, mp in snap["mappings"].items():
        for f in mp["fields"]:
            attr = next(a for a in snap["schema"]["attributes"] if a["name"] == f["target"])
            if attr["codes"] or any(st.get("op") == "lookup" for st in f["transform"]):
                snap["value_coverage"].setdefault(mid, {})[f["target"]] = get(f"/api/mappings/{mid}/fields/{f['target']}/values")

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(snap, default=str, separators=(",", ":")))
print(f"wrote {out_path} ({out_path.stat().st_size / 1e6:.1f} MB), {len(ex_items)} exceptions")
