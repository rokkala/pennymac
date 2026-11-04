import csv
from datetime import datetime

import pytest
from sqlalchemy import select

from lbp.exceptions.manager import ExceptionManager
from lbp.mapping import service as ms
from lbp.pipeline.batch import create_batch, run_batch
from lbp.store import db


def _drifted_copy(src, dst, rename=None, reformat=None):
    """Copy a CSV renaming headers and re-formatting ISO date columns to MM/DD/YYYY."""
    rename, reformat = rename or {}, reformat or []
    with open(src) as f, open(dst, "w", newline="") as g:
        r = csv.DictReader(f)
        cols = [rename.get(c, c) for c in r.fieldnames]
        w = csv.DictWriter(g, fieldnames=cols)
        w.writeheader()
        for row in r:
            out = {rename.get(k, k): v for k, v in row.items()}
            for c in reformat:
                if out.get(c):
                    out[c] = datetime.strptime(out[c], "%Y-%m-%d").strftime("%m/%d/%Y")
            w.writerow(out)
    return dst


def _batch(src_id, path):
    bid = create_batch(src_id, path, path.name, "ops1")
    run_batch(bid, workers=1, micro_batch_size=100)
    with db.get_engine().connect() as c:
        return c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first()


def test_drift_blocks_then_remap_and_resume(onboarded, tmp_path):
    src = onboarded["pcg_retail"]
    bad = _drifted_copy(src["path"], tmp_path / "pcg_day2.csv", rename={"NoteRate": "Note_Rate_Pct"}, reformat=["MaturityDate"])
    b = _batch(src["source_id"], bad)
    assert b.status == "blocked"
    pf = b.preflight
    miss = next(m for m in pf["missing_columns"] if m["column"] == "NoteRate")
    assert miss["blocking"] and miss["rename_to"]["column"] == "Note_Rate_Pct"
    td = next(t for t in pf["type_drift"] if t["column"] == "MaturityDate")
    assert td["breaks"] == ["maturity_date"] and td["suggested_date_format"] == "%m/%d/%Y"
    with db.get_engine().connect() as c:
        assert c.execute(select(db.loans_staging).where(db.loans_staging.c.batch_id == b.batch_id)).first() is None  # nothing loaded
    # analyst turns the drift report into a new mapping version; SME approves; batch resumes on it
    draft = ms.remap_from_drift(src["source_id"], {"NoteRate": "Note_Rate_Pct"}, {"MaturityDate": "%m/%d/%Y"}, "analyst1")
    assert draft["version"] == 2
    ms.submit(draft["mapping_id"], "analyst1")
    ms.approve(draft["mapping_id"], "sme1", ["sme"])
    run_batch(b.batch_id, workers=1, micro_batch_size=100)
    with db.get_engine().connect() as c:
        b2 = c.execute(select(db.batches).where(db.batches.c.batch_id == b.batch_id)).first()
    assert b2.status == "completed" and b2.mapping_id == draft["mapping_id"] and b2.reconciliation["balanced"]
    diff = ms.diff_versions(draft["mapping_id"])
    assert {c["target"] for c in diff["changes"]} >= {"interest_rate", "maturity_date"}


def test_drift_override_requires_role(onboarded, tmp_path):
    from lbp.pipeline.batch import override_preflight

    src = onboarded["pcg_retail"]
    b = _batch(src["source_id"], _drifted_copy(src["path"], tmp_path / "x.csv", rename={"LoanID": "LoanIdentifier"}))
    assert b.status == "blocked"
    with pytest.raises(ValueError):
        override_preflight(b.batch_id, "ops1", ["ops"], "need it today")
    override_preflight(b.batch_id, "sme1", ["sme"], "Seller confirmed; loan ids patched downstream")
    run_batch(b.batch_id, workers=1)
    with db.get_engine().connect() as c:
        assert c.execute(select(db.batches.c.status).where(db.batches.c.batch_id == b.batch_id)).scalar() == "completed"


def test_resent_tape_is_flagged_not_overwritten(onboarded):
    src = onboarded["sub_servicing"]
    first = _batch(src["source_id"], src["path"])
    # same tape re-sent: identical bytes are stopped at submission; forcing it through still never overwrites
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "ops1", allow_duplicate=True, reason="test re-send")
    run_batch(bid, workers=1, micro_batch_size=100)
    with db.get_engine().connect() as c:
        again = c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first()
    assert again.loaded == 0 and again.failed == again.processed
    m = ExceptionManager()
    dups = m.list(status="open", rule_id="DUP02", batch_id=again.batch_id, limit=1000)
    assert dups["total"] == first.loaded
    ex = m.get(dups["items"][0]["exception_id"], ["reviewer"])
    assert ex["tier"] == "T4" and "already boarded" in ex["message"] and ex["sse_compare"]["existing_batch_id"] == first.batch_id
    # dual control approves the update
    r = m.resolve(ex["exception_id"], "maker1", ["reviewer"], value=ex["loan_number"])
    assert r["status"] == "pending_checker"
    assert m.checker_decision(ex["exception_id"], "checker1", ["checker"], True)["loan_boarded"]


def test_value_map_editor_and_replay(onboarded, tmp_path):
    from lbp.mapping.inspect import value_coverage, with_value_map
    from lbp.pipeline.replay import replay_batch

    src = onboarded["correspondent"]
    # occupancy arrives as words the shared lookup does not know
    path = tmp_path / "corr_words.csv"
    with open(src["path"]) as f, open(path, "w", newline="") as g:
        r = csv.DictReader(f)
        w = csv.DictWriter(g, fieldnames=r.fieldnames)
        w.writeheader()
        for i, row in enumerate(r):
            if i % 3 == 0:
                row["Occupancy Status"] = "Owner-Occ"
            w.writerow(row)
    b = _batch(src["source_id"], path)
    held_before = b.processed - b.loaded
    # systemic issue explains the spike and points at the value map
    from lbp.analytics.service import systemic_issues

    issue = next(i for i in systemic_issues()["issues"] if i["field"] == "occupancy_type")
    assert issue["action"] == "value_map" and issue["top_value"] == "OWNER-OCC"
    # new mapping version adds the translation
    v2 = ms.new_version(src["source_id"], "analyst1")
    f = next(x for x in v2["fields"] if x["target"] == "occupancy_type")
    ms.update_field(v2["mapping_id"], "occupancy_type", "override", "analyst1", transform=with_value_map(f["transform"], {"Owner-Occ": "P"}))
    ms.accept_all(v2["mapping_id"], "analyst1", 0.0)
    ms.submit(v2["mapping_id"], "analyst1")
    ms.approve(v2["mapping_id"], "sme1", ["sme"])
    cov = value_coverage(v2["mapping_id"], "occupancy_type")
    assert cov["value_map"] == {"owner-occ": "P"}
    preview = replay_batch(b.batch_id, "ops1", dry_run=True)
    assert preview["now_boarded"] >= preview["replayed"] * 0.8 and preview["dry_run"]
    with db.get_engine().connect() as c:
        assert c.execute(select(db.batches.c.loaded).where(db.batches.c.batch_id == b.batch_id)).scalar() == b.loaded  # dry run wrote nothing
    done = replay_batch(b.batch_id, "ops1")
    with db.get_engine().connect() as c:
        b2 = c.execute(select(db.batches).where(db.batches.c.batch_id == b.batch_id)).first()
    assert b2.loaded == b.loaded + done["now_boarded"] and b2.replays and b2.reconciliation["balanced"]
    assert held_before - done["now_boarded"] == done["still_held"]


def test_mapping_memory_learns(env, sample_files, tmp_path):
    a = ms.register_source("PCG Retail", sample_files["pcg_retail"], "analyst1")
    ms.update_field(a["mapping_id"], "borrower_home_phone", "reject", "analyst1")
    ms.add_field(a["mapping_id"], "borrower_cell_phone", "analyst1", ["HomePhone"], [{"op": "digits_only"}])
    ms.accept_all(a["mapping_id"], "analyst1", 0.0)
    ms.submit(a["mapping_id"], "analyst1")
    ms.approve(a["mapping_id"], "sme1", ["sme"])
    # a second seller with the same layout: suggestions come from memory
    b = ms.register_source("PCG Retail – Branch 2", sample_files["pcg_retail"], "analyst1")
    by_t = {s["target"]: s for s in b["suggestions"]}
    assert b["stats"]["memory_hits"] >= 30
    assert by_t["loan_number"]["confidence"] >= 0.93 and "Approved 1× before" in by_t["loan_number"]["rationale"]
    assert by_t["borrower_cell_phone"]["source"] == "HomePhone"          # human correction learned
    assert "borrower_home_phone" not in by_t or by_t["borrower_home_phone"]["source"] != "HomePhone"


def test_identical_file_rejected_and_lease(onboarded):
    from lbp.pipeline.batch import BatchBusyError, DuplicateFileError, _acquire_lease, recover_stale

    src = onboarded["pcg_retail"]
    b = _batch(src["source_id"], src["path"])
    with pytest.raises(DuplicateFileError):
        create_batch(src["source_id"], src["path"], "again.csv", "ops1")
    with pytest.raises(ValueError):
        create_batch(src["source_id"], src["path"], "again.csv", "ops1", allow_duplicate=True)
    bid = create_batch(src["source_id"], src["path"], "again.csv", "ops1", allow_duplicate=True, reason="seller asked to re-board")
    # a second worker cannot take a batch another worker holds
    assert _acquire_lease(bid, "w1") and not _acquire_lease(bid, "w2")
    with pytest.raises(BatchBusyError):
        run_batch(bid, workers=1)
    # the holder dies: after the stale window the batch is requeued and resumes
    from datetime import timedelta
    with db.get_engine().begin() as c:
        c.execute(db.batches.update().where(db.batches.c.batch_id == bid).values(heartbeat_at=db.now() - timedelta(minutes=30)))
    assert recover_stale() == [bid]
    run_batch(bid, workers=1)
    with db.get_engine().connect() as c:
        r = c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first()
    assert r.status == "completed" and r.reconciliation["balanced"] and r.worker_id is None
    assert b.file_sha256 == r.file_sha256


def test_crash_mid_batch_never_double_stages(onboarded, monkeypatch):
    """Kill the pipeline after a micro-batch commits; the resume must not re-stage those rows."""
    from lbp.pipeline import batch as pl

    src = onboarded["sub_servicing"]
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "ops1")
    real = pl._persist_chunk
    calls = {"n": 0}

    def crashing(*a, **k):
        calls["n"] += 1
        out = real(*a, **k)  # commits rows + checkpoint atomically
        if calls["n"] == 2:
            raise RuntimeError("simulated worker crash")
        return out

    monkeypatch.setattr(pl, "_persist_chunk", crashing)
    with pytest.raises(RuntimeError):
        run_batch(bid, workers=1, micro_batch_size=100)
    monkeypatch.setattr(pl, "_persist_chunk", real)
    run_batch(bid, workers=1, micro_batch_size=100)
    with db.get_engine().connect() as c:
        rows = [r[0] for r in c.execute(select(db.loans_staging.c.row_number).where(db.loans_staging.c.batch_id == bid))]
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first()
    assert len(rows) == len(set(rows)) == 300 and b.reconciliation["balanced"]


def test_schema_violation_is_an_exception_not_a_crash(onboarded, tmp_path):
    src = onboarded["pcg_retail"]
    path = tmp_path / "long.csv"
    with open(src["path"]) as f, open(path, "w", newline="") as g:
        r = csv.DictReader(f)
        w = csv.DictWriter(g, fieldnames=r.fieldnames)
        w.writeheader()
        for i, row in enumerate(r):
            if i < 5:
                row["PropertyCounty"] = "X" * 80  # SSE column holds 40
            w.writerow(row)
    b = _batch(src["source_id"], path)
    assert b.status == "completed" and b.reconciliation["balanced"]
    ex = ExceptionManager().list(status="open", rule_id="SCHEMA", batch_id=b.batch_id)
    assert sum(1 for i in ex["items"] if i["field"] == "property_county") == 5
