"""Vendors own feeds; operations are scoped and protected at vendor level."""
import csv

import pytest
from sqlalchemy import select

from lbp import vendors as vs
from lbp.exceptions.manager import ExceptionManager
from lbp.mapping import service as ms
from lbp.pipeline.batch import create_batch, run_batch
from lbp.pipeline.delivery import decide_profile, propose_profile
from lbp.store import db


def _feed(vendor_id, name, path):
    reg = ms.register_source(name, path, "analyst1", vendor_id=vendor_id)
    ms.accept_all(reg["mapping_id"], "analyst1", 0.0)
    ms.submit(reg["mapping_id"], "analyst1")
    ms.approve(reg["mapping_id"], "sme1", ["sme"])
    return reg["source_id"]


def _incremental(sid, kind="incremental"):
    propose_profile(sid, {"load_type": kind, "action": {"mode": "upsert"}, "sequence": {"source": "none"}}, "a", ["analyst"])
    decide_profile(sid, "s", ["sme"], True)


def _sse(ln):
    with db.get_engine().connect() as c:
        return c.execute(select(db.sse_loans).where(db.sse_loans.c.loan_number == ln)).first()


def test_vendor_crud_roles_and_rollups(sample_files):
    with pytest.raises(vs.VendorError, match="requires"):
        vs.create_vendor({"name": "Summit"}, "rev", ["reviewer"])
    v = vs.create_vendor({"name": "Summit Home Lending", "vendor_type": "correspondent", "external_ref": "SEL-0042",
                          "contact": {"name": "Ops desk", "email": "ops@summit.example"}}, "analyst1", ["analyst"])
    assert v["status"] == "onboarding" and v["feeds"] == []
    with pytest.raises(vs.VendorError, match="already exists"):
        vs.create_vendor({"name": "summit home lending"}, "analyst1", ["analyst"])
    with pytest.raises(vs.VendorError, match="vendor_type"):
        vs.update_vendor(v["vendor_id"], {"vendor_type": "bank"}, "analyst1", ["analyst"])
    tape = _feed(v["vendor_id"], "Loan tape", sample_files["pcg_retail"])
    run_batch(create_batch(tape, sample_files["pcg_retail"], "t.csv", "ops"), workers=1)
    out = vs.get_vendor(v["vendor_id"])
    assert [f["name"] for f in out["feeds"]] == ["Loan tape"] and out["active_loans"] > 0 and out["feeds"][0]["mappings"][0]["status"] == "approved"
    with pytest.raises(ValueError, match="already has a feed"):
        ms.register_source("Loan tape", sample_files["pcg_retail"], "analyst1", vendor_id=v["vendor_id"])
    # suspending needs SME/Compliance and a reason; a suspended vendor's files are recorded, not processed
    with pytest.raises(vs.VendorError, match="requires"):
        vs.update_vendor(v["vendor_id"], {"status": "suspended", "reason": "x"}, "analyst1", ["analyst"])
    vs.update_vendor(v["vendor_id"], {"status": "suspended", "reason": "Contract under review"}, "sme1", ["sme"])
    with pytest.raises(ValueError, match="suspended"):
        create_batch(tape, sample_files["pcg_retail"], "t2.csv", "ops", allow_duplicate=True, reason="x")
    bid = create_batch(tape, sample_files["pcg_retail"], "t3.csv", "s3", allow_duplicate=True, reason="x", strict=False)
    with db.get_engine().connect() as c:
        assert c.execute(select(db.batches.c.status).where(db.batches.c.batch_id == bid)).scalar() == "failed"


def test_feed_without_vendor_gets_one_and_can_be_moved(sample_files):
    reg = ms.register_source("Bulk tape", sample_files["bulk_acquisition"], "analyst1")
    assert reg["vendor_id"]
    target = vs.create_vendor({"name": "Atlas Capital", "vendor_type": "bulk_seller"}, "a", ["analyst"])
    with pytest.raises(vs.VendorError, match="requires"):
        vs.move_feed(reg["source_id"], target["vendor_id"], "a", ["analyst"], "group feeds")
    vs.move_feed(reg["source_id"], target["vendor_id"], "sme1", ["sme"], "Bulk tapes come from Atlas")
    assert [f["source_id"] for f in vs.get_vendor(target["vendor_id"])["feeds"]] == [reg["source_id"]]
    assert ms.get_mapping(reg["mapping_id"])["source"]["vendor_name"] == "Atlas Capital"


def test_change_file_cannot_touch_another_vendors_loans(sample_files, tmp_path):
    a = vs.create_vendor({"name": "Vendor A"}, "a", ["analyst"])
    b = vs.create_vendor({"name": "Vendor B"}, "a", ["analyst"])
    tape_a = _feed(a["vendor_id"], "Tape", sample_files["pcg_retail"])
    run_batch(create_batch(tape_a, sample_files["pcg_retail"], "a.csv", "ops"), workers=1)
    delta_b = _feed(b["vendor_id"], "Deltas", sample_files["pcg_retail"])
    _incremental(delta_b)
    ln = next(r["LoanID"] for r in csv.DictReader(open(sample_files["pcg_retail"])) if _sse(r["LoanID"]))
    before = _sse(ln)
    p = tmp_path / "b_delta.csv"
    p.write_text(f"LoanID,CurrentUPB\n{ln},1234\n")
    bid = create_batch(delta_b, p, p.name, "ops")
    run_batch(bid, workers=1)
    assert float(_sse(ln).current_principal_balance) == float(before.current_principal_balance)
    em = ExceptionManager()
    ex = em.list(status="open", batch_id=bid)["items"]
    assert [e["rule_id"] for e in ex] == ["CHG06"] and ex[0]["tier"] == "T4" and ex[0]["vendor_name"] == "Vendor B"
    # a documented servicing transfer: maker + checker approve, the change applies and the loan moves to vendor B
    em.resolve(ex[0]["exception_id"], "rev1", ["reviewer"], value=ln, comment="Transfer agreement TA-17")
    out = em.checker_decision(ex[0]["exception_id"], "chk1", ["checker"], True)
    row = _sse(ln)
    assert out["loan_boarded"] and float(row.current_principal_balance) == 1234 and row.lbp_source_id == delta_b
    # vendor scoping of reads
    assert {e["vendor_id"] for e in em.list(status=None, source_ids=vs.source_ids(b["vendor_id"]))["items"]} == {b["vendor_id"]}


def test_snapshot_compares_the_vendors_whole_portfolio(sample_files, tmp_path):
    v = vs.create_vendor({"name": "Cornerstone Servicing", "vendor_type": "sub_servicer"}, "a", ["analyst"])
    other = vs.create_vendor({"name": "Other Seller"}, "a", ["analyst"])
    tape = _feed(v["vendor_id"], "Boarding tapes", sample_files["pcg_retail"])
    run_batch(create_batch(tape, sample_files["pcg_retail"], "t.csv", "ops"), workers=1)
    other_tape = _feed(other["vendor_id"], "Tape", sample_files["correspondent"])
    run_batch(create_batch(other_tape, sample_files["correspondent"], "o.csv", "ops"), workers=1)
    snap_feed = _feed(v["vendor_id"], "Monthly snapshot", sample_files["pcg_retail"])
    _incremental(snap_feed, "snapshot")
    rows = [r for r in csv.DictReader(open(sample_files["pcg_retail"])) if _sse(r["LoanID"])]
    p = tmp_path / "snap.csv"
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows[3:])
    bid = create_batch(snap_feed, p, p.name, "ops")
    run_batch(bid, workers=1)
    with db.get_engine().connect() as c:
        snap = c.execute(select(db.batches.c.change_summary).where(db.batches.c.batch_id == bid)).scalar()["snapshot"]
    # loans boarded through the vendor's tape feed count; the other vendor's loans do not
    assert snap["missing"] == 3 and snap["portfolio_active"] == len(rows)


def test_vendor_api_and_scoped_listings(client, sample_files):
    an, sme = {"X-User": "ana", "X-Roles": "analyst"}, {"X-User": "sam", "X-Roles": "sme"}
    assert client.post("/api/vendors", json={"name": "X"}, headers={"X-User": "o", "X-Roles": "ops"}).status_code == 403
    v = client.post("/api/vendors", json={"name": "Westside Lending", "vendor_type": "correspondent"}, headers=an).json()
    with open(sample_files["correspondent"], "rb") as f:
        r = client.post("/api/sources", data={"name": "Weekly tape", "vendor_id": v["vendor_id"]}, files={"file": ("w.csv", f)}, headers=an)
    assert r.status_code == 200 and r.json()["vendor_id"] == v["vendor_id"]
    other = client.post("/api/vendors", json={"name": "Elsewhere"}, headers=an).json()
    got = client.get(f"/api/vendors/{v['vendor_id']}").json()
    assert got["feeds"][0]["name"] == "Weekly tape" and got["pending_mapping_review"] == 1
    lst = {x["vendor_id"]: x for x in client.get("/api/vendors").json()["vendors"]}
    assert lst[v["vendor_id"]]["feeds"] == 1 and lst[other["vendor_id"]]["feeds"] == 0
    assert [s["vendor_name"] for s in client.get(f"/api/sources?vendor_id={v['vendor_id']}").json()["sources"]] == ["Westside Lending"]
    assert client.get(f"/api/sources?vendor_id={other['vendor_id']}").json()["sources"] == []
    for path in ("/api/batches", "/api/exceptions", "/api/exceptions/summary", "/api/deliveries", "/api/schedules", "/api/analytics/vendors",
                 "/api/analytics/exceptions", "/api/analytics/dq-scorecard", "/api/analytics/source-performance", "/api/analytics/systemic",
                 "/api/analytics/ai-mapping", "/api/analytics/import-status"):
        assert client.get(f"{path}?vendor_id={v['vendor_id']}").status_code == 200, path
    assert client.get("/api/batches?vendor_id=ven_nope").status_code == 404
    r = client.put(f"/api/vendors/{v['vendor_id']}", json={"status": "suspended", "reason": "audit"}, headers=an)
    assert r.status_code == 400 and "requires" in r.json()["detail"]
    assert client.put(f"/api/vendors/{v['vendor_id']}", json={"status": "active"}, headers=sme).json()["status"] == "active"
