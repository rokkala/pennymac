"""Multi-writer safety. Meaningful on a real RDBMS (set LBP_TEST_DATABASE_URL); SQLite serialises anyway."""
import os
import threading

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("LBP_TEST_DATABASE_URL"), reason="needs a real database")


def test_parallel_audit_writers_keep_one_chain(env):
    from lbp.store import db

    errors = []

    def writer(n):
        try:
            for i in range(25):
                with db.get_engine().begin() as c:
                    db.audit(c, f"w{n}", "test.concurrent", "x", f"{n}-{i}")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    before = db.verify_audit_chain()["entries"]
    ts = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    v = db.verify_audit_chain()
    assert v["valid"] and v["entries"] == before + 200


def test_only_one_worker_wins_a_lease(onboarded):
    from lbp.pipeline.batch import _acquire_lease, create_batch

    src = onboarded["pcg_retail"]
    bid = create_batch(src["source_id"], src["path"], "x.csv", "ops")
    wins, barrier = [], threading.Barrier(8)

    def worker(n):
        barrier.wait()
        if _acquire_lease(bid, f"w{n}"):
            wins.append(n)

    ts = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(wins) == 1


def test_sequencing_gate_is_atomic_across_workers(onboarded, tmp_path):
    """8 workers race for two change files of one vendor (sequence 1 and 2): exactly one lease is granted,
    and it is for sequence 1, never 2 ahead of it."""
    from lbp.pipeline.batch import LEASE_FROM, create_batch, run_batch
    from lbp.pipeline.delivery import decide_profile, propose_profile
    from lbp.pipeline.sequencing import acquire

    src = onboarded["pcg_retail"]
    run_batch(create_batch(src["source_id"], src["path"], src["path"].name, "ops"), workers=1)
    propose_profile(src["source_id"], {"load_type": "incremental", "sequence": {"source": "filename", "pattern": r"_(\d+)\.csv$",
                                                                                 "kind": "integer"}}, "a", ["analyst"])
    decide_profile(src["source_id"], "s", ["sme"], True)
    ids = []
    for n in (1, 2):
        p = tmp_path / f"D_{n}.csv"
        p.write_text(f"LoanID,CurrentUPB\nPCG00000001,{n}000\n")
        ids.append(create_batch(src["source_id"], p, p.name, "ops"))
    wins, barrier = [], threading.Barrier(8)

    def worker(n):
        barrier.wait()
        ok, _ = acquire(ids[n % 2], f"w{n}", LEASE_FROM)
        if ok:
            wins.append(ids[n % 2])

    ts = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert wins == [ids[0]]
