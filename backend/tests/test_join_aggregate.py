"""Aggregate mode: where / order_by / formatting / memory, beyond what the golden fixtures pin."""
from __future__ import annotations

from pathlib import Path

import pytest

from lbp.multifile.joiner import join_files
from lbp.multifile.layout import LayoutError
from tests.test_join_golden import read_csv, read_exceptions


def layout(columns: list[dict]) -> dict:
    return {
        "files": [
            {"role": "master", "name_pattern": r"m_(?P<date>\d+)\.csv", "key": ["id"], "required": True},
            {"role": "items", "name_pattern": r"i_(?P<date>\d+)\.csv", "required": True},
        ],
        "relations": [{"detail": "items", "to": "master", "on": [{"parent": "id", "detail": "ref"}],
                       "mode": "aggregate", "aggregate": {"columns": columns}}],
    }


def run(tmp_path: Path, columns: list[dict], detail: str, master: str = "id\n1\n") -> list[list[str]]:
    m, d = tmp_path / "m.csv", tmp_path / "d.csv"
    m.write_text(master, encoding="utf-8")
    d.write_text(detail, encoding="utf-8")
    join_files(layout(columns), {"master": m, "items": d}, {}, tmp_path / "o.csv", tmp_path)
    return read_csv(tmp_path / "o.csv")


DETAIL = "ref,amt,kind,dt\n1,5,fee,2024-01-03\n1,9,tax,2024-01-01\n1,2,fee,2024-01-02\n1,,fee,\n"


def test_aggregate_where_and_order_by(tmp_path: Path):
    cols = [
        {"as": "fee_total", "op": "sum", "col": "amt", "where": {"==": [{"var": "kind"}, "fee"]}},
        {"as": "fee_n", "op": "count", "where": {"==": [{"var": "kind"}, "fee"]}},
        {"as": "n", "op": "count"},
        {"as": "first_file", "op": "first", "col": "amt"},
        {"as": "first_desc", "op": "first", "col": "amt", "order_by": [{"col": "amt", "desc": True, "type": "number"}]},
        {"as": "first_asc", "op": "first", "col": "amt", "order_by": [{"col": "amt", "type": "number"}]},
        {"as": "last_by_date", "op": "last", "col": "amt", "order_by": [{"col": "dt", "type": "date"}]},
        {"as": "none_match", "op": "sum", "col": "amt", "where": {"==": [{"var": "kind"}, "zzz"]}},
        {"as": "none_n", "op": "count", "where": {"==": [{"var": "kind"}, "zzz"]}},
    ]
    rows = run(tmp_path, cols, DETAIL)
    got = dict(zip(rows[0], rows[1], strict=True))
    assert got["fee_total"] == "7" and got["fee_n"] == "3" and got["n"] == "4"
    assert got["first_file"] == "5"
    assert got["first_desc"] == "9"  # order_by desc changes first
    assert got["first_asc"] == "2"  # the empty amt sorts last in ascending order too
    assert got["last_by_date"] == "5"  # by date: 9, 2, 5, then the empty amt (ignored by last)
    assert got["none_match"] == "" and got["none_n"] == "0"


def test_order_by_nulls_last_descending_and_stable_ties(tmp_path: Path):
    detail = "ref,amt,tag\n1,,a\n1,3,b\n1,3,c\n1,1,d\n"
    cols = [
        {"as": "desc_all", "op": "concat_distinct", "col": "tag",
         "order_by": [{"col": "amt", "desc": True, "type": "number"}]},
        {"as": "asc_all", "op": "concat_distinct", "col": "tag", "order_by": [{"col": "amt", "type": "number"}]},
        {"as": "text_desc", "op": "concat_distinct", "col": "tag", "order_by": [{"col": "tag", "desc": True}]},
    ]
    rows = run(tmp_path, cols, detail)
    assert rows[1][1:] == ["b|c|d|a", "d|b|c|a", "d|c|b|a"]


def test_sum_is_decimal_without_float_artifacts(tmp_path: Path):
    rows = run(tmp_path, [{"as": "t", "op": "sum", "col": "amt"}], "ref,amt\n1,0.1\n1,0.2\n1,0.7\n")
    assert rows[1][1] == "1"
    rows = run(tmp_path, [{"as": "t", "op": "sum", "col": "amt"}], "ref,amt\n1,0.10\n1,0.20\n1,-0.05\n")
    assert rows[1][1] == "0.25"
    rows = run(tmp_path, [{"as": "t", "op": "sum", "col": "amt"}], "ref,amt\n1,100\n1,200\n")
    assert rows[1][1] == "300"  # no exponent form


def test_sum_skips_non_numeric_and_records_join07_without_the_value(tmp_path: Path):
    m, d = tmp_path / "m.csv", tmp_path / "d.csv"
    m.write_text("id\n1\n2\n", encoding="utf-8")
    d.write_text("ref,amt\n1,4\n1,SECRET-123\n1,6\n2,N/A\n", encoding="utf-8")
    cols = [{"as": "t", "op": "sum", "col": "amt"}, {"as": "n", "op": "count"}]
    res = join_files(layout(cols), {"master": m, "items": d}, {}, tmp_path / "o.csv", tmp_path)
    assert read_csv(tmp_path / "o.csv") == [["id", "t", "n"], ["1", "10", "3"], ["2", "", "1"]]
    assert res.exception_counts == {"JOIN07": 2}
    exc = read_exceptions(res.exceptions_path)
    assert [(e["code"], e["role"], e["row_number"], e["key"]) for e in exc] == [
        ("JOIN07", "items", 2, "1"), ("JOIN07", "items", 4, "2")]
    assert all("SECRET-123" not in e["message"] and "amt" in e["message"] and "items" in e["message"] for e in exc)


def test_absurd_exponents_are_not_numeric(tmp_path: Path):
    from lbp.multifile.joiner import _dec

    assert _dec("1E999999999") is None and _dec("1e-50") is None and _dec("NaN") is None
    assert _dec("1E5") is not None
    rows = run(tmp_path, [{"as": "t", "op": "sum", "col": "amt"}, {"as": "hi", "op": "max", "col": "amt"}],
               "ref,amt\n1,1E999999999\n1,3\n")
    assert rows[1][1] == "3" and len(rows[1][2]) < 50


def test_missing_aggregate_source_column_is_layout_error(tmp_path: Path):
    with pytest.raises(LayoutError, match="nope"):
        run(tmp_path, [{"as": "t", "op": "sum", "col": "nope"}], "ref,amt\n1,1\n")
    with pytest.raises(LayoutError, match="zip"):
        run(tmp_path, [{"as": "t", "op": "count", "order_by": [{"col": "zip"}]}], "ref,amt\n1,1\n")
    with pytest.raises(LayoutError, match=r"items.*status"):
        run(tmp_path, [{"as": "t", "op": "count", "where": {"==": [{"var": "status"}, "x"]}}], "ref,amt\n1,1\n")


def test_aggregate_needs_a_spec(tmp_path: Path):
    lay = layout([{"as": "n", "op": "count"}])
    lay["relations"][0]["aggregate"] = {}
    m = tmp_path / "m.csv"
    m.write_text("id\n1\n", encoding="utf-8")
    with pytest.raises(LayoutError):
        join_files(lay, {"master": m, "items": m}, {}, tmp_path / "o.csv", tmp_path)


@pytest.mark.parametrize(("policy", "n_join07", "rows_out"), [("first", 1, 1), ("last", 1, 1), ("reject_all", 0, 0)])
def test_join07_not_repeated_for_duplicate_master_keys(tmp_path: Path, policy: str, n_join07: int, rows_out: int):
    lay = layout([{"as": "total", "op": "sum", "col": "amt"}])
    lay["relations"][0]["on_duplicate_master"] = policy
    m, d = tmp_path / "m.csv", tmp_path / "d.csv"
    m.write_text("id\n1\n1\n1\n", encoding="utf-8")
    d.write_text("ref,amt\n1,bad\n1,3\n", encoding="utf-8")
    res = join_files(lay, {"master": m, "items": d}, {}, tmp_path / "o.csv", tmp_path)
    codes = [e["code"] for e in read_exceptions(res.exceptions_path)]
    assert codes.count("JOIN07") == n_join07
    assert res.exception_counts.get("JOIN07", 0) == n_join07
    assert res.exception_counts["JOIN03"] == 3 - rows_out
    assert res.rows_out == rows_out
