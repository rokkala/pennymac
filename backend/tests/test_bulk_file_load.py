"""Glue writes dirty rows to files; one load step COPYs staging + exceptions."""
import os

from sqlalchemy import func, select

from lbp import glue_jobs
from lbp.pipeline.batch import create_batch, process_chunk
from lbp.pipeline import loader as ldr
from lbp.store import db


def _batch(bid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first()


def test_begin_bulk_checkpoint_zero_wipes_sse_without_staging(onboarded):
    """Force reopen: leftover sse_loans must die even if staging was already cleared."""
    from sqlalchemy import func

    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "ops")
    with db.get_engine().begin() as c:
        c.execute(db.batches.update().where(db.batches.c.batch_id == bid).values(checkpoint=0))
        c.execute(db.sse_loans.insert().values(
            loan_number="ORPHAN-SSE-01", lbp_batch_id=bid, lbp_source_id=src["source_id"]))
    assert glue_jobs.begin_bulk(bid) == 0
    with db.get_engine().connect() as c:
        n = c.execute(select(func.count()).select_from(db.sse_loans).where(
            db.sse_loans.c.lbp_batch_id == bid)).scalar()
    assert n == 0


def test_copy_insert_exceptions_roundtrip(onboarded):
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "ops")
    row = {
        "exception_id": db.new_id("ex"), "batch_id": bid, "source_id": src["source_id"],
        "loan_number": "PCG00000001", "staging_id": None, "rule_id": "R005", "rule_version": 1,
        "rule_name": "state", "category": "format", "severity": "FAIL", "blocking": True,
        "field": "property_state", "original_value": "XX", "message": "bad", "risk": "medium",
        "tier": "T3", "queue": "ops", "status": "open", "proposal": {"value": "CA"},
        "resolved_value": None, "maker": None, "checker": None, "qa_sample": False,
        "created_at": db.now(), "resolved_at": None,
    }
    with db.get_engine().begin() as c:
        ldr.copy_insert_exceptions(c, [row])
        n = c.execute(select(func.count()).select_from(db.exceptions).where(db.exceptions.c.batch_id == bid)).scalar()
    assert n == 1


def test_persist_partition_file_load_balances_with_exceptions(onboarded, monkeypatch):
    """Dirty path must not OLTP-insert; files + load_dirty_files still balance."""
    from lbp.config import get_settings
    from lbp.ingestion.parser import ParseOptions, iter_rows

    monkeypatch.setenv("LBP_BULK_FILE_LOAD", "1")
    monkeypatch.setenv("LBP_SPARK_DB_FREE", "0")  # same-job clean COPY + dirty files

    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    cfg, _ = glue_jobs.prepare_large(bid)
    key = f"{cfg.mapping_id}:{cfg.mapping_version}|{cfg.rules_key}"
    _, it = iter_rows(src["path"], ParseOptions(**(cfg.parse_options or {})))
    results = process_chunk(list(it), cfg.fields, cfg.runtime_set, 0, key)
    assert any(r.get("fails") or r.get("terrs") for r in results), "fixture needs dirty rows"

    ckpt = glue_jobs.begin_bulk(bid)
    glue_jobs.persist_partition(bid, cfg, results, checkpoint=ckpt, source_id=src["source_id"])
    # Before finalize/load: dirty exceptions must not be in DB yet (file path)
    with db.get_engine().connect() as c:
        pre = c.execute(select(func.count()).select_from(db.exceptions).where(db.exceptions.c.batch_id == bid)).scalar()
    assert pre == 0
    bulk = get_settings().data_dir / "bulk-load" / bid
    assert bulk.exists() and any(bulk.iterdir()), "expected dirty part files"

    res = glue_jobs.finalize_bulk(bid, cfg)  # loads dirty files then reconciles
    done = _batch(bid)
    assert done.status == "completed" and done.reconciliation["balanced"], done.reconciliation
    assert res["loaded"] == done.loaded and done.loaded > 0
    with db.get_engine().connect() as c:
        ex_n = c.execute(select(func.count()).select_from(db.exceptions).where(db.exceptions.c.batch_id == bid)).scalar()
    assert ex_n > 0
