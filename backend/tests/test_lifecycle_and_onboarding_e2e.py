"""End to end over HTTP: onboard a two-file feed from sample files, approve it, deliver, load, then archive,
restore, discard and delete."""
import json

from sqlalchemy import select

from lbp import samples
from lbp.store import db

ONB = {"X-User": "ana", "X-Roles": "onboarding"}
REV = {"X-User": "rev", "X-Roles": "onboarding_reviewer"}
OPS = {"X-User": "oli", "X-Roles": "ops"}
ADMIN = {"X-User": "root", "X-Roles": "admin"}


def _create(client, files, name="Escrow two-file"):
    with open(files["master"], "rb") as m, open(files["details"], "rb") as d:
        r = client.post("/api/multi-file-feeds",
                        data={"name": name, "description": "e2e",
                              "layout": json.dumps(samples.master_detail_layout()),
                              "readiness": json.dumps(samples.master_detail_readiness())},
                        files={"master": (files["master"].name, m), "escrow_items": (files["details"].name, d)},
                        headers=ONB)
    assert r.status_code == 200, r.text
    return r.json()


def _approve(client, reg):
    mid, sid = reg["mapping_id"], reg["source_id"]
    assert client.post(f"/api/mappings/{mid}/accept-all?min_confidence=0", headers=ONB).status_code == 200
    r = client.post(f"/api/mappings/{mid}/submit", headers=ONB)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/mappings/{mid}/approve", json={"approve": True, "comment": "ok"}, headers=REV)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/sources/{sid}/layout/decide", json={"approve": True, "comment": "ok"}, headers=REV)
    assert r.status_code == 200, r.text


def _deliver(client, sid, files):
    with open(files["master"], "rb") as m, open(files["details"], "rb") as d:
        return client.post("/api/upload/set", data={"source_id": sid, "auto_start": "false"},
                           files=[("files", (files["master"].name, m)), ("files", (files["details"].name, d))],
                           headers=OPS)


def _ids(client, **params):
    return [s["source_id"] for s in client.get("/api/sources", params=params).json()["sources"]]


def test_onboard_load_archive_restore_discard_delete(client, env):
    from lbp.pipeline.batch import run_batch

    files = samples.generate_master_detail(env / "src", 40, date="20261117", seed=7, offset=10_000)
    reg = _create(client, files)
    sid, mid = reg["source_id"], reg["mapping_id"]

    # a draft mapping can be discarded; an approved one cannot
    _approve(client, reg)
    r = client.post(f"/api/mappings/{mid}/discard", json={"reason": "no longer needed"}, headers=ONB)
    assert r.status_code == 400 and "approved" in r.json()["detail"]

    # deliver both files and load the set
    r = _deliver(client, sid, files)
    assert r.status_code == 200, r.text
    parts = r.json()
    assert {p["role"] for p in parts} == {"master", "escrow_items"}
    bid = next(p["batch_id"] for p in parts if p["batch_id"])
    run_batch(bid)
    b = client.get(f"/api/batches/{bid}").json()
    assert b["status"] == "completed", b
    assert b["loaded"] > 0

    # a feed with history cannot be deleted, even by an admin
    r = client.request("DELETE", f"/api/sources/{sid}", params={"reason": "cleanup attempt"}, headers=ADMIN)
    assert r.status_code == 400 and "archive it instead" in r.json()["detail"]
    assert sid in _ids(client)

    # archive: onboarding alone cannot archive a live feed, a reviewer can
    r = client.post(f"/api/sources/{sid}/archive", json={"reason": "vendor stopped sending"}, headers=ONB)
    assert r.status_code in (400, 403)
    r = client.post(f"/api/sources/{sid}/archive", json={"reason": "vendor stopped sending"}, headers=REV)
    assert r.status_code == 200, r.text
    r = _deliver(client, sid, files)
    assert r.status_code == 409, r.text
    assert sid not in _ids(client)
    shown = client.get("/api/sources", params={"include_archived": "true"}).json()["sources"]
    row = next(s for s in shown if s["source_id"] == sid)
    assert row["status"] == "retired" and row["retired_reason"] == "vendor stopped sending"

    # restore: deliveries are accepted again
    r = client.post(f"/api/sources/{sid}/restore", json={"reason": "vendor is back"}, headers=REV)
    assert r.status_code == 200, r.text
    assert sid in _ids(client)
    # (the first delivery is already loaded, so the vendor sends the next day's files)
    nxt = samples.generate_master_detail(env / "next", 40, date="20261118", seed=8, offset=10_000)
    r = _deliver(client, sid, nxt)
    assert r.status_code == 200, r.text
    assert any(p["batch_id"] for p in r.json())


def test_discard_draft_and_delete_unused_feed(client, env):
    files = samples.generate_master_detail(env / "src", 40, date="20261117", seed=7, offset=10_000)
    reg = _create(client, files)
    sid, mid = reg["source_id"], reg["mapping_id"]

    # too-short reason is refused; a draft is discarded
    r = client.post(f"/api/mappings/{mid}/discard", json={"reason": "no"}, headers=ONB)
    assert r.status_code == 400
    r = client.post(f"/api/mappings/{mid}/discard", json={"reason": "wrong sample files"}, headers=ONB)
    assert r.status_code == 200 and r.json()["status"] == "discarded"

    # only an administrator may delete; a never-used feed goes
    r = client.request("DELETE", f"/api/sources/{sid}", params={"reason": "created by mistake"}, headers=REV)
    assert r.status_code in (400, 403)
    r = client.request("DELETE", f"/api/sources/{sid}", params={"reason": "created by mistake"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert sid not in _ids(client, include_archived="true")
    with db.get_engine().connect() as c:
        assert c.execute(select(db.mappings).where(db.mappings.c.source_id == sid)).first() is None
