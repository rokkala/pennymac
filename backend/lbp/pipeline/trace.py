"""Step Functions history for a batch, reduced to the steps and short returns the desk shows.

Loan rows never leave Glue, so the execution output is only status, engine and errors.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger("lbp.pipeline.trace")

LABELS = {
    "Route": "Route",
    "GlueStandard": "Glue",
    "GlueSpark": "Glue Spark",
    "Finalize": "Finalize",
    "MarkFailed": "Failed",
    "NotifyCompleted": "Notified",
    "NotifyFailed": "Notified",
    "NotifyAttention": "Notified",
    "WaitingForEarlierFile": "Waiting",
}
_BRIEF_KEYS = ("status", "engine", "job_name", "state", "balanced", "error", "cause")


def _brief(raw) -> str | None:
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            data = json.loads(raw[:4000])
        except json.JSONDecodeError:
            return raw[:180]
    else:
        data = raw
    if isinstance(data, dict) and isinstance(data.get("Payload"), dict):
        data = data["Payload"]
    if isinstance(data, dict) and isinstance(data.get("outcome"), dict):
        data = data["outcome"]
    if not isinstance(data, dict):
        return str(data)[:180]
    bits = []
    for key in _BRIEF_KEYS:
        val = data.get(key)
        if val not in (None, "", {}, []):
            bits.append(str(val)[:160])
    glue = data.get("glue")
    if isinstance(glue, dict) and glue.get("state"):
        bits.append(f"glue {glue['state']}")
    text = " · ".join(bits)
    return text[:220] or None


def summarize_events(events: list[dict], execution_status: str) -> dict:
    """Turn GetExecutionHistory events into ordered steps. Choice states are skipped."""
    steps: list[dict] = []
    for ev in events:
        kind = ev.get("type") or ""
        if kind.endswith("StateEntered"):
            name = (ev.get("stateEnteredEventDetails") or {}).get("name")
            if name not in LABELS:
                continue
            if steps and steps[-1]["state"] == "running":
                steps[-1]["state"] = "succeeded"
            steps.append({"name": name, "label": LABELS[name], "state": "running", "summary": None})
            continue
        if not steps:
            continue
        if kind == "TaskSucceeded":
            steps[-1]["state"] = "succeeded"
            steps[-1]["summary"] = _brief((ev.get("taskSucceededEventDetails") or {}).get("output")) or steps[-1]["summary"]
        elif kind in ("TaskFailed", "TaskTimedOut", "ExecutionFailed"):
            details = ev.get("taskFailedEventDetails") or ev.get("executionFailedEventDetails") or {}
            steps[-1]["state"] = "failed"
            steps[-1]["summary"] = _brief({"error": details.get("error"), "cause": details.get("cause")})
    if steps and steps[-1]["state"] == "running" and execution_status in ("SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"):
        steps[-1]["state"] = "failed" if execution_status != "SUCCEEDED" else "succeeded"
    current = next((s for s in reversed(steps) if s["state"] == "running"), None) or (steps[-1] if steps else None)
    return {"execution_status": execution_status, "steps": steps, "current": current}


def fetch_traces(batch_ids: list[str]) -> dict[str, dict]:
    """Latest execution for each batch id. Empty when this process is not on AWS."""
    from ..config import get_settings

    s = get_settings()
    want = [b for b in batch_ids if b]
    if s.env != "aws" or not s.state_machine_arn or not want:
        return {}
    try:
        import boto3

        sf = boto3.client("stepfunctions", region_name=s.aws_region)
        executions = sf.list_executions(stateMachineArn=s.state_machine_arn, maxResults=50).get("executions") or []
        found: dict[str, dict] = {}
        looking = set(want)
        for ex in executions:
            bid = ex["name"].rsplit("-", 1)[0]
            if bid in looking and bid not in found:
                found[bid] = ex
        out = {}
        for bid, ex in found.items():
            hist = sf.get_execution_history(executionArn=ex["executionArn"], maxResults=100, reverseOrder=False)
            out[bid] = summarize_events(hist.get("events") or [], ex.get("status") or "")
        return out
    except Exception as e:  # the desk still lists files if Step Functions is unreachable
        log.warning("pipeline trace unavailable: %s", e)
        return {}
