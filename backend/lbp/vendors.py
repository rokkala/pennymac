"""Vendors: the counterparty that owns one or more feeds.

    Vendor (Cornerstone Servicing, sub-servicer)
      ├── Feed "Boarding tapes"        full tapes      mapping v1, v2 …   schedule: on demand
      └── Feed "Intraday change files" incremental     mapping v1         schedule: every 4 h, pushed to S3

Every operational view (files, deliveries, exceptions, analytics) can be scoped to one vendor, and
data integrity is enforced at vendor level:

  * a change file may only change loans that belong to the same vendor (CHG06 otherwise),
  * a snapshot is compared with the vendor's whole portfolio, across all its feeds,
  * a suspended vendor's files are recorded but not processed.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from .store import db

VENDOR_TYPES = ("correspondent", "bulk_seller", "sub_servicer", "retail", "other")
STATUSES = ("onboarding", "active", "suspended", "offboarded")


class VendorError(ValueError):
    pass


def _role(roles, *need):
    if not set(roles) & set(need + ("admin",)):
        raise VendorError(f"requires one of: {', '.join(need)}")


def _clean(fields: dict) -> dict:
    out = {}
    for k in ("name", "vendor_type", "legal_name", "external_ref", "contact", "notes"):
        if k in fields and fields[k] is not None:
            out[k] = fields[k].strip() if isinstance(fields[k], str) else fields[k]
    if "name" in out and not out["name"]:
        raise VendorError("vendor name is required")
    if out.get("vendor_type") and out["vendor_type"] not in VENDOR_TYPES:
        raise VendorError(f"vendor_type must be one of {', '.join(VENDOR_TYPES)}")
    if out.get("contact") is not None and not isinstance(out["contact"], dict):
        raise VendorError("contact must be an object {name, email, phone}")
    return out


def create_vendor(fields: dict, actor: str, roles: list[str]) -> dict:
    _role(roles, "analyst", "sme")
    vals = _clean(fields)
    if not vals.get("name"):
        raise VendorError("vendor name is required")
    with db.get_engine().begin() as c:
        if c.execute(select(db.vendors.c.vendor_id).where(func.lower(db.vendors.c.name) == vals["name"].lower())).first():
            raise VendorError(f"a vendor named '{vals['name']}' already exists")
        vid = db.new_id("ven")
        c.execute(db.vendors.insert().values(vendor_id=vid, status="onboarding", created_by=actor, **{"vendor_type": "other", **vals}))
        db.audit(c, actor, "vendor.create", "vendor", vid, vals)
    return get_vendor(vid)


def ensure_vendor(name: str, actor: str, vendor_type: str = "other") -> str:
    """Vendor id for a name, creating it if needed (back-compat for callers that register a feed by name)."""
    with db.get_engine().begin() as c:
        row = c.execute(select(db.vendors.c.vendor_id).where(func.lower(db.vendors.c.name) == name.strip().lower())).first()
        if row:
            return row[0]
        vid = db.new_id("ven")
        c.execute(db.vendors.insert().values(vendor_id=vid, name=name.strip(), vendor_type=vendor_type, status="onboarding", created_by=actor))
        db.audit(c, actor, "vendor.create", "vendor", vid, {"name": name, "implicit": True})
        return vid


def update_vendor(vendor_id: str, fields: dict, actor: str, roles: list[str]) -> dict:
    _role(roles, "analyst", "sme")
    vals = _clean(fields)
    status = fields.get("status")
    if status is not None:
        if status not in STATUSES:
            raise VendorError(f"status must be one of {', '.join(STATUSES)}")
        if status in ("suspended", "offboarded"):
            _role(roles, "sme", "compliance")
        vals["status"] = status
    if status in ("suspended", "offboarded") and not fields.get("reason"):
        raise VendorError("a reason is required to suspend or offboard a vendor")
    with db.get_engine().begin() as c:
        cur = c.execute(select(db.vendors).where(db.vendors.c.vendor_id == vendor_id).with_for_update()).first()
        if not cur:
            raise VendorError("vendor not found")
        if vals.get("name") and c.execute(select(db.vendors.c.vendor_id).where(
                func.lower(db.vendors.c.name) == vals["name"].lower(), db.vendors.c.vendor_id != vendor_id)).first():
            raise VendorError(f"a vendor named '{vals['name']}' already exists")
        c.execute(db.vendors.update().where(db.vendors.c.vendor_id == vendor_id).values(updated_at=db.now(), **vals))
        db.audit(c, actor, "vendor.update" if "status" not in vals else f"vendor.{vals['status']}", "vendor", vendor_id,
                 {**vals, **({"reason": fields["reason"]} if fields.get("reason") else {})})
    return get_vendor(vendor_id)


def move_feed(source_id: str, vendor_id: str, actor: str, roles: list[str], reason: str) -> dict:
    """Re-home a feed under another vendor (e.g. grouping backfilled feeds, or an acquisition)."""
    _role(roles, "sme")
    if not reason:
        raise VendorError("a reason is required")
    with db.get_engine().begin() as c:
        src = c.execute(select(db.sources.c.source_id, db.sources.c.vendor_id).where(db.sources.c.source_id == source_id)).first()
        if not src:
            raise VendorError("feed not found")
        if not c.execute(select(db.vendors.c.vendor_id).where(db.vendors.c.vendor_id == vendor_id)).first():
            raise VendorError("vendor not found")
        busy = c.execute(select(func.count()).select_from(db.batches).where(
            db.batches.c.source_id == source_id, db.batches.c.status.in_(("running", "claimed", "pausing", "waiting")))).scalar()
        if busy:
            raise VendorError("this feed has files in progress; move it when they have finished")
        c.execute(db.sources.update().where(db.sources.c.source_id == source_id).values(vendor_id=vendor_id))
        db.audit(c, actor, "source.move_vendor", "source", source_id, {"from": src.vendor_id, "to": vendor_id, "reason": reason})
    from .config_store import publish_all

    publish_all(actor, f"feed {source_id} moved to vendor {vendor_id}")  # vendor portfolios (vendor_feeds) changed
    return {"source_id": source_id, "vendor_id": vendor_id}


# ------------------------------------------------------------------ lookups
def source_ids(vendor_id: str | None) -> list[str] | None:
    """Feed ids of a vendor (None = no vendor filter)."""
    if not vendor_id:
        return None
    with db.get_engine().connect() as c:
        if not c.execute(select(db.vendors.c.vendor_id).where(db.vendors.c.vendor_id == vendor_id)).first():
            raise VendorError("vendor not found")
        return [r[0] for r in c.execute(select(db.sources.c.source_id).where(db.sources.c.vendor_id == vendor_id))]


def siblings(conn, source_id: str) -> list[str]:
    """All feeds of the vendor that owns this feed (the feed itself if it has no vendor)."""
    vid = conn.execute(select(db.sources.c.vendor_id).where(db.sources.c.source_id == source_id)).scalar()
    if not vid:
        return [source_id]
    return [r[0] for r in conn.execute(select(db.sources.c.source_id).where(db.sources.c.vendor_id == vid))]


def names_by_source(conn) -> dict[str, dict]:
    """source_id -> {vendor_id, vendor_name, feed_name} for labelling rows."""
    rows = conn.execute(select(db.sources.c.source_id, db.sources.c.name, db.sources.c.vendor_id, db.vendors.c.name.label("vname"))
                        .select_from(db.sources.outerjoin(db.vendors, db.vendors.c.vendor_id == db.sources.c.vendor_id))).all()
    return {r.source_id: {"vendor_id": r.vendor_id, "vendor_name": r.vname or r.name, "feed_name": r.name} for r in rows}


# ------------------------------------------------------------------ reads
def _rollups(c, vendor_ids: list[str] | None = None) -> dict[str, dict]:
    from .pipeline.delivery import profile_of

    now = db.now()
    feeds = c.execute(select(db.sources)).all()
    by_v: dict[str, list] = {}
    for f in feeds:
        by_v.setdefault(f.vendor_id, []).append(f)
    loans = dict(c.execute(select(db.sse_loans.c.lbp_source_id, func.count()).where(db.sse_loans.c.lbp_status == "active")
                           .group_by(db.sse_loans.c.lbp_source_id)).all())
    ex = db.exceptions
    open_ex = dict(c.execute(select(ex.c.source_id, func.count()).where(ex.c.status.in_(("open", "pending_review", "pending_checker", "escalated")))
                             .group_by(ex.c.source_id)).all())
    b = db.batches
    last = dict(c.execute(select(b.c.source_id, func.max(b.c.created_at)).group_by(b.c.source_id)).all())
    waiting = dict(c.execute(select(b.c.source_id, func.count()).where(b.c.status.in_(("waiting", "out_of_order", "blocked")))
                             .group_by(b.c.source_id)).all())
    d = db.deliveries
    dstats: dict[str, dict] = {}
    for sid, st, n in c.execute(select(d.c.source_id, d.c.status, func.count()).where(d.c.due_at > now - timedelta(days=30), d.c.due_at <= now)
                                .group_by(d.c.source_id, d.c.status)):
        dstats.setdefault(sid, {})[st] = n
    recent_bad = dict(c.execute(select(d.c.source_id, func.count()).where(d.c.due_at > now - timedelta(days=2), d.c.due_at <= now,
                                                                         d.c.status.in_(("late", "missed"))).group_by(d.c.source_id)).all())
    sched = dict(c.execute(select(db.delivery_schedules.c.source_id, func.count()).where(
        db.delivery_schedules.c.status.in_(("active", "paused", "pending_approval"))).group_by(db.delivery_schedules.c.source_id)).all())
    out = {}
    for vid, fs in by_v.items():
        if vendor_ids is not None and vid not in vendor_ids:
            continue
        ids = [f.source_id for f in fs]
        agg: dict[str, int] = {}
        for sid in ids:
            for k, n in dstats.get(sid, {}).items():
                agg[k] = agg.get(k, 0) + n
        due = sum(n for k, n in agg.items() if k != "waived")
        lasts = [last[s] for s in ids if last.get(s)]
        out[vid] = {
            "feeds": len(fs), "live_feeds": sum(1 for f in fs if f.active_mapping_id),
            "load_types": sorted({profile_of(f.delivery)["load_type"] for f in fs}),
            "active_loans": sum(loans.get(s, 0) for s in ids), "open_exceptions": sum(open_ex.get(s, 0) for s in ids),
            "last_file": max(lasts).isoformat() + "Z" if lasts else None,
            "attention_files": sum(waiting.get(s, 0) for s in ids),
            "late_or_missed": sum(recent_bad.get(sid, 0) for sid in ids),  # last 48 h, still not received
            "missed_30d": agg.get("missed", 0),
            "on_time_pct": round(100 * agg.get("received", 0) / due, 1) if due else None,
            "schedules": sum(sched.get(s, 0) for s in ids),
            "pending_mapping_review": sum(1 for f in fs if f.status in ("draft", "mapping")),
        }
    return out


def list_vendors() -> list[dict]:
    with db.get_engine().connect() as c:
        rows = c.execute(select(db.vendors).order_by(db.vendors.c.name)).all()
        roll = _rollups(c)
    return [{**db.row_to_dict(r), **roll.get(r.vendor_id, {"feeds": 0, "live_feeds": 0, "load_types": [], "active_loans": 0,
                                                           "open_exceptions": 0, "last_file": None, "attention_files": 0,
                                                           "late_or_missed": 0, "on_time_pct": None, "schedules": 0,
                                                           "pending_mapping_review": 0})} for r in rows]


def get_vendor(vendor_id: str) -> dict:
    from .pipeline.delivery import display_sequence, profile_of

    with db.get_engine().connect() as c:
        v = c.execute(select(db.vendors).where(db.vendors.c.vendor_id == vendor_id)).first()
        if not v:
            raise VendorError("vendor not found")
        feeds = c.execute(select(db.sources).where(db.sources.c.vendor_id == vendor_id).order_by(db.sources.c.created_at)).all()
        ids = [f.source_id for f in feeds] or ["-"]
        maps = c.execute(select(db.mappings.c.mapping_id, db.mappings.c.source_id, db.mappings.c.version, db.mappings.c.status,
                                db.mappings.c.stats, db.mappings.c.approved_by, db.mappings.c.approved_at)
                         .where(db.mappings.c.source_id.in_(ids)).order_by(db.mappings.c.version)).all()
        sch = c.execute(select(db.delivery_schedules.c.schedule_id, db.delivery_schedules.c.source_id, db.delivery_schedules.c.name,
                               db.delivery_schedules.c.status).where(db.delivery_schedules.c.source_id.in_(ids))).all()
        loans = dict(c.execute(select(db.sse_loans.c.lbp_source_id, func.count()).where(db.sse_loans.c.lbp_status == "active",
                                                                                       db.sse_loans.c.lbp_source_id.in_(ids))
                               .group_by(db.sse_loans.c.lbp_source_id)).all())
        last = dict(c.execute(select(db.batches.c.source_id, func.max(db.batches.c.created_at)).where(db.batches.c.source_id.in_(ids))
                              .group_by(db.batches.c.source_id)).all())
        roll = _rollups(c, [vendor_id]).get(vendor_id, {})
    out = {**db.row_to_dict(v), **roll, "feeds": []}
    for f in feeds:
        prof = profile_of(f.delivery)
        out["feeds"].append({
            "source_id": f.source_id, "name": f.name, "description": f.description, "format": f.format, "status": f.status,
            "active_mapping_id": f.active_mapping_id, "load_type": prof["load_type"], "delivery_pending": bool(f.delivery_draft),
            "last_sequence": display_sequence(f.last_sequence), "active_loans": loans.get(f.source_id, 0),
            "last_file": last[f.source_id].isoformat() + "Z" if last.get(f.source_id) else None,
            "columns": len((f.profile or {}).get("columns", [])), "created_by": f.created_by,
            "mappings": [{"mapping_id": m.mapping_id, "version": m.version, "status": m.status,
                          "auto_mapped_pct": (m.stats or {}).get("auto_mapped_pct"), "approved_by": m.approved_by}
                         for m in maps if m.source_id == f.source_id],
            "schedules": [{"schedule_id": s.schedule_id, "name": s.name, "status": s.status} for s in sch if s.source_id == f.source_id],
        })
    return out
