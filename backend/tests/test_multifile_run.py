"""Join stage inside run_batch (Task 11): a file set is joined once into a CSV, join exceptions are recorded
(masked), the match-rate gate blocks before any load, resume reuses the same joined file, and single-file
feeds never reach the multi-file code."""
import csv
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, update

from lbp import config_store
from lbp.store import db

READY = {"require": "all_required", "pairing": "business_date", "wait_timeout_minutes": 240, "on_timeout": "alert_only"}
DATE = "20261117"
N_MASTER = 12


def _layout(details_min_rate=0.0, payments_required=True):
    return {
        "files": [
            {"role": "master", "entity": "loan", "name_pattern": r"loans_(?P<date>\d{8})\.csv", "key": ["LoanID"], "required": True},
            {"role": "details", "name_pattern": r"details_(?P<date>\d{8})\.csv", "required": True,
             "columns": ["LoanID", "Carrier", "CoSSN"]},
            {"role": "payments", "name_pattern": r"payments_(?P<date>\d{8})\.csv", "required": payments_required},
        ],
        "relations": [
            {"detail": "details", "to": "master", "on": [{"parent": "LoanID", "detail": "LoanID"}], "mode": "merge",
             "on_orphan_detail": "exception", "min_match_rate": details_min_rate},
            {"detail": "payments", "to": "master", "on": [{"parent": "LoanID", "detail": "LoanKey"}], "mode": "aggregate",
             "on_orphan_detail": "drop",
             "aggregate": {"columns": [{"op": "sum", "col": "Amount", "as": "escrow_total"},
                                       {"op": "count", "as": "payment_count"}]}},
        ],
    }


def _master(env) -> tuple[Path, list[str]]:
    from lbp.samples import write_pcg_retail

    p = write_pcg_retail(env / "src" / f"loans_{DATE}.csv", N_MASTER, defect_rate=0.0)
    with p.open() as f:
        ids = [r["LoanID"] for r in csv.DictReader(f)]
    return p, ids


def _write(env, name, header, rows) -> Path:
    p = env / "src" / name
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return p


def _details(env, ids, drop_carrier=False):
    """Loans 0..9 get a detail row; loan 9 gets two (JOIN04); one orphan row (JOIN01) carries an SSN."""
    rows = [[ids[i], f"Carrier{i}", f"{500 + i:03d}12{1000 + i:04d}"] for i in range(10)]
    rows.append([ids[9], "CarrierDup", "500129999"])
    rows.append(["ORPHAN0001", "Nobody", "123-45-6789"])
    header = ["LoanID", "Carrier", "CoSSN"]
    if drop_carrier:
        header = ["LoanID", "CoSSN"]
        rows = [[r[0], r[2]] for r in rows]
    return _write(env, f"details_{DATE}.csv", header, rows)


def _payments(env, ids):
    rows = [[ids[i], amt] for i in range(6) for amt in ("100.10", "50")]
    rows.append(["NOPE", "1"])  # orphan, dropped by policy
    return _write(env, f"payments_{DATE}.csv", ["LoanKey", "Amount"], rows)


def _onboard(master_path) -> str:
    """Feed with an approved mapping that also maps a merged detail column, an aggregate and a detail PII column."""
    from lbp.mapping import service as ms

    reg = ms.register_source("pcg_retail", master_path, "analyst1")
    ms.accept_all(reg["mapping_id"], "analyst1", 0.0)
    with db.get_engine().begin() as c:
        fields = c.execute(select(db.mappings.c.fields).where(db.mappings.c.mapping_id == reg["mapping_id"])).scalar()
        by_target = {f["target"]: f for f in fields}
        extra = {
            "hazard_insurance_carrier": (["details.Carrier"], []),
            "escrow_payment": (["escrow_total"], by_target["escrow_balance"]["transform"]),
            "coborrower_ssn": (["details.CoSSN"], by_target["borrower_ssn"]["transform"]),
        }
        fields = [f for f in fields if f["target"] not in extra]
        for target, (sources, transform) in extra.items():
            fields.append({"source": sources[0], "sources": sources, "target": target, "module": "X", "confidence": 1.0,
                           "transform": transform, "status": "overridden", "manual": True, "reviewed_by": "analyst1"})
        c.execute(update(db.mappings).where(db.mappings.c.mapping_id == reg["mapping_id"]).values(fields=fields))
    ms.submit(reg["mapping_id"], "analyst1")
    ms.approve(reg["mapping_id"], "onboarding.reviewer", ["onboarding_reviewer"])
    return reg["source_id"]


def _configure(sid, layout):
    with db.get_engine().begin() as c:
        c.execute(update(db.sources).where(db.sources.c.source_id == sid).values(layout=layout, readiness=READY))
    config_store.publish(sid, "sme1", "layout")


def _feed(env, layout=None, drop_carrier=False, with_payments=True):
    """Feed + attached files; returns (source_id, batch_id, loan ids). Master attached last."""
    from lbp.multifile.fileset import attach_file

    master, ids = _master(env)
    sid = _onboard(master)
    _configure(sid, layout or _layout())
    if with_payments:
        attach_file(sid, f"payments_{DATE}.csv", _payments(env, ids), "s3-intake")
    out = attach_file(sid, f"details_{DATE}.csv", _details(env, ids, drop_carrier), "s3-intake")
    if with_payments:
        out = attach_file(sid, f"loans_{DATE}.csv", master, "s3-intake")
    return sid, out, ids


def _batch(bid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first()


def _staging(bid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.loans_staging).where(db.loans_staging.c.batch_id == bid)
                         .order_by(db.loans_staging.c.row_number)).all()


def _join_exceptions(bid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.exceptions).where(db.exceptions.c.batch_id == bid, db.exceptions.c.category == "join")
                         .order_by(db.exceptions.c.rule_id)).all()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ------------------------------------------------------------------ tests
def test_run_joined_batch_loads_merged_and_aggregated_fields(env):
    from lbp.pipeline.batch import run_batch

    sid, out, ids = _feed(env)
    bid = out["batch_id"]
    assert out["status"] == "consumed" and bid
    res = run_batch(bid)
    b = _batch(bid)
    assert b.status == "completed", b.error
    assert res["processed"] == N_MASTER - 1  # loan 9 excluded by JOIN04
    assert b.joined_path and Path(b.joined_path).exists()
    with Path(b.joined_path).open(encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert header[0] == "LoanID" and "details.Carrier" in header and "escrow_total" in header and "payment_count" in header
    recs = {s.loan_number: s.record for s in _staging(bid)}
    assert ids[9] not in recs and len(recs) == N_MASTER - 1
    assert recs[ids[0]]["hazard_insurance_carrier"] == "Carrier0"
    assert float(recs[ids[0]]["escrow_payment"]) == pytest.approx(150.1)
    assert recs[ids[7]]["escrow_payment"] in (None, "")  # no payments for loan 7
    assert recs[ids[11]]["hazard_insurance_carrier"] in (None, "")  # left join, no detail
    # joined rows follow master order
    with db.get_engine().connect() as c:
        order = [r[0] for r in c.execute(select(db.loans_staging.c.loan_number).where(db.loans_staging.c.batch_id == bid)
                                         .order_by(db.loans_staging.c.row_number))]
    assert order == [i for i in ids if i != ids[9]]
    js = b.join_summary
    assert js["sha256"] == _sha(b.joined_path) and js["per_role"]["details"]["orphaned"] == 1
    assert js["exception_counts"] == {"JOIN01": 1, "JOIN04": 1}
    assert "layout_version" in js and js["rows_out"] == N_MASTER - 1
    # the drift pre-flight ran on the joined file; detail/aggregate columns are informational, not drift
    assert b.preflight["decision"] != "block"
    assert not [c for c in b.preflight["new_columns"] if c["column"].startswith("details.") or c["column"] == "escrow_total"]


def test_orphan_exceptions_created_and_pii_masked(env):
    from lbp.pipeline.batch import run_batch

    sid, out, ids = _feed(env)
    bid = out["batch_id"]
    run_batch(bid)
    exs = {e.rule_id: e for e in _join_exceptions(bid)}
    assert set(exs) == {"JOIN01", "JOIN04"}
    o = exs["JOIN01"]
    assert o.role == "details" and o.category == "join" and o.blocking is False and o.queue == "join" and o.status == "open"
    raw = json.loads(o.original_value)
    assert raw["Carrier"] == "Nobody"
    assert raw["CoSSN"] != "123-45-6789" and raw["CoSSN"].endswith("6789")  # PII via the mapping (details.CoSSN)
    assert "ORPHAN0001" not in (o.loan_number or "") and (o.loan_number or "").startswith("tok_")  # key fingerprinted
    d = exs["JOIN04"]
    assert d.role == "master" and d.blocking is True
    mraw = json.loads(d.original_value)
    assert mraw["BorrowerSSN"] and "*" in mraw["BorrowerSSN"]  # master PII via the profile
    assert ids[9] not in (d.loan_number or "")
    # nothing in the batch record or audit trail carries row values
    b = _batch(bid)
    blob = json.dumps([b.error, b.join_summary, b.reconciliation], default=str)
    assert "123-45-6789" not in blob and "Nobody" not in blob and "ORPHAN0001" not in blob
    # the unmasked JSONL is gone
    assert not list(Path(b.joined_path).parent.glob("*.jsonl"))
    # staged raw rows of the joined file mask detail PII too
    st = {s.loan_number: s for s in _staging(bid)}[ids[0]]
    assert st.raw["details.CoSSN"] != "500121000" and st.raw["details.CoSSN"].endswith("1000")
    assert st.raw["details.Carrier"] == "Carrier0"


def test_low_match_rate_blocks_before_any_load_and_override_resumes(env):
    from lbp.pipeline.batch import override_preflight, run_batch

    sid, out, ids = _feed(env, layout=_layout(details_min_rate=0.95))
    bid = out["batch_id"]
    res = run_batch(bid)
    b = _batch(bid)
    assert res["status"] == "blocked" and b.status == "blocked"
    assert "min_match_rate" in b.error and "details" in b.error
    assert _staging(bid) == []
    path, sha = b.joined_path, b.join_summary["sha256"]
    assert path and Path(path).exists()
    assert run_batch(bid)["status"] == "blocked"  # still blocked without an override, same file
    assert _batch(bid).joined_path == path and _sha(path) == sha
    override_preflight(bid, "sme1", ["onboarding_reviewer"], "vendor confirmed partial details file")
    run_batch(bid)
    b = _batch(bid)
    assert b.status == "completed", b.error
    assert b.joined_path == path and _sha(path) == sha
    assert len(_staging(bid)) == N_MASTER - 1
    assert [o["stage"] for o in b.join_summary["overrides"]] == ["match_rate"]
    assert b.join_summary["overrides"][0]["actor"] == "sme1"
    assert len(_join_exceptions(bid)) == 2  # recorded once, not again on resume


def test_resume_reuses_same_joined_file(env, monkeypatch):
    from lbp.multifile import joiner
    from lbp.pipeline import batch as pb

    sid, out, ids = _feed(env)
    bid = out["batch_id"]
    calls = {"join": 0, "chunk": 0}
    real_join, real_persist = joiner.join_files, pb._persist_chunk

    def counting_join(*a, **k):
        calls["join"] += 1
        return real_join(*a, **k)

    def dying_persist(*a, **k):
        calls["chunk"] += 1
        if calls["chunk"] == 2:
            raise RuntimeError("worker killed")
        return real_persist(*a, **k)

    monkeypatch.setattr(joiner, "join_files", counting_join)
    monkeypatch.setattr(pb, "_persist_chunk", dying_persist)
    with pytest.raises(RuntimeError):
        pb.run_batch(bid, micro_batch_size=4)
    b = _batch(bid)
    assert b.status == "failed" and b.checkpoint == 4
    path, sha = b.joined_path, _sha(b.joined_path)
    assert sha == b.join_summary["sha256"]
    monkeypatch.setattr(pb, "_persist_chunk", real_persist)
    pb.run_batch(bid, micro_batch_size=4)
    b = _batch(bid)
    assert b.status == "completed", b.error
    assert calls["join"] == 1  # joined once
    assert b.joined_path == path and _sha(path) == sha
    rows = _staging(bid)
    assert len(rows) == N_MASTER - 1 and len({r.loan_number for r in rows}) == N_MASTER - 1
    assert [r.row_number for r in rows] == list(range(N_MASTER - 1))
    assert b.processed == N_MASTER - 1 and b.reconciliation["balanced"] is True
    assert len(_join_exceptions(bid)) == 2


def test_resume_with_changed_joined_file_fails(env, monkeypatch):
    from lbp.pipeline import batch as pb

    sid, out, ids = _feed(env)
    bid = out["batch_id"]
    real = pb._persist_chunk
    n = {"c": 0}

    def dying(*a, **k):
        n["c"] += 1
        if n["c"] == 2:
            raise RuntimeError("worker killed")
        return real(*a, **k)

    monkeypatch.setattr(pb, "_persist_chunk", dying)
    with pytest.raises(RuntimeError):
        pb.run_batch(bid, micro_batch_size=4)
    monkeypatch.setattr(pb, "_persist_chunk", real)
    path = _batch(bid).joined_path
    with open(path, "a", encoding="utf-8") as f:
        f.write("tampered\n")
    with pytest.raises(Exception, match="joined file"):
        pb.run_batch(bid, micro_batch_size=4)
    b = _batch(bid)
    assert b.status == "failed" and "joined file" in b.error and b.checkpoint == 4
    Path(path).unlink()
    with pytest.raises(Exception, match="joined file"):
        pb.run_batch(bid, micro_batch_size=4)


def test_preflight_runs_per_role(env):
    from lbp.pipeline.batch import run_batch

    sid, out, ids = _feed(env, drop_carrier=True)
    bid = out["batch_id"]
    res = run_batch(bid)
    b = _batch(bid)
    assert res["status"] == "blocked" and b.status == "blocked"
    assert "details" in b.error and "Carrier" in b.error
    assert b.preflight["decision"] == "block" and b.preflight["roles"]["details"]["missing"] == ["Carrier"]
    assert _staging(bid) == [] and b.joined_path is None
    # an override accepts this block only; the join then runs and the joined file gets its own drift check
    from lbp.pipeline.batch import override_preflight

    override_preflight(bid, "sme1", ["onboarding_reviewer"], "carrier column retired by the vendor")
    run_batch(bid)
    b = _batch(bid)
    assert b.status == "completed", b.error
    assert [o["stage"] for o in b.join_summary["overrides"]] == ["roles"]
    assert "override" not in b.preflight and b.preflight["join_overrides"][0]["stage"] == "roles"
    assert any(m["column"] == "details.Carrier" for m in b.preflight["missing_columns"])  # drift re-checked


def test_legacy_batch_never_touches_multifile_code(env, sample_files, monkeypatch):
    from lbp.mapping import service as ms
    from lbp.multifile import joiner, stage
    from lbp.pipeline.batch import create_batch, run_batch

    def boom(*a, **k):
        raise AssertionError("multi-file code used for a single-file batch")

    monkeypatch.setattr(stage, "materialize_join", boom)
    monkeypatch.setattr(stage, "join_reconciliation", boom)
    monkeypatch.setattr(joiner, "join_files", boom)
    reg = ms.register_source("correspondent", sample_files["correspondent"], "analyst1")
    ms.accept_all(reg["mapping_id"], "analyst1", 0.0)
    ms.submit(reg["mapping_id"], "analyst1")
    ms.approve(reg["mapping_id"], "onboarding.reviewer", ["onboarding_reviewer"])
    bid = create_batch(reg["source_id"], sample_files["correspondent"], "corr.csv", "ops1")
    run_batch(bid)
    b = _batch(bid)
    assert b.status == "completed", b.error
    assert b.file_set_id is None and b.joined_path is None and b.join_summary is None
    assert "join" not in b.reconciliation


def test_reconciliation_reports_per_role_counts(env):
    from lbp.pipeline.batch import run_batch

    sid, out, ids = _feed(env)
    bid = out["batch_id"]
    run_batch(bid)
    rec = _batch(bid).reconciliation
    j = rec["join"]
    assert j["master_rows_read"] == N_MASTER and j["master_rows_excluded_by_join"] == 1 and j["joined_rows"] == N_MASTER - 1
    assert j["per_role"]["details"] == {"rows_read": 12, "matched": 11, "orphaned": 1, "rejected": 0}
    assert j["per_role"]["payments"] == {"rows_read": 13, "matched": 12, "orphaned": 1, "rejected": 0}
    assert j["per_role"]["master"]["rows_read"] == N_MASTER and j["per_role"]["master"]["rejected"] == 1
    assert j["exceptions"] == {"JOIN01": 1, "JOIN04": 1}
    assert rec["source_rows"] == N_MASTER - 1
    assert rec["source_rows"] + j["master_rows_excluded_by_join"] == j["master_rows_read"]
    assert rec["balanced"] is True and j["balanced"] is True


def test_absent_optional_detail_joins_against_empty_file(env):
    from lbp.multifile.fileset import attach_file, create_batch_for_set
    from lbp.pipeline.batch import run_batch

    master, ids = _master(env)
    sid = _onboard(master)
    _configure(sid, _layout(payments_required=False))
    attach_file(sid, f"details_{DATE}.csv", _details(env, ids), "s3-intake")
    out = attach_file(sid, f"loans_{DATE}.csv", master, "s3-intake")
    assert out["status"] == "waiting"  # all_required waits for every declared file
    with db.get_engine().begin() as c:  # as load_master_only / an accepted partial set would
        c.execute(update(db.file_sets).where(db.file_sets.c.set_id == out["set_id"]).values(status="ready"))
    bid = create_batch_for_set(out["set_id"], "sme1")
    run_batch(bid)
    b = _batch(bid)
    assert b.status == "completed", b.error
    assert b.join_summary["absent_roles"] == ["payments"]
    recs = {s.loan_number: s.record for s in _staging(bid)}
    assert recs[ids[0]]["hazard_insurance_carrier"] == "Carrier0" and recs[ids[0]]["escrow_payment"] in (None, "")
    with Path(b.joined_path).open(encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert "escrow_total" in header and "payment_count" in header
    assert not list(Path(b.joined_path).parent.glob(f"{bid}.*.empty.csv"))


def test_absent_required_role_fails_clearly(env):
    from lbp.pipeline.batch import run_batch

    sid, out, ids = _feed(env)
    bid = out["batch_id"]
    with db.get_engine().begin() as c:
        c.execute(delete(db.batch_files).where(db.batch_files.c.batch_id == bid, db.batch_files.c.role == "details"))
    with pytest.raises(Exception, match="details"):
        run_batch(bid)
    b = _batch(bid)
    assert b.status == "failed" and "details" in b.error and "required" in b.error
    with db.get_engine().connect() as c:
        assert c.execute(select(func.count()).select_from(db.loans_staging).where(db.loans_staging.c.batch_id == bid)).scalar() == 0


# ------------------------------------------------------------------ fix round 1
def test_gate_block_survives_a_crash_after_the_join_is_recorded(env, monkeypatch):
    """The block marker is written with joined_path in one write; a crash right after it still blocks the rerun."""
    from lbp.multifile import stage
    from lbp.pipeline.batch import run_batch

    sid, out, ids = _feed(env, layout=_layout(details_min_rate=0.95))
    bid = out["batch_id"]
    real = stage._record

    def record_then_die(*a, **k):
        real(*a, **k)
        raise RuntimeError("worker killed")

    monkeypatch.setattr(stage, "_record", record_then_die)
    with pytest.raises(RuntimeError):
        run_batch(bid)
    b = _batch(bid)
    assert b.joined_path and b.join_summary["blocked"]["stage"] == "match_rate"
    monkeypatch.setattr(stage, "_record", real)
    with db.get_engine().begin() as c:  # whatever the crash left, the batch is picked up again
        c.execute(update(db.batches).where(db.batches.c.batch_id == bid).values(status="failed"))
    assert run_batch(bid)["status"] == "blocked"
    assert _batch(bid).status == "blocked" and _staging(bid) == []


def test_reuse_rechecks_match_rate_when_the_marker_is_missing(env):
    """A recorded join whose summary lost (or never had) the block marker is re-gated from its recorded rates."""
    from lbp.pipeline.batch import run_batch

    sid, out, ids = _feed(env, layout=_layout(details_min_rate=0.95))
    bid = out["batch_id"]
    assert run_batch(bid)["status"] == "blocked"
    b = _batch(bid)
    for drop_rates in (False, True):
        js = {**b.join_summary, "blocked": None}
        if drop_rates:
            js.pop("master_rate_by_role", None)
        with db.get_engine().begin() as c:  # the state a crash between the two old writes left behind
            c.execute(update(db.batches).where(db.batches.c.batch_id == bid).values(status="queued", join_summary=js, preflight={}))
        assert run_batch(bid)["status"] == "blocked"
        assert _batch(bid).status == "blocked" and _staging(bid) == []


def test_crash_between_exceptions_and_record_does_not_duplicate_exceptions(env, monkeypatch):
    from lbp.multifile import stage
    from lbp.pipeline.batch import run_batch

    sid, out, ids = _feed(env)
    bid = out["batch_id"]
    real = stage._record

    def die(*a, **k):
        raise RuntimeError("worker killed")

    monkeypatch.setattr(stage, "_record", die)
    with pytest.raises(RuntimeError):
        run_batch(bid)
    assert _batch(bid).joined_path is None and len(_join_exceptions(bid)) == 2
    monkeypatch.setattr(stage, "_record", real)
    run_batch(bid)
    b = _batch(bid)
    assert b.status == "completed", b.error
    assert sorted(e.rule_id for e in _join_exceptions(bid)) == ["JOIN01", "JOIN04"]


def test_join_heartbeat_only_refreshes_its_own_lease(env, monkeypatch):
    import time
    from datetime import datetime

    from lbp.multifile import stage
    from lbp.pipeline import batch as pb

    sid, out, ids = _feed(env)
    bid = out["batch_id"]
    old = datetime(2020, 1, 1)
    monkeypatch.setattr(pb, "JOIN_HEARTBEAT_SECONDS", 0.02)
    seen = {}

    def slow_join(batch_id, cfg):
        for owner in ("other-worker:1", None):
            with db.get_engine().begin() as c:
                c.execute(update(db.batches).where(db.batches.c.batch_id == batch_id)
                          .values(heartbeat_at=old, worker_id=owner or seen["mine"]))
            time.sleep(0.2)
            seen[owner or "own"] = _batch(batch_id).heartbeat_at
        return {"status": "blocked", "stage": "roles", "message": "Blocked: test."}

    from lbp.pipeline import sequencing

    orig = sequencing.acquire

    def acquire(batch_id, worker_id, lease_from):
        seen["mine"] = worker_id
        return orig(batch_id, worker_id, lease_from)

    monkeypatch.setattr(sequencing, "acquire", acquire)
    monkeypatch.setattr(stage, "materialize_join", slow_join)
    pb.run_batch(bid)
    assert seen["other-worker:1"] == old  # another worker's lease is never refreshed
    assert seen["own"] > old


def _handlers(monkeypatch):
    import importlib.util
    import sys

    path = Path(__file__).resolve().parents[2] / "aws" / "lambdas" / "handlers.py"
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    spec = importlib.util.spec_from_file_location("handlers", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["handlers"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_route_sends_file_set_batches_to_the_standard_engine(env, monkeypatch):
    from moto import mock_aws

    sid, out, ids = _feed(env)
    bid = out["batch_id"]
    with mock_aws():
        h = _handlers(monkeypatch)
        monkeypatch.setattr(h, "SPARK_THRESHOLD_ROWS", 2)
        assert (_batch(bid).total_rows or 0) > 2
        assert h.route_batch({"batch_id": bid}, None)["engine"] == "standard"
        with db.get_engine().begin() as c:  # the same batch as a single-file batch would go to Spark
            c.execute(update(db.batches).where(db.batches.c.batch_id == bid).values(file_set_id=None))
        assert h.route_batch({"batch_id": bid}, None)["engine"] == "spark"


def test_prepare_large_refuses_file_set_batches(env):
    from lbp import glue_jobs

    sid, out, ids = _feed(env)
    bid = out["batch_id"]
    with pytest.raises(ValueError, match="file set"):
        glue_jobs.prepare_large(bid)
    b = _batch(bid)
    assert b.status == "queued" and b.worker_id is None


def test_replay_of_a_file_set_batch_reads_the_joined_file(env):
    from lbp.pipeline.batch import run_batch
    from lbp.pipeline.replay import replay_batch

    sid, out, ids = _feed(env)
    bid = out["batch_id"]
    run_batch(bid)
    with db.get_engine().begin() as c:  # hold loan 0 again, as if a rule had failed it
        c.execute(update(db.loans_staging).where(db.loans_staging.c.batch_id == bid, db.loans_staging.c.loan_number == ids[0])
                  .values(boarded=False, status="FAIL", record={}))
        c.execute(delete(db.sse_loans).where(db.sse_loans.c.loan_number == ids[0]))
    res = replay_batch(bid, "sme1")
    assert res["replayed"] == 1
    st = {s.loan_number: s for s in _staging(bid)}[ids[0]]
    assert st.record["hazard_insurance_carrier"] == "Carrier0"
    assert float(st.record["escrow_payment"]) == pytest.approx(150.1)
    assert st.raw["details.CoSSN"] != "500121000"
    b = _batch(bid)
    assert "join" in b.reconciliation
    with db.get_engine().begin() as c:  # held again, but the joined file is gone: replay refuses, never the master
        c.execute(update(db.loans_staging).where(db.loans_staging.c.batch_id == bid, db.loans_staging.c.loan_number == ids[0])
                  .values(boarded=False, status="FAIL"))
        c.execute(update(db.batches).where(db.batches.c.batch_id == bid).values(joined_path=None))
    with pytest.raises(Exception, match="joined file"):
        replay_batch(bid, "sme1", dry_run=True)


# ------------------------------------------------------------------ final review I4: joined PII in staged raw rows
def test_joined_pii_cols_falls_back_to_source_column_names():
    """The reviewer's reproduction: aggregate outputs take the PII type of their SOURCE column (name detection)
    or of their `as` name; detail columns and aggregates with no known type are value-checked (DETECT)."""
    from types import SimpleNamespace

    from lbp.ingestion.pii import DETECT_PII
    from lbp.multifile import stage

    lay = {"files": [{"role": "master", "name_pattern": "m.csv", "key": ["loan_id"]}, {"role": "borrowers", "name_pattern": "b.csv"}],
           "relations": [{"detail": "borrowers", "to": "master", "on": [{"parent": "loan_id", "detail": "loan_ref"}], "mode": "aggregate",
                          "aggregate": {"columns": [{"as": "borrower_ssns", "op": "concat_distinct", "col": "ssn"},
                                                    {"as": "names", "op": "first", "col": "borrower_name"},
                                                    {"as": "contact_email", "op": "first", "col": "c1"},
                                                    {"as": "memo", "op": "first", "col": "note"},
                                                    {"as": "n", "op": "count"}]}}]}
    cfg = SimpleNamespace(layout=lay, profile={"columns": []}, fields=[], pii_cols={})
    got = stage.joined_pii_cols(cfg, ["loan_id", "borrower_ssns", "names", "contact_email", "memo", "n", "borrowers.tax_id_no",
                                      "borrowers.note"])
    assert got == {"borrower_ssns": "SSN", "names": "NAME", "contact_email": "EMAIL", "memo": DETECT_PII, "n": DETECT_PII,
                   "borrowers.tax_id_no": "SSN", "borrowers.note": DETECT_PII}


def test_mask_raw_value_checks_detect_columns_and_leaves_legacy_types_alone():
    from lbp.ingestion.pii import DETECT_PII
    from lbp.pipeline.batch import _mask_raw

    raw = {"memo": "ann@example.com", "n": "3", "ids": "123-45-6789|987-65-4321", "plain": "Carrier0", "ssn": "123-45-6789"}
    out = _mask_raw(raw, {"memo": DETECT_PII, "n": DETECT_PII, "ids": DETECT_PII, "plain": DETECT_PII, "ssn": "SSN"})
    assert out["memo"] != "ann@example.com" and out["memo"].endswith("@example.com")
    assert out["n"] == "3" and out["plain"] == "Carrier0" and out["ssn"] == "***-**-6789"
    assert "123-45-6789" not in out["ids"] and "987-65" not in out["ids"]


def test_aggregated_detail_pii_is_masked_in_staged_raw_rows(env):
    from lbp.multifile.fileset import attach_file
    from lbp.pipeline.batch import run_batch

    lay = _layout(payments_required=False)
    lay["files"].append({"role": "borrowers", "name_pattern": r"borrowers_(?P<date>\d{8})\.csv", "required": True})
    lay["relations"].append({"detail": "borrowers", "to": "master", "on": [{"parent": "LoanID", "detail": "LoanRef"}],
                             "mode": "aggregate", "on_orphan_detail": "drop",
                             "aggregate": {"columns": [{"op": "concat_distinct", "col": "ssn", "as": "borrower_ssns"},
                                                       {"op": "first", "col": "borrower_name", "as": "names"},
                                                       {"op": "first", "col": "note", "as": "memo"}]}})
    master, ids = _master(env)
    sid = _onboard(master)
    _configure(sid, lay)
    rows = [[i, f"{600 + n:03d}-45-{1000 + n:04d}", f"Zelda{n}", f"zelda{n}@example.com"] for n, i in enumerate(ids)]
    attach_file(sid, f"borrowers_{DATE}.csv", _write(env, f"borrowers_{DATE}.csv", ["LoanRef", "ssn", "borrower_name", "note"], rows),
                "s3-intake")
    attach_file(sid, f"payments_{DATE}.csv", _payments(env, ids), "s3-intake")
    attach_file(sid, f"details_{DATE}.csv", _details(env, ids), "s3-intake")
    out = attach_file(sid, f"loans_{DATE}.csv", master, "s3-intake")
    run_batch(out["batch_id"])
    assert _batch(out["batch_id"]).status == "completed", _batch(out["batch_id"]).error
    staged = _staging(out["batch_id"])
    assert staged
    blob = json.dumps([s.raw for s in staged])
    assert "Zelda" not in blob and "-45-1000" not in blob and "zelda0@" not in blob
    r0 = staged[0].raw
    assert r0["borrower_ssns"].endswith("1000") and r0["names"].startswith("Z") and r0["memo"].endswith("@example.com")
    assert r0["details.Carrier"] == "Carrier0"  # not PII: kept as is


def test_accept_partial_absent_merge_role_with_mapped_columns_needs_no_second_override(env):
    """Minor (Ruling V, note m): an absent merge role's empty file carries the role's mapped `role.col` source
    columns, so the drift pre-flight does not see them as missing and the accepted set loads without a second
    (pre-flight) override."""
    from lbp.multifile.fileset import attach_file, override_set
    from lbp.pipeline.batch import run_batch

    lay = _layout()
    lay["files"][1].pop("columns")  # nothing declared: the empty header must still hold details.Carrier / details.CoSSN
    master, ids = _master(env)
    sid = _onboard(master)
    _configure(sid, lay)
    attach_file(sid, f"payments_{DATE}.csv", _payments(env, ids), "s3-intake")
    out = attach_file(sid, f"loans_{DATE}.csv", master, "s3-intake")
    assert out["status"] == "waiting"
    acc = override_set(out["set_id"], "accept_partial", "sme1", ["onboarding_reviewer"], "vendor sent no details file today")
    bid = acc["batch_id"]
    run_batch(bid)
    b = _batch(bid)
    assert b.status == "completed", (b.status, b.error, (b.preflight or {}).get("summary"))
    assert b.join_summary["absent_roles"] == ["details"] and not (b.preflight or {}).get("override")
    recs = {s.loan_number: s.record for s in _staging(bid)}
    assert recs[ids[0]]["hazard_insurance_carrier"] in (None, "") and recs[ids[0]]["coborrower_ssn"] in (None, "")
