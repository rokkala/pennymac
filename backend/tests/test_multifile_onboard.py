"""Multi-file onboarding (Task 3): a feed, its joined-sample mapping and its pending layout from sample files."""
import copy
import json

import pytest
from sqlalchemy import func, select

from lbp import samples
from lbp.mapping import service as ms
from lbp.multifile import onboard
from lbp.multifile.onboard import OnboardError, inspect_files, register_multifile_source
from lbp.store import db

ONB = ["onboarding"]
ANA = {"X-User": "ana", "X-Roles": "analyst"}
OPS = {"X-User": "oli", "X-Roles": "ops"}


def _files(tmp_path, n=60):
    out = samples.generate_master_detail(tmp_path / "md", n, date="20261117", seed=7, offset=10_000)
    return {"master": out["master"], "escrow_items": out["details"]}


def _counts():
    tabs = [db.sources, db.mappings, db.vendors]
    with db.get_engine().connect() as c:
        return {t.name: c.execute(select(func.count()).select_from(t)).scalar() for t in tabs}


def _reg(files, layout=None, name="Escrow two-file", **kw):
    return register_multifile_source(name, files, layout or samples.master_detail_layout(), samples.master_detail_readiness(),
                                     "ana", ONB, **kw)


def _src(sid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.sources).where(db.sources.c.source_id == sid)).first()


def _mapping(mid):
    with db.get_engine().connect() as c:
        return c.execute(select(db.mappings).where(db.mappings.c.mapping_id == mid)).first()


def test_inspect_returns_columns_per_role(env):
    files = _files(env)
    out = inspect_files({r: (p.read_bytes(), p.name) for r, p in files.items()})
    assert out["escrow_items"]["columns"] == samples.DETAIL_HEADER
    assert out["escrow_items"]["rows_sampled"] > 0 and out["escrow_items"]["format"] == "csv"
    assert "LoanID" in out["master"]["columns"]


def test_register_creates_feed_mapping_and_pending_layout(env):
    r = _reg(_files(env))
    s, m = _src(r["source_id"]), _mapping(r["mapping_id"])
    assert s and m.version == 1 and m.status == "draft"
    assert s.layout is None and s.layout_draft and r["layout_draft"]["relations"][0]["detail"] == "escrow_items"
    assert s.layout_proposed_by == "ana"
    assert {"escrow_items": samples.DETAIL_HEADER}.items() <= r["role_columns"].items() and "LoanID" in r["role_columns"]["master"]
    assert s.profile["role_columns"] == r["role_columns"]
    by_target = {f["target"]: f["sources"] for f in m.fields}
    assert by_target["tax_annual_amount"] == ["tax_total"] and by_target["hazard_insurance_annual_premium"] == ["hazard_total"]


def test_register_then_full_flow_loads_a_set(env):
    from lbp.multifile.fileset import attach_file
    from lbp.multifile.service import decide_layout
    from lbp.pipeline.batch import run_batch

    files = _files(env, 80)
    r = _reg(files)
    mid, sid = r["mapping_id"], r["source_id"]
    ms.accept_all(mid, "ana", 0.0)
    ms.submit(mid, "ana")
    ms.approve(mid, "rev", ["onboarding_reviewer"], True, "ok")
    decide_layout(sid, "rev", ["onboarding_reviewer"], True, "ok")
    assert _src(sid).layout
    attach_file(sid, files["master"].name, files["master"], "s3-auto-arrival")
    done = attach_file(sid, files["escrow_items"].name, files["escrow_items"], "s3-auto-arrival")
    assert done["batch_id"]
    run_batch(done["batch_id"])
    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == done["batch_id"])).first()
    assert b.status == "completed", b.error
    assert b.loaded > 0 and b.join_summary


def test_wrong_key_no_rows_leaves_no_source_behind(env):
    files = _files(env)
    lay = copy.deepcopy(samples.master_detail_layout())
    lay["relations"][0]["on"] = [{"parent": "LoanID", "detail": "PayeeName"}]   # never matches
    before = _counts()
    with pytest.raises(OnboardError, match="escrow_items"):
        _reg(files, lay)
    assert _counts() == before
    lay["relations"][0]["on"] = [{"parent": "LoanID", "detail": "NoSuchColumn"}]
    with pytest.raises(OnboardError, match="NoSuchColumn"):
        _reg(files, lay)
    assert _counts() == before


def test_zero_match_even_without_min_match_rate(env):
    lay = copy.deepcopy(samples.master_detail_layout())
    lay["relations"][0]["on"] = [{"parent": "LoanID", "detail": "PayeeName"}]
    lay["relations"][0]["min_match_rate"] = 0
    before = _counts()
    with pytest.raises(OnboardError, match="no rows"):
        _reg(_files(env), lay)
    assert _counts() == before


def test_missing_master_role_rejected(env):
    files = _files(env)
    before = _counts()
    with pytest.raises(OnboardError, match="master"):
        _reg({"escrow_items": files["escrow_items"]})
    lay = copy.deepcopy(samples.master_detail_layout())
    lay["files"][0]["role"] = "loans"
    with pytest.raises(OnboardError):
        _reg(files, lay)
    assert _counts() == before


def test_duplicate_role_rejected(env):
    files = _files(env)
    lay = copy.deepcopy(samples.master_detail_layout())
    lay["files"].append(copy.deepcopy(lay["files"][1]))
    before = _counts()
    with pytest.raises(OnboardError, match="escrow_items"):
        _reg(files, lay)
    assert _counts() == before
    with pytest.raises(OnboardError):
        _reg({**files, "extra": files["escrow_items"]})   # a file for a role the layout does not have
    assert _counts() == before


def test_empty_or_header_only_detail_clear_error(env):
    files = _files(env)
    before = _counts()
    head = env / "hdr.csv"
    head.write_text(",".join(samples.DETAIL_HEADER) + "\n")
    with pytest.raises(OnboardError, match="escrow_items.*no data rows"):
        _reg({**files, "escrow_items": head})
    empty = env / "empty.csv"
    empty.write_text("")
    with pytest.raises(OnboardError, match="escrow_items"):
        _reg({**files, "escrow_items": empty})
    junk = env / "junk.xlsx"
    junk.write_bytes(b"\x00\x01not a workbook")
    with pytest.raises(OnboardError, match="escrow_items"):
        _reg({**files, "escrow_items": junk})
    assert _counts() == before
    with pytest.raises(OnboardError, match="escrow_items"):
        inspect_files({"escrow_items": (b"", "x.csv")})
    with pytest.raises(OnboardError, match="escrow_items"):
        inspect_files({"escrow_items": (b"A,B\n", "x.csv")})


def _merge_case(env, master_hdr, detail_hdr, on):
    m, d = env / "m.csv", env / "d.csv"
    m.write_text(",".join(master_hdr) + "\n" + "\n".join(f"{i},{100 + i}" for i in range(1, 6)) + "\n")
    d.write_text(",".join(detail_hdr) + "\n" + "\n".join(f"{i},x{i},y{i}" for i in range(1, 6)) + "\n")
    lay = {"files": [{"role": "master", "key": [on[0]], "required": True, "name_pattern": r"m_(?P<d>\d{8})\.csv"},
                      {"role": "extra", "required": True, "name_pattern": r"e_(?P<d>\d{8})\.csv"}],
           "relations": [{"detail": "extra", "to": "master", "on": [{"parent": on[0], "detail": on[1]}], "mode": "merge"}]}
    return {"master": m, "extra": d}, lay


def test_detail_columns_with_spaces_and_dots(env):
    files, lay = _merge_case(env, ["Loan Id", "Balance"], ["Loan Id", "Fee Type", "amt.net"], ("Loan Id", "Loan Id"))
    r = register_multifile_source("Merge feed", files, lay, {"require": "all_required", "pairing": "business_date"}, "ana", ONB)
    cols = [c["name"] for c in _src(r["source_id"]).profile["columns"]]
    assert "extra.Fee Type" in cols and "extra.amt.net" in cols
    ms.accept_all(r["mapping_id"], "ana", 0.0)     # the mapping engine copes with dotted/spaced names


def test_same_column_name_in_two_roles(env):
    files, lay = _merge_case(env, ["id", "note"], ["id", "note", "z"], ("id", "id"))
    r = register_multifile_source("Same col", files, lay, {"require": "all_required", "pairing": "business_date"}, "ana", ONB)
    cols = [c["name"] for c in _src(r["source_id"]).profile["columns"]]
    assert "note" in cols and "extra.note" in cols
    assert r["role_columns"]["master"] == ["id", "note"] and r["role_columns"]["extra"] == ["id", "note", "z"]


def test_snapshot_or_incremental_delivery_not_possible_at_onboarding(env):
    r = _reg(_files(env))
    from lbp.pipeline.delivery import profile_of
    assert profile_of(_src(r["source_id"]).delivery)["load_type"] == "full"


def test_failure_after_register_rolls_back(env, monkeypatch):
    from lbp.multifile import service
    monkeypatch.setattr(onboard, "propose_layout", lambda *a, **k: (_ for _ in ()).throw(service.LayoutServiceError("boom")))
    before = _counts()
    with pytest.raises(service.LayoutServiceError):
        _reg(_files(env))
    assert _counts() == before


def test_requires_onboarding_role_and_unique_name(env):
    files = _files(env)
    before = _counts()
    with pytest.raises(Exception, match="role required"):
        register_multifile_source("X", files, samples.master_detail_layout(), samples.master_detail_readiness(), "bob", ["monitoring"])
    assert _counts() == before
    r = _reg(files, vendor_id=None)
    with db.get_engine().connect() as c:
        vid = c.execute(select(db.sources.c.vendor_id).where(db.sources.c.source_id == r["source_id"])).scalar()
    with pytest.raises(Exception, match="already has a feed"):
        _reg(files, vendor_id=vid)
    assert _counts()["sources"] == before["sources"] + 1


# ------------------------------------------------------------------ API
def _parts(files):
    return {r: (p.name, p.read_bytes()) for r, p in files.items()}


def test_endpoints_role_gating(client, env):
    files = _files(env)
    for url, data in (("/api/multi-file-feeds/inspect", {}),
                      ("/api/multi-file-feeds/preview", {"layout": json.dumps(samples.master_detail_layout())}),
                      ("/api/multi-file-feeds", {"name": "n", "layout": json.dumps(samples.master_detail_layout())})):
        assert client.post(url, files=_parts(files), data=data, headers=OPS).status_code == 403
    r = client.post("/api/multi-file-feeds/inspect", files=_parts(files), headers=ANA)
    assert r.status_code == 200 and r.json()["escrow_items"]["columns"] == samples.DETAIL_HEADER


def test_register_endpoint_and_errors(client, env):
    files = _files(env)
    data = {"name": "API feed", "description": "d", "layout": json.dumps(samples.master_detail_layout()),
            "readiness": json.dumps(samples.master_detail_readiness())}
    r = client.post("/api/multi-file-feeds", files=_parts(files), data=data, headers=ANA)
    assert r.status_code == 200, r.text
    assert r.json()["layout_draft"] and r.json()["mapping_id"]
    bad = client.post("/api/multi-file-feeds", files={"escrow_items": _parts(files)["escrow_items"]}, data={**data, "name": "B"}, headers=ANA)
    assert bad.status_code == 400 and "master" in bad.json()["detail"]
    nolayout = client.post("/api/multi-file-feeds", files=_parts(files), data={"name": "C"}, headers=ANA)
    assert nolayout.status_code == 400


def test_preview_endpoint_without_source_masks_pii_like_existing_preview(client, env):
    files = _files(env)
    data = {"layout": json.dumps(samples.master_detail_layout()), "readiness": json.dumps(samples.master_detail_readiness())}
    before = _counts()
    r = client.post("/api/multi-file-feeds/preview", files=_parts(files), data=data, headers=ANA)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["errors"] == [] and body["rows"] and "tax_total" in body["columns"]
    tin = files["escrow_items"].read_text().splitlines()[1].split(",")[-1]
    assert tin not in r.text                      # a detail-role PII value never leaves unmasked
    assert _counts() == before
    bad = client.post("/api/multi-file-feeds/preview", files=_parts(files), data={"layout": json.dumps({"files": [], "relations": []})}, headers=ANA)
    assert bad.status_code == 200 and bad.json()["errors"]


# ------------------------------------------------------------------ non-CSV master / detail
def _rewrite(src, dest, delim="|"):
    import csv
    with open(src, newline="") as f, open(dest, "w", newline="") as o:
        csv.writer(o, delimiter=delim, lineterminator="\n").writerows(csv.reader(f))
    return dest


def _pipe_files(env, n=80):
    f = _files(env, n)
    return {"master": _rewrite(f["master"], env / "loans_20261117.txt"),
            "escrow_items": _rewrite(f["escrow_items"], env / "escrow_items_20261117.txt")}


def _layout_txt():
    lay = copy.deepcopy(samples.master_detail_layout())
    for f in lay["files"]:
        f["name_pattern"] = f["name_pattern"].replace(r"\.csv", r"\.txt")
    return lay


def _sample_readers_work(r):
    from lbp.mapping import inspect as minsp
    pv = ms.preview(r["mapping_id"], 50)
    assert pv
    cols = [c["name"] for c in _src(r["source_id"]).profile["columns"]]
    assert "LoanID" in cols and "tax_total" in cols and len(cols) > 10
    assert _src(r["source_id"]).parse_options.get("delimiter") in (",", None) and _src(r["source_id"]).parse_options["format"] == "csv"
    minsp.field_inspect(r["mapping_id"], "tax_annual_amount", 50)
    minsp.value_coverage(r["mapping_id"], "tax_annual_amount")


def test_pipe_delimited_files_register_and_readers_see_joined_columns(env):
    r = _reg(_pipe_files(env), _layout_txt())
    spec = {f["role"]: f for f in r["layout_draft"]["files"]}
    assert spec["master"]["parse_options"]["delimiter"] == "|" and spec["escrow_items"]["parse_options"]["delimiter"] == "|"
    _sample_readers_work(r)


def test_xlsx_master_registers_and_readers_work(env):
    import csv

    import openpyxl
    f = _files(env, 40)
    wb = openpyxl.Workbook()
    ws = wb.active
    with open(f["master"], newline="") as fh:
        for row in csv.reader(fh):
            ws.append(row)
    x = env / "loans_20261117.xlsx"
    wb.save(x)
    lay = copy.deepcopy(samples.master_detail_layout())
    lay["files"][0]["name_pattern"] = r"loans_(?P<date>\d{8})\.xlsx"
    r = _reg({"master": x, "escrow_items": f["escrow_items"]}, lay)
    assert {f["role"]: f for f in r["layout_draft"]["files"]}["master"]["parse_options"]["format"] == "xlsx"
    _sample_readers_work(r)


def test_pipe_delimited_full_flow_loads(env):
    from lbp.multifile.fileset import attach_file
    from lbp.multifile.service import decide_layout
    from lbp.pipeline.batch import run_batch

    files = _pipe_files(env, 80)
    r = _reg(files, _layout_txt())
    mid, sid = r["mapping_id"], r["source_id"]
    ms.accept_all(mid, "ana", 0.0)
    ms.submit(mid, "ana")
    ms.approve(mid, "rev", ["onboarding_reviewer"], True, "ok")
    decide_layout(sid, "rev", ["onboarding_reviewer"], True, "ok")
    attach_file(sid, files["master"].name, files["master"], "s3-auto-arrival")
    done = attach_file(sid, files["escrow_items"].name, files["escrow_items"], "s3-auto-arrival")
    run_batch(done["batch_id"])
    with db.get_engine().connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == done["batch_id"])).first()
    assert b.status == "completed", b.error
    assert b.loaded > 0 and b.join_summary


# ------------------------------------------------------------------ final review: role names, missing samples, tidy-up
BAD_PART_NAMES = ["../x", "ABSOLUTE", "", "Upper", "a" * 41, "layout"]


@pytest.fixture()
def tmproot(tmp_path, monkeypatch):
    """Every temp dir the routes make lives here; after a request nothing may be left in it (or beside it)."""
    import tempfile

    root = tmp_path / "tmproot" / "inner"
    root.mkdir(parents=True)
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


def _part_name(bad, tmp_path):
    return str(tmp_path / "outside" / "pwned") if bad == "ABSOLUTE" else bad


def _nothing_escaped(tmp_path, root):
    assert not (tmp_path / "outside").exists() or not any((tmp_path / "outside").iterdir())
    assert list(root.iterdir()) == []                 # temp dirs removed
    assert [p.name for p in root.parent.iterdir()] == ["inner"]   # nothing written next to them (../x)


@pytest.mark.parametrize("bad", BAD_PART_NAMES)
@pytest.mark.parametrize("url", ["/api/multi-file-feeds/inspect", "/api/multi-file-feeds/preview", "/api/multi-file-feeds"])
def test_bad_part_names_refused_and_nothing_written_outside(client, env, tmp_path, tmproot, url, bad):
    (tmp_path / "outside").mkdir(exist_ok=True)
    files = _files(env)
    parts = {"master": _parts(files)["master"], _part_name(bad, tmp_path): _parts(files)["escrow_items"]}
    data = {"name": "Bad", "layout": json.dumps(samples.master_detail_layout()), "readiness": json.dumps(samples.master_detail_readiness())}
    before = _counts()
    r = client.post(url, files=parts, data=data, headers=ANA)
    assert r.status_code == 400, r.text
    assert "is not allowed" in r.json()["detail"]
    _nothing_escaped(tmp_path, tmproot)
    assert _counts() == before


@pytest.mark.parametrize("bad", ["../x", "ABSOLUTE", "", "Upper", "a" * 41])
def test_bad_layout_role_names_refused_by_preview_and_register(client, env, tmp_path, tmproot, bad):
    (tmp_path / "outside").mkdir(exist_ok=True)
    lay = samples.master_detail_layout()
    role = _part_name(bad, tmp_path)
    lay["files"][1]["role"] = role
    lay["relations"][0]["detail"] = role
    files = _files(env)
    data = {"name": "Bad", "layout": json.dumps(lay), "readiness": json.dumps(samples.master_detail_readiness())}
    r = client.post("/api/multi-file-feeds/preview", files={"master": _parts(files)["master"]}, data=data, headers=ANA)
    assert r.status_code == 200 and any("role name" in e for e in r.json()["errors"]), r.text
    before = _counts()
    with pytest.raises(OnboardError, match="role name"):
        register_multifile_source("Bad", {"master": files["master"], role: files["escrow_items"]}, lay,
                                  samples.master_detail_readiness(), "ana", ONB)
    _nothing_escaped(tmp_path, tmproot)
    assert _counts() == before


def test_preview_refuses_parts_that_are_not_layout_roles(client, env):
    files = _files(env)
    data = {"layout": json.dumps(samples.master_detail_layout()), "readiness": json.dumps(samples.master_detail_readiness())}
    r = client.post("/api/multi-file-feeds/preview", files={**_parts(files), "extra": ("e.csv", b"a\n1\n")}, data=data, headers=ANA)
    assert r.status_code == 400 and "layout role" in r.json()["detail"]


def test_inspect_and_preview_never_name_temp_files_by_role(env, tmproot, monkeypatch):
    """Defence in depth: even called directly (no route check), a hostile role cannot steer a path."""
    from lbp.multifile.preview import preview_join

    files = _files(env)
    evil = str(tmproot.parent / "evil")
    with pytest.raises(OnboardError):
        inspect_files({evil: (files["master"].read_bytes(), "x.csv")})
    lay = samples.master_detail_layout()
    out = preview_join(lay, samples.master_detail_readiness(),
                       {"master": (files["master"].read_bytes(), "m.csv"), evil: (files["escrow_items"].read_bytes(), "d.csv")}, {})
    assert out["errors"]
    assert not list(tmproot.parent.glob("evil*")) and list(tmproot.iterdir()) == []


def test_layout_role_without_a_sample_file_is_a_clear_error_not_500(client, env):
    """The wizard's layout editor can add a detail role that has no sample slot: the check must say so."""
    lay = samples.master_detail_layout()
    lay["files"].append({"role": "fees", "name_pattern": r"fees_(?P<date>\d{8})\.csv", "required": False})
    lay["relations"].append({"detail": "fees", "to": "master", "on": [{"parent": "LoanID", "detail": "LoanRef"}], "mode": "merge"})
    files = _files(env)
    data = {"name": "Gap", "layout": json.dumps(lay), "readiness": json.dumps(samples.master_detail_readiness())}
    r = client.post("/api/multi-file-feeds/preview", files=_parts(files), data=data, headers=ANA)
    assert r.status_code == 200, r.text
    assert any("no sample file was sent for the fees role" in e for e in r.json()["errors"])
    before = _counts()
    r = client.post("/api/multi-file-feeds", files=_parts(files), data=data, headers=ANA)
    assert r.status_code == 400 and "no sample file was sent for the fees role" in r.json()["detail"]
    assert _counts() == before
    from lbp.multifile.layout import LayoutError
    from lbp.multifile.preview import build_joined_sample

    with pytest.raises(LayoutError, match="no sample file was sent for the fees role"):
        build_joined_sample(lay, samples.master_detail_readiness(), dict(files), {}, env / "out")


def _sample_dir(env):
    return env / "data" / "samples"


def test_failed_onboarding_removes_the_joined_sample(env, monkeypatch):
    from lbp.multifile import service

    monkeypatch.setattr(onboard, "propose_layout", lambda *a, **k: (_ for _ in ()).throw(service.LayoutServiceError("boom")))
    with pytest.raises(service.LayoutServiceError):
        _reg(_files(env))
    assert not _sample_dir(env).exists() or list(_sample_dir(env).iterdir()) == []


def test_register_source_failure_removes_the_joined_sample(env, monkeypatch):
    def boom(*a, **k):
        raise ms.MappingError("this vendor already has a feed named X")

    monkeypatch.setattr(ms, "register_source", boom)
    before = _counts()
    with pytest.raises(ms.MappingError):
        _reg(_files(env))
    assert not _sample_dir(env).exists() or list(_sample_dir(env).iterdir()) == []
    assert _counts() == before


def test_successful_onboarding_keeps_its_joined_sample(env):
    _reg(_files(env))
    assert len(list(_sample_dir(env).iterdir())) == 1
