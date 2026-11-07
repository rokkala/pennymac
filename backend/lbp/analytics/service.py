"""Pillar 2 - analytics over the processed zone.

Six dashboards from the PoV (Import Status, Exception Analytics, DQ Scorecard, Source
Performance, AI Mapping Insights, Executive Summary) plus a natural-language "ask" endpoint.
Locally these query the platform tables directly; in AWS the same metrics are materialised
as Redshift Serverless views over S3/Glue-catalogued Parquet and served through embedded
QuickSight (see aws/terraform/analytics.tf and docs/analytics.md).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import and_, func, or_, select

from ..exceptions.policy import TIER_LABELS
from ..schema.sse_target import ATTRIBUTES, BY_NAME, MODULES  # noqa: F401
from ..store import db

DAY = timedelta(days=1)
ATTENTION_STATUSES = ("failed", "blocked", "waiting", "paused", "out_of_order")
# Step Functions history is only polled for in-flight rows on the list endpoint (throttle).
TRACE_STATUSES = ("queued", "running", "pausing", "paused", "blocked", "waiting", "out_of_order")


def _iso(d):
    return d.isoformat() + "Z" if d else None


def _seq(v):
    from ..pipeline.delivery import display_sequence

    return display_sequence(v)


def _label(names: dict, sid) -> str:
    """'Vendor · Feed' (or just the vendor when the feed carries the vendor's name)."""
    n = names.get(sid)
    if not n:
        return sid
    return n["vendor_name"] if n["feed_name"] == n["vendor_name"] else f"{n['vendor_name']} · {n['feed_name']}"


def _names(c) -> dict:
    from ..vendors import names_by_source

    return names_by_source(c)


def import_status(limit: int = 50, source_ids: list[str] | None = None, *,
                  statuses: list[str] | None = None, since=None, until=None, q: str | None = None) -> dict:
    b = db.batches
    e = db.exceptions
    open_states = ("open", "pending_review", "pending_checker", "escalated")
    limit = max(1, min(int(limit or 50), 200))

    def _scope_time_q(stmt):
        if source_ids is not None:
            stmt = stmt.where(b.c.source_id.in_(source_ids or ["-"]))
        if since is not None:
            stmt = stmt.where(b.c.created_at >= since)
        if until is not None:
            stmt = stmt.where(b.c.created_at <= until)
        if q:
            needle = f"%{q.strip()}%"
            stmt = stmt.where(or_(b.c.filename.ilike(needle), b.c.batch_id.ilike(needle)))
        return stmt

    with db.get_engine().connect() as c:
        q_rows = _scope_time_q(select(b, db.sources.c.name.label("source_name")).join(
            db.sources, db.sources.c.source_id == b.c.source_id))
        if statuses:
            q_rows = q_rows.where(b.c.status.in_(statuses))
        rows = c.execute(q_rows.order_by(b.c.created_at.desc()).limit(limit)).all()
        attn_statuses = [s for s in (statuses or ATTENTION_STATUSES) if s in ATTENTION_STATUSES]
        attn_q = _scope_time_q(select(func.count()).select_from(b)).where(
            b.c.status.in_(attn_statuses or ["__none__"]))
        attention = int(c.execute(attn_q).scalar() or 0)
        names = _names(c)
        bids = [r.batch_id for r in rows]
        ex_total, ex_open = {}, {}
        if bids:
            for bid, n in c.execute(select(e.c.batch_id, func.count()).where(e.c.batch_id.in_(bids)).group_by(e.c.batch_id)):
                ex_total[bid] = n
            for bid, n in c.execute(select(e.c.batch_id, func.count()).where(e.c.batch_id.in_(bids), e.c.status.in_(open_states)).group_by(e.c.batch_id)):
                ex_open[bid] = n
    items = []
    for r in rows:
        total = r.total_rows or 0
        remaining = max(total - (r.processed or 0), 0)
        eta = round(remaining / r.throughput_lps) if r.throughput_lps and r.status == "running" else None
        mbs = r.micro_batches or []
        items.append({
            "batch_id": r.batch_id, "source_id": r.source_id, "source_name": r.source_name,
            "vendor_id": names.get(r.source_id, {}).get("vendor_id"), "vendor_name": names.get(r.source_id, {}).get("vendor_name"), "filename": r.filename, "status": r.status,
            "total_rows": total, "processed": r.processed, "passed": r.passed, "warned": r.warned, "failed": r.failed, "loaded": r.loaded,
            "exceptions": ex_total.get(r.batch_id, 0), "open_exceptions": ex_open.get(r.batch_id, 0),
            "progress_pct": round((r.processed or 0) / total * 100, 1) if total else (100.0 if r.status == "completed" else 0.0),
            "throughput_lps": r.throughput_lps, "projected_24h": int((r.throughput_lps or 0) * 86400), "eta_seconds": eta,
            "micro_batches": len(mbs), "last_micro_batches": mbs[-20:], "created_at": _iso(r.created_at), "started_at": _iso(r.started_at),
            "finished_at": _iso(r.finished_at), "reconciliation": r.reconciliation, "error": r.error, "submitted_by": r.submitted_by,
            "preflight": r.preflight, "replays": r.replays or [], "mapping_id": r.mapping_id,
            "load_type": r.load_type or "full", "sequence": _seq(r.sequence), "sequence_detail": r.sequence_detail,
            "change_summary": r.change_summary, "delivery_id": r.delivery_id,
        })
    from ..pipeline.trace import fetch_traces

    trace_ids = [i["batch_id"] for i in items if i["status"] in TRACE_STATUSES]
    for bid, trace in fetch_traces(trace_ids).items():
        for item in items:
            if item["batch_id"] == bid:
                item["pipeline"] = trace
    running = [i for i in items if i["status"] in ("running", "queued")]
    return {"batches": items, "running": len(running), "attention": attention,
            "current_throughput_lps": round(sum(i["throughput_lps"] or 0 for i in running), 1),
            "target_lps": round(1_000_000 / 86400, 1)}


def exception_analytics(days: int = 30, source_ids: list[str] | None = None) -> dict:
    e = db.exceptions
    since = db.now() - days * DAY
    with db.get_engine().connect() as c:
        q = select(e.c.rule_id, e.c.rule_name, e.c.category, e.c.tier, e.c.status, e.c.field, e.c.severity, e.c.source_id,
                   e.c.created_at, e.c.resolved_at, e.c.original_value, e.c.blocking).where(e.c.created_at >= since)
        if source_ids is not None:
            q = q.where(e.c.source_id.in_(source_ids or ["-"]))
        rows = c.execute(q).all()
        nm = _names(c)
        src_names = {k: _label(nm, k) for k in nm}
    by_cat, by_rule, by_tier, by_status, by_src = Counter(), Counter(), Counter(), Counter(), Counter()
    rule_names, trend = {}, defaultdict(lambda: {"created": 0, "resolved": 0, "auto_applied": 0})
    res_time = defaultdict(list)
    aging = Counter()
    top_values = Counter()
    now = db.now()
    for r in rows:
        by_cat[r.category] += 1
        by_rule[r.rule_id] += 1
        rule_names[r.rule_id] = r.rule_name
        by_tier[r.tier] += 1
        by_status[r.status] += 1
        by_src[src_names.get(r.source_id, r.source_id)] += 1
        trend[r.created_at.date().isoformat()]["created"] += 1
        if r.status == "auto_applied":
            trend[r.created_at.date().isoformat()]["auto_applied"] += 1
        if r.resolved_at and r.status in ("resolved", "auto_applied"):
            trend[r.resolved_at.date().isoformat()]["resolved"] += 1
            res_time[r.tier].append((r.resolved_at - r.created_at).total_seconds() / 60)
        if r.status in ("open", "pending_review", "pending_checker", "escalated"):
            age_h = (now - r.created_at).total_seconds() / 3600
            aging["<4h" if age_h < 4 else "4-24h" if age_h < 24 else "1-3d" if age_h < 72 else ">3d"] += 1
            top_values[(r.rule_id, r.original_value)] += 1
    total = len(rows)
    auto = by_status.get("auto_applied", 0)
    return {
        "total": total,
        "open": sum(by_status.get(s, 0) for s in ("open", "pending_review", "pending_checker", "escalated")),
        "auto_applied": auto, "auto_apply_rate": round(auto / total * 100, 1) if total else 0,
        "by_category": dict(by_cat.most_common()),
        "by_rule": [{"rule_id": k, "rule_name": rule_names[k], "count": v} for k, v in by_rule.most_common(15)],
        "by_tier": [{"tier": t, "label": TIER_LABELS[t], "count": by_tier.get(t, 0)} for t in ("T1", "T2", "T3", "T4", "T5")],
        "by_status": dict(by_status), "by_source": dict(by_src.most_common()),
        "trend": [{"date": d, **v} for d, v in sorted(trend.items())],
        "avg_resolution_minutes": {t: round(sum(v) / len(v), 1) for t, v in res_time.items() if v},
        "aging": {k: aging.get(k, 0) for k in ("<4h", "4-24h", "1-3d", ">3d")},
        "bulk_candidates": [{"rule_id": k[0], "original_value": k[1], "count": v} for k, v in top_values.most_common(10) if v > 1],
    }


def dq_scorecard(sample_limit: int = 20000, source_ids: list[str] | None = None) -> dict:
    st, e = db.loans_staging, db.exceptions
    with db.get_engine().connect() as c:
        bsrc = dict(c.execute(select(db.batches.c.batch_id, db.batches.c.source_id)).all())
        rq = select(st.c.record, st.c.batch_id).where(st.c.row_number.is_not(None), st.c.status != "UNCHANGED")
        fq, mq, tq = select(e.c.field, func.count()), select(e.c.source_id, e.c.field, func.count()), select(func.count()).select_from(st)
        if source_ids is not None:
            bids = [k for k, v in bsrc.items() if v in source_ids] or ["-"]
            rq, tq = rq.where(st.c.batch_id.in_(bids)), tq.where(st.c.batch_id.in_(bids))
            fq, mq = fq.where(e.c.source_id.in_(source_ids or ["-"])), mq.where(e.c.source_id.in_(source_ids or ["-"]))
        recs = c.execute(rq.order_by(st.c.id.desc()).limit(sample_limit)).all()
        nm = _names(c)
        src_names = {k: _label(nm, k) for k in nm}
        ex_by_field = dict(c.execute(fq.group_by(e.c.field)).all())
        ex_by_src_mod = c.execute(mq.group_by(e.c.source_id, e.c.field)).all()
        total_loans = c.execute(tq).scalar() or 0
    n = len(recs)
    filled = Counter()
    per_src_n = Counter()
    for r, bid in recs:
        per_src_n[bsrc.get(bid)] += 1
        for k, v in (r or {}).items():
            if v not in (None, ""):
                filled[k] += 1
    fields = []
    for a in ATTRIBUTES:
        comp = round(filled[a.name] / n * 100, 1) if n else 0
        err_rate = round(ex_by_field.get(a.name, 0) / total_loans * 100, 2) if total_loans else 0
        if comp == 0 and not a.required:
            continue
        validity = max(0.0, 100 - err_rate * 5)
        score = round((0.6 * comp + 0.4 * validity) if a.required else (0.3 * comp + 0.7 * validity), 1)
        fields.append({"field": a.name, "module": a.module, "required": a.required, "risk": a.risk, "completeness": comp,
                       "exception_rate": err_rate, "validity": round(validity, 1), "score": score})
    # heatmap source x module
    src_mod = defaultdict(lambda: defaultdict(int))
    for sid, fld, cnt in ex_by_src_mod:
        if fld in BY_NAME:
            src_mod[sid][BY_NAME[fld].module] += cnt
    heat = []
    for sid, cnt in per_src_n.items():
        if not sid:
            continue
        row = {"source": src_names.get(sid, sid)}
        for m in MODULES:
            nfields = len([a for a in ATTRIBUTES if a.module == m])
            row[m] = round(max(0.0, 100 - src_mod[sid][m] / max(cnt * nfields, 1) * 100 * 20), 1)
        heat.append(row)
    req = [f for f in fields if f["required"]]
    overall = round(sum(f["score"] for f in fields) / len(fields), 1) if fields else 0
    return {"overall_score": overall, "sampled_loans": n,
            "required_completeness": round(sum(f["completeness"] for f in req) / len(req), 1) if req else 0,
            "fields": sorted(fields, key=lambda f: f["score"]), "heatmap": heat, "modules": MODULES}


def source_performance(source_ids: list[str] | None = None) -> dict:
    b = db.batches
    with db.get_engine().connect() as c:
        q = (select(db.sources.c.source_id, db.sources.c.name, db.sources.c.format, db.sources.c.status,
                    func.count(b.c.batch_id), func.sum(b.c.processed), func.sum(b.c.loaded), func.sum(b.c.failed),
                    func.avg(b.c.throughput_lps))
             .select_from(db.sources.outerjoin(b, b.c.source_id == db.sources.c.source_id)))
        if source_ids is not None:
            q = q.where(db.sources.c.source_id.in_(source_ids or ["-"]))
        rows = c.execute(q.group_by(db.sources.c.source_id, db.sources.c.name, db.sources.c.format, db.sources.c.status)).all()
        names = _names(c)
        ex = dict(c.execute(select(db.exceptions.c.source_id, func.count()).group_by(db.exceptions.c.source_id)).all())
        auto = dict(c.execute(select(db.exceptions.c.source_id, func.count()).where(db.exceptions.c.status == "auto_applied")
                              .group_by(db.exceptions.c.source_id)).all())
        durations = c.execute(select(b.c.source_id, b.c.started_at, b.c.finished_at).where(b.c.finished_at.is_not(None))).all()
    dur = defaultdict(list)
    for sid, s, f in durations:
        if s and f:
            dur[sid].append((f - s).total_seconds())
    out = []
    for sid, name, fmt, status, nb, proc, loaded, failed, tput in rows:
        proc, loaded = proc or 0, loaded or 0
        out.append({"source_id": sid, "name": _label(names, sid), "feed_name": name, "vendor_id": names.get(sid, {}).get("vendor_id"),
                    "vendor_name": names.get(sid, {}).get("vendor_name"), "format": fmt, "status": status, "batches": nb, "loans_processed": proc,
                    "loans_boarded": loaded, "success_rate": round(loaded / proc * 100, 1) if proc else None,
                    "first_pass_failure_rate": round((failed or 0) / proc * 100, 1) if proc else None,
                    "exceptions": ex.get(sid, 0), "exceptions_per_100": round(ex.get(sid, 0) / proc * 100, 1) if proc else None,
                    "auto_fixed": auto.get(sid, 0), "avg_throughput_lps": round(tput or 0, 1),
                    "avg_batch_seconds": round(sum(dur[sid]) / len(dur[sid]), 1) if dur[sid] else None})
    return {"sources": sorted(out, key=lambda x: -(x["loans_processed"] or 0))}


def ai_mapping_insights(source_ids: list[str] | None = None) -> dict:
    with db.get_engine().connect() as c:
        q = select(db.mappings, db.sources.c.name).join(db.sources, db.sources.c.source_id == db.mappings.c.source_id)
        if source_ids is not None:
            q = q.where(db.mappings.c.source_id.in_(source_ids or ["-"]))
        maps = c.execute(q).all()
        _nm = _names(c)
        e = db.exceptions
        t1 = c.execute(select(func.count()).select_from(e).where(e.c.tier == "T1")).scalar() or 0
        t1_rolled = c.execute(select(func.count()).select_from(db.audit_log).where(db.audit_log.c.action == "exception.rollback")).scalar() or 0
        qa_open = c.execute(select(func.count()).select_from(e).where(e.c.status == "auto_applied", e.c.qa_sample.is_(True))).scalar() or 0
        resolves = c.execute(select(db.audit_log.c.detail).where(db.audit_log.c.action == "exception.resolve")).all()
    out = []
    for m in maps:
        fields = m.fields or []
        n = len(fields) or 1
        st = Counter(f.get("status") for f in fields)
        conf = [f.get("confidence", 0) for f in fields]
        review_min = round((m.approved_at - m.created_at).total_seconds() / 60, 1) if m.approved_at else None
        out.append({"mapping_id": m.mapping_id, "source": _label(_nm, m.source_id), "vendor_id": _nm.get(m.source_id, {}).get("vendor_id"), "version": m.version, "status": m.status, "fields": len(fields),
                    "auto_mapped_pct": (m.stats or {}).get("auto_mapped_pct"), "avg_confidence": round(sum(conf) / n, 3),
                    "accepted_as_suggested": st.get("accepted", 0), "overridden": st.get("overridden", 0), "rejected": st.get("rejected", 0),
                    "override_rate": round((st.get("overridden", 0) + st.get("rejected", 0)) / n * 100, 1),
                    "review_minutes": review_min,
                    "confidence_histogram": [sum(1 for x in conf if lo <= x < hi) for lo, hi in ((0, .5), (.5, .8), (.8, .9), (.9, .95), (.95, 1.01))]})
    accepted_ai = sum(1 for (d,) in resolves if (d or {}).get("accepted_ai"))
    return {"mappings": out, "exception_ai": {
        "t1_auto_applied": t1, "t1_override_rate_pct": round(t1_rolled / t1 * 100, 2) if t1 else 0.0, "qa_samples_pending": qa_open,
        "human_resolutions": len(resolves), "ai_proposal_acceptance_pct": round(accepted_ai / len(resolves) * 100, 1) if resolves else None}}


def executive_summary(source_ids: list[str] | None = None) -> dict:
    sse, e, b = db.sse_loans, db.exceptions, db.batches

    def scoped(q, col):
        return q if source_ids is None else q.where(col.in_(source_ids or ["-"]))

    with db.get_engine().connect() as c:
        boarded = c.execute(scoped(select(func.count()).select_from(sse), sse.c.lbp_source_id)).scalar() or 0
        today = c.execute(scoped(select(func.count()).select_from(sse).where(sse.c.lbp_boarded_at >= db.now() - DAY), sse.c.lbp_source_id)).scalar() or 0
        upb = c.execute(scoped(select(func.sum(sse.c.current_principal_balance)), sse.c.lbp_source_id)).scalar() or 0
        open_blocking = c.execute(scoped(select(func.count()).select_from(e).where(and_(e.c.blocking.is_(True),
                                  e.c.status.in_(("open", "pending_review", "pending_checker", "escalated")))), e.c.source_id)).scalar() or 0
        t5 = c.execute(scoped(select(func.count()).select_from(e).where(e.c.tier == "T5", e.c.status == "escalated"), e.c.source_id)).scalar() or 0
        processed = c.execute(scoped(select(func.sum(b.c.processed)).where(func.coalesce(b.c.load_type, "full") == "full"), b.c.source_id)).scalar() or 0
        peak = c.execute(scoped(select(func.max(b.c.throughput_lps)), b.c.source_id)).scalar() or 0
        daily = c.execute(scoped(select(func.date(sse.c.lbp_boarded_at), func.count()), sse.c.lbp_source_id)
                          .group_by(func.date(sse.c.lbp_boarded_at))).all()
        by_type = dict(c.execute(scoped(select(sse.c.loan_type, func.count()), sse.c.lbp_source_id).group_by(sse.c.loan_type)).all())
        by_inv = dict(c.execute(scoped(select(sse.c.investor_category, func.count()), sse.c.lbp_source_id).group_by(sse.c.investor_category)).all())
    ex = exception_analytics(source_ids=source_ids)
    return {
        "loans_boarded_total": boarded, "loans_boarded_24h": today, "upb_boarded": round(upb, 2), "loans_processed": processed,
        "straight_through_rate": min(100.0, round(boarded / processed * 100, 1)) if processed else None,
        "open_blocking_exceptions": open_blocking, "compliance_blocks": t5, "peak_throughput_lps": peak,
        "projected_capacity_24h": int(peak * 86400), "target_24h": 1_000_000,
        "capacity_vs_target_pct": round(peak * 86400 / 1_000_000 * 100, 1) if peak else 0,
        "boarded_by_day": [{"date": str(d), "count": n} for d, n in daily], "by_loan_type": by_type, "by_investor": by_inv,
        "exception_trend": ex["trend"], "auto_apply_rate": ex["auto_apply_rate"],
    }


# ---------------------------------------------------------------- natural language ask
INTENTS = [
    (r"(how many|count|number of).*(board|loaded)", lambda: ("Loans boarded", executive_summary()["loans_boarded_total"])),
    (r"(straight.?through|stp|pass rate|success rate)", lambda: ("Straight-through rate %", executive_summary()["straight_through_rate"])),
    (r"(top|most common|biggest).*(exception|rule|failure)", lambda: ("Top exception rules", exception_analytics()["by_rule"][:5])),
    (r"(open|pending|backlog).*(exception|queue)", lambda: ("Open exceptions by tier", exception_analytics()["by_tier"])),
    (r"(which|worst|best).*(source|vendor|feed|seller)", lambda: ("Vendor and feed performance", [
        {k: s[k] for k in ("name", "success_rate", "exceptions_per_100")} for s in source_performance()["sources"]])),
    (r"(throughput|capacity|1m|million|per day|24)", lambda: ("Capacity", {k: executive_summary()[k] for k in (
        "peak_throughput_lps", "projected_capacity_24h", "capacity_vs_target_pct")})),
    (r"(quality|dq|complete)", lambda: ("DQ", {k: dq_scorecard()[k] for k in ("overall_score", "required_completeness")})),
    (r"(auto.?appl|t1|ai)", lambda: ("AI exception handling", ai_mapping_insights()["exception_ai"])),
    (r"(compliance|ofac|fraud|blocked|t5)", lambda: ("Compliance blocks", executive_summary()["compliance_blocks"])),
    (r"(upb|balance|volume)", lambda: ("UPB boarded", executive_summary()["upb_boarded"])),
]


def ask(question: str) -> dict:
    q = question.lower()
    for rx, fn in INTENTS:
        if re.search(rx, q):
            title, value = fn()
            return {"question": question, "answer_title": title, "answer": value, "engine": "intent-match (QuickSight Q in AWS)"}
    return {"question": question, "answer_title": None, "answer": None,
            "suggestions": ["How many loans were boarded?", "What are the top exception rules?", "Which source has the worst success rate?",
                            "What is our projected 24h capacity?", "How many open exceptions by tier?"]}


# ---------------------------------------------------------------- systemic issues (root cause)
def systemic_issues(min_count: int = 8, min_share_pct: float = 1.0, source_ids: list[str] | None = None) -> dict:
    """Group open exceptions into likely root causes.

    Many exceptions on the same source + rule + field are usually one mapping or source defect,
    not many loan defects. Each issue carries a recommended fix and a deep link into the Mapping UI.
    """
    e = db.exceptions
    open_states = ("open", "pending_review", "pending_checker", "escalated")
    with db.get_engine().connect() as c:
        q = select(e.c.source_id, e.c.rule_id, e.c.rule_name, e.c.field, e.c.category, e.c.original_value, e.c.batch_id, e.c.tier) \
            .where(e.c.status.in_(open_states))
        if source_ids is not None:
            q = q.where(e.c.source_id.in_(source_ids or ["-"]))
        rows = c.execute(q).all()
        _nm = _names(c)
        processed = dict(c.execute(select(db.batches.c.source_id, func.sum(db.batches.c.processed)).group_by(db.batches.c.source_id)).all())
        srcs = {r.source_id: r for r in c.execute(select(db.sources.c.source_id, db.sources.c.name, db.sources.c.active_mapping_id))}
        maps = {r.mapping_id: r for r in c.execute(select(db.mappings.c.mapping_id, db.mappings.c.fields))}
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        groups[(r.source_id, r.rule_id, r.field)].append(r)
    issues = []
    for (sid, rule_id, field), items in groups.items():
        n = len(items)
        share = n / max(processed.get(sid) or 1, 1) * 100
        if n < min_count or share < min_share_pct:
            continue
        vals = Counter(i.original_value for i in items)
        top_val, top_n = vals.most_common(1)[0]
        s = srcs.get(sid)
        mp = maps.get(s.active_mapping_id) if s else None
        spec = next((f for f in (mp.fields if mp else []) if f["target"] == field), None)
        attr = BY_NAME.get(field)
        if items[0].category == "transform":
            cause, action = f"Transformation for {field} fails on {n} loans", "fix_transform"
            detail = f"Most common error: {top_val}"
        elif items[0].category == "duplicate":
            cause, action = f"{n} loans already boarded or repeated in the file", "review_duplicates"
            detail = "Likely a re-sent tape. Confirm with the seller before approving updates."
        elif top_n / n >= 0.5 and attr and attr.codes:
            cause, action = f"Untranslated value '{top_val}' in {field} on {top_n} loans", "value_map"
            detail = "Add a value translation in the mapping, then replay the batch."
        elif top_n / n >= 0.5:
            cause, action = f"Same value '{top_val}' fails {rule_id} on {top_n} loans", "bulk_fix"
            detail = "Check the source column and transformation; bulk-resolve if the value is right."
        else:
            cause, action = f"{rule_id} fails on {n} loans ({round(share, 1)}% of the source)", "source_quality"
            detail = "Values vary: likely a data-quality problem at the source. Raise with the seller."
        issues.append({
            "source_id": sid, "source_name": _label(_nm, sid) if s else sid, "vendor_id": _nm.get(sid, {}).get("vendor_id"), "mapping_id": s.active_mapping_id if s else None,
            "rule_id": rule_id, "rule_name": items[0].rule_name, "field": field, "category": items[0].category,
            "exceptions": n, "share_pct": round(share, 2), "batches": sorted({i.batch_id for i in items}),
            "distinct_values": len(vals), "top_value": top_val, "top_value_count": top_n, "tiers": dict(Counter(i.tier for i in items)),
            "cause": cause, "detail": detail, "action": action,
            "mapped_from": (spec.get("sources") or [spec.get("source")]) if spec else None,
        })
    issues.sort(key=lambda x: -x["exceptions"])
    return {"issues": issues, "open_exceptions": len(rows),
            "explained_pct": round(sum(i["exceptions"] for i in issues) / max(len(rows), 1) * 100, 1)}
