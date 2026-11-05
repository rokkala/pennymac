import io
import time

import pytest


def _client(monkeypatch, **env):
    from fastapi.testclient import TestClient

    from lbp import config
    from lbp.store import db

    for k, v in env.items():
        monkeypatch.setenv(f"LBP_{k}", v)
    config.reset_settings()
    db.reset_engine()
    import importlib

    import lbp.api.main as main

    importlib.reload(main)
    return TestClient(main.app), main


def test_every_write_route_is_in_the_authorization_matrix(env):
    from lbp.api.main import PUBLIC, ROUTE_ROLES, app

    writes = {(m, r.path) for r in app.routes if getattr(r, "path", "").startswith("/api") for m in getattr(r, "methods", set())
              if m in ("POST", "PUT", "DELETE", "PATCH")}
    missing = writes - set(ROUTE_ROLES) - PUBLIC
    assert not missing, f"write routes without an explicit role entry: {sorted(missing)}"


def test_role_enforcement_dev_mode(client):
    def h(roles):
        return {"X-User": "u1", "X-Roles": roles}

    assert client.put("/api/policy", json={"changes": {}, "requested_by": "x"}, headers=h("monitoring")).status_code == 403
    assert client.post("/api/mappings/m/approve", json={"approve": True}, headers=h("onboarding")).status_code == 403
    assert client.post("/api/exceptions/x/compliance-clear", json={"reason": "r"}, headers=h("monitoring")).status_code == 403
    assert client.post("/api/rules", json={}, headers=h("monitoring")).status_code == 403
    assert client.get("/api/audit", headers=h("monitoring")).status_code == 403
    assert client.get("/api/audit", headers=h("compliance_reviewer")).status_code == 200
    assert client.get("/api/exceptions", headers=h("monitoring")).status_code == 200  # reads are open to any role
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Request-ID"]


def _rsa():
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key, **claims):
    import jwt

    base = {"iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TEST", "token_use": "id", "aud": "client123",
            "email": "ana@pennymac.com", "cognito:groups": ["compliance_reviewer"], "exp": int(time.time()) + 600}
    return jwt.encode({**base, **claims}, key, algorithm="RS256", headers={"kid": "k1"})


def test_jwt_mode(env, monkeypatch):
    key = _rsa()

    class FakeJwks:
        def get_signing_key_from_jwt(self, _t):
            return type("K", (), {"key": key.public_key()})()

    from lbp import security

    monkeypatch.setattr(security, "_jwks_client", lambda url: FakeJwks())
    client, _ = _client(monkeypatch, AUTH_MODE="jwt", COGNITO_USER_POOL_ID="us-east-1_TEST", COGNITO_CLIENT_ID="client123",
                        COGNITO_REGION="us-east-1")
    with client:
        ok = {"Authorization": f"Bearer {_token(key)}"}
        assert client.get("/api/me", headers=ok).json()["name"] == "ana@pennymac.com"
        assert client.get("/api/audit", headers=ok).status_code == 200
        # dev headers are ignored in jwt mode
        assert client.get("/api/me", headers={"X-User": "mallory", "X-Roles": "admin"}).status_code == 401
        assert client.get("/api/me", headers={"Authorization": f"Bearer {_token(key, aud='other')}"}).status_code == 401
        assert client.get("/api/me", headers={"Authorization": f"Bearer {_token(key, exp=int(time.time()) - 5)}"}).status_code == 401
        assert client.get("/api/me", headers={"Authorization": f"Bearer {_token(_rsa())}"}).status_code == 401  # wrong signer
        assert client.get("/api/me", headers={"Authorization": f"Bearer {_token(key, **{'cognito:groups': []})}"}).status_code == 403
        monitoring = {"Authorization": f"Bearer {_token(key, **{'cognito:groups': ['monitoring']})}"}
        assert client.put("/api/policy", json={"changes": {}, "requested_by": "x"}, headers=monitoring).status_code == 403
        assert client.get("/api/health").status_code == 200 and client.get("/api/config").json()["auth"] == "cognito"


def test_production_refuses_unsafe_config(env, monkeypatch):
    client, _ = _client(monkeypatch, ENV="aws")
    with pytest.raises(RuntimeError, match="unsafe configuration"):
        with client:
            pass


def test_upload_validation(client, monkeypatch):
    h = {"X-User": "a", "X-Roles": "onboarding"}
    r = client.post("/api/sources", data={"name": "x"}, files={"file": ("tape.exe", b"MZ....")}, headers=h)
    assert r.status_code == 415
    r = client.post("/api/sources", data={"name": "x"}, files={"file": ("tape.csv", b"\x7fELF\x00\x00")}, headers=h)
    assert r.status_code == 415
    r = client.post("/api/sources", data={"name": "x"}, files={"file": ("tape.xlsx", b"not a zip")}, headers=h)
    assert r.status_code == 415
    from lbp import config

    monkeypatch.setenv("LBP_MAX_UPLOAD_MB", "1")
    config.reset_settings()
    r = client.post("/api/sources", data={"name": "x"}, files={"file": ("big.csv", io.BytesIO(b"a,b\n" * 400_000))}, headers=h)
    assert r.status_code == 413


def test_audit_chain_detects_tampering(onboarded):
    from lbp.store import db

    v = db.verify_audit_chain()
    assert v["valid"] and v["entries"] > 10
    with db.get_engine().begin() as c:
        first = c.execute(db.select(db.audit_log.c.id).order_by(db.audit_log.c.id).limit(1).offset(3)).scalar()
        c.execute(db.audit_log.update().where(db.audit_log.c.id == first).values(actor="someone.else"))
    bad = db.verify_audit_chain()
    assert not bad["valid"] and bad["broken_at_id"] == first


def test_npi_never_in_error_messages_and_retention(onboarded, tmp_path):
    import csv

    from lbp.pipeline.batch import create_batch, run_batch
    from lbp.pipeline.retention import purge_staging_npi
    from lbp.store import db

    src = onboarded["pcg_retail"]
    path = tmp_path / "dob.csv"
    with open(src["path"]) as f, open(path, "w", newline="") as g:
        r = csv.DictReader(f)
        w = csv.DictWriter(g, fieldnames=r.fieldnames)
        w.writeheader()
        for i, row in enumerate(r):
            if i < 3:
                row["BorrowerDOB"] = "1980-31-31"  # unparseable
            w.writerow(row)
    bid = create_batch(src["source_id"], path, "dob.csv", "ops")
    run_batch(bid, workers=1)
    with db.get_engine().connect() as c:
        msgs = [r[0] + " " + (r[1] or "") for r in c.execute(db.select(db.exceptions.c.message, db.exceptions.c.original_value)
                                                              .where(db.exceptions.c.field == "borrower_dob"))]
    assert msgs and not any("1980-31-31" in m for m in msgs)
    res = purge_staging_npi(0, "comp1")
    assert res["purged_rows"] > 0
    with db.get_engine().connect() as c:
        rec = c.execute(db.select(db.loans_staging.c.record, db.loans_staging.c.raw).where(db.loans_staging.c.boarded.is_(True)).limit(1)).first()
    assert rec.raw is None and str(rec.record["borrower_ssn"]).startswith("tok_")
    assert db.verify_audit_chain()["valid"]


def test_rotating_db_secret_and_ssm_settings(env, monkeypatch):
    """RDS-managed secret is read per connection; Cognito client id comes from SSM (as deployed)."""
    import json

    import boto3
    from moto import mock_aws

    from lbp import config

    with mock_aws():
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        arn = boto3.client("secretsmanager", region_name="us-east-1").create_secret(
            Name="lbp/db", SecretString=json.dumps({"username": "lbpadmin", "password": "s3cret-1"}))["ARN"]
        boto3.client("ssm", region_name="us-east-1").put_parameter(Name="/lbp-poc/app/cognito_client_id", Value="abc123", Type="String")
        monkeypatch.setenv("LBP_AWS_REGION", "us-east-1")
        monkeypatch.setenv("LBP_DB_SECRET_ARN", arn)
        monkeypatch.setenv("LBP_DB_HOST", "db.internal")
        monkeypatch.setenv("LBP_DB_DRIVER", "postgresql+psycopg")
        monkeypatch.setenv("LBP_SSM_PREFIX", "/lbp-poc/app/")
        monkeypatch.delenv("LBP_DATABASE_URL", raising=False)
        config.reset_settings()
        config._secret_cache.clear()
        s = config.get_settings()
        assert s.cognito_client_id == "abc123"
        url = s.resolved_database_url()
        assert url == "postgresql+psycopg://lbpadmin@db.internal:5432/lbp?sslmode=require" and "s3cret" not in url
        assert config.db_secret()["password"] == "s3cret-1"
        boto3.client("secretsmanager", region_name="us-east-1").put_secret_value(SecretId=arn, SecretString=json.dumps({"username": "lbpadmin", "password": "s3cret-2"}))
        assert config.db_secret(force=True)["password"] == "s3cret-2"


def test_proposals_never_leak_npi_in_list_or_detail(env):
    from lbp.exceptions.manager import ExceptionManager
    from lbp.store import db

    with db.get_engine().begin() as c:
        c.execute(db.loans_staging.insert().values(id=990001, batch_id="b", row_number=0, loan_number="L1", status="FAIL",
                                                   record={"borrower_ssn": "123456789"}, boarded=False))
        c.execute(db.exceptions.insert().values(
            exception_id="ex_npi", batch_id="b", source_id="s", loan_number="L1", staging_id=990001, rule_id="CHG01", field="borrower_ssn",
            original_value="123456789", status="open", tier="T4", risk="high", blocking=True,
            proposal={"value": "987654321", "previous": "123456789", "vendor": "987654321", "precedents": [{"original": "1"}]}))
    em = ExceptionManager()
    item = em.list(status="open")["items"][0]
    flat = str(item)
    assert "987654321" not in flat and "123456789" not in flat
    det = str(em.get("ex_npi", roles=["reviewer"]))
    assert "987654321" not in det and "123456789" not in det
    assert "987654321" in str(em.get("ex_npi", roles=["compliance"])["proposal"])  # Compliance sees the real value
