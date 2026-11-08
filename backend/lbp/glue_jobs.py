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
    if not b:
        raise ValueError(f"unknown batch {batch_id}")
    cfg = load_config(b.source_id)
    leased, g = acquire(batch_id, f"glue:{socket.gethostname()}:{os.getpid()}", LEASE_FROM)
    if not leased:
        if g and g["decision"] != "go":
            return None, {"batch_id": batch_id, "status": "waiting" if g["decision"] == "wait" else "out_of_order"}
        raise BatchBusyError(batch_id)
    # Re-read after lease so preflight/checkpoint aren't stale from a racing worker.
    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
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


def persist_stream(batch_id: str, cfg, results: Iterable[dict], chunk: int | None = None, workers: int | None = None) -> dict:
    """Driver step 3: persist processed rows (ordered by row number) in micro-batches with the same
    atomic checkpoint as the standard path, then reconcile and complete. Rows at or below the
    checkpoint are skipped, so a retried job never stages a row twice.

    workers>1 runs chunk JDBC in parallel; checkpoints still advance in row order (barrier)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

    from .exceptions.manager import Triage
    from .pipeline import sequencing
    from .pipeline.batch import _persist_chunk, reconcile

    chunk = chunk or int(os.environ.get("LBP_PERSIST_CHUNK", "25000"))
    workers = workers if workers is not None else int(os.environ.get("LBP_PERSIST_WORKERS", "4"))

    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
    checkpoint = b.checkpoint or 0
    counters = {"processed": b.processed or 0, "passed": b.passed or 0, "warned": b.warned or 0, "failed": b.failed or 0, "loaded": b.loaded or 0}
    # Drop rows at/above checkpoint left by a killed parallel flush so retry stays idempotent.
    _orphan_cleanup(batch_id, checkpoint)
    t0, done_rows = time.monotonic(), 0
    micro = list(b.micro_batches or [])
    lock = threading.Lock()
    ready: dict[int, tuple[int, dict, dict]] = {}  # start_row -> (n, stats, local_counters)

    def commit_ready():
        nonlocal checkpoint, done_rows
        while checkpoint in ready:
            n, stats, local = ready.pop(checkpoint)
            for k in counters:
                counters[k] += local[k]
            done_rows += n
            start = checkpoint
            checkpoint += n
            micro.append({"index": len(micro), "start_row": start, "rows": n, **stats})
            with db.get_engine().begin() as c:
                c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(
                    checkpoint=checkpoint, micro_batches=micro[-500:], heartbeat_at=db.now(),
                    throughput_lps=round(done_rows / max(time.monotonic() - t0, 1e-6), 1), **counters))

    def run_chunk(buf: list[dict]):
        local = {"processed": 0, "passed": 0, "warned": 0, "failed": 0, "loaded": 0}
        triage = Triage()
        triage.runtime_set = cfg.runtime_set
        start = buf[0]["row"]
        held: dict = {}

        def progress(_c, stats, _n=len(buf), _start=start):
            held["stats"] = stats

        _persist_chunk(batch_id, b.source_id, buf, triage, cfg.pii_cols, local, progress)
        with lock:
            ready[start] = (len(buf), held.get("stats") or {}, local)
            commit_ready()

    buf: list[dict] = []
    if workers <= 1:
        for r in results:
            if r["row"] < checkpoint:
                continue
            buf.append(r)
            if len(buf) >= chunk:
                run_chunk(buf)
                buf = []
        if buf:
            run_chunk(buf)
    else:
        # ponytail: in-flight queue capped at 2*workers so driver RAM stays bounded on 10M tapes.
        inflight: set = set()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for r in results:
                if r["row"] < checkpoint:
                    continue
                buf.append(r)
                if len(buf) < chunk:
                    continue
                inflight.add(pool.submit(run_chunk, buf))
                buf = []
                while len(inflight) >= workers * 2:
                    done, not_done = wait(inflight, return_when=FIRST_COMPLETED)
                    inflight = set(not_done)
                    for f in done:
                        f.result()
            if buf:
                inflight.add(pool.submit(run_chunk, buf))
            while inflight:
                done, not_done = wait(inflight, return_when=FIRST_COMPLETED)
                inflight = set(not_done)
                for f in done:
                    f.result()
    assert not ready, f"uncommitted chunks at {sorted(ready)} — row gaps or non-contiguous numbering"
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


def _clean_add(r: dict) -> bool:
    if r.get("status") not in ("PASS", "WARN"):
        return False
    if r.get("action") not in (None, "add"):
        return False
    if r.get("fails") or r.get("terrs"):
        return False
    return bool((r.get("record") or {}).get("loan_number"))


def _flag_dup(r: dict, rule_id: str, message: str) -> dict:
    from .pipeline.batch import DUP_RULES

    fails = [f for f in (r.get("fails") or []) if f.get("rule_id") not in DUP_RULES]
    fails.append({"rule_id": rule_id, "version": 1, "name": DUP_RULES[rule_id], "field": "loan_number",
                  "category": "duplicate", "severity": "FAIL", "message": message, "regulatory_tag": "SOX"})
    return {**r, "fails": fails, "status": "FAIL"}


def _orphan_cleanup(batch_id: str, checkpoint: int) -> None:
    """Drop partial persist so retries stay idempotent.

    checkpoint<=0 (force reopen): wipe ALL rows for this batch — staging may already be empty
    while sse_loans remain from a prior success/OOM, and the staging subquery would miss them.
    """
    with db.get_engine().begin() as c:
        st = db.loans_staging
        if checkpoint <= 0:
            c.execute(db.sse_loans.delete().where(db.sse_loans.c.lbp_batch_id == batch_id))
            c.execute(db.exceptions.delete().where(db.exceptions.c.batch_id == batch_id))
            c.execute(st.delete().where(st.c.batch_id == batch_id))
            return
        orphan_loans = select(st.c.loan_number).where(st.c.batch_id == batch_id, st.c.row_number >= checkpoint)
        c.execute(db.sse_loans.delete().where(db.sse_loans.c.lbp_batch_id == batch_id,
                                              db.sse_loans.c.loan_number.in_(orphan_loans)))
        c.execute(db.exceptions.delete().where(db.exceptions.c.batch_id == batch_id,
                                               db.exceptions.c.loan_number.in_(orphan_loans)))
        c.execute(st.delete().where(st.c.batch_id == batch_id, st.c.row_number >= checkpoint))


def _split_clean_dirty(batch_id: str, rows: list[dict], *, check_dup02: bool = True) -> tuple[list[dict], list[dict]]:
    seen: set[str] = set()
    clean, dirty = [], []
    for r in rows:
        ln = str(r["record"]["loan_number"])
        if ln in seen:
            dirty.append(_flag_dup(r, "DUP01", f"Loan number {ln} appears more than once in this file"))
        else:
            seen.add(ln)
            clean.append(r)
    if not check_dup02:
        return clean, dirty
    existing: set[str] = set()
    nums = [str(r["record"]["loan_number"]) for r in clean]
    with db.get_engine().connect() as c:
        for i in range(0, len(nums), 900):
            part = nums[i:i + 900]
            existing |= {x for (x,) in c.execute(
                select(db.sse_loans.c.loan_number).where(db.sse_loans.c.loan_number.in_(part),
                                                        db.sse_loans.c.lbp_batch_id != batch_id))}
    still = []
    for r in clean:
        ln = str(r["record"]["loan_number"])
        if ln in existing:
            dirty.append(_flag_dup(r, "DUP02", f"Loan {ln} was already boarded from another batch."))
        else:
            still.append(r)
    return still, dirty


def _copy_clean_adds(batch_id: str, source_id: str, still: list[dict]) -> None:
    from .pipeline.loader import copy_insert_loans, copy_insert_staging, to_sse_row

    if not still:
        return
    sse_rows = [to_sse_row(r["record"], batch_id, r["status"], source_id) for r in still]
    staging = [{"batch_id": batch_id, "row_number": r["row"], "loan_number": str(r["record"]["loan_number"]),
                "status": r["status"], "record": {}, "raw": None, "transform_errors": {}, "boarded": True,
                "action": "add", "changes": None, "base_version": None} for r in still]
    with db.get_engine().begin() as c:
        copy_insert_loans(c, sse_rows)
        copy_insert_staging(c, staging)


def begin_bulk(batch_id: str) -> int:
    """Driver: drop orphans at/above checkpoint so executor retries stay idempotent. Returns checkpoint."""
    import shutil

    from .config import get_settings

    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
    if not b:
        raise ValueError(f"unknown batch {batch_id}")
    checkpoint = b.checkpoint or 0
    _orphan_cleanup(batch_id, checkpoint)
    shutil.rmtree(_bulk_load_root(batch_id), ignore_errors=True)  # stale dirty part files from a prior attempt
    s = get_settings()
    if s.env == "aws" and s.processed_bucket:
        import boto3

        client = boto3.client("s3", region_name=_require_aws_region(s))
        prefix = f"bulk-load/{batch_id}/"
        token = None
        while True:
            kw = {"Bucket": s.processed_bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = client.list_objects_v2(**kw)
            objs = [{"Key": o["Key"]} for o in resp.get("Contents") or []]
            for i in range(0, len(objs), 1000):
                client.delete_objects(Bucket=s.processed_bucket, Delete={"Objects": objs[i:i + 1000]})
            token = resp.get("NextContinuationToken")
            if not token:
                break
    with db.get_engine().begin() as c:
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(heartbeat_at=db.now()))
    return checkpoint


def _file_load_on() -> bool:
    return os.environ.get("LBP_BULK_FILE_LOAD", "1").lower() not in ("0", "false", "no")


def _spark_db_free_on() -> bool:
    """Spark persist writes S3 parts only; load job owns Postgres COPY."""
    return os.environ.get("LBP_SPARK_DB_FREE", "1").lower() not in ("0", "false", "no")


def _s3_import_on() -> bool:
    """Clean parts as CSV; load prefers aws_s3.table_import_from_s3 (STDIN CSV fallback)."""
    return os.environ.get("LBP_S3_IMPORT", "0").lower() in ("1", "true", "yes")


def _bulk_load_root(batch_id: str):
    from pathlib import Path

    from .config import get_settings

    root = get_settings().data_dir / "bulk-load" / batch_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def _materialize_dirty_adds(batch_id: str, source_id: str, results: list[dict], triage, pii_cols) -> tuple[list, list, list]:
    """Triage dirty full-tape adds in memory → staging, exceptions (with _row_number), boarded SSE rows."""
    from .exceptions.manager import _str
    from .pipeline.batch import _mask_raw, _triage_results, detect_duplicates
    from .pipeline.loader import to_sse_row

    slim = os.environ.get("LBP_SLIM_STAGING", "").lower() in ("1", "true", "yes")
    detect_duplicates(batch_id, results)
    staged, ex_rows_by_idx, _st = _triage_results(results, triage)
    staging_rows, adds = [], []
    for r, rec, status in staged:
        action = "unchanged" if status == "UNCHANGED" else r.get("action")
        if status == "UNCHANGED":
            staging_rows.append({"batch_id": batch_id, "row_number": r["row"], "loan_number": _str(rec.get("loan_number")),
                                 "status": status, "record": {}, "raw": None, "transform_errors": {}, "boarded": False,
                                 "action": "unchanged", "changes": None, "base_version": r.get("base_version")})
            continue
        boarded = status in ("PASS", "WARN")
        if boarded and action in (None, "add"):
            adds.append(to_sse_row(rec, batch_id, status, source_id))
        store_rec = {} if slim and boarded and action in (None, "add") else rec
        staging_rows.append({"batch_id": batch_id, "row_number": r["row"], "loan_number": _str(rec.get("loan_number")),
                             "status": status, "record": store_rec, "raw": None if slim else _mask_raw(r["raw"], pii_cols),
                             "transform_errors": r["terrs"], "boarded": boarded, "action": action, "changes": None,
                             "base_version": r.get("base_version")})
    exceptions = []
    for idx, exs in ex_rows_by_idx.items():
        s = staging_rows[idx]
        for e in exs:
            e = dict(e)
            e.pop("regulatory_tag", None)
            exceptions.append({
                "exception_id": db.new_id("ex"), "batch_id": batch_id, "source_id": source_id,
                "loan_number": s["loan_number"], "staging_id": None, "_row_number": s["row_number"],
                "resolved_at": db.now() if e.get("status") == "auto_applied" else None,
                "rule_version": e.pop("rule_version", None), "resolved_value": e.pop("resolved_value", None),
                "maker": e.pop("maker", None), "created_at": db.now(), **e,
            })
    return staging_rows, exceptions, adds


def _upload_part_dir(batch_id: str, kind: str, part) -> None:
    from .config import get_settings

    s = get_settings()
    if not (s.env == "aws" and s.processed_bucket):
        return
    import boto3

    client = boto3.client("s3", region_name=s.aws_region)
    prefix = f"bulk-load/{batch_id}/{kind}/{part.name}"
    for p in part.iterdir():
        if p.is_file():
            client.upload_file(str(p), s.processed_bucket, f"{prefix}/{p.name}")


def _part_name_from_rows(files: dict[str, list], part_name: str | None = None) -> str:
    """Stable part dir so Spark retries overwrite instead of duplicating uuid parts."""
    if part_name:
        return part_name
    for rows in files.values():
        for r in rows:
            rn = r.get("row") if isinstance(r, dict) else None
            if rn is None and isinstance(r, dict):
                rn = r.get("row_number")
            if rn is not None:
                try:
                    return f"part-{int(rn):05d}"
                except (TypeError, ValueError):
                    pass
    import uuid
    return f"p-{uuid.uuid4().hex[:12]}"


def _write_jsonl_part(batch_id: str, kind: str, files: dict[str, list], part_name: str | None = None) -> None:
    """Write one part under bulk-load/{batch_id}/{kind}/part-* (and S3 when env=aws)."""
    import shutil

    name = _part_name_from_rows(files, part_name)
    part = _bulk_load_root(batch_id) / kind / name
    if part.exists():
        shutil.rmtree(part)
    part.mkdir(parents=True, exist_ok=True)
    for fname, rows in files.items():
        with (part / fname).open("w") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")
    _upload_part_dir(batch_id, kind, part)


def _csv_cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)
    return v


def _write_csv_rows(path, rows: list[dict], cols: list[str]) -> None:
    import csv

    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: _csv_cell(r.get(c)) for c in cols})


def _write_dirty_part(batch_id: str, staging: list, exceptions: list, loans: list) -> None:
    _write_jsonl_part(batch_id, "dirty", {
        "staging.jsonl": staging, "exceptions.jsonl": exceptions, "loans.jsonl": loans,
    })


class DirtyPartWriter:
    """Stream dirty rows into one dirty/part-NNNNN/ directory (coalesce path: ≤8 parts)."""

    def __init__(self, batch_id: str, part_name: str):
        self.batch_id = batch_id
        self.part_name = part_name
        self.part = _bulk_load_root(batch_id) / "dirty" / part_name
        self.part.mkdir(parents=True, exist_ok=True)
        # "w" so a retried task on the same part_name truncates instead of duplicating rows.
        self._files = {
            "staging.jsonl": (self.part / "staging.jsonl").open("w"),
            "exceptions.jsonl": (self.part / "exceptions.jsonl").open("w"),
            "loans.jsonl": (self.part / "loans.jsonl").open("w"),
        }
        self.n_st = self.n_ex = self.n_lo = 0
        self._closed = False

    def __call__(self, staging: list, exceptions: list, loans: list) -> None:
        for name, rows, attr in (
            ("staging.jsonl", staging, "n_st"),
            ("exceptions.jsonl", exceptions, "n_ex"),
            ("loans.jsonl", loans, "n_lo"),
        ):
            if not rows:
                continue
            f = self._files[name]
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")
            setattr(self, attr, getattr(self, attr) + len(rows))

    def sync_s3(self) -> None:
        """Flush local handles and overwrite S3 objects (mid-partition progress)."""
        from .config import get_settings

        if self._closed:
            return
        for f in self._files.values():
            f.flush()
        s = get_settings()
        if not (s.env == "aws" and s.processed_bucket):
            return
        import boto3

        client = boto3.client("s3", region_name=s.aws_region)
        prefix = f"bulk-load/{self.batch_id}/dirty/{self.part_name}"
        for p in self.part.iterdir():
            if p.is_file() and p.stat().st_size > 0:
                client.upload_file(str(p), s.processed_bucket, f"{prefix}/{p.name}")

    def close(self) -> None:
        if self._closed:
            return
        for f in self._files.values():
            f.close()
        self._closed = True
        for path in (
            self.part / "staging.jsonl",
            self.part / "exceptions.jsonl",
            self.part / "loans.jsonl",
        ):
            if path.exists() and path.stat().st_size == 0:
                path.unlink()
        from .config import get_settings

        s = get_settings()
        if s.env == "aws" and s.processed_bucket and self.part.exists() and any(self.part.iterdir()):
            import boto3

            client = boto3.client("s3", region_name=s.aws_region)
            prefix = f"bulk-load/{self.batch_id}/dirty/{self.part_name}"
            for p in self.part.iterdir():
                if p.is_file():
                    client.upload_file(str(p), s.processed_bucket, f"{prefix}/{p.name}")


def open_dirty_part_writer(batch_id: str, part_name: str) -> DirtyPartWriter:
    return DirtyPartWriter(batch_id, part_name)


def write_clean_sse_csv(batch_id: str, sse_rows: list, filename: str | None = None) -> str | None:
    """Write one CSV under clean/sse/ (and upload on AWS). Returns filename or None."""
    if not sse_rows:
        return None
    from .config import get_settings

    sse_dir = _bulk_load_root(batch_id) / "clean" / "sse"
    sse_dir.mkdir(parents=True, exist_ok=True)
    name = filename or f"{_part_name_from_rows({'sse': sse_rows})}.csv"
    cols = sorted({k for r in sse_rows for k in r})
    path = sse_dir / name
    _write_csv_rows(path, sse_rows, cols)
    s = get_settings()
    if s.env == "aws" and s.processed_bucket:
        import boto3

        boto3.client("s3", region_name=_require_aws_region(s)).upload_file(
            str(path), s.processed_bucket, f"bulk-load/{batch_id}/clean/sse/{name}")
    return name


def _write_clean_part(batch_id: str, staging: list, sse_rows: list) -> None:
    """Clean materialize: JSONL parts, or CSV under clean/sse/ (staging rebuilt at load)."""
    if not _s3_import_on():
        _write_jsonl_part(batch_id, "clean", {"staging.jsonl": staging, "sse.jsonl": sse_rows})
        return
    write_clean_sse_csv(batch_id, sse_rows)


def staging_from_sse(batch_id: str, sse_rows: list[dict]) -> list[dict]:
    """Slim staging rows derived from clean SSE (no separate staging.csv needed)."""
    out = []
    for r in sse_rows:
        rn = r.get("row")
        if rn is not None and rn != "":
            try:
                rn = int(rn)
            except (TypeError, ValueError):
                rn = None
        out.append({
            "batch_id": batch_id,
            "row_number": rn,
            "loan_number": str(r.get("loan_number")),
            "status": r.get("lbp_dq_status") or "PASS",
            "record": {}, "raw": None, "transform_errors": {}, "boarded": True,
            "action": "add", "changes": None, "base_version": None,
        })
    return out


def clean_sse_csv_uris(batch_id: str) -> list[tuple[str, str | None]]:
    """[(local_path_or_empty, s3_key_or_none), ...] for clean/sse/*.csv."""
    from .config import get_settings

    root = _bulk_load_root(batch_id) / "clean" / "sse"
    found: dict[str, tuple[str, str | None]] = {}
    if root.exists():
        for p in sorted(root.glob("*.csv")):
            found[p.name] = (str(p), None)
    s = get_settings()
    if s.env == "aws" and s.processed_bucket:
        import boto3

        client = boto3.client("s3", region_name=s.aws_region)
        prefix = f"bulk-load/{batch_id}/clean/sse/"
        token = None
        while True:
            kw = {"Bucket": s.processed_bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = client.list_objects_v2(**kw)
            for obj in resp.get("Contents") or []:
                key = obj["Key"]
                if not key.endswith(".csv"):
                    continue
                name = key.rsplit("/", 1)[-1]
                local = root / name
                if not local.exists():
                    root.mkdir(parents=True, exist_ok=True)
                    client.download_file(s.processed_bucket, key, str(local))
                found[name] = (str(local), key)
            token = resp.get("NextContinuationToken")
            if not token:
                break
    return [found[k] for k in sorted(found)]


def _write_oltp_part(batch_id: str, rows: list) -> None:
    _write_jsonl_part(batch_id, "oltp", {"rows.jsonl": rows})


def _list_kind_part_names(batch_id: str, kind: str) -> list[str]:
    """Part directory names under bulk-load/{batch_id}/{kind}/ (local and/or S3).

    Also accepts legacy flat dirty parts at bulk-load/{batch_id}/p-* (pre-split layout).
    """
    from .config import get_settings

    def _is_part(name: str) -> bool:
        return name.startswith("p-") or name.startswith("part-")

    root = _bulk_load_root(batch_id) / kind
    names = {p.name for p in root.iterdir() if p.is_dir() and _is_part(p.name)} if root.exists() else set()
    legacy = kind == "dirty"
    if legacy:
        flat = _bulk_load_root(batch_id)
        names |= {p.name for p in flat.iterdir() if p.is_dir() and _is_part(p.name)} if flat.exists() else set()
    s = get_settings()
    if s.env == "aws" and s.processed_bucket:
        import boto3

        client = boto3.client("s3", region_name=s.aws_region)
        prefixes = [f"bulk-load/{batch_id}/{kind}/"]
        if legacy:
            prefixes.append(f"bulk-load/{batch_id}/")
        for prefix in prefixes:
            token = None
            while True:
                kw = {"Bucket": s.processed_bucket, "Prefix": prefix, "Delimiter": "/"}
                if token:
                    kw["ContinuationToken"] = token
                resp = client.list_objects_v2(**kw)
                for cp in resp.get("CommonPrefixes") or []:
                    part = cp["Prefix"][len(prefix):].strip("/")
                    if _is_part(part):
                        names.add(part)
                token = resp.get("NextContinuationToken")
                if not token:
                    break
    return sorted(names)


def _list_dirty_part_names(batch_id: str) -> list[str]:
    return _list_kind_part_names(batch_id, "dirty")


def _ensure_kind_part(batch_id: str, kind: str, part_name: str, filenames: tuple[str, ...]):
    """Download one part from S3 if needed; return local part Path."""
    from .config import get_settings

    part = _bulk_load_root(batch_id) / kind / part_name
    # Legacy dirty flat layout
    legacy = kind == "dirty" and not part.exists() and (_bulk_load_root(batch_id) / part_name).exists()
    if legacy:
        part = _bulk_load_root(batch_id) / part_name
    else:
        part.mkdir(parents=True, exist_ok=True)
    s = get_settings()
    if s.env == "aws" and s.processed_bucket:
        import boto3
        from botocore.exceptions import ClientError

        client = boto3.client("s3", region_name=_require_aws_region(s))
        prefixes = [f"bulk-load/{batch_id}/{kind}/{part_name}/"]
        if kind == "dirty":
            prefixes.append(f"bulk-load/{batch_id}/{part_name}/")
        for name in filenames:
            dest = part / name
            if dest.exists():
                continue
            for prefix in prefixes:
                try:
                    client.download_file(s.processed_bucket, f"{prefix}{name}", str(dest))
                    break
                except ClientError as e:
                    code = str(e.response.get("Error", {}).get("Code", ""))
                    if code in ("404", "NoSuchKey", "NotFound"):
                        continue
                    raise
    return part


def _ensure_dirty_part(batch_id: str, part_name: str):
    return _ensure_kind_part(batch_id, "dirty", part_name,
                             ("staging.jsonl", "exceptions.jsonl", "loans.jsonl"))


def _read_jsonl(path) -> list:
    if not path.exists():
        return []
    out = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _read_csv(path) -> list[dict]:
    if not path.exists():
        return []
    import csv

    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    # Restore JSON object columns + bools written as text
    for r in rows:
        for k in ("record", "raw", "transform_errors", "changes", "proposal"):
            if k in r and isinstance(r[k], str) and r[k]:
                try:
                    r[k] = json.loads(r[k])
                except json.JSONDecodeError:
                    pass
        for k in ("boarded", "blocking", "qa_sample"):
            if k in r and isinstance(r[k], str):
                r[k] = r[k].strip().lower() in ("1", "true", "t", "yes")
        if "row_number" in r and r["row_number"] not in (None, ""):
            try:
                r["row_number"] = int(r["row_number"])
            except (TypeError, ValueError):
                pass
    return rows


def _parse_dt(v):
    """JSONL round-trip turns datetimes into strings; restore for SQLite/typed columns."""
    if v is None or not isinstance(v, str):
        return v
    from datetime import datetime

    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            d = datetime.strptime(v, fmt)
            return d.date() if fmt == "%Y-%m-%d" else d
        except ValueError:
            continue
    return v


def _revive_sse_row(r: dict) -> dict:
    """Restore typed fields after JSONL/CSV so SQLite/Postgres inserts accept the row."""
    from .pipeline.loader import _DATE_FIELDS
    from .schema.sse_target import ATTRIBUTES

    bools = {a.name for a in ATTRIBUTES if a.dtype == "bool"}
    ints = {a.name for a in ATTRIBUTES if a.dtype == "int"} | {"lbp_version"}
    decimals = {a.name for a in ATTRIBUTES if a.dtype == "decimal"}
    for k, v in list(r.items()):
        if v == "":
            r[k] = None
            continue
        if k in bools and isinstance(v, str):
            r[k] = v.strip().lower() in ("1", "true", "t", "yes")
        elif k in ints and isinstance(v, str):
            try:
                r[k] = int(float(v))
            except ValueError:
                r[k] = None
        elif k in decimals and isinstance(v, str):
            try:
                r[k] = float(v)
            except ValueError:
                r[k] = None
    for k in _DATE_FIELDS:
        if k in r and isinstance(r[k], str) and r[k]:
            r[k] = _parse_dt(r[k])
    for k in ("lbp_boarded_at", "lbp_updated_at", "lbp_closed_at"):
        if k in r and r[k] is not None:
            r[k] = _parse_dt(r.get(k))
    if not r.get("lbp_boarded_at"):
        r["lbp_boarded_at"] = db.now()
    return r


def load_dirty_files(batch_id: str) -> dict:
    """Driver: COPY dirty parts one at a time (never hold all 15M exceptions in RAM).

    Does not wipe the whole bulk-load root — oltp/ clean/ must survive until finalize/run_load_bulk.
    """
    import shutil

    from .pipeline.loader import copy_insert_exceptions, copy_insert_loans, copy_insert_staging

    parts = _list_dirty_part_names(batch_id)
    if not parts:
        return {"staging": 0, "exceptions": 0, "loans": 0}
    n_st = n_ex = n_lo = 0
    seen_ln: set[str] = set()
    with db.get_engine().connect() as c:
        source_id = c.execute(select(db.batches.c.source_id).where(db.batches.c.batch_id == batch_id)).scalar()
    for name in parts:
        part = _ensure_dirty_part(batch_id, name)
        staging = _read_jsonl(part / "staging.jsonl")
        exceptions = _read_jsonl(part / "exceptions.jsonl")
        loans = _read_jsonl(part / "loans.jsonl")
        if not staging and not exceptions and not loans:
            continue
        keep_loans, dup_meta = [], {}  # ln -> (rule_id, message)
        nums = [str(r.get("loan_number")) for r in loans if r.get("loan_number")]
        owner: dict[str, str] = {}
        if nums:
            with db.get_engine().connect() as c:
                for i in range(0, len(nums), 900):
                    chunk = nums[i:i + 900]
                    for ln, bid in c.execute(select(db.sse_loans.c.loan_number, db.sse_loans.c.lbp_batch_id).where(
                            db.sse_loans.c.loan_number.in_(chunk))):
                        owner[str(ln)] = bid
        for r in loans:
            ln = str(r.get("loan_number"))
            if ln in seen_ln or owner.get(ln) == batch_id:
                dup_meta[ln] = ("DUP01", f"Loan number {ln} appears more than once in this file")
            elif ln in owner:
                dup_meta[ln] = ("DUP02", f"Loan {ln} was already boarded from another batch.")
            else:
                seen_ln.add(ln)
                keep_loans.append(r)
        dup_ex = []
        if dup_meta:
            from .pipeline.batch import DUP_RULES
            for s in staging:
                if str(s.get("loan_number")) in dup_meta:
                    s["boarded"] = False
                    s["status"] = "FAIL"
            for ln, (rule_id, message) in sorted(dup_meta.items()):
                st = next((s for s in staging if str(s.get("loan_number")) == ln), None)
                dup_ex.append({
                    "exception_id": db.new_id("ex"), "batch_id": batch_id, "source_id": source_id,
                    "loan_number": ln, "staging_id": None, "rule_id": rule_id, "rule_version": 1,
                    "rule_name": DUP_RULES[rule_id], "category": "duplicate", "severity": "FAIL",
                    "blocking": True, "field": "loan_number", "original_value": ln, "message": message,
                    "risk": "medium", "tier": "T3", "queue": "ops", "status": "open",
                    "proposal": None, "resolved_value": None, "maker": None, "checker": None,
                    "qa_sample": False, "created_at": db.now(), "resolved_at": None,
                    "_row_number": (st or {}).get("row_number"),
                })
        with db.get_engine().begin() as c:
            if keep_loans:
                copy_insert_loans(c, [_revive_sse_row(r) for r in keep_loans])
                n_lo += len(keep_loans)
            if staging:
                copy_insert_staging(c, staging)
                n_st += len(staging)
            all_ex = list(exceptions) + dup_ex
            if all_ex:
                rns = [s["row_number"] for s in staging] if staging else [e.get("_row_number") for e in all_ex]
                rns = [r for r in rns if r is not None]
                id_by_row = {}
                for i in range(0, len(rns), 900):
                    chunk = rns[i:i + 900]
                    id_by_row.update({r[0]: r[1] for r in c.execute(
                        select(db.loans_staging.c.row_number, db.loans_staging.c.id).where(
                            db.loans_staging.c.batch_id == batch_id,
                            db.loans_staging.c.row_number.in_(chunk))).all()})
                for e in all_ex:
                    rn = e.pop("_row_number", None)
                    if rn is not None:
                        e["staging_id"] = id_by_row.get(rn)
                    e["created_at"] = _parse_dt(e.get("created_at")) or db.now()
                    e["resolved_at"] = _parse_dt(e.get("resolved_at"))
                copy_insert_exceptions(c, all_ex)
                n_ex += len(all_ex)
        # Drop only this dirty part after load so driver disk stays bounded; leave oltp/clean.
        shutil.rmtree(part, ignore_errors=True)
    return {"staging": n_st, "exceptions": n_ex, "loans": n_lo}


def serialize_mapped_rows(batch_id: str, source_id: str, rows: list[dict], *, cfg,
                          checkpoint: int = 0, clean_sink: list | None = None,
                          dirty_writer=None) -> None:
    """Thin persist from already-mapped parquet payloads: clean → SSE sink, dirty → files.

    No DB. Triage/_materialize_dirty_adds only for non-clean rows. Spark S3-import path.
    """
    from .exceptions.manager import Triage
    from .pipeline.loader import to_sse_row

    rows = [r for r in rows if r.get("row", -1) >= checkpoint]
    if not rows:
        return
    clean = [r for r in rows if _clean_add(r)]
    other = [r for r in rows if not _clean_add(r)]
    still, dup_dirty = _split_clean_dirty(batch_id, clean, check_dup02=False) if clean else ([], [])
    other = other + dup_dirty
    if still and clean_sink is not None:
        for r in still:
            sse = to_sse_row(r["record"], batch_id, r["status"], source_id)
            sse["row"] = r["row"]
            clean_sink.append(sse)
    if other:
        if dirty_writer is None:
            raise ValueError("serialize_mapped_rows requires dirty_writer when dirty rows present")
        triage = Triage()
        triage.runtime_set = cfg.runtime_set
        file_rows = [r for r in other if r.get("action") in (None, "add")]
        oltp_rows = [r for r in other if r.get("action") not in (None, "add")]
        if file_rows:
            staging, exceptions, loans = _materialize_dirty_adds(
                batch_id, source_id, file_rows, triage, cfg.pii_cols)
            if staging or exceptions or loans:
                dirty_writer(staging, exceptions, loans)
        if oltp_rows:
            _write_oltp_part(batch_id, oltp_rows)


def persist_partition(batch_id: str, cfg, rows: list[dict], checkpoint: int = 0,
                      source_id: str | None = None, clean_sink: list | None = None,
                      dirty_writer=None) -> None:
    """Executor: clean/dirty → files (DB-free) or COPY clean + dirty files. No ordered checkpoint.

    clean_sink: append clean SSE dicts (Spark coalesce). dirty_writer: DirtyPartWriter callable.
    """
    from .exceptions.manager import Triage
    from .pipeline.batch import _persist_chunk
    from .pipeline.loader import copy_insert_loans, to_sse_row

    rows = [r for r in rows if r.get("row", -1) >= checkpoint]
    if not rows:
        return
    db_free = _spark_db_free_on()
    if source_id is None:
        if db_free:
            raise ValueError("persist_partition requires source_id when LBP_SPARK_DB_FREE is on")
        with db.get_engine().connect() as c:
            source_id = c.execute(select(db.batches.c.source_id).where(db.batches.c.batch_id == batch_id)).scalar()
    clean = [r for r in rows if _clean_add(r)]
    other = [r for r in rows if not _clean_add(r)]
    still, dirty = _split_clean_dirty(batch_id, clean, check_dup02=not db_free) if clean else ([], [])
    other = other + dirty
    if still:
        if db_free:
            sse_rows = []
            for r in still:
                sse = to_sse_row(r["record"], batch_id, r["status"], source_id)
                sse["row"] = r["row"]  # carried for staging_from_sse / reconcile
                sse_rows.append(sse)
            if clean_sink is not None:
                clean_sink.extend(sse_rows)
            elif _s3_import_on():
                _write_clean_part(batch_id, [], sse_rows)
            else:
                staging = [{"batch_id": batch_id, "row_number": r["row"], "loan_number": str(r["record"]["loan_number"]),
                            "status": r["status"], "record": {}, "raw": None, "transform_errors": {}, "boarded": True,
                            "action": "add", "changes": None, "base_version": None} for r in still]
                _write_clean_part(batch_id, staging, sse_rows)
        else:
            _copy_clean_adds(batch_id, source_id, still)
    if other:
        triage = Triage()
        triage.runtime_set = cfg.runtime_set
        file_rows = [r for r in other if r.get("action") in (None, "add")]
        oltp_rows = [r for r in other if r.get("action") not in (None, "add")]
        if file_rows and _file_load_on():
            staging, exceptions, loans = _materialize_dirty_adds(batch_id, source_id, file_rows, triage, cfg.pii_cols)
            if db_free:
                if staging or exceptions or loans:
                    if dirty_writer is not None:
                        dirty_writer(staging, exceptions, loans)
                    else:
                        _write_dirty_part(batch_id, staging, exceptions, loans)
            else:
                if loans:
                    with db.get_engine().begin() as c:
                        copy_insert_loans(c, loans)
                if staging or exceptions:
                    _write_dirty_part(batch_id, staging, exceptions, [])
        elif file_rows and not db_free:
            throwaway = {"processed": 0, "passed": 0, "warned": 0, "failed": 0, "loaded": 0}
            _persist_chunk(batch_id, source_id, file_rows, triage, cfg.pii_cols, throwaway, lambda *_a, **_k: None)
        elif file_rows and db_free:
            _write_oltp_part(batch_id, file_rows)
        if oltp_rows:
            if db_free:
                _write_oltp_part(batch_id, oltp_rows)
            else:
                throwaway = {"processed": 0, "passed": 0, "warned": 0, "failed": 0, "loaded": 0}
                _persist_chunk(batch_id, source_id, oltp_rows, triage, cfg.pii_cols, throwaway, lambda *_a, **_k: None)
    if not db_free:
        with db.get_engine().begin() as c:
            c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(heartbeat_at=db.now()))


def mark_staged(batch_id: str) -> dict:
    """Spark finished materializing S3 parts; load job owns COPY."""
    with db.get_engine().begin() as c:
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(
            status="staged", worker_id=None, heartbeat_at=db.now(), error=None))
        db.audit(c, "pipeline", "batch.staged", "batch", batch_id, {"engine": "glue-spark-db-free"})
    return {"batch_id": batch_id, "status": "staged"}


def _require_aws_region(s) -> str:
    if not s.aws_region:
        raise ValueError("aws_region is required when env=aws (no silent default)")
    return s.aws_region


def _sql_ident(name: str) -> str:
    """Reject anything that isn't a plain SQL identifier before interpolating into DDL."""
    import re

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name


def _try_aws_s3_import_csv(conn, table: str, cols: list[str], s3_bucket: str, s3_key: str, region: str) -> bool:
    """True if aws_s3.table_import_from_s3 loaded rows into `table`. False → caller uses local CSV."""
    from sqlalchemy import text

    table = _sql_ident(table)
    cols = [_sql_ident(c) for c in cols]
    try:
        # Savepoint so a failed import doesn't abort the outer txn (caller still needs DROP/local read).
        with conn.begin_nested():
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS aws_commons"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS aws_s3 CASCADE"))
            col_list = ", ".join(cols)
            conn.execute(
                text(
                    f"""
                    SELECT aws_s3.table_import_from_s3(
                      :table, :cols, '(FORMAT CSV, HEADER true)',
                      aws_commons.create_s3_uri(:bucket, :key, :region)
                    )
                    """
                ),
                {"table": table, "cols": col_list, "bucket": s3_bucket, "key": s3_key, "region": region},
            )
        return True
    except Exception:
        return False


def _normalize_staging_csv_rows(rows: list[dict]) -> list[dict]:
    for r in rows:
        for k in ("record", "raw", "transform_errors", "changes"):
            if k in r and isinstance(r[k], str) and r[k]:
                try:
                    r[k] = json.loads(r[k])
                except json.JSONDecodeError:
                    pass
            elif k in r and r[k] == "":
                r[k] = None
        if "boarded" in r and isinstance(r["boarded"], str):
            r["boarded"] = r["boarded"].strip().lower() in ("1", "true", "t", "yes")
        if "row_number" in r and r["row_number"] not in (None, ""):
            try:
                r["row_number"] = int(r["row_number"])
            except (TypeError, ValueError):
                pass
        elif "row_number" in r and r["row_number"] == "":
            r["row_number"] = None
    return rows


def _load_clean_csv_part(batch_id: str, part) -> tuple[list, list]:
    """Return (staging_rows, sse_rows) from CSV part — aws_s3 into temp when possible, else local read."""
    from .config import get_settings

    sse_path, st_path = part / "sse.csv", part / "staging.csv"
    s = get_settings()
    # Prefer server-side import when parts are on S3 and the extension works.
    if s.env == "aws" and s.processed_bucket and sse_path.exists():
        import csv

        from sqlalchemy import text

        prefix = f"bulk-load/{batch_id}/clean/{part.name}"
        with db.get_engine().connect() as c:
            with sse_path.open(newline="") as f:
                sse_cols = next(csv.reader(f))
            st_cols = []
            if st_path.exists():
                with st_path.open(newline="") as f:
                    st_cols = next(csv.reader(f))
            tmp_sse = _sql_ident(f"lbp_imp_sse_{part.name.replace('-', '_')}")
            tmp_st = _sql_ident(f"lbp_imp_st_{part.name.replace('-', '_')}")
            sse_cols = [_sql_ident(x) for x in sse_cols]
            st_cols = [_sql_ident(x) for x in st_cols]
            c.execute(text(f"DROP TABLE IF EXISTS {tmp_sse}"))
            c.execute(text(f"DROP TABLE IF EXISTS {tmp_st}"))
            c.execute(text(f"CREATE UNLOGGED TABLE {tmp_sse} ({', '.join(f'{x} TEXT' for x in sse_cols)})"))
            if st_cols:
                c.execute(text(f"CREATE UNLOGGED TABLE {tmp_st} ({', '.join(f'{x} TEXT' for x in st_cols)})"))
            c.commit()
            region = _require_aws_region(s)
            ok_sse = _try_aws_s3_import_csv(
                c, tmp_sse, sse_cols, s.processed_bucket, f"{prefix}/sse.csv", region)
            ok_st = (not st_cols) or _try_aws_s3_import_csv(
                c, tmp_st, st_cols, s.processed_bucket, f"{prefix}/staging.csv", region)
            if ok_sse and ok_st:
                sse_rows = [dict(r._mapping) for r in c.execute(text(f"SELECT * FROM {tmp_sse}"))]
                staging = [dict(r._mapping) for r in c.execute(text(f"SELECT * FROM {tmp_st}"))] if st_cols else []
                staging = _normalize_staging_csv_rows(staging)
                c.execute(text(f"DROP TABLE IF EXISTS {tmp_sse}"))
                c.execute(text(f"DROP TABLE IF EXISTS {tmp_st}"))
                c.commit()
                return staging, sse_rows
            c.execute(text(f"DROP TABLE IF EXISTS {tmp_sse}"))
            c.execute(text(f"DROP TABLE IF EXISTS {tmp_st}"))
            c.commit()
    return _normalize_staging_csv_rows(_read_csv(st_path)), _read_csv(sse_path)


def _dup_hold_row(batch_id: str, source_id: str, row: dict, st_by_ln: dict, rule_id: str, rule_name: str, message: str) -> tuple[dict, dict]:
    from .pipeline.batch import DUP_RULES

    ln = str(row.get("loan_number"))
    st = dict(st_by_ln.get(ln) or {
        "batch_id": batch_id, "row_number": row.get("row"), "loan_number": ln, "status": "FAIL",
        "record": {}, "raw": None, "transform_errors": {}, "boarded": False,
        "action": "add", "changes": None, "base_version": None,
    })
    st["status"] = "FAIL"
    st["boarded"] = False
    ex = {
        "exception_id": db.new_id("ex"), "batch_id": batch_id, "source_id": source_id,
        "loan_number": ln, "staging_id": None, "rule_id": rule_id, "rule_version": 1,
        "rule_name": rule_name or DUP_RULES.get(rule_id, rule_id), "category": "duplicate", "severity": "FAIL",
        "blocking": True, "field": "loan_number", "original_value": ln, "message": message,
        "risk": "medium", "tier": "T3", "queue": "ops", "status": "open",
        "proposal": None, "resolved_value": None, "maker": None, "checker": None,
        "qa_sample": False, "created_at": db.now(), "resolved_at": None,
        "_row_number": st.get("row_number"),
    }
    return st, ex


def _apply_clean_sse_batch(batch_id: str, source_id: str, sse_rows: list, staging: list | None,
                           seen: set[str] | None = None) -> tuple[int, int, int]:
    """DUP01 (cross-file via `seen`) + DUP02 split + COPY. Returns (n_st, n_sse, n_dup)."""
    from .pipeline.batch import DUP_RULES
    from .pipeline.loader import copy_insert_exceptions, copy_insert_loans, copy_insert_staging

    if not sse_rows:
        return 0, 0, 0
    if not staging:
        staging = staging_from_sse(batch_id, sse_rows)
    if seen is None:
        seen = set()
    nums = [str(r.get("loan_number")) for r in sse_rows if r.get("loan_number")]
    existing: set[str] = set()
    with db.get_engine().connect() as c:
        for i in range(0, len(nums), 900):
            chunk = nums[i:i + 900]
            existing |= {x for (x,) in c.execute(
                select(db.sse_loans.c.loan_number).where(
                    db.sse_loans.c.loan_number.in_(chunk),
                    db.sse_loans.c.lbp_batch_id != batch_id)).all()}
    keep_sse, keep_st, dup_ex, dup_st = [], [], [], []
    st_by_ln = {str(s.get("loan_number")): s for s in staging}
    n_dup = 0
    for row in sse_rows:
        ln = str(row.get("loan_number"))
        if ln in seen:
            n_dup += 1
            st, ex = _dup_hold_row(
                batch_id, source_id, row, st_by_ln, "DUP01", DUP_RULES["DUP01"],
                f"Loan number {ln} appears more than once in this file")
            dup_st.append(st)
            dup_ex.append(ex)
        elif ln in existing:
            n_dup += 1
            st, ex = _dup_hold_row(
                batch_id, source_id, row, st_by_ln, "DUP02", DUP_RULES["DUP02"],
                f"Loan {ln} was already boarded from another batch.")
            dup_st.append(st)
            dup_ex.append(ex)
        else:
            seen.add(ln)
            keep_sse.append(row)
            if ln in st_by_ln:
                keep_st.append(st_by_ln[ln])
            else:
                keep_st.append(staging_from_sse(batch_id, [row])[0])
    n_st = n_sse = 0
    with db.get_engine().begin() as c:
        if keep_sse:
            for r in keep_sse:
                _revive_sse_row(r)
                r.pop("row", None)
            copy_insert_loans(c, keep_sse)
            n_sse = len(keep_sse)
        if keep_st:
            copy_insert_staging(c, keep_st)
            n_st += len(keep_st)
        if dup_st:
            copy_insert_staging(c, dup_st)
            n_st += len(dup_st)
        if dup_ex:
            rns = [e.pop("_row_number", None) for e in dup_ex]
            id_by_row = {}
            valid = [r for r in rns if r is not None]
            for i in range(0, len(valid), 900):
                chunk = valid[i:i + 900]
                id_by_row.update({r[0]: r[1] for r in c.execute(
                    select(db.loans_staging.c.row_number, db.loans_staging.c.id).where(
                        db.loans_staging.c.batch_id == batch_id,
                        db.loans_staging.c.row_number.in_(chunk))).all()})
            for e, rn in zip(dup_ex, rns, strict=True):
                if rn is not None:
                    e["staging_id"] = id_by_row.get(rn)
                e["created_at"] = _parse_dt(e.get("created_at")) or db.now()
            copy_insert_exceptions(c, dup_ex)
    return n_st, n_sse, n_dup


def _read_sse_csv_file(local_path: str, s3_key: str | None) -> list[dict]:
    """Load one clean SSE CSV via aws_s3 when possible, else local DictReader."""
    from pathlib import Path

    from .config import get_settings

    s = get_settings()
    if s.env == "aws" and s.processed_bucket and s3_key:
        import csv

        from sqlalchemy import text

        with open(local_path, newline="") as f:
            cols = [_sql_ident(c) for c in next(csv.reader(f))]
        tmp = _sql_ident("lbp_imp_sse_" + (s3_key.rsplit("/", 1)[-1].replace("-", "_").replace(".", "_")[:40]))
        with db.get_engine().connect() as c:
            c.execute(text(f"DROP TABLE IF EXISTS {tmp}"))
            c.execute(text(f"CREATE UNLOGGED TABLE {tmp} ({', '.join(f'{x} TEXT' for x in cols)})"))
            c.commit()
            if _try_aws_s3_import_csv(
                c, tmp, cols, s.processed_bucket, s3_key, _require_aws_region(s)):
                rows = [dict(r._mapping) for r in c.execute(text(f"SELECT * FROM {tmp}"))]
                c.execute(text(f"DROP TABLE IF EXISTS {tmp}"))
                c.commit()
                return rows
            c.execute(text(f"DROP TABLE IF EXISTS {tmp}"))
            c.commit()
    return _read_csv(Path(local_path))


def load_clean_files(batch_id: str) -> dict:
    """Driver: coalesced clean/sse/*.csv (preferred) or legacy p-* JSONL/CSV; DUP01/DUP02 held."""
    import shutil

    n_st = n_sse = n_dup = 0
    seen: set[str] = set()
    with db.get_engine().connect() as c:
        source_id = c.execute(select(db.batches.c.source_id).where(db.batches.c.batch_id == batch_id)).scalar()

    coalesced = clean_sse_csv_uris(batch_id)
    if coalesced:
        for local, key in coalesced:
            sse_rows = _read_sse_csv_file(local, key)
            a, b, d = _apply_clean_sse_batch(batch_id, source_id, sse_rows, None, seen=seen)
            n_st += a
            n_sse += b
            n_dup += d
        shutil.rmtree(_bulk_load_root(batch_id) / "clean" / "sse", ignore_errors=True)
        return {"staging": n_st, "sse": n_sse, "dup02": n_dup}

    parts = _list_kind_part_names(batch_id, "clean")
    if not parts:
        return {"staging": 0, "sse": 0, "dup02": 0}
    for name in parts:
        part = _ensure_kind_part(
            batch_id, "clean", name,
            ("staging.csv", "sse.csv", "staging.jsonl", "sse.jsonl"))
        if (part / "sse.csv").exists() or (part / "staging.csv").exists():
            staging, sse_rows = _load_clean_csv_part(batch_id, part)
        else:
            staging = _read_jsonl(part / "staging.jsonl")
            sse_rows = _read_jsonl(part / "sse.jsonl")
        if not staging and not sse_rows:
            continue
        a, b, d = _apply_clean_sse_batch(batch_id, source_id, sse_rows, staging or None, seen=seen)
        n_st += a
        n_sse += b
        n_dup += d
        shutil.rmtree(part, ignore_errors=True)
    return {"staging": n_st, "sse": n_sse, "dup02": n_dup}



def _load_oltp_parts(batch_id: str, cfg) -> None:
    import shutil

    from .exceptions.manager import Triage
    from .pipeline.batch import _persist_chunk

    parts = _list_kind_part_names(batch_id, "oltp")
    if not parts:
        return
    with db.get_engine().connect() as c:
        source_id = c.execute(select(db.batches.c.source_id).where(db.batches.c.batch_id == batch_id)).scalar()
    triage = Triage()
    triage.runtime_set = cfg.runtime_set
    for name in parts:
        part = _ensure_kind_part(batch_id, "oltp", name, ("rows.jsonl",))
        rows = _read_jsonl(part / "rows.jsonl")
        if rows:
            throwaway = {"processed": 0, "passed": 0, "warned": 0, "failed": 0, "loaded": 0}
            _persist_chunk(batch_id, source_id, rows, triage, cfg.pii_cols, throwaway, lambda *_a, **_k: None)
        shutil.rmtree(part, ignore_errors=True)


def _complete_from_staging(batch_id: str, cfg, t0: float, engine: str) -> dict:
    from sqlalchemy import func

    from .pipeline import sequencing
    from .pipeline.batch import reconcile

    st = db.loans_staging
    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
        processed = c.execute(select(func.count()).select_from(st).where(
            st.c.batch_id == batch_id, st.c.row_number.is_not(None))).scalar() or 0
        passed = c.execute(select(func.count()).select_from(st).where(
            st.c.batch_id == batch_id, st.c.status == "PASS")).scalar() or 0
        warned = c.execute(select(func.count()).select_from(st).where(
            st.c.batch_id == batch_id, st.c.status == "WARN")).scalar() or 0
        failed = c.execute(select(func.count()).select_from(st).where(
            st.c.batch_id == batch_id, st.c.status.in_(("FAIL", "REJECTED")))).scalar() or 0
        loaded = c.execute(select(func.count()).select_from(st).where(
            st.c.batch_id == batch_id, st.c.boarded.is_(True))).scalar() or 0
        max_row = c.execute(select(func.max(st.c.row_number)).where(st.c.batch_id == batch_id)).scalar()
    counters = {"processed": processed, "passed": passed, "warned": warned, "failed": failed, "loaded": loaded}
    with db.get_engine().begin() as c:
        rec = reconcile(c, batch_id, processed)
        c.execute(db.batches.update().where(db.batches.c.batch_id == batch_id).values(
            status="completed" if rec["balanced"] else "failed", total_rows=processed, finished_at=db.now(),
            checkpoint=(max_row + 1) if max_row is not None else (b.checkpoint or 0),
            reconciliation=rec, worker_id=None, throughput_lps=round(processed / max(time.monotonic() - t0, 1e-6), 1),
            error=None if rec["balanced"] else "reconciliation mismatch", **counters))
        db.audit(c, "pipeline", "batch.completed", "batch", batch_id,
                 {**counters, "reconciliation": rec, "engine": engine})
        released = sequencing.advance(c, b) if rec["balanced"] else []
    out = {"batch_id": batch_id, **counters, "reconciliation": rec, "released": released}
    emit_metrics(out, time.monotonic() - t0, engine)
    return out


def finalize_bulk(batch_id: str, cfg) -> dict:
    """Driver (same-job / tests): load clean+dirty files if present, reconcile, complete."""
    import shutil

    t0 = time.monotonic()
    if _file_load_on():
        if _spark_db_free_on() or _list_kind_part_names(batch_id, "clean"):
            load_clean_files(batch_id)
        load_dirty_files(batch_id)
        _load_oltp_parts(batch_id, cfg)
        shutil.rmtree(_bulk_load_root(batch_id), ignore_errors=True)
    return _complete_from_staging(batch_id, cfg, t0, "spark-bulk")


def run_load_bulk(batch_id: str, cfg) -> dict:
    """Load job: wipe orphans, COPY clean+dirty from S3 parts, reconcile."""
    import shutil

    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
    if not b:
        raise ValueError(f"unknown batch {batch_id}")
    # "running" allowed: feed_load_job acquires the lease (→ running) after gating on staged.
    if b.status not in ("staged", "failed", "paused", "running"):
        raise ValueError(f"load refuses batch status={b.status!r}; want staged|failed|paused|running")
    t0 = time.monotonic()
    _orphan_cleanup(batch_id, 0)
    # Keep S3/local bulk-load parts — only wipe DB orphans.
    load_clean_files(batch_id)
    load_dirty_files(batch_id)
    _load_oltp_parts(batch_id, cfg)
    shutil.rmtree(_bulk_load_root(batch_id), ignore_errors=True)
    return _complete_from_staging(batch_id, cfg, t0, "glue-load")


def persist_bulk(batch_id: str, cfg, results: Iterable[dict], chunk: int | None = None) -> dict:
    """Driver-side bulk (tests / fallback): ordered chunks via COPY + finalize semantics of persist_partition."""
    chunk = chunk or int(os.environ.get("LBP_PERSIST_CHUNK", "100000"))
    ckpt = begin_bulk(batch_id)
    with db.get_engine().connect() as c:
        source_id = c.execute(select(db.batches.c.source_id).where(db.batches.c.batch_id == batch_id)).scalar()
    buf: list[dict] = []
    for r in results:
        if r["row"] < ckpt:
            continue
        buf.append(r)
        if len(buf) >= chunk:
            persist_partition(batch_id, cfg, buf, checkpoint=ckpt, source_id=source_id)
            buf = []
    if buf:
        persist_partition(batch_id, cfg, buf, checkpoint=ckpt, source_id=source_id)
    return finalize_bulk(batch_id, cfg)


def summary(res: dict) -> str:
    return json.dumps({k: v for k, v in res.items() if k not in ("micro_batch_log",)}, default=str)[:4000]
