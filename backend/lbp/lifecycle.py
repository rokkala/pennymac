"""Feed lifecycle: archive / restore a feed, discard a draft mapping version, delete a never-used feed.

Archiving is the normal way to retire a feed: its history, mappings and audit trail stay, it leaves the
working lists, its schedules pause, and every intake path (upload, file set upload, scheduled pull, S3
arrival) refuses its files. Restoring undoes it. Permanent deletion exists only for a feed that has never
been used (no batches, file sets, exceptions or loans) and only for admins.
"""
from __future__ import annotations

from sqlalchemy import func, select

from .store import db

MIN_REASON = 5
# blocked / out_of_order still resume and load data (drift override, apply-out-of-order); failed and completed do not
BUSY_BATCH_STATUSES = ("running", "claimed", "pausing", "waiting", "queued", "staged", "paused", "blocked", "out_of_order")
BUSY_SET_STATUSES = ("waiting", "ready")
MEMBER_ROLES = ("onboarding", "onboarding_reviewer")


class LifecycleError(ValueError):
    pass


class FeedArchivedError(LifecycleError):
    """A file was sent to an archived feed (HTTP 409)."""


def _roles(roles) -> set[str]:
    from .security import expand_roles

    return set(expand_roles(roles or []))


def _need(roles, *need: str) -> set[str]:
    have = _roles(roles)
    if not have & (set(need) | {"admin"}):
        raise LifecycleError(f"requires one of: {', '.join(need)}")
    return have


def _reason(reason: str | None) -> str:
    text = (reason or "").strip()
    if len(text) < MIN_REASON:
        raise LifecycleError(f"a reason of at least {MIN_REASON} characters is required")
    return text


def assert_not_archived(source_id: str) -> None:
    """Raise FeedArchivedError when the feed is archived. Call at every point where a file enters a feed."""
    with db.get_engine().connect() as c:
        row = c.execute(select(db.sources.c.name, db.sources.c.status).where(db.sources.c.source_id == source_id)).first()
    if row is not None and row.status == "retired":
        raise FeedArchivedError(f"feed '{row.name}' is archived; restore it before sending it files")


def _lock_feed(c, source_id: str):
    """Write-first lock on the feed row (see multifile.fileset._lock_source), then read it."""
    s = db.sources
    if c.execute(s.update().where(s.c.source_id == source_id).values(source_id=s.c.source_id)).rowcount == 0:
        raise LifecycleError("feed not found")
    return c.execute(select(s).where(s.c.source_id == source_id)).first()


def _public(src) -> dict:
    return {"source_id": src.source_id, "name": src.name, "status": src.status, "retired_at": src.retired_at,
            "retired_by": src.retired_by, "retired_reason": src.retired_reason}


def _republish(actor: str, reason: str) -> None:
    from .config_store import publish_all

    publish_all(actor, reason)  # vendor portfolios (vendor_feeds) changed, as for a feed move


def archive_feed(source_id: str, actor: str, roles: list[str], reason: str) -> dict:
    have = _need(roles, *MEMBER_ROLES)
    reason = _reason(reason)
    with db.get_engine().begin() as c:
        src = _lock_feed(c, source_id)
        if src.status == "retired":
            raise LifecycleError("this feed is already archived")
        if src.status == "live" and not have & {"onboarding_reviewer", "admin"}:
            raise LifecycleError("archiving a live feed requires the onboarding_reviewer role")
        busy = c.execute(select(func.count()).select_from(db.batches).where(
            db.batches.c.source_id == source_id, db.batches.c.status.in_(BUSY_BATCH_STATUSES))).scalar()
        if busy:
            raise LifecycleError(f"this feed has {busy} file(s) in progress; archive it when they have finished")
        waiting = c.execute(select(func.count()).select_from(db.file_sets).where(
            db.file_sets.c.source_id == source_id, db.file_sets.c.status.in_(BUSY_SET_STATUSES))).scalar()
        if waiting:
            raise LifecycleError(f"this feed has {waiting} multi-file delivery(ies) still waiting for files; "
                                 "resolve or discard them before archiving")
        reviewing = c.execute(select(func.count()).select_from(db.mappings).where(
            db.mappings.c.source_id == source_id, db.mappings.c.status == "in_review")).scalar()
        if reviewing:
            raise LifecycleError("a mapping for this feed is awaiting review; the reviewer must approve or send it back "
                                 "(or it must be withdrawn) before the feed can be archived")
        sched = db.delivery_schedules
        paused = [r[0] for r in c.execute(select(sched.c.schedule_id).where(sched.c.source_id == source_id, sched.c.status == "active"))]
        if paused:
            c.execute(sched.update().where(sched.c.schedule_id.in_(paused)).values(status="paused"))
            # a paused schedule expects nothing: open future windows are waived, as for set_status("paused")
            c.execute(db.deliveries.update().where(db.deliveries.c.schedule_id.in_(paused), db.deliveries.c.status == "expected",
                                                   db.deliveries.c.due_at > db.now()).values(
                status="waived", waived_by=actor, waive_reason="feed archived"))
        c.execute(db.sources.update().where(db.sources.c.source_id == source_id).values(
            status="retired", retired_from_status=src.status, retired_at=db.now(), retired_by=actor, retired_reason=reason))
        db.audit(c, actor, "source.archive", "source", source_id,
                 {"reason": reason, "from_status": src.status, "paused_schedules": paused})
        out = _public(c.execute(select(db.sources).where(db.sources.c.source_id == source_id)).first())
    _republish(actor, f"feed {source_id} archived")
    return out


def restore_feed(source_id: str, actor: str, roles: list[str], reason: str) -> dict:
    have = _need(roles, *MEMBER_ROLES)
    reason = _reason(reason)
    with db.get_engine().begin() as c:
        src = _lock_feed(c, source_id)
        if src.status != "retired":
            raise LifecycleError("this feed is not archived")
        back = src.retired_from_status or ("live" if src.active_mapping_id else "mapping")
        if back == "live" and not have & {"onboarding_reviewer", "admin"}:
            raise LifecycleError("restoring a live feed requires the onboarding_reviewer role")
        clash = c.execute(select(db.sources.c.source_id).where(
            db.sources.c.vendor_id == src.vendor_id, db.sources.c.name == src.name, db.sources.c.source_id != source_id,
            db.sources.c.status != "retired")).first()
        if clash:
            raise LifecycleError(f"this vendor now has another feed named '{src.name}'; rename or archive that one before restoring this feed")
        c.execute(db.sources.update().where(db.sources.c.source_id == source_id).values(
            status=back, retired_from_status=None, retired_at=None, retired_by=None, retired_reason=None))
        # schedules stay paused: a person re-activates them (and their next windows) deliberately
        db.audit(c, actor, "source.restore", "source", source_id,
                 {"reason": reason, "status": back, "was_archived_by": src.retired_by, "was_archived_for": src.retired_reason})
        out = _public(c.execute(select(db.sources).where(db.sources.c.source_id == source_id)).first())
    _republish(actor, f"feed {source_id} restored")
    return out


def discard_mapping(mapping_id: str, actor: str, roles: list[str], reason: str) -> dict:
    """Drop a draft mapping version nobody will approve. Only a `draft` can be discarded (an approved version is
    history, one in review must be sent back first); the row stays, marked `discarded`."""
    _need(roles, *MEMBER_ROLES)
    reason = _reason(reason)
    with db.get_engine().begin() as c:
        m = c.execute(select(db.mappings).where(db.mappings.c.mapping_id == mapping_id).with_for_update()).first()
        if not m:
            raise LifecycleError("mapping not found")
        if m.status == "in_review":
            raise LifecycleError("this mapping is awaiting review; the reviewer must send it back before it can be discarded")
        if m.status != "draft":
            raise LifecycleError(f"only a draft mapping can be discarded; this one is {m.status}")
        c.execute(db.mappings.update().where(db.mappings.c.mapping_id == mapping_id).values(status="discarded"))
        db.audit(c, actor, "mapping.discard", "mapping", mapping_id,
                 {"source_id": m.source_id, "version": m.version, "reason": reason})
    return {"mapping_id": mapping_id, "source_id": m.source_id, "version": m.version, "status": "discarded"}


def delete_feed(source_id: str, actor: str, roles: list[str], reason: str) -> dict:
    """Permanently remove a feed that has never been used. Refused when it has any batches, file sets,
    exceptions or loans (archive it instead). The audit trail is append-only and is kept."""
    if "admin" not in _roles(roles):
        raise LifecycleError("only an administrator can permanently delete a feed")
    reason = _reason(reason)
    with db.get_engine().begin() as c:
        src = _lock_feed(c, source_id)
        used = {"batches": db.batches.c.source_id, "file sets": db.file_sets.c.source_id,
                "exceptions": db.exceptions.c.source_id, "loans": db.sse_loans.c.lbp_source_id}
        for label, col in used.items():
            if c.execute(select(func.count()).select_from(col.table).where(col == source_id)).scalar():
                raise LifecycleError(f"this feed has {label} on record, so it cannot be deleted; archive it instead")
        sched_ids = [r[0] for r in c.execute(select(db.delivery_schedules.c.schedule_id).where(db.delivery_schedules.c.source_id == source_id))]
        n_map = c.execute(db.mappings.delete().where(db.mappings.c.source_id == source_id)).rowcount
        if sched_ids:
            c.execute(db.deliveries.delete().where(db.deliveries.c.source_id == source_id))
            c.execute(db.pulled_files.delete().where(db.pulled_files.c.schedule_id.in_(sched_ids)))
            c.execute(db.delivery_schedules.delete().where(db.delivery_schedules.c.schedule_id.in_(sched_ids)))
        c.execute(db.sources.delete().where(db.sources.c.source_id == source_id))
        db.audit(c, actor, "source.delete", "source", source_id,
                 {"reason": reason, "name": src.name, "vendor_id": src.vendor_id, "status": src.status,
                  "mappings_removed": n_map, "schedules_removed": len(sched_ids)})
    _republish(actor, f"feed {source_id} deleted")
    return {"source_id": source_id, "deleted": True}
