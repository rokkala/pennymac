"""Join preview (Task 13): a capped sample joined in a temp dir; read-only, masked, never persisted."""
import json
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import func, select
from test_multifile_intake import _configure, _onboard

from lbp.multifile.layout import validate_layout
from lbp.multifile.preview import MASTER_SAMPLE_ROWS, ORPHAN_SAMPLE_ROWS, preview_join
from lbp.store import db

LAYOUT = {
    "files": [
        {"role": "master", "entity": "thing", "name_pattern": r"m_(?P<d>\d{8})\.csv", "key": ["id"], "required": True},
        {"role": "notes", "name_pattern": r"n_(?P<d>\d{8})\.csv", "required": True},
    ],
    "relations": [{"detail": "notes", "to": "master", "on": [{"parent": "id", "detail": "ref"}], "mode": "merge",
                   "normalize": ["trim", "strip_leading_zeros"]}],
}
READY = {"require": "all_required", "pairing": "business_date"}
NPI = "123-45-6789"


def _csv(header, rows):
    return ("\n".join([",".join(header)] + [",".join(r) for r in rows]) + "\n").encode()


def _samples(master_rows, detail_rows):
    return {"master": (_csv(["id", "ssn", "amount"], master_rows), "m_20261117.csv"),
            "notes": (_csv(["ref", "tag", "email"], detail_rows), "n_20261117.csv")}


def _counts():
    tabs = [db.sources, db.batches, db.exceptions, db.audit_log, db.file_sets, db.batch_files, db.config_publications]
    with db.get_engine().connect() as c:
        return {t.name: c.execute(select(func.count()).select_from(t)).scalar() for t in tabs}


def test_preview_reports_match_rate_and_masked_rows(env):
    master = [[str(i), NPI, "10"] for i in range(1, 5)]
    detail = [["001", "a", "jo@x.com"], ["2", "b", "x@y.org"], ["99", "orphan", "z@z.io"]]
    out = preview_join(LAYOUT, READY, _samples(master, detail), {}, n=3)
    assert out["errors"] == [] and out["sampled"] is False
    assert out["columns"][:3] == ["id", "ssn", "amount"] and "notes.tag" in out["columns"]
    assert len(out["rows"]) == 3
    assert out["master_match_rate"] == 0.5          # ids 1 and 2 of 4 have a detail row (leading zeros normalised)
    assert out["detail_match_rate"]["notes"] == pytest.approx(2 / 3)
    assert out["per_role"]["master"]["rows_in"] == 4 and out["per_role"]["notes"]["orphaned"] == 1
    blob = json.dumps(out)
    assert NPI not in blob and "6789" in blob       # masked, last four kept
    assert "jo@x.com" not in blob                    # email column of a detail role masked
    assert out["rows"][0]["notes.tag"] == "a"
    assert out["blocked"] is None
    for ex in out["exceptions"]:
        assert set(ex) == {"code", "role", "row_number", "message", "raw", "key"}


def test_preview_blocked_by_min_match_rate(env):
    lay = json.loads(json.dumps(LAYOUT))
    lay["relations"][0]["min_match_rate"] = 0.9
    out = preview_join(lay, READY, _samples([["1", NPI, "1"], ["2", NPI, "1"]], [["1", "a", "e@e.io"]]), {})
    assert out["blocked"] and "min_match_rate" in out["blocked"] and NPI not in json.dumps(out)


def test_preview_invalid_layout_returns_errors_not_500(env, client, sample_files):
    bad = {"files": [], "relations": []}
    out = preview_join(bad, READY, {}, {})
    assert out == {"errors": validate_layout(bad, READY)} and out["errors"]
    # a join-time error (missing column) is a safe message without row values
    s = _samples([["1", NPI, "1"]], [["1", "a", "e@e.io"]])
    s["notes"] = (_csv(["other"], [["1"]]), "n_20261117.csv")
    out = preview_join(LAYOUT, READY, s, {})
    assert out["errors"] and "notes" in out["errors"][0] and NPI not in json.dumps(out)
    # over HTTP: 200 with errors
    sid = _onboard(sample_files)
    r = client.post(f"/api/sources/{sid}/layout/preview", data={"layout": json.dumps(bad), "readiness": json.dumps(READY)},
                    headers={"X-User": "ana", "X-Roles": "analyst"})
    assert r.status_code == 200 and r.json()["errors"]


def test_preview_does_not_write_db_or_files_outside_tmp(env, sample_files, monkeypatch):
    sid = _onboard(sample_files)
    _configure(sid, LAYOUT, READY)
    before = _counts()
    made = []
    real = tempfile.mkdtemp

    def spy(*a, **k):
        d = real(*a, **k)
        made.append(Path(d))
        return d

    monkeypatch.setattr(tempfile, "mkdtemp", spy)
    data_files = sorted(p for p in env.rglob("*") if p.is_file())
    out = preview_join(LAYOUT, READY, _samples([["1", NPI, "1"]], [["1", "a", "e@e.io"], ["7", "o", "o@o.io"]]), {})
    assert out["errors"] == [] and out["exception_counts"]
    assert _counts() == before
    assert made and not any(p.exists() for p in made)
    assert sorted(p for p in env.rglob("*") if p.is_file()) == data_files


def test_preview_sample_caps_keep_orphans(env):
    n = MASTER_SAMPLE_ROWS + 500
    master = [[str(i), "x", "1"] for i in range(1, n + 1)]
    detail = [[str(i), "t", "e"] for i in (1, 2, MASTER_SAMPLE_ROWS + 1, n)]            # last two: outside the sample
    detail += [[f"9{i:06d}", "o", "e"] for i in range(ORPHAN_SAMPLE_ROWS + 50)]            # many orphans
    out = preview_join(LAYOUT, READY, _samples(master, detail), {}, n=5)
    assert out["sampled"] is True and out["errors"] == []
    assert out["per_role"]["master"]["rows_in"] == MASTER_SAMPLE_ROWS
    # kept: the 2 matching rows plus exactly ORPHAN_SAMPLE_ROWS non-matching ones (the two beyond the master cut
    # count among the orphans, so a few of the 9xxxxxx ones are dropped)
    assert out["per_role"]["notes"]["rows_in"] == 2 + ORPHAN_SAMPLE_ROWS
    assert out["per_role"]["notes"]["orphaned"] == ORPHAN_SAMPLE_ROWS
    assert out["rows_read"]["master"] == n and out["rows_read"]["notes"] == len(detail)
    assert len(out["exceptions"]) <= 20


def test_preview_endpoint_role_gate_and_parts(client, env, sample_files):
    sid = _onboard(sample_files)
    _configure(sid, LAYOUT, READY)
    s = _samples([["1", NPI, "1"]], [["1", "a", "e@e.io"]])
    files = {"master": (s["master"][1], s["master"][0]), "notes": (s["notes"][1], s["notes"][0])}
    url = f"/api/sources/{sid}/layout/preview"
    assert client.post(url, files=files, headers={"X-User": "oli", "X-Roles": "ops"}).status_code == 403
    before = _counts()
    r = client.post(url, files=files, headers={"X-User": "ana", "X-Roles": "analyst"})   # live layout
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["errors"] == [] and body["master_match_rate"] == 1.0 and NPI not in r.text
    assert _counts() == before
    # a part that is not a role of the layout, or more parts than roles, is a 400
    bad = client.post(url, files={**files, "extra": ("e.csv", b"a\n1\n")}, headers={"X-User": "ana", "X-Roles": "analyst"})
    assert bad.status_code == 400
