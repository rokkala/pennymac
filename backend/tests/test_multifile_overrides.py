"""File-set overrides (Task 12): accept_partial, discard, repair; role/reason gate, merge into override, audit."""
from datetime import timedelta

import pytest
from sqlalchemy import update

from lbp.multifile.fileset import FileSetError, override_set
from lbp.store import db
from tests import test_multifile_fileset as base
from tests.test_multifile_fileset import BORR, LAYOUT, MASTER, READY, T0, _attach, _audit, _batches, _configure, _members, _set, expire_sets

feed = base.feed  # the feed fixture of the file-set tests

SME = ["onboarding_reviewer"]


def test_override_requires_reason_and_role(env, feed):
    a = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    with pytest.raises(FileSetError, match="reason"):
        override_set(a["set_id"], "discard", "sme1", SME, "  ")
    with pytest.raises(FileSetError, match="role"):
        override_set(a["set_id"], "discard", "ops1", ["monitoring"], "no")
    with pytest.raises(FileSetError, match="unknown"):
        override_set(a["set_id"], "explode", "sme1", SME, "no")
    assert _set(a["set_id"]).status == "waiting" and not _audit("fileset.override")
    # compliance and admin are accepted
    override_set(a["set_id"], "discard", "c1", ["compliance_reviewer"], "bad delivery")
    assert _set(a["set_id"]).status == "discarded"


def test_accept_partial_loads_with_missing_detail_policy_and_audits(env, feed):
    _configure(feed, LAYOUT, {**READY, "on_timeout": "fail"})
    a = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    expire_sets(T0 + timedelta(minutes=241))
    assert _set(a["set_id"]).status == "expired"
    with db.get_engine().begin() as c:  # an earlier marker must survive the override
        c.execute(update(db.file_sets).where(db.file_sets.c.set_id == a["set_id"]).values(
            override={**_set(a["set_id"]).override, "note": "kept"}))
    out = override_set(a["set_id"], "accept_partial", "sme1", SME, "vendor confirmed details are late")
    s = _set(a["set_id"])
    assert out["batch_id"] and s.status == "consumed" and s.batch_id == out["batch_id"]
    assert [b.batch_id for b in _batches(feed)] == [out["batch_id"]]
    assert s.override["note"] == "kept" and s.override["timeout"]["action"] == "fail"
    ov = s.override["overrides"][-1]
    assert ov["action"] == "accept_partial" and ov["actor"] == "sme1" and ov["reason"] and ov["missing_roles"] == ["borrowers"]
    (row,) = _audit("fileset.override")
    assert row.entity_id == a["set_id"] and row.detail["missing_roles"] == ["borrowers"] and row.detail["reason"]
    assert [m.role for m in _members(a["set_id"])] == ["master"]
    # a set without the master cannot be accepted
    b = _attach(env, feed, "borrowers_20261118.csv", BORR, T0)
    with pytest.raises(FileSetError, match="master"):
        override_set(b["set_id"], "accept_partial", "sme1", SME, "try")
    assert _set(b["set_id"]).status == "waiting"


def test_discard_waiting_set(env, feed):
    a = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    out = override_set(a["set_id"], "discard", "sme1", SME, "wrong file")
    s = _set(a["set_id"])
    assert out["status"] == "discarded" and s.status == "discarded" and not _batches(feed)
    assert s.override["overrides"][0]["reason"] == "wrong file"
    assert _audit("fileset.override")[0].detail["action"] == "discard"
    with pytest.raises(FileSetError, match="discarded"):  # nothing to do on a discarded set
        override_set(a["set_id"], "discard", "sme1", SME, "again")


def test_repair_moves_member_before_batch_only(env, feed):
    wrong = _attach(env, feed, "borrowers_20261117.csv", BORR, T0)
    # the borrowers file really belongs to the 20261118 delivery: move it to that (new) set
    out = override_set(wrong["set_id"], "repair", "sme1", SME, "misrouted detail", target_pairing_key="20261118", member_role="borrowers")
    tgt = out["target_set_id"]
    assert tgt != wrong["set_id"] and _set(tgt).status == "waiting" and _set(tgt).pairing_key == "20261118"
    assert not _members(wrong["set_id"]) and _set(wrong["set_id"]).status == "discarded"
    assert [m.role for m in _members(tgt)] == ["borrowers"]
    assert _set(wrong["set_id"]).override["overrides"][0]["to_set"] == tgt
    # the master for that date arrives: the target joins and is queued
    done = _attach(env, feed, "loans_20261118.csv", MASTER + "3,300\n", T0)
    assert done["set_id"] == tgt and done["status"] == "consumed"
    # moving the last member leaves the source empty -> discarded; target re-evaluated
    other = _attach(env, feed, "loans_20261119.csv", MASTER, T0)
    moved = override_set(other["set_id"], "repair", "sme1", SME, "wrong day", target_pairing_key="20261120")
    assert _set(other["set_id"]).status == "discarded" and not _members(other["set_id"])
    assert moved["role"] == "master"
    m0 = _attach(env, feed, "loans_20261130.csv", MASTER, T0)
    with pytest.raises(FileSetError, match="member_role"):
        override_set(m0["set_id"], "repair", "sme1", SME, "x", target_pairing_key="20261121", member_role="nope")
    # target completes through repair: the moved master joins a waiting set holding the detail
    d = _attach(env, feed, "borrowers_20261122.csv", BORR, T0)
    m = _attach(env, feed, "loans_20261123.csv", MASTER, T0)
    r = override_set(m["set_id"], "repair", "sme1", SME, "date typo", target_pairing_key="20261122")
    assert r["target_set_id"] == d["set_id"] and r["target_status"] == "consumed" and r["batch_id"]
    # a consumed set cannot be repaired
    with pytest.raises(FileSetError, match="queued|consumed"):
        override_set(d["set_id"], "repair", "sme1", SME, "late", target_pairing_key="20261124")


def test_override_after_batch_queued_rejected(env, feed):
    _attach(env, feed, "borrowers_20261117.csv", BORR, T0)
    done = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    assert done["status"] == "consumed"
    n = len(_batches(feed))
    for action in ("accept_partial", "discard", "repair"):
        with pytest.raises(FileSetError, match="queued|consumed"):
            override_set(done["set_id"], action, "sme1", SME, "too late", target_pairing_key="20261118", member_role="borrowers")
    assert _set(done["set_id"]).status == "consumed" and len(_batches(feed)) == n and not _audit("fileset.override")


def test_file_sets_endpoints(client, env, feed):
    a = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    rows = client.get("/api/file-sets", params={"source_id": feed, "status": "waiting"}).json()
    assert [r["set_id"] for r in rows] == [a["set_id"]]
    r = rows[0]
    assert r["members"][0]["role"] == "master" and r["members"][0]["filename"] == "loans_20261117.csv"
    assert "file_path" not in r["members"][0] and r["pairing_key"] == "20261117" and r["expires_at"]
    assert client.get("/api/file-sets", params={"status": "ready"}).json() == []
    url = f"/api/file-sets/{a['set_id']}/override"
    assert client.post(url, json={"action": "discard", "reason": "x"}, headers={"x-user": "m", "x-roles": "monitoring"}).status_code == 403
    bad = client.post(url, json={"action": "discard", "reason": ""}, headers={"x-user": "s", "x-roles": "onboarding_reviewer"})
    assert bad.status_code == 400
    ok = client.post(url, json={"action": "discard", "reason": "wrong"}, headers={"x-user": "s", "x-roles": "onboarding_reviewer"})
    assert ok.status_code == 200 and ok.json()["status"] == "discarded"
