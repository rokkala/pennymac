import pytest
from sqlalchemy import select

from lbp import config_store
from lbp.multifile.service import LayoutServiceError, decide_layout, propose_layout
from lbp.store import db

LAYOUT = {
    "files": [
        {"role": "master", "entity": "loan", "name_pattern": r"m_(?P<date>\d{8})\.csv", "key": ["id"], "required": True},
        {"role": "fees", "name_pattern": r"f_(?P<date>\d{8})\.csv", "required": False},
    ],
    "relations": [{"detail": "fees", "to": "master", "on": [{"parent": "id", "detail": "ref"}], "mode": "merge"}],
}
READY = {"require": "all_required", "pairing": "business_date"}
ANA, SME = ["analyst"], ["sme"]


def _audit_actions(sid):
    with db.get_engine().connect() as c:
        return [r.action for r in c.execute(select(db.audit_log).where(db.audit_log.c.entity_id == sid))]


def _src(sid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.sources).where(db.sources.c.source_id == sid)).first()


def test_propose_requires_role(onboarded):
    sid = onboarded["pcg_retail"]["source_id"]
    with pytest.raises(LayoutServiceError, match="role required"):
        propose_layout(sid, LAYOUT, READY, "bob", ["reviewer"])
    assert _src(sid).layout_draft is None


def test_invalid_layout_rejected_with_errors(onboarded):
    sid = onboarded["pcg_retail"]["source_id"]
    with pytest.raises(LayoutServiceError, match="exactly one master"):
        propose_layout(sid, {"files": [], "relations": []}, READY, "ana", ANA)
    assert _src(sid).layout_draft is None and "source.layout_propose" not in _audit_actions(sid)


def test_approver_must_differ_from_proposer(onboarded):
    sid = onboarded["pcg_retail"]["source_id"]
    propose_layout(sid, LAYOUT, READY, "sam", SME)
    with pytest.raises(LayoutServiceError, match="different user"):
        decide_layout(sid, "sam", SME, True)
    with pytest.raises(LayoutServiceError, match="SME role required"):
        decide_layout(sid, "ana", ANA, True)
    assert _src(sid).layout_draft is not None


def test_approve_publishes_bundle_and_audits(onboarded):
    sid = onboarded["pcg_retail"]["source_id"]
    out = propose_layout(sid, LAYOUT, READY, "ana", ANA)
    assert out["proposed_by"] == "ana" and out["readiness_draft"]["wait_timeout_minutes"] == 240
    assert _src(sid).layout is None
    decide_layout(sid, "sam", SME, True, "ok")
    s = _src(sid)
    assert s.layout["relations"][0]["cardinality"] == "one" and s.layout_draft is None and s.layout_proposed_by is None
    assert s.readiness["pairing"] == "business_date" and s.readiness_draft is None
    assert config_store.bundle_json(sid)["layout"] == s.layout
    assert config_store.load(sid).layout == s.layout
    acts = _audit_actions(sid)
    assert "source.layout_propose" in acts and "source.layout_approve" in acts
    with db.get_engine().connect() as c:
        reasons = [r.reason for r in c.execute(select(db.config_publications).where(db.config_publications.c.source_id == sid))]
    assert "layout approved" in reasons


def test_reject_clears_draft(onboarded):
    sid = onboarded["pcg_retail"]["source_id"]
    propose_layout(sid, LAYOUT, READY, "ana", ANA)
    decide_layout(sid, "sam", SME, False, "no")
    s = _src(sid)
    assert s.layout is None and s.layout_draft is None and s.readiness_draft is None
    assert "source.layout_reject" in _audit_actions(sid)
    with pytest.raises(LayoutServiceError, match="awaiting approval"):
        decide_layout(sid, "sam", SME, True)


def test_layout_endpoints_roundtrip(client, onboarded):
    sid = onboarded["pcg_retail"]["source_id"]
    an, sme = {"X-User": "ana", "X-Roles": "analyst"}, {"X-User": "sam", "X-Roles": "sme"}
    url = f"/api/sources/{sid}/layout"
    assert client.get(url).json()["configured"] is False
    assert client.get("/api/sources/nope/layout").status_code == 404
    assert client.put(url, json={"layout": LAYOUT, "readiness": READY}, headers={"X-User": "x", "X-Roles": "reviewer"}).status_code == 403
    assert client.put(url, json={"layout": {"files": []}, "readiness": READY}, headers=an).status_code == 400
    r = client.put(url, json={"layout": LAYOUT, "readiness": READY}, headers=an)
    assert r.status_code == 200, r.text
    g = client.get(url).json()
    assert g["draft"] and g["proposed_by"] == "ana" and not g["configured"]
    assert client.post(url + "/decide", json={"approve": True}, headers=an).status_code == 403
    assert client.post(url + "/decide", json={"approve": True}, headers={"X-User": "ana", "X-Roles": "sme"}).status_code == 400
    assert client.post(url + "/decide", json={"approve": True, "comment": "ok"}, headers=sme).status_code == 200
    g = client.get(url).json()
    assert g["configured"] and g["draft"] is None and g["layout"]["files"][0]["role"] == "master"


def test_publish_failure_after_approval_is_reported_not_silent(onboarded, monkeypatch):
    """I1: the approval commits, then publishing fails: decide_layout says so explicitly (the approval is saved,
    the feed must be republished) instead of returning success."""
    from lbp.multifile.service import LayoutPublishError

    sid = onboarded["pcg_retail"]["source_id"]
    propose_layout(sid, LAYOUT, READY, "ana", ANA)

    def boom(*_a, **_k):
        raise config_store.ConfigError("storage unavailable")

    monkeypatch.setattr(config_store, "publish", boom)
    with pytest.raises(LayoutPublishError, match="approved.*republish"):
        decide_layout(sid, "sam", SME, True, "ok")
    assert _src(sid).layout is not None
    assert "source.layout_publish_failed" in _audit_actions(sid)


def test_decide_endpoint_reports_publish_failure(client, onboarded, monkeypatch):
    sid = onboarded["pcg_retail"]["source_id"]
    an, sme = {"X-User": "ana", "X-Roles": "analyst"}, {"X-User": "sam", "X-Roles": "sme"}
    assert client.put(f"/api/sources/{sid}/layout", json={"layout": LAYOUT, "readiness": READY}, headers=an).status_code == 200

    def boom(*_a, **_k):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(config_store, "publish", boom)
    r = client.post(f"/api/sources/{sid}/layout/decide", json={"approve": True}, headers=sme)
    assert r.status_code == 502 and "republish" in r.json()["detail"] and "approved" in r.json()["detail"]


@pytest.mark.parametrize("load_type", ["snapshot", "incremental"])
def test_propose_refused_when_delivery_load_type_is_not_full(onboarded, load_type):
    """I5: Phase 1 multi-file feeds load as full; a feed delivered as snapshot/incremental cannot get a layout."""
    sid = onboarded["pcg_retail"]["source_id"]
    with db.get_engine().begin() as c:
        c.execute(db.sources.update().where(db.sources.c.source_id == sid).values(delivery={"load_type": load_type}))
    with pytest.raises(LayoutServiceError, match=f"{load_type}.*full"):
        propose_layout(sid, LAYOUT, READY, "ana", ANA)
    assert _src(sid).layout_draft is None
