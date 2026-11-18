"""Match-rate gate exemption (Task 15, Ruling V): a relation whose detail role is absent (accepted missing by an
override or released by load_master_only) is not gated; a relation whose detail file is present still is."""
from __future__ import annotations

from pathlib import Path

from lbp.multifile.joiner import join_files, match_rate_gate
from lbp.multifile.layout import normalize_layout

LAYOUT = {
    "files": [
        {"role": "master", "name_pattern": r"m_(?P<d>\d+)\.csv", "key": ["id"], "required": True},
        {"role": "fees", "name_pattern": r"f_(?P<d>\d+)\.csv", "required": False},
        {"role": "notes", "name_pattern": r"n_(?P<d>\d+)\.csv", "required": False},
    ],
    "relations": [
        {"detail": "fees", "to": "master", "on": [{"parent": "id", "detail": "ref"}], "mode": "aggregate",
         "min_match_rate": 0.9, "aggregate": {"columns": [{"as": "fee_n", "op": "count"}]}},
        {"detail": "notes", "to": "master", "on": [{"parent": "id", "detail": "ref"}], "mode": "aggregate",
         "min_match_rate": 0.9, "aggregate": {"columns": [{"as": "note_n", "op": "count"}]}},
    ],
}


def test_gate_skips_only_absent_relations():
    rels = normalize_layout(LAYOUT)["relations"]
    low = {"fees": 0.0, "notes": 0.5}
    full = match_rate_gate(rels, low, {})
    assert "fees->master" in full and "notes->master" in full
    assert match_rate_gate(rels, low, {}, absent_roles=["fees"]) == (
        "relation notes->master: master match rate 50.0% is below min_match_rate 90.0%")  # text unchanged
    assert match_rate_gate(rels, low, {}, absent_roles=["fees", "notes"]) is None
    assert match_rate_gate(rels, {"fees": 0.0, "notes": 1.0}, {}, absent_roles=["fees"]) is None


def test_join_files_exempts_absent_role(tmp_path: Path):
    (tmp_path / "m.csv").write_text("id\n1\n2\n", encoding="utf-8")
    (tmp_path / "fees.csv").write_text("ref\n", encoding="utf-8")  # the empty file an absent role joins against
    (tmp_path / "notes.csv").write_text("ref\n1\n2\n", encoding="utf-8")
    inputs = {"master": tmp_path / "m.csv", "fees": tmp_path / "fees.csv", "notes": tmp_path / "notes.csv"}
    blocked = join_files(LAYOUT, inputs, {}, tmp_path / "o1.csv", tmp_path)
    assert blocked.blocked and "fees->master" in blocked.blocked
    ok = join_files(LAYOUT, inputs, {}, tmp_path / "o2.csv", tmp_path, absent_roles=["fees"])
    assert ok.blocked is None and ok.rows_out == 2
    # a present role with a low rate still blocks even when another role is absent
    (tmp_path / "notes.csv").write_text("ref\n1\n", encoding="utf-8")
    still = join_files(LAYOUT, inputs, {}, tmp_path / "o3.csv", tmp_path, absent_roles=["fees"])
    assert still.blocked and "notes->master" in still.blocked and "fees->master" not in still.blocked
