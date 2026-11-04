"""Confidence x Risk routing policy (the hard gate).

Thresholds live in the Policy Store (SQL table locally / DynamoDB in AWS). Changing them
requires a Compliance approver distinct from the requester, and every change is audited.

Routing order (first match wins):
  T5 Block & Escalate  critical field/rule (OFAC hit, fraud)          -> halt loan, alert Compliance
  T4 Dual Control      high-risk field (rate, term, FICO, DTI, HMDA,  -> maker-checker, NO AI auto-apply ever
                       identity), any confidence
  T1 Auto-Apply        confidence >= t1 and effective risk low         -> applied, audited, 5% sampled QA
  T2 Suggest           confidence >= t2 and risk low/medium            -> single reviewer, AI pre-fills
  T3 Mandatory Review  everything else                                 -> standard queue, hints only
"""
from __future__ import annotations

from sqlalchemy import select

from ..store import db

DEFAULT_POLICY = {
    "t1_enabled": True,             # kill switch for AI auto-apply (SR 11-7 model risk control)
    "t1_min_sample": 50,            # auto-suspend only judges with at least this many T1 fixes
    "t1_min_confidence": 0.95,
    "t2_min_confidence": 0.80,
    "t1_allowed_risk": ["low"],
    "t2_allowed_risk": ["low", "medium"],
    "dual_control_risk": ["high"],
    "block_risk": ["critical"],
    "block_categories": ["compliance", "fraud"],
    "format_fix_downgrades_medium": True,
    "qa_sample_pct": 5,
    "rollback_window_minutes": 60,
    "t1_max_override_rate_pct": 2.0,
}

QUEUES = {"T1": "auto-apply", "T2": "single-review", "T3": "standard-review", "T4": "dual-control", "T5": "compliance"}
TIER_LABELS = {"T1": "Auto-Apply", "T2": "Suggest", "T3": "Mandatory Review", "T4": "Dual Control", "T5": "Block & Escalate"}


class PolicyError(ValueError):
    pass


def get_policy() -> dict:
    with db.get_engine().connect() as c:
        row = c.execute(select(db.policy.c.value).where(db.policy.c.key == "routing")).first()
    return {**DEFAULT_POLICY, **(row[0] if row else {})}


def set_policy(changes: dict, requested_by: str, approved_by: str, approver_roles: list[str], reason: str | None = None) -> dict:
    if "compliance" not in (approver_roles or []):
        raise PolicyError("policy changes require Compliance approval")
    emergency_off = changes == {"t1_enabled": False}
    if requested_by == approved_by and not emergency_off:  # switching auto-apply OFF is the safe direction: one person may do it
        raise PolicyError("requester and approver must be different users")
    unknown = set(changes) - set(DEFAULT_POLICY)
    if unknown:
        raise PolicyError(f"unknown policy keys: {sorted(unknown)}")
    if float(changes.get("t1_min_confidence", 0.95)) < 0.9:
        raise PolicyError("t1_min_confidence below 0.90 is not permitted")
    new = {**get_policy(), **changes}
    with db.get_engine().begin() as c:
        exists = c.execute(select(db.policy.c.key).where(db.policy.c.key == "routing")).first()
        stmt = db.policy.update().where(db.policy.c.key == "routing") if exists else db.policy.insert().values(key="routing")
        c.execute(stmt.values(value=new, updated_by=requested_by, approved_by=approved_by, updated_at=db.now()))
        db.audit(c, approved_by, "policy.update", "policy", "routing", {"changes": changes, "requested_by": requested_by, "reason": reason})
    return new


def t1_health(window_days: int = 30) -> dict:
    """Live override rate of AI auto-applied fixes (rollbacks + failed QA samples / T1 fixes)."""
    from datetime import timedelta

    from sqlalchemy import func

    since = db.now() - timedelta(days=window_days)
    with db.get_engine().connect() as c:
        t1 = c.execute(select(func.count()).select_from(db.exceptions).where(db.exceptions.c.tier == "T1",
                                                                             db.exceptions.c.created_at >= since)).scalar() or 0
        overrides = c.execute(select(func.count()).select_from(db.audit_log).where(
            db.audit_log.c.action.in_(("exception.rollback", "exception.qa_fail")), db.audit_log.c.ts >= since)).scalar() or 0
    return {"t1_fixes": t1, "overrides": overrides, "override_rate_pct": round(overrides / t1 * 100, 2) if t1 else 0.0, "window_days": window_days}


def effective_policy() -> dict:
    """Configured policy plus automatic controls: T1 is suspended when its override rate breaches the limit."""
    p = get_policy()
    h = t1_health()
    suspended = h["t1_fixes"] >= p["t1_min_sample"] and h["override_rate_pct"] > p["t1_max_override_rate_pct"]
    return {**p, "t1_effective": bool(p["t1_enabled"]) and not suspended, "t1_auto_suspended": suspended, "t1_health": h}


def route(confidence: float | None, field_risk: str, category: str, fix_kind: str | None, policy: dict) -> str:
    conf = confidence or 0.0
    if field_risk in policy["block_risk"] or category in policy["block_categories"]:
        return "T5"
    if field_risk in policy["dual_control_risk"]:
        return "T4"
    effective = field_risk
    if policy.get("format_fix_downgrades_medium") and field_risk == "medium" and fix_kind in ("format", "lookup"):
        effective = "low"
    if conf >= policy["t1_min_confidence"] and effective in policy["t1_allowed_risk"] and policy.get("t1_effective", policy.get("t1_enabled", True)):
        return "T1"
    if conf >= policy["t2_min_confidence"] and effective in policy["t2_allowed_risk"]:
        return "T2"
    return "T3"
