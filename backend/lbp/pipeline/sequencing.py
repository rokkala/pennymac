"""Per-vendor ordering of incremental and snapshot files.

Change files must be applied in the order the vendor produced them, otherwise an older balance
overwrites a newer one. Each sequenced batch passes a gate before it may take the processing lease;
gate and lease run in one transaction that first takes a row lock on the source, so two workers
can never both decide "my file is next".

    go            nothing earlier is pending and no gap is open
    wait          an earlier file of this vendor is still pending (queued, running, blocked, failed),
                  or (strict, integer sequences) a sequence number is missing. Status 'waiting';
                  released automatically when the earlier file completes. Ops can skip a gap with a reason.
    stale         the file is older than (or equal to) what is already applied. Status 'out_of_order';
                  an SME discards it, or applies it with every change held for dual control.

Full tapes are not sequenced. The delivery scheduler (scheduling/) is complementary: it counts files
per expected window and alerts when one is late or missing; sequencing guarantees the order they apply in.
"""
from __future__ import annotations

from sqlalchemy import or_, select

from ..store import db
from .delivery import display_sequence, next_integer, profile_of

PENDING = ("queued", "claimed", "running", "pausing", "paused", "waiting", "blocked", "failed")


def is_sequenced(b) -> bool:
    return (b.load_type or "full") != "full" and b.sequence is not None


def gate(c, b) -> dict:
    src = c.execute(select(db.sources).where(db.sources.c.source_id == b.source_id)).first()
    prof = profile_of(src.delivery)
    seq, last = b.sequence, src.last_sequence
    override = (b.sequence_detail or {}).get("override") or {}
    out = {"sequence": display_sequence(seq), "last_applied": display_sequence(last), "checked_at": db.now().isoformat()}
    if last is not None and seq <= last:
        if override.get("type") == "apply_out_of_order":
            return {**out, "decision": "go", "reason": "applied out of order by override (every change held for dual control)"}
        return {**out, "decision": "stale", "reason": f"file sequence {display_sequence(seq)} is not newer than the last applied "
                                                      f"({display_sequence(last)}); applying it could overwrite newer data"}
    bt = db.batches
    conds = [bt.c.source_id == b.source_id, bt.c.batch_id != b.batch_id, bt.c.load_type != "full", bt.c.sequence.is_not(None),
             bt.c.sequence < seq, bt.c.status.in_(PENDING)]
    if last is not None:
        conds.append(bt.c.sequence > last)
    earlier = c.execute(select(bt.c.batch_id, bt.c.sequence, bt.c.status).where(*conds).order_by(bt.c.sequence)).all()
    if earlier:
        e = earlier[0]
        return {**out, "decision": "wait", "waiting_for_batch": e.batch_id,
                "reason": f"waiting for batch {e.batch_id} (sequence {display_sequence(e.sequence)}, {e.status}) to finish first"}
    if override.get("type") == "skip_gap":
        return {**out, "decision": "go", "reason": f"gap skipped by {override.get('actor')}: {override.get('reason')}"}
    s = prof["sequence"]
    if last is not None and s.get("kind") == "integer" and s.get("strict", True) and seq != next_integer(last):
        lo, hi = int(last) + 1, int(seq) - 1
        missing = [str(n) for n in range(lo, min(hi, lo + 9) + 1)]
        more = f" (+{hi - lo - 9} more)" if hi - lo + 1 > 10 else ""
        return {**out, "decision": "wait", "missing": missing,
                "reason": f"sequence gap: waiting for file(s) {', '.join(missing)}{more} before {display_sequence(seq)}"}
    return {**out, "decision": "go", "reason": "next in sequence"}


def acquire(batch_id: str, worker_id: str, lease_from: tuple[str, ...]) -> tuple[bool, dict | None]:
    """Gate (sequenced batches) + lease, atomically. Returns (leased, gate_result)."""
    bt = db.batches
    with db.get_engine().begin() as c:
        b = c.execute(select(bt).where(bt.c.batch_id == batch_id)).first()
        if b is None or b.status not in lease_from + ("waiting", "out_of_order"):
            return False, None
        g = None
        if is_sequenced(b):
            # write-first lock on the source row: serialises gate decisions for this vendor
            c.execute(db.sources.update().where(db.sources.c.source_id == b.source_id).values(seq_lock_at=db.now()))
            g = gate(c, b)
            if g["decision"] != "go":
                status = "waiting" if g["decision"] == "wait" else "out_of_order"
                detail = {**(b.sequence_detail or {}), "gate": g}
                c.execute(bt.update().where(bt.c.batch_id == batch_id).values(status=status, sequence_detail=detail, error=g["reason"],
                                                                              worker_id=None))
                if b.status != status:
                    db.audit(c, "pipeline", f"batch.sequence_{status}", "batch", batch_id, {"reason": g["reason"]})
                return False, g
            c.execute(bt.update().where(bt.c.batch_id == batch_id).values(sequence_detail={**(b.sequence_detail or {}), "gate": g}))
        res = c.execute(bt.update().where(bt.c.batch_id == batch_id, bt.c.status.in_(lease_from + ("waiting", "out_of_order")))
                        .values(status="running", worker_id=worker_id, heartbeat_at=db.now(), error=None))
        return res.rowcount == 1, g


def advance(c, b) -> list[str]:
    """After a sequenced batch completes: move the vendor's cursor forward and release waiting files."""
    if not is_sequenced(b):
        return []
    s = db.sources
    c.execute(s.update().where(s.c.source_id == b.source_id, or_(s.c.last_sequence.is_(None), s.c.last_sequence < b.sequence))
              .values(last_sequence=b.sequence))
    return release_waiting(c, b.source_id)


def release_waiting(c, source_id: str) -> list[str]:
    bt = db.batches
    ids = [r[0] for r in c.execute(select(bt.c.batch_id).where(bt.c.source_id == source_id, bt.c.status == "waiting")
                                   .order_by(bt.c.sequence))]
    if ids:
        c.execute(bt.update().where(bt.c.batch_id.in_(ids)).values(status="queued", error=None))
    return ids


class SequenceActionError(ValueError):
    pass


def _load(c, batch_id):
    b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id).with_for_update()).first()
    if not b:
        raise SequenceActionError("batch not found")
    return b


def skip_gap(batch_id: str, actor: str, roles: list[str], reason: str) -> None:
    if not set(roles) & {"ops", "sme", "admin"}:
        raise SequenceActionError("Ops or SME role required")
    if not reason:
        raise SequenceActionError("a reason is required")
    with db.get_engine().begin() as c:
        b = _load(c, batch_id)
        if b.status != "waiting":
            raise SequenceActionError("only a waiting batch can skip a gap")
        g = (b.sequence_detail or {}).get("gate") or {}
        if g.get("waiting_for_batch"):
            raise SequenceActionError(f"this file waits for batch {g['waiting_for_batch']}, which arrived earlier; finish or discard that "
                                      "batch first (skipping would apply files out of order)")
        det = {**(b.sequence_detail or {}), "override": {"type": "skip_gap", "actor": actor, "reason": reason, "ts": db.now().isoformat(),
                                                         "skipped": g.get("missing") or g.get("missing_deliveries")}}
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(status="queued", sequence_detail=det, error=None))
        db.audit(c, actor, "batch.sequence_skip_gap", "batch", batch_id, {"reason": reason, "skipped": det["override"]["skipped"]})


def apply_out_of_order(batch_id: str, actor: str, roles: list[str], reason: str) -> None:
    if not set(roles) & {"sme", "compliance", "admin"}:
        raise SequenceActionError("SME or Compliance role required")
    if not reason:
        raise SequenceActionError("a reason is required")
    with db.get_engine().begin() as c:
        b = _load(c, batch_id)
        if b.status != "out_of_order":
            raise SequenceActionError("batch is not out of order")
        det = {**(b.sequence_detail or {}), "override": {"type": "apply_out_of_order", "actor": actor, "reason": reason,
                                                         "ts": db.now().isoformat()}}
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(status="queued", sequence_detail=det, error=None))
        db.audit(c, actor, "batch.sequence_apply_out_of_order", "batch", batch_id, {"reason": reason})


def discard(batch_id: str, actor: str, roles: list[str], reason: str) -> list[str]:
    """Drop a file that has not loaded anything (bad resend, superseded). Releases files waiting behind it."""
    if not set(roles) & {"ops", "sme", "admin"}:
        raise SequenceActionError("Ops or SME role required")
    if not reason:
        raise SequenceActionError("a reason is required")
    with db.get_engine().begin() as c:
        b = _load(c, batch_id)
        if b.status not in ("waiting", "out_of_order", "blocked", "queued", "failed"):
            raise SequenceActionError(f"cannot discard a batch in status {b.status}")
        if (b.checkpoint or 0) > 0:
            raise SequenceActionError("this batch has already applied rows; it cannot be discarded (replay or resolve instead)")
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(status="discarded", error=f"discarded: {reason}",
                                                                                      finished_at=db.now()))
        db.audit(c, actor, "batch.discard", "batch", batch_id, {"reason": reason})
        return release_waiting(c, b.source_id)
