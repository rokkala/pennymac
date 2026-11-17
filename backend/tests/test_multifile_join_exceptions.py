"""Join exceptions in the Exception Manager (final review C1): they have no staged loan (staging_id NULL), so no
action may scope by staging_id. They are acknowledged/closed with a reason; never value-resolved or reject-loan'd."""
import pytest
from sqlalchemy import select

from lbp.exceptions.manager import ExceptionActionError, ExceptionManager
from lbp.store import db

MON = ["monitoring"]


def _insert(eid, batch, code="JOIN01", category="join", status="open", tier="T3", staging_id=None):
    with db.get_engine().begin() as c:
        c.execute(db.exceptions.insert().values(
            exception_id=eid, batch_id=batch, source_id="src_x", loan_number="tok_abc", staging_id=staging_id, rule_id=code,
            rule_version=1, rule_name=code, category=category, severity="FAIL", blocking=True, field="loan_id",
            original_value='{"loan_id": "1"}', message="m", risk="medium", tier=tier, queue="join", status=status,
            role="master" if category == "join" else None, proposal={"value": "9", "confidence": 0.99} if category != "join" else None))


def _statuses():
    with db.get_engine().connect() as c:
        return {r.exception_id: r.status for r in c.execute(select(db.exceptions.c.exception_id, db.exceptions.c.status))}


@pytest.fixture()
def joins(env):
    db.metadata.create_all(db.get_engine())
    _insert("ex0", "bat_A", "JOIN01")
    _insert("ex1", "bat_A", "JOIN02")
    _insert("ex2", "bat_OTHER_FEED", "JOIN05")
    return ExceptionManager()


def test_reject_loan_on_a_join_exception_is_refused_and_touches_nothing(joins):
    with pytest.raises(ExceptionActionError, match="join"):
        joins.reject_loan("ex0", "u", MON, "r")
    assert _statuses() == {"ex0": "open", "ex1": "open", "ex2": "open"}


def test_reject_loan_without_staged_row_is_scoped_to_the_exception(joins):
    """A non-join exception with no staged row (defence in depth): only that exception is rejected."""
    _insert("ex3", "bat_B", "R001", category="format")
    _insert("ex4", "bat_C", "R001", category="format")
    joins.reject_loan("ex3", "u", MON, "r")
    assert _statuses() == {"ex0": "open", "ex1": "open", "ex2": "open", "ex3": "rejected", "ex4": "open"}


def test_get_does_not_list_unrelated_null_staging_rows(joins):
    ex = joins.get("ex0", MON)
    assert ex["related"] == [] and ex["loan_record"] == {} and ex["loan_status"] is None


def test_join_exceptions_cannot_be_value_resolved(joins):
    with pytest.raises(ExceptionActionError, match="join"):
        joins.resolve("ex0", "u", MON, value="123")
    with pytest.raises(ExceptionActionError, match="join"):
        joins.resolve("ex0", "u", MON, use_proposal=True)
    out = joins.bulk_resolve("u", MON, "JOIN01", '{"loan_id": "1"}', value="x")
    assert out["matched"] == 0 and out["resolved"] == 0
    with pytest.raises(ExceptionActionError, match="join"):
        joins.compliance_clear("ex0", "u", ["compliance_reviewer"], "x", "note")
    with pytest.raises(ExceptionActionError, match="join"):
        joins.ai_suggest("ex0")
    with db.get_engine().connect() as c:
        assert c.execute(select(db.precedents)).all() == []
    assert _statuses() == {"ex0": "open", "ex1": "open", "ex2": "open"}


def test_acknowledge_closes_one_join_exception_with_a_reason_and_audits(joins):
    with pytest.raises(ExceptionActionError, match="reason"):
        joins.acknowledge("ex0", "u", MON, "  ")
    out = joins.acknowledge("ex0", "u", MON, "vendor confirmed orphan row; resend not needed")
    assert out == {"exception_id": "ex0", "status": "resolved"}
    assert _statuses() == {"ex0": "resolved", "ex1": "open", "ex2": "open"}
    with db.get_engine().connect() as c:
        row = c.execute(select(db.exceptions).where(db.exceptions.c.exception_id == "ex0")).first()
        a = c.execute(select(db.audit_log).where(db.audit_log.c.entity_id == "ex0")).all()
        assert c.execute(select(db.precedents)).all() == []
    assert row.maker == "u" and row.resolved_at is not None and row.resolved_value is None
    assert [x.action for x in a] == ["exception.join_acknowledged"] and a[0].detail["reason"].startswith("vendor confirmed")
    with pytest.raises(ExceptionActionError, match="status"):
        joins.acknowledge("ex0", "u", MON, "again")
    # escalated join exceptions can still be closed
    joins.escalate("ex1", "u", MON, "look")
    joins.acknowledge("ex1", "u", MON, "checked")
    assert _statuses()["ex1"] == "resolved"


def test_acknowledge_is_only_for_join_exceptions(joins):
    _insert("ex3", "bat_B", "R001", category="format", staging_id=1)
    with pytest.raises(ExceptionActionError, match="join"):
        joins.acknowledge("ex3", "u", MON, "r")


def test_acknowledge_api(client):
    db.metadata.create_all(db.get_engine())
    _insert("ex0", "bat_A", "JOIN01")
    _insert("ex1", "bat_A", "JOIN02")
    ops = {"X-User": "oli", "X-Roles": "ops"}
    assert client.post("/api/exceptions/ex0/reject", json={"reason": "r"}, headers=ops).status_code == 400
    assert client.post("/api/exceptions/ex0/acknowledge", json={"reason": "r"}, headers={"X-User": "a", "X-Roles": "analyst"}).status_code == 403
    r = client.post("/api/exceptions/ex0/acknowledge", json={"reason": "orphan explained"}, headers=ops)
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    assert client.post("/api/exceptions/ex1/acknowledge", json={"reason": ""}, headers=ops).status_code == 400
    assert _statuses() == {"ex0": "resolved", "ex1": "open"}


# ------------------------------------------------------------------ I7: keyed join-key fingerprint
def test_join_key_fingerprint_is_keyed_not_a_plain_hash(env, monkeypatch):
    import hashlib
    import hmac

    from lbp import config_store
    from lbp.ingestion.pii import mask_value
    from lbp.multifile import stage

    key = "123456789"
    fp = stage.fingerprint(key)
    assert fp.startswith("tok_") and len(fp) == len(mask_value(key, "KEY", mode="hash")) == 16
    assert fp != mask_value(key, "KEY", mode="hash")  # not the unsalted sha256 token (brute-forceable for SSN keys)
    assert fp != "tok_" + hashlib.sha256(key.encode()).hexdigest()[:12]
    assert stage.fingerprint(key) == fp and stage.fingerprint("123456780") != fp and stage.fingerprint("") is None
    dk = config_store.derived_key(stage.FINGERPRINT_LABEL)
    assert dk != config_store._key()  # domain-separated, never the signing key itself
    assert fp == "tok_" + hmac.new(dk, key.encode(), hashlib.sha256).hexdigest()[:12]
    monkeypatch.setattr(config_store, "_key", lambda: b"another-secret")
    config_store._DERIVED.clear()
    assert stage.fingerprint(key) != fp  # depends on the server secret
    config_store._DERIVED.clear()
    # mask_value elsewhere is unchanged
    assert mask_value(key, "KEY", mode="hash") == "tok_" + hashlib.sha256(key.encode()).hexdigest()[:12]
