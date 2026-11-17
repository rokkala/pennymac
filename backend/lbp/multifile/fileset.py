"""File sets: the files of one multi-file delivery, collected until the feed's readiness policy is met.

    route_file       filename -> (role, captured groups) by the layout's `name_pattern` (fullmatch, file order)
    pairing_key      the value that ties a set's files together (captured groups, or the arrival window)
    attach_file      add an arriving file to the open (`waiting`) set with the same pairing key, or open one
    evaluate_set     `waiting` -> `ready` when the readiness requirement is met
    expire_sets      sets past `wait_timeout_minutes`: alert naming the missing role(s), then apply `on_timeout`
    create_batch_for_set   one batch on the master file (one delivery, one sequence number), members linked

Set statuses: waiting | ready | expired | overridden | consumed | discarded. Only `waiting` sets accept
files, so a file for a role of a set that is already ready/consumed opens a new set (a correction), which
must again receive every role it requires. Set identity (`members_sha`) is the sha256 of the sorted
`role:sha256` pairs; a set identical to one whose batch is live is rejected as a duplicate.

Concurrency: attach and expiry take a write-first lock on the feed's `sources` row before reading any set
(row lock on PostgreSQL, the database write lock on SQLite, where `with_for_update` is a no-op) and then
read the open sets `with_for_update`; so two arrivals for one feed are serialised and cannot open two sets
for one key. A batch is created only after claiming the set with a conditional update (exactly one caller
wins), outside the attach transaction because `create_batch` opens its own.

Messages and audit entries carry filenames, roles and hashes only, never file contents.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from ..pipeline.batch import DuplicateFileError
from ..store import db

NAMED_GROUP_PAIRINGS = ("sequence", "business_date", "filename_token")
CORRECTION_REASON = "file set correction: members_sha differs"
_CLAIM = "claim:"


class FileSetError(ValueError):
    pass


class DuplicateFileSetError(DuplicateFileError):
    """The same files (by role and sha256) as a set whose batch is live."""

    def __init__(self, batch_id: str, when):
        ValueError.__init__(self, f"this exact set of files was already submitted for this feed as batch {batch_id} "
                                  f"({when:%Y-%m-%d %H:%M} UTC)")
        self.batch_id = batch_id


# ------------------------------------------------------------------ pure helpers
def route_file(layout: dict, filename: str) -> tuple[str, dict[str, str]] | None:
    """The role whose `name_pattern` fully matches the bare filename (patterns tried in file order), with the
    named groups it captured. None when no file of the layout matches."""
    name = Path(str(filename).replace("\\", "/")).name
    for f in (layout or {}).get("files") or []:
        pat = f.get("name_pattern")
        if not pat:
            continue
        m = re.fullmatch(pat, name)
        if m:
            return f.get("role"), {k: v for k, v in m.groupdict().items() if v is not None}
    return None


def pairing_key(readiness: dict, captured: dict[str, str], arrived_at: datetime) -> str:
    """Key shared by the files of one set. For sequence / business_date / filename_token it is the captured
    named groups (`name=value`, sorted by name), so files pair only when their groups carry equal values.
    For window_minutes it names the arrival minute of the set's first file (pairing itself uses the window)."""
    pairing = (readiness or {}).get("pairing") or "business_date"
    if pairing == "window_minutes":
        return f"window:{arrived_at:%Y-%m-%dT%H:%M}"
    if not captured:
        raise FileSetError(f"pairing {pairing} needs a value captured by a named group in name_pattern; none was found")
    return "|".join(f"{k}={captured[k]}" for k in sorted(captured))


def _members_sha(members: dict[str, str]) -> str:
    return hashlib.sha256("\n".join(f"{r}:{members[r]}" for r in sorted(members)).encode()).hexdigest()


def _required_roles(layout: dict, readiness: dict) -> list[str]:
    """Roles a set must hold to be ready. master_only: the master. all_required: every declared file; a
    detail's `required` flag decides whether the set may load without it (load_master_only / overrides)."""
    roles = [f.get("role") for f in (layout or {}).get("files") or [] if f.get("role")]
    if (readiness or {}).get("require") == "master_only":
        return ["master"]
    return roles


def _missing(layout: dict, readiness: dict, present: set[str]) -> list[str]:
    return [r for r in _required_roles(layout, readiness) if r not in present]


def _config(source_id: str):
    from ..config_store import ConfigError, load

    try:
        cfg = load(source_id)
    except ConfigError as e:
        raise FileSetError(str(e)) from e
    if not cfg.layout:
        raise FileSetError(f"feed {source_id} has no multi-file layout")
    return cfg


def _lock_source(c, source_id: str) -> None:
    """Write-first lock on the feed row (no-op update): serialises set decisions for this feed on both
    PostgreSQL (row lock) and SQLite (database write lock taken before any read)."""
    s = db.sources
    if c.execute(s.update().where(s.c.source_id == source_id).values(source_id=s.c.source_id)).rowcount == 0:
        raise FileSetError("unknown source")


def _present(c, set_id: str) -> dict[str, str]:
    bf = db.batch_files
    return {r.role: r.file_sha256 for r in c.execute(select(bf.c.role, bf.c.file_sha256).where(bf.c.set_id == set_id))}


def _evaluate(c, s, cfg, now: datetime) -> str:
    if s.status != "waiting":
        return s.status
    members = _present(c, s.set_id)
    vals = {"members_sha": _members_sha(members) if members else None}
    status = "waiting"
    if not _missing(cfg.layout, cfg.readiness, set(members)):
        status = "ready"
        vals.update(status="ready", ready_at=now)
    c.execute(db.file_sets.update().where(db.file_sets.c.set_id == s.set_id).values(**vals))
    if status == "ready":
        db.audit(c, "pipeline", "file_set.ready", "file_set", s.set_id, {"roles": sorted(members), "members_sha": vals["members_sha"]})
    return status


# ------------------------------------------------------------------ intake
def attach_file(source_id: str, filename: str, file_path: Path, actor: str, role: str | None = None,
                arrived_at: datetime | None = None) -> dict:
    """Attach one arriving file to its set; queue the set's batch when the set becomes ready."""
    from ..ingestion.parser import estimate_rows
    from ..pipeline.batch import file_sha256
    from ..storage import local_path

    cfg = _config(source_id)
    layout, readiness = cfg.layout, cfg.readiness or {}
    if role is not None:
        f = next((x for x in layout.get("files") or [] if x.get("role") == role), None)
        if f is None:
            raise FileSetError(f"role {role!r} is not declared in the feed layout")
        m = re.fullmatch(f.get("name_pattern") or "", Path(str(filename)).name)
        captured = {k: v for k, v in m.groupdict().items() if v is not None} if m else {}
    else:
        routed = route_file(layout, filename)
        if routed is None:
            raise FileSetError(f"'{Path(str(filename)).name}' does not match any file in the feed layout")
        role, captured = routed
    now = arrived_at or db.now()
    key = pairing_key(readiness, captured, now)
    local = local_path(file_path)
    digest = file_sha256(local)
    rows = estimate_rows(local)
    fs, bf = db.file_sets, db.batch_files

    with db.get_engine().begin() as c:
        _lock_source(c, source_id)
        q = select(fs).where(fs.c.source_id == source_id, fs.c.status == "waiting")
        if readiness.get("pairing") == "window_minutes":
            q = q.where(fs.c.opened_at >= now - timedelta(minutes=int(readiness["window_minutes"])), fs.c.opened_at <= now)
        else:
            q = q.where(fs.c.pairing_key == key)
        s = c.execute(q.order_by(fs.c.opened_at).with_for_update()).first()
        if s is None:
            set_id = db.new_id("fst")
            c.execute(fs.insert().values(set_id=set_id, source_id=source_id, pairing_key=key, status="waiting", opened_at=now,
                                         expires_at=now + timedelta(minutes=int(readiness.get("wait_timeout_minutes") or 0))))
            db.audit(c, actor, "file_set.open", "file_set", set_id, {"source_id": source_id, "pairing_key": key})
            s = c.execute(select(fs).where(fs.c.set_id == set_id)).first()
        prior = c.execute(select(bf).where(bf.c.set_id == s.set_id, bf.c.role == role)).first()
        vals = {"filename": Path(str(filename)).name, "file_path": str(file_path), "file_sha256": digest, "row_count": rows,
                "received_at": now}
        if prior is None:
            c.execute(bf.insert().values(set_id=s.set_id, role=role, **vals))
            db.audit(c, actor, "file_set.attach", "file_set", s.set_id, {"role": role, "file": vals["filename"], "sha256": digest})
        elif prior.file_sha256 != digest:
            c.execute(bf.update().where(bf.c.id == prior.id).values(**vals))
            db.audit(c, actor, "file_set.member_replaced", "file_set", s.set_id,
                     {"role": role, "file": vals["filename"], "sha256": digest, "previous_file": prior.filename,
                      "previous_sha256": prior.file_sha256})
        # else: the same file again for this role: idempotent, nothing changes
        status = _evaluate(c, s, cfg, now)
        set_id = s.set_id

    batch_id = None
    if status == "ready":
        batch_id = create_batch_for_set(set_id, actor)
        status = "consumed"
    return {"set_id": set_id, "role": role, "status": status, "batch_id": batch_id}


def evaluate_set(set_id: str, now: datetime | None = None) -> str:
    """Re-check a set against its feed's readiness policy; returns the (possibly new) status."""
    with db.get_engine().begin() as c:
        s = c.execute(select(db.file_sets).where(db.file_sets.c.set_id == set_id)).first()
        if s is None:
            raise FileSetError("file set not found")
        cfg = _config(s.source_id)
        _lock_source(c, s.source_id)
        s = c.execute(select(db.file_sets).where(db.file_sets.c.set_id == set_id).with_for_update()).first()
        return _evaluate(c, s, cfg, now or db.now())


def expire_sets(now: datetime | None = None) -> list[str]:
    """Handle waiting sets whose wait_timeout has passed (each once): alert naming the missing role(s), then
    on_timeout: alert_only keeps the set waiting; fail marks it expired; load_master_only queues a batch on
    the files present when every missing role is non-required and the master is present (else expired)."""
    from ..scheduling import alerts

    now = now or db.now()
    fs = db.file_sets
    with db.get_engine().connect() as c:
        due = c.execute(select(fs.c.set_id, fs.c.source_id).where(fs.c.status == "waiting", fs.c.expires_at.is_not(None),
                                                                   fs.c.expires_at <= now)).all()
    handled: list[str] = []
    to_load: list[str] = []
    notes: list[tuple[str, str, dict]] = []
    for set_id, source_id in due:
        try:
            cfg = _config(source_id)
        except FileSetError:
            continue
        layout, readiness = cfg.layout, cfg.readiness or {}
        policy = readiness.get("on_timeout") or "alert_only"
        with db.get_engine().begin() as c:
            _lock_source(c, source_id)
            s = c.execute(select(fs).where(fs.c.set_id == set_id).with_for_update()).first()
            if s is None or s.status != "waiting" or (s.override or {}).get("timeout"):
                continue
            present = set(_present(c, set_id))
            missing = _missing(layout, readiness, present)
            optional = {f.get("role") for f in layout.get("files") or [] if f.get("role") != "master" and not f.get("required")}
            action = policy
            if policy == "load_master_only" and ("master" not in present or not set(missing) <= optional):
                action = "fail"
            record = {"at": now.isoformat(), "policy": policy, "action": action, "missing_roles": missing}
            vals: dict = {"override": {**(s.override or {}), "timeout": record}}
            if action == "fail":
                vals["status"] = "expired"
            elif action == "load_master_only":
                vals.update(status="ready", ready_at=now, members_sha=_members_sha(_present(c, set_id)))
            c.execute(fs.update().where(fs.c.set_id == set_id, fs.c.status == "waiting").values(**vals))
            db.audit(c, "scheduler", "file_set.timeout", "file_set", set_id, record)
        roles = ", ".join(missing) or "none"
        kind = "delivery_late" if action == "alert_only" else "delivery_missed"
        verb = {"alert_only": "still waiting", "fail": "set expired", "load_master_only": "loading the master file without it"}[action]
        msg = (f"file set {set_id} for feed {source_id} (pairing {s.pairing_key}): missing {roles} file "
               f"after {readiness.get('wait_timeout_minutes')} min; {verb}")
        notes.append((kind, msg, {"set_id": set_id, "source_id": source_id, "missing_roles": missing, "on_timeout": policy}))
        handled.append(set_id)
        if action == "load_master_only":
            to_load.append(set_id)
    for kind, msg, detail in notes:
        alerts.notify(kind, msg, detail)
    for set_id in to_load:
        create_batch_for_set(set_id, "scheduler")
    return handled


# ------------------------------------------------------------------ batch
def create_batch_for_set(set_id: str, actor: str) -> str:
    """Queue the batch of a ready set: registered on the master file through `create_batch` (so the
    sequencing gate and delivery matching see one file), then linked to the set and its members."""
    from ..pipeline.batch import create_batch

    fs, bf, bt = db.file_sets, db.batch_files, db.batches
    claim = _CLAIM + db.new_id("c")[-20:]
    with db.get_engine().begin() as c:
        s = c.execute(select(fs).where(fs.c.set_id == set_id).with_for_update()).first()
        if s is None:
            raise FileSetError("file set not found")
        if s.status not in ("ready", "overridden") or s.batch_id is not None:
            raise FileSetError(f"file set {set_id} is {s.status}; only a ready set without a batch can be queued")
        members = {r.role: r for r in c.execute(select(bf).where(bf.c.set_id == set_id))}
        master = members.get("master")
        if master is None:
            raise FileSetError(f"file set {set_id} has no master file")
        msha = _members_sha({r: m.file_sha256 for r, m in members.items()})
        dup = c.execute(select(bt.c.batch_id, bt.c.created_at).select_from(fs.join(bt, bt.c.batch_id == fs.c.batch_id)).where(
            fs.c.source_id == s.source_id, fs.c.members_sha == msha, fs.c.set_id != set_id,
            bt.c.status.not_in(("failed", "discarded")))).first()
        if dup:
            raise DuplicateFileSetError(dup.batch_id, dup.created_at)
        master_dup = c.execute(select(bt.c.batch_id).where(bt.c.source_id == s.source_id, bt.c.file_sha256 == master.file_sha256,
                                                           bt.c.status.not_in(("failed", "discarded")))).first()
        # claim: exactly one caller may go on to create the batch
        if c.execute(fs.update().where(fs.c.set_id == set_id, fs.c.batch_id.is_(None)).values(batch_id=claim, members_sha=msha)).rowcount != 1:
            raise FileSetError(f"file set {set_id} is already being queued")
    try:  # the stored URI as-is: Path() would collapse an s3:// URI
        if master_dup:  # members_sha is new: a correction set whose master file is unchanged
            bid = create_batch(s.source_id, master.file_path, master.filename, actor, allow_duplicate=True, reason=CORRECTION_REASON)
        else:
            bid = create_batch(s.source_id, master.file_path, master.filename, actor)
    except Exception:
        with db.get_engine().begin() as c:
            c.execute(fs.update().where(fs.c.set_id == set_id, fs.c.batch_id == claim).values(batch_id=None))
        raise
    with db.get_engine().begin() as c:
        c.execute(bt.update().where(bt.c.batch_id == bid).values(file_set_id=set_id))
        c.execute(bf.update().where(bf.c.set_id == set_id).values(batch_id=bid))
        c.execute(fs.update().where(fs.c.set_id == set_id).values(batch_id=bid, status="consumed"))
        db.audit(c, actor, "file_set.batch", "file_set", set_id, {"batch_id": bid, "roles": sorted(members), "members_sha": msha})
    return bid
