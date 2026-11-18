"""Feed lifecycle: archive / restore, discard a draft mapping, delete a never-used feed, and every intake
path refusing an archived feed."""
from datetime import datetime

import pytest
from sqlalchemy import select, update

from lbp import config_store, lifecycle
from lbp import vendors as vendor_svc
from lbp.lifecycle import FeedArchivedError, LifecycleError
from lbp.mapping import service as ms
from lbp.multifile import fileset
from lbp.scheduling import service as sched
from lbp.store import db

MEMBER = ["onboarding"]
REVIEWER = ["onboarding_reviewer"]
ADMIN = ["admin"]
WHY = "vendor retired this feed"
OPS = {"X-User": "oli", "X-Roles": "monitoring"}
ONB = {"X-User": "ona", "X-Roles": "onboarding"}
ADM = {"X-User": "ada", "X-Roles": "admin"}
LAYOUT = {
    "files": [
        {"role": "master", "entity": "loan", "name_pattern": r"loans_(?P<date>\d{8})\.csv", "key": ["loan_id"], "required": True},
        {"role": "borrowers", "name_pattern": r"borrowers_(?P<date>\d{8})\.csv", "required": True},
    ],
    "relations": [{"detail": "borrowers", "to": "master", "on": [{"parent": "loan_id", "detail": "loan_id"}], "mode": "merge"}],
}
READY = {"require": "all_required", "pairing": "business_date", "wait_timeout_minutes": 240, "on_timeout": "alert_only"}
CFG = {"cron": "0 6 * * *", "timezone": "UTC", "calendar": "none", "grace_minutes": 30, "miss_after_minutes": 240,
       "window_before_minutes": 600}


def _draft_feed(sample_files, name="pcg_retail", vendor_id=None):
    """A feed with a draft mapping only (status 'mapping')."""
    return ms.register_source(name, sample_files["pcg_retail"], "analyst1", vendor_id=vendor_id)


def _live_feed(sample_files, name="pcg_retail", vendor_id=None):
    reg = _draft_feed(sample_files, name, vendor_id)
    ms.accept_all(reg["mapping_id"], "analyst1", 0.0)
    ms.submit(reg["mapping_id"], "analyst1")
    ms.approve(reg["mapping_id"], "onboarding.reviewer", ["onboarding_reviewer"])
    return reg["source_id"]


def _src(sid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.sources).where(db.sources.c.source_id == sid)).first()


def _audit(action, entity_id=None):
    with db.get_engine().connect() as c:
        q = select(db.audit_log).where(db.audit_log.c.action == action)
        if entity_id:
            q = q.where(db.audit_log.c.entity_id == entity_id)
        return c.execute(q).all()


def _schedule(sid, cfg=None):
    s = sched.create_schedule(sid, "Daily tape", cfg or CFG, "ops1", ["ops"])
    return sched.decide(s["schedule_id"], "sme1", ["sme"], True)


def _batch(sid, status):
    with db.get_engine().begin() as c:
        c.execute(db.batches.insert().values(batch_id=db.new_id("bat"), source_id=sid, filename="f.csv", status=status))


def _multifile(sid):
    with db.get_engine().begin() as c:
        c.execute(update(db.sources).where(db.sources.c.source_id == sid).values(layout=LAYOUT, readiness=READY))
    config_store.publish(sid, "sme1", "layout")


# ------------------------------------------------------------------ archive
def test_archive_hides_feed_and_pauses_schedule(sample_files):
    sid = _live_feed(sample_files)
    s = _schedule(sid)
    out = lifecycle.archive_feed(sid, "ona", REVIEWER, WHY)
    row = _src(sid)
    assert out["status"] == "retired" and row.status == "retired" and row.retired_from_status == "live"
    assert row.retired_by == "ona" and row.retired_reason == WHY and row.retired_at is not None
    assert sched.get_schedule(s["schedule_id"])["status"] == "paused"
    a = _audit("source.archive", sid)
    assert len(a) == 1 and a[0].detail["reason"] == WHY and a[0].detail["paused_schedules"] == [s["schedule_id"]]
    with pytest.raises(LifecycleError, match="already archived"):
        lifecycle.archive_feed(sid, "ona", REVIEWER, WHY)


@pytest.mark.parametrize("status", ["running", "claimed", "pausing", "waiting", "queued", "staged", "paused"])
def test_archive_refused_while_batch_in_progress(sample_files, status):
    sid = _live_feed(sample_files)
    _batch(sid, status)
    with pytest.raises(LifecycleError, match="in progress"):
        lifecycle.archive_feed(sid, "ona", REVIEWER, WHY)
    assert _src(sid).status == "live"  # nothing partially archived
    assert not _audit("source.archive", sid)


def test_archive_allows_finished_batches(sample_files):
    sid = _live_feed(sample_files)
    _batch(sid, "completed")
    _batch(sid, "failed")
    assert lifecycle.archive_feed(sid, "ona", REVIEWER, WHY)["status"] == "retired"


def test_archive_refused_while_fileset_waiting(env, sample_files):
    sid = _live_feed(sample_files)
    _multifile(sid)
    d = env / "incoming"
    d.mkdir()
    (d / "loans_20261117.csv").write_text("loan_id,amount\n1,100\n")
    s = _schedule(sid)
    r = fileset.attach_file(sid, "loans_20261117.csv", d / "loans_20261117.csv", "s3-intake", arrived_at=datetime(2026, 11, 17, 8))
    assert r["status"] == "waiting"
    with pytest.raises(LifecycleError, match="still waiting"):
        lifecycle.archive_feed(sid, "ona", REVIEWER, WHY)
    row = _src(sid)
    assert row.status == "live" and row.retired_at is None
    assert sched.get_schedule(s["schedule_id"])["status"] == "active"  # nothing partially archived


@pytest.mark.parametrize("reason", ["", "   ", "abcd", None])
def test_archive_requires_reason_min_5(sample_files, reason):
    sid = _draft_feed(sample_files)["source_id"]
    with pytest.raises(LifecycleError, match="reason"):
        lifecycle.archive_feed(sid, "ona", MEMBER, reason)
    assert _src(sid).status == "mapping"
    for fn in (lifecycle.restore_feed, lifecycle.delete_feed):
        with pytest.raises(LifecycleError, match="reason"):
            fn(sid, "ada", ADMIN, "1234")
    assert lifecycle.archive_feed(sid, "ona", MEMBER, "12345")["status"] == "retired"


def test_live_feed_archive_needs_reviewer_role(sample_files):
    live = _live_feed(sample_files)
    with pytest.raises(LifecycleError, match="onboarding_reviewer"):
        lifecycle.archive_feed(live, "ona", ["onboarding"], WHY)
    with pytest.raises(LifecycleError, match="requires"):
        lifecycle.archive_feed(live, "mo", ["monitoring"], WHY)
    assert _src(live).status == "live"
    assert lifecycle.archive_feed(live, "rev", ["onboarding_reviewer"], WHY)["status"] == "retired"
    # a feed that never went live: the member role is enough
    draft = _draft_feed(sample_files, "other_feed", _src(live).vendor_id)["source_id"]
    assert lifecycle.archive_feed(draft, "ona", ["onboarding"], WHY)["status"] == "retired"


# ------------------------------------------------------------------ restore
def test_restore_returns_previous_status_and_unarchives(sample_files):
    live = _live_feed(sample_files)
    draft = _draft_feed(sample_files, "second", _src(live).vendor_id)["source_id"]
    lifecycle.archive_feed(live, "rev", REVIEWER, WHY)
    lifecycle.archive_feed(draft, "ona", MEMBER, WHY)
    with pytest.raises(LifecycleError, match="onboarding_reviewer"):  # restoring a live feed: reviewer rule too
        lifecycle.restore_feed(live, "ona", MEMBER, "bring it back")
    assert lifecycle.restore_feed(live, "rev", REVIEWER, "bring it back")["status"] == "live"
    assert lifecycle.restore_feed(draft, "ona", MEMBER, "bring it back")["status"] == "mapping"
    for sid in (live, draft):
        r = _src(sid)
        assert r.retired_at is None and r.retired_by is None and r.retired_reason is None and r.retired_from_status is None
    assert _src(live).active_mapping_id  # still its approved mapping
    assert _audit("source.restore", live)[0].detail["reason"] == "bring it back"
    with pytest.raises(LifecycleError, match="not archived"):
        lifecycle.restore_feed(live, "rev", REVIEWER, "bring it back")


def test_restore_name_clash_refused(sample_files):
    first = _live_feed(sample_files, "Tape")
    vid = _src(first).vendor_id
    lifecycle.archive_feed(first, "rev", REVIEWER, WHY)
    # registering the name while an archived feed holds it is refused, saying so
    with pytest.raises(ms.MappingError, match="archived feed named 'Tape'"):
        ms.register_source("Tape", sample_files["pcg_retail"], "analyst1", vendor_id=vid)
    # a newer feed can still end up with the name (here: a rename done in the database)
    second = _draft_feed(sample_files, "Tape 2", vid)["source_id"]
    with db.get_engine().begin() as c:
        c.execute(update(db.sources).where(db.sources.c.source_id == second).values(name="Tape"))
    with pytest.raises(LifecycleError, match="another feed named 'Tape'"):
        lifecycle.restore_feed(first, "rev", REVIEWER, "bring it back")
    assert _src(first).status == "retired"
    lifecycle.archive_feed(second, "ona", MEMBER, WHY)
    with pytest.raises(ms.MappingError, match="archived feed named 'Tape'"):
        ms.register_source("Tape", sample_files["pcg_retail"], "analyst1", vendor_id=vid)
    lifecycle.restore_feed(first, "rev", REVIEWER, "bring it back")  # the clash is archived too now: fine
    assert _src(first).status == "live"


# ------------------------------------------------------------------ intake paths
def test_upload_to_archived_feed_409(client, sample_files):
    sid = _live_feed(sample_files)
    lifecycle.archive_feed(sid, "rev", REVIEWER, WHY)
    with open(sample_files["pcg_retail"], "rb") as f:
        r = client.post("/api/upload", data={"source_id": sid}, files={"file": ("a.csv", f)}, headers=OPS)
    assert r.status_code == 409 and "archived" in r.json()["detail"]
    with db.get_engine().connect() as c:
        assert c.execute(select(db.batches)).first() is None
    # create_batch itself (S3 arrival, scheduler, replay) refuses too
    from lbp.pipeline.batch import create_batch

    with pytest.raises(FeedArchivedError):
        create_batch(sid, sample_files["pcg_retail"], "a.csv", "ops", strict=False)
    # restored: accepted again
    lifecycle.restore_feed(sid, "rev", REVIEWER, "bring it back")
    with open(sample_files["pcg_retail"], "rb") as f:
        assert client.post("/api/upload", data={"source_id": sid, "auto_start": "false"}, files={"file": ("a.csv", f)},
                           headers=OPS).status_code == 200


def test_zip_set_upload_to_archived_feed_409(client, sample_files):
    import io
    import zipfile

    sid = _live_feed(sample_files)
    _multifile(sid)
    lifecycle.archive_feed(sid, "rev", REVIEWER, WHY)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("loans_20261117.csv", "loan_id,amount\n1,100\n")
        z.writestr("borrowers_20261117.csv", "loan_id,name\n1,Ann\n")
    r = client.post("/api/upload/set", data={"source_id": sid}, files=[("files", ("d.zip", buf.getvalue(), "application/zip"))], headers=OPS)
    assert r.status_code == 409 and "archived" in r.json()["detail"]
    r = client.post("/api/upload", data={"source_id": sid}, files={"file": ("loans_20261117.csv", b"loan_id,amount\n1,1\n")}, headers=OPS)
    assert r.status_code == 409
    with db.get_engine().connect() as c:
        assert c.execute(select(db.file_sets)).first() is None


def test_attach_file_archived_rejected(env, sample_files):
    sid = _live_feed(sample_files)
    _multifile(sid)
    lifecycle.archive_feed(sid, "rev", REVIEWER, WHY)
    d = env / "incoming"
    d.mkdir()
    (d / "loans_20261117.csv").write_text("loan_id,amount\n1,100\n")
    with pytest.raises(FeedArchivedError, match="archived"):
        fileset.attach_file(sid, "loans_20261117.csv", d / "loans_20261117.csv", "s3-intake", arrived_at=datetime(2026, 11, 17, 8))
    with pytest.raises(FeedArchivedError):
        fileset.attach_file(sid, "loans_20261117.csv", d / "loans_20261117.csv", "s3-intake", role="master")
    with db.get_engine().connect() as c:
        assert c.execute(select(db.file_sets)).first() is None and c.execute(select(db.batch_files)).first() is None
    assert "FeedArchivedError" in fileset.safe_message(FeedArchivedError("feed 'x' is archived"))  # safe text for alerts


def test_scheduler_tick_skips_archived_feed(sample_files, monkeypatch):
    sid = _live_feed(sample_files)
    s = _schedule(sid)
    monkeypatch.setattr(sched, "_now", lambda: datetime(2030, 1, 7, 0, 0))
    lifecycle.archive_feed(sid, "rev", REVIEWER, WHY)
    # even a schedule left active (e.g. by a restore race or a hand edit) expects nothing from an archived feed
    with db.get_engine().begin() as c:
        c.execute(update(db.delivery_schedules).where(db.delivery_schedules.c.schedule_id == s["schedule_id"]).values(status="active"))
    res = sched.tick()
    assert res["materialized"] == 0 and res["pulled"] == []
    with db.get_engine().connect() as c:
        assert c.execute(select(db.deliveries).where(db.deliveries.c.source_id == sid)).first() is None


def test_pull_now_archived_409(client, sample_files):
    sid = _live_feed(sample_files)
    s = _schedule(sid, {**CFG, "pull": {"protocol": "local", "path": "pcg", "pattern": "PCG_*.csv"}})
    lifecycle.archive_feed(sid, "rev", REVIEWER, WHY)
    r = client.post(f"/api/schedules/{s['schedule_id']}/pull-now", headers=OPS)
    assert r.status_code == 409 and "archived" in r.json()["detail"]
    with pytest.raises(FeedArchivedError):
        sched.pull_now(s["schedule_id"], "ops1", ["ops"])


def test_s3_arrival_for_archived_feed_is_rejected(sample_files, monkeypatch):
    import sys
    import types

    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *a, **k: types.SimpleNamespace(head_object=lambda **kw: {"Metadata": {}})
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "aws" / "lambdas"))
    try:
        import handlers
    finally:
        sys.path.pop(0)
    sid = _live_feed(sample_files)
    lifecycle.archive_feed(sid, "rev", REVIEWER, WHY)
    ev = {"detail": {"bucket": {"name": "raw"}, "object": {"key": f"incoming/{sid}/x_a.csv"}}}
    out = handlers.on_file_arrival(ev, None)
    assert "archived" in out["rejected"] and "batch_id" not in out
    assert _audit("alert.file_rejected")
    with db.get_engine().connect() as c:
        assert c.execute(select(db.batches)).first() is None


# ------------------------------------------------------------------ mappings
def test_discard_draft_ok_approved_refused_in_review_refused(sample_files):
    reg = _draft_feed(sample_files)
    sid, m1 = reg["source_id"], reg["mapping_id"]
    ms.accept_all(m1, "analyst1", 0.0)
    ms.submit(m1, "analyst1")
    with pytest.raises(LifecycleError, match="awaiting review"):
        lifecycle.discard_mapping(m1, "ona", MEMBER, WHY)
    ms.approve(m1, "onboarding.reviewer", ["onboarding_reviewer"])
    with pytest.raises(LifecycleError, match="approved"):
        lifecycle.discard_mapping(m1, "ona", MEMBER, WHY)
    v2 = ms.new_version(sid, "analyst1")["mapping_id"]
    with pytest.raises(LifecycleError, match="reason"):
        lifecycle.discard_mapping(v2, "ona", MEMBER, "no")
    with pytest.raises(LifecycleError, match="requires"):
        lifecycle.discard_mapping(v2, "mo", ["monitoring"], WHY)
    out = lifecycle.discard_mapping(v2, "ona", MEMBER, WHY)
    assert out["status"] == "discarded" and ms.get_mapping(v2)["status"] == "discarded"
    assert _audit("mapping.discard", v2)[0].detail["reason"] == WHY
    with pytest.raises(LifecycleError, match="draft"):
        lifecycle.discard_mapping(v2, "ona", MEMBER, WHY)
    with pytest.raises(LifecycleError, match="not found"):
        lifecycle.discard_mapping("map_nope", "ona", MEMBER, WHY)
    assert _src(sid).active_mapping_id == m1  # the live mapping is untouched


def test_new_version_after_discarding_only_draft_uses_last_non_discarded_or_errors_clearly(sample_files):
    # a feed whose only mapping is a discarded draft: clear error, nothing created
    reg = _draft_feed(sample_files)
    lifecycle.discard_mapping(reg["mapping_id"], "ona", MEMBER, WHY)
    with pytest.raises(ms.MappingError, match="no mapping to base a new version on"):
        ms.new_version(reg["source_id"], "ona")
    # a live feed: v1 approved, v2 discarded -> the new draft builds on v1 and takes the next version number
    sid = _live_feed(sample_files, "live_one")
    with db.get_engine().connect() as c:
        v1 = c.execute(select(db.mappings).where(db.mappings.c.source_id == sid)).first()
    v2 = ms.new_version(sid, "ana")
    lifecycle.discard_mapping(v2["mapping_id"], "ona", MEMBER, WHY)
    v3 = ms.new_version(sid, "ana")
    assert v3["version"] == 3 and v3["status"] == "draft" and v3["fields"] == v1.fields
    assert _audit("mapping.new_version", v3["mapping_id"])[0].detail["from"] == v1.mapping_id
    with pytest.raises(ms.MappingError, match="draft already exists"):
        ms.new_version(sid, "ana")


# ------------------------------------------------------------------ delete
def test_delete_feed_admin_only(client, sample_files):
    sid = _draft_feed(sample_files)["source_id"]
    for roles in (MEMBER, REVIEWER, ["monitoring"]):
        with pytest.raises(LifecycleError, match="administrator"):
            lifecycle.delete_feed(sid, "ona", roles, WHY)
    assert client.delete(f"/api/sources/{sid}?reason={WHY}", headers=ONB).status_code == 403
    assert _src(sid) is not None
    assert client.delete(f"/api/sources/{sid}?reason=no", headers=ADM).status_code == 400
    assert client.delete(f"/api/sources/{sid}?reason={WHY}", headers=ADM).json() == {"source_id": sid, "deleted": True}
    assert _src(sid) is None
    assert client.delete(f"/api/sources/{sid}?reason={WHY}", headers=ADM).status_code == 404


@pytest.mark.parametrize("what", ["batch", "file_set", "exception", "loan"])
def test_delete_feed_with_history_refused(sample_files, what):
    sid = _live_feed(sample_files)
    with db.get_engine().begin() as c:
        if what == "batch":
            c.execute(db.batches.insert().values(batch_id="b1", source_id=sid, filename="f.csv", status="completed"))
        elif what == "file_set":
            c.execute(db.file_sets.insert().values(set_id="fst1", source_id=sid, status="discarded"))
        elif what == "exception":
            c.execute(db.exceptions.insert().values(exception_id="ex1", source_id=sid, status="open"))
        else:
            c.execute(db.sse_loans.insert().values(loan_number="L1", lbp_source_id=sid))
    with pytest.raises(LifecycleError, match="archive it instead"):
        lifecycle.delete_feed(sid, "ada", ADMIN, WHY)
    assert _src(sid) is not None and not _audit("source.delete", sid)


def test_delete_feed_with_batch_refused(sample_files):
    sid = _live_feed(sample_files)
    _batch(sid, "completed")
    with pytest.raises(LifecycleError, match="batches"):
        lifecycle.delete_feed(sid, "ada", ADMIN, WHY)
    lifecycle.archive_feed(sid, "rev", REVIEWER, WHY)  # archived is no exception: history still blocks deletion
    with pytest.raises(LifecycleError, match="batches"):
        lifecycle.delete_feed(sid, "ada", ADMIN, WHY)


def test_delete_never_used_feed_removes_mappings_schedules_and_keeps_audit(sample_files):
    sid = _live_feed(sample_files)
    other = _live_feed(sample_files, "keep_me", _src(sid).vendor_id)
    s = _schedule(sid)
    with db.get_engine().connect() as c:
        mids = [r[0] for r in c.execute(select(db.mappings.c.mapping_id).where(db.mappings.c.source_id == sid))]
    sched.tick(now=datetime(2030, 1, 7, 0, 0))  # materialises deliveries for the schedule
    out = lifecycle.delete_feed(sid, "ada", ADMIN, WHY)
    assert out == {"source_id": sid, "deleted": True}
    with db.get_engine().connect() as c:
        assert _src(sid) is None
        assert not c.execute(select(db.mappings).where(db.mappings.c.source_id == sid)).all()
        assert not c.execute(select(db.delivery_schedules).where(db.delivery_schedules.c.source_id == sid)).all()
        assert not c.execute(select(db.deliveries).where(db.deliveries.c.source_id == sid)).all()
    assert _src(other) is not None and ms.get_mapping(
        [m for m in _mapping_ids(other)][0])["status"] == "approved"  # other feeds untouched
    d = _audit("source.delete", sid)
    assert len(d) == 1 and d[0].detail["reason"] == WHY and d[0].detail["mappings_removed"] == len(mids)
    assert d[0].detail["schedules_removed"] == 1 and s["schedule_id"]
    assert _audit("source.register", sid) and _audit("mapping.approve", mids[0])  # history kept
    assert db.verify_audit_chain()["valid"]


def _mapping_ids(sid):
    with db.get_engine().connect() as c:
        return [r[0] for r in c.execute(select(db.mappings.c.mapping_id).where(db.mappings.c.source_id == sid))]


# ------------------------------------------------------------------ lists
def test_list_sources_default_excludes_archived_and_flag_includes(client, sample_files):
    a = _live_feed(sample_files, "alpha")
    b = _draft_feed(sample_files, "beta_feed", _src(a).vendor_id)["source_id"]
    lifecycle.archive_feed(b, "ona", MEMBER, WHY)
    ids = lambda r: {s["source_id"] for s in r.json()["sources"]}  # noqa: E731
    assert ids(client.get("/api/sources")) == {a}
    r = client.get("/api/sources?include_archived=true")
    assert ids(r) == {a, b}
    row = next(s for s in r.json()["sources"] if s["source_id"] == b)
    assert row["status"] == "retired" and row["retired_reason"] == WHY and row["retired_at"]
    live = next(s for s in r.json()["sources"] if s["source_id"] == a)
    assert live["status"] == "live" and live["retired_at"] is None
    assert ids(client.get(f"/api/sources?vendor_id={_src(a).vendor_id}")) == {a}


def test_lifecycle_routes_over_http(client, sample_files):
    sid = _live_feed(sample_files)
    assert client.post(f"/api/sources/{sid}/archive", json={"reason": WHY}, headers=OPS).status_code == 403  # monitoring
    r = client.post(f"/api/sources/{sid}/archive", json={"reason": WHY}, headers=ONB)
    assert r.status_code == 400 and "onboarding_reviewer" in r.json()["detail"]  # live feed: reviewer rule in the service
    rev = {"X-User": "rita", "X-Roles": "onboarding_reviewer"}
    assert client.post(f"/api/sources/{sid}/archive", json={"reason": WHY}, headers=rev).json()["status"] == "retired"
    assert client.post(f"/api/sources/{sid}/restore", json={"reason": "bring it back"}, headers=rev).json()["status"] == "live"
    assert client.post("/api/sources/src_nope/archive", json={"reason": WHY}, headers=rev).status_code == 404
    v2 = client.post(f"/api/sources/{sid}/mappings/new-version", headers=ONB).json()["mapping_id"]
    assert client.post(f"/api/mappings/{v2}/discard", json={"reason": WHY}, headers=OPS).status_code == 403
    assert client.post(f"/api/mappings/{v2}/discard", json={"reason": WHY}, headers=ONB).json()["status"] == "discarded"


# ------------------------------------------------------------------ vendors
def test_vendor_summary_excludes_archived(client, sample_files):
    a = _live_feed(sample_files, "alpha")
    vid = _src(a).vendor_id
    b = _live_feed(sample_files, "beta_feed", vid)
    _schedule(b)
    before = next(v for v in vendor_svc.list_vendors() if v["vendor_id"] == vid)
    assert before["feeds"] == 2 and before["live_feeds"] == 2 and before["archived_feeds"] == 0 and before["schedules"] == 1
    lifecycle.archive_feed(b, "rev", REVIEWER, WHY)
    v = next(x for x in client.get("/api/vendors").json()["vendors"] if x["vendor_id"] == vid)
    assert v["feeds"] == 1 and v["live_feeds"] == 1 and v["archived_feeds"] == 1
    lifecycle.archive_feed(a, "rev", REVIEWER, WHY)  # every feed archived: the vendor still reports zero, not nothing
    v = next(x for x in vendor_svc.list_vendors() if x["vendor_id"] == vid)
    assert v["feeds"] == 0 and v["live_feeds"] == 0 and v["archived_feeds"] == 2 and v["pending_mapping_review"] == 0
    detail = vendor_svc.get_vendor(vid)
    assert {f["source_id"]: f["status"] for f in detail["feeds"]} == {a: "retired", b: "retired"}


# ------------------------------------------------------------------ migration
NEW_COLS = {"sources": {"retired_at", "retired_by", "retired_reason", "retired_from_status"}}


def test_migration_0008_roundtrip(tmp_path, monkeypatch):
    from alembic import command
    from sqlalchemy import create_engine, inspect

    from lbp import cli, config

    url = f"sqlite:///{tmp_path / 'mig.db'}"
    monkeypatch.setenv("LBP_DATABASE_URL", url)
    monkeypatch.setenv("LBP_AUTO_CREATE_SCHEMA", "false")
    config.reset_settings()
    db.reset_engine()
    cfg = cli._alembic_cfg()
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(url))
    for table, cols in NEW_COLS.items():
        assert cols <= {c["name"] for c in insp.get_columns(table)}
    command.downgrade(cfg, "0007")
    insp = inspect(create_engine(url))
    for table, cols in NEW_COLS.items():
        assert not cols & {c["name"] for c in insp.get_columns(table)}
    assert "layout" in {c["name"] for c in insp.get_columns("sources")}  # 0007 stays
    command.upgrade(cfg, "head")
    db.reset_engine()
    config.reset_settings()
