"""Incremental / snapshot loads, change control and per-vendor sequencing (end to end)."""
import csv

from sqlalchemy import select

from lbp.exceptions.manager import ExceptionManager
from lbp.pipeline import sequencing
from lbp.pipeline.batch import create_batch, run_batch
from lbp.pipeline.delivery import decide_profile, propose_profile
from lbp.store import db

PROFILE = {
    "load_type": "incremental",
    "action": {"mode": "column", "column": "Action", "values": {"A": "add", "C": "update", "D": "close"}},
    "sequence": {"source": "filename", "pattern": r"_(\d+)\.csv$", "kind": "integer", "strict": True},
}


def _set_profile(source_id, profile):
    propose_profile(source_id, profile, "analyst1", ["analyst"])
    decide_profile(source_id, "sme1", ["sme"], True)


def _write(path, cols, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return path


def _run(src_id, path, **kw):
    bid = create_batch(src_id, path, path.name, "ops1", **kw)
    res = run_batch(bid, workers=1, micro_batch_size=100)
    with db.get_engine().connect() as c:
        return c.execute(select(db.batches).where(db.batches.c.batch_id == bid)).first(), res


def _sse(ln):
    with db.get_engine().connect() as c:
        return c.execute(select(db.sse_loans).where(db.sse_loans.c.loan_number == ln)).first()


def _boarded_pcg(onboarded):
    src = onboarded["pcg_retail"]
    rows = list(csv.DictReader(open(src["path"])))
    b, _ = _run(src["source_id"], src["path"])
    assert b.status == "completed"
    with db.get_engine().connect() as c:
        live = {r.loan_number: r for r in c.execute(select(db.sse_loans).where(db.sse_loans.c.lbp_source_id == src["source_id"]))}
    assert live and all(r.lbp_status == "active" and r.lbp_version == 1 for r in live.values())
    by_id = {r["LoanID"]: r for r in rows if r["LoanID"] in live}
    return src, by_id, live


def _pick(by_id, live, n, arm=None):
    out = [k for k, r in by_id.items() if arm is None or (r["AmortizationType"] == "ARM") == arm]
    return out[:n]


def test_incremental_sparse_updates_closes_and_change_control(onboarded, tmp_path):
    src, by_id, live = _boarded_pcg(onboarded)
    sid = src["source_id"]
    _set_profile(sid, PROFILE)
    fixed = _pick(by_id, live, 3, arm=False)
    arm = _pick(by_id, live, 1, arm=True)[0]
    upd, closer, same, rate_fixed = fixed[0], fixed[1], fixed[2], _pick(by_id, live, 4, arm=False)[3]
    cols = ["LoanID", "Action", "CurrentUPB", "NextDueDate", "NoteRate", "InvestorCode"]
    e = {"CurrentUPB": "", "NextDueDate": "", "NoteRate": "", "InvestorCode": ""}
    new_upb = round(float(live[upd].current_principal_balance) - 1234.56, 2)
    rows = [
        {**e, "LoanID": upd, "Action": "C", "CurrentUPB": str(new_upb), "NextDueDate": "2027-01-01"},
        {**e, "LoanID": closer, "Action": "D"},
        {**e, "LoanID": same, "Action": "C", "CurrentUPB": str(live[same].current_principal_balance)},
        {**e, "LoanID": arm, "Action": "C", "NoteRate": "7.875"},     # ARM reset: routine; original rate is set-once
        {**e, "LoanID": rate_fixed, "Action": "C", "CurrentUPB": "99000", "InvestorCode": "FN999"},  # investor change: protected
        {**e, "LoanID": "PCG99999999", "Action": "C", "CurrentUPB": "1000"},   # not in SSE
        {**e, "LoanID": "PCG88888888", "Action": "X"},                         # unrecognised action code
    ]
    b, res = _run(sid, _write(tmp_path / "PCG_DELTA_000001.csv", cols, rows))
    assert b.status == "completed", b.error
    assert b.load_type == "incremental" and b.sequence == "000000000001"
    assert b.preflight["decision"] != "block"
    rec = b.reconciliation
    assert rec["balanced"], rec
    cs = b.change_summary
    assert cs["updates_applied"] == 2 and cs["closes_applied"] == 1 and cs["unchanged_rows"] == 1
    # sparse update: only sent fields changed, everything else intact, version moved
    u = _sse(upd)
    assert float(u.current_principal_balance) == new_upb and str(u.next_payment_due_date) == "2027-01-01"
    assert u.borrower_last_name == live[upd].borrower_last_name and u.lbp_version == 2 and u.lbp_batch_id == live[upd].lbp_batch_id
    assert _sse(closer).lbp_status == "closed" and _sse(closer).lbp_close_reason == "D"
    assert _sse(same).lbp_version == 1
    assert float(_sse(arm).interest_rate) == 7.875
    assert float(_sse(arm).original_interest_rate) == float(live[arm].original_interest_rate) and cs["set_once_ignored"] >= 1
    # protected change: whole update held for dual control, SSE untouched
    assert _sse(rate_fixed).investor_code == live[rate_fixed].investor_code
    assert float(_sse(rate_fixed).current_principal_balance) == float(live[rate_fixed].current_principal_balance)
    em = ExceptionManager()
    ex = {e["rule_id"]: e for e in em.list(status="open", batch_id=b.batch_id, limit=100)["items"]}
    assert ex["CHG01"]["tier"] == "T4" and ex["CHG01"]["field"] == "investor_code" and ex["CHG01"]["proposal"]["value"] == "FN999"
    assert "CHG02" in ex and "ACT01" in ex
    with db.get_engine().connect() as c:
        logged = c.execute(select(db.loan_changes).where(db.loan_changes.c.batch_id == b.batch_id)).all()
    assert {r.action for r in logged} == {"update", "close"}
    assert any(r.loan_number == upd and "current_principal_balance" in r.changes for r in logged)

    # a later file moves the same loan's balance while the protected change is still held
    _run(sid, _write(tmp_path / "PCG_DELTA_000002.csv", cols, [
        {"LoanID": rate_fixed, "Action": "C", "CurrentUPB": "98000", "NextDueDate": "", "NoteRate": ""}]))
    assert float(_sse(rate_fixed).current_principal_balance) == 98000 and _sse(rate_fixed).lbp_version == 2
    # maker + checker approve the investor change: the held balance (99000) conflicts with the newer 98000 -> CHG05
    em.resolve(ex["CHG01"]["exception_id"], "reviewer1", ["reviewer"], use_proposal=True)
    out = em.checker_decision(ex["CHG01"]["exception_id"], "checker1", ["checker"], True)
    assert out["loan_boarded"] is False
    conflict = [e for e in em.list(status="open", rule_id="CHG05", limit=10)["items"] if e["loan_number"] == rate_fixed]
    assert conflict and conflict[0]["field"] == "current_principal_balance"
    assert float(_sse(rate_fixed).current_principal_balance) == 98000
    # reviewer keeps the newer balance: investor change applied, balance stays, version moves once
    out = em.resolve(conflict[0]["exception_id"], "reviewer1", ["reviewer"], value="98000")
    if out["status"] == "pending_checker":
        out = em.checker_decision(conflict[0]["exception_id"], "checker2", ["checker"], True)
    assert out["loan_boarded"] is True
    r = _sse(rate_fixed)
    assert r.investor_code == "FN999" and float(r.current_principal_balance) == 98000 and r.lbp_version == 3

    # CHG02: the reviewer corrects a typo'd loan number and the change lands on the right loan
    target = fixed[0]
    out = em.resolve(ex["CHG02"]["exception_id"], "reviewer1", ["reviewer"], value=target)
    if out["status"] == "pending_checker":
        out = em.checker_decision(ex["CHG02"]["exception_id"], "checker1", ["checker"], True)
    assert out["loan_boarded"] is True and float(_sse(target).current_principal_balance) == 1000


def test_sequencing_gap_wait_release_and_out_of_order(onboarded, tmp_path):
    src, by_id, live = _boarded_pcg(onboarded)
    sid = src["source_id"]
    _set_profile(sid, PROFILE)
    ln = _pick(by_id, live, 1, arm=False)[0]
    cols = ["LoanID", "Action", "CurrentUPB"]

    def f(n, upb):
        return _write(tmp_path / f"PCG_DELTA_{n:06d}.csv", cols, [{"LoanID": ln, "Action": "C", "CurrentUPB": str(upb)}])

    b1, _ = _run(sid, f(1, 1001))
    assert b1.status == "completed"
    b3, r3 = _run(sid, f(3, 3003))                       # file 2 never arrived
    assert b3.status == "waiting" and r3["sequence"]["missing"] == ["2"]
    assert float(_sse(ln).current_principal_balance) == 1001
    b2, r2 = _run(sid, f(2, 2002))                       # the missing file lands, completes and releases file 3
    assert b2.status == "completed" and r2["released"] == [b3.batch_id]
    run_batch(b3.batch_id, workers=1, micro_batch_size=100)
    assert float(_sse(ln).current_principal_balance) == 3003
    # an older file re-sent with different content is held, not applied
    old, _ = _run(sid, _write(tmp_path / "PCG_DELTA_000002b_000002.csv", cols, [{"LoanID": ln, "Action": "C", "CurrentUPB": "2222"}]))
    assert old.status == "out_of_order" and float(_sse(ln).current_principal_balance) == 3003
    sequencing.discard(old.batch_id, "ops1", ["ops"], "superseded resend")
    # a gap can be skipped by Ops with a reason
    b6, _ = _run(sid, f(6, 6006))
    assert b6.status == "waiting"
    sequencing.skip_gap(b6.batch_id, "ops1", ["ops"], "vendor confirmed files 4-5 were never produced")
    run_batch(b6.batch_id, workers=1, micro_batch_size=100)
    assert float(_sse(ln).current_principal_balance) == 6006
    with db.get_engine().connect() as c:
        assert c.execute(select(db.sources.c.last_sequence).where(db.sources.c.source_id == sid)).scalar() == "000000000006"
    # same sequence twice while the first is pending is refused at arrival
    w, _ = _run(sid, f(8, 8008))
    assert w.status == "waiting"
    try:
        create_batch(sid, _write(tmp_path / "PCG_DELTA_x_000008.csv", cols, [{"LoanID": ln, "Action": "C", "CurrentUPB": "1"}]),
                     "PCG_DELTA_x_000008.csv", "ops1")
        raise AssertionError("expected refusal")
    except ValueError as e:
        assert "already pending" in str(e)


def test_out_of_order_override_holds_every_change(onboarded, tmp_path):
    src, by_id, live = _boarded_pcg(onboarded)
    sid = src["source_id"]
    _set_profile(sid, PROFILE)
    ln = _pick(by_id, live, 1, arm=False)[0]
    cols = ["LoanID", "Action", "CurrentUPB"]
    _run(sid, _write(tmp_path / "D_000005.csv", cols, [{"LoanID": ln, "Action": "C", "CurrentUPB": "5005"}]))
    late, _ = _run(sid, _write(tmp_path / "D_000004.csv", cols, [{"LoanID": ln, "Action": "C", "CurrentUPB": "4004"}]))
    assert late.status == "out_of_order"
    sequencing.apply_out_of_order(late.batch_id, "sme1", ["sme"], "file 4 carried a correction we need")
    run_batch(late.batch_id, workers=1, micro_batch_size=100)
    assert float(_sse(ln).current_principal_balance) == 5005  # not overwritten
    ex = ExceptionManager().list(status="open", batch_id=late.batch_id)["items"]
    assert [e["rule_id"] for e in ex] == ["CHG01"] and ex[0]["tier"] == "T4"


def test_preexisting_issue_does_not_block_unrelated_update(onboarded, tmp_path):
    src, by_id, live = _boarded_pcg(onboarded)
    sid = src["source_id"]
    _set_profile(sid, PROFILE)
    ln = _pick(by_id, live, 1, arm=False)[0]
    with db.get_engine().begin() as c:  # an old data issue already sitting in SSE
        c.execute(db.sse_loans.update().where(db.sse_loans.c.loan_number == ln).values(property_state="ZZ"))
    b, _ = _run(sid, _write(tmp_path / "PCG_DELTA_000001.csv", ["LoanID", "Action", "CurrentUPB"],
                            [{"LoanID": ln, "Action": "C", "CurrentUPB": "4321"}]))
    assert float(_sse(ln).current_principal_balance) == 4321
    assert b.change_summary["preexisting_issues"] >= 1 and b.reconciliation["balanced"]


def test_snapshot_diff_adds_updates_unchanged_and_close_reviews(onboarded, tmp_path):
    src, by_id, live = _boarded_pcg(onboarded)
    sid = src["source_id"]
    _set_profile(sid, {"load_type": "snapshot", "sequence": {"source": "filename", "pattern": r"_(\d{8})\.csv$", "kind": "date",
                                                             "strict": False}})
    rows = list(csv.DictReader(open(src["path"])))
    cols = list(rows[0].keys())
    keep = [r for r in rows if r["LoanID"] in live]
    gone = [r["LoanID"] for r in keep[:4]]
    snap = [dict(r) for r in keep[4:]]
    snap[0]["CurrentUPB"] = "11111.11"
    new = dict(snap[1], LoanID="PCG77777777")
    snap.append(new)
    b, _ = _run(sid, _write(tmp_path / "PCG_SNAP_20261102.csv", cols, snap))
    assert b.status == "completed" and b.reconciliation["balanced"], b.reconciliation
    cs = b.change_summary
    assert cs["adds_applied"] == 1 and cs["updates_applied"] == 1 and cs["unchanged_rows"] == len(snap) - 2
    assert cs["snapshot"]["missing"] == 4 and cs["snapshot"]["reviews_raised"] == 4
    em = ExceptionManager()
    reviews = em.list(status="open", rule_id="CHG04", limit=10)["items"]
    assert sorted(e["loan_number"] for e in reviews) == sorted(gone) and all(e["tier"] == "T3" for e in reviews)
    em.resolve(reviews[0]["exception_id"], "reviewer1", ["reviewer"], use_proposal=True)       # confirm the payoff
    assert _sse(reviews[0]["loan_number"]).lbp_status == "closed"
    em.reject_loan(reviews[1]["exception_id"], "reviewer1", ["reviewer"], "loan still serviced; vendor omission")
    assert _sse(reviews[1]["loan_number"]).lbp_status == "active"
    # a truncated snapshot (half the portfolio missing) raises no close reviews and is flagged
    b2, _ = _run(sid, _write(tmp_path / "PCG_SNAP_20261103.csv", cols, snap[: len(snap) // 3]))
    assert b2.change_summary["snapshot"]["truncation_suspected"] is True
    assert len(em.list(status="open", rule_id="CHG04", limit=100)["items"]) == 2


def test_resent_defect_does_not_undo_a_human_correction(onboarded, tmp_path):
    """A reviewer corrected a value at boarding; the vendor's next snapshot re-sends the original bad value.
    The correction stands (no change, no exception) instead of regressing SSE or re-asking the reviewer."""
    src = onboarded["pcg_retail"]
    sid = src["source_id"]
    rows = list(csv.DictReader(open(src["path"])))
    rows[0]["PropertyCity"] = "Columbsu"                       # defect in the boarding tape
    tape = _write(tmp_path / "pcg_tape.csv", list(rows[0].keys()), rows)
    b, _ = _run(sid, tape)
    em = ExceptionManager()
    ln = rows[0]["LoanID"]
    with db.get_engine().begin() as c:  # a reviewer fixed it (recorded like any human resolution)
        st_id = c.execute(select(db.loans_staging.c.id).where(db.loans_staging.c.batch_id == b.batch_id, db.loans_staging.c.loan_number == ln)).scalar()
        c.execute(db.exceptions.insert().values(exception_id="ex_fix", batch_id=b.batch_id, source_id=sid, loan_number=ln, staging_id=st_id,
                                                rule_id="R099", field="property_city", original_value="Columbsu", resolved_value="Columbus",
                                                status="resolved", tier="T3", blocking=True))
        c.execute(db.sse_loans.update().where(db.sse_loans.c.loan_number == ln).values(property_city="Columbus"))
    _set_profile(sid, {"load_type": "snapshot", "sequence": {"source": "none"}})
    b2, _ = _run(sid, _write(tmp_path / "pcg_snap.csv", list(rows[0].keys()), [r for r in rows if _sse(r["LoanID"])]))
    assert _sse(ln).property_city == "Columbus"
    assert b2.change_summary["corrections_kept"] >= 1
    assert not [e for e in em.list(status="open", batch_id=b2.batch_id, limit=500)["items"] if e["loan_number"] == ln]
