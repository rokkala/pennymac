"""Entry points for the AWS Glue data plane (thin wrappers in aws/glue/ call these).

All loan data moves through Glue. Each job reads the feed's *published* configuration
(config_store: approved mapping, delivery profile, rule set; signed), never a draft:

    lbp-feed        Glue 5.0 job, driver only (Python 3.11). One batch end to end: sequencing gate, schema-drift
                    pre-flight, map, validate, triage (T1-T5), apply adds / updates / closes,
                    checkpoint per micro-batch, reconcile, advance the vendor's sequence cursor.
                    Also runs replays of held loans (--mode replay).
    lbp-feed-spark  Glue Spark, for very large full tapes. Partitions run the same mapping and
                    rule code (mapInPandas); the driver persists in bounded micro-batches so SSE
                    sees a fixed number of connections; same checkpoints and reconciliation.
    lbp-vendor-pull Glue 5.0 job, driver only. Fetches a vendor's files over SFTP / S3 into the raw zone,
                    where the arrival event starts lbp-feed for each one.

Glue runs are started by Step Functions (file arrival) or by the control-plane API (resume,
override, replay, pull now) through lbp.dispatch.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import time
from collections.abc import Callable, Iterable

from sqlalchemy import select

from .store import db

log = logging.getLogger("lbp.glue")


# ------------------------------------------------------------------ pipeline metrics
def emit_metrics(res: dict, seconds: float, engine: str) -> None:
    """LBP/Pipeline metrics for the dashboard and the failure-rate alarm (AWS only; counts, never loan data)."""
    from .config import get_settings

    s = get_settings()
    if s.env != "aws" or not isinstance(res, dict) or "processed" not in res:
        return
    try:
        import boto3

        dims = [{"Name": "Engine", "Value": engine}]
        data = [{"MetricName": "LoansProcessed", "Value": float(res.get("processed") or 0), "Unit": "Count"},
                {"MetricName": "LoansFailed", "Value": float(res.get("failed") or 0), "Unit": "Count"},
                {"MetricName": "BatchSeconds", "Value": round(seconds, 2), "Unit": "Seconds"}]
        # undimensioned copies feed the account-wide alarm and dashboard; dimensioned ones split by engine
        boto3.client("cloudwatch", region_name=s.aws_region).put_metric_data(
            Namespace="LBP/Pipeline", MetricData=data + [{**d, "Dimensions": dims} for d in data])
    except Exception as e:  # metrics must never fail a boarding run
        log.warning("metrics not emitted: %s", e)


# ------------------------------------------------------------------ lbp-feed: one batch
def process_batch(batch_id: str) -> dict:
    from .dispatch import dispatch
    from .pipeline.batch import run_batch

    t0 = time.monotonic()
    res = run_batch(batch_id)
    emit_metrics(res, time.monotonic() - t0, "standard")
    for nxt in res.get("released", []):  # files that were waiting behind this one
        dispatch(nxt)
    return res


def replay(batch_id: str, actor: str) -> dict:
    from .pipeline.replay import replay_batch

    return replay_batch(batch_id, actor, dry_run=False)


def pull(schedule_id: str) -> dict:
    from .scheduling.service import pull_now

    return pull_now(schedule_id, actor="glue:vendor-pull", roles=["admin"])


# ------------------------------------------------------------------ Spark: large full tapes
def prepare_large(batch_id: str):
    """Driver step 1: config, lease and pre-flight. Returns (cfg, batch) or (None, status dict)."""
    from .config_store import load as load_config
    from .pipeline.batch import LEASE_FROM, BatchBusyError
    from .pipeline.preflight import check_file
    from .pipeline.sequencing import acquire
    from .storage import local_path

    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
    cfg = load_config(b.source_id)
    leased, g = acquire(batch_id, f"glue:{socket.gethostname()}:{os.getpid()}", LEASE_FROM)
    if not leased:
        if g and g["decision"] != "go":
            return None, {"batch_id": batch_id, "status": "waiting" if g["decision"] == "wait" else "out_of_order"}
        raise BatchBusyError(batch_id)
    pf = b.preflight or {}
    if (b.checkpoint or 0) == 0 and not pf.get("override"):
        pf = {**check_file(local_path(b.file_path), cfg.parse_options, cfg.profile, cfg.fields), "mapping_id": cfg.mapping_id,
              "mapping_version": cfg.mapping_version, "config_version": cfg.version, "checked_at": db.now().isoformat()}
        with db.get_engine().begin() as c:
            c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(preflight=pf, mapping_id=cfg.mapping_id))
            db.audit(c, "pipeline", f"batch.preflight_{pf['decision']}", "batch", batch_id, {"summary": pf["summary"]})
        if pf["decision"] == "block":
            with db.get_engine().begin() as c:
                c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(status="blocked", error=pf["summary"], worker_id=None))
            return None, {"batch_id": batch_id, "status": "blocked"}
    with db.get_engine().begin() as c:
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(started_at=b.started_at or db.now(), error=None))
    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
    return cfg, b


def partition_processor(fields: list[dict], runtime_set: dict, key: str) -> Callable[[list[dict], int], list[dict]]:
    """What each Spark partition runs: the same mapping + rule code as every other path (pure, no DB)."""
    from .pipeline.batch import process_chunk

    def run(rows: list[dict], start_row: int) -> list[dict]:
        return process_chunk(rows, fields, runtime_set, start_row, key)

    return run


def persist_stream(batch_id: str, cfg, results: Iterable[dict], chunk: int = 10_000) -> dict:
    """Driver step 3: persist processed rows (ordered by row number) in micro-batches with the same
    atomic checkpoint as the standard path, then reconcile and complete. Rows at or below the
    checkpoint are skipped, so a retried job never stages a row twice."""
    from .exceptions.manager import Triage
    from .pipeline import sequencing
    from .pipeline.batch import _persist_chunk, reconcile

    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
    checkpoint = b.checkpoint or 0
    counters = {"processed": b.processed or 0, "passed": b.passed or 0, "warned": b.warned or 0, "failed": b.failed or 0, "loaded": b.loaded or 0}
    triage = Triage()
    triage.runtime_set = cfg.runtime_set
    t0, done_rows = time.monotonic(), 0
    micro = list(b.micro_batches or [])

    def flush(buf):
        nonlocal checkpoint, done_rows

        def progress(c, stats, _n=len(buf), _start=buf[0]["row"]):
            nonlocal checkpoint, done_rows
            checkpoint, done_rows = _start + _n, done_rows + _n
            micro.append({"index": len(micro), "start_row": _start, "rows": _n, **stats})
            c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(
                checkpoint=checkpoint, micro_batches=micro[-500:], heartbeat_at=db.now(),
                throughput_lps=round(done_rows / max(time.monotonic() - t0, 1e-6), 1), **counters))

        _persist_chunk(batch_id, b.source_id, buf, triage, cfg.pii_cols, counters, progress)

    buf: list[dict] = []
    for r in results:
        if r["row"] < checkpoint:
            continue
        buf.append(r)
        if len(buf) >= chunk:
            flush(buf)
            buf = []
    if buf:
        flush(buf)
    with db.get_engine().begin() as c:
        rec = reconcile(c, batch_id, counters["processed"])
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(
            status="completed" if rec["balanced"] else "failed", total_rows=counters["processed"], finished_at=db.now(), reconciliation=rec,
            worker_id=None, error=None if rec["balanced"] else "reconciliation mismatch"))
        db.audit(c, "pipeline", "batch.completed", "batch", batch_id, {**counters, "reconciliation": rec, "engine": "glue-spark"})
        released = sequencing.advance(c, b) if rec["balanced"] else []
    out = {"batch_id": batch_id, **counters, "reconciliation": rec, "released": released}
    emit_metrics(out, time.monotonic() - t0, "spark")
    return out


def summary(res: dict) -> str:
    return json.dumps({k: v for k, v in res.items() if k not in ("micro_batch_log",)}, default=str)[:4000]
