"""Guided rule shapes: compile / summarize / autotest / decompile."""
from lbp.rules.default_rules import BASE_LOAN
from lbp.rules.jsonlogic import apply, validate
from lbp.rules.shapes import ShapeError, catalog, compile_tree, decompile, summarize, templates


def test_catalog_lists_expected_shapes():
    ids = {s["id"] for s in catalog()}
    assert {"required", "between", "compare_num", "one_of", "if_then", "date_order"} <= ids


def test_templates_nonempty():
    t = templates()
    assert t and t[0]["tree"] and t[0]["name"]


def test_compile_required_and_between():
    tree = {
        "op": "and",
        "children": [
            {"shape": "required", "field": "loan_number"},
            {"shape": "between", "field": "interest_rate", "min": 0.5, "max": 15},
        ],
    }
    out = compile_tree(tree)
    assert not validate(out["expression"])
    assert apply(out["expression"], BASE_LOAN) is True
    assert apply(out["expression"], {**BASE_LOAN, "interest_rate": 20}) is False
    assert apply(out["expression"], {**BASE_LOAN, "loan_number": ""}) is False
    assert out["tests"] and all("record" in t and "expect" in t for t in out["tests"])
    assert "interest_rate" in summarize(tree)


def test_compile_if_then_and_one_of():
    tree = {
        "shape": "if_then",
        "when": {"shape": "equals", "field": "loan_type", "value": "FHA"},
        "then": {"shape": "equals", "field": "investor_category", "value": "GNMA"},
    }
    out = compile_tree(tree)
    assert apply(out["expression"], {**BASE_LOAN, "loan_type": "FHA", "investor_category": "GNMA"})
    assert not apply(out["expression"], {**BASE_LOAN, "loan_type": "FHA", "investor_category": "FNMA"})
    assert apply(out["expression"], {**BASE_LOAN, "loan_type": "CNV", "investor_category": "FNMA"})


def test_compile_date_order_uses_date_ops():
    tree = {"shape": "date_order", "field_a": "note_date", "order": "before", "field_b": "maturity_date"}
    out = compile_tree(tree)
    assert "date_before" in str(out["expression"]) or "days_between" in str(out["expression"])
    assert apply(out["expression"], BASE_LOAN)


def test_rejects_unknown_field_and_empty_group():
    try:
        compile_tree({"shape": "required", "field": "not_a_real_field"})
        assert False, "expected ShapeError"
    except ShapeError as e:
        assert "field" in str(e).lower() or "unknown" in str(e).lower()
    try:
        compile_tree({"op": "and", "children": []})
        assert False, "expected ShapeError"
    except ShapeError:
        pass


def test_decompile_roundtrip_simple():
    tree = {"shape": "between", "field": "interest_rate", "min": 0.5, "max": 15}
    out = compile_tree(tree)
    back = decompile(out["expression"])
    assert back is not None
    assert back.get("shape") == "between" or (back.get("op") == "and" and any(c.get("shape") == "between" for c in back.get("children", [])))
    # recompile decompiled tree still works
    again = compile_tree(back if back.get("shape") or back.get("op") else tree)
    assert apply(again["expression"], BASE_LOAN)
