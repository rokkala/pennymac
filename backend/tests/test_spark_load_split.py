"""Spark DB-free materialize + separate load job (clean/dirty S3 parts)."""
from sqlalchemy import func, select

from lbp import glue_jobs
from lbp.config import get_settings
from lbp.ingestion.parser import ParseOptions, iter_rows
from lbp.pipeline.batch import create_batch, process_chunk
from lbp.store import db


def _batch(bid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first()


def _results(src, cfg):
    key = f"{cfg.mapping_id}:{cfg.mapping_version}|{cfg.rules_key}"
    _, it = iter_rows(src["path"], ParseOptions(**(cfg.parse_options or {})))
    return process_chunk(list(it), cfg.fields, cfg.runtime_set, 0, key)


def test_persist_partition_db_free_writes_clean_and_dirty_without_sse(onboarded, monkeypatch):
    monkeypatch.setenv("LBP_SPARK_DB_FREE", "1")
    monkeypatch.setenv("LBP_BULK_FILE_LOAD", "1")

    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    cfg, _ = glue_jobs.prepare_large(bid)
    results = _results(src, cfg)
    assert any(_cleanish(r) for r in results), "need clean rows"
    assert any(r.get("fails") or r.get("terrs") for r in results), "need dirty rows"

    ckpt = glue_jobs.begin_bulk(bid)
    glue_jobs.persist_partition(bid, cfg, results, checkpoint=ckpt, source_id=src["source_id"])

    with db.get_engine().connect() as c:
        sse_n = c.execute(select(func.count()).select_from(db.sse_loans).where(
            db.sse_loans.c.lbp_batch_id == bid)).scalar()
        st_n = c.execute(select(func.count()).select_from(db.loans_staging).where(
            db.loans_staging.c.batch_id == bid)).scalar()
        ex_n = c.execute(select(func.count()).select_from(db.exceptions).where(
            db.exceptions.c.batch_id == bid)).scalar()
    assert sse_n == 0 and st_n == 0 and ex_n == 0

    root = get_settings().data_dir / "bulk-load" / bid
    assert (root / "clean").exists() and any((root / "clean").iterdir())
    assert (root / "dirty").exists() and any((root / "dirty").iterdir())


def _cleanish(r):
    return r.get("status") in ("PASS", "WARN") and not r.get("fails") and not r.get("terrs")


def test_mark_staged_sets_status(onboarded, monkeypatch):
    monkeypatch.setenv("LBP_SPARK_DB_FREE", "1")
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "ops")
    assert glue_jobs.mark_staged(bid)["status"] == "staged"
    assert _batch(bid).status == "staged"


def test_run_load_bulk_balances_db_free_batch(onboarded, monkeypatch):
    monkeypatch.setenv("LBP_SPARK_DB_FREE", "1")
    monkeypatch.setenv("LBP_BULK_FILE_LOAD", "1")
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    cfg, _ = glue_jobs.prepare_large(bid)
    results = _results(src, cfg)
    ckpt = glue_jobs.begin_bulk(bid)
    glue_jobs.persist_partition(bid, cfg, results, checkpoint=ckpt, source_id=src["source_id"])
    glue_jobs.mark_staged(bid)
    res = glue_jobs.run_load_bulk(bid, cfg)
    done = _batch(bid)
    assert done.status == "completed" and done.reconciliation["balanced"], done.reconciliation
    assert res["loaded"] == done.loaded and done.loaded > 0


def test_load_clean_dup02_does_not_unique_violate(onboarded, monkeypatch):
    monkeypatch.setenv("LBP_SPARK_DB_FREE", "1")
    monkeypatch.setenv("LBP_BULK_FILE_LOAD", "1")
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    cfg, _ = glue_jobs.prepare_large(bid)
    results = _results(src, cfg)
    clean = next(r for r in results if _cleanish(r))
    ln = str(clean["record"]["loan_number"])
    with db.get_engine().begin() as c:
        c.execute(db.sse_loans.insert().values(
            loan_number=ln, lbp_batch_id="bat_other", lbp_source_id=src["source_id"]))
    ckpt = glue_jobs.begin_bulk(bid)
    glue_jobs.persist_partition(bid, cfg, results, checkpoint=ckpt, source_id=src["source_id"])
    glue_jobs.mark_staged(bid)
    glue_jobs.run_load_bulk(bid, cfg)
    with db.get_engine().connect() as c:
        owner = c.execute(select(db.sse_loans.c.lbp_batch_id).where(db.sse_loans.c.loan_number == ln)).scalar()
        ex_n = c.execute(select(func.count()).select_from(db.exceptions).where(
            db.exceptions.c.batch_id == bid, db.exceptions.c.rule_id == "DUP02")).scalar()
    assert owner == "bat_other"
    assert ex_n >= 1


def test_s3_import_persist_writes_clean_csv(onboarded, monkeypatch):
    monkeypatch.setenv("LBP_SPARK_DB_FREE", "1")
    monkeypatch.setenv("LBP_BULK_FILE_LOAD", "1")
    monkeypatch.setenv("LBP_S3_IMPORT", "1")
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    cfg, _ = glue_jobs.prepare_large(bid)
    results = _results(src, cfg)
    ckpt = glue_jobs.begin_bulk(bid)
    glue_jobs.persist_partition(bid, cfg, results, checkpoint=ckpt, source_id=src["source_id"])
    sse_dir = get_settings().data_dir / "bulk-load" / bid / "clean" / "sse"
    assert sse_dir.exists() and any(sse_dir.glob("*.csv")), "expected coalesced clean/sse/*.csv"
    assert not any((get_settings().data_dir / "bulk-load" / bid / "clean").glob("p-*/sse.jsonl"))


def test_dirty_writer_one_part_dir(onboarded, monkeypatch):
    """Spark coalesce path: dirty_writer appends into one part-* dir instead of many uuid dirs."""
    monkeypatch.setenv("LBP_SPARK_DB_FREE", "1")
    monkeypatch.setenv("LBP_BULK_FILE_LOAD", "1")
    monkeypatch.setenv("LBP_S3_IMPORT", "1")
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    cfg, _ = glue_jobs.prepare_large(bid)
    results = _results(src, cfg)
    assert any(r.get("fails") or r.get("terrs") for r in results)
    ckpt = glue_jobs.begin_bulk(bid)
    writer = glue_jobs.open_dirty_part_writer(bid, "part-00000")
    glue_jobs.persist_partition(
        bid, cfg, results, checkpoint=ckpt, source_id=src["source_id"], dirty_writer=writer)
    writer.close()
    dirty = get_settings().data_dir / "bulk-load" / bid / "dirty"
    parts = [p for p in dirty.iterdir() if p.is_dir()]
    assert [p.name for p in parts] == ["part-00000"]
    assert (parts[0] / "staging.jsonl").exists() or (parts[0] / "exceptions.jsonl").exists()


def test_serialize_mapped_rows_skips_triage_on_clean(onboarded, monkeypatch):
    """Thin persist: clean rows → SSE sink only; Triage only for dirty."""
    monkeypatch.setenv("LBP_SPARK_DB_FREE", "1")
    monkeypatch.setenv("LBP_BULK_FILE_LOAD", "1")
    monkeypatch.setenv("LBP_S3_IMPORT", "1")
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    cfg, _ = glue_jobs.prepare_large(bid)
    results = _results(src, cfg)
    clean = [r for r in results if glue_jobs._clean_add(r)]
    dirty = [r for r in results if not glue_jobs._clean_add(r)]
    assert clean and dirty

    calls = {"n": 0}
    real = glue_jobs._materialize_dirty_adds

    def spy(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(glue_jobs, "_materialize_dirty_adds", spy)

    sink, writer = [], glue_jobs.open_dirty_part_writer(bid, "part-00000")
    glue_jobs.serialize_mapped_rows(
        bid, src["source_id"], clean, cfg=cfg, checkpoint=0, clean_sink=sink, dirty_writer=writer)
    assert calls["n"] == 0 and len(sink) == len(clean)
    assert all(s.get("loan_number") and s.get("lbp_batch_id") == bid for s in sink)

    glue_jobs.serialize_mapped_rows(
        bid, src["source_id"], dirty, cfg=cfg, checkpoint=0, clean_sink=sink, dirty_writer=writer)
    writer.close()
    assert calls["n"] == 1
    assert writer.n_st or writer.n_ex


def test_serialize_mapped_rows_load_balances(onboarded, monkeypatch):
    monkeypatch.setenv("LBP_SPARK_DB_FREE", "1")
    monkeypatch.setenv("LBP_BULK_FILE_LOAD", "1")
    monkeypatch.setenv("LBP_S3_IMPORT", "1")
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    cfg, _ = glue_jobs.prepare_large(bid)
    results = _results(src, cfg)
    glue_jobs.begin_bulk(bid)
    sink, writer = [], glue_jobs.open_dirty_part_writer(bid, "part-00000")
    glue_jobs.serialize_mapped_rows(
        bid, src["source_id"], results, cfg=cfg, checkpoint=0, clean_sink=sink, dirty_writer=writer)
    writer.close()
    # write clean CSV like Spark path
    assert sink
    glue_jobs.write_clean_sse_csv(bid, sink, filename="part-00000.csv")
    glue_jobs.mark_staged(bid)
    res = glue_jobs.run_load_bulk(bid, cfg)
    done = _batch(bid)
    assert done.status == "completed" and done.reconciliation["balanced"], done.reconciliation
    assert res["loaded"] == done.loaded and done.loaded > 0


def test_s3_import_run_load_bulk_balances(onboarded, monkeypatch):
    monkeypatch.setenv("LBP_SPARK_DB_FREE", "1")
    monkeypatch.setenv("LBP_BULK_FILE_LOAD", "1")
    monkeypatch.setenv("LBP_S3_IMPORT", "1")
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    cfg, _ = glue_jobs.prepare_large(bid)
    results = _results(src, cfg)
    ckpt = glue_jobs.begin_bulk(bid)
    glue_jobs.persist_partition(bid, cfg, results, checkpoint=ckpt, source_id=src["source_id"])
    glue_jobs.mark_staged(bid)
    res = glue_jobs.run_load_bulk(bid, cfg)
    done = _batch(bid)
    assert done.status == "completed" and done.reconciliation["balanced"], done.reconciliation
    assert res["loaded"] == done.loaded and done.loaded > 0


def test_s3_import_dup02_still_holds(onboarded, monkeypatch):
    monkeypatch.setenv("LBP_SPARK_DB_FREE", "1")
    monkeypatch.setenv("LBP_BULK_FILE_LOAD", "1")
    monkeypatch.setenv("LBP_S3_IMPORT", "1")
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    cfg, _ = glue_jobs.prepare_large(bid)
    results = _results(src, cfg)
    clean = next(r for r in results if _cleanish(r))
    ln = str(clean["record"]["loan_number"])
    with db.get_engine().begin() as c:
        c.execute(db.sse_loans.insert().values(
            loan_number=ln, lbp_batch_id="bat_other", lbp_source_id=src["source_id"]))
    ckpt = glue_jobs.begin_bulk(bid)
    glue_jobs.persist_partition(bid, cfg, results, checkpoint=ckpt, source_id=src["source_id"])
    glue_jobs.mark_staged(bid)
    glue_jobs.run_load_bulk(bid, cfg)
    with db.get_engine().connect() as c:
        owner = c.execute(select(db.sse_loans.c.lbp_batch_id).where(db.sse_loans.c.loan_number == ln)).scalar()
        ex_n = c.execute(select(func.count()).select_from(db.exceptions).where(
            db.exceptions.c.batch_id == bid, db.exceptions.c.rule_id == "DUP02")).scalar()
    assert owner == "bat_other"
    assert ex_n >= 1
