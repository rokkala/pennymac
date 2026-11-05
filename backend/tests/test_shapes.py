"""Guided rule shapes: compile / summarize / autotest / decompile."""
from lbp.rules.default_rules import BASE_LOAN
from lbp.rules.jsonlogic import apply, validate
from lbp.rules.shapes import ShapeError, catalog, compile_tree, decompile, summarize, templates


def test_catalog_lists_expected_shapes():
    ids = {s["id"] for s in catalog()}
    assert {"required", "between", "compare_num", "one_of", "if_then", "date_order", "pattern", "in_codes", "blank_or", "days_between",
            "compare_scaled", "is_false", "pmt_within", "if_flag_then", "length_between", "not_in", "is_date"} <= ids


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


def test_pattern_loan_number_matches():
    tree = {"shape": "pattern", "field": "loan_number", "pattern": "[A-Z0-9-]{6,20}"}
    out = compile_tree(tree)
    assert out["expression"] == {"matches": [{"var": "loan_number"}, "[A-Z0-9-]{6,20}"]}
    assert apply(out["expression"], BASE_LOAN) is True
    assert apply(out["expression"], {**BASE_LOAN, "loan_number": "AB"}) is False
    assert apply(out["expression"], {**BASE_LOAN, "loan_number": "loan#bad!"}) is False
    back = decompile(out["expression"])
    assert back == tree or back.get("shape") == "pattern"
    assert "loan_number" in summarize(tree)


def test_pattern_rejects_bad_regex():
    try:
        compile_tree({"shape": "pattern", "field": "loan_number", "pattern": "[unterminated"})
        assert False, "expected ShapeError"
    except ShapeError as e:
        assert "regex" in str(e).lower() or "pattern" in str(e).lower()


def test_in_codes_and_blank_or_between():
    codes = compile_tree({"shape": "in_codes", "field": "property_state"})
    assert "in_codes" in str(codes["expression"])
    assert apply(codes["expression"], BASE_LOAN) is True
    assert apply(codes["expression"], {**BASE_LOAN, "property_state": "ZZ"}) is False

    opt = compile_tree({
        "shape": "blank_or",
        "inner": {"shape": "between", "field": "borrower_fico", "min": 300, "max": 850},
    })
    assert apply(opt["expression"], {**BASE_LOAN, "borrower_fico": None}) is True
    assert apply(opt["expression"], {**BASE_LOAN, "borrower_fico": 740}) is True
    assert apply(opt["expression"], {**BASE_LOAN, "borrower_fico": 100}) is False


def test_days_between_range():
    tree = {
        "shape": "days_between",
        "field_a": "note_date",
        "field_b": "first_payment_date",
        "min": 1,
        "max": 125,
    }
    out = compile_tree(tree)
    assert apply(out["expression"], BASE_LOAN) is True
    assert apply(out["expression"], {**BASE_LOAN, "note_date": "2024-01-01", "first_payment_date": "2024-01-01"}) is False


def test_flag_compare_scaled_pmt_and_length():
    assert apply(compile_tree({"shape": "is_false", "field": "fraud_alert_flag"})["expression"], BASE_LOAN) is True
    assert apply(compile_tree({"shape": "is_false", "field": "fraud_alert_flag"})["expression"], {**BASE_LOAN, "fraud_alert_flag": True}) is False

    scaled = compile_tree({
        "shape": "compare_scaled",
        "field": "current_principal_balance",
        "op": "<=",
        "other": "original_loan_amount",
        "factor": 1.05,
    })
    assert apply(scaled["expression"], BASE_LOAN) is True
    assert apply(scaled["expression"], {**BASE_LOAN, "current_principal_balance": 500000.0}) is False

    pmt = compile_tree({
        "shape": "pmt_within",
        "payment_field": "principal_interest_payment",
        "rate_field": "interest_rate",
        "term_field": "original_term_months",
        "amount_field": "original_loan_amount",
        "pct": 0.02,
        "skip_when": {"shape": "equals", "field": "amortization_type", "value": "ARM"},
    })
    assert apply(pmt["expression"], BASE_LOAN) is True
    assert apply(pmt["expression"], {**BASE_LOAN, "principal_interest_payment": 4000.0}) is False
    assert apply(pmt["expression"], {**BASE_LOAN, "amortization_type": "ARM", "principal_interest_payment": 4000.0}) is True

    flagged = compile_tree({
        "shape": "if_flag_then",
        "flag": "escrow_flag",
        "then": {"shape": "compare_num", "field": "escrow_balance", "op": ">=", "number": 0},
    })
    assert apply(flagged["expression"], BASE_LOAN) is True
    assert apply(flagged["expression"], {**BASE_LOAN, "escrow_balance": -10.0}) is False

    length = compile_tree({"shape": "length_between", "field": "loan_number", "min": 6, "max": 20})
    assert apply(length["expression"], BASE_LOAN) is True
    assert apply(length["expression"], {**BASE_LOAN, "loan_number": "AB"}) is False

    assert apply(compile_tree({"shape": "is_date", "field": "note_date"})["expression"], BASE_LOAN) is True
    assert apply(compile_tree({"shape": "not_in", "field": "loan_type", "values": ["XX", "YY"]})["expression"], BASE_LOAN) is True


def test_default_rules_mostly_decompile():
    from lbp.rules.default_rules import DEFAULT_RULES

    miss = []
    for r in DEFAULT_RULES:
        if decompile(r["expression"]) is None:
            miss.append(r["rule_id"])
    assert miss == [], f"still undecompilable: {miss}"
