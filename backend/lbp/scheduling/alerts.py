"""Operational alerts: always logged and audited; published to SNS when LBP_ALERT_TOPIC_ARN is set
(Terraform wires it to the pipeline alert topic, which fans out to email / PagerDuty / Slack).

Messages carry identifiers and counts only, never loan-level NPI.
"""
from __future__ import annotations

import json
import logging

from ..config import get_settings
from ..store import db

log = logging.getLogger("lbp.alerts")


def notify(kind: str, message: str, detail: dict | None = None) -> bool:
    detail = detail or {}
    log.warning("ALERT %s: %s", kind, message)
    try:
        with db.get_engine().begin() as c:
            db.audit(c, "scheduler", f"alert.{kind}", "alert", detail.get("delivery_id") or detail.get("batch_id") or kind,
                     {"message": message, **detail})
    except Exception:  # noqa: BLE001 - an alert must never break the caller
        log.exception("could not audit alert %s", kind)
    arn = get_settings().alert_topic_arn
    if not arn:
        return False
    try:
        import boto3

        boto3.client("sns", region_name=get_settings().aws_region).publish(
            TopicArn=arn, Subject=f"Loan boarding: {message}"[:100],
            Message=json.dumps({"kind": kind, "message": message, **detail}, default=str))
        return True
    except Exception:  # noqa: BLE001
        log.exception("SNS publish failed for alert %s", kind)
        return False
