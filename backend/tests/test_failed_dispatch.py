"""N1: local-mode dispatchers never start a batch that was recorded as failed (suspended vendor, unsequenceable file)."""
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from lbp import dispatch as dsp
from lbp.store import db
from tests.test_multifile_fileset import BORR, MASTER, T0, _attach, _batches, feed  # noqa: F401
from tests.test_scheduler import CFG, _schedule, clock  # noqa: F401

ADMIN = {"X-User": "admin1", "X-Roles": "admin"}


def _suspend(sid):
    with db.get_engine().begin() as c:
        vid = c.execute(select(db.sources.c.vendor_id).where(db.sources.c.source_id == sid)).scalar()
        c.execute(update(db.vendors).where(db.vendors.c.vendor_id == vid).values(status="suspended"))


@pytest.fixture()
def calls(monkeypatch):
    got = []
    monkeypatch.setattr("lbp.api.main.dispatch", got.append)
    return got


def test_tick_endpoint_skips_swept_failed_set_batch(client, feed, env, calls, monkeypatch):  # noqa: F811
    from lbp.multifile.fileset import sweep_sets
    from lbp.pipeline.delivery import DeliveryError
    from lbp.scheduling import service as sched

    _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    _suspend(feed)
    try:
        _attach(env, feed, "borrowers_20261117.csv", BORR, T0 + timedelta(minutes=1))
    except DeliveryError:
        pass
    bid = sweep_sets(T0 + timedelta(minutes=5))["batches"][0]
    before = _batches(feed)[0]
    assert before.status == "failed" and before.error
    monkeypatch.setattr(sched, "tick", lambda *a, **k: {"batches": [bid]})
    r = client.post("/api/scheduler/tick", headers=ADMIN)
    assert r.status_code == 200 and r.json()["batches"] == [bid]  # still reported
    assert calls == []
    after = _batches(feed)[0]
    assert after.status == "failed" and after.error == before.error


def test_pull_now_skips_failed_scheduled_pull_batch(client, onboarded, clock, env, calls):  # noqa: F811
    import shutil

    src = onboarded["pcg_retail"]
    drop = env / "data" / "dropzone" / "pcg"
    drop.mkdir(parents=True)
    s = _schedule(src["source_id"], {**CFG, "pull": {"protocol": "local", "path": "pcg", "pattern": "PCG_*.csv", "poll_minutes": 15}})
    _suspend(src["source_id"])
    from datetime import datetime
    clock.t = datetime(2030, 1, 7, 5, 0)
    shutil.copy(src["path"], drop / "PCG_20300107.csv")
    r = client.post(f"/api/schedules/{s['schedule_id']}/pull-now", headers=ADMIN)
    assert r.status_code == 200
    bids = r.json()["batches"]
    assert len(bids) == 1 and calls == []
    b = _batches(src["source_id"])[0]
    assert b.batch_id == bids[0] and b.status == "failed" and b.error


def test_tick_endpoint_still_dispatches_queued_batch(client, onboarded, clock, env, calls):  # noqa: F811
    import shutil
    from datetime import datetime

    src = onboarded["pcg_retail"]
    drop = env / "data" / "dropzone" / "pcg"
    drop.mkdir(parents=True)
    s = _schedule(src["source_id"], {**CFG, "pull": {"protocol": "local", "path": "pcg", "pattern": "PCG_*.csv", "poll_minutes": 15}})
    clock.t = datetime(2030, 1, 7, 5, 0)
    shutil.copy(src["path"], drop / "PCG_20300107.csv")
    r = client.post(f"/api/schedules/{s['schedule_id']}/pull-now", headers=ADMIN)
    bids = r.json()["batches"]
    assert len(bids) == 1 and calls == bids
    assert _batches(src["source_id"])[0].status != "failed"


def test_dispatchable_helper(onboarded, sample_files):  # noqa: F811
    from lbp.pipeline.batch import create_batch

    assert dsp.dispatchable([]) == []
    sid = onboarded["pcg_retail"]["source_id"]
    ok = create_batch(sid, str(onboarded["pcg_retail"]["path"]), "PCG_a.csv", "t", strict=False)
    with db.get_engine().begin() as c:
        failed = "B-failed-x"
        row = dict(c.execute(select(db.batches).where(db.batches.c.batch_id == ok)).first()._mapping)
        row.update(batch_id=failed, status="failed")
        c.execute(db.batches.insert().values(**row))
    assert dsp.dispatchable([ok, failed]) == [ok]
    assert dsp.dispatchable([failed]) == []
    assert dsp.dispatchable([failed, ok, "no-such"]) == [ok, "no-such"]
