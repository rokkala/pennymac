"""Vendor delivery schedules and the scheduler tick.

A schedule says when a vendor's file is *due* (cron in the vendor's timezone + business calendar)
and, optionally, where to pull it from. Each due time becomes a `deliveries` row:

    expected  ->  received        (arrived by due + grace)
              ->  late            (past due + grace; alert once)  -> received_late
              ->  missed          (past due + miss_after; alert)  -> received_late
              ->  waived          (Ops: "no file today", with a reason)

Arrivals from any channel (UI upload, S3 push, SFTP/S3 pull) are matched to the oldest still-live
delivery of that vendor whose window has opened; if none is live, to the window that just passed when it
was missed. Otherwise the file is processed as an unscheduled arrival. File arrival stays event-driven: the scheduler watches
deadlines and pulls for vendors that don't push; it never delays processing of a file that has landed.

Schedules are configuration with consequences (alerts, sequencing gaps, outbound connections), so
create/change follows maker-checker: a proposal takes effect only when a different SME approves it.

The tick is idempotent and safe to run from several workers: a leader lease admits one at a time,
deliveries are unique per (schedule, due_at), alerts are stamped once, pulled files are unique.
"""
from __future__ import annotations

import fnmatch
import logging
import os
import socket
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..config import get_settings
from ..store import db
from . import cron
from .alerts import notify
from .pullers import fetch_new, validate_pull

log = logging.getLogger("lbp.scheduler")

OPEN = ("expected", "late", "missed")
DEFAULTS = {"timezone": "America/New_York", "calendar": "us_federal", "holiday_rule": "skip", "window_before_minutes": 720,
            "grace_minutes": 30, "miss_after_minutes": 240, "expected_files": 1, "load_type": None, "filename_glob": None,
            "pull": None}
LOOKBACK_DAYS = 31
HORIZON_HOURS = 36
LEASE_SECONDS = 300


class ScheduleError(ValueError):
    pass


def _now():
    """Single clock for the scheduler (tests substitute it)."""
    return db.now()


def effective(cfg: dict | None) -> dict:
    return {**DEFAULTS, **(cfg or {})}


def validate_config(cfg: dict) -> list[str]:
    c = effective(cfg)
    errs = []
    try:
        cron.parse(c.get("cron") or "")
    except cron.CronError as e:
        errs.append(f"cron: {e}")
    try:
        cron.tz_of(c["timezone"])
    except cron.CronError as e:
        errs.append(str(e))
    if c["calendar"] not in cron.CALENDARS:
        errs.append(f"calendar must be one of {cron.CALENDARS}")
    if c["holiday_rule"] not in ("skip", "next_business_day"):
        errs.append("holiday_rule must be skip or next_business_day")
    for k in ("window_before_minutes", "grace_minutes", "miss_after_minutes", "expected_files"):
        if not isinstance(c[k], int) or c[k] < (1 if k == "expected_files" else 0):
            errs.append(f"{k} must be a whole number{' >= 1' if k == 'expected_files' else ' >= 0'}")
    if not errs and c["miss_after_minutes"] < c["grace_minutes"]:
        errs.append("miss_after_minutes must be at least grace_minutes")
    if c["load_type"] not in (None, "full", "incremental", "snapshot"):
        errs.append("load_type must be full, incremental or snapshot")
    if c["pull"]:
        errs += validate_pull(c["pull"])
        pm = c["pull"].get("poll_minutes", 15)
        if not isinstance(pm, int) or pm < 5:
            errs.append("pull.poll_minutes must be at least 5")
    return errs


def _role(roles, *need):
    if not set(roles) & set(need + ("admin",)):
        raise ScheduleError(f"requires one of: {', '.join(need)}")


# ------------------------------------------------------------------ maker-checker
def create_schedule(source_id: str, name: str, cfg: dict, actor: str, roles: list[str]) -> dict:
    _role(roles, "ops", "sme")
    errs = validate_config(cfg)
    if errs:
        raise ScheduleError("; ".join(errs))
    with db.get_engine().begin() as c:
        if not c.execute(select(db.sources.c.source_id).where(db.sources.c.source_id == source_id)).first():
            raise ScheduleError("unknown source")
        sid = db.new_id("sch")
        c.execute(db.delivery_schedules.insert().values(schedule_id=sid, source_id=source_id, name=name or "Delivery", config=None,
                                                        proposed=effective(cfg), status="pending_approval", version=0, proposed_by=actor,
                                                        created_by=actor))
        db.audit(c, actor, "schedule.propose", "schedule", sid, {"source_id": source_id, "config": _safe(cfg)})
    return get_schedule(sid)


def propose_change(schedule_id: str, cfg: dict, actor: str, roles: list[str], name: str | None = None) -> dict:
    _role(roles, "ops", "sme")
    errs = validate_config(cfg)
    if errs:
        raise ScheduleError("; ".join(errs))
    with db.get_engine().begin() as c:
        s = _load(c, schedule_id)
        if s.status == "retired":
            raise ScheduleError("schedule is retired")
        c.execute(db.delivery_schedules.update().where(db.delivery_schedules.c.schedule_id == schedule_id).values(
            proposed={**effective(cfg), **({"name": name} if name else {})}, proposed_by=actor))
        db.audit(c, actor, "schedule.propose_change", "schedule", schedule_id, {"config": _safe(cfg)})
    return get_schedule(schedule_id)


def decide(schedule_id: str, actor: str, roles: list[str], approve: bool, comment: str | None = None) -> dict:
    _role(roles, "sme", "compliance")
    with db.get_engine().begin() as c:
        s = _load(c, schedule_id)
        if not s.proposed:
            raise ScheduleError("nothing is awaiting approval")
        if actor == s.proposed_by:
            raise ScheduleError("maker-checker: the approver must be a different user from the proposer")
        t = db.delivery_schedules
        if not approve:
            c.execute(t.update().where(t.c.schedule_id == schedule_id).values(
                proposed=None, status="rejected" if s.status == "pending_approval" else s.status))
            db.audit(c, actor, "schedule.reject", "schedule", schedule_id, {"comment": comment})
        else:
            errs = validate_config(s.proposed)  # allowed hosts may have changed since the proposal
            if errs:
                raise ScheduleError("; ".join(errs))
            prop = dict(s.proposed)
            new_name = prop.pop("name", None)
            c.execute(t.update().where(t.c.schedule_id == schedule_id).values(
                config=prop, proposed=None, version=(s.version or 0) + 1, approved_by=actor, approved_at=_now(),
                status="active" if s.status in ("pending_approval",) else s.status, **({"name": new_name} if new_name else {})))
            if s.config and (s.config.get("cron"), s.config.get("timezone"), s.config.get("calendar"), s.config.get("holiday_rule")) != (
                    prop.get("cron"), prop.get("timezone"), prop.get("calendar"), prop.get("holiday_rule")):
                # timing changed: drop future windows built from the old timing (past ones are history)
                c.execute(db.deliveries.delete().where(db.deliveries.c.schedule_id == schedule_id, db.deliveries.c.status == "expected",
                                                       db.deliveries.c.due_at > _now()))
            db.audit(c, actor, "schedule.approve", "schedule", schedule_id, {"version": (s.version or 0) + 1, "comment": comment})
    return get_schedule(schedule_id)


def set_status(schedule_id: str, actor: str, roles: list[str], status: str, reason: str | None = None) -> dict:
    _role(roles, "ops", "sme")
    if status not in ("active", "paused", "retired"):
        raise ScheduleError("status must be active, paused or retired")
    with db.get_engine().begin() as c:
        s = _load(c, schedule_id)
        if s.config is None:
            raise ScheduleError("schedule has never been approved")
        if s.status == "retired":
            raise ScheduleError("schedule is retired")
        c.execute(db.delivery_schedules.update().where(db.delivery_schedules.c.schedule_id == schedule_id).values(status=status))
        if status in ("paused", "retired"):
            c.execute(db.deliveries.update().where(db.deliveries.c.schedule_id == schedule_id, db.deliveries.c.status == "expected",
                                                   db.deliveries.c.due_at > _now()).values(status="waived", waived_by=actor,
                                                                                            waive_reason=f"schedule {status}"))
        db.audit(c, actor, f"schedule.{status}", "schedule", schedule_id, {"reason": reason})
    return get_schedule(schedule_id)


def waive(delivery_id: str, actor: str, roles: list[str], reason: str) -> dict:
    """No file is coming for this window (vendor holiday, agreed skip): stops late/missed alerts for it."""
    _role(roles, "ops", "sme")
    if not reason:
        raise ScheduleError("a reason is required")
    with db.get_engine().begin() as c:
        d = c.execute(select(db.deliveries).where(db.deliveries.c.delivery_id == delivery_id).with_for_update()).first()
        if not d:
            raise ScheduleError("delivery not found")
        if d.status not in OPEN:
            raise ScheduleError(f"cannot waive a delivery that is {d.status}")
        c.execute(db.deliveries.update().where(db.deliveries.c.delivery_id == delivery_id).values(
            status="waived", waived_by=actor, waive_reason=reason))
        db.audit(c, actor, "delivery.waive", "delivery", delivery_id, {"reason": reason, "was": d.status})
    return {"delivery_id": delivery_id, "status": "waived"}


def _load(c, schedule_id):
    s = c.execute(select(db.delivery_schedules).where(db.delivery_schedules.c.schedule_id == schedule_id).with_for_update()).first()
    if not s:
        raise ScheduleError("schedule not found")
    return s


def _safe(cfg: dict) -> dict:
    """Config for the audit log (no secrets ever live in it, but keep the shape explicit)."""
    out = dict(cfg or {})
    if out.get("pull"):
        out["pull"] = {k: v for k, v in out["pull"].items() if k != "password"}
    return out


# ------------------------------------------------------------------ deliveries
def _materialize(c, s, now) -> int:
    """Create delivery windows for due times between the last one recorded and now + horizon."""
    cfg = effective(s.config)
    t = db.deliveries
    last = c.execute(select(func.max(t.c.due_at)).where(t.c.schedule_id == s.schedule_id)).scalar()
    start = max(x for x in (s.approved_at, now - timedelta(days=LOOKBACK_DAYS), last) if x is not None)
    dues = cron.occurrences(cfg["cron"], cfg["timezone"], start, now + timedelta(hours=HORIZON_HOURS), cfg["calendar"], cfg["holiday_rule"])
    n = 0
    for due in dues:
        try:
            with c.begin_nested():
                c.execute(t.insert().values(delivery_id=db.new_id("dlv"), schedule_id=s.schedule_id, source_id=s.source_id, due_at=due,
                                            window_start=due - timedelta(minutes=cfg["window_before_minutes"]),
                                            local_label=cron.local_label(due, cfg["timezone"]), status="expected", batch_ids=[]))
            n += 1
        except IntegrityError:
            continue  # another tick created it
    return n


def match_arrival(c, source_id: str, batch_id: str, filename: str) -> str | None:
    """Attach a newly registered batch to the delivery it satisfies (inside create_batch's transaction)."""
    sch = c.execute(select(db.delivery_schedules).where(db.delivery_schedules.c.source_id == source_id,
                                                        db.delivery_schedules.c.status == "active")).all()
    if not sch:
        return None
    now = _now()
    for s in sch:
        _materialize(c, s, now)
    by_id = {s.schedule_id: effective(s.config) for s in sch}
    t = db.deliveries
    cands = c.execute(select(t).where(t.c.schedule_id.in_(list(by_id)), t.c.status.in_(OPEN), t.c.window_start <= now)
                      .order_by(t.c.due_at).with_for_update()).all()
    cands = [d for d in cands if not by_id[d.schedule_id].get("filename_glob")
             or fnmatch.fnmatch(filename or "", by_id[d.schedule_id]["filename_glob"])]
    # Oldest window that is still live (expected / late) first. Only when none is live does a file count as
    # the late arrival of a *missed* window, and only of the window that just passed (the latest due time
    # before now): a file today never fills a gap from weeks ago.
    live = [d for d in cands if d.status in ("expected", "late")]
    pick = live[:1]
    if not pick:
        latest = []
        for sid in {d.schedule_id for d in cands}:
            last = c.execute(select(t.c.delivery_id).where(t.c.schedule_id == sid, t.c.due_at <= now).order_by(t.c.due_at.desc()).limit(1)).scalar()
            latest += [d for d in cands if d.delivery_id == last and d.status == "missed"]
        pick = sorted(latest, key=lambda d: d.due_at)[-1:]
    for d in pick:
        cfg = by_id[d.schedule_id]
        ids = list(d.batch_ids or []) + [batch_id]
        done = len(ids) >= int(cfg.get("expected_files") or 1)
        on_time = now <= d.due_at + timedelta(minutes=cfg["grace_minutes"])
        status = ("received" if on_time else "received_late") if done else d.status
        c.execute(t.update().where(t.c.delivery_id == d.delivery_id).values(batch_ids=ids, status=status,
                                                                            received_at=d.received_at or now))
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(delivery_id=d.delivery_id))
        if done and d.status in ("late", "missed"):
            db.audit(c, "scheduler", "delivery.received_late", "delivery", d.delivery_id, {"batch_id": batch_id, "was": d.status})
        return d.delivery_id
    return None


# ------------------------------------------------------------------ tick
def _acquire_leader(owner: str, now) -> bool:
    st = db.scheduler_state
    with db.get_engine().begin() as c:
        if c.execute(select(st.c.id).where(st.c.id == 1)).first() is None:
            try:
                with c.begin_nested():
                    c.execute(st.insert().values(id=1))
            except IntegrityError:
                pass
        res = c.execute(st.update().where(st.c.id == 1, (st.c.owner.is_(None)) | (st.c.owner == owner) |
                                          (st.c.heartbeat_at < now - timedelta(seconds=LEASE_SECONDS)))
                        .values(owner=owner, heartbeat_at=now))
        return res.rowcount == 1


def _release_leader(owner: str, result: dict) -> None:
    st = db.scheduler_state
    with db.get_engine().begin() as c:
        c.execute(st.update().where(st.c.id == 1, st.c.owner == owner).values(owner=None, last_tick_at=_now(), last_result=result))


def tick(now=None, pull: bool = True) -> dict:
    """One scheduler pass. Returns what changed; `batches` lists batches created by pulls (local mode)."""
    now = now or _now()
    owner = f"{socket.gethostname()}:{os.getpid()}"
    if not _acquire_leader(owner, now):
        return {"skipped": "another scheduler instance holds the lease"}
    res = {"at": now.isoformat(), "materialized": 0, "late": [], "missed": [], "pulled": [], "batches": [], "pull_errors": []}
    try:
        t = db.deliveries
        with db.get_engine().begin() as c:
            sch = c.execute(select(db.delivery_schedules).where(db.delivery_schedules.c.status == "active")).all()
            from ..vendors import names_by_source

            names = {k: (v["vendor_name"] if v["feed_name"] == v["vendor_name"] else f"{v['vendor_name']} · {v['feed_name']}")
                     for k, v in names_by_source(c).items()}
            for s in sch:
                res["materialized"] += _materialize(c, s, now)
        cfgs = {s.schedule_id: effective(s.config) for s in sch}
        alerts = []
        with db.get_engine().begin() as c:
            rows = c.execute(select(t).where(t.c.schedule_id.in_(list(cfgs) or ["-"]), t.c.status.in_(("expected", "late")),
                                             t.c.due_at <= now).with_for_update()).all()
            for d in rows:
                cfg = cfgs[d.schedule_id]
                if now > d.due_at + timedelta(minutes=cfg["miss_after_minutes"]):
                    c.execute(t.update().where(t.c.delivery_id == d.delivery_id).values(status="missed", missed_alerted_at=now))
                    res["missed"].append(d.delivery_id)
                    alerts.append(("delivery_missed", f"{names.get(d.source_id, d.source_id)}: file due {d.local_label} has not arrived "
                                                      f"({cfg['miss_after_minutes']} min past due)", d))
                elif d.status == "expected" and now > d.due_at + timedelta(minutes=cfg["grace_minutes"]):
                    c.execute(t.update().where(t.c.delivery_id == d.delivery_id).values(status="late", late_alerted_at=now))
                    res["late"].append(d.delivery_id)
                    alerts.append(("delivery_late", f"{names.get(d.source_id, d.source_id)}: file due {d.local_label} is late", d))
        for kind, msg, d in alerts:  # after commit: an alert is sent once, for a state that is durable
            notify(kind, msg, {"delivery_id": d.delivery_id, "source_id": d.source_id, "schedule_id": d.schedule_id,
                               "due_at": d.due_at.isoformat()})
        if pull:
            for s in sch:
                cfg = cfgs[s.schedule_id]
                if not cfg.get("pull"):
                    continue
                poll = timedelta(minutes=int(cfg["pull"].get("poll_minutes", 15)))
                if s.last_pull_at and now - s.last_pull_at < poll:
                    continue
                with db.get_engine().connect() as c:
                    window_open = c.execute(select(t.c.delivery_id).where(t.c.schedule_id == s.schedule_id, t.c.status.in_(OPEN),
                                                                          t.c.window_start <= now).limit(1)).first()
                if not window_open:
                    continue
                from ..dispatch import aws_mode, start_glue

                if aws_mode() and get_settings().glue_pull_job:
                    # the pull itself is data movement: it runs as a Glue job, not in the scheduler Lambda
                    with db.get_engine().begin() as c:
                        c.execute(db.delivery_schedules.update().where(db.delivery_schedules.c.schedule_id == s.schedule_id)
                                  .values(last_pull_at=now))
                    res["pulled"].append({"schedule_id": s.schedule_id, "glue_run_id": start_glue(get_settings().glue_pull_job,
                                                                                                {"schedule_id": s.schedule_id})})
                    continue
                out = pull_now(s.schedule_id, actor="scheduler", roles=["admin"], now=now)
                res["pulled"] += out["fetched"]
                res["batches"] += out["batches"]
                if out.get("error"):
                    res["pull_errors"].append({"schedule_id": s.schedule_id, "error": out["error"]})
    finally:
        _release_leader(owner, {k: (len(v) if isinstance(v, list) else v) for k, v in res.items()})
    return res


def pull_now(schedule_id: str, actor: str, roles: list[str], now=None) -> dict:
    """Fetch new files for a pull schedule and register each as a batch (or, in AWS, drop it in the raw
    zone where the normal S3 arrival event registers it)."""
    from ..pipeline.batch import DuplicateFileError, create_batch
    from ..storage import persist_upload

    _role(roles, "ops", "sme")
    now = now or _now()
    with db.get_engine().begin() as c:
        s = _load(c, schedule_id)
        if s.status != "active" or not effective(s.config).get("pull"):
            raise ScheduleError("schedule is not an active pull schedule")
        c.execute(db.delivery_schedules.update().where(db.delivery_schedules.c.schedule_id == schedule_id).values(last_pull_at=now))
        already = {(r.remote_name, r.remote_size, r.remote_mtime) for r in c.execute(
            select(db.pulled_files).where(db.pulled_files.c.schedule_id == schedule_id))}
    cfg = effective(s.config)
    out = {"schedule_id": schedule_id, "fetched": [], "batches": [], "skipped": []}
    try:
        got, out["skipped"] = fetch_new(cfg["pull"], already)
    except Exception as e:  # noqa: BLE001 - any connector failure is recorded, never raised into the tick
        msg = f"{e.__class__.__name__}: {str(e).splitlines()[0][:300] if str(e) else ''}"
        out["error"] = msg
        _record_pull_error(s, msg, now)
        return out
    aws = get_settings().env == "aws" and get_settings().raw_bucket
    for remote, local, sha in got:
        with db.get_engine().begin() as c:
            try:
                with c.begin_nested():
                    pid = c.execute(db.pulled_files.insert().returning(db.pulled_files.c.id).values(
                        schedule_id=schedule_id, remote_name=remote.name, remote_size=remote.size, remote_mtime=remote.mtime,
                        sha256=sha)).scalar()
            except IntegrityError:
                local.unlink(missing_ok=True)
                continue  # fetched concurrently by another instance
        uri = persist_upload(local, f"incoming/{s.source_id}/{sha[:12]}", metadata={"submitted-by": f"scheduler:{schedule_id}"})
        out["fetched"].append(remote.name)
        bid = None
        if not aws:
            try:
                bid = create_batch(s.source_id, uri, local.name, f"scheduler:{schedule_id}", strict=False,
                                   load_type=cfg.get("load_type"))
                out["batches"].append(bid)
            except DuplicateFileError as e:
                bid = e.batch_id
                out["skipped"].append(f"{remote.name}: identical to batch {e.batch_id}")
            except ValueError as e:
                out["skipped"].append(f"{remote.name}: {e}")
        with db.get_engine().begin() as c:
            c.execute(db.pulled_files.update().where(db.pulled_files.c.id == pid).values(batch_id=bid))
            db.audit(c, actor, "delivery.pulled", "schedule", schedule_id, {"file": remote.name, "size": remote.size, "batch_id": bid,
                                                                            "sha256": sha})
    with db.get_engine().begin() as c:
        c.execute(db.deliveries.update().where(db.deliveries.c.schedule_id == schedule_id, db.deliveries.c.status.in_(OPEN))
                  .values(last_pull_error=None))
    return out


def _record_pull_error(s, msg, now) -> None:
    t = db.deliveries
    with db.get_engine().begin() as c:
        d = c.execute(select(t).where(t.c.schedule_id == s.schedule_id, t.c.status.in_(OPEN), t.c.window_start <= now)
                      .order_by(t.c.due_at).limit(1)).first()
        if d is None:
            return
        attempts = (d.pull_attempts or 0) + 1
        c.execute(t.update().where(t.c.delivery_id == d.delivery_id).values(pull_attempts=attempts, last_pull_error=msg))
        db.audit(c, "scheduler", "delivery.pull_failed", "delivery", d.delivery_id, {"error": msg, "attempt": attempts})
    if attempts == 3:
        notify("pull_failing", f"Pull for schedule {s.name} has failed 3 times: {msg}", {"delivery_id": d.delivery_id,
                                                                                      "schedule_id": s.schedule_id})


# ------------------------------------------------------------------ reads
def _sched_dict(s, names, now, stats) -> dict:
    d = db.row_to_dict(s)
    cfg = effective(s.config or s.proposed)
    n = names.get(s.source_id) or {}
    d["source_name"] = n.get("feed_name", s.source_id) if isinstance(n, dict) else n
    if isinstance(n, dict):
        d["vendor_id"], d["vendor_name"] = n.get("vendor_id"), n.get("vendor_name")
    d["describe"] = cron.describe(cfg.get("cron") or "")
    d["kind"] = "pull" if cfg.get("pull") else "push"
    d["next_due"] = None
    if s.status == "active" and s.config:
        nxt = cron.next_after(cfg["cron"], cfg["timezone"], now, 1, cfg["calendar"], cfg["holiday_rule"])
        if nxt:
            d["next_due"] = nxt[0].isoformat() + "Z"
            d["next_due_local"] = cron.local_label(nxt[0], cfg["timezone"])
    d["stats_30d"] = stats.get(s.schedule_id, {})
    return d


def _stats(c, now) -> dict:
    t = db.deliveries
    out: dict[str, dict] = {}
    for sid, st, n in c.execute(select(t.c.schedule_id, t.c.status, func.count()).where(t.c.due_at > now - timedelta(days=30),
                                                                                      t.c.due_at <= now).group_by(t.c.schedule_id, t.c.status)):
        out.setdefault(sid, {})[st] = n
    for v in out.values():
        due = sum(n for k, n in v.items() if k != "waived")
        v["on_time_pct"] = round(100 * v.get("received", 0) / due, 1) if due else None
    return out


def list_schedules(source_id: str | None = None, source_ids: list[str] | None = None) -> list[dict]:
    from ..vendors import names_by_source

    now = _now()
    with db.get_engine().connect() as c:
        q = select(db.delivery_schedules).order_by(db.delivery_schedules.c.created_at)
        if source_id:
            q = q.where(db.delivery_schedules.c.source_id == source_id)
        if source_ids is not None:
            q = q.where(db.delivery_schedules.c.source_id.in_(source_ids or ["-"]))
        rows = c.execute(q).all()
        names = names_by_source(c)
        stats = _stats(c, now)
    return [_sched_dict(s, names, now, stats) for s in rows]


def get_schedule(schedule_id: str) -> dict:
    now = _now()
    with db.get_engine().connect() as c:
        s = c.execute(select(db.delivery_schedules).where(db.delivery_schedules.c.schedule_id == schedule_id)).first()
        if not s:
            raise ScheduleError("schedule not found")
        from ..vendors import names_by_source

        names = names_by_source(c)
        stats = _stats(c, now)
    return _sched_dict(s, names, now, stats)


def list_deliveries(frm=None, to=None, source_id: str | None = None, status: str | None = None, limit: int = 500,
                    source_ids: list[str] | None = None) -> list[dict]:
    now = _now()
    frm = frm or now - timedelta(days=7)
    to = to or now + timedelta(days=2)
    t = db.deliveries
    q = select(t).where(t.c.due_at >= frm, t.c.due_at <= to)
    if source_id:
        q = q.where(t.c.source_id == source_id)
    if status:
        q = q.where(t.c.status.in_(status.split(",")))
    if source_ids is not None:
        q = q.where(t.c.source_id.in_(source_ids or ["-"]))
    from ..vendors import names_by_source

    with db.get_engine().connect() as c:
        rows = c.execute(q.order_by(t.c.due_at.desc()).limit(limit)).all()
        names = names_by_source(c)
        snames = dict(c.execute(select(db.delivery_schedules.c.schedule_id, db.delivery_schedules.c.name)).all())
        bids = sorted({b for r in rows for b in (r.batch_ids or [])})
        bat = {r.batch_id: r for r in c.execute(select(db.batches.c.batch_id, db.batches.c.status, db.batches.c.filename,
                                                       db.batches.c.sequence, db.batches.c.load_type)
                                                .where(db.batches.c.batch_id.in_(bids or ["-"])))}
    out = []
    from ..pipeline.delivery import display_sequence

    for r in rows:
        d = db.row_to_dict(r)
        n = names.get(r.source_id) or {}
        d["source_name"], d["vendor_id"], d["vendor_name"] = n.get("feed_name", r.source_id), n.get("vendor_id"), n.get("vendor_name")
        d["schedule_name"] = snames.get(r.schedule_id)
        d["batches"] = [{"batch_id": b, "status": bat[b].status, "filename": bat[b].filename, "load_type": bat[b].load_type,
                         "sequence": display_sequence(bat[b].sequence)} for b in (r.batch_ids or []) if b in bat]
        out.append(d)
    return out


def vendor_freshness(source_ids: list[str] | None = None) -> list[dict]:
    """Per feed (grouped under its vendor): last arrival, applied cursor, on-time rate, open gaps, change volume (30 days)."""
    from ..pipeline.delivery import display_sequence, profile_of

    now = _now()
    b, t = db.batches, db.deliveries
    with db.get_engine().connect() as c:
        srcs = c.execute(select(db.sources)).all()
        stats = _stats(c, now)
        sch = c.execute(select(db.delivery_schedules)).all()
        last_arr = dict(c.execute(select(b.c.source_id, func.max(b.c.created_at)).group_by(b.c.source_id)).all())
        waiting = dict(c.execute(select(b.c.source_id, func.count()).where(b.c.status.in_(("waiting", "out_of_order")))
                                 .group_by(b.c.source_id)).all())
        open_late = dict(c.execute(select(t.c.source_id, func.count()).where(t.c.status.in_(("late", "missed")))
                                   .group_by(t.c.source_id)).all())
        recent = c.execute(select(b.c.source_id, b.c.change_summary, b.c.load_type).where(
            b.c.created_at > now - timedelta(days=30), b.c.status == "completed")).all()
        active = dict(c.execute(select(db.sse_loans.c.lbp_source_id, func.count()).where(db.sse_loans.c.lbp_status == "active")
                                .group_by(db.sse_loans.c.lbp_source_id)).all())
    vol: dict[str, dict] = {}
    for r in recent:
        v = vol.setdefault(r.source_id, {"files": 0, "adds": 0, "updates": 0, "closes": 0, "unchanged": 0, "conflicts": 0})
        v["files"] += 1
        cs = r.change_summary or {}
        v["adds"] += cs.get("adds_applied", 0)
        v["updates"] += cs.get("updates_applied", 0)
        v["closes"] += cs.get("closes_applied", 0)
        v["unchanged"] += cs.get("unchanged_rows", 0)
        v["conflicts"] += cs.get("conflicts", 0)
    from ..vendors import names_by_source

    with db.get_engine().connect() as c:
        vn = names_by_source(c)
    out = []
    for s in srcs:
        if source_ids is not None and s.source_id not in source_ids:
            continue
        mine = [x for x in sch if x.source_id == s.source_id]
        agg: dict[str, int] = {}
        for x in mine:
            for k, n in stats.get(x.schedule_id, {}).items():
                if k != "on_time_pct":
                    agg[k] = agg.get(k, 0) + n
        due = sum(n for k, n in agg.items() if k != "waived")
        nxt = [d for d in (_sched_dict(x, {}, now, {}).get("next_due") for x in mine) if d]
        prof = profile_of(s.delivery)
        out.append({
            "source_id": s.source_id, "name": s.name, "vendor_id": s.vendor_id, "vendor_name": (vn.get(s.source_id) or {}).get("vendor_name"),
            "load_type": prof["load_type"], "schedules": len(mine),
            "last_arrival": last_arr[s.source_id].isoformat() + "Z" if last_arr.get(s.source_id) else None,
            "hours_since_arrival": round((now - last_arr[s.source_id]).total_seconds() / 3600, 1) if last_arr.get(s.source_id) else None,
            "last_sequence": display_sequence(s.last_sequence), "waiting_files": waiting.get(s.source_id, 0),
            "open_late_or_missed": open_late.get(s.source_id, 0), "deliveries_30d": agg,
            "on_time_pct": round(100 * agg.get("received", 0) / due, 1) if due else None,
            "next_due": min(nxt) if nxt else None, "active_loans": active.get(s.source_id, 0), "changes_30d": vol.get(s.source_id, {}),
        })
    return out


def preview(cfg: dict, n: int = 8) -> dict:
    errs = [e for e in validate_config({**cfg, "pull": None}) if not e.startswith("pull")]
    if errs:
        return {"valid": False, "errors": errs}
    c = effective(cfg)
    nxt = cron.next_after(c["cron"], c["timezone"], _now(), n, c["calendar"], c["holiday_rule"])
    return {"valid": True, "describe": cron.describe(c["cron"]),
            "next": [{"utc": x.isoformat() + "Z", "local": cron.local_label(x, c["timezone"])} for x in nxt]}
