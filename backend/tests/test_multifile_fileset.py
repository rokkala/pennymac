"""File-set intake and readiness (Task 9): routing, pairing, readiness, timeouts, duplicates."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from lbp import config_store
from lbp.multifile.fileset import FileSetError, attach_file, create_batch_for_set, evaluate_set, expire_sets, pairing_key, route_file
from lbp.pipeline.batch import DuplicateFileError
from lbp.store import db

LAYOUT = {
    "files": [
        {"role": "master", "entity": "loan", "name_pattern": r"loans_(?P<date>\d{8})\.csv", "key": ["loan_id"], "required": True},
        {"role": "borrowers", "name_pattern": r"borrowers_(?P<date>\d{8})\.csv", "required": True},
    ],
    "relations": [{"detail": "borrowers", "to": "master", "on": [{"parent": "loan_id", "detail": "loan_id"}], "mode": "merge"}],
}
READY = {"require": "all_required", "pairing": "business_date", "wait_timeout_minutes": 240, "on_timeout": "alert_only"}
T0 = datetime(2026, 11, 17, 8, 0, 0)


@pytest.fixture()
def feed(sample_files):
    """One feed with an approved mapping and a published multi-file layout."""
    from lbp.mapping import service as ms

    reg = ms.register_source("pcg_retail", sample_files["pcg_retail"], "analyst1")
    ms.accept_all(reg["mapping_id"], "analyst1", 0.0)
    ms.submit(reg["mapping_id"], "analyst1")
    ms.approve(reg["mapping_id"], "onboarding.reviewer", ["onboarding_reviewer"])
    sid = reg["source_id"]
    _configure(sid, LAYOUT, READY)
    return sid


def _configure(sid, layout, readiness):
    with db.get_engine().begin() as c:
        c.execute(update(db.sources).where(db.sources.c.source_id == sid).values(layout=layout, readiness=readiness))
    config_store.publish(sid, "sme1", "layout")


def _file(env, name, body):
    d = env / "incoming"
    d.mkdir(exist_ok=True)
    p = d / f"{len(list(d.iterdir()))}_{name}"
    p.write_text(body)
    return p


def _attach(env, sid, name, body, at=None, role=None):
    return attach_file(sid, name, _file(env, name, body), "s3-intake", role=role, arrived_at=at)


def _set(set_id):
    with db.get_engine().connect() as c:
        return c.execute(select(db.file_sets).where(db.file_sets.c.set_id == set_id)).first()


def _batches(sid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.batches).where(db.batches.c.source_id == sid).order_by(db.batches.c.created_at)).all()


def _members(set_id):
    with db.get_engine().connect() as c:
        return c.execute(select(db.batch_files).where(db.batch_files.c.set_id == set_id).order_by(db.batch_files.c.role)).all()


def _audit(action):
    with db.get_engine().connect() as c:
        return c.execute(select(db.audit_log).where(db.audit_log.c.action == action)).all()


MASTER = "loan_id,amount\n1,100\n2,200\n"
BORR = "loan_id,name\n1,Ann\n2,Bob\n"


def test_route_by_pattern_and_capture():
    assert route_file(LAYOUT, "loans_20261117.csv") == ("master", {"date": "20261117"})
    assert route_file(LAYOUT, "borrowers_20261117.csv") == ("borrowers", {"date": "20261117"})
    assert route_file(LAYOUT, "inbound/2026/loans_20261117.csv") == ("master", {"date": "20261117"})  # bare filename
    assert route_file(LAYOUT, "loans_20261117.csv.bak") is None  # fullmatch, not search
    assert route_file(LAYOUT, "xloans_20261117.csv") is None
    assert route_file(LAYOUT, "loans_2026.csv") is None
    # patterns are tried in file order of the layout: the first match wins
    overlap = {"files": [{"role": "master", "name_pattern": r"(?P<d>\d+)_.*\.csv"}, {"role": "extra", "name_pattern": r"(?P<d>\d+)_x\.csv"}]}
    assert route_file(overlap, "1_x.csv") == ("master", {"d": "1"})
    assert pairing_key(READY, {"date": "20261117"}, T0) == pairing_key(READY, {"date": "20261117"}, T0 + timedelta(days=3))
    assert pairing_key(READY, {"date": "20261117"}, T0) != pairing_key(READY, {"date": "20261118"}, T0)
    with pytest.raises(FileSetError):
        pairing_key(READY, {}, T0)


def test_unrouteable_name_raises(env, feed):
    with pytest.raises(FileSetError, match="does not match"):
        _attach(env, feed, "payments_20261117.csv", MASTER)
    with db.get_engine().connect() as c:
        assert c.execute(select(db.file_sets)).first() is None


def test_two_files_same_date_make_one_ready_set_and_one_batch(env, feed):
    a = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    assert a["role"] == "master" and a["status"] == "waiting" and a["batch_id"] is None
    b = _attach(env, feed, "borrowers_20261117.csv", BORR, T0 + timedelta(minutes=5))
    assert b["set_id"] == a["set_id"] and b["role"] == "borrowers"
    assert b["status"] == "consumed" and b["batch_id"]
    batches = _batches(feed)
    assert [x.batch_id for x in batches] == [b["batch_id"]]
    bat = batches[0]
    assert bat.file_set_id == a["set_id"] and bat.filename == "loans_20261117.csv" and bat.status == "queued"
    s = _set(a["set_id"])
    assert s.status == "consumed" and s.batch_id == bat.batch_id and s.ready_at is not None and len(s.members_sha) == 64
    members = _members(a["set_id"])
    assert [m.role for m in members] == ["borrowers", "master"] and {m.batch_id for m in members} == {bat.batch_id}
    assert next(m for m in members if m.role == "master").file_path == bat.file_path
    assert next(m for m in members if m.role == "master").file_sha256 == bat.file_sha256


def test_master_only_stays_waiting_no_batch(env, feed):
    a = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    assert a["status"] == "waiting" and a["batch_id"] is None
    assert evaluate_set(a["set_id"], T0 + timedelta(minutes=10)) == "waiting"
    assert _batches(feed) == []
    s = _set(a["set_id"])
    assert s.status == "waiting" and s.batch_id is None and s.expires_at == T0 + timedelta(minutes=240)


def test_mismatched_dates_open_separate_sets(env, feed):
    a = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    b = _attach(env, feed, "borrowers_20261118.csv", BORR, T0 + timedelta(minutes=1))
    assert a["set_id"] != b["set_id"]
    assert a["status"] == b["status"] == "waiting"
    assert _batches(feed) == []
    assert _set(a["set_id"]).pairing_key != _set(b["set_id"]).pairing_key


def test_window_minutes_pairing(env, feed):
    lay = {**LAYOUT, "files": [{**LAYOUT["files"][0], "name_pattern": r"loans_\w+\.csv"},
                               {**LAYOUT["files"][1], "name_pattern": r"borrowers_\w+\.csv"}]}
    _configure(feed, lay, {**READY, "pairing": "window_minutes", "window_minutes": 30})
    a = _attach(env, feed, "loans_a.csv", MASTER, T0)
    b = _attach(env, feed, "borrowers_a.csv", BORR, T0 + timedelta(minutes=20))
    assert b["set_id"] == a["set_id"] and b["status"] == "consumed"
    c = _attach(env, feed, "loans_b.csv", MASTER + "3,300\n", T0 + timedelta(minutes=60))
    assert c["set_id"] != a["set_id"] and c["status"] == "waiting"
    late = _attach(env, feed, "borrowers_b.csv", BORR + "3,Cy\n", T0 + timedelta(minutes=95))  # 35 min after the set opened
    assert late["set_id"] not in (a["set_id"], c["set_id"]) and late["status"] == "waiting"
    assert len(_batches(feed)) == 1


def test_same_file_twice_is_idempotent(env, feed):
    a = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    again = _attach(env, feed, "loans_20261117.csv", MASTER, T0 + timedelta(minutes=1))
    assert again["set_id"] == a["set_id"] and again["status"] == "waiting"
    assert len(_members(a["set_id"])) == 1 and not _audit("file_set.member_replaced")
    sha_before = _members(a["set_id"])[0].file_sha256
    changed = _attach(env, feed, "loans_20261117.csv", MASTER + "3,300\n", T0 + timedelta(minutes=2))
    assert changed["set_id"] == a["set_id"] and changed["status"] == "waiting"
    m = _members(a["set_id"])
    assert len(m) == 1 and m[0].file_sha256 != sha_before
    rep = _audit("file_set.member_replaced")
    assert len(rep) == 1 and rep[0].detail["role"] == "master" and rep[0].detail["previous_sha256"] == sha_before
    assert "amount" not in str(rep[0].detail)  # filenames and hashes only, never contents
    assert _batches(feed) == []


def test_resent_role_after_consumed_opens_new_set(env, feed):
    a = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    _attach(env, feed, "borrowers_20261117.csv", BORR, T0 + timedelta(minutes=1))
    assert _set(a["set_id"]).status == "consumed"
    # correction: the same master again, with a corrected borrowers file
    m2 = _attach(env, feed, "loans_20261117.csv", MASTER, T0 + timedelta(minutes=30))
    assert m2["set_id"] != a["set_id"] and m2["status"] == "waiting" and m2["batch_id"] is None
    assert len(_batches(feed)) == 1  # a correction set still waits for every required role
    b2 = _attach(env, feed, "borrowers_20261117.csv", BORR.replace("Bob", "Rob"), T0 + timedelta(minutes=31))
    assert b2["set_id"] == m2["set_id"] and b2["status"] == "consumed" and b2["batch_id"]
    bats = _batches(feed)
    assert len(bats) == 2 and bats[1].file_set_id == m2["set_id"] and bats[0].file_sha256 == bats[1].file_sha256
    created = [r for r in _audit("batch.create") if r.entity_id == b2["batch_id"]]
    assert created[0].detail["duplicate_of"] == bats[0].batch_id
    assert created[0].detail["reason"] == "file set correction: members_sha differs"


def test_duplicate_member_set_rejected(env, feed):
    _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    first = _attach(env, feed, "borrowers_20261117.csv", BORR, T0 + timedelta(minutes=1))
    m2 = _attach(env, feed, "loans_20261117.csv", MASTER, T0 + timedelta(minutes=30))
    with pytest.raises(DuplicateFileError) as ei:
        _attach(env, feed, "borrowers_20261117.csv", BORR, T0 + timedelta(minutes=31))
    assert ei.value.batch_id == first["batch_id"]
    assert len(_batches(feed)) == 1
    s = _set(m2["set_id"])
    assert s.status == "discarded" and s.batch_id is None and s.members_sha == _set(first["set_id"]).members_sha
    assert s.override["duplicate_of"] == first["batch_id"]
    with pytest.raises(FileSetError):  # a discarded set is never queued
        create_batch_for_set(m2["set_id"], "ops1")
    # once the earlier batch failed, the same files may be submitted again
    with db.get_engine().begin() as c:
        c.execute(update(db.batches).where(db.batches.c.batch_id == first["batch_id"]).values(status="failed"))
    _attach(env, feed, "loans_20261117.csv", MASTER, T0 + timedelta(minutes=40))
    again = _attach(env, feed, "borrowers_20261117.csv", BORR, T0 + timedelta(minutes=41))
    assert again["status"] == "consumed" and again["batch_id"]


def test_duplicate_discard_merges_existing_override(env, feed):
    _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    first = _attach(env, feed, "borrowers_20261117.csv", BORR, T0 + timedelta(minutes=1))
    m2 = _attach(env, feed, "loans_20261117.csv", MASTER, T0 + timedelta(minutes=30))
    with db.get_engine().begin() as c:
        c.execute(update(db.file_sets).where(db.file_sets.c.set_id == m2["set_id"]).values(override={"note": "kept"}))
    with pytest.raises(DuplicateFileError):
        _attach(env, feed, "borrowers_20261117.csv", BORR, T0 + timedelta(minutes=31))
    assert _set(m2["set_id"]).override == {"note": "kept", "duplicate_of": first["batch_id"]}


def _fail_arrival_for(monkeypatch, filename):
    """Make delivery matching (called inside batch registration, after the batch row insert) raise for one file."""
    from lbp.scheduling import service as sched

    real = sched.match_arrival

    def boom(c, source_id, batch_id, fname):
        if fname == filename:
            raise RuntimeError("simulated failure")
        return real(c, source_id, batch_id, fname)

    monkeypatch.setattr(sched, "match_arrival", boom)


def test_batch_failure_leaves_set_ready_and_no_batch_row(env, feed, monkeypatch):
    _fail_arrival_for(monkeypatch, "loans_20261117.csv")
    a = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    with pytest.raises(RuntimeError):
        _attach(env, feed, "borrowers_20261117.csv", BORR, T0 + timedelta(minutes=1))
    s = _set(a["set_id"])
    assert s.status == "ready" and s.batch_id is None
    assert _batches(feed) == []
    assert {m.batch_id for m in _members(a["set_id"])} == {None}


def test_ready_set_without_batch_is_retried_by_sweep(env, feed, monkeypatch):
    _fail_arrival_for(monkeypatch, "loans_20261117.csv")
    a = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    with pytest.raises(RuntimeError):
        _attach(env, feed, "borrowers_20261117.csv", BORR, T0 + timedelta(minutes=1))
    # a persistent failure is recorded on the set and alerted once
    expire_sets(T0 + timedelta(minutes=5))
    expire_sets(T0 + timedelta(minutes=6))
    s = _set(a["set_id"])
    assert s.status == "ready" and s.batch_id is None
    assert s.override["error"]["stage"] == "batch" and "RuntimeError" in s.override["error"]["message"]
    assert len([d for d in _alerts("file_set_error") if d["set_id"] == a["set_id"]]) == 1
    monkeypatch.undo()
    expire_sets(T0 + timedelta(minutes=7))
    s = _set(a["set_id"])
    assert s.status == "consumed" and s.batch_id
    assert [b.file_set_id for b in _batches(feed)] == [a["set_id"]]


def test_one_set_failing_does_not_stop_the_others(env, feed, monkeypatch):
    from lbp.scheduling import alerts

    a = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    b = _attach(env, feed, "loans_20261118.csv", MASTER + "3,300\n", T0)
    real = alerts.notify

    def notify(kind, message, detail=None):
        if (detail or {}).get("set_id") == a["set_id"]:
            raise RuntimeError("sns down")
        return real(kind, message, detail)

    monkeypatch.setattr(alerts, "notify", notify)
    handled = expire_sets(T0 + timedelta(minutes=241))
    assert b["set_id"] in handled
    assert any(d["set_id"] == b["set_id"] for d in _alerts("delivery_late"))
    err = _set(a["set_id"]).override["error"]
    assert err["stage"] == "timeout" and "RuntimeError" in err["message"]
    assert [r for r in _audit("file_set.error") if r.entity_id == a["set_id"]]
    # batch sweep: one ready set failing does not stop another
    _fail_arrival_for(monkeypatch, "loans_20261117.csv")
    with pytest.raises(RuntimeError):
        _attach(env, feed, "borrowers_20261117.csv", BORR, T0 + timedelta(minutes=250))
    with db.get_engine().begin() as c:  # leave set b ready without a batch, as a crash after attach would
        c.execute(update(db.file_sets).where(db.file_sets.c.set_id == b["set_id"]).values(status="ready"))
        c.execute(db.batch_files.insert().values(set_id=b["set_id"], role="borrowers", filename="borrowers_20261118.csv",
                                                 file_path=str(_file(env, "borrowers_20261118.csv", BORR + "3,Cy\n")),
                                                 file_sha256="0" * 64))
    expire_sets(T0 + timedelta(minutes=251))
    assert _set(a["set_id"]).status == "ready"
    assert _set(b["set_id"]).status == "consumed"


def test_pairing_compares_values_not_group_names(env, feed):
    lay = {**LAYOUT, "files": [{**LAYOUT["files"][0], "name_pattern": r"loans_(?P<date>\d{8})\.csv"},
                               {**LAYOUT["files"][1], "name_pattern": r"borrowers_(?P<d>\d{8})\.csv"}]}
    _configure(feed, lay, READY)
    a = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    b = _attach(env, feed, "borrowers_20261117.csv", BORR, T0 + timedelta(minutes=1))
    assert b["set_id"] == a["set_id"] and b["status"] == "consumed"
    assert pairing_key(READY, {"date": "1"}, T0) == pairing_key(READY, {"d": "1"}, T0)
    with pytest.raises(FileSetError, match="too long"):
        pairing_key(READY, {"date": "9" * 200}, T0)


def test_aware_arrival_time_is_stored_as_naive_utc(env, feed):
    from datetime import timezone

    eastern = timezone(timedelta(hours=-5))
    a = _attach(env, feed, "loans_20261117.csv", MASTER, datetime(2026, 11, 17, 3, 0, tzinfo=eastern))
    assert _set(a["set_id"]).opened_at == T0
    assert expire_sets(datetime(2026, 11, 17, 12, 1, tzinfo=UTC)) == [a["set_id"]]


def _alerts(kind):
    return [r.detail for r in _audit(f"alert.{kind}")]


def test_timeout_alerts_names_missing_role_and_applies_policy(env, feed):
    # alert_only: alert names the missing role; the set keeps waiting; one alert per set
    a = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    assert expire_sets(T0 + timedelta(minutes=239)) == []
    assert expire_sets(T0 + timedelta(minutes=241)) == [a["set_id"]]
    assert _set(a["set_id"]).status == "waiting"
    late = _alerts("delivery_late")
    assert len(late) == 1 and "borrowers" in late[0]["message"] and late[0]["set_id"] == a["set_id"]
    assert late[0]["missing_roles"] == ["borrowers"]
    assert expire_sets(T0 + timedelta(minutes=300)) == [] and len(_alerts("delivery_late")) == 1

    # fail: the set is expired; a late detail never joins it
    _configure(feed, LAYOUT, {**READY, "on_timeout": "fail"})
    f = _attach(env, feed, "loans_20261118.csv", MASTER + "3,300\n", T0)
    assert set(expire_sets(T0 + timedelta(minutes=241))) == {f["set_id"]}
    assert _set(f["set_id"]).status == "expired"
    missed = _alerts("delivery_missed")
    assert len(missed) == 1 and "borrowers" in missed[0]["message"]
    late_detail = _attach(env, feed, "borrowers_20261118.csv", BORR, T0 + timedelta(minutes=250))
    assert late_detail["set_id"] != f["set_id"] and late_detail["status"] == "waiting"
    assert _batches(feed) == []

    # load_master_only (details non-required): the master is loaded alone after the timeout
    optional = {**LAYOUT, "files": [LAYOUT["files"][0], {**LAYOUT["files"][1], "required": False}]}
    _configure(feed, optional, {**READY, "on_timeout": "load_master_only"})
    m = _attach(env, feed, "loans_20261119.csv", MASTER + "4,400\n", T0)
    assert m["status"] == "waiting"
    assert m["set_id"] in expire_sets(T0 + timedelta(minutes=241))
    s = _set(m["set_id"])
    assert s.status == "consumed" and s.batch_id
    assert [x.role for x in _members(m["set_id"])] == ["master"]
    assert [b.file_set_id for b in _batches(feed)] == [m["set_id"]]
    assert any("borrowers" in d["message"] for d in _alerts("delivery_late") + _alerts("delivery_missed") if d["set_id"] == m["set_id"])

    # load_master_only is never accepted while a detail is required
    with pytest.raises(config_store.ConfigError):
        _configure(feed, LAYOUT, {**READY, "on_timeout": "load_master_only"})


def test_two_open_sets_route_independently(env, feed):
    s1 = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    s2 = _attach(env, feed, "loans_20261118.csv", MASTER + "3,300\n", T0 + timedelta(minutes=1))
    assert s1["set_id"] != s2["set_id"]
    b2 = _attach(env, feed, "borrowers_20261118.csv", BORR + "3,Cy\n", T0 + timedelta(minutes=2))
    assert b2["set_id"] == s2["set_id"] and b2["status"] == "consumed"
    assert _set(s1["set_id"]).status == "waiting"
    b1 = _attach(env, feed, "borrowers_20261117.csv", BORR, T0 + timedelta(minutes=3))
    assert b1["set_id"] == s1["set_id"] and b1["status"] == "consumed"
    assert {b.file_set_id for b in _batches(feed)} == {s1["set_id"], s2["set_id"]}


def test_explicit_role_overrides_routing(env, feed):
    r = _attach(env, feed, "borrowers_20261117.csv", BORR, T0, role="borrowers")
    assert r["role"] == "borrowers"
    with pytest.raises(FileSetError, match="role"):
        _attach(env, feed, "borrowers_20261117.csv", BORR, T0, role="nope")


def test_concurrent_arrivals_create_one_set_and_one_batch(env, feed):
    import threading

    for day in range(10, 16):
        names = {f"loans_202611{day}.csv": MASTER + f"{day},1\n", f"borrowers_202611{day}.csv": BORR + f"{day},X\n"}
        paths = {n: _file(env, n, b) for n, b in names.items()}
        out, errs = [], []
        go = threading.Barrier(len(paths))

        def arrive(name, paths=paths, out=out, errs=errs, go=go):
            go.wait()
            try:
                out.append(attach_file(feed, name, paths[name], "s3-intake", arrived_at=T0))
            except Exception as e:  # noqa: BLE001
                errs.append(e)

        ts = [threading.Thread(target=arrive, args=(n,)) for n in paths]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert not errs
        assert len({r["set_id"] for r in out}) == 1
        assert sum(1 for r in out if r["batch_id"]) == 1
    assert len(_batches(feed)) == 6


def test_batch_is_linked_to_its_set_when_inserted(env, feed, monkeypatch):
    """No window where a queued batch exists without its set link (a worker would run it as a plain file)."""
    from lbp.scheduling import service as sched

    real, seen = sched.match_arrival, []

    def spy(c, source_id, batch_id, fname):
        b = c.execute(select(db.batches.c.file_set_id).where(db.batches.c.batch_id == batch_id)).first()
        s = c.execute(select(db.file_sets.c.status).where(db.file_sets.c.set_id == b.file_set_id)).first() if b.file_set_id else None
        seen.append((b.file_set_id, s.status if s else None))
        return real(c, source_id, batch_id, fname)

    monkeypatch.setattr(sched, "match_arrival", spy)
    a = _attach(env, feed, "loans_20261117.csv", MASTER, T0)
    _attach(env, feed, "borrowers_20261117.csv", BORR, T0 + timedelta(minutes=1))
    assert seen == [(a["set_id"], "consumed")]
