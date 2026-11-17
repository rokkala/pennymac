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

Concurrency: attach, expiry and batch creation take a write-first lock on the feed's `sources` row before
reading any set (row lock on PostgreSQL, the database write lock on SQLite, where `with_for_update` is a
no-op) and then read the sets `with_for_update`; so two arrivals for one feed are serialised and cannot
open two sets for one key. A set's batch is registered in ONE transaction with the set's move
ready -> consumed and the members' links, so no worker ever sees a queued set batch without its set.

Robustness: `expire_sets` handles each set in isolation (an error is recorded on the set, audited and logged,
then the sweep goes on) and also retries every `ready` set that has no batch yet.

Messages and audit entries carry filenames, roles and hashes only, never file contents.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from ..pipeline.batch import DuplicateFileError
from ..store import db

NAMED_GROUP_PAIRINGS = ("sequence", "business_date", "filename_token")
CORRECTION_REASON = "file set correction: members_sha differs"
PAIRING_KEY_MAX = 120  # file_sets.pairing_key String(120)

log = logging.getLogger(__name__)


class FileSetError(ValueError):
    pass


class SetNotReadyError(FileSetError):
    """The set is no longer ready (another worker queued or discarded it meanwhile): benign for intake and sweep."""


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
    values, ordered by group name, so files pair when their values are equal whatever the groups are called.
    For window_minutes it names the arrival minute of the set's first file (pairing itself uses the window)."""
    pairing = (readiness or {}).get("pairing") or "business_date"
    if pairing == "window_minutes":
        return f"window:{_naive_utc(arrived_at):%Y-%m-%dT%H:%M}"
    if not captured:
        raise FileSetError(f"pairing {pairing} needs a value captured by a named group in name_pattern; none was found")
    key = "|".join(captured[k] for k in sorted(captured))
    if len(key) > PAIRING_KEY_MAX:
        raise FileSetError(f"pairing value is too long ({len(key)} characters, at most {PAIRING_KEY_MAX})")
    return key


def _captures(layout: dict, role: str, filename: str) -> dict[str, str]:
    f = next((x for x in (layout or {}).get("files") or [] if x.get("role") == role), None)
    if f is None:
        raise FileSetError(f"role {role!r} is not declared in the feed layout")
    m = re.fullmatch(f.get("name_pattern") or "", Path(str(filename)).name)
    return {k: v for k, v in m.groupdict().items() if v is not None} if m else {}


def plan_files(layout: dict, readiness: dict, names: list[str], manifest: dict[str, str] | None = None,
               now: datetime | None = None) -> list[tuple[str, str]]:
    """(filename, role) for the files of one upload, all or nothing: a manifest ({role: filename}) assigns roles
    explicitly, any other file is routed by name_pattern. A file that routes nowhere, a manifest entry naming an
    undeclared role or a file not in the upload, two files for one role, or a file whose pairing value cannot be
    derived fails the whole upload before anything is attached."""
    manifest = manifest or {}
    by_name: dict[str, str] = {}
    for role, fname in manifest.items():
        _captures(layout, role, fname)  # the role must be declared
        if fname not in names:
            raise FileSetError(f"the manifest names '{fname}', which is not in this upload")
        if fname in by_name:
            raise FileSetError(f"the manifest assigns '{fname}' to more than one role")
        by_name[fname] = role
    out, seen, keys = [], set(), set()
    for n in names:
        role = by_name.get(n)
        if role is None:
            routed = route_file(layout, n)
            if routed is None:
                raise FileSetError(f"'{Path(str(n)).name}' does not match any file in the feed layout")
            role = routed[0]
        if role in seen:
            raise FileSetError(f"more than one file for role {role!r} in one upload")
        seen.add(role)
        keys.add(pairing_key(readiness or {}, _captures(layout, role, n), _naive_utc(now)))
        out.append((n, role))
    if len(keys) > 1:
        raise FileSetError(f"the files of one upload must share one pairing value; found {len(keys)}: {', '.join(sorted(keys))}")
    # the master last: with require master_only it would make the set ready before its details are attached
    return sorted(out, key=lambda x: x[1] == "master")


def _naive_utc(t: datetime | None) -> datetime:
    """Timestamps are stored naive UTC (db.now()); an aware value is converted, a naive one taken as UTC."""
    if t is None:
        return db.now()
    return t.astimezone(UTC).replace(tzinfo=None) if t.tzinfo is not None else t


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


def feed_layout(source_id: str) -> dict | None:
    """The published layout of a feed, or None for a single-file feed. The feed row's approved `layout` is read
    first: a feed without one is single-file and its configuration bundle is never read (so a missing or corrupt
    bundle behaves exactly as before). A feed with one loads its published bundle; its ConfigError is raised."""
    from ..config_store import load

    with db.get_engine().connect() as c:
        approved = c.execute(select(db.sources.c.layout).where(db.sources.c.source_id == source_id)).scalar()
    if not approved:
        return None
    return load(source_id).layout or None


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
                arrived_at: datetime | None = None, strict: bool = True) -> dict:
    """Attach one arriving file to its set; queue the set's batch when the set becomes ready. strict=False
    (unattended arrivals) records a batch that cannot be sequenced as failed, like create_batch(strict=False)."""
    from ..ingestion.parser import estimate_rows
    from ..pipeline.batch import file_sha256
    from ..storage import local_path

    cfg = _config(source_id)
    layout, readiness = cfg.layout, cfg.readiness or {}
    if role is not None:
        captured = _captures(layout, role, filename)
    else:
        routed = route_file(layout, filename)
        if routed is None:
            raise FileSetError(f"'{Path(str(filename)).name}' does not match any file in the feed layout")
        role, captured = routed
    now = _naive_utc(arrived_at)
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
        try:
            batch_id = create_batch_for_set(set_id, actor, strict=strict)
            status = "consumed"
        except SetNotReadyError:  # queued (or discarded) by another worker meanwhile: report what it is now
            with db.get_engine().connect() as c:
                now_set = c.execute(select(fs.c.status, fs.c.batch_id).where(fs.c.set_id == set_id)).first()
            status, batch_id = now_set.status, now_set.batch_id
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
        return _evaluate(c, s, cfg, _naive_utc(now))


SAFE_TEXT_ERRORS = (FileSetError, DuplicateFileError)


def _safe_message(e: Exception) -> str:
    """Error text safe to store and alert on. Only our own errors (FileSetError, DuplicateFileError), which
    carry identifiers only, keep their text; any other error (a DeliveryError can quote a column value, a
    database error its parameters) is reduced to its class name and a fixed phrase."""
    if isinstance(e, SAFE_TEXT_ERRORS):
        return f"{e.__class__.__name__}: {(str(e).splitlines() or [''])[0]}"[:300]
    return f"{e.__class__.__name__}: details withheld (may contain data values)"


safe_message = _safe_message  # for intake callers (scheduler, API, S3 arrival)


def _merge_override(set_id: str, patch: dict) -> dict:
    """Merge keys into file_sets.override (never replace it) in its own committed transaction."""
    fs = db.file_sets
    with db.get_engine().begin() as c:
        s = c.execute(select(fs.c.source_id).where(fs.c.set_id == set_id)).first()
        if s is not None:
            _lock_source(c, s.source_id)
        cur = c.execute(select(fs.c.override).where(fs.c.set_id == set_id).with_for_update()).scalar() or {}
        merged = {**cur, **patch}
        c.execute(fs.update().where(fs.c.set_id == set_id).values(override=merged))
        return cur


def _record_error(set_id: str, stage: str, e: Exception, now: datetime) -> bool:
    """Record a failure on the set (override.error), audit and log it. True when it was not alerted before."""
    msg = _safe_message(e)
    log.warning("file set %s: %s failed: %s", set_id, stage, msg)
    try:
        prev = _merge_override(set_id, {"error": {"at": now.isoformat(), "stage": stage, "message": msg}})
        with db.get_engine().begin() as c:
            db.audit(c, "scheduler", "file_set.error", "file_set", set_id, {"stage": stage, "message": msg})
        return not (prev.get("error_alerted") or {}).get(stage)
    except Exception:  # noqa: BLE001 - recording must never stop the sweep
        log.exception("could not record the error of file set %s", set_id)
        return False


def _expire_one(set_id: str, source_id: str, now: datetime):
    """Apply the timeout to one waiting set (once). Returns the alert to send, or None when not handled."""
    try:
        cfg = _config(source_id)
    except FileSetError as e:
        log.warning("file set %s: timeout skipped, feed %s configuration did not load (%s)", set_id, source_id, e.__class__.__name__)
        return None
    layout, readiness = cfg.layout, cfg.readiness or {}
    policy = readiness.get("on_timeout") or "alert_only"
    fs = db.file_sets
    with db.get_engine().begin() as c:
        _lock_source(c, source_id)
        s = c.execute(select(fs).where(fs.c.set_id == set_id).with_for_update()).first()
        if s is None or s.status != "waiting" or (s.override or {}).get("timeout"):
            return None
        present = _present(c, set_id)
        missing = _missing(layout, readiness, set(present))
        optional = {f.get("role") for f in layout.get("files") or [] if f.get("role") != "master" and not f.get("required")}
        action = policy
        if policy == "load_master_only" and ("master" not in present or not set(missing) <= optional):
            action = "fail"
        record = {"at": now.isoformat(), "policy": policy, "action": action, "missing_roles": missing}
        vals: dict = {"override": {**(s.override or {}), "timeout": record}}
        if action == "fail":
            vals["status"] = "expired"
        elif action == "load_master_only":  # the batch is queued by the ready-set sweep
            vals.update(status="ready", ready_at=now, members_sha=_members_sha(present))
        c.execute(fs.update().where(fs.c.set_id == set_id, fs.c.status == "waiting").values(**vals))
        db.audit(c, "scheduler", "file_set.timeout", "file_set", set_id, record)
    kind = "delivery_late" if action == "alert_only" else "delivery_missed"
    verb = {"alert_only": "still waiting", "fail": "set expired", "load_master_only": "loading the master file without it"}[action]
    msg = (f"file set {set_id} for feed {source_id} (pairing {s.pairing_key}): missing {', '.join(missing) or 'none'} file "
           f"after {readiness.get('wait_timeout_minutes')} min; {verb}")
    return kind, msg, {"set_id": set_id, "source_id": source_id, "missing_roles": missing, "on_timeout": policy}


def expire_sets(now: datetime | None = None) -> list[str]:
    """See sweep_sets; returns the set_ids whose timeout was handled in this call."""
    return sweep_sets(now)["handled"]


def sweep_sets(now: datetime | None = None) -> dict:
    """Handle waiting sets whose wait_timeout has passed (each once): alert naming the missing role(s), then
    on_timeout: alert_only keeps the set waiting; fail marks it expired; load_master_only queues a batch on
    the files present when every missing role is non-required and the master is present (else expired).
    Then retry every ready set that has no batch (a crash or failure after it became ready). Each set is
    handled in isolation: an error is recorded on that set and the sweep goes on. Returns {"handled": set_ids
    whose timeout was handled in this call, "batches": batch ids queued by it (the caller starts them)}."""
    from ..scheduling import alerts

    now = _naive_utc(now)
    fs = db.file_sets
    with db.get_engine().connect() as c:
        due = c.execute(select(fs.c.set_id, fs.c.source_id).where(fs.c.status == "waiting", fs.c.expires_at.is_not(None),
                                                                   fs.c.expires_at <= now).order_by(fs.c.expires_at)).all()
    handled: list[str] = []
    queued: list[str] = []
    for set_id, source_id in due:
        try:
            note = _expire_one(set_id, source_id, now)
            if note is None:
                continue
            handled.append(set_id)
            alerts.notify(*note)
        except Exception as e:  # noqa: BLE001 - one set never stops the others
            _record_error(set_id, "timeout", e, now)
    with db.get_engine().connect() as c:
        pending = c.execute(select(fs.c.set_id, fs.c.source_id).where(fs.c.status == "ready", fs.c.batch_id.is_(None))
                            .order_by(fs.c.ready_at)).all()
    for set_id, source_id in pending:
        try:
            queued.append(create_batch_for_set(set_id, "scheduler"))
        except DuplicateFileError:
            continue  # recorded on the set (discarded, duplicate_of) by create_batch_for_set
        except SetNotReadyError:
            continue  # queued or discarded by another worker since we listed it: nothing to do
        except Exception as e:  # noqa: BLE001
            if _record_error(set_id, "batch", e, now):
                try:
                    _merge_override(set_id, {"error_alerted": {"batch": now.isoformat()}})
                    alerts.notify("file_set_error", f"file set {set_id} for feed {source_id} is ready but its batch could not be "
                                                    f"queued: {_safe_message(e)}", {"set_id": set_id, "source_id": source_id})
                except Exception:  # noqa: BLE001
                    log.exception("could not alert on file set %s", set_id)
    return {"handled": handled, "batches": queued}


# ------------------------------------------------------------------ batch
def create_batch_for_set(set_id: str, actor: str, strict: bool = True) -> str:
    """Queue the batch of a ready set, registered on the master file (so the sequencing gate and delivery
    matching see one file). One transaction: the set moves ready -> consumed, the batch is inserted already
    linked to the set, and the members get the batch id; any failure rolls all of it back (set stays ready).
    A set identical (members_sha) to one whose batch is live is marked discarded and DuplicateFileSetError raised.
    A set that is no longer ready raises SetNotReadyError. strict=False: as create_batch(strict=False), a batch
    that cannot be sequenced is recorded as failed with the reason instead of raising."""
    from ..pipeline.batch import _register_batch
    from ..storage import local_path

    fs, bf, bt = db.file_sets, db.batch_files, db.batches
    with db.get_engine().connect() as c:
        s0 = c.execute(select(fs.c.source_id).where(fs.c.set_id == set_id)).first()
        master_path = c.execute(select(bf.c.file_path).where(bf.c.set_id == set_id, bf.c.role == "master")).scalar()
    if s0 is None:
        raise FileSetError("file set not found")
    local = local_path(master_path) if master_path else None  # outside the transaction: may download from S3
    dup = None
    with db.get_engine().begin() as c:
        _lock_source(c, s0.source_id)
        s = c.execute(select(fs).where(fs.c.set_id == set_id).with_for_update()).first()
        if s.status not in ("ready", "overridden") or s.batch_id is not None:
            raise SetNotReadyError(f"file set {set_id} is {s.status}; only a ready set without a batch can be queued")
        members = {r.role: r for r in c.execute(select(bf).where(bf.c.set_id == set_id))}
        master = members.get("master")
        if master is None:
            raise FileSetError(f"file set {set_id} has no master file")
        if master.file_path != master_path:  # replaced since we looked: resolve again
            local = local_path(master.file_path)
        msha = _members_sha({r: m.file_sha256 for r, m in members.items()})
        dup = c.execute(select(bt.c.batch_id, bt.c.created_at).select_from(fs.join(bt, bt.c.batch_id == fs.c.batch_id)).where(
            fs.c.source_id == s.source_id, fs.c.members_sha == msha, fs.c.set_id != set_id,
            bt.c.status.not_in(("failed", "discarded")))).first()
        if dup:
            c.execute(fs.update().where(fs.c.set_id == set_id).values(
                status="discarded", members_sha=msha, override={**(s.override or {}), "duplicate_of": dup.batch_id}))
            db.audit(c, actor, "file_set.duplicate", "file_set", set_id, {"duplicate_of": dup.batch_id, "members_sha": msha})
        else:
            if c.execute(fs.update().where(fs.c.set_id == set_id, fs.c.status == s.status, fs.c.batch_id.is_(None))
                         .values(status="consumed", members_sha=msha)).rowcount != 1:
                raise SetNotReadyError(f"file set {set_id} is already being queued")
            master_dup = c.execute(select(bt.c.batch_id).where(bt.c.source_id == s.source_id, bt.c.file_sha256 == master.file_sha256,
                                                               bt.c.status.not_in(("failed", "discarded")))).first()
            # master_dup with a new members_sha: a correction set whose master file is unchanged (Ruling A)
            bid = _register_batch(c, s.source_id, master.file_path, master.filename, actor, local, master.file_sha256,
                                  bool(master_dup), CORRECTION_REASON if master_dup else None, None, strict, file_set_id=set_id)
            c.execute(bf.update().where(bf.c.set_id == set_id).values(batch_id=bid))
            c.execute(fs.update().where(fs.c.set_id == set_id).values(batch_id=bid))
            db.audit(c, actor, "file_set.batch", "file_set", set_id, {"batch_id": bid, "roles": sorted(members), "members_sha": msha})
    if dup:
        raise DuplicateFileSetError(dup.batch_id, dup.created_at)
    return bid
