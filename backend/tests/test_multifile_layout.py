import copy

from lbp.multifile.layout import (
    AGG_OPS,
    DEFAULT_READINESS,
    NORMALIZERS,
    SUPPORTED_MODES,
    LayoutError,
    normalize_layout,
    validate_layout,
)


def layout():
    return {
        "files": [
            {"role": "master", "entity": "loan", "name_pattern": r"loans_(?P<date>\d{8})\.csv", "key": ["loan_id"], "required": True},
            {"role": "fees", "name_pattern": r"fees_(?P<date>\d{8})\.csv", "required": False},
        ],
        "relations": [
            {"detail": "fees", "to": "master", "on": [{"parent": "loan_id", "detail": "loan_ref"}], "mode": "merge",
             "cardinality": "one"},
        ],
    }


def test_constants():
    assert SUPPORTED_MODES == {"merge", "aggregate"}
    assert NORMALIZERS == ("trim", "strip_leading_zeros", "upper")
    assert "concat_distinct" in AGG_OPS and len(AGG_OPS) == 8
    assert DEFAULT_READINESS["on_timeout"] == "alert_only"
    assert issubclass(LayoutError, ValueError)


def test_valid_minimal_layout_has_no_errors():
    assert validate_layout(layout(), None) == []


def test_exactly_one_master_required():
    none = layout()
    none["files"][0]["role"] = "loans"
    none["relations"][0]["to"] = "loans"
    assert any("master" in e for e in validate_layout(none, None))
    two = layout()
    two["files"][1]["role"] = "master"
    assert any("master" in e for e in validate_layout(two, None))


def test_unsupported_mode_rejected():
    for mode in ("flatten", "child"):
        lay = layout()
        lay["relations"][0]["mode"] = mode
        assert any("not yet supported" in e for e in validate_layout(lay, None))


def test_merge_requires_cardinality_one():
    lay = layout()
    lay["relations"][0]["cardinality"] = "many"
    assert any("merge" in e and "cardinality" in e for e in validate_layout(lay, None))
    del lay["relations"][0]["cardinality"]  # the merge default is one, so this is now valid
    assert not any("cardinality" in e for e in validate_layout(lay, None))
    agg = agg_layout("total")
    agg["relations"][0]["cardinality"] = "many"
    assert validate_layout(agg, None) == []


def agg_layout(*names):
    lay = layout()
    lay["relations"][0]["mode"] = "aggregate"
    lay["relations"][0]["aggregate"] = {"columns": [{"as": n, "op": "sum", "col": "fee_amt"} for n in names]}
    return lay


def test_duplicate_output_column_rejected():
    assert validate_layout(agg_layout("total", "other"), None) == []
    assert any("total" in e for e in validate_layout(agg_layout("total", "total"), None))
    errs = validate_layout(agg_layout("loan_id"), None, columns={"master": ["loan_id", "x"]})
    assert any("loan_id" in e for e in errs)


def test_unknown_normalizer_and_agg_op_rejected():
    lay = layout()
    lay["relations"][0]["normalize"] = ["trim", "reverse"]
    assert any("reverse" in e for e in validate_layout(lay, None))
    lay = agg_layout("total")
    lay["relations"][0]["aggregate"]["columns"][0]["op"] = "median"
    assert any("median" in e for e in validate_layout(lay, None))


def test_relation_must_reference_declared_roles():
    lay = layout()
    lay["relations"][0]["detail"] = "ghost"
    assert any("ghost" in e for e in validate_layout(lay, None))
    lay = layout()
    lay["relations"][0]["to"] = "nowhere"
    assert any("nowhere" in e for e in validate_layout(lay, None))


def test_key_parts_count_must_match():
    lay = layout()
    lay["relations"][0]["on"].append({"parent": "x", "detail": "y"})
    assert any("key" in e for e in validate_layout(lay, None))


def test_readiness_timeout_policy_rules():
    lay = layout()
    ready = {"on_timeout": "load_master_only"}
    assert validate_layout(lay, ready) == []
    lay["files"][1]["required"] = True
    assert any("load_master_only" in e for e in validate_layout(lay, ready))
    assert any("on_timeout" in e for e in validate_layout(lay, {"on_timeout": "bogus"}))


def test_normalize_layout_fills_defaults_without_mutating():
    lay = layout()
    del lay["relations"][0]["cardinality"]
    before = copy.deepcopy(lay)
    out = normalize_layout(lay)
    assert lay == before
    rel = out["relations"][0]
    assert rel["join"] == "left" and rel["cardinality"] == "one"  # merge defaults to one
    assert rel["on_orphan_detail"] == "exception" and rel["on_missing_detail"] == "allow"
    assert rel["on_duplicate_master"] == "reject_all" and rel["min_match_rate"] == 0.0
    assert rel["normalize"] == ["trim"]
    rel["normalize"].append("upper")
    assert DEFAULT_READINESS["require"] == "all_required"
    assert normalize_layout(lay)["relations"][0]["normalize"] == ["trim"]


def test_name_pattern_must_compile_and_named_groups_required_for_pairing():
    lay = layout()
    lay["files"][1]["name_pattern"] = "fees_("
    assert any("regex" in e for e in validate_layout(lay, None))
    lay = layout()
    lay["files"][1]["name_pattern"] = r"fees_\d{8}\.csv"
    assert any("fees" in e and "group" in e for e in validate_layout(lay, {"pairing": "business_date"}))
    assert validate_layout(lay, {"pairing": "window_minutes", "window_minutes": 30}) == []


def test_malformed_shapes_return_errors_without_raising():
    lay = layout()
    lay["relations"][0]["normalize"] = None
    assert validate_layout(lay, None) == []  # null falls back to the default
    lay = layout()
    lay["relations"][0]["on"] = ["loan_id"]
    assert any("key part" in e for e in validate_layout(lay, None))
    lay = agg_layout("total")
    lay["relations"][0]["aggregate"]["columns"] = ["total"]
    assert any("object" in e for e in validate_layout(lay, None))
    assert validate_layout({"files": None, "relations": None}, None)
    assert validate_layout({"files": "x", "relations": 3}, None)
    assert validate_layout(None, None)
    assert any("object" in e for e in validate_layout({"files": [1], "relations": ["r"]}, None))
    assert validate_layout(layout(), ["bad"]) == []
    lay = layout()
    lay["files"][0]["key"] = "loan_id"
    assert any("master key" in e for e in validate_layout(lay, None))


def test_other_validation_branches():
    lay = layout()
    lay["relations"][0]["join"] = "outer"
    lay["relations"][0]["min_match_rate"] = 2
    errs = validate_layout(lay, None)
    assert any("join" in e for e in errs) and any("min_match_rate" in e for e in errs)
    lay = layout()
    lay["relations"].append(dict(lay["relations"][0]))
    assert any("more than one relation" in e for e in validate_layout(lay, None))
    assert any("window_minutes" in e for e in validate_layout(layout(), {"pairing": "window_minutes"}))


def test_aggregate_where_and_order_by_shape_validated():
    def errs_for(**col_extra):
        lay = agg_layout("total")
        lay["relations"][0]["aggregate"]["columns"][0].update(col_extra)
        return validate_layout(lay, None)

    assert errs_for(where={">": [{"var": "amt"}, 5]}, order_by=[{"col": "d", "desc": True, "type": "date"}]) == []
    assert any("where" in e for e in errs_for(where="amt > 5"))
    assert any("where" in e for e in errs_for(where={"nope": [1]}) + errs_for(where=[1]))
    assert any("order_by" in e for e in errs_for(order_by={"col": "d"}))
    assert any("order_by" in e for e in errs_for(order_by=["d"]))
    assert any("order_by" in e for e in errs_for(order_by=[{"desc": True}]))
    assert any("order_by" in e for e in errs_for(order_by=[{"col": "d", "type": "money"}]))
    assert any("order_by" in e for e in errs_for(order_by=[{"col": "d", "desc": "yes"}]))


def test_cardinality_default_depends_on_mode():
    lay = layout()
    del lay["relations"][0]["cardinality"]
    assert normalize_layout(lay)["relations"][0]["cardinality"] == "one"
    lay["relations"][0]["mode"] = "aggregate"
    assert normalize_layout(lay)["relations"][0]["cardinality"] == "many"
    lay["relations"][0]["cardinality"] = "one"
    assert normalize_layout(lay)["relations"][0]["cardinality"] == "one"
    lay["relations"][0]["mode"] = "merge"
    lay["relations"][0]["cardinality"] = "many"
    assert normalize_layout(lay)["relations"][0]["cardinality"] == "many"  # explicit never overridden
