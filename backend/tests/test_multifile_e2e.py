"""End to end (Task 15): a master/detail feed onboarded through the services, files delivered through the API,
the set joined and loaded; timeout + accept-partial override; zip delivery; the single-file path unchanged."""
import csv
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from lbp.store import db

OPS = {"X-User": "oli", "X-Roles": "ops"}
N = 40


def _feed(files, *, min_match_rate=0.8):
    """Feed created through the services: approved mapping (incl. two aggregate outputs), layout proposed by
    one user and approved by another. Returns the source id."""
    from lbp.mapping import service as ms
    from lbp.multifile.service import decide_layout, propose_layout
    from lbp.samples import master_detail_layout, master_detail_readiness

    reg = ms.register_source("Escrow tape", files["master"], "analyst1", "Master + escrow items")
    mid = reg["mapping_id"]
    ms.accept_all(mid, "analyst1", 0.0)
    with db.get_engine().connect() as c:
        fields = c.execute(select(db.mappings.c.fields).where(db.mappings.c.mapping_id == mid)).scalar()
    money = next(f for f in fields if f["target"] == "escrow_balance")["transform"]
    for target, col in (("tax_annual_amount", "tax_total"), ("hazard_insurance_annual_premium", "hazard_total")):
        # add_field only knows the sampled (master) columns: add on a master column, then point it at the
        # aggregate output the join produces
        ms.add_field(mid, target, "analyst1", ["EscrowBalance"], money)
        ms.update_field(mid, target, "override", "analyst1", sources=[col], transform=money)
    ms.submit(mid, "analyst1")
    ms.approve(mid, "onboarding.reviewer", ["onboarding_reviewer"], True, "ok")
    sid = reg["source_id"]
    propose_layout(sid, master_detail_layout(min_match_rate), master_detail_readiness(), "analyst1", ["onboarding"])
    decide_layout(sid, "sme1", ["onboarding_reviewer"], True, "two-file escrow feed")
    return sid


def _upload(client, sid, path, name=None):
    with open(path, "rb") as f:
        r = client.post("/api/upload", data={"source_id": sid, "auto_start": "false"},
                        files={"file": (name or path.name, f)}, headers=OPS)
    assert r.status_code == 200, r.text
    return r.json()


def _batches(sid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.batches).where(db.batches.c.source_id == sid)).all()


def _batch(bid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first()


def _staging(bid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.loans_staging).where(db.loans_staging.c.batch_id == bid)).all()


def _audit(action):
    with db.get_engine().connect() as c:
        return c.execute(select(db.audit_log).where(db.audit_log.c.action == action)).all()


def _detail_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _norm(ref):
    return (ref.strip().lstrip("0") or "0").upper()


# ------------------------------------------------------------------ tests
def test_e2e_master_then_detail_loads_joined_loans(client, env):
    from lbp.pipeline.batch import run_batch
    from lbp.samples import generate_master_detail

    files = generate_master_detail(env / "src", N)
    sid = _feed(files)
    with open(files["master"], newline="") as f:
        ids = [r["LoanID"] for r in csv.DictReader(f)]
    details = _detail_rows(files["details"])
    orphans = [d for d in details if _norm(d["LoanRef"]) not in set(ids)]
    noisy = [d for d in details if d["LoanRef"] != _norm(d["LoanRef"]) and _norm(d["LoanRef"]) in set(ids)]
    without = [i for i in ids if not any(_norm(d["LoanRef"]) == i for d in details)]
    assert orphans and noisy and without  # the generator delivers the data problems it promises

    m = _upload(client, sid, files["master"])
    assert m["role"] == "master" and m["status"] == "waiting" and m["batch_id"] is None
    assert _batches(sid) == []

    d = _upload(client, sid, files["details"])
    assert d["set_id"] == m["set_id"] and d["role"] == "escrow_items" and d["status"] == "consumed" and d["batch_id"]
    bid = d["batch_id"]
    assert [b.batch_id for b in _batches(sid)] == [bid]
    run_batch(bid)
    b = _batch(bid)
    assert b.status == "completed", b.error
    j = b.reconciliation["join"]
    assert j["master_rows_read"] == N and j["master_rows_excluded_by_join"] == 0
    assert b.processed == N - j["master_rows_excluded_by_join"] and len(_staging(bid)) == N

    # hand-checked aggregate: a loan whose detail rows carry key noise (case / leading zeros / spaces)
    lid = _norm(noisy[0]["LoanRef"])
    mine = [x for x in details if _norm(x["LoanRef"]) == lid]
    tax = sum((Decimal(x["ItemAmount"]) for x in mine if x["ItemType"] == "TAX"), Decimal(0))
    haz = sum((Decimal(x["ItemAmount"]) for x in mine if x["ItemType"] == "HAZ"), Decimal(0))
    rec = {s.loan_number: s.record for s in _staging(bid)}[lid]
    if tax:
        assert Decimal(str(rec["tax_annual_amount"])) == tax
    if haz:
        assert Decimal(str(rec["hazard_insurance_annual_premium"])) == haz
    assert tax or haz
    lonely = {s.loan_number: s.record for s in _staging(bid)}[without[0]]  # a master without details still loads
    assert lonely.get("tax_annual_amount") in (None, "") and lonely.get("hazard_insurance_annual_premium") in (None, "")

    # orphan detail rows: JOIN01 on the detail role, key fingerprinted, PII masked
    with db.get_engine().connect() as c:
        exs = c.execute(select(db.exceptions).where(db.exceptions.c.batch_id == bid, db.exceptions.c.category == "join")).all()
    assert {e.rule_id for e in exs} == {"JOIN01"} and len(exs) == len(orphans)
    for e in exs:
        assert e.role == "escrow_items" and e.loan_number.startswith("tok_")
        raw = json.loads(e.original_value)
        assert "*" in raw["PayerTIN"]
    tins = {o["PayerTIN"] for o in orphans}
    refs = {o["LoanRef"].strip() for o in orphans}
    blob = json.dumps([[e.loan_number, e.original_value, e.message] for e in exs])
    assert not any(t in blob for t in tins)  # the raw row is PII-masked (its loan reference is not PII)
    assert not any(r in json.dumps([[e.loan_number, e.message] for e in exs]) for r in refs)  # the key is fingerprinted

    # the batch list shows the per-role counts
    rows = client.get("/api/batches", params={"limit": 50}).json()["batches"]
    jb = next(x for x in rows if x["batch_id"] == bid)["reconciliation"]["join"]
    assert jb["per_role"]["master"]["rows_read"] == N
    er = jb["per_role"]["escrow_items"]
    assert er["rows_read"] == len(details) and er["orphaned"] == len(orphans) and er["matched"] == len(details) - len(orphans)
    assert jb["exceptions"] == {"JOIN01": len(orphans)}


def test_e2e_timeout_alert_then_override_accept_partial(client, env, monkeypatch):
    from lbp.api import main as api
    from lbp.multifile.fileset import expire_sets
    from lbp.pipeline.batch import override_preflight, run_batch
    from lbp.samples import generate_master_detail

    started = []
    monkeypatch.setattr(api, "dispatch", started.append)
    files = generate_master_detail(env / "src", 20)
    sid = _feed(files)
    m = _upload(client, sid, files["master"])
    assert m["status"] == "waiting"

    later = datetime.now(UTC) + timedelta(minutes=241)
    assert expire_sets(later) == [m["set_id"]]
    late = [a.detail for a in _audit("alert.delivery_late") if a.detail.get("set_id") == m["set_id"]]
    assert len(late) == 1 and late[0]["missing_roles"] == ["escrow_items"] and "escrow_items" in late[0]["message"]
    sets = client.get("/api/file-sets", params={"source_id": sid}).json()
    assert sets[0]["status"] == "waiting" and _batches(sid) == []  # alert_only keeps the set waiting

    url = f"/api/file-sets/{m['set_id']}/override"
    sme = {"X-User": "sme1", "X-Roles": "onboarding_reviewer"}
    assert client.post(url, json={"action": "accept_partial", "reason": " "}, headers=sme).status_code == 400
    r = client.post(url, json={"action": "accept_partial", "reason": "vendor confirmed no escrow items today"}, headers=sme)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "consumed" and out["missing_roles"] == ["escrow_items"] and started == [out["batch_id"]]
    bid = out["batch_id"]

    # the absent detail joins as an empty file; its master-side match rate is 0, so the gate still asks for a reason
    res = run_batch(bid)
    assert res["status"] == "blocked" and "min_match_rate" in _batch(bid).error
    override_preflight(bid, "sme1", ["onboarding_reviewer"], "partial set accepted: no escrow items expected")
    run_batch(bid)
    b = _batch(bid)
    assert b.status == "completed", b.error
    assert b.join_summary["absent_roles"] == ["escrow_items"] and b.processed == 20  # on_missing_detail: allow
    assert all(s.record.get("tax_annual_amount") in (None, "") for s in _staging(bid))
    (ov,) = [a for a in _audit("fileset.override") if a.entity_id == m["set_id"]]
    assert ov.actor == "sme1" and ov.detail["action"] == "accept_partial" and ov.detail["missing_roles"] == ["escrow_items"]
    assert ov.detail["reason"] == "vendor confirmed no escrow items today"
    assert [a.entity_id for a in _audit("file_set.timeout")] == [m["set_id"]]


def test_e2e_legacy_feed_regression(client, env, sample_files):
    """The single-file sample flow through /api/upload is unchanged: no file set, no join, no layout in the bundle."""
    from lbp import config_store
    from lbp.mapping import service as ms
    from lbp.pipeline.batch import run_batch

    reg = ms.register_source("pcg_retail", sample_files["pcg_retail"], "analyst1")
    ms.accept_all(reg["mapping_id"], "analyst1", 0.0)
    ms.submit(reg["mapping_id"], "analyst1")
    ms.approve(reg["mapping_id"], "onboarding.reviewer", ["onboarding_reviewer"])
    sid = reg["source_id"]
    r = _upload(client, sid, sample_files["pcg_retail"], "PCG_20261117.csv")
    assert set(r) == {"batch_id", "status"} and r["status"] == "queued"
    run_batch(r["batch_id"])
    b = _batch(r["batch_id"])
    assert b.status == "completed", b.error
    assert b.processed == 300 and b.file_set_id is None and b.joined_path is None and b.join_summary is None
    assert "join" not in b.reconciliation
    assert "layout" not in config_store.bundle_json(sid)
    with db.get_engine().connect() as c:
        assert c.execute(select(func.count()).select_from(db.file_sets)).scalar() == 0
        assert c.execute(select(func.count()).select_from(db.batch_files)).scalar() == 0


def test_e2e_zip_upload_set(client, env):
    from lbp.pipeline.batch import run_batch
    from lbp.samples import generate_master_detail

    files = generate_master_detail(env / "src", N)
    sid = _feed(files)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files.values():
            z.write(p, p.name)
    r = client.post("/api/upload/set", data={"source_id": sid, "auto_start": "false"},
                    files=[("files", ("delivery_20261117.zip", buf.getvalue(), "application/zip"))], headers=OPS)
    assert r.status_code == 200, r.text
    res = r.json()
    assert sorted(x["role"] for x in res) == ["escrow_items", "master"] and len({x["set_id"] for x in res}) == 1
    (bid,) = [x["batch_id"] for x in res if x["batch_id"]]
    run_batch(bid)
    b = _batch(bid)
    assert b.status == "completed", b.error
    assert b.processed == N and b.filename == files["master"].name
    with db.get_engine().connect() as c:
        roles = sorted(x.role for x in c.execute(select(db.batch_files).where(db.batch_files.c.batch_id == bid)))
    assert roles == ["escrow_items", "master"]


@pytest.mark.parametrize("n", [12, 40])
def test_generate_master_detail_is_deterministic_and_noisy(env, n):
    from lbp.samples import generate_master_detail

    a = generate_master_detail(env / "a", n)
    b = generate_master_detail(env / "b", n)
    assert set(a) == {"master", "details"}
    assert a["master"].read_bytes() == b["master"].read_bytes() and a["details"].read_bytes() == b["details"].read_bytes()
    with open(a["master"], newline="") as f:
        ids = [r["LoanID"] for r in csv.DictReader(f)]
    rows = _detail_rows(a["details"])
    assert len(ids) == n and 2 * n <= len(rows) <= 4 * n + n
    per = {i: sum(1 for d in rows if _norm(d["LoanRef"]) == i) for i in ids}
    assert any(v == 0 for v in per.values())
    assert any(_norm(d["LoanRef"]) not in per for d in rows)
