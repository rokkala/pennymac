"""Micro-batch boarding pipeline: parse -> map/transform -> validate -> triage -> load.

* Files are streamed and cut into micro-batches (default 10K rows, configurable 10K-50K).
* Transform + rule evaluation (CPU-bound) runs in a process pool; the parent process owns
  all writes, so SQLite works locally and RDS sees a bounded number of connections.
* A checkpoint is committed after each micro-batch; a failed or paused batch resumes from
  the last checkpoint without re-loading rows.
* T1 fixes are applied in-line and the loan re-validated, so clean-after-fix loans board in
  the same pass. Everything else is routed to the Exception Manager.
* Reconciliation at the end proves source = boarded + held + rejected.

In AWS the same `process_chunk` function runs inside the Glue job (mapInPandas) or the ECS
worker, orchestrated by Step Functions (see aws/).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path

from sqlalchemy import func, or_, select

from ..config import get_settings
from ..exceptions.manager import Triage, _str
from ..ingestion.parser import ParseOptions, estimate_rows, iter_rows, read_sample
from ..ingestion.pii import TARGET_PII_TYPES, mask_value
from ..mapping.transforms import compile_mapping
from ..rules.executor import RuleExecutor
from ..rules.registry import RuleRegistry
from ..store import db
from .delivery import norm
from .loader import load_records

log = logging.getLogger(__name__)

_running: dict[str, threading.Thread] = {}


# ---------------------------------------------------------------- worker side (pure)
_W_CACHE: dict = {}


def _worker_ctx(cache_key, fields, runtime_set):
    """Compile mapping + rules once per worker process per (mapping version, rule set)."""
    from ..rules.schema_checks import covered_by_rules

    ctx = _W_CACHE.get(cache_key)
    if ctx is None:
        _W_CACHE.clear()
        ctx = (compile_mapping(fields), RuleExecutor(runtime_set), covered_by_rules(runtime_set))
        _W_CACHE[cache_key] = ctx
    return ctx


def incremental_context(b, cfg) -> tuple[dict, object]:
    """Per-batch context for change files (from the published feed configuration): effective profile,
    file-level action, the vendor's feeds, loan-number key mapper."""
    from .delivery import file_action, profile_of

    profile = profile_of(cfg.delivery)
    profile["load_type"] = b.load_type
    if ((b.sequence_detail or {}).get("override") or {}).get("type") == "apply_out_of_order":
        profile["_protect_all"] = True
    return {"profile": profile, "file_action": file_action(profile, b.filename), "vendor_feeds": list(cfg.vendor_feeds)}, \
        compile_mapping([f for f in cfg.fields if f.get("target") == "loan_number"])


def with_current(incr_base: dict, key_mapper, rows: list[dict]) -> dict:
    """Attach the live SSE records of the loans in this chunk (fetched just before the chunk is processed),
    and the values already corrected on them (so a re-sent defect does not undo a correction)."""
    from .changes import current_rows

    nums = [key_mapper(r)[0].get("loan_number") for r in rows]
    with db.get_engine().connect() as c:
        cur = current_rows(c, nums)
        corr: dict[str, dict] = {}
        ex = db.exceptions
        keys = sorted(cur)
        for i in range(0, len(keys), 900):
            for ln, f, orig in c.execute(select(ex.c.loan_number, ex.c.field, ex.c.original_value).where(
                    ex.c.loan_number.in_(keys[i:i + 900]), ex.c.status.in_(("resolved", "auto_applied")), ex.c.original_value.is_not(None),
                    ex.c.rule_id.not_in(("CHG01", "CHG02", "CHG03", "CHG04", "CHG05", "CHG06", "ACT01", "DUP01", "DUP02")))):
                corr.setdefault(ln, {})[f] = orig
    return {**incr_base, "current": cur, "corrections": corr}


def _fails_of(ev, terrs) -> list[dict]:
    return [{"rule_id": f.rule_id, "version": f.version, "name": f.name, "field": f.field, "category": f.category,
             "severity": f.severity, "message": f.error or f.message, "regulatory_tag": f.regulatory_tag}
            for f in ev.failures if f.field not in terrs]


def _status_of(fails, terrs) -> str:
    if terrs or any(f["severity"] == "FAIL" for f in fails):
        return "FAIL"
    return "WARN" if fails else "PASS"


def process_chunk(rows: list[dict], fields: list[dict], runtime_set: dict, start_row: int, fields_key: str = "",
                  incr: dict | None = None) -> list[dict]:
    """Map + validate one micro-batch. With `incr` (incremental / snapshot loads) each row is first
    planned against the loan's current SSE record: incr = {profile, file_action, current: {loan: row}}."""
    from ..rules.schema_checks import schema_violations
    from .incremental import feeds_by_column, plan_row, preexisting_filter

    mapper, executor, covered = _worker_ctx(fields_key, fields, runtime_set)
    clear_token = (incr or {}).get("profile", {}).get("clear_token") if incr else None
    feeds = feeds_by_column(fields) if clear_token else {}
    out = []
    for i, raw in enumerate(rows):
        clear_targets: set[str] = set()
        if clear_token:
            for col, v in raw.items():
                if v is not None and str(v).strip() == clear_token:
                    raw = {**raw, col: ""}
                    clear_targets |= set(feeds.get(col, []))
        rec, terrs = mapper(raw)
        plan = None
        if incr is not None:
            ln = rec.get("loan_number")
            plan = plan_row(raw, rec, terrs, incr["current"].get(str(ln)) if ln not in (None, "") else None,
                            incr["profile"], incr.get("file_action"), clear_targets, incr.get("corrections"), incr.get("vendor_feeds"))
            rec = plan["record"]
        row = {"row": start_row + i, "raw": raw, "record": rec, "terrs": terrs, "shadow": []}
        if plan is not None:
            row.update(action=plan["action"], changes=plan["changes"], base_version=plan["base_version"],
                       delta_fields=plan["delta_fields"], base_values=plan["base_values"], close_reason=plan["close_reason"],
                       preexisting=0, set_once_ignored=plan["set_once_ignored"], corrections_kept=plan["corrections_kept"])
            if plan["action"] == "unchanged":
                out.append({**row, "status": "UNCHANGED", "fails": [], "terrs": {}})
                continue
            if plan["skip_rules"]:
                out.append({**row, "status": _status_of(plan["fails"], terrs), "fails": plan["fails"]})
                continue
        ev = executor.evaluate(rec)
        fails = _fails_of(ev, terrs)
        if plan is not None and plan["action"] == "update" and any(f["severity"] == "FAIL" for f in fails):
            base = incr["current"][str(rec.get("loan_number"))]
            base_ev = executor.evaluate({k: v for k, v in base.items() if not k.startswith("lbp_")})
            fails, row["preexisting"] = preexisting_filter(fails, {(f.rule_id, f.field) for f in base_ev.failures}, plan["delta_fields"])
        failed_fields = {f["field"] for f in fails} | set(terrs)
        check_fields = set(plan["delta_fields"]) if plan is not None and plan["action"] == "update" else None
        for v in schema_violations(rec, covered):
            if v["field"] not in failed_fields and (check_fields is None or v["field"] in check_fields):
                fails.append({"rule_id": "SCHEMA", "version": 1, "name": "SSE schema constraint", "field": v["field"],
                              "category": "format", "severity": "FAIL", "message": v["message"], "regulatory_tag": None})
        if plan is not None:
            fails = fails + plan["fails"]
        row["shadow"] = ev.shadow_diffs
        out.append({**row, "status": _status_of(fails, terrs), "fails": fails})
    return out


# ---------------------------------------------------------------- parent side
def _chunks(it, size):
    buf = []
    for r in it:
        buf.append(r)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def _mask_raw(raw: dict, pii_cols: dict[str, str]) -> dict:
    return {k: (mask_value(v, pii_cols[k]) if k in pii_cols and v else v) for k, v in raw.items()}


class DuplicateFileError(ValueError):
    def __init__(self, batch_id: str, when):
        super().__init__(f"this exact file was already submitted for this source as batch {batch_id} ({when:%Y-%m-%d %H:%M} UTC). "
                         "Re-submit only with a reason (allow_duplicate).")
        self.batch_id = batch_id


def file_sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def create_batch(source_id: str, file_path: Path, filename: str, actor: str, allow_duplicate: bool = False,
                 reason: str | None = None, load_type: str | None = None, strict: bool = True) -> str:
    """Register an arriving file. With strict=False (unattended S3/scheduler arrivals) a file that cannot be
    sequenced is still recorded, as a failed batch with the reason, so nothing disappears silently."""
    from ..storage import local_path
    from .delivery import LOAD_TYPES, DeliveryError, display_sequence, extract_sequence, file_action, profile_of

    local = local_path(file_path)
    digest = file_sha256(local)
    with db.get_engine().begin() as c:
        src = c.execute(select(db.sources).where(db.sources.c.source_id == source_id)).first()
        if not src:
            raise ValueError("unknown source")
        if not src.active_mapping_id:
            raise ValueError("source has no approved mapping; complete onboarding first")
        prior = c.execute(select(db.batches.c.batch_id, db.batches.c.created_at).where(
            db.batches.c.source_id == source_id, db.batches.c.file_sha256 == digest,
            db.batches.c.status.not_in(("failed", "discarded")))).first()
        if prior and not allow_duplicate:
            raise DuplicateFileError(prior.batch_id, prior.created_at)
        if prior and not reason:
            raise ValueError("a reason is required to re-submit an identical file")
        prof = profile_of(src.delivery)
        lt = load_type or prof["load_type"]
        problem, seq = None, None
        vstatus = c.execute(select(db.vendors.c.status, db.vendors.c.name).where(db.vendors.c.vendor_id == src.vendor_id)).first()
        try:
            if vstatus and vstatus.status in ("suspended", "offboarded"):
                raise DeliveryError(f"vendor {vstatus.name} is {vstatus.status}; its files are recorded but not processed")
            if lt not in LOAD_TYPES:
                raise DeliveryError(f"load_type must be one of {', '.join(LOAD_TYPES)}")
            if lt == "incremental" and prof["action"].get("mode") == "filename" and not file_action(prof, filename):
                raise DeliveryError(f"'{filename}' does not match any add/update/close filename pattern for this vendor")
            if lt != "full":
                first = None
                if prof["sequence"].get("source") == "column":
                    _, rows = read_sample(local, 1, ParseOptions(**(src.parse_options or {})))
                    first = rows[0] if rows else None
                seq = extract_sequence(prof, filename, first)
                if seq is not None:
                    clash = c.execute(select(db.batches.c.batch_id).where(
                        db.batches.c.source_id == source_id, db.batches.c.sequence == seq, db.batches.c.load_type != "full",
                        db.batches.c.status.not_in(("failed", "discarded", "completed")))).first()
                    if clash:
                        raise DeliveryError(f"a file with sequence {display_sequence(seq)} is already pending as batch {clash.batch_id}; "
                                            "discard it first if this file replaces it")
        except DeliveryError as e:
            if strict:
                raise
            problem = str(e)
        bid = db.new_id("bat")
        c.execute(db.batches.insert().values(batch_id=bid, source_id=source_id, mapping_id=src.active_mapping_id, filename=filename,
                                             file_path=str(file_path), status="failed" if problem else "queued", submitted_by=actor,
                                             micro_batches=[], file_sha256=digest, total_rows=estimate_rows(local),
                                             load_type=lt if lt in LOAD_TYPES else "full", sequence=seq, error=problem))
        from ..scheduling.service import match_arrival

        delivery_id = match_arrival(c, source_id, bid, filename)
        db.audit(c, actor, "batch.create", "batch", bid, {"file": filename, "source_id": source_id, "sha256": digest, "load_type": lt,
                                                           "sequence": display_sequence(seq), "delivery_id": delivery_id,
                                                           **({"rejected": problem} if problem else {}),
                                                           **({"duplicate_of": prior.batch_id, "reason": reason} if prior else {})})
    return bid


class BatchBusyError(RuntimeError):
    pass


LEASE_FROM = ("queued", "claimed", "paused", "failed", "blocked")
STALE_AFTER_MINUTES = 10


def _acquire_lease(batch_id: str, worker_id: str) -> bool:
    """Atomically move a batch into 'running' for one worker. False if another worker holds it."""
    with db.get_engine().begin() as c:
        res = c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id, db.batches.c.status.in_(LEASE_FROM))
                        .values(status="running", worker_id=worker_id, heartbeat_at=db.now()))
        return res.rowcount == 1


def recover_stale(minutes: int = STALE_AFTER_MINUTES) -> list[str]:
    """Requeue batches whose worker stopped heart-beating (crash, OOM, deploy). They resume from checkpoint."""
    from datetime import timedelta

    cutoff = db.now() - timedelta(minutes=minutes)
    with db.get_engine().begin() as c:
        stale = [r[0] for r in c.execute(select(db.batches.c.batch_id).where(
            db.batches.c.status.in_(("running", "pausing")), db.batches.c.heartbeat_at < cutoff,
            # Step Functions executions own their batches (retries, timeouts, MarkFailed); never requeue them
            ~func.coalesce(db.batches.c.worker_id, "").like("sfn:%")))]
        for bid in stale:
            c.execute(db.batches.update().where(db.batches.c.batch_id == bid).values(status="queued", worker_id=None))
            db.audit(c, "pipeline", "batch.recovered", "batch", bid, {"reason": f"no heartbeat for {minutes} min"})
    return stale


def override_preflight(batch_id: str, actor: str, roles: list[str], reason: str) -> None:
    """An SME/Compliance user accepts the drift risk and lets a blocked batch run on the current mapping."""
    if not set(roles) & {"sme", "compliance", "admin"}:
        raise ValueError("SME or Compliance role required to override a drift block")
    if not reason:
        raise ValueError("a reason is required")
    with db.get_engine().begin() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
        if not b or b.status != "blocked":
            raise ValueError("batch is not blocked")
        pf = {**(b.preflight or {}), "override": {"actor": actor, "reason": reason, "ts": db.now().isoformat()}}
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(preflight=pf, status="queued"))
        db.audit(c, actor, "batch.preflight_override", "batch", batch_id, {"reason": reason})


def _run_and_follow(batch_id: str) -> None:
    """In-process runner (local API mode): run the batch, then any files it released from waiting."""
    try:
        res = run_batch(batch_id)
    except BatchBusyError:
        return
    except Exception:  # noqa: BLE001 - recorded on the batch by run_batch
        return
    for nxt in res.get("released", []):
        start_batch_async(nxt)


def start_batch_async(batch_id: str) -> None:
    if batch_id in _running and _running[batch_id].is_alive():
        return
    t = threading.Thread(target=_run_and_follow, args=(batch_id,), daemon=True, name=f"batch-{batch_id}")
    _running[batch_id] = t
    t.start()


def request_pause(batch_id: str, actor: str) -> None:
    with db.get_engine().begin() as c:
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(status="pausing"))
        db.audit(c, actor, "batch.pause", "batch", batch_id)


def _safe_error(e: Exception) -> str:
    """Error text for storage/UI: first line only, never the SQL parameters (they can contain NPI)."""
    msg = str(getattr(e, "orig", None) or e).splitlines()[0] if str(e) else e.__class__.__name__
    return f"{e.__class__.__name__}: {msg}"[:1000]


def run_batch(batch_id: str, workers: int | None = None, micro_batch_size: int | None = None) -> dict:
    s = get_settings()
    workers = workers or s.workers
    size = micro_batch_size or s.micro_batch_size
    eng = db.get_engine()
    from ..config_store import ConfigError
    from ..config_store import load as load_config

    with eng.connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
        if b is None:
            raise ValueError("unknown batch")
        active = c.execute(select(db.sources.c.active_mapping_id).where(db.sources.c.source_id == b.source_id)).scalar()
    # The data plane reads only the feed's published (approved, signed) configuration, never the live tables.
    try:
        cfg = load_config(b.source_id)
        if active and cfg.mapping_id != active:
            raise ConfigError(f"published configuration (mapping v{cfg.mapping_version}) is behind the approved mapping; republish the feed")
    except ConfigError as e:
        with eng.begin() as c:
            c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(status="failed", error=f"configuration: {e}"))
            db.audit(c, "pipeline", "batch.config_rejected", "batch", batch_id, {"error": str(e)})
        raise
    if cfg.mapping_id != b.mapping_id:
        # resuming a drift-blocked batch (or one queued before a new version) runs on the newest published mapping
        with eng.begin() as c:
            c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(mapping_id=cfg.mapping_id))
            b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
    import os
    import socket

    from . import sequencing

    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    if b.status == "running":
        raise BatchBusyError(f"batch {batch_id} is already being processed")
    leased, g = sequencing.acquire(batch_id, worker_id, LEASE_FROM)
    if not leased:
        if g and g["decision"] != "go":
            return {"batch_id": batch_id, "status": "waiting" if g["decision"] == "wait" else "out_of_order", "sequence": g}
        raise BatchBusyError(f"batch {batch_id} is already being processed")
    # ---- schema-drift pre-flight (first run, or the mapping changed since the last check)
    pf = b.preflight or {}
    if (b.checkpoint or 0) == 0 and not pf.get("override") and (pf.get("mapping_id") != cfg.mapping_id or pf.get("decision") == "block"):
        from ..storage import local_path
        from .preflight import check_file

        pf = {**check_file(local_path(b.file_path), cfg.parse_options, cfg.profile, cfg.fields, sparse=(b.load_type == "incremental"),
                           delivery=cfg.delivery), "mapping_id": cfg.mapping_id, "mapping_version": cfg.mapping_version,
              "config_version": cfg.version, "checked_at": db.now().isoformat()}
        with eng.begin() as c:
            c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(preflight=pf))
            db.audit(c, "pipeline", f"batch.preflight_{pf['decision']}", "batch", batch_id, {"summary": pf["summary"]})
        if pf["decision"] == "block":
            with eng.begin() as c:
                c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(status="blocked", error=pf["summary"],
                                                                                              worker_id=None))
            return {"batch_id": batch_id, "status": "blocked", "preflight": pf}
    with eng.begin() as c:
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id)
                  .values(started_at=b.started_at or db.now(), error=None))
    fields = cfg.fields
    runtime_set = cfg.runtime_set
    fields_key = f"{cfg.mapping_id}:{cfg.mapping_version}|{cfg.rules_key}"
    pii_cols = cfg.pii_cols
    triage = Triage()
    triage.runtime_set = runtime_set
    checkpoint = b.checkpoint or 0
    micro = list(b.micro_batches or [])
    counters = {"processed": b.processed or 0, "passed": b.passed or 0, "warned": b.warned or 0, "failed": b.failed or 0,
                "loaded": b.loaded or 0}
    t_start = time.monotonic()
    rows_this_run = 0
    opts = ParseOptions(**(cfg.parse_options or {}))
    incremental = (b.load_type or "full") != "full"
    change_acc = dict(b.change_summary or {}) if incremental else None
    incr_base, key_mapper = incremental_context(b, cfg) if incremental else (None, None)
    with eng.begin() as c:
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(
            sequence_detail={**(b.sequence_detail or {}), "config": {"version": cfg.version, "sha256": cfg.sha256[:16]}}))
    try:
        from ..storage import local_path

        _, it = iter_rows(local_path(b.file_path), opts)
        # skip already-checkpointed rows
        for _ in range(checkpoint):
            next(it, None)
        pool = ProcessPoolExecutor(max_workers=workers) if workers > 1 else None
        pending: deque[tuple[int, Future | list]] = deque()
        row_cursor = checkpoint
        chunk_iter = _chunks(it, size)
        exhausted = False
        paused = False

        def submit_next():
            nonlocal row_cursor, exhausted
            chunk = next(chunk_iter, None)
            if chunk is None:
                exhausted = True
                return
            start = row_cursor
            row_cursor += len(chunk)
            incr = with_current(incr_base, key_mapper, chunk) if incremental else None
            if pool:
                pending.append((start, pool.submit(process_chunk, chunk, fields, runtime_set, start, fields_key, incr)))
            else:
                pending.append((start, process_chunk(chunk, fields, runtime_set, start, fields_key, incr)))

        for _ in range(max(2, workers * 2)):
            submit_next()
        mb_index = len(micro)
        while pending:
            start, fut = pending.popleft()
            t0 = time.monotonic()
            results = fut.result() if isinstance(fut, Future) else fut
            if not exhausted:
                submit_next()
            def progress(c, stats, _start=start, _n=len(results), _t0=t0):
                # runs inside the same transaction as the staged rows: checkpoint and data commit together
                nonlocal rows_this_run, checkpoint, mb_index
                rows_this_run += _n
                checkpoint = _start + _n
                elapsed = max(time.monotonic() - t_start, 1e-6)
                micro.append({"index": mb_index, "start_row": _start, "rows": _n, "seconds": round(time.monotonic() - _t0, 3), **stats})
                mb_index += 1
                extra = {"change_summary": dict(change_acc)} if change_acc is not None else {}
                c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id, db.batches.c.worker_id == worker_id).values(
                    checkpoint=checkpoint, micro_batches=micro[-500:], throughput_lps=round(rows_this_run / elapsed, 1),
                    heartbeat_at=db.now(), **extra, **counters))

            _persist_chunk(batch_id, b.source_id, results, triage, pii_cols, counters, progress, change_acc)
            with eng.connect() as c:
                cur = c.execute(select(db.batches.c.status).where(db.batches.c.batch_id == batch_id)).scalar()
            if cur == "pausing":
                paused = True
                break
        if pool:
            pool.shutdown(wait=not paused, cancel_futures=paused)
        released: list[str] = []
        if not paused and b.load_type == "snapshot":
            snap = snapshot_missing(batch_id, b.source_id, incr_base["profile"], triage, cfg.vendor_feeds)
            change_acc["snapshot"] = snap
        with eng.begin() as c:
            if paused:
                c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(status="paused", worker_id=None))
            else:
                rec = reconcile(c, batch_id, counters["processed"])
                c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(
                    status="completed", total_rows=counters["processed"], finished_at=db.now(), reconciliation=rec, worker_id=None,
                    **({"change_summary": dict(change_acc)} if change_acc is not None else {})))
                db.audit(c, "pipeline", "batch.completed", "batch", batch_id, {**counters, "reconciliation": rec,
                                                                                **({"changes": change_acc} if change_acc else {})})
                released = sequencing.advance(c, b)
                if released:
                    db.audit(c, "pipeline", "batch.sequence_released", "batch", batch_id, {"released": released})
    except Exception as e:  # noqa: BLE001
        log.error("batch %s failed: %s", batch_id, _safe_error(e))  # no traceback args: SQL params can hold NPI
        with eng.begin() as c:
            c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(status="failed", error=_safe_error(e), worker_id=None))
            db.audit(c, "pipeline", "batch.failed", "batch", batch_id, {"error": _safe_error(e)[:500], "checkpoint": checkpoint})
        raise
    return {"batch_id": batch_id, **counters, "seconds": round(time.monotonic() - t_start, 2), "released": released,
            **({"changes": change_acc} if change_acc is not None else {})}


DUP_RULES = {
    "DUP01": "Duplicate loan number in this file",
    "DUP02": "Loan already exists in SSE",
}


def detect_duplicates(batch_id: str, results: list[dict], check_in_batch: bool = True) -> int:
    """Flag in-file duplicates (DUP01) and loans already boarded by another batch (DUP02).

    Without this, the SSE upsert would silently overwrite a live loan when a seller re-sends a tape.
    Both route to dual control (loan_number is a high-risk identity field): a person decides whether
    the incoming record is an update of the boarded loan or a bad row.
    """
    nums = sorted({str(r["record"].get("loan_number")) for r in results if r["record"].get("loan_number")})
    if not nums:
        return 0
    st, sse = db.loans_staging, db.sse_loans
    prior, existing = set(), {}
    with db.get_engine().connect() as c:
        for i in range(0, len(nums), 900):
            part = nums[i:i + 900]
            if check_in_batch:
                prior |= {x for (x,) in c.execute(select(st.c.loan_number).where(st.c.batch_id == batch_id, st.c.loan_number.in_(part)))}
            for ln, bid, at in c.execute(select(sse.c.loan_number, sse.c.lbp_batch_id, sse.c.lbp_boarded_at)
                                         .where(sse.c.loan_number.in_(part), sse.c.lbp_batch_id != batch_id)):
                existing[ln] = (bid, at)
        names = dict(c.execute(select(db.batches.c.batch_id, db.sources.c.name)
                               .join(db.sources, db.sources.c.source_id == db.batches.c.source_id)
                               .where(db.batches.c.batch_id.in_([v[0] for v in existing.values()] or ["-"]))).all())
    seen, flagged = set(), 0
    for r in results:
        ln = r["record"].get("loan_number")
        if not ln:
            continue
        ln = str(ln)
        dup = None
        if check_in_batch and (ln in seen or ln in prior):
            dup = ("DUP01", f"Loan number {ln} appears more than once in this file")
        elif ln in existing and r.get("action") in (None, "add"):
            bid, at = existing[ln]
            dup = ("DUP02", f"Loan {ln} was already boarded from {names.get(bid, bid)} ({bid}) on {at:%Y-%m-%d %H:%M}. "
                            "Approve only if this file is a legitimate update of that loan.")
        seen.add(ln)
        if dup:
            r["fails"] = [f for f in r["fails"] if f["rule_id"] not in DUP_RULES] + [{
                "rule_id": dup[0], "version": 1, "name": DUP_RULES[dup[0]], "field": "loan_number", "category": "duplicate",
                "severity": "FAIL", "message": dup[1], "regulatory_tag": "SOX"}]
            r["status"] = "FAIL"
            flagged += 1
    return flagged


def _triage_results(results, triage: Triage):
    """Classify/propose/route every failure; apply T1 fixes and re-validate. Pure (no DB writes)."""
    staged, ex_rows_by_idx = [], {}
    passed = warned = failed = auto_fixed = unchanged = 0
    executor = None
    for idx, r in enumerate(results):
        rec, status = r["record"], r["status"]
        if status == "UNCHANGED":
            unchanged += 1
            staged.append((r, rec, status))
            continue
        exs = []
        for fld, msg in r["terrs"].items():
            if fld in TARGET_PII_TYPES:  # never persist raw NPI inside an error message
                kind = msg.split(":", 1)[0]
                raw_val = msg.split(": ", 1)[-1].strip("'\"") if ": " in msg else ""
                msg = f"{kind}: {mask_value(raw_val, TARGET_PII_TYPES[fld]) if raw_val else '(blank)'}"
            exs.append(triage.classify_and_propose("TRANSFORM", "Transform / type cast failed", "transform", "FAIL", fld, rec, msg))
            exs[-1]["original_value"] = msg.split(": ", 1)[-1] if ": " in msg else msg
        for f in r["fails"]:
            exs.append(triage.classify_and_propose(f["rule_id"], f["name"], f["category"], f["severity"], f["field"], rec,
                                                   f["message"], f["regulatory_tag"]))
            exs[-1]["rule_version"] = f["version"]
            _route_change_rule(exs[-1], rec, r.get("base_values"))
        if exs:
            blocking = [e for e in exs if e["blocking"]]
            t1 = [e for e in exs if e["tier"] == "T1" and e["proposal"]]
            for e in t1:
                rec[e["field"]] = e["proposal"]["value"]
                e["status"] = "auto_applied"
                e["resolved_value"] = _str(e["proposal"]["value"])
                e["maker"] = "ai:auto-apply"
            for e in exs:
                e.setdefault("status", "escalated" if e["tier"] == "T5" else "open")
            if t1 and all(e["status"] == "auto_applied" for e in blocking):
                executor = executor or RuleExecutor(getattr(triage, "runtime_set", None) or RuleRegistry().runtime_set())
                ev = executor.evaluate(rec)
                if not any(f.severity == "FAIL" for f in ev.failures):
                    status = "WARN" if ev.failures or any(not e["blocking"] for e in exs) else "PASS"
                    auto_fixed += 1
            if r.get("action") == "update":
                # judge the change on the *effective* values: a vendor re-sending a defect that was auto-fixed
                # at boarding (e.g. state 'C A' -> 'CA') is not a change once the same fix is applied again
                bv = r.get("base_values") or {}
                live = {f for f in (r.get("delta_fields") or []) if norm(rec.get(f)) != norm(bv.get(f))}
                exs = [e for e in exs if not (e["rule_id"] == "CHG01" and e["field"] not in live)]
                open_block = [e for e in exs if e["blocking"] and e["status"] != "auto_applied"]
                if not live and not open_block:
                    status, exs = "UNCHANGED", []
                elif status == "FAIL" and not open_block:
                    executor = executor or RuleExecutor(getattr(triage, "runtime_set", None) or RuleRegistry().runtime_set())
                    ev = executor.evaluate(rec)
                    if not any(f.severity == "FAIL" for f in ev.failures):
                        status = "WARN" if any(not e["blocking"] for e in exs) else "PASS"
            if exs:
                ex_rows_by_idx[idx] = exs
        if status == "UNCHANGED":
            unchanged += 1
            r["status"] = status
            staged.append((r, rec, status))
            continue
        if status == "PASS":
            passed += 1
        elif status == "WARN":
            warned += 1
        else:
            failed += 1
        r["status"] = status
        staged.append((r, rec, status))
    return staged, ex_rows_by_idx, {"passed": passed, "warned": warned, "failed": failed, "auto_fixed": auto_fixed, "unchanged": unchanged}


def _route_change_rule(e: dict, rec: dict, base_values: dict | None = None) -> None:
    """Change-control routing on top of confidence x risk: a protected-field change always needs a maker
    and a checker (T4, or T5 if the field is critical); the vendor's value is offered as a hint only."""
    from ..exceptions.policy import QUEUES

    if e["rule_id"] == "CHG01" and e["tier"] != "T5":
        e["tier"], e["queue"] = "T4", QUEUES["T4"]
        e["qa_sample"] = False
        val = rec.get(e["field"])
        e["proposal"] = None if val is None else {
            "value": val, "confidence": 0.0, "source": "vendor_change", "fix_kind": "vendor", "hint_only": True,
            "previous": (base_values or {}).get(e["field"]),
            "rationale": "Value sent by the vendor; approve to apply it, or enter the value SSE should keep."}
    elif e["rule_id"] in ("ACT01", "CHG02", "CHG03", "CHG04", "CHG05", "CHG06") and e["tier"] in ("T1", "T2"):
        e["tier"], e["queue"] = "T3", QUEUES["T3"]  # a person decides; never auto-fixed
        e["proposal"] = None


def _exception_rows(batch_id, source_id, ex_rows_by_idx, loan_numbers, staging_ids):
    out = []
    for idx, exs in ex_rows_by_idx.items():
        for e in exs:
            e = dict(e)
            e.pop("regulatory_tag", None)
            out.append({"exception_id": db.new_id("ex"), "batch_id": batch_id, "source_id": source_id,
                        "loan_number": loan_numbers[idx], "staging_id": staging_ids[idx],
                        "resolved_at": db.now() if e["status"] == "auto_applied" else None,
                        "rule_version": e.pop("rule_version", None), "resolved_value": e.pop("resolved_value", None),
                        "maker": e.pop("maker", None), **e})
    return out


def _insert_exceptions(c, rows):
    if rows:
        cols = set().union(*(x.keys() for x in rows))
        c.execute(db.exceptions.insert(), [{k: x.get(k) for k in cols} for x in rows])


def _record_load_rejections(c, batch_id, source_id, rejected, staging_rows, ids, triage):
    """SSE refused these loans at write time: hold them with a LOAD exception instead of failing the batch."""
    by_ln = {s["loan_number"]: (s, i) for s, i in zip(staging_rows, ids, strict=True)}
    rows = []
    for ln, err in rejected:
        s, sid = by_ln.get(ln, (None, None))
        if sid is None:
            continue
        c.execute(db.loans_staging.update().where(db.loans_staging.c.id == sid).values(boarded=False, status="FAIL"))
        e = triage.classify_and_propose("LOAD", "SSE rejected the record", "load", "FAIL", "loan_number", s["record"], f"SSE write rejected: {err}")
        e.pop("regulatory_tag", None)
        e["status"] = "open"
        rows.append({"exception_id": db.new_id("ex"), "batch_id": batch_id, "source_id": source_id, "loan_number": ln, "staging_id": sid, **e})
    _insert_exceptions(c, rows)
    db.audit(c, "pipeline", "batch.load_rejections", "batch", batch_id, {"count": len(rows)})


def _persist_chunk(batch_id, source_id, results, triage: Triage, pii_cols, counters, progress=None, change_acc: dict | None = None) -> dict:
    from .changes import apply_closes, apply_updates, conflict_failures

    dups = detect_duplicates(batch_id, results)
    staged, ex_rows_by_idx, st = _triage_results(results, triage)
    staging_rows = []
    for r, rec, status in staged:
        action = "unchanged" if status == "UNCHANGED" else r.get("action")
        changes = None
        if action == "update":
            bv = r.get("base_values") or {}
            changes = {f: {"old": bv.get(f), "new": rec.get(f)} for f in r.get("delta_fields") or []}
        elif action == "close":
            changes = {"lbp_status": {"old": "active", "new": "closed"}, "close_reason": r.get("close_reason")}
        if status == "UNCHANGED":  # nothing to keep: the SSE record is the truth (snapshots resend millions of these)
            staging_rows.append({"batch_id": batch_id, "row_number": r["row"], "loan_number": _str(rec.get("loan_number")),
                                 "status": status, "record": {}, "raw": None, "transform_errors": {}, "boarded": False,
                                 "action": "unchanged", "changes": None, "base_version": r.get("base_version")})
            continue
        staging_rows.append({"batch_id": batch_id, "row_number": r["row"], "loan_number": _str(rec.get("loan_number")),
                             "status": status, "record": rec, "raw": _mask_raw(r["raw"], pii_cols), "transform_errors": r["terrs"],
                             "boarded": status in ("PASS", "WARN"), "action": action, "changes": changes,
                             "base_version": r.get("base_version")})
    with db.get_engine().begin() as c:
        ids = [row[0] for row in c.execute(db.loans_staging.insert().returning(db.loans_staging.c.id), staging_rows)] if staging_rows else []
        _insert_exceptions(c, _exception_rows(batch_id, source_id, ex_rows_by_idx, [s["loan_number"] for s in staging_rows], ids))
        rejected: list = []
        adds = [(s["record"], s["status"]) for s in staging_rows if s["boarded"] and s["action"] in (None, "add")]
        loaded = load_records(c, adds, batch_id, rejected, source_id=source_id)
        if rejected:
            _record_load_rejections(c, batch_id, source_id, rejected, staging_rows, ids, triage)
            st["failed"] += len(rejected)
            st["passed"] = max(0, st["passed"] - len(rejected))
        upd = [{"idx": i, "staging_id": ids[i], "loan_number": s["loan_number"], "record": s["record"], "changes": s["changes"],
                "base_version": s["base_version"], "dq_status": s["status"]}
               for i, s in enumerate(staging_rows) if s["boarded"] and s["action"] == "update"]
        cls = [{"idx": i, "staging_id": ids[i], "loan_number": s["loan_number"], "close_reason": (s["changes"] or {}).get("close_reason")}
               for i, s in enumerate(staging_rows) if s["boarded"] and s["action"] == "close"]
        applied_u, conflicts_u = apply_updates(c, upd, batch_id, source_id)
        applied_c, conflicts_c = apply_closes(c, cls, batch_id, source_id)
        conflicts = conflicts_u + conflicts_c
        if conflicts:
            ex_rows = []
            for cf in conflicts:
                s = staging_rows[cf["idx"]]
                c.execute(db.loans_staging.update().where(db.loans_staging.c.id == ids[cf["idx"]]).values(boarded=False, status="FAIL"))
                for f in conflict_failures(cf):
                    e = triage.classify_and_propose(f["rule_id"], f["name"], f["category"], "FAIL", f["field"], s["record"], f["message"])
                    _route_change_rule(e, s["record"])
                    if f.get("live") is not None or f.get("vendor") is not None:
                        e["proposal"] = {"value": f.get("live"), "vendor": f.get("vendor"), "previous": f.get("old"), "confidence": 0.0,
                                         "source": "conflict", "fix_kind": "vendor", "hint_only": True,
                                         "rationale": "SSE changed after the vendor produced this file. Keep the SSE value or apply the vendor's."}
                    e.pop("regulatory_tag", None)
                    e["status"] = "escalated" if e["tier"] == "T5" else "open"
                    e["qa_sample"] = False
                    ex_rows.append({"exception_id": db.new_id("ex"), "batch_id": batch_id, "source_id": source_id,
                                    "loan_number": s["loan_number"], "staging_id": ids[cf["idx"]], **e})
            _insert_exceptions(c, ex_rows)
            moved = len(conflicts)
            st["failed"] += moved
            ok_warn = sum(1 for cf in conflicts if staging_rows[cf["idx"]]["status"] == "WARN")
            st["warned"] -= ok_warn
            st["passed"] -= moved - ok_warn
        loaded += len(applied_u) + len(applied_c)
        counters["processed"] += len(results)
        counters["passed"] += st["passed"]
        counters["warned"] += st["warned"]
        counters["failed"] += st["failed"]
        counters["loaded"] += loaded
        stats = {**st, "loaded": loaded, "duplicates": dups, "exceptions": sum(len(v) for v in ex_rows_by_idx.values())}
        if change_acc is not None:
            acts = {}
            for s in staging_rows:
                acts[s["action"] or "add"] = acts.get(s["action"] or "add", 0) + 1
            for k in ("add", "update", "close", "unchanged"):
                change_acc[f"{k}_rows"] = change_acc.get(f"{k}_rows", 0) + acts.get(k, 0)
            change_acc["adds_applied"] = change_acc.get("adds_applied", 0) + (len(adds) - len(rejected))
            change_acc["updates_applied"] = change_acc.get("updates_applied", 0) + len(applied_u)
            change_acc["closes_applied"] = change_acc.get("closes_applied", 0) + len(applied_c)
            change_acc["conflicts"] = change_acc.get("conflicts", 0) + len(conflicts)
            tf = dict(change_acc.get("fields_changed") or {})
            for i in applied_u:  # which fields the applied updates actually changed (explains large update counts)
                for f, ch in (staging_rows[i]["changes"] or {}).items():
                    if isinstance(ch, dict) and norm(ch.get("old")) != norm(ch.get("new")):
                        tf[f] = tf.get(f, 0) + 1
            change_acc["fields_changed"] = dict(sorted(tf.items(), key=lambda kv: -kv[1])[:12])
            change_acc["preexisting_issues"] = change_acc.get("preexisting_issues", 0) + sum(r.get("preexisting", 0) for r in results)
            change_acc["set_once_ignored"] = change_acc.get("set_once_ignored", 0) + sum(r.get("set_once_ignored", 0) for r in results)
            change_acc["corrections_kept"] = change_acc.get("corrections_kept", 0) + sum(r.get("corrections_kept", 0) for r in results)
            stats["changes"] = {k: acts.get(k, 0) for k in ("add", "update", "close", "unchanged")}
        if progress:
            progress(c, stats)
    return stats


def snapshot_missing(batch_id: str, source_id: str, profile: dict, triage: Triage, vendor_feeds: list[str] | None = None) -> dict:
    """Snapshot loads: active loans of this vendor that are absent from the file.

    Absence is not proof of payoff, so each one becomes a CHG04 review (confirm close / keep). If the
    share missing exceeds snapshot.max_missing_pct the file is treated as truncated: no reviews are
    raised, the batch is flagged and an alert is sent, so a half-delivered file cannot close half a portfolio.
    """
    from sqlalchemy import and_, exists

    from ..exceptions.policy import QUEUES
    from ..vendors import siblings
    from .changes import current_rows
    from .incremental import CHANGE_RULES

    sse, st = db.sse_loans, db.loans_staging
    sn = profile["snapshot"]
    with db.get_engine().connect() as c:
        feeds = vendor_feeds or siblings(c, source_id)  # the vendor's whole portfolio, across all its feeds
        if c.execute(select(st.c.id).where(st.c.batch_id == batch_id, st.c.row_number.is_(None)).limit(1)).first():
            return dict((c.execute(select(db.batches.c.change_summary).where(db.batches.c.batch_id == batch_id)).scalar() or {})
                        .get("snapshot") or {"resumed": True})  # already raised before a crash; never twice
        portfolio = c.execute(select(func.count()).select_from(sse).where(sse.c.lbp_source_id.in_(feeds), sse.c.lbp_status == "active")).scalar()
        missing_q = select(sse.c.loan_number).where(sse.c.lbp_source_id.in_(feeds), sse.c.lbp_status == "active", ~exists().where(
            and_(st.c.batch_id == batch_id, st.c.loan_number == sse.c.loan_number)))
        missing = [r[0] for r in c.execute(missing_q)]
    pct = round(len(missing) / portfolio * 100, 2) if portfolio else 0.0
    out = {"portfolio_active": portfolio, "missing": len(missing), "missing_pct": pct, "max_missing_pct": float(sn.get("max_missing_pct", 5)),
           "action": sn.get("missing_action", "review")}
    if not missing or out["action"] == "ignore":
        return out
    if pct > out["max_missing_pct"]:
        out["truncation_suspected"] = True
        with db.get_engine().begin() as c:
            db.audit(c, "pipeline", "batch.snapshot_truncation_suspected", "batch", batch_id, out)
        from ..scheduling.alerts import notify

        notify("snapshot_truncated", f"Snapshot for {source_id} is missing {len(missing)} of {portfolio} active loans ({pct}%)",
               {"batch_id": batch_id, **out})
        return out
    with db.get_engine().begin() as c:
        for i in range(0, len(missing), 900):
            part = missing[i:i + 900]
            cur = current_rows(c, part)
            rows = [{"batch_id": batch_id, "row_number": None, "loan_number": ln, "status": "FAIL", "record": cur[ln], "raw": None,
                     "transform_errors": {}, "boarded": False, "action": "close_inferred",
                     "changes": {"lbp_status": {"old": "active", "new": "closed"}}, "base_version": cur[ln].get("lbp_version")}
                    for ln in part if ln in cur]
            ids = [r[0] for r in c.execute(st.insert().returning(st.c.id), rows)] if rows else []
            ex = []
            for r, sid in zip(rows, ids, strict=True):
                e = triage.classify_and_propose("CHG04", CHANGE_RULES["CHG04"], "change_control", "FAIL", "lbp_status", r["record"],
                                                f"Loan {r['loan_number']} is active in SSE for this vendor but absent from its snapshot. "
                                                "Confirm 'closed' to close it, or reject to keep it active.")
                e.pop("regulatory_tag", None)
                tier = sn.get("missing_review_tier", "T3")
                e.update(tier=tier, queue=QUEUES[tier], status="open", qa_sample=False,
                         proposal={"value": "closed", "confidence": 0.0, "source": "snapshot_absence", "fix_kind": "vendor",
                                   "hint_only": tier in ("T3", "T4"), "rationale": "Absent from the vendor's full snapshot"})
                ex.append({"exception_id": db.new_id("ex"), "batch_id": batch_id, "source_id": source_id, "loan_number": r["loan_number"],
                           "staging_id": sid, **e})
            _insert_exceptions(c, ex)
        out["reviews_raised"] = len(missing)
        db.audit(c, "pipeline", "batch.snapshot_missing", "batch", batch_id, out)
    return out


def summarize_changes(conn, batch_id: str) -> dict:
    """Authoritative change counts from the database (used where chunks run in parallel, e.g. Step Functions)."""
    st, lc = db.loans_staging, db.loan_changes
    acts = dict(conn.execute(select(st.c.action, func.count()).where(st.c.batch_id == batch_id, st.c.row_number.is_not(None))
                             .group_by(st.c.action)).all())
    applied = dict(conn.execute(select(lc.c.action, func.count()).where(lc.c.batch_id == batch_id, lc.c.status == "applied")
                                .group_by(lc.c.action)).all())
    adds = conn.execute(select(func.count()).select_from(st).where(st.c.batch_id == batch_id, st.c.boarded.is_(True),
                                                                  or_(st.c.action.is_(None), st.c.action == "add"))).scalar()
    conflicts = conn.execute(select(func.count()).select_from(db.exceptions).where(db.exceptions.c.batch_id == batch_id,
                                                                                   db.exceptions.c.rule_id == "CHG05")).scalar()
    return {"add_rows": acts.get("add", 0) + acts.get(None, 0), "update_rows": acts.get("update", 0), "close_rows": acts.get("close", 0),
            "unchanged_rows": acts.get("unchanged", 0), "adds_applied": adds, "updates_applied": applied.get("update", 0),
            "closes_applied": applied.get("close", 0), "conflicts": conflicts}


def reconcile(conn, batch_id: str, source_rows: int) -> dict:
    """source = boarded + held + rejected (+ unchanged for change files). Rows synthesised by the platform
    (snapshot close reviews, row_number NULL) are reported separately and are not part of the source count."""
    st = db.loans_staging
    file_rows = st.c.row_number.is_not(None)
    def n(*conds):
        return conn.execute(select(func.count()).select_from(st).where(st.c.batch_id == batch_id, file_rows, *conds)).scalar()

    staged = n()
    boarded = n(st.c.boarded.is_(True))
    rejected = n(st.c.status == "REJECTED")
    unchanged = n(st.c.status == "UNCHANGED")
    held = staged - boarded - rejected - unchanged
    adds_boarded = n(st.c.boarded.is_(True), or_(st.c.action.is_(None), st.c.action == "add"))
    in_sse = conn.execute(select(func.count()).select_from(db.sse_loans).where(db.sse_loans.c.lbp_batch_id == batch_id)).scalar()
    ex = db.exceptions
    by_status = dict(conn.execute(select(ex.c.status, func.count()).where(ex.c.batch_id == batch_id).group_by(ex.c.status)).all())
    dup = staged - conn.execute(select(func.count(func.distinct(st.c.loan_number))).where(st.c.batch_id == batch_id, file_rows)).scalar()
    out = {
        "source_rows": source_rows, "staged": staged, "boarded": boarded, "held_in_exceptions": held, "rejected": rejected,
        "unchanged": unchanged, "in_sse": in_sse, "duplicate_loan_numbers": dup, "exceptions_by_status": by_status,
        "balanced": source_rows == staged == boarded + held + rejected + unchanged and in_sse <= adds_boarded,
    }
    changed_boarded = n(st.c.boarded.is_(True), st.c.action.in_(("update", "close")))
    if changed_boarded or unchanged:
        lc = db.loan_changes
        logged = conn.execute(select(func.count(func.distinct(lc.c.staging_id))).where(
            lc.c.batch_id == batch_id, lc.c.status == "applied", lc.c.action.in_(("update", "close")),
            lc.c.staging_id.in_(select(st.c.id).where(st.c.batch_id == batch_id, file_rows)))).scalar()
        # every applied change is in the change log (a no-op update, already equal in SSE, logs nothing)
        out["changes_logged"] = logged
        out["balanced"] = out["balanced"] and logged <= changed_boarded
    return out
