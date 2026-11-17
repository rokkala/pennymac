"""Multi-file intake (Task 10): API upload and zip, scheduler sweep, scheduled pulls and S3 arrivals deliver
files of a feed with a layout into file sets; feeds without a layout keep their single-file path."""
import io
import json
import zipfile
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update

from lbp import config_store
from lbp.store import db

LAYOUT = {
    "files": [
        {"role": "master", "entity": "loan", "name_pattern": r"loans_(?P<date>\d{8})\.csv", "key": ["loan_id"], "required": True},
        {"role": "borrowers", "name_pattern": r"borrowers_(?P<date>\d{8})\.csv", "required": True},
    ],
    "relations": [{"detail": "borrowers", "to": "master", "on": [{"parent": "loan_id", "detail": "loan_id"}], "mode": "merge"}],
}
READY = {"require": "all_required", "pairing": "business_date", "wait_timeout_minutes": 240, "on_timeout": "alert_only"}
MASTER = "loan_id,amount\n1,100\n2,200\n"
BORR = "loan_id,name\n1,Ann\n2,Bob\n"
OPS = {"X-User": "oli", "X-Roles": "ops"}


def _onboard(sample_files, key="pcg_retail"):
    from lbp.mapping import service as ms

    reg = ms.register_source(key, sample_files[key], "analyst1")
    ms.accept_all(reg["mapping_id"], "analyst1", 0.0)
    ms.submit(reg["mapping_id"], "analyst1")
    ms.approve(reg["mapping_id"], "onboarding.reviewer", ["onboarding_reviewer"])
    return reg["source_id"]


def _configure(sid, layout, readiness):
    with db.get_engine().begin() as c:
        c.execute(update(db.sources).where(db.sources.c.source_id == sid).values(layout=layout, readiness=readiness))
    config_store.publish(sid, "sme1", "layout")


@pytest.fixture()
def feed(sample_files):
    """A feed with an approved mapping and a published multi-file layout."""
    sid = _onboard(sample_files)
    _configure(sid, LAYOUT, READY)
    return sid


@pytest.fixture()
def legacy(sample_files):
    """A single-file feed (no layout)."""
    return _onboard(sample_files, "correspondent")


def _rows(table, **where):
    with db.get_engine().connect() as c:
        q = select(table)
        for k, v in where.items():
            q = q.where(table.c[k] == v)
        return c.execute(q).all()


def _no_set_code(monkeypatch):
    """Any call into the file-set intake fails the test: the legacy path must not reach it."""
    from lbp.multifile import fileset

    def boom(*a, **k):
        raise AssertionError("file-set intake used for a feed without a layout")

    monkeypatch.setattr(fileset, "attach_file", boom)
    monkeypatch.setattr(fileset, "create_batch_for_set", boom)


def _zip(members: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in members.items():
            z.writestr(name, body)
    return buf.getvalue()


def _upload_dir_files(env):
    d = env / "data" / "uploads"
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


# ------------------------------------------------------------------ API upload
def test_upload_legacy_feed_unchanged(client, legacy, env, monkeypatch):
    """A feed without a layout follows the single-file path exactly: upload, local pull and S3 arrival."""
    from lbp.scheduling import service as svc

    _no_set_code(monkeypatch)
    sample = env / "samples" / "correspondent_sample.csv"
    with open(sample, "rb") as f:
        r = client.post("/api/upload", data={"source_id": legacy, "auto_start": "false", "role": "master"},
                        files={"file": ("CORR_20261117.csv", f)}, headers=OPS)
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"batch_id", "status"} and r.json()["status"] == "queued"
    b = _rows(db.batches, batch_id=r.json()["batch_id"])[0]
    assert b.file_set_id is None and b.filename == "CORR_20261117.csv" and b.status == "queued"
    with open(sample, "rb") as f:  # the duplicate rule is unchanged too
        again = client.post("/api/upload", data={"source_id": legacy, "auto_start": "false"},
                            files={"file": ("CORR_20261117.csv", f)}, headers=OPS)
    assert again.status_code == 409 and again.json()["detail"]["duplicate_of"] == b.batch_id
    # upload/set is only for feeds with a layout
    assert client.post("/api/upload/set", data={"source_id": legacy}, files=[("files", ("a.csv", b"x,y\n1,2\n"))],
                       headers=OPS).status_code == 400
    # scheduled pull: glob pattern, one batch per file via create_batch
    drop = env / "data" / "dropzone" / "pcg"
    drop.mkdir(parents=True)
    (drop / "CORR_20261118.csv").write_text("".join(sample.read_text().splitlines(keepends=True)[:-1]))  # not the uploaded file
    (drop / "notes.txt").write_text("ignored: pattern")
    sch = svc.create_schedule(legacy, "Daily", {"cron": "0 6 * * *", "timezone": "UTC", "calendar": "none",
                                                "pull": {"protocol": "local", "path": "pcg", "pattern": "CORR_*.csv"}}, "ops1", ["ops"])
    svc.decide(sch["schedule_id"], "sme1", ["sme"], True)
    out = svc.pull_now(sch["schedule_id"], "ops1", ["ops"])
    assert out["fetched"] == ["CORR_20261118.csv"] and len(out["batches"]) == 1
    assert _rows(db.batches, batch_id=out["batches"][0])[0].file_set_id is None
    assert svc.pull_now(sch["schedule_id"], "ops1", ["ops"])["fetched"] == []  # pulled_files dedupe unchanged
    assert _rows(db.file_sets) == [] and _rows(db.batch_files) == []


def test_upload_layout_feed_routes_to_set(client, feed, env):
    r = client.post("/api/upload", data={"source_id": feed, "auto_start": "false"},
                    files={"file": ("loans_20261117.csv", MASTER.encode())}, headers=OPS)
    assert r.status_code == 200, r.text
    a = r.json()
    assert set(a) == {"set_id", "role", "status", "batch_id"}
    assert a["role"] == "master" and a["status"] == "waiting" and a["batch_id"] is None
    # an explicit role form field is honoured
    r = client.post("/api/upload", data={"source_id": feed, "auto_start": "false", "role": "borrowers"},
                    files={"file": ("borrowers_20261117.csv", BORR.encode())}, headers=OPS)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["set_id"] == a["set_id"] and b["role"] == "borrowers" and b["status"] == "consumed" and b["batch_id"]
    bat = _rows(db.batches, batch_id=b["batch_id"])[0]
    assert bat.file_set_id == a["set_id"] and bat.filename == "loans_20261117.csv"
    # a name that routes nowhere is a 400 and attaches nothing
    r = client.post("/api/upload", data={"source_id": feed, "auto_start": "false"},
                    files={"file": ("payments_20261117.csv", MASTER.encode())}, headers=OPS)
    assert r.status_code == 400 and "does not match" in r.text
    assert len(_rows(db.file_sets)) == 1
    # the identical set again is a duplicate: 409 with duplicate_of
    client.post("/api/upload", data={"source_id": feed, "auto_start": "false"},
                files={"file": ("loans_20261117.csv", MASTER.encode())}, headers=OPS)
    r = client.post("/api/upload", data={"source_id": feed, "auto_start": "false"},
                    files={"file": ("borrowers_20261117.csv", BORR.encode())}, headers=OPS)
    assert r.status_code == 409 and r.json()["detail"]["duplicate_of"] == b["batch_id"]


def test_upload_set_zip_with_manifest(client, feed, env):
    # the vendor's names do not tell the roles apart: the manifest assigns them (pairing by arrival window)
    lay = {**LAYOUT, "files": [{**LAYOUT["files"][0], "name_pattern": r"\d{8}_[ab]\.csv"},
                               {**LAYOUT["files"][1], "name_pattern": r"\d{8}_[ab]\.csv"}]}
    _configure(feed, lay, {**READY, "pairing": "window_minutes", "window_minutes": 30})
    z = _zip({"20261117_a.csv": BORR, "20261117_b.csv": MASTER})  # swapped on purpose: the manifest wins
    manifest = json.dumps({"master": "20261117_b.csv", "borrowers": "20261117_a.csv"})
    r = client.post("/api/upload/set", data={"source_id": feed, "manifest": manifest, "auto_start": "false"},
                    files=[("files", ("delivery.zip", z, "application/zip"))], headers=OPS)
    assert r.status_code == 200, r.text
    res = r.json()
    assert {x["role"] for x in res} == {"master", "borrowers"}
    assert len({x["set_id"] for x in res}) == 1
    done = [x for x in res if x["batch_id"]]
    assert len(done) == 1 and done[0]["status"] == "consumed"
    bat = _rows(db.batches, batch_id=done[0]["batch_id"])[0]
    assert bat.filename == "20261117_b.csv"
    members = {m.role: m for m in _rows(db.batch_files, set_id=res[0]["set_id"])}
    assert members["master"].filename == "20261117_b.csv" and members["borrowers"].filename == "20261117_a.csv"
    # a manifest naming a file that is not in the request, or a role not in the layout, is a 400 and attaches nothing
    for bad in ({"master": "nope.csv"}, {"payments": "20261118_a.csv"}):
        r = client.post("/api/upload/set", data={"source_id": feed, "manifest": json.dumps(bad), "auto_start": "false"},
                        files=[("files", ("d.zip", _zip({"20261118_a.csv": MASTER}), "application/zip"))], headers=OPS)
        assert r.status_code == 400, r.text
    r = client.post("/api/upload/set", data={"source_id": feed, "manifest": "not json", "auto_start": "false"},
                    files=[("files", ("d.zip", _zip({"20261118_a.csv": MASTER}), "application/zip"))], headers=OPS)
    assert r.status_code == 400
    assert len(_rows(db.file_sets)) == 1


def test_upload_set_zip_without_manifest_routes_by_pattern(client, feed, env):
    z = _zip({"loans_20261117.csv": MASTER, "borrowers_20261117.csv": BORR})
    r = client.post("/api/upload/set", data={"source_id": feed, "auto_start": "false"},
                    files=[("files", ("delivery.zip", z, "application/zip"))], headers=OPS)
    assert r.status_code == 200, r.text
    res = r.json()
    assert sorted(x["role"] for x in res) == ["borrowers", "master"]
    assert [x["status"] for x in res][-1] == "consumed" and res[-1]["batch_id"]
    # several `files` parts work the same way
    r = client.post("/api/upload/set", data={"source_id": feed, "auto_start": "false"},
                    files=[("files", ("loans_20261118.csv", MASTER + "3,300\n")), ("files", ("borrowers_20261118.csv", BORR + "3,Cy\n"))],
                    headers=OPS)
    assert r.status_code == 200, r.text
    res2 = r.json()
    assert sorted(x["role"] for x in res2) == ["borrowers", "master"] and any(x["batch_id"] for x in res2)
    sets_before = len(_rows(db.file_sets))
    # a member that routes nowhere fails the whole request: nothing is attached, nothing left on disk
    before = _upload_dir_files(env)
    z = _zip({"loans_20261119.csv": MASTER, "payments_20261119.csv": BORR})
    r = client.post("/api/upload/set", data={"source_id": feed, "auto_start": "false"},
                    files=[("files", ("delivery.zip", z, "application/zip"))], headers=OPS)
    assert r.status_code == 400 and "payments_20261119.csv" in r.text
    assert len(_rows(db.file_sets)) == sets_before
    assert _upload_dir_files(env) == before
    # two files for one role in one request are ambiguous
    z = _zip({"loans_20261119.csv": MASTER, "loans_20261120.csv": MASTER})
    r = client.post("/api/upload/set", data={"source_id": feed, "auto_start": "false"},
                    files=[("files", ("delivery.zip", z, "application/zip"))], headers=OPS)
    assert r.status_code == 400
    assert len(_rows(db.file_sets)) == sets_before


def test_zip_rejects_path_traversal_and_oversized_members(client, feed, env, monkeypatch):
    from lbp import config

    def post(z, name="delivery.zip"):
        return client.post("/api/upload/set", data={"source_id": feed, "auto_start": "false"},
                           files=[("files", (name, z, "application/zip"))], headers=OPS)

    before = _upload_dir_files(env)
    for evil in ("../loans_20261117.csv", "/etc/loans_20261117.csv", "inbound/loans_20261117.csv", "..\\loans_20261117.csv",
                 "loans_20261117.exe", ".hidden.csv"):
        r = post(_zip({evil: MASTER, "borrowers_20261117.csv": BORR}))
        assert r.status_code == 400, (evil, r.text)
    # a directory entry, a symlink and an encrypted member are odd members too
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        link = zipfile.ZipInfo("loans_20261117.csv")
        link.external_attr = (0o120777 << 16)
        z.writestr(link, "/etc/passwd")
    assert post(buf.getvalue()).status_code == 400
    assert post(b"PK\x03\x04 not really a zip").status_code == 400
    assert post(_zip({})).status_code == 400  # empty archive
    # too many members
    assert post(_zip({f"loans_2026{i:04d}.csv": MASTER for i in range(40)})).status_code in (400, 413)
    # a zip and other files in one request is ambiguous
    r = client.post("/api/upload/set", data={"source_id": feed, "auto_start": "false"},
                    files=[("files", ("d.zip", _zip({"loans_20261117.csv": MASTER}), "application/zip")),
                           ("files", ("borrowers_20261117.csv", BORR))], headers=OPS)
    assert r.status_code == 400
    # per-member and total uncompressed size use the upload limit (a highly compressible member is a zip bomb)
    monkeypatch.setenv("LBP_MAX_UPLOAD_MB", "1")
    config.reset_settings()
    big = "loan_id,amount\n" + "1,100\n" * 200_000  # ~1.2 MB uncompressed, a few KB compressed
    r = post(_zip({"loans_20261117.csv": big, "borrowers_20261117.csv": BORR}))
    assert r.status_code == 413, r.text
    # a member whose header understates its size is still stopped while extracting
    raw = bytearray(_zip({"loans_20261117.csv": big, "borrowers_20261117.csv": BORR}))
    real = len(big).to_bytes(4, "little")
    i = raw.find(real)
    while i != -1:  # patch every recorded uncompressed size (local header and central directory)
        raw[i:i + 4] = (100).to_bytes(4, "little")
        i = raw.find(real, i + 4)
    assert post(bytes(raw)).status_code in (400, 413)
    assert _rows(db.file_sets) == [] and _rows(db.batch_files) == []
    assert _upload_dir_files(env) == before


# ------------------------------------------------------------------ scheduler
def test_tick_expires_waiting_sets(feed, env, monkeypatch):
    from lbp.multifile import fileset
    from lbp.scheduling import service as svc

    _configure(feed, LAYOUT, {**READY, "on_timeout": "fail"})
    p = env / "loans_20261117.csv"
    p.write_text(MASTER)
    t0 = datetime(2026, 11, 17, 8, 0)
    a = fileset.attach_file(feed, p.name, p, "ops1", arrived_at=t0)
    assert a["status"] == "waiting"
    svc.tick(now=t0 + timedelta(minutes=60))
    assert _rows(db.file_sets, set_id=a["set_id"])[0].status == "waiting"
    svc.tick(now=t0 + timedelta(minutes=241))
    s = _rows(db.file_sets, set_id=a["set_id"])[0]
    assert s.status == "expired" and s.override["timeout"]["missing_roles"] == ["borrowers"]
    # a failing sweep never breaks the rest of the tick, and its log carries no data values
    calls = []

    def boom(now=None):
        calls.append(now)
        raise RuntimeError("loan 1234567890 broke")

    monkeypatch.setattr(fileset, "sweep_sets", boom)
    with __import__("unittest.mock").mock.patch.object(svc.log, "warning") as warn:
        out = svc.tick(now=t0 + timedelta(minutes=300))
    assert calls and "materialized" in out and "skipped" not in out
    assert warn.called and "1234567890" not in str(warn.call_args_list)


def test_pull_attaches_each_role(feed, env, monkeypatch):
    """A scheduled pull for a layout feed fetches one pattern per role and attaches each file to its set."""
    pytest.importorskip("paramiko")
    import boto3
    from moto import mock_aws

    from lbp import config
    from lbp.scheduling import service as svc

    monkeypatch.setenv("LBP_PULL_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "x")
    config.reset_settings()
    srv = _sftp(env)
    out_dir = srv["root"] / "out"
    (out_dir / "loans_20261117.csv").write_text(MASTER)
    (out_dir / "borrowers_20261117.csv").write_text(BORR)
    (out_dir / "CORR_20261117.csv").write_text(MASTER)  # matches the schedule's glob, but no role of the layout
    try:
        with mock_aws():
            boto3.client("secretsmanager", region_name="us-east-1").create_secret(
                Name="lbp/vendors/pcg", SecretString='{"username": "pennymac", "password": "s3cret"}')
            pull = {"protocol": "sftp", "host": "127.0.0.1", "port": srv["port"], "path": "/out", "pattern": "*.csv",
                    "secret_ref": "lbp/vendors/pcg", "host_key_sha256": srv["fingerprint"]}
            sch = svc.create_schedule(feed, "Daily", {"cron": "0 6 * * *", "timezone": "UTC", "calendar": "none", "pull": pull},
                                      "ops1", ["ops"])
            svc.decide(sch["schedule_id"], "sme1", ["sme"], True)
            out = svc.pull_now(sch["schedule_id"], "ops1", ["ops"])
            assert sorted(out["fetched"]) == ["borrowers_20261117.csv", "loans_20261117.csv"], out
            assert len(out["batches"]) == 1, out
            bat = _rows(db.batches, batch_id=out["batches"][0])[0]
            assert bat.file_set_id and bat.filename == "loans_20261117.csv"
            s = _rows(db.file_sets, set_id=bat.file_set_id)[0]
            assert s.status == "consumed"
            pulled = _rows(db.pulled_files, schedule_id=sch["schedule_id"])
            assert sorted(p.remote_name for p in pulled) == ["borrowers_20261117.csv", "loans_20261117.csv"]
            assert bat.batch_id in {p.batch_id for p in pulled}
            # pulled_files dedupe: the same remote files are never fetched again
            again = svc.pull_now(sch["schedule_id"], "ops1", ["ops"])
            assert again["fetched"] == [] and again["batches"] == []
    finally:
        srv["sock"].close()


def _sftp(env):
    """Start the in-process SFTP fake of test_sftp_pull (its fixture body, without the fixture machinery)."""
    import base64
    import hashlib
    import socket
    import threading

    import paramiko

    from tests.test_sftp_pull import _serve

    key = paramiko.RSAKey.generate(2048)
    root = env / "sftp"
    (root / "out").mkdir(parents=True)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    threading.Thread(target=_serve, args=(sock, key, str(root)), daemon=True).start()
    fp = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
    return {"port": sock.getsockname()[1], "fingerprint": fp, "root": root, "sock": sock}


# ------------------------------------------------------------------ S3 arrival
def test_s3_arrival_attaches_role(feed, legacy, env, monkeypatch, tmp_path):
    import boto3
    from moto import mock_aws

    from tests.test_lambdas import _aws, _executions, _load

    with mock_aws():
        h = _load(monkeypatch)
        sfn, arn = _aws(monkeypatch)
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="lbp-raw")

        def drop(sid, name, body, meta=None):
            p = tmp_path / name
            p.write_text(body)
            key = f"incoming/{sid}/{name}"
            s3.upload_file(str(p), "lbp-raw", key, ExtraArgs={"Metadata": {"submitted-by": "vendor-sftp", **(meta or {})}})
            return h.on_file_arrival({"detail": {"bucket": {"name": "lbp-raw"}, "object": {"key": key}}}, None)

        first = drop(feed, "loans_20261117.csv", MASTER)
        assert first["role"] == "master" and first["status"] == "waiting" and first["batch_id"] is None
        assert first.get("execution_arn") is None and _executions(sfn, arn) == []
        second = drop(feed, "borrowers_20261117.csv", BORR, {"role": "borrowers"})
        assert second["role"] == "borrowers" and second["set_id"] == first["set_id"] and second["batch_id"]
        assert second["execution_arn"] and len(_executions(sfn, arn)) == 1
        bat = _rows(db.batches, batch_id=second["batch_id"])[0]
        assert bat.file_set_id == first["set_id"] and bat.file_path.startswith("s3://lbp-raw/incoming/")
        # an arrival that routes nowhere is rejected visibly (alert), never dropped silently, and raises nothing
        bad = drop(feed, "payments_20261117.csv", MASTER)
        assert bad.get("rejected") and "payments_20261117.csv" in bad["rejected"]
        alerts = [r.detail for r in _rows(db.audit_log) if r.action == "alert.file_set_rejected"]
        assert alerts and alerts[0]["source_id"] == feed
        # unattended: a feed whose vendor is suspended still records the set's batch, as a failed batch (strict=False)
        with db.get_engine().begin() as c:
            vid = c.execute(select(db.sources.c.vendor_id).where(db.sources.c.source_id == feed)).scalar()
            c.execute(update(db.vendors).where(db.vendors.c.vendor_id == vid).values(status="suspended"))
        drop(feed, "loans_20261118.csv", MASTER + "3,300\n")
        late = drop(feed, "borrowers_20261118.csv", BORR + "3,Cy\n")
        assert late["batch_id"] and late["execution_arn"] is None
        assert _rows(db.batches, batch_id=late["batch_id"])[0].status == "failed"
        # a feed without a layout keeps the single-file path (no set, the original return shape)
        _no_set_code(monkeypatch)
        sample = env / "samples" / "correspondent_sample.csv"
        leg = drop(legacy, "CORR_20261117.csv", sample.read_text())
        assert set(leg) == {"batch_id", "execution_arn"} and leg["execution_arn"]
        assert _rows(db.batches, batch_id=leg["batch_id"])[0].file_set_id is None


# ------------------------------------------------------------------ review fixes (round 1)
OPTIONAL = {**LAYOUT, "files": [LAYOUT["files"][0], {**LAYOUT["files"][1], "required": False}]}


def test_master_only_upload_set_attaches_master_last(client, feed, env):
    """master_only: the master as the FIRST member must not make the set ready before its detail is attached."""
    _configure(feed, OPTIONAL, {**READY, "require": "master_only"})
    z = _zip({"loans_20261117.csv": MASTER, "borrowers_20261117.csv": BORR})
    r = client.post("/api/upload/set", data={"source_id": feed, "auto_start": "false"},
                    files=[("files", ("delivery.zip", z, "application/zip"))], headers=OPS)
    assert r.status_code == 200, r.text
    res = r.json()
    assert len({x["set_id"] for x in res}) == 1 and [x["role"] for x in res] == ["borrowers", "master"]
    assert res[-1]["status"] == "consumed" and res[-1]["batch_id"]
    assert {m.role for m in _rows(db.batch_files, set_id=res[0]["set_id"])} == {"master", "borrowers"}
    assert len(_rows(db.file_sets)) == 1


def test_master_only_pull_attaches_master_last(feed, env):
    from lbp.scheduling import service as svc

    _configure(feed, OPTIONAL, {**READY, "require": "master_only"})
    drop = env / "data" / "dropzone" / "mf"
    drop.mkdir(parents=True)
    (drop / "borrowers_20261117.csv").write_text(BORR)
    (drop / "loans_20261117.csv").write_text(MASTER)  # LocalPuller lists by name: borrowers, loans; also try the reverse
    (drop / "aaa_loans_20261118.csv").write_text(MASTER)  # matches no role
    sch = svc.create_schedule(feed, "Daily", {"cron": "0 6 * * *", "timezone": "UTC", "calendar": "none",
                                              "pull": {"protocol": "local", "path": "mf", "pattern": "*.csv"}}, "ops1", ["ops"])
    svc.decide(sch["schedule_id"], "sme1", ["sme"], True)
    from lbp.scheduling import pullers

    real = pullers.LocalPuller.list
    pullers.LocalPuller.list = lambda self: sorted(real(self), key=lambda f: not f.name.startswith("loans"))  # master first
    try:
        out = svc.pull_now(sch["schedule_id"], "ops1", ["ops"])
    finally:
        pullers.LocalPuller.list = real
    assert sorted(out["fetched"]) == ["borrowers_20261117.csv", "loans_20261117.csv"] and len(out["batches"]) == 1
    sets = _rows(db.file_sets)
    assert len(sets) == 1 and sets[0].status == "consumed"
    assert {m.role for m in _rows(db.batch_files, set_id=sets[0].set_id)} == {"master", "borrowers"}


def test_tick_dispatches_batches_queued_by_the_sweep(feed, env):
    from lbp.multifile import fileset
    from lbp.scheduling import service as svc

    _configure(feed, OPTIONAL, {**READY, "on_timeout": "load_master_only"})
    p = env / "loans_20261117.csv"
    p.write_text(MASTER)
    t0 = datetime(2026, 11, 17, 8, 0)
    a = fileset.attach_file(feed, p.name, p, "ops1", arrived_at=t0)
    out = svc.tick(now=t0 + timedelta(minutes=241))
    s = _rows(db.file_sets, set_id=a["set_id"])[0]
    assert s.status == "consumed" and s.batch_id
    assert out["batches"] == [s.batch_id] and out["file_sets_expired"] == [a["set_id"]]
    assert fileset.expire_sets(t0 + timedelta(minutes=300)) == []  # existing return contract: handled set ids


def test_scheduler_tick_lambda_dispatches_sweep_batches(feed, env, monkeypatch):
    from moto import mock_aws

    from lbp.multifile import fileset
    from tests.test_lambdas import _aws, _executions, _load

    _configure(feed, OPTIONAL, {**READY, "on_timeout": "load_master_only"})
    with mock_aws():
        h = _load(monkeypatch)
        sfn, arn = _aws(monkeypatch)
        p = env / "loans_20261117.csv"
        p.write_text(MASTER)
        fileset.attach_file(feed, p.name, p, "ops1", arrived_at=datetime(2026, 1, 1, 8, 0))  # long expired
        out = h.scheduler_tick({}, None)
        assert out["batches"] == 1
        assert len(_executions(sfn, arn)) == 1


def test_legacy_feed_ignores_a_corrupt_config_bundle(client, legacy, env, monkeypatch):
    _no_set_code(monkeypatch)
    cur = env / "data" / "config" / "feeds" / legacy / "current.json"
    cur.parent.mkdir(parents=True, exist_ok=True)
    cur.write_text("{not json")
    sample = env / "samples" / "correspondent_sample.csv"
    with open(sample, "rb") as f:
        r = client.post("/api/upload", data={"source_id": legacy, "auto_start": "false"},
                        files={"file": ("CORR_20261117.csv", f)}, headers=OPS)
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"batch_id", "status"}


def test_s3_arrival_config_error_is_alerted(feed, env, monkeypatch, tmp_path):
    import boto3
    from moto import mock_aws

    from lbp import config_store
    from tests.test_lambdas import _aws, _load

    with mock_aws():
        h = _load(monkeypatch)
        _aws(monkeypatch)
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="lbp-raw")

        def bad(_sid):
            raise config_store.ConfigError("feed configuration failed signature verification")

        monkeypatch.setattr(config_store, "load", bad)
        p = tmp_path / "loans_20261117.csv"
        p.write_text(MASTER)
        key = f"incoming/{feed}/loans_20261117.csv"
        s3.upload_file(str(p), "lbp-raw", key)
        out = h.on_file_arrival({"detail": {"bucket": {"name": "lbp-raw"}, "object": {"key": key}}}, None)
        assert out.get("rejected") and out["key"] == key
        assert [r for r in _rows(db.audit_log) if r.action == "alert.file_set_rejected"]


def test_upload_set_refuses_bad_requests_before_attaching(client, feed, env):
    def post(files, headers=OPS):
        return client.post("/api/upload/set", data={"source_id": feed, "auto_start": "false"}, files=files, headers=headers)

    before = _upload_dir_files(env)
    # unsupported compression method -> 400
    raw = bytearray(_zip({"loans_20261117.csv": MASTER}))
    for sig, off in ((b"PK\x03\x04", 8), (b"PK\x01\x02", 10)):
        i = raw.find(sig)
        raw[i + off:i + off + 2] = (99).to_bytes(2, "little")
    r = post([("files", ("d.zip", bytes(raw), "application/zip"))])
    assert r.status_code == 400, r.text
    # all files of one request share one pairing key
    r = post([("files", ("d.zip", _zip({"loans_20261117.csv": MASTER, "borrowers_20261118.csv": BORR}), "application/zip"))])
    assert r.status_code == 400 and "pairing" in r.text
    # more parts than the layout has roles: refused before any part is saved
    r = post([("files", (f"loans_2026111{i}.csv", MASTER)) for i in range(3)])
    assert r.status_code == 400 and "at most 2" in r.text
    # a non-monitoring role is refused
    assert post([("files", ("loans_20261117.csv", MASTER))], {"X-User": "ana", "X-Roles": "analyst"}).status_code == 403
    assert _rows(db.file_sets) == [] and _upload_dir_files(env) == before


@pytest.fixture()
def unpublished(sample_files):
    """I1: a feed whose approved layout never reached its published bundle (publish failed after approval)."""
    sid = _onboard(sample_files)
    with db.get_engine().begin() as c:
        c.execute(update(db.sources).where(db.sources.c.source_id == sid).values(layout=LAYOUT, readiness=READY))
    assert config_store.load(sid).layout is None
    return sid


def test_approved_layout_without_published_bundle_is_an_error(unpublished):
    from lbp.multifile.fileset import feed_layout

    with pytest.raises(config_store.ConfigError, match="republish"):
        feed_layout(unpublished)


def test_upload_refuses_feed_whose_layout_is_not_published(client, unpublished, env):
    with open(env / "samples" / "pcg_retail_sample.csv", "rb") as f:
        r = client.post("/api/upload", data={"source_id": unpublished, "auto_start": "false"},
                        files={"file": ("loans_20261117.csv", f)}, headers=OPS)
    assert r.status_code == 400 and "republish" in r.text
    assert _rows(db.batches, source_id=unpublished) == []


def test_s3_arrival_for_unpublished_layout_is_alerted(unpublished, env, monkeypatch, tmp_path):
    import boto3
    from moto import mock_aws

    from tests.test_lambdas import _aws, _load

    with mock_aws():
        h = _load(monkeypatch)
        with db.get_engine().begin() as c:  # _aws republishes every feed: publish this one without its layout again
            c.execute(update(db.sources).where(db.sources.c.source_id == unpublished).values(layout=None))
        _aws(monkeypatch)
        with db.get_engine().begin() as c:
            c.execute(update(db.sources).where(db.sources.c.source_id == unpublished).values(layout=LAYOUT))
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="lbp-raw")
        p = tmp_path / "loans_20261117.csv"
        p.write_text(MASTER)
        key = f"incoming/{unpublished}/loans_20261117.csv"
        s3.upload_file(str(p), "lbp-raw", key)
        out = h.on_file_arrival({"detail": {"bucket": {"name": "lbp-raw"}, "object": {"key": key}}}, None)
        assert out.get("rejected") and "ConfigError" in out["rejected"]  # alerted, never a single-file batch
    assert _rows(db.batches, source_id=unpublished) == []
