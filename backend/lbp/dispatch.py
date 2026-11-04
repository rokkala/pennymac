"""Start processing of a batch, wherever the platform runs.

    local  a background thread runs the same pipeline in-process (development, demo)
    aws    a Step Functions execution: route -> Glue job (.sync) -> finalize -> notify

The control-plane API never processes loan data itself in AWS: uploads, resumes, overrides,
skips and released follow-on files all go through here to Glue.
"""
from __future__ import annotations

import json
import logging
import time

from sqlalchemy import select

from .config import get_settings
from .store import db

log = logging.getLogger("lbp.dispatch")


def aws_mode() -> bool:
    s = get_settings()
    return s.env == "aws" and bool(s.state_machine_arn)


def dispatch(batch_id: str) -> str:
    if not aws_mode():
        from .pipeline.batch import start_batch_async

        start_batch_async(batch_id)
        return "local"
    import boto3

    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches.c.batch_id, db.batches.c.source_id, db.batches.c.file_path).where(db.batches.c.batch_id == batch_id)).first()
    bucket, key = "", ""
    if b and str(b.file_path).startswith("s3://"):
        bucket, _, key = str(b.file_path)[5:].partition("/")
    s = get_settings()
    arn = boto3.client("stepfunctions", region_name=s.aws_region).start_execution(
        stateMachineArn=s.state_machine_arn, name=f"{batch_id}-{int(time.time() * 1000)}",
        input=json.dumps({"batch_id": batch_id, "source_id": b.source_id if b else None, "bucket": bucket, "key": key}))["executionArn"]
    return arn


def start_glue(job_name: str, arguments: dict) -> str:
    """Control-plane actions that move data (replay, vendor pull) run as Glue jobs in AWS."""
    import boto3

    return boto3.client("glue", region_name=get_settings().aws_region).start_job_run(
        JobName=job_name, Arguments={f"--{k}": str(v) for k, v in arguments.items()})["JobRunId"]
