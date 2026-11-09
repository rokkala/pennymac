"""Exception Manager: AI proposes, human disposes.

Resolution pipeline per failing rule:
  1. Classify  - category, failing rule, field risk tier, PII-safe context
  2. Retrieve  - top-K precedents of past human fixes (RAG)
  3. Propose   - correction + confidence + rationale + citations (fixers, precedents, optional LLM)
  4. Route     - confidence x risk -> T1..T5 queue (see policy.py)

Human actions are enforced server-side: maker-checker with distinct users for T4, Compliance
only for T5, rollback window for T1, QA sampling of auto-applied fixes, bulk resolve limited
to T2/T3. Every action lands in the audit log and resolved fixes feed the precedent index.
"""
from __future__ import annotations

import json
import random
from datetime import timedelta

from sqlalchemy import and_, func, select

from ..ai import get_llm
from ..ingestion.pii import TARGET_PII_TYPES, mask_record
from ..schema.sse_target import BY_NAME, risk_of
from ..store import db
from . import fixers
from .policy import QUEUES, effective_policy, get_policy, route
from .retrieval import consensus, get_index

OPEN_STATES = ("open", "pending_review", "pending_checker", "escalated")


class ExceptionActionError(ValueError):
    pass


def _str(v):
    return None if v is None else (json.dumps(v) if isinstance(v, (dict, list)) else str(v))


def _coerce(field: str, value):
    """Cast a reviewer-entered string into the SSE type for re-validation."""
    from ..mapping.transforms import TransformError, apply_field, cast_step_for

    if value is None or field not in BY_NAME:
        return value
    if not isinstance(value, str):
        return value
    step = cast_step_for(field)
    try:
        return apply_field({"sources": ["v"], "transform": [{"op": "trim"}] + ([step] if step else [])}, {"v": value})
    except TransformError as e:
        raise ExceptionActionError(f"invalid value for {field}: {e}") from e


class Triage:
    """Pure (no DB writes) triage used inside the pipeline workers' parent process."""

    def __init__(self, policy: dict | None = None, rng_seed: int | None = None):
        self.policy = policy or effective_policy()
        self.index = get_index()
        self._cache: dict = {}
        self.rng = random.Random(rng_seed)

    def _precedents(self, rule_id, field, original):
        key = (field, _str(original))
        if key not in self._cache:
            self._cache[key] = self.index.search(rule_id, field, original, k=3)
        return self._cache[key]

    def classify_and_propose(self, rule_id: str, rule_name: str, category: str, severity: str, field: str,
                             record: dict, message: str, regulatory_tag: str | None = None) -> dict:
        original = record.get(field)
        risk = risk_of(field)
        if category in ("compliance", "fraud"):
            risk = "critical"
        precedents = self._precedents(rule_id, field, original)
        prop = fixers.propose(field, original, record)
        proposal = None
        if prop:
            proposal = {**prop.to_dict(), "source": "fixer"}
            agree = [p for p in precedents if p["corrected"] == _str(prop.value) and p["similarity"] >= 0.6]
            if agree:
                proposal["confidence"] = round(min(0.99, prop.confidence + 0.02 * min(len(agree) + agree[0]["count"] / 10, 2)), 3)
                proposal["rationale"] += f"; matches {agree[0]['count']} prior fix(es)"
        else:
            val, strength = consensus(precedents)
            if val is not None and strength > 0:
                proposal = {"value": val, "confidence": round(0.7 + 0.2 * strength, 3), "source": "precedent", "fix_kind": "precedent",
                            "rationale": f"Same value previously corrected to '{val}' by reviewers"}
        if proposal:
            proposal["precedents"] = precedents
        tier = route(proposal["confidence"] if proposal else None, risk, category, proposal.get("fix_kind") if proposal else None, self.policy)
        if tier == "T5":
            proposal = None  # never suggest a value for a blocked loan
        elif tier in ("T3", "T4") and proposal:
            proposal["hint_only"] = True
        return {
            "rule_id": rule_id, "rule_name": rule_name, "category": category, "severity": severity, "field": field,
            "original_value": _str(original), "message": message, "risk": risk, "tier": tier, "queue": QUEUES[tier],
            "proposal": proposal, "blocking": severity == "FAIL", "regulatory_tag": regulatory_tag,
            "qa_sample": tier == "T1" and self.rng.random() * 100 < self.policy["qa_sample_pct"],
        }


class ExceptionManager:
    def __init__(self):
        self.index = get_index()

    # ------------------------------------------------------------------ reads
    def list(self, status: str | None = None, tier: str | None = None, queue: str | None = None, batch_id: str | None = None,
             rule_id: str | None = None, source_id: str | None = None, q: str | None = None, limit: int = 100, offset: int = 0,
             source_ids: list[str] | None = None, loaded_on: str | None = None) -> dict:
        t = db.exceptions
        b = db.batches
        conds = []
        if status == "open":
            conds.append(t.c.status.in_(OPEN_STATES))
        elif status:
            conds.append(t.c.status == status)
        for col, val in ((t.c.tier, tier), (t.c.queue, queue), (t.c.batch_id, batch_id), (t.c.rule_id, rule_id), (t.c.source_id, source_id)):
            if val:
                conds.append(col == val)
        if source_ids is not None:
            conds.append(t.c.source_id.in_(source_ids or ["-"]))
        if q:
            conds.append(t.c.loan_number.like(f"%{q}%"))
        if loaded_on:
            # calendar day of the batch load (UTC date of started_at, else created_at)
            load_ts = func.coalesce(b.c.started_at, b.c.created_at)
            conds.append(func.date(load_ts) == loaded_on)
        join = t.outerjoin(b, b.c.batch_id == t.c.batch_id)
        where = and_(*conds) if conds else True
        with db.get_engine().connect() as c:
            total = c.execute(select(func.count()).select_from(join).where(where)).scalar()
            rows = c.execute(
                select(t, b.c.filename.label("filename"),
                       func.coalesce(b.c.started_at, b.c.created_at).label("loaded_at"))
                .select_from(join).where(where)
                .order_by(func.coalesce(b.c.started_at, b.c.created_at).desc().nullslast(),
                          t.c.created_at.desc(), t.c.exception_id)
                .limit(limit).offset(offset)
            ).all()
            from ..vendors import names_by_source

            names = names_by_source(c)
        items = []
        for r in rows:
            it = db.row_to_dict(r)
            # row_to_dict may include joined labels; normalize
            it["filename"] = getattr(r, "filename", None) or it.get("filename")
            loaded = getattr(r, "loaded_at", None) or it.get("loaded_at")
            it["loaded_at"] = loaded.isoformat() + "Z" if hasattr(loaded, "isoformat") else loaded
            n = names.get(it.get("source_id")) or {}
            it["vendor_id"], it["vendor_name"], it["feed_name"] = n.get("vendor_id"), n.get("vendor_name"), n.get("feed_name")
            items.append(it)
        from ..ingestion.pii import mask_value

        for it in items:  # list views never carry raw NPI
            if it["field"] in TARGET_PII_TYPES and it["original_value"]:
                it["original_value"] = it["original_value_masked"] = mask_value(it["original_value"], TARGET_PII_TYPES[it["field"]])
                if it.get("resolved_value"):
                    it["resolved_value"] = mask_value(it["resolved_value"], TARGET_PII_TYPES[it["field"]])
            if it["field"] in TARGET_PII_TYPES and it.get("proposal"):
                pr, kind = it["proposal"], TARGET_PII_TYPES[it["field"]]
                it["proposal"] = {**pr, "precedents": [], **{k: (mask_value(str(pr[k]), kind) if pr.get(k) not in (None, "") else pr.get(k))
                                                            for k in ("value", "previous", "vendor") if k in pr}}
        return {"total": total, "items": items}

    def loads(self, status: str | None = "open", source_ids: list[str] | None = None, vendor_id: str | None = None,
              tier: str | None = None) -> dict:
        """Distinct file loads that have exceptions — options for vendor / file / date filters."""
        t, b = db.exceptions, db.batches
        conds = []
        if status == "open":
            conds.append(t.c.status.in_(OPEN_STATES))
        elif status:
            conds.append(t.c.status == status)
        if tier:
            conds.append(t.c.tier == tier)
        if source_ids is not None:
            conds.append(t.c.source_id.in_(source_ids or ["-"]))
        where = and_(*conds) if conds else True
        load_ts = func.coalesce(b.c.started_at, b.c.created_at)
        with db.get_engine().connect() as c:
            from ..vendors import names_by_source

            names = names_by_source(c)
            if vendor_id:
                sids = [sid for sid, n in names.items() if n.get("vendor_id") == vendor_id]
                where = and_(where, t.c.source_id.in_(sids or ["-"]))
            rows = c.execute(
                select(t.c.batch_id, t.c.source_id, b.c.filename, load_ts.label("loaded_at"), func.count().label("open_count"))
                .select_from(t.outerjoin(b, b.c.batch_id == t.c.batch_id))
                .where(where).group_by(t.c.batch_id, t.c.source_id, b.c.filename, load_ts)
                .order_by(load_ts.desc().nullslast())
            ).all()
        out = []
        for r in rows:
            n = names.get(r.source_id) or {}
            loaded = r.loaded_at
            iso = loaded.isoformat() + "Z" if hasattr(loaded, "isoformat") else None
            out.append({
                "batch_id": r.batch_id,
                "source_id": r.source_id,
                "filename": r.filename,
                "loaded_at": iso,
                "loaded_on": iso[:10] if iso else None,
                "vendor_id": n.get("vendor_id"),
                "vendor_name": n.get("vendor_name"),
                "feed_name": n.get("feed_name"),
                "open_count": r.open_count,
            })
        return {"loads": out}
    def get(self, exception_id: str, roles: list[str] | None = None) -> dict:
        with db.get_engine().connect() as c:
            row = c.execute(select(db.exceptions).where(db.exceptions.c.exception_id == exception_id)).first()
            if not row:
                raise ExceptionActionError("exception not found")
            ex = db.row_to_dict(row)
            st = c.execute(select(db.loans_staging).where(db.loans_staging.c.id == ex["staging_id"])).first()
            siblings = c.execute(select(db.exceptions.c.exception_id, db.exceptions.c.rule_id, db.exceptions.c.field,
                                        db.exceptions.c.status, db.exceptions.c.tier)
                                 .where(db.exceptions.c.staging_id == ex["staging_id"])).all()
            audit = c.execute(select(db.audit_log).where(db.audit_log.c.entity_id == exception_id).order_by(db.audit_log.c.ts)).all()
        record = (st.record if st else {}) or {}
        can_see_pii = bool(set(roles or []) & {"compliance", "admin"})
        ex["loan_record"] = record if can_see_pii else mask_record(record, TARGET_PII_TYPES)
        if not can_see_pii and ex["field"] in TARGET_PII_TYPES:
            from ..ingestion.pii import mask_value

            kind = TARGET_PII_TYPES[ex["field"]]
            ex["original_value"] = mask_value(ex["original_value"], kind) if ex["original_value"] else ex["original_value"]
            if ex.get("resolved_value"):
                ex["resolved_value"] = mask_value(ex["resolved_value"], kind)
            if ex.get("proposal"):
                pr = ex["proposal"]
                ex["proposal"] = {**pr, "precedents": [], **{k: (mask_value(str(pr[k]), kind) if pr.get(k) not in (None, "") else pr.get(k))
                                                            for k in ("value", "previous", "vendor") if k in pr}}
        ex["loan_status"] = st.status if st else None
        ex["loan_boarded"] = bool(st.boarded) if st else False
        ex["related"] = [dict(s._mapping) for s in siblings if s.exception_id != exception_id]
        if ex["rule_id"] in ("DUP01", "DUP02"):
            ex["sse_compare"] = self._sse_compare(ex["loan_number"], record, can_see_pii)
        ex["audit"] = [db.row_to_dict(a) for a in audit]
        return ex

    def _sse_compare(self, loan_number: str, incoming: dict, can_see_pii: bool) -> dict:
        """Field-by-field comparison of an incoming duplicate with the loan already in SSE."""
        from ..ingestion.pii import mask_value

        with db.get_engine().connect() as c:
            row = c.execute(select(db.sse_loans).where(db.sse_loans.c.loan_number == loan_number)).first()
        if not row:
            return {"existing": False}
        cur = dict(row._mapping)
        diffs = []
        for k, v in incoming.items():
            old = cur.get(k)
            old_s = None if old is None else (old.isoformat() if hasattr(old, "isoformat") else str(old))
            new_s = None if v in (None, "") else str(v)
            if k in cur and (old_s or None) != (new_s or None):
                try:
                    if old is not None and v not in (None, "") and float(old) == float(v):
                        continue
                except (TypeError, ValueError):
                    pass
                if not can_see_pii and k in TARGET_PII_TYPES:
                    old_s = mask_value(old_s, TARGET_PII_TYPES[k]) if old_s else old_s
                    new_s = mask_value(new_s, TARGET_PII_TYPES[k]) if new_s else new_s
                diffs.append({"field": k, "in_sse": old_s, "incoming": new_s})
        return {"existing": True, "existing_batch_id": cur.get("lbp_batch_id"),
                "boarded_at": cur["lbp_boarded_at"].isoformat() if cur.get("lbp_boarded_at") else None,
                "differences": diffs, "identical": not diffs}

    # ------------------------------------------------------------------ actions
    def _load(self, c, exception_id):
        row = c.execute(select(db.exceptions).where(db.exceptions.c.exception_id == exception_id).with_for_update()).first()
        if not row:
            raise ExceptionActionError("exception not found")
        return dict(row._mapping)

    def _set(self, c, exception_id, **values):
        c.execute(db.exceptions.update().where(db.exceptions.c.exception_id == exception_id).values(**values))

    def resolve(self, exception_id: str, actor: str, roles: list[str], value=None, use_proposal: bool = False,
                comment: str | None = None) -> dict:
        with db.get_engine().begin() as c:
            ex = self._load(c, exception_id)
            if ex["status"] not in ("open", "pending_review"):
                raise ExceptionActionError(f"cannot resolve an exception in status {ex['status']}")
            if ex["tier"] == "T5":
                raise ExceptionActionError("T5 exceptions are blocked; only Compliance can clear or reject them")
            if use_proposal:
                if not ex["proposal"] or ex["proposal"].get("value") is None:
                    raise ExceptionActionError("no proposal to accept")
                value = ex["proposal"]["value"]
            if value is None:
                raise ExceptionActionError("a corrected value is required")
            typed = _coerce(ex["field"], value)
            if ex["tier"] == "T4":
                # maker step: needs a distinct checker
                self._set(c, exception_id, status="pending_checker", maker=actor, resolved_value=_str(typed))
                db.audit(c, actor, "exception.maker_submit", "exception", exception_id, {"value": _str(typed), "comment": comment})
                return {"exception_id": exception_id, "status": "pending_checker"}
            self._set(c, exception_id, status="resolved", maker=actor, resolved_value=_str(typed), resolved_at=db.now())
            db.audit(c, actor, "exception.resolve", "exception", exception_id,
                     {"value": _str(typed), "accepted_ai": bool(use_proposal), "comment": comment})
            self._remember(c, ex, typed, actor)
            boarded = self._finalize_loan(c, ex["staging_id"], actor)
        return {"exception_id": exception_id, "status": "resolved", "loan_boarded": boarded}

    def checker_decision(self, exception_id: str, actor: str, roles: list[str], approve: bool, comment: str | None = None) -> dict:
        from ..security import expand_roles

        roles = list(expand_roles(roles))
        with db.get_engine().begin() as c:
            ex = self._load(c, exception_id)
            if ex["status"] != "pending_checker":
                raise ExceptionActionError("exception is not awaiting a checker")
            if actor == ex["maker"]:
                raise ExceptionActionError("maker-checker: checker must be a different user from the maker")
            if not set(roles) & {"monitoring_reviewer", "admin"}:
                raise ExceptionActionError("monitoring reviewer role required")
            if not approve:
                self._set(c, exception_id, status="open", checker=actor)
                db.audit(c, actor, "exception.checker_reject", "exception", exception_id, {"comment": comment})
                return {"exception_id": exception_id, "status": "open"}
            self._set(c, exception_id, status="resolved", checker=actor, resolved_at=db.now())
            db.audit(c, actor, "exception.checker_approve", "exception", exception_id, {"value": ex["resolved_value"], "comment": comment})
            self._remember(c, ex, ex["resolved_value"], actor)
            boarded = self._finalize_loan(c, ex["staging_id"], actor)
        return {"exception_id": exception_id, "status": "resolved", "loan_boarded": boarded}

    def reject_loan(self, exception_id: str, actor: str, roles: list[str], reason: str) -> dict:
        from ..security import expand_roles

        roles = list(expand_roles(roles))
        with db.get_engine().begin() as c:
            ex = self._load(c, exception_id)
            if ex["tier"] == "T5" and "compliance_reviewer" not in roles and "admin" not in roles:
                raise ExceptionActionError("only Compliance can act on T5 exceptions")
            c.execute(db.exceptions.update().where(and_(db.exceptions.c.staging_id == ex["staging_id"],
                                                        db.exceptions.c.status.in_(OPEN_STATES)))
                      .values(status="rejected", maker=actor, resolved_at=db.now()))
            c.execute(db.loans_staging.update().where(db.loans_staging.c.id == ex["staging_id"]).values(status="REJECTED", updated_at=db.now()))
            db.audit(c, actor, "loan.reject", "exception", exception_id, {"reason": reason, "loan_number": ex["loan_number"]})
        return {"exception_id": exception_id, "status": "rejected"}

    def escalate(self, exception_id: str, actor: str, roles: list[str], reason: str) -> dict:
        with db.get_engine().begin() as c:
            ex = self._load(c, exception_id)
            self._set(c, exception_id, status="escalated", tier="T5" if ex["category"] in ("compliance", "fraud") else ex["tier"])
            db.audit(c, actor, "exception.escalate", "exception", exception_id, {"reason": reason})
        return {"exception_id": exception_id, "status": "escalated"}

    def compliance_clear(self, exception_id: str, actor: str, roles: list[str], value, comment: str) -> dict:
        """Compliance has investigated outside EM (e.g. OFAC false positive) and records the outcome."""
        from ..security import expand_roles

        roles = list(expand_roles(roles))
        if "compliance_reviewer" not in roles and "admin" not in roles:
            raise ExceptionActionError("Compliance role required")
        with db.get_engine().begin() as c:
            ex = self._load(c, exception_id)
            if ex["tier"] != "T5":
                raise ExceptionActionError("only T5 exceptions use compliance clearance")
            if not comment:
                raise ExceptionActionError("an investigation note is required")
            typed = _coerce(ex["field"], value)
            self._set(c, exception_id, status="resolved", checker=actor, resolved_value=_str(typed), resolved_at=db.now())
            db.audit(c, actor, "exception.compliance_clear", "exception", exception_id, {"value": _str(typed), "note": comment})
            boarded = self._finalize_loan(c, ex["staging_id"], actor)
        return {"exception_id": exception_id, "status": "resolved", "loan_boarded": boarded}

    def bulk_resolve(self, actor: str, roles: list[str], rule_id: str, original_value, value=None, use_proposal: bool = False,
                     batch_id: str | None = None, limit: int = 5000) -> dict:
        t = db.exceptions
        conds = [t.c.rule_id == rule_id, t.c.status.in_(("open", "pending_review")), t.c.tier.in_(("T2", "T3"))]
        conds.append(t.c.original_value.is_(None) if original_value is None else t.c.original_value == _str(original_value))
        if batch_id:
            conds.append(t.c.batch_id == batch_id)
        with db.get_engine().connect() as c:
            ids = [r[0] for r in c.execute(select(t.c.exception_id).where(and_(*conds)).limit(limit))]
        done, errors = 0, []
        for eid in ids:
            try:
                self.resolve(eid, actor, roles, value=value, use_proposal=use_proposal, comment="bulk resolve")
                done += 1
            except ExceptionActionError as e:
                errors.append({"exception_id": eid, "error": str(e)})
        return {"matched": len(ids), "resolved": done, "errors": errors[:20]}

    def rollback(self, exception_id: str, actor: str, roles: list[str], reason: str) -> dict:
        """Undo a T1 auto-apply inside the rollback window (target < 5 min to execute)."""
        policy = get_policy()
        with db.get_engine().begin() as c:
            ex = self._load(c, exception_id)
            if ex["status"] != "auto_applied":
                raise ExceptionActionError("only auto-applied fixes can be rolled back")
            if db.now() - ex["created_at"] > timedelta(minutes=policy["rollback_window_minutes"]) and "admin" not in roles:
                raise ExceptionActionError("rollback window has passed; admin required")
            st = c.execute(select(db.loans_staging).where(db.loans_staging.c.id == ex["staging_id"])).first()
            rec = dict(st.record)
            rec[ex["field"]] = ex["original_value"]
            c.execute(db.loans_staging.update().where(db.loans_staging.c.id == st.id).values(record=rec, status="FAIL", boarded=False))
            c.execute(db.sse_loans.delete().where(db.sse_loans.c.loan_number == ex["loan_number"]))
            self._set(c, exception_id, status="open", tier="T3", queue=QUEUES["T3"], resolved_value=None)
            db.audit(c, actor, "exception.rollback", "exception", exception_id, {"reason": reason, "override": True})
        return {"exception_id": exception_id, "status": "open", "tier": "T3"}

    def qa_review(self, exception_id: str, actor: str, roles: list[str], correct: bool, comment: str | None = None) -> dict:
        with db.get_engine().begin() as c:
            ex = self._load(c, exception_id)
            if ex["status"] != "auto_applied":
                raise ExceptionActionError("QA applies to auto-applied fixes")
            db.audit(c, actor, "exception.qa_pass" if correct else "exception.qa_fail", "exception", exception_id, {"comment": comment})
            self._set(c, exception_id, qa_sample=False)
        if not correct:
            return self.rollback(exception_id, actor, roles + ["admin"], f"QA failed: {comment}")
        return {"exception_id": exception_id, "qa": "passed"}

    def ai_suggest(self, exception_id: str) -> dict:
        """On-demand LLM suggestion with masked context; stored as proposal, never auto-applied."""
        ex = self.get(exception_id)
        if ex["tier"] in ("T5",):
            raise ExceptionActionError("no AI suggestions for blocked loans")
        llm = get_llm()
        ctx = {k: v for k, v in ex["loan_record"].items() if v not in (None, "")}
        out = llm.complete_json(
            "You fix mortgage loan data exceptions. Respond JSON {\"value\":..., \"confidence\":0-1, \"rationale\":str}. "
            "If unsure, set value null.",
            json.dumps({"rule": ex["rule_name"], "message": ex["message"], "field": ex["field"],
                        "current_value": ex.get("original_value_masked") or ex["original_value"], "loan": ctx}, default=str),
        )
        if not isinstance(out, dict) or out.get("value") is None:
            return {"exception_id": exception_id, "proposal": ex["proposal"], "note": f"no suggestion from {llm.name}"}
        proposal = {"value": out["value"], "confidence": min(float(out.get("confidence", 0.5)), 0.94), "source": f"llm:{llm.name}",
                    "rationale": str(out.get("rationale", ""))[:500], "fix_kind": "llm", "hint_only": ex["tier"] in ("T3", "T4")}
        with db.get_engine().begin() as c:
            self._set(c, exception_id, proposal=proposal)
            db.audit(c, "ai", "exception.ai_suggest", "exception", exception_id, {"provider": llm.name})
        return {"exception_id": exception_id, "proposal": proposal}

    # ------------------------------------------------------------------ internals
    def _remember(self, c, ex, value, actor):
        self.index.add(c, ex["rule_id"], ex["field"], ex["source_id"], ex["original_value"], _str(value), {"tier": ex["tier"]}, actor)

    def _finalize_loan(self, c, staging_id: int, actor: str) -> bool:
        """Apply resolved values, re-validate, board to SSE when no blocking exceptions remain.

        Change files: an update is re-merged onto the *live* SSE record and only its fields are written
        (rebased under optimistic concurrency, see pipeline/changes.py); a close marks the loan closed."""
        from ..pipeline.loader import load_records
        from ..rules.executor import RuleExecutor
        from ..rules.registry import RuleRegistry

        st = c.execute(select(db.loans_staging).where(db.loans_staging.c.id == staging_id)).first()
        if not st or st.boarded:
            return False
        exs = c.execute(select(db.exceptions).where(db.exceptions.c.staging_id == staging_id)).all()
        rec = dict(st.record)
        resolved_fields = set()
        for e in exs:
            if e.status in ("resolved", "auto_applied") and e.resolved_value is not None:
                rec[e.field] = _coerce(e.field, e.resolved_value)
                if e.status == "resolved":
                    resolved_fields.add(e.field)
        open_blocking = [e for e in exs if e.blocking and e.status in OPEN_STATES + ("rejected",)]
        c.execute(db.loans_staging.update().where(db.loans_staging.c.id == staging_id).values(record=rec, updated_at=db.now()))
        if open_blocking:
            return False
        action = st.action or "add"
        source_id = exs[0].source_id if exs else None
        if action in ("close", "close_inferred"):
            return self._finalize_close(c, st, rec, source_id, actor)
        executor = RuleExecutor(RuleRegistry().runtime_set())
        live = None
        if action == "update":
            from ..pipeline.changes import current_rows

            live = current_rows(c, [rec.get("loan_number")]).get(str(rec.get("loan_number")))
            if live is None:
                self._raise_new(c, st, rec, [("CHG02", "loan_number", f"Loan {rec.get('loan_number')} is not in SSE; correct the loan number or reject.")], actor)
                return False
            delta = set((st.changes or {}).keys()) | resolved_fields
            delta.discard("loan_number")
            delta = {f for f in delta if not f.startswith("lbp_")}
            base = {k: v for k, v in live.items() if not k.startswith("lbp_")}
            rec = {**base, **{f: rec.get(f) for f in delta}, "loan_number": live["loan_number"]}
        ev = executor.evaluate(rec)
        resolved_rules = {(e.rule_id, e.field) for e in exs}
        fails = [f for f in ev.failures if f.severity == "FAIL"]
        if action == "update" and fails:
            base_ev = executor.evaluate({k: v for k, v in live.items() if not k.startswith("lbp_")})
            pre = {(f.rule_id, f.field) for f in base_ev.failures}
            fails = [f for f in fails if not ((f.rule_id, f.field) in pre and f.field not in delta)]
        new_fails = [f for f in fails if (f.rule_id, f.field) not in resolved_rules]
        still = [f for f in fails if (f.rule_id, f.field) in resolved_rules]
        if new_fails or still:
            triage = Triage()
            for f in new_fails + still:
                row = triage.classify_and_propose(f.rule_id, f.name, f.category, f.severity, f.field, rec, f.message, f.regulatory_tag)
                row.pop("regulatory_tag", None)
                row["status"] = "pending_review" if row["tier"] != "T5" else "escalated"
                c.execute(db.exceptions.insert().values(exception_id=db.new_id("ex"), batch_id=st.batch_id, source_id=source_id,
                                                        loan_number=st.loan_number, staging_id=staging_id, rule_version=f.version, **row))
            db.audit(c, actor, "loan.revalidate_failed", "loan", st.loan_number, {"rules": [f.rule_id for f in new_fails + still]})
            return False
        if action == "update":
            from ..pipeline.changes import apply_updates, conflict_failures
            from ..pipeline.delivery import is_protected_change, norm, profile_of

            if st.base_version is None:
                # no base record when the row arrived (loan number was corrected): the protected-field check
                # runs now, against the loan it will actually change
                prof = profile_of(c.execute(select(db.sources.c.delivery).where(db.sources.c.source_id == source_id)).scalar())
                prot = [f for f in sorted(delta) if is_protected_change(prof, f, rec) and norm(live.get(f)) != norm(rec.get(f))
                        and ("CHG01", f) not in resolved_rules]
                if prot:
                    self._raise_new(c, st, rec, [("CHG01", f, f"{f} changed from '{live.get(f)}' to '{rec.get(f)}'. Protected fields "
                                                  "need a maker and a checker.") for f in prot], actor)
                    return False
                resolved_fields |= delta

            old = {f: ((st.changes or {}).get(f) or {}).get("old", live.get(f)) for f in delta}
            item = {"idx": 0, "staging_id": staging_id, "loan_number": rec["loan_number"], "record": rec, "base_version": st.base_version,
                    "changes": {f: {"old": old[f], "new": rec.get(f)} for f in delta}, "dq_status": ev.status,
                    "force_fields": resolved_fields, "reopen": rec.get("lbp_status") == "active" and live.get("lbp_status") == "closed",
                    "reassign_source": source_id if any(e.rule_id == "CHG06" and e.status == "resolved" for e in exs) else None}
            if live.get("lbp_status") == "closed" and not item["reopen"]:
                self._raise_new(c, st, rec, [("CHG03", "lbp_status", "Loan is closed in SSE; resolve with 'active' to reopen it.")], actor)
                return False
            applied, conflicts = apply_updates(c, [item], st.batch_id, source_id, actor)
            if conflicts:
                self._raise_new(c, st, rec, [(f["rule_id"], f["field"], f["message"],
                                              {"value": f.get("live"), "vendor": f.get("vendor"), "previous": f.get("old"), "confidence": 0.0,
                                               "source": "conflict", "fix_kind": "vendor", "hint_only": True,
                                               "rationale": "SSE changed after the vendor produced this file."} if "live" in f else None)
                                             for f in conflict_failures(conflicts[0])], actor)
                return False
        else:
            load_records(c, [(rec, ev.status)], st.batch_id, source_id=source_id)
        c.execute(db.loans_staging.update().where(db.loans_staging.c.id == staging_id).values(boarded=True, status=ev.status, record=rec))
        c.execute(db.batches.update().where(db.batches.c.batch_id == st.batch_id).values(loaded=db.batches.c.loaded + 1))
        db.audit(c, actor, "loan.boarded" if action == "add" else "loan.updated", "loan", st.loan_number,
                 {"batch_id": st.batch_id, "after_exception_resolution": True})
        return True

    def _finalize_close(self, c, st, rec, source_id, actor) -> bool:
        from ..pipeline.changes import apply_closes

        decision = str(rec.get("lbp_status") or "closed").lower()
        if st.action == "close_inferred" and decision != "closed":
            c.execute(db.loans_staging.update().where(db.loans_staging.c.id == st.id).values(status="REJECTED", updated_at=db.now()))
            db.audit(c, actor, "loan.close_declined", "loan", st.loan_number, {"batch_id": st.batch_id, "kept": "active"})
            return False
        reason = "snapshot_absent" if st.action == "close_inferred" else ((st.changes or {}).get("close_reason") or "closed")
        applied, conflicts = apply_closes(c, [{"idx": 0, "staging_id": st.id, "loan_number": st.loan_number, "close_reason": reason}],
                                          st.batch_id, source_id, actor)
        if conflicts:
            self._raise_new(c, st, rec, [("CHG02", "loan_number", "Loan is no longer in SSE.")], actor)
            return False
        c.execute(db.loans_staging.update().where(db.loans_staging.c.id == st.id).values(boarded=True, status="PASS", updated_at=db.now()))
        c.execute(db.batches.update().where(db.batches.c.batch_id == st.batch_id).values(loaded=db.batches.c.loaded + 1))
        db.audit(c, actor, "loan.closed", "loan", st.loan_number, {"batch_id": st.batch_id, "reason": reason})
        return True

    def _raise_new(self, c, st, rec, items, actor) -> None:
        from ..pipeline.batch import _route_change_rule
        from ..pipeline.incremental import CHANGE_RULES

        triage = Triage()
        src = c.execute(select(db.batches.c.source_id).where(db.batches.c.batch_id == st.batch_id)).scalar()
        for item in items:
            rule_id, field, msg = item[:3]
            row = triage.classify_and_propose(rule_id, CHANGE_RULES.get(rule_id, rule_id), "change_control", "FAIL", field, rec, msg)
            row.pop("regulatory_tag", None)
            _route_change_rule(row, rec)
            if len(item) > 3 and item[3]:
                row["proposal"] = item[3]
            row["status"] = "escalated" if row["tier"] == "T5" else "open"
            row["qa_sample"] = False
            c.execute(db.exceptions.insert().values(exception_id=db.new_id("ex"), batch_id=st.batch_id, source_id=src,
                                                    loan_number=st.loan_number, staging_id=st.id, **row))
        db.audit(c, actor, "loan.change_held", "loan", st.loan_number, {"rules": [i[0] for i in items]})
