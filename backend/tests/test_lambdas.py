"""The AWS execution path (EventBridge -> Step Functions -> Lambda) exercised against mocked AWS."""
import importlib.util
import json
import sys
from pathlib import Path

HANDLERS = Path(__file__).resolve().parents[2] / "aws" / "lambdas" / "handlers.py"


def _load(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("LBP_PROCESSED_BUCKET", "lbp-processed")
    monkeypatch.setenv("LBP_MICRO_BATCH_SIZE", "100")
    spec = importlib.util.spec_from_file_location("handlers", HANDLERS)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["handlers"] = mod
    spec.loader.exec_module(mod)
    return mod


def _aws(monkeypatch):
    """moto Step Functions + Glue, LBP in AWS mode (dispatch -> Step Functions, data movement -> Glue)."""
    import boto3

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    sfn = boto3.client("stepfunctions", region_name="us-east-1")
    arn = sfn.create_state_machine(name="lbp-boarding", definition='{"StartAt":"A","States":{"A":{"Type":"Succeed"}}}',
                                   roleArn="arn:aws:iam::123456789012:role/x")["stateMachineArn"]
    glue = boto3.client("glue", region_name="us-east-1")
    for j in ("lbp-feed", "lbp-vendor-pull"):
        glue.create_job(Name=j, Role="r", Command={"Name": "glueetl", "ScriptLocation": "s3://x/y.py"})
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="lbp-config")
    secret = boto3.client("secretsmanager", region_name="us-east-1").create_secret(Name="lbp/config-signing", SecretString="k3y")["ARN"]
    monkeypatch.setenv("LBP_CONFIG_BUCKET", "lbp-config")
    monkeypatch.setenv("LBP_CONFIG_SIGNING_SECRET_ARN", secret)
    monkeypatch.setenv("LBP_STATE_MACHINE_ARN", arn)
    monkeypatch.setenv("LBP_GLUE_FEED_JOB", "lbp-feed")
    monkeypatch.setenv("LBP_GLUE_PULL_JOB", "lbp-vendor-pull")
    monkeypatch.setenv("LBP_ENV", "aws")
    monkeypatch.setenv("LBP_AUTH_MODE", "dev")
    from lbp import config, config_store

    config.reset_settings()
    config_store.publish_all("test", "configs published to S3 for Glue")  # what approvals do in AWS
    return sfn, arn


def _executions(sfn, arn):
    return [json.loads(sfn.describe_execution(executionArn=e["executionArn"])["input"]) for e in sfn.list_executions(stateMachineArn=arn)["executions"]]


def test_arrival_routes_to_glue_and_finalize_releases_followers(onboarded, monkeypatch, tmp_path):
    """EventBridge arrival -> Step Functions -> Route -> Glue (lbp-feed) -> Finalize, as the state machine runs them,
    with a change file that waits for its predecessor and is started by Finalize."""
    import csv

    import boto3
    from moto import mock_aws
    from sqlalchemy import select

    from lbp import glue_jobs
    from lbp.pipeline.batch import create_batch, run_batch
    from lbp.pipeline.delivery import decide_profile, propose_profile
    from lbp.store import db

    src = onboarded["pcg_retail"]
    run_batch(create_batch(src["source_id"], src["path"], src["path"].name, "ops1"), workers=1, micro_batch_size=100)
    propose_profile(src["source_id"], {"load_type": "incremental", "action": {"mode": "upsert"},
                                       "sequence": {"source": "filename", "pattern": r"_(\d+)\.csv$", "kind": "integer"}}, "a1", ["analyst"])
    decide_profile(src["source_id"], "sme1", ["sme"], True)
    with db.get_engine().connect() as c:
        ln = c.execute(select(db.sse_loans.c.loan_number).where(db.sse_loans.c.lbp_source_id == src["source_id"]).limit(1)).scalar()
    with mock_aws():
        h = _load(monkeypatch)
        sfn, arn = _aws(monkeypatch)
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="lbp-raw")
        for n, upb in ((2, 2222), (1, 1111)):
            p = tmp_path / f"PCG_DELTA_{n}.csv"
            with open(p, "w", newline="") as f:
                csv.writer(f).writerows([["LoanID", "CurrentUPB"], [ln, upb]])
            key = f"incoming/{src['source_id']}/PCG_DELTA_{n}.csv"
            s3.upload_file(str(p), "lbp-raw", key, ExtraArgs={"Metadata": {"submitted-by": "vendor-sftp"}})
            h.on_file_arrival({"detail": {"bucket": {"name": "lbp-raw"}, "object": {"key": key}}}, None)
        ex = _executions(sfn, arn)
        second, first = ex[1] if ex[1]["key"].endswith("_2.csv") else ex[0], ex[0] if ex[0]["key"].endswith("_1.csv") else ex[1]
        # Route: change files always run on the standard job
        r2 = h.route_batch(second, None)
        assert r2["job_name"] == "lbp-feed" and r2["engine"] == "standard"
        # Glue run for file 2: waits behind file 1, nothing loaded
        assert glue_jobs.process_batch(second["batch_id"])["status"] == "waiting"
        assert h.finalize_batch(second, None)["status"] == "waiting"
        # Glue run for file 1, then Finalize starts file 2 (released from waiting)
        glue_jobs.process_batch(first["batch_id"])
        fin = h.finalize_batch(first, None)
        assert fin["status"] == "completed" and fin["balanced"] and fin["started_followers"] == [second["batch_id"]]
        assert _executions(sfn, arn)[0]["batch_id"] in (second["batch_id"], first["batch_id"])
        glue_jobs.process_batch(second["batch_id"])
        with db.get_engine().connect() as c:
            row = c.execute(select(db.sse_loans).where(db.sse_loans.c.loan_number == ln)).first()
        assert float(row.current_principal_balance) == 2222 and row.lbp_version == 3


def test_route_unknown_batch_raises(onboarded, monkeypatch):
    from moto import mock_aws

    with mock_aws():
        h = _load(monkeypatch)
        try:
            h.route_batch({"batch_id": "bat_missing"}, None)
            assert False, "expected ValueError"
        except ValueError as e:
            assert "unknown batch" in str(e)


def test_process_batch_does_not_dispatch_followers(onboarded, monkeypatch):
    """AWS Finalize owns follower start; Glue process_batch must not also dispatch (double SFN)."""
    import csv

    from moto import mock_aws
    from sqlalchemy import select

    from lbp import glue_jobs
    from lbp.dispatch import dispatch
    from lbp.pipeline.batch import create_batch, run_batch
    from lbp.pipeline.delivery import decide_profile, propose_profile
    from lbp.store import db

    src = onboarded["pcg_retail"]
    run_batch(create_batch(src["source_id"], src["path"], src["path"].name, "ops1"), workers=1, micro_batch_size=100)
    propose_profile(src["source_id"], {"load_type": "incremental", "action": {"mode": "upsert"},
                                       "sequence": {"source": "filename", "pattern": r"_(\d+)\.csv$", "kind": "integer"}}, "a1", ["analyst"])
    decide_profile(src["source_id"], "sme1", ["sme"], True)
    with db.get_engine().connect() as c:
        ln = c.execute(select(db.sse_loans.c.loan_number).where(db.sse_loans.c.lbp_source_id == src["source_id"]).limit(1)).scalar()

    calls = []
    monkeypatch.setattr("lbp.dispatch.dispatch", lambda bid: calls.append(bid) or "arn:fake")

    with mock_aws():
        h = _load(monkeypatch)
        _aws(monkeypatch)
        from pathlib import Path
        import tempfile
        td = Path(tempfile.mkdtemp())
        for n, upb in ((1, 1111), (2, 2222)):
            p = td / f"PCG_DELTA_{n}.csv"
            with open(p, "w", newline="") as f:
                csv.writer(f).writerows([["LoanID", "CurrentUPB"], [ln, upb]])
            create_batch(src["source_id"], str(p), p.name, "s3")
        with db.get_engine().connect() as c:
            bids = [r[0] for r in c.execute(select(db.batches.c.batch_id).where(
                db.batches.c.source_id == src["source_id"], db.batches.c.load_type != "full").order_by(db.batches.c.sequence))]
        first, second = bids[0], bids[1]
        glue_jobs.process_batch(second)  # waiting
        calls.clear()
        glue_jobs.process_batch(first)
        assert calls == [], f"process_batch must not dispatch; got {calls}"
        fin = h.finalize_batch({"batch_id": first}, None)
        assert fin["started_followers"] == [second]


def test_mark_failed_does_not_kill_running_batch(onboarded, monkeypatch):
    from moto import mock_aws
    from sqlalchemy import select

    from lbp.pipeline.batch import create_batch
    from lbp.store import db

    with mock_aws():
        h = _load(monkeypatch)
        src = onboarded["pcg_retail"]
        bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
        with db.get_engine().begin() as c:
            c.execute(db.batches.update().where(db.batches.c.batch_id == bid).values(
                status="running", worker_id="glue:1", checkpoint=100))
        h.mark_failed({"batch_id": bid, "error": {"Error": "BatchBusyError"}}, None)
        with db.get_engine().connect() as c:
            b = c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first()
        assert b.status == "running" and b.worker_id == "glue:1" and b.checkpoint == 100


def test_route_sends_large_full_tapes_to_spark(onboarded, monkeypatch):
    from moto import mock_aws
    from sqlalchemy import select

    from lbp.pipeline.batch import create_batch
    from lbp.store import db

    with mock_aws():
        h = _load(monkeypatch)
        monkeypatch.setattr(h, "SPARK_THRESHOLD_ROWS", 100)
        src = onboarded["pcg_retail"]
        bid = create_batch(src["source_id"], src["path"], "big.csv", "s3")
        assert h.route_batch({"batch_id": bid}, None)["engine"] == "spark"
        xl = onboarded["bulk_acquisition"]
        bid2 = create_batch(xl["source_id"], xl["path"], "big.xlsx", "s3")
        assert h.route_batch({"batch_id": bid2}, None)["engine"] == "standard"  # Excel is not splittable
        with db.get_engine().begin() as c:
            c.execute(db.batches.update().where(db.batches.c.batch_id == bid).values(status="staged"))
        assert h.mark_failed({"batch_id": bid, "error": {"Cause": "x"}}, None)["status"] == "failed"
        with db.get_engine().connect() as c:
            assert c.execute(select(db.batches.c.status).where(db.batches.c.batch_id == bid)).scalar() == "failed"


def test_api_uploads_dispatch_to_step_functions_not_inline(onboarded, monkeypatch):
    from fastapi.testclient import TestClient
    from moto import mock_aws

    with mock_aws():
        _load(monkeypatch)
        sfn, arn = _aws(monkeypatch)
        import boto3

        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="lbp-raw")
        monkeypatch.setenv("LBP_RAW_BUCKET", "lbp-raw")
        from lbp import config

        config.reset_settings()
        from lbp.api.main import app

        src = onboarded["correspondent"]
        import lbp.api.main as _m
        from lbp.security import Principal

        # AWS refuses dev identity headers; stand in for a verified Cognito token (expanded roles)
        from lbp.security import expand_roles
        monkeypatch.setattr(_m, "current_principal", lambda *a, **k: Principal(name="maria.ops", roles=expand_roles(["ops"])))
        cl = TestClient(app)  # no lifespan: Lambda runs the app the same way (Mangum lifespan="off")
        with open(src["path"], "rb") as f:
            r = cl.post("/api/upload", data={"source_id": src["source_id"]}, files={"file": ("c.csv", f)}, headers={"X-User": "o", "X-Roles": "ops"})
        assert r.status_code == 200 and r.json()["status"] == "submitted"
        ex = _executions(sfn, arn)
        assert ex[0]["batch_id"] == r.json()["batch_id"] and ex[0]["key"].startswith(f"uploads/{src['source_id']}/")


def test_api_lambda_handler_requires_auth(env, monkeypatch):
    with __import__("moto").mock_aws():
        h = _load(monkeypatch)
        event = {"version": "2.0", "routeKey": "GET /api/exceptions", "rawPath": "/api/exceptions", "rawQueryString": "",
                 "headers": {"x-roles": "reviewer", "x-user": "lee"}, "isBase64Encoded": False,
                 "requestContext": {"http": {"method": "GET", "path": "/api/exceptions", "sourceIp": "10.0.0.1", "protocol": "HTTP/1.1",
                                             "userAgent": "t"}, "stage": "$default", "requestId": "r1", "accountId": "1", "apiId": "a",
                                    "domainName": "x", "domainPrefix": "x", "time": "t", "timeEpoch": 0}}
        r = h.api(event, type("C", (), {"function_name": "f", "aws_request_id": "r1"})())
        assert r["statusCode"] == 200 and "items" in json.loads(r["body"])  # local dev mode
        monkeypatch.setenv("LBP_AUTH_MODE", "jwt")
        monkeypatch.setenv("LBP_COGNITO_USER_POOL_ID", "p")
        monkeypatch.setenv("LBP_COGNITO_CLIENT_ID", "c")
        from lbp import config

        config.reset_settings()
        r = h.api(event, type("C", (), {"function_name": "f", "aws_request_id": "r2"})())
        assert r["statusCode"] == 401  # spoofed identity headers are rejected in jwt mode


def test_file_arrival_starts_pipeline_once(onboarded, monkeypatch):
    import boto3
    from moto import mock_aws

    with mock_aws():
        h = _load(monkeypatch)
        sfn, arn = _aws(monkeypatch)
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="lbp-raw")
        src = onboarded["bulk_acquisition"]
        key = f"incoming/{src['source_id']}/tape.xlsx"
        s3.upload_file(str(src["path"]), "lbp-raw", key, ExtraArgs={"Metadata": {"submitted-by": "maria.ops"}})
        ev = {"detail": {"bucket": {"name": "lbp-raw"}, "object": {"key": key}}}
        first = h.on_file_arrival(ev, None)
        again = h.on_file_arrival(ev, None)  # EventBridge redelivery / seller re-drop
        assert first["batch_id"] and first["execution_arn"] and again["duplicate_of"] == first["batch_id"]
        assert len(_executions(sfn, arn)) == 1


def test_scheduler_tick_lambda(env, monkeypatch):
    with __import__("moto").mock_aws():
        h = _load(monkeypatch)
        out = h.scheduler_tick({}, None)
        assert out["materialized"] == 0 and "late" in out


def test_scheduler_starts_glue_pull_jobs_in_aws(onboarded, monkeypatch, env):
    """In AWS the scheduler Lambda never moves files itself: a due pull starts the lbp-vendor-pull Glue job."""
    from datetime import timedelta

    import boto3
    from moto import mock_aws

    from lbp.scheduling import service as svc
    from lbp.store import db

    with mock_aws():
        _load(monkeypatch)
        _aws(monkeypatch)
        (env / "data" / "dropzone" / "pcg").mkdir(parents=True)
        s = svc.create_schedule(onboarded["pcg_retail"]["source_id"], "Daily", {"cron": "0 6 * * *", "timezone": "UTC", "calendar": "none",
                                "window_before_minutes": 1440, "pull": {"protocol": "local", "path": "pcg", "pattern": "*.csv"}}, "o", ["ops"])
        svc.decide(s["schedule_id"], "s", ["sme"], True)
        with db.get_engine().begin() as c:
            c.execute(db.delivery_schedules.update().values(approved_at=db.now() - timedelta(days=2)))
        res = svc.tick()
        assert res["pulled"] and res["pulled"][0]["glue_run_id"]
        runs = boto3.client("glue", region_name="us-east-1").get_job_runs(JobName="lbp-vendor-pull")["JobRuns"]
        assert len(runs) == 1 and runs[0]["Arguments"]["--schedule_id"] == s["schedule_id"]


def test_migrate_lambda_publishes_configs(onboarded, monkeypatch):
    """The deploy step: migrations (no-op on a current schema here) + a signed configuration for every live feed."""
    from moto import mock_aws

    with mock_aws():
        h = _load(monkeypatch)
        _aws(monkeypatch)
        import lbp.cli

        monkeypatch.setattr("alembic.command.upgrade", lambda *a, **k: None)  # schema is created by the fixture
        out = h.migrate({}, None)
        assert out["migrated"] is True
        from lbp import config_store

        for feed in onboarded.values():
            assert config_store.load(feed["source_id"]).version >= 1
        assert lbp.cli  # imported for the patch target


def test_glue_runs_emit_pipeline_metrics(monkeypatch):
    """LBP/Pipeline metrics (dashboard + failure-rate alarm) come from the Glue jobs now that no Lambda processes data."""
    import boto3
    from moto import mock_aws

    from lbp import config, glue_jobs

    with mock_aws():
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        monkeypatch.setenv("LBP_ENV", "aws")
        config.reset_settings()
        glue_jobs.emit_metrics({"processed": 120, "failed": 3}, 4.2, "standard")
        names = {m["MetricName"] for m in boto3.client("cloudwatch", region_name="us-east-1").list_metrics(Namespace="LBP/Pipeline")["Metrics"]}
        assert {"LoansProcessed", "LoansFailed", "BatchSeconds"} <= names
        glue_jobs.emit_metrics({"status": "waiting"}, 1, "standard")  # nothing to report, never raises


def test_state_machine_matches_handlers_and_glue_jobs():
    """Every template variable in the ASL is supplied by Terraform, every state transition resolves, and the Glue
    arguments match what the job scripts read."""
    import re

    root = Path(__file__).resolve().parents[2] / "aws"
    asl = (root / "stepfunctions" / "boarding.asl.json").read_text()
    tf = (root / "terraform" / "orchestration.tf").read_text()
    for var in set(re.findall(r"\$\{(\w+)\}", asl)):
        assert re.search(rf"^\s*{var}\s*=", tf, re.M), f"{var} not passed by orchestration.tf"
    d = json.loads(re.sub(r"\$\{\w+\}", "x", asl))
    st = d["States"]
    for name, s in st.items():
        for n in [s.get("Next"), s.get("Default")] + [c.get("Next") for c in s.get("Choices", []) + s.get("Catch", [])]:
            assert n is None or n in st, (name, n)
    assert "--batch_id" in (root / "glue" / "feed_job.py").read_text() or '"batch_id"' in (root / "glue" / "feed_job.py").read_text()
    for job in ("feed_job.py", "feed_spark_job.py", "vendor_pull_job.py"):
        assert f'"{job}"' in tf or job in tf, f"{job} not deployed"
