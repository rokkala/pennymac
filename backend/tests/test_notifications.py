"""In-app notifications for rule peer review."""
from lbp import notifications as ntf
from lbp.rules.default_rules import BASE_LOAN
from lbp.rules.registry import RuleRegistry


def _draft(reg, actor="onboarding.reviewer", **kw):
    body = {
        "name": "FICO floor",
        "expression": {">=": [{"var": "borrower_fico"}, 580]},
        "field": "borrower_fico",
        "tests": [
            {"record": {**BASE_LOAN}, "expect": True},
            {"record": {**BASE_LOAN, "borrower_fico": 500}, "expect": False},
        ],
        **kw,
    }
    return reg.create_draft(body, actor)


def test_submit_notifies_peer_pool_not_author(env):
    reg = RuleRegistry()
    r = _draft(reg)
    reg.transition(r["rule_id"], 1, "in_review", "onboarding.reviewer")
    for peer in ntf.list_for("compliance.reviewer"):
        if peer["kind"] == "rule.in_review" and r["rule_id"] in (peer.get("entity_id") or ""):
            break
    else:
        assert False, "compliance.reviewer should be notified"
    assert all(x["kind"] != "rule.in_review" or x["entity_id"] != r["rule_id"] for x in ntf.list_for("onboarding.reviewer"))


def test_author_cannot_approve_peer_can_and_author_notified(env):
    reg = RuleRegistry()
    r = _draft(reg)
    reg.transition(r["rule_id"], 1, "in_review", "onboarding.reviewer")
    try:
        reg.transition(r["rule_id"], 1, "approved", "onboarding.reviewer", ["onboarding_reviewer"])
        assert False, "author must not approve"
    except Exception as e:
        assert "maker-checker" in str(e).lower()
    reg.transition(r["rule_id"], 1, "approved", "compliance.reviewer", ["compliance_reviewer"])
    kinds = {x["kind"] for x in ntf.list_for("onboarding.reviewer")}
    assert "rule.approved" in kinds


def test_delete_rule_removes_all_versions(env):
    reg = RuleRegistry()
    r = _draft(reg)
    rid = r["rule_id"]
    out = reg.delete_rule(rid, "onboarding.reviewer", "cleanup")
    assert out["ok"] and out["versions_removed"] >= 1
    assert reg.versions(rid) == []
    try:
        reg.delete_rule(rid, "onboarding.reviewer")
        assert False, "expected not found"
    except Exception as e:
        assert "not found" in str(e).lower()


def test_delete_rule_api(client):
    h = {"X-User": "onboarding.reviewer", "X-Roles": "onboarding_reviewer"}
    created = client.post(
        "/api/rules",
        json={"name": "Temp", "tree": {"shape": "between", "field": "interest_rate", "min": 1, "max": 10}},
        headers=h,
    )
    assert created.status_code == 200, created.text
    rid = created.json()["rule_id"]
    assert client.delete(f"/api/rules/{rid}?reason=cleanup", headers=h).status_code == 200
    assert client.get(f"/api/rules/{rid}", headers=h).status_code == 404
    assert client.delete("/api/rules/R999", headers={"X-User": "monitoring", "X-Roles": "monitoring"}).status_code == 403


def test_submitter_cannot_approve_even_if_author_field_cleared(env):
    """Fail closed: missing author must not allow self-approve; submitter is also blocked."""
    reg = RuleRegistry()
    r = _draft(reg, actor="onboarding.reviewer")
    reg.transition(r["rule_id"], 1, "in_review", "onboarding.reviewer")
    body = reg.get(r["rule_id"], 1)
    body.pop("author", None)
    body.pop("owner", None)
    reg.store.put(body, "in_review")
    try:
        reg.transition(r["rule_id"], 1, "approved", "onboarding.reviewer", ["onboarding_reviewer"])
        assert False, "must not approve without author / as submitter"
    except Exception as e:
        assert "maker-checker" in str(e).lower()


def test_notifications_api(client):
    h_onb = {"X-User": "onboarding.reviewer", "X-Roles": "onboarding_reviewer"}
    h_comp = {"X-User": "compliance.reviewer", "X-Roles": "compliance_reviewer"}
    create = client.post(
        "/api/rules",
        json={
            "name": "Rate band",
            "tree": {"shape": "between", "field": "interest_rate", "min": 0.5, "max": 15},
        },
        headers=h_onb,
    )
    assert create.status_code == 200, create.text
    rid, ver = create.json()["rule_id"], create.json()["version"]
    sub = client.post(f"/api/rules/{rid}/{ver}/transition", json={"to": "in_review", "comment": "please review"}, headers=h_onb)
    assert sub.status_code == 200, sub.text

    inbox = client.get("/api/notifications", headers=h_comp)
    assert inbox.status_code == 200
    assert inbox.json()["unread"] >= 1
    assert any(n["kind"] == "rule.in_review" for n in inbox.json()["notifications"])

    waiting = client.get("/api/rules?queue=awaiting_review", headers=h_comp)
    assert waiting.status_code == 200
    assert any(r["rule_id"] == rid for r in waiting.json()["rules"])

    mine = client.get("/api/rules?queue=awaiting_review", headers=h_onb)
    assert all(r["rule_id"] != rid for r in mine.json()["rules"])
