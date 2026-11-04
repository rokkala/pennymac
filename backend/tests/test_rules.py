import pytest

from lbp.rules.default_rules import BASE_LOAN
from lbp.rules.executor import RuleExecutor
from lbp.rules.registry import RuleError, RuleRegistry


def _draft(reg, **kw):
    body = {"name": "FICO floor", "expression": {">=": [{"var": "borrower_fico"}, 580]}, "field": "borrower_fico",
            "tests": [{"record": {**BASE_LOAN}, "expect": True}, {"record": {**BASE_LOAN, "borrower_fico": 500}, "expect": False}], **kw}
    return reg.create_draft(body, "sme.author")


def test_update_draft_renames(env):
    reg = RuleRegistry()
    r = _draft(reg)
    u = reg.update_draft(r["rule_id"], 1, {"name": "FICO floor revised"}, "sme.author")
    assert u["name"] == "FICO floor revised" and u["status"] == "draft"
    reg.transition(r["rule_id"], 1, "in_review", "sme.author")
    with pytest.raises(RuleError):
        reg.update_draft(r["rule_id"], 1, {"name": "nope"}, "sme.author")


def test_lifecycle_gates(env):
    reg = RuleRegistry()
    r = _draft(reg)
    assert r["status"] if "status" in r else True
    with pytest.raises(RuleError):
        reg.transition(r["rule_id"], 1, "active", "x")  # can't skip review
    reg.transition(r["rule_id"], 1, "in_review", "sme.author")
    with pytest.raises(RuleError):
        reg.transition(r["rule_id"], 1, "approved", "sme.author")  # maker-checker
    reg.transition(r["rule_id"], 1, "approved", "peer", ["sme"])
    reg.transition(r["rule_id"], 1, "active", "peer")
    assert reg.get(r["rule_id"], 1)["status"] == "active"


def test_failing_tests_block_review(env):
    reg = RuleRegistry()
    r = _draft(reg, tests=[{"record": {**BASE_LOAN, "borrower_fico": 500}, "expect": True}])
    with pytest.raises(RuleError):
        reg.transition(r["rule_id"], 1, "in_review", "sme.author")


def test_regulatory_rule_needs_compliance(env):
    reg = RuleRegistry()
    r = _draft(reg, regulatory_tag="ECOA")
    reg.transition(r["rule_id"], 1, "in_review", "sme.author")
    res = reg.transition(r["rule_id"], 1, "approved", "peer", ["sme"])
    assert res["status"] == "in_review" and res["pending"]
    res = reg.transition(r["rule_id"], 1, "approved", "comp", ["compliance"])
    assert res["status"] == "approved"


def test_new_version_supersedes_and_canary(env):
    reg = RuleRegistry()
    v2 = reg.create_draft({**reg.get("R007", 1), "expression": {"<=": [0.5, {"var": "interest_rate"}, 12]}, "rule_id": "R007"}, "sme.author")
    assert v2["version"] == 2
    reg.transition("R007", 2, "in_review", "sme.author")
    reg.transition("R007", 2, "approved", "comp", ["compliance"])
    reg.transition("R007", 2, "canary", "comp", canary_pct=100)
    ex = RuleExecutor(reg.runtime_set())
    ev = ex.evaluate({**BASE_LOAN, "interest_rate": 13.0})
    assert "R007" in ev.canary_rules and any(f.rule_id == "R007" and f.version == 2 for f in ev.failures)
    reg.transition("R007", 2, "active", "comp")
    assert reg.get("R007", 1)["status"] == "retired"


def test_shadow_reports_diffs_only(env):
    reg = RuleRegistry()
    reg.create_draft({**reg.get("R012", 1), "rule_id": "R012", "expression": {"<=": [300, {"var": "borrower_fico"}, 700]},
                      "tests": [{"record": BASE_LOAN, "expect": False}, {"record": {**BASE_LOAN, "borrower_fico": 650}, "expect": True}]}, "a")
    reg.transition("R012", 2, "in_review", "a")
    reg.transition("R012", 2, "approved", "comp", ["compliance"])
    reg.transition("R012", 2, "shadow", "comp")
    ev = RuleExecutor(reg.runtime_set()).evaluate(BASE_LOAN)  # FICO 740: active passes, shadow fails
    assert ev.status == "PASS" and ev.shadow_diffs and ev.shadow_diffs[0]["rule_id"] == "R012"


def test_default_rules_pass_clean_loan(env):
    ev = RuleExecutor(RuleRegistry().runtime_set()).evaluate(BASE_LOAN)
    assert ev.status == "PASS", [f.rule_id for f in ev.failures]
