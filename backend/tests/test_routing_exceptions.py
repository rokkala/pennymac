import pytest
from sqlalchemy import select

from lbp.exceptions.manager import ExceptionActionError, ExceptionManager, Triage
from lbp.exceptions.policy import DEFAULT_POLICY, PolicyError, route, set_policy
from lbp.pipeline.batch import create_batch, run_batch
from lbp.rules.default_rules import BASE_LOAN
from lbp.store import db


def test_routing_matrix():
    p = DEFAULT_POLICY
    assert route(0.99, "low", "format", "format", p) == "T1"
    assert route(0.97, "medium", "format", "format", p) == "T1"  # pure formatting downgrade
    assert route(0.97, "medium", "format", "derive", p) == "T2"
    assert route(0.85, "medium", "range", None, p) == "T2"
    assert route(0.6, "low", "range", None, p) == "T3"
    assert route(0.99, "high", "range", "scale", p) == "T4"  # never auto-apply regulated fields
    assert route(0.99, "low", "compliance", None, p) == "T5"
    assert route(None, "critical", "fraud", None, p) == "T5"


def test_triage_proposals(env):
    t = Triage(rng_seed=1)
    ex = t.classify_and_propose("R005", "state", "format", "FAIL", "property_state", {**BASE_LOAN, "property_state": "XX", "property_zip": "75024"}, "m")
    assert ex["proposal"]["value"] == "TX" and ex["tier"] == "T2"
    ex = t.classify_and_propose("R012", "fico", "range", "FAIL", "borrower_fico", {**BASE_LOAN, "borrower_fico": 7400}, "m")
    assert ex["proposal"]["value"] == 740 and ex["tier"] == "T4" and ex["proposal"]["hint_only"]
    ex = t.classify_and_propose("R019", "ofac", "compliance", "FAIL", "ofac_check_status", {**BASE_LOAN, "ofac_check_status": "H"}, "m")
    assert ex["tier"] == "T5" and ex["proposal"] is None


def test_policy_change_requires_compliance(env):
    with pytest.raises(PolicyError):
        set_policy({"qa_sample_pct": 10}, "analyst", "analyst", ["compliance_reviewer"])
    with pytest.raises(PolicyError):
        set_policy({"qa_sample_pct": 10}, "analyst", "bob", ["onboarding_reviewer"])
    with pytest.raises(PolicyError):
        set_policy({"t1_min_confidence": 0.5}, "analyst", "comp", ["compliance"])  # member ≠ reviewer
    assert set_policy({"qa_sample_pct": 10}, "analyst", "comp", ["compliance_reviewer"])["qa_sample_pct"] == 10


def _batch(onboarded, key="pcg_retail"):
    src = onboarded[key]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "ops1")
    run_batch(bid, workers=1, micro_batch_size=100)
    return bid


def test_pipeline_reconciles(onboarded):
    for key in onboarded:
        bid = _batch(onboarded, key)
        with db.get_engine().connect() as c:
            b = c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first()
        assert b.status == "completed" and b.reconciliation["balanced"], b.reconciliation
        assert b.processed == 300 and b.loaded >= 270


def test_t2_resolution_boards_loan(onboarded):
    _batch(onboarded)
    m = ExceptionManager()
    items = m.list(status="open", tier="T2")["items"]
    single = [i for i in items if len([x for x in m.list(status="open")["items"] if x["staging_id"] == i["staging_id"]]) == 1]
    assert single, "expected at least one single-exception T2 loan"
    ex = single[0]
    res = m.resolve(ex["exception_id"], "reviewer1", ["reviewer"], use_proposal=True)
    assert res["status"] == "resolved" and res["loan_boarded"]


def test_t4_maker_checker(onboarded):
    _batch(onboarded)
    m = ExceptionManager()
    ex = m.list(status="open", tier="T4")["items"][0]
    rec = m.get(ex["exception_id"], ["admin"])["loan_record"]
    from lbp.rules.default_rules import BASE_LOAN as B

    good = B.get(ex["field"], rec.get(ex["field"]))
    r = m.resolve(ex["exception_id"], "maker1", ["reviewer"], value=good)
    assert r["status"] == "pending_checker"
    with pytest.raises(ExceptionActionError):
        m.checker_decision(ex["exception_id"], "maker1", ["checker"], True)
    r = m.checker_decision(ex["exception_id"], "checker1", ["checker"], True)
    assert r["status"] == "resolved"


def test_t5_only_compliance(onboarded):
    for k in onboarded:
        _batch(onboarded, k)
    m = ExceptionManager()
    t5 = m.list(status="escalated", tier="T5")["items"]
    assert t5
    with pytest.raises(ExceptionActionError):
        m.resolve(t5[0]["exception_id"], "reviewer1", ["reviewer"], value="C")
    with pytest.raises(ExceptionActionError):
        m.compliance_clear(t5[0]["exception_id"], "reviewer1", ["reviewer"], "C", "note")
    r = m.reject_loan(t5[0]["exception_id"], "comp1", ["compliance_reviewer"], "confirmed OFAC match")
    assert r["status"] == "rejected"


def test_pause_and_resume_from_checkpoint(onboarded):
    from lbp.pipeline import batch as pl

    src = onboarded["sub_servicing"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "ops1")
    original = pl._persist_chunk
    calls = {"n": 0}

    def spy(*a, **k):
        calls["n"] += 1
        out = original(*a, **k)
        if calls["n"] == 1:
            pl.request_pause(bid, "ops1")
        return out

    pl._persist_chunk = spy
    try:
        run_batch(bid, workers=1, micro_batch_size=100)
    finally:
        pl._persist_chunk = original
    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first()
    assert b.status == "paused" and b.checkpoint == 100
    run_batch(bid, workers=1, micro_batch_size=100)
    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first()
    assert b.status == "completed" and b.processed == 300 and b.reconciliation["balanced"]


def test_bulk_resolve(onboarded):
    for k in onboarded:
        _batch(onboarded, k)
    m = ExceptionManager()
    items = [i for i in m.list(status="open", limit=1000)["items"] if i["tier"] in ("T2", "T3") and i["proposal"]]
    if not items:
        pytest.skip("no bulk candidates in this sample")
    it = items[0]
    res = m.bulk_resolve("rev1", ["reviewer"], it["rule_id"], it["original_value"], use_proposal=True)
    assert res["resolved"] >= 1


def test_t1_kill_switch_and_auto_suspend(env):
    from lbp.exceptions.policy import effective_policy

    t = Triage(rng_seed=1)
    ex = t.classify_and_propose("R016", "occ", "format", "FAIL", "occupancy_type", {**BASE_LOAN, "occupancy_type": "owner"}, "m")
    assert ex["tier"] == "T1"
    # emergency off: one Compliance · Reviewer may switch auto-apply off (never on) alone
    set_policy({"t1_enabled": False}, "comp1", "comp1", ["compliance_reviewer"])
    ex = Triage(rng_seed=1).classify_and_propose("R016", "occ", "format", "FAIL", "occupancy_type", {**BASE_LOAN, "occupancy_type": "owner"}, "m")
    assert ex["tier"] == "T2"
    with pytest.raises(PolicyError):
        set_policy({"t1_enabled": True}, "comp1", "comp1", ["compliance_reviewer"])
    set_policy({"t1_enabled": True}, "comp1", "comp2", ["compliance_reviewer"])
    # auto-suspend: override rate above the 2% control limit with enough sample
    with db.get_engine().begin() as c:
        for i in range(60):
            c.execute(db.exceptions.insert().values(exception_id=f"ex_t1_{i}", tier="T1", status="auto_applied", rule_id="R016",
                                                    field="occupancy_type", created_at=db.now()))
        for i in range(3):
            db.audit(c, "rev", "exception.rollback", "exception", f"ex_t1_{i}")
    eff = effective_policy()
    assert eff["t1_auto_suspended"] and not eff["t1_effective"] and eff["t1_health"]["override_rate_pct"] == 5.0
    ex = Triage(rng_seed=1).classify_and_propose("R016", "occ", "format", "FAIL", "occupancy_type", {**BASE_LOAN, "occupancy_type": "owner"}, "m")
    assert ex["tier"] == "T2"
