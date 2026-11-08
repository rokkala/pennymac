"""Regression tests for DB-free bulk load data-loss / duplicate bugs."""
import json

from sqlalchemy import func, select

from lbp import glue_jobs
from lbp.config import get_settings
from lbp.pipeline.batch import create_batch, reconcile
from lbp.pipeline.loader import to_sse_row
from lbp.store import db


def _batch(bid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first()


def test_load_dirty_files_inserts_loans_jsonl(onboarded):
    """Boarded dirty adds live in loans.jsonl; load must COPY them into sse_loans."""
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    loan = to_sse_row(
        {"loan_number": "DIRTY-ADD-01", "property_state": "CA"}, bid, "WARN", src["source_id"])
    part = get_settings().data_dir / "bulk-load" / bid / "dirty" / "part-00000"
    part.mkdir(parents=True, exist_ok=True)
    staging = [{
        "batch_id": bid, "row_number": 0, "loan_number": "DIRTY-ADD-01", "status": "WARN",
        "record": {}, "raw": None, "transform_errors": {}, "boarded": True,
        "action": "add", "changes": None, "base_version": None,
    }]
    (part / "staging.jsonl").write_text(json.dumps(staging[0]) + "\n")
    (part / "loans.jsonl").write_text(json.dumps(loan, default=str) + "\n")
    out = glue_jobs.load_dirty_files(bid)
    assert out["loans"] == 1 and out["staging"] == 1
    with db.get_engine().connect() as c:
        n = c.execute(select(func.count()).select_from(db.sse_loans).where(
            db.sse_loans.c.loan_number == "DIRTY-ADD-01")).scalar()
    assert n == 1


def test_load_dirty_files_preserves_oltp_parts(onboarded):
    """Dirty load must not wipe oltp/ — finalize_bulk / run_load_bulk still need those parts."""
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    root = get_settings().data_dir / "bulk-load" / bid
    dirty = root / "dirty" / "part-00000"
    oltp = root / "oltp" / "part-00000"
    dirty.mkdir(parents=True, exist_ok=True)
    oltp.mkdir(parents=True, exist_ok=True)
    (dirty / "staging.jsonl").write_text(json.dumps({
        "batch_id": bid, "row_number": 1, "loan_number": "X1", "status": "FAIL",
        "record": {}, "raw": None, "transform_errors": {}, "boarded": False,
        "action": "add", "changes": None, "base_version": None,
    }) + "\n")
    (oltp / "rows.jsonl").write_text(json.dumps({"row": 2, "action": "update"}) + "\n")
    glue_jobs.load_dirty_files(bid)
    assert (oltp / "rows.jsonl").exists(), "oltp part deleted before _load_oltp_parts"


def test_load_clean_holds_cross_file_dup01(onboarded, monkeypatch):
    monkeypatch.setenv("LBP_SPARK_DB_FREE", "1")
    monkeypatch.setenv("LBP_BULK_FILE_LOAD", "1")
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    row = to_sse_row(
        {"loan_number": "DUP-CROSS-01", "property_state": "TX"}, bid, "PASS", src["source_id"])
    row["row"] = 0
    glue_jobs.write_clean_sse_csv(bid, [row], filename="part-00000.csv")
    row2 = dict(row)
    row2["row"] = 1
    glue_jobs.write_clean_sse_csv(bid, [row2], filename="part-00001.csv")
    out = glue_jobs.load_clean_files(bid)
    with db.get_engine().connect() as c:
        sse_n = c.execute(select(func.count()).select_from(db.sse_loans).where(
            db.sse_loans.c.loan_number == "DUP-CROSS-01")).scalar()
        ex_n = c.execute(select(func.count()).select_from(db.exceptions).where(
            db.exceptions.c.batch_id == bid, db.exceptions.c.rule_id == "DUP01")).scalar()
    assert sse_n == 1
    assert ex_n >= 1
    assert out["sse"] == 1


def test_reconcile_fails_when_boarded_adds_missing_from_sse(onboarded):
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    with db.get_engine().begin() as c:
        c.execute(db.loans_staging.insert().values(
            batch_id=bid, row_number=0, loan_number="MISS-SSE-01", status="PASS",
            record={}, boarded=True, action="add"))
        rec = reconcile(c, bid, 1)
    assert not rec["balanced"], rec
    assert rec["in_sse"] == 0 and rec["boarded"] == 1


def test_dirty_writer_reopen_overwrites_not_appends(onboarded):
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    staging = [{
        "batch_id": bid, "row_number": 0, "loan_number": "W1", "status": "FAIL",
        "record": {}, "raw": None, "transform_errors": {}, "boarded": False,
        "action": "add", "changes": None, "base_version": None,
    }]
    w1 = glue_jobs.open_dirty_part_writer(bid, "part-00000")
    w1(staging, [], [])
    w1.close()
    w2 = glue_jobs.open_dirty_part_writer(bid, "part-00000")
    w2(staging, [], [])
    w2.close()
    path = get_settings().data_dir / "bulk-load" / bid / "dirty" / "part-00000" / "staging.jsonl"
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1, "retry must truncate, not append"


def test_prepare_large_unknown_batch_raises():
    try:
        glue_jobs.prepare_large("bat_does_not_exist")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "unknown batch" in str(e)


def test_jsonl_part_name_is_deterministic_from_rows(onboarded):
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    rows = [{"row": 42, "action": "update", "record": {"loan_number": "U1"}}]
    glue_jobs._write_oltp_part(bid, rows)
    glue_jobs._write_oltp_part(bid, rows)  # retry
    oltp = get_settings().data_dir / "bulk-load" / bid / "oltp"
    parts = [p.name for p in oltp.iterdir() if p.is_dir()]
    assert parts == ["part-00042"], parts


def test_write_clean_sse_csv_retry_overwrites_same_name(onboarded):
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    row = to_sse_row({"loan_number": "CSV-DET-01", "property_state": "FL"}, bid, "PASS", src["source_id"])
    row["row"] = 7
    a = glue_jobs.write_clean_sse_csv(bid, [row])
    b = glue_jobs.write_clean_sse_csv(bid, [row])  # retry
    assert a == b == "part-00007.csv"
    sse = get_settings().data_dir / "bulk-load" / bid / "clean" / "sse"
    assert sorted(p.name for p in sse.glob("*.csv")) == ["part-00007.csv"]


def test_load_dirty_skips_loan_already_in_sse(onboarded):
    """Clean then dirty for the same loan must not unique-violate or double-insert."""
    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "s3")
    loan = to_sse_row(
        {"loan_number": "ALREADY-01", "property_state": "NY"}, bid, "PASS", src["source_id"])
    with db.get_engine().begin() as c:
        c.execute(db.sse_loans.insert().values(**{
            k: loan.get(k) for k in ("loan_number", "property_state", "lbp_batch_id",
                                     "lbp_boarded_at", "lbp_dq_status", "lbp_source_id",
                                     "lbp_status", "lbp_version")}))
    part = get_settings().data_dir / "bulk-load" / bid / "dirty" / "part-00000"
    part.mkdir(parents=True, exist_ok=True)
    (part / "loans.jsonl").write_text(json.dumps(loan, default=str) + "\n")
    (part / "staging.jsonl").write_text(json.dumps({
        "batch_id": bid, "row_number": 0, "loan_number": "ALREADY-01", "status": "WARN",
        "record": {}, "raw": None, "transform_errors": {}, "boarded": True,
        "action": "add", "changes": None, "base_version": None,
    }) + "\n")
    out = glue_jobs.load_dirty_files(bid)
    assert out["loans"] == 0
    with db.get_engine().connect() as c:
        n = c.execute(select(func.count()).select_from(db.sse_loans).where(
            db.sse_loans.c.loan_number == "ALREADY-01")).scalar()
        st = c.execute(select(db.loans_staging.c.boarded, db.loans_staging.c.status).where(
            db.loans_staging.c.batch_id == bid, db.loans_staging.c.loan_number == "ALREADY-01")).first()
        ex = c.execute(select(func.count()).select_from(db.exceptions).where(
            db.exceptions.c.batch_id == bid, db.exceptions.c.rule_id == "DUP01")).scalar()
    assert n == 1 and st.boarded is False and st.status == "FAIL" and ex >= 1


def test_begin_bulk_unknown_batch_raises():
    try:
        glue_jobs.begin_bulk("bat_does_not_exist")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "unknown batch" in str(e)
