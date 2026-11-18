"""Delivery scheduler: cron + calendars, delivery lifecycle, alerts once, maker-checker, pull connectors."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from lbp.scheduling import cron
from lbp.scheduling import service as svc
from lbp.store import db


# ------------------------------------------------------------------ cron
def test_cron_business_days_holidays_and_dst():
    ny = "America/New_York"
    # Thanksgiving 2026-11-26 is skipped on a business-day schedule
    occ = cron.occurrences("0 6 * * MON-FRI", ny, datetime(2026, 11, 23), datetime(2026, 11, 28), "us_federal")
    days = [o.date() for o in occ]
    assert date(2026, 11, 26) not in days and len(days) == 4
    shifted = cron.occurrences("0 6 * * MON-FRI", ny, datetime(2026, 11, 23), datetime(2026, 11, 28), "us_federal", "next_business_day")
    assert len(shifted) == 4  # Thursday's delivery folds into Friday's window
    # wall-clock 06:00 New York stays 06:00 across the DST change (11:00 UTC -> 10:00 UTC)
    occ = cron.occurrences("0 6 * * *", ny, datetime(2026, 3, 6), datetime(2026, 3, 10))
    assert [o.hour for o in occ] == [11, 11, 10, 10]
    # Federal Reserve observance: Sunday -> Monday; Saturday is not moved
    assert date(2022, 6, 20) in cron.us_federal_holidays(2022)
    assert date(2026, 7, 3) not in cron.us_federal_holidays(2026)
    assert cron.is_business_day(date(2026, 12, 24)) and not cron.is_business_day(date(2026, 12, 25))
    assert cron.describe("0 6 * * MON-FRI") == "Business days at 06:00"
    assert cron.describe("15 */4 * * *") == "Every 4 hours at :15"
    nxt = cron.next_after("30 7 1 * *", "UTC", datetime(2026, 11, 2), 2)
    assert nxt == [datetime(2026, 12, 1, 7, 30), datetime(2027, 1, 1, 7, 30)]
    for bad in ("* * *", "61 * * * *", "0 6 * * FUNDAY", "0 6 31-1 * *", "*/0 * * * *"):
        with pytest.raises(cron.CronError):
            cron.parse(bad)
    with pytest.raises(cron.CronError):
        cron.tz_of("Mars/Olympus")


# ------------------------------------------------------------------ lifecycle
class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture()
def clock(monkeypatch):
    c = Clock(datetime(2030, 1, 7, 0, 0))  # a Monday, safely in the future
    monkeypatch.setattr(svc, "_now", c)
    return c


CFG = {"cron": "0 6 * * *", "timezone": "UTC", "calendar": "none", "grace_minutes": 30, "miss_after_minutes": 240,
       "window_before_minutes": 600}


def _schedule(source_id, cfg=None):
    s = svc.create_schedule(source_id, "Daily tape", cfg or CFG, "ops1", ["ops"])
    with pytest.raises(svc.ScheduleError, match="different user"):
        svc.decide(s["schedule_id"], "ops1", ["sme"], True)
    return svc.decide(s["schedule_id"], "sme1", ["sme"], True)


def _deliveries(sid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.deliveries).where(db.deliveries.c.schedule_id == sid).order_by(db.deliveries.c.due_at)).all()


def _alerts(kind):
    with db.get_engine().connect() as c:
        return c.execute(select(db.audit_log).where(db.audit_log.c.action == f"alert.{kind}")).all()


def test_delivery_lifecycle_received_late_missed_and_alerts_once(onboarded, clock):
    from lbp.pipeline.batch import create_batch

    src = onboarded["pcg_retail"]
    s = _schedule(src["source_id"])
    assert s["status"] == "active" and s["describe"] == "Daily at 06:00" and s["next_due"].startswith("2030-01-07T06:00")
    res = svc.tick()
    assert res["materialized"] >= 2
    d = _deliveries(s["schedule_id"])
    assert d[0].due_at == datetime(2030, 1, 7, 6) and d[0].status == "expected"
    # file arrives 05:10 -> received on time
    clock.t = datetime(2030, 1, 7, 5, 10)
    bid = create_batch(src["source_id"], src["path"], src["path"].name, "ops1")
    d = _deliveries(s["schedule_id"])
    assert d[0].status == "received" and d[0].batch_ids == [bid]
    with db.get_engine().connect() as c:
        assert c.execute(select(db.batches.c.delivery_id).where(db.batches.c.batch_id == bid)).scalar() == d[0].delivery_id
    # next day nothing arrives: late after grace (alert once), missed after miss window (alert once)
    clock.t = datetime(2030, 1, 8, 6, 45)
    assert len(svc.tick()["late"]) == 1
    assert svc.tick()["late"] == [] and len(_alerts("delivery_late")) == 1
    clock.t = datetime(2030, 1, 8, 10, 1)
    assert len(svc.tick()["missed"]) == 1 and len(_alerts("delivery_missed")) == 1
    svc.tick()
    assert len(_alerts("delivery_missed")) == 1
    # the file finally lands: received_late
    clock.t = datetime(2030, 1, 8, 13, 0)
    import shutil

    p2 = src["path"].with_name("pcg_day2.csv")
    shutil.copy(src["path"], p2)
    with open(p2, "a") as f:
        f.write("\n")
    create_batch(src["source_id"], p2, p2.name, "ops1", allow_duplicate=True, reason="test")
    d = {x.due_at: x for x in _deliveries(s["schedule_id"])}
    assert d[datetime(2030, 1, 8, 6)].status == "received_late"
    # Ops waives a day the vendor told us is skipped: no alerts for it
    clock.t = datetime(2030, 1, 9, 5, 0)
    svc.tick()
    day3 = {x.due_at: x for x in _deliveries(s["schedule_id"])}[datetime(2030, 1, 9, 6)]
    svc.waive(day3.delivery_id, "ops1", ["ops"], "vendor holiday")
    clock.t = datetime(2030, 1, 9, 12, 0)
    assert svc.tick()["missed"] == []
    # stats + freshness
    sch = svc.get_schedule(s["schedule_id"])
    assert sch["stats_30d"]["received"] == 1 and sch["stats_30d"]["received_late"] == 1
    fr = {v["source_id"]: v for v in svc.vendor_freshness()}[src["source_id"]]
    assert fr["schedules"] == 1 and fr["on_time_pct"] == 50.0


def test_leader_lease_and_idempotent_materialize(onboarded, clock):
    s = _schedule(onboarded["pcg_retail"]["source_id"])
    with db.get_engine().begin() as c:
        c.execute(db.scheduler_state.update().where(db.scheduler_state.c.id == 1).values(owner="other:1", heartbeat_at=clock.t))
    assert "skipped" in svc.tick()
    clock.t += timedelta(minutes=10)  # the other instance stopped heart-beating
    assert "skipped" not in svc.tick()
    n = len(_deliveries(s["schedule_id"]))
    svc.tick()
    assert len(_deliveries(s["schedule_id"])) == n


def test_schedule_validation_and_change_control(onboarded, clock, monkeypatch):
    sid = onboarded["pcg_retail"]["source_id"]
    with pytest.raises(svc.ScheduleError, match="cron"):
        svc.create_schedule(sid, "x", {**CFG, "cron": "0 25 * * *"}, "ops1", ["ops"])
    with pytest.raises(svc.ScheduleError, match="requires"):
        svc.create_schedule(sid, "x", CFG, "comp1", ["compliance"])
    with pytest.raises(svc.ScheduleError, match="miss_after"):
        svc.create_schedule(sid, "x", {**CFG, "grace_minutes": 300, "miss_after_minutes": 60}, "ops1", ["ops"])
    # pull configs: host allow-list, pinned host key, secret prefix
    sftp = {"protocol": "sftp", "host": "sftp.vendor.com", "path": "/out", "pattern": "*.csv", "secret_ref": "other/secret"}
    with pytest.raises(svc.ScheduleError) as e:
        svc.create_schedule(sid, "x", {**CFG, "pull": sftp}, "ops1", ["ops"])
    assert "allowed list" in str(e.value) and "host_key_sha256" in str(e.value) and "secret_ref" in str(e.value)
    s = _schedule(sid)
    svc.propose_change(s["schedule_id"], {**CFG, "cron": "0 7 * * *"}, "ops1", ["ops"])
    assert svc.get_schedule(s["schedule_id"])["config"]["cron"] == "0 6 * * *"  # unchanged until approved
    svc.decide(s["schedule_id"], "sme2", ["sme"], True)
    assert svc.get_schedule(s["schedule_id"])["config"]["cron"] == "0 7 * * *"
    svc.set_status(s["schedule_id"], "ops1", ["ops"], "paused")
    assert svc.tick()["materialized"] == 0
    pv = svc.preview({"cron": "0 6 * * MON-FRI", "timezone": "America/New_York", "calendar": "us_federal"}, 3)
    assert pv["valid"] and len(pv["next"]) == 3 and pv["next"][0]["local"].endswith(("EST", "EDT"))


def test_local_pull_fetches_once_and_registers_batches(onboarded, clock, env, monkeypatch):
    import shutil

    from lbp import config

    src = onboarded["pcg_retail"]
    drop = env / "data" / "dropzone" / "pcg"
    drop.mkdir(parents=True)
    s = _schedule(src["source_id"], {**CFG, "pull": {"protocol": "local", "path": "pcg", "pattern": "PCG_*.csv", "poll_minutes": 15}})
    clock.t = datetime(2030, 1, 7, 5, 0)
    shutil.copy(src["path"], drop / "PCG_20300107.csv")
    (drop / "notes.txt").write_text("ignored: pattern")
    (drop / "PCG_evil.exe").write_text("ignored: extension")
    res = svc.tick()
    assert len(res["batches"]) == 1 and res["pulled"] == ["PCG_20300107.csv"]
    assert _deliveries(s["schedule_id"])[0].status == "received"
    clock.t += timedelta(minutes=20)
    assert svc.tick()["pulled"] == []  # same remote file is never fetched twice
    # a path that escapes the drop root is refused at validation time
    with pytest.raises(svc.ScheduleError, match="inside"):
        svc.create_schedule(src["source_id"], "x", {**CFG, "pull": {"protocol": "local", "path": "../../etc", "pattern": "*"}}, "ops1", ["ops"])
    # connector failures are recorded on the open delivery, never raised into the tick
    shutil.rmtree(drop)
    clock.t = datetime(2030, 1, 8, 5, 0)
    out = svc.tick()
    assert out["pull_errors"] and "does not exist" in out["pull_errors"][0]["error"]
    assert config.get_settings().pull_local_root.name == "dropzone"


def test_s3_pull_with_moto(onboarded, clock, monkeypatch):
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")
    from lbp import config

    monkeypatch.setenv("LBP_PULL_ALLOWED_HOSTS", "s3:vendor-share")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    config.reset_settings()
    src = onboarded["pcg_retail"]
    with moto.mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="vendor-share")
        s3.upload_file(str(src["path"]), "vendor-share", "outbound/PCG_1.csv")
        s3.put_object(Bucket="vendor-share", Key="outbound/archive/PCG_0.csv", Body=b"old")  # sub-folder: ignored
        s = _schedule(src["source_id"], {**CFG, "pull": {"protocol": "s3", "bucket": "vendor-share", "prefix": "outbound/",
                                                         "pattern": "PCG_*.csv"}})
        clock.t = datetime(2030, 1, 7, 5, 0)
        out = svc.pull_now(s["schedule_id"], "ops1", ["ops"])
        assert out["fetched"] == ["outbound/PCG_1.csv"] and len(out["batches"]) == 1


def test_sftp_requires_paramiko_or_pinned_key(onboarded, monkeypatch):
    from lbp import config
    from lbp.scheduling.pullers import PullError, make_puller

    monkeypatch.setenv("LBP_PULL_ALLOWED_HOSTS", "sftp.vendor.com")
    config.reset_settings()
    with pytest.raises(PullError, match="host_key_sha256"):
        make_puller({"protocol": "sftp", "host": "sftp.vendor.com", "path": "/out", "pattern": "*.csv",
                     "secret_ref": "lbp/vendors/pcg"})


def test_new_file_never_fills_an_old_missed_window(onboarded, clock):
    import shutil

    from lbp.pipeline.batch import create_batch

    src = onboarded["pcg_retail"]
    s = _schedule(src["source_id"])
    clock.t = datetime(2030, 1, 12, 5, 30)  # five days without files: Jan 7-11 all missed
    svc.tick()
    p = src["path"].with_name("pcg_jan12.csv")
    shutil.copy(src["path"], p)
    create_batch(src["source_id"], p, p.name, "ops1")
    d = {x.due_at.day: x.status for x in _deliveries(s["schedule_id"])}
    assert d[12] == "received" and all(d[k] == "missed" for k in range(7, 12))
    clock.t = datetime(2030, 1, 12, 9, 0)  # an extra file the same day: unscheduled, it fills no old gap
    with open(p, "a") as f:
        f.write("\n")
    bid = create_batch(src["source_id"], p, "pcg_extra.csv", "ops1", allow_duplicate=True, reason="t")
    d = {x.due_at.day: x.status for x in _deliveries(s["schedule_id"])}
    assert all(d[k] == "missed" for k in range(7, 12))
    with db.get_engine().connect() as c:
        assert c.execute(select(db.batches.c.delivery_id).where(db.batches.c.batch_id == bid)).scalar() is None
    # Jan 12's file never came; a file at 14:00 (before Jan 13's window opens) is Jan 12's late file
    clock.t = datetime(2030, 1, 13, 5, 0)
    svc.tick()
    clock.t = datetime(2030, 1, 13, 7, 0)
    svc.tick()
    clock.t = datetime(2030, 1, 13, 10, 30)
    svc.tick()
    assert {x.due_at.day: x.status for x in _deliveries(s["schedule_id"])}[13] == "missed"
    clock.t = datetime(2030, 1, 13, 14, 0)
    with open(p, "a") as f:
        f.write("\n")
    create_batch(src["source_id"], p, "pcg_late.csv", "ops1", allow_duplicate=True, reason="t")
    assert {x.due_at.day: x.status for x in _deliveries(s["schedule_id"])}[13] == "received_late"
