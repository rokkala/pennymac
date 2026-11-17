"""Golden-fixture harness for the multi-file join (the fixtures are the spec of record).

Every directory under fixtures/joins/ is one case: a layout, input files by role, the expected joined CSV,
the expected exceptions (code, role, row_number) and the expected `blocked` message. Every case runs
against every engine in ENGINES; a later phase registers the Spark engine here for parity.
"""
from __future__ import annotations

import csv
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from lbp.multifile.joiner import JoinResult, RoleStats, join_files
from lbp.multifile.layout import LayoutError

FIXTURES = Path(__file__).parent / "fixtures" / "joins"
ENGINES: dict[str, Callable[..., JoinResult]] = {"local": join_files}
CASES = sorted(p for p in FIXTURES.iterdir() if (p / "case.json").is_file())


def read_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def read_exceptions(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_case(case_dir: Path, engine: str, tmp_path: Path) -> tuple[dict, JoinResult, Path]:
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    inputs = {role: case_dir / name for role, name in case["files"].items()}
    out = tmp_path / "joined.csv"
    work = tmp_path / "work"
    work.mkdir()
    res = ENGINES[engine](case["layout"], inputs, case.get("parse_options") or {}, out, work)
    return case, res, out


@pytest.mark.parametrize("engine", sorted(ENGINES))
@pytest.mark.parametrize("case_dir", CASES, ids=[p.name for p in CASES])
def test_golden_case(case_dir: Path, engine: str, tmp_path: Path):
    case, res, out = run_case(case_dir, engine, tmp_path)
    expected = read_csv(case_dir / case["expected_rows"])
    assert read_csv(out) == expected
    assert res.columns == expected[0]
    assert res.rows_out == len(expected) - 1
    got = sorted((e["code"], e["role"], e["row_number"]) for e in read_exceptions(res.exceptions_path))
    want = sorted((e["code"], e["role"], e["row_number"]) for e in case["expected_exceptions"])
    assert got == want
    assert res.blocked == case["expected_blocked"]


def test_harness_finds_cases():
    assert "merge_basic" in [p.name for p in CASES]


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
        "relations": [{"detail": "details", "to": "master", "on": [{"parent": "id", "detail": "id"}], "mode": mode}],
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


def test_aggregate_not_supported_yet(tmp_path: Path):
    master = tmp_path / "m.csv"
    master.write_text("id\n1\n", encoding="utf-8")
    lay = quirks_layout("aggregate")
    lay["relations"][0]["aggregate"] = {"columns": [{"as": "n", "op": "count"}]}
    with pytest.raises(LayoutError, match="not supported"):
        join_files(lay, {"master": master, "details": master}, {}, tmp_path / "o.csv", tmp_path)


def test_missing_key_column_is_layout_error(tmp_path: Path):
    master = tmp_path / "m.csv"
    master.write_text("other\n1\n", encoding="utf-8")
    with pytest.raises(LayoutError, match="id"):
        join_files(quirks_layout(), {"master": master, "details": master}, {}, tmp_path / "o.csv", tmp_path)
