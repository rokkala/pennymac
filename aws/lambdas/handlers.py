"""AWS Lambda entry points: the thin control plane around the Glue data plane.

Lambdas never transform or load loan data. They register arriving files, decide which Glue job runs
a batch, react to the outcome, drive the delivery scheduler and serve the web app's API.

Pipeline (Step Functions, see ../stepfunctions/boarding.asl.json):
  S3 raw/incoming/<feed_id>/<file> --EventBridge--> on_file_arrival   register the batch, start an execution
  Route         route_batch        standard job (default) or Spark (very large full tapes)
  Glue          lbp-feed / lbp-feed-spark   (.sync) gate, pre-flight, map, validate, triage, load, reconcile
  Finalize      finalize_batch     read the outcome; start files that were waiting behind this one
  Notify        SNS
Scheduler: EventBridge Scheduler -> scheduler_tick (delivery windows, alerts; pulls start lbp-vendor-pull).
Deploy: migrate (Alembic + rule seed + publish feed configurations).
API: API Gateway (HTTP API) -> api (FastAPI via Mangum): configuration, approvals, exceptions.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
from pathlib import Path

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

s3 = boto3.client("s3")
GLUE_FEED_JOB = os.environ.get("LBP_GLUE_FEED_JOB", "lbp-feed")
GLUE_SPARK_JOB = os.environ.get("LBP_GLUE_SPARK_JOB", "lbp-feed-spark")
SPARK_THRESHOLD_ROWS = int(os.environ.get("LBP_GLUE_THRESHOLD_ROWS", "500000"))


# ---------------------------------------------------------------- 1. file arrival
def on_file_arrival(event, _ctx):
    """EventBridge 'Object Created' on the raw bucket, prefix incoming/<feed_id>/."""
    from lbp.dispatch import dispatch
    from lbp.pipeline.batch import DuplicateFileError, create_batch

    detail = event.get("detail", {})
    bucket = detail["bucket"]["name"]
    key = urllib.parse.unquote_plus(detail["object"]["key"])
    parts = key.split("/")
    if len(parts) < 3 or parts[0] != "incoming":
        log.info("ignoring %s", key)
        return {"ignored": key}
    source_id = parts[1]
    head = s3.head_object(Bucket=bucket, Key=key)
    meta = head.get("Metadata", {})
    try:
        # strict=False: a file that cannot be sequenced (or a suspended vendor's file) is recorded as a failed batch, not dropped
        batch_id = create_batch(source_id, f"s3://{bucket}/{key}", Path(key).name, meta.get("submitted-by", "s3-auto-arrival"),
                                strict=False, load_type=meta.get("load-type") or None)
    except DuplicateFileError as e:
        log.warning("duplicate file ignored: %s", e)
        return {"duplicate_of": e.batch_id, "key": key}
    from sqlalchemy import select

    from lbp.store import db

    with db.get_engine().connect() as c:
        status = c.execute(select(db.batches.c.status).where(db.batches.c.batch_id == batch_id)).scalar()
    return {"batch_id": batch_id, "execution_arn": None if status == "failed" else dispatch(batch_id)}


# ---------------------------------------------------------------- 2. route
def route_batch(event, _ctx):
    """Choose the Glue job. Spark only pays off for very large full tapes in a splittable format;
    change files, snapshots and Excel run on the standard driver-only job (smallest footprint)."""
    from sqlalchemy import select

    from lbp.store import db

    batch_id = event["batch_id"]
    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
        fmt = c.execute(select(db.sources.c.format).where(db.sources.c.source_id == b.source_id)).scalar()
    spark = (b.load_type or "full") == "full" and fmt in ("csv", "txt", "psv", "dat") and (b.total_rows or 0) > SPARK_THRESHOLD_ROWS \
        and (b.checkpoint or 0) == 0
    job = GLUE_SPARK_JOB if spark else GLUE_FEED_JOB
    return {**event, "job_name": job, "engine": "spark" if spark else "standard", "total_rows": b.total_rows,
            "load_type": b.load_type or "full"}


# ---------------------------------------------------------------- 3. finalize
def finalize_batch(event, _ctx):
    """After the Glue run: report the outcome and start the vendor's files that were released from waiting."""
    from sqlalchemy import select

    from lbp.dispatch import dispatch
    from lbp.store import db

    batch_id = event["batch_id"]
    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
        follow = [r[0] for r in c.execute(select(db.batches.c.batch_id).where(
            db.batches.c.source_id == b.source_id, db.batches.c.status == "queued", db.batches.c.batch_id != batch_id,
            db.batches.c.load_type != "full").order_by(db.batches.c.sequence))] if b.status == "completed" else []
    for x in follow:
        dispatch(x)
    rec = b.reconciliation or {}
    return {"batch_id": batch_id, "status": b.status, "balanced": bool(rec.get("balanced")), "reconciliation": rec,
            "change_summary": b.change_summary, "error": b.error, "started_followers": follow}


def mark_failed(event, _ctx):
    from lbp.store import db

    batch_id = event.get("batch_id")
    err = json.dumps(event.get("error", {}))[:2000]
    with db.get_engine().begin() as c:
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id, db.batches.c.status != "completed")
                  .values(status="failed", error=err, worker_id=None))
        db.audit(c, "pipeline", "batch.failed", "batch", batch_id, {"error": err})
    return {"batch_id": batch_id, "status": "failed"}


# ---------------------------------------------------------------- 4. delivery scheduler
def scheduler_tick(_event, _ctx):
    """EventBridge Scheduler (rate 5 minutes): delivery windows and late/missed alerts. Due pulls start the
    lbp-vendor-pull Glue job; pulled files land in the raw zone and arrive like any other file."""
    from lbp.scheduling.service import tick

    res = tick()
    out = {k: (len(v) if isinstance(v, list) else v) for k, v in res.items()}
    log.info("scheduler tick: %s", json.dumps(out, default=str))
    return out


# ---------------------------------------------------------------- 5. migrate (deploy step)
def migrate(_event, _ctx):
    """Invoked once per deploy: Alembic migrations, default rule seed, and a signed configuration for every
    live feed (so Glue always finds one). Idempotent."""
    import contextlib
    import io

    from lbp.cli import migrate as run

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = run()
    out = json.loads(buf.getvalue().strip().splitlines()[-1])
    if code:
        raise RuntimeError(f"migration failed: {out}")
    return out


# ---------------------------------------------------------------- API (control plane)
def _api():
    from mangum import Mangum

    from lbp.api.main import app

    return Mangum(app, lifespan="off")


_api_handler = None


def api(event, ctx):
    """API Gateway (HTTP API, payload v2) -> FastAPI. The bearer token is passed through and verified
    in-process by lbp.security (identity headers are never trusted outside local dev)."""
    global _api_handler
    if _api_handler is None:
        _api_handler = _api()
    return _api_handler(event, ctx)
