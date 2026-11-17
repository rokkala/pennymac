"""Golden-fixture harness for the multi-file join (the fixtures are the spec of record).

Every directory under fixtures/joins/ is one case: a layout, input files by role, the expected joined CSV,
the expected exceptions (code, role, row_number), the expected `blocked` message and optionally the expected
per-role counts. A case may list `variants`, each overriding fields of the first relation (`relation`) and/or
input files (`files`) and carrying its own expectations. Every case runs against every engine in ENGINES; a
later phase registers the Spark engine here for parity.
"""
from __future__ import annotations

import csv
import json
import logging
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest

from lbp.multifile.joiner import JoinResult, RoleStats, join_files
from lbp.multifile.layout import LayoutError

FIXTURES = Path(__file__).parent / "fixtures" / "joins"
ENGINES: dict[str, Callable[..., JoinResult]] = {"local": join_files}
CASES = sorted(p for p in FIXTURES.iterdir() if (p / "case.json").is_file())
EXPECT_KEYS = ("expected_rows", "expected_exceptions", "expected_blocked", "expected_per_role")


def load_case(case_dir: Path, variant: str | None = None) -> dict:
    """The case with the named variant applied (relation overrides, file overrides, expectations)."""
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    if variant is None:
        return case
    v = next(v for v in case["variants"] if v["id"] == variant)
    case["layout"]["relations"][0].update(v.get("relation") or {})
    case["files"] = {**case["files"], **(v.get("files") or {})}
    for k in EXPECT_KEYS:
        case.pop(k, None)
        if k in v:
            case[k] = v[k]
    return case


def case_ids() -> list[tuple[Path, str | None]]:
    out: list[tuple[Path, str | None]] = []
    for p in CASES:
        variants = json.loads((p / "case.json").read_text(encoding="utf-8")).get("variants")
        if variants:
            out.extend((p, v["id"]) for v in variants)
        else:
            out.append((p, None))
    return out


CASE_VARIANTS = case_ids()


def read_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def read_exceptions(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_case(case_dir: Path, engine: str, tmp_path: Path, variant: str | None = None) -> tuple[dict, JoinResult, Path]:
    case = load_case(case_dir, variant)
    inputs = {role: case_dir / name for role, name in case["files"].items()}
    out = tmp_path / "joined.csv"
    work = tmp_path / "work"
    work.mkdir()
    res = ENGINES[engine](case["layout"], inputs, case.get("parse_options") or {}, out, work)
    return case, res, out


@pytest.mark.parametrize("engine", sorted(ENGINES))
@pytest.mark.parametrize(("case_dir", "variant"), CASE_VARIANTS,
                         ids=[p.name + (f"-{v}" if v else "") for p, v in CASE_VARIANTS])
def test_golden_case(case_dir: Path, variant: str | None, engine: str, tmp_path: Path):
    case, res, out = run_case(case_dir, engine, tmp_path, variant)
    expected = read_csv(case_dir / case["expected_rows"])
    assert read_csv(out) == expected
    assert res.columns == expected[0]
    assert res.rows_out == len(expected) - 1
    got = sorted((e["code"], e["role"], e["row_number"]) for e in read_exceptions(res.exceptions_path))
    want = sorted((e["code"], e["role"], e["row_number"]) for e in case["expected_exceptions"])
    assert got == want
    assert res.exception_counts == dict(Counter(code for code, _, _ in want))
    assert res.blocked == case["expected_blocked"]
    for role, stats in (case.get("expected_per_role") or {}).items():
        assert res.per_role[role] == RoleStats(**stats), role
    assert not list((tmp_path / "work").iterdir()), "temp DB must be removed"


def test_harness_finds_cases():
    names = [p.name for p in CASES]
    for case in ("merge_basic", "orphans", "duplicate_master", "cardinality_one", "inner_join", "empty_files",
                 "low_match_rate", "composite_key"):
        assert case in names


def test_merge_basic_counts(tmp_path: Path):
    _, res, _ = run_case(FIXTURES / "merge_basic", "local", tmp_path)
    assert res.per_role["master"] == RoleStats(rows_in=3, matched=2, orphaned=0, rejected=0)
    assert res.per_role["details"] == RoleStats(rows_in=2, matched=2, orphaned=0, rejected=0)
    assert res.master_match_rate == pytest.approx(2 / 3)
    assert res.detail_match_rate == {"details": 1.0}
    assert res.exception_counts == {}
    assert res.exceptions_path.is_file()
    assert not list((tmp_path / "work").iterdir()), "temp DB must be removed"


def quirks_layout(mode: str = "merge") -> dict:
    return {
        "files": [
            {"role": "master", "name_pattern": r"m_(?P<date>\d+)\.csv", "key": ["id"], "required": True},
            {"role": "details", "name_pattern": r"d_(?P<date>\d+)\.csv", "required": True},
        ],
        "relations": [{"detail": "details", "to": "master", "on": [{"parent": "id", "detail": "id"}], "mode": mode,
                       "cardinality": "one"}],
    }


def test_header_quirks(tmp_path: Path):
    master = tmp_path / "m.csv"
    master.write_text("id,status,note\n1,open,x\n2,closed,y\n", encoding="utf-8-sig")  # BOM'd
    detail = tmp_path / "d.csv"
    detail.write_text("id;status;amt\n2;late;9.50\n1;current;3\n", encoding="utf-8")
    out = tmp_path / "out.csv"
    res = join_files(quirks_layout(), {"master": master, "details": detail}, {"details": {"delimiter": ";"}}, out, tmp_path)
    rows = read_csv(out)
    # The BOM is not part of the first header; a detail column named like a master column is namespaced.
    assert rows[0] == ["id", "status", "note", "details.id", "details.status", "details.amt"]
    assert rows[1:] == [["1", "open", "x", "1", "current", "3"], ["2", "closed", "y", "2", "late", "9.50"]]
    assert res.columns == rows[0]
    assert out.read_bytes()[:3] != b"\xef\xbb\xbf"


def test_orphan_detail_is_an_exception(tmp_path: Path):
    master = tmp_path / "m.csv"
    master.write_text("id,v\n1,a\n", encoding="utf-8")
    detail = tmp_path / "d.csv"
    detail.write_text("id,w\n9,z\n1,b\n", encoding="utf-8")
    res = join_files(quirks_layout(), {"master": master, "details": detail}, {}, tmp_path / "o.csv", tmp_path)
    exc = read_exceptions(res.exceptions_path)
    assert [(e["code"], e["role"], e["row_number"], e["key"]) for e in exc] == [("JOIN01", "details", 1, "9")]
    assert exc[0]["raw"] == {"id": "9", "w": "z"}
    assert res.exception_counts == {"JOIN01": 1}
    assert res.per_role["details"] == RoleStats(rows_in=2, matched=1, orphaned=1, rejected=0)
    assert res.detail_match_rate == {"details": 0.5}


def test_unsupported_mode_is_layout_error(tmp_path: Path):
    master = tmp_path / "m.csv"
    master.write_text("id\n1\n", encoding="utf-8")
    with pytest.raises(LayoutError, match="mode"):
        join_files(quirks_layout("flatten"), {"master": master, "details": master}, {}, tmp_path / "o.csv", tmp_path)


def test_missing_key_column_is_layout_error(tmp_path: Path):
    master = tmp_path / "m.csv"
    master.write_text("other\n1\n", encoding="utf-8")
    with pytest.raises(LayoutError, match="id"):
        join_files(quirks_layout(), {"master": master, "details": master}, {}, tmp_path / "o.csv", tmp_path)


@pytest.mark.parametrize("role", ["master", "details"])
def test_zero_byte_file_is_layout_error(role: str, tmp_path: Path):
    d = FIXTURES / "empty_files"
    inputs = {"master": d / "master.csv", "details": d / "details.csv", role: d / "empty.csv"}
    out = tmp_path / "o.csv"
    with pytest.raises(LayoutError, match=f"{role}.*empty file"):
        join_files(load_case(d)["layout"], inputs, {}, out, tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == [], "no partial outputs or temp DB left behind"


def test_merge_with_cardinality_many_is_layout_error(tmp_path: Path):
    lay = quirks_layout()
    lay["relations"][0]["cardinality"] = "many"
    master = tmp_path / "m.csv"
    master.write_text("id\n1\n", encoding="utf-8")
    with pytest.raises(LayoutError, match="cardinality"):
        join_files(lay, {"master": master, "details": master}, {}, tmp_path / "o.csv", tmp_path)


def npi_layout() -> dict:
    return {
        "files": [
            {"role": "master", "name_pattern": r"m_(?P<date>\d+)\.csv", "key": ["id"], "required": True},
            {"role": "details", "name_pattern": r"d_(?P<date>\d+)\.csv", "required": True},
            {"role": "items", "name_pattern": r"i_(?P<date>\d+)\.csv", "required": True},
        ],
        "relations": [
            {"detail": "details", "to": "master", "on": [{"parent": "id", "detail": "ref"}], "mode": "merge",
             "cardinality": "one", "on_missing_detail": "exception", "min_match_rate": 0.99},
            {"detail": "items", "to": "master", "on": [{"parent": "id", "detail": "ref"}], "mode": "aggregate",
             "on_duplicate_master": "first", "aggregate": {"columns": [{"as": "total", "op": "sum", "col": "amt"}]}},
        ],
    }


def test_exceptions_raw_not_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    # Every value is distinctive, so finding one in a log line or message is never a coincidence.
    master = "id,name\nK1001,SecretAnna\nK1002,SecretBert\nK1002,SecretCarl\nK1003,SecretDora\n,SecretEmil\nK1004,SecretFynn\n"
    details = "ref,note\nK1001,NoteAlpha\nK1009,NoteOrphan\nK1003,NoteGamma\nK1003,NoteDelta\n,NoteNull\n"
    items = "ref,amt\nK1001,AmtNotANumber\nK1002,77.5\n"
    files = {}
    for role, text in (("master", master), ("details", details), ("items", items)):
        files[role] = tmp_path / f"{role}.csv"
        files[role].write_text(text, encoding="utf-8")
    values = {v for text in (master, details, items) for line in text.splitlines()[1:] for v in line.split(",") if v}
    work = tmp_path / "work"
    work.mkdir()
    with caplog.at_level(logging.DEBUG):
        res = join_files(npi_layout(), files, {}, tmp_path / "o.csv", work)
    exc = read_exceptions(res.exceptions_path)
    assert {e["code"] for e in exc} == {"JOIN01", "JOIN02", "JOIN03", "JOIN04", "JOIN05", "JOIN07"}
    assert res.blocked is not None
    assert caplog.records, "the join logs a summary"
    texts = [caplog.text, res.blocked, *(e["message"] for e in exc)]
    leaked = sorted(v for v in values for t in texts if v in t)
    assert leaked == []
    j05 = [e for e in exc if e["code"] == "JOIN05"]
    assert {e["role"] for e in j05} == {"master", "details"}
    assert all(("id" in e["message"] or "ref" in e["message"]) and e["key"] is None for e in j05)
    # raw payloads stay in the JSONL (masking happens when they are persisted)
    assert any(e["raw"].get("note") == "NoteOrphan" for e in exc)


def test_failure_mid_join_removes_partial_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from lbp.multifile import joiner

    def boom(self, rows):
        raise RuntimeError("engine failure")

    monkeypatch.setattr(joiner.MergeMode, "reduce", boom)
    d = FIXTURES / "merge_basic"
    case = load_case(d)
    work = tmp_path / "work"
    work.mkdir()
    out = tmp_path / "o.csv"
    with pytest.raises(RuntimeError):
        join_files(case["layout"], {r: d / n for r, n in case["files"].items()}, {}, out, work)
    assert not out.exists() and not out.with_name("o.exceptions.jsonl").exists()
    assert not list(work.iterdir())


def test_layout_error_from_headers_removes_outputs(tmp_path: Path):
    lay = npi_layout()
    lay["relations"][1]["aggregate"]["columns"][0]["col"] = "nope"
    m = tmp_path / "m.csv"
    m.write_text("id\n1\n", encoding="utf-8")
    d = tmp_path / "d.csv"
    d.write_text("ref,amt\n1,2\n", encoding="utf-8")
    out = tmp_path / "out" / "o.csv"
    out.parent.mkdir()
    with pytest.raises(LayoutError, match="nope"):
        join_files(lay, {"master": m, "details": d, "items": d}, {}, out, tmp_path)
    assert not list(out.parent.iterdir())


def test_duplicate_output_column_checked_before_loading_details(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from lbp.multifile import joiner

    calls: list[str] = []
    real = joiner._batched_insert
    monkeypatch.setattr(joiner, "_batched_insert", lambda conn, sql, rows: (calls.append(sql), real(conn, sql, rows)))
    lay = npi_layout()
    lay["relations"][1]["aggregate"]["columns"][0]["as"] = "name"  # clashes with a master column
    m = tmp_path / "m.csv"
    m.write_text("id,name\n1,a\n", encoding="utf-8")
    d = tmp_path / "d.csv"
    d.write_text("ref,amt\n1,2\n", encoding="utf-8")
    with pytest.raises(LayoutError, match="name"):
        join_files(lay, {"master": m, "details": d, "items": d}, {}, tmp_path / "o.csv", tmp_path)
    assert not [c for c in calls if "detail_" in c], "no detail rows loaded before the column check"
