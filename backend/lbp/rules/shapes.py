"""Typed rule shapes + condition trees for SME-guided authoring.

Leaves are catalog shapes; groups are and / or / xor. compile_tree() emits JSON Logic,
auto-tests, a primary field, and a plain-English summary. JSON Logic stays the Glue
runtime form; the tree is what the console edits.
"""
from __future__ import annotations

import re
from typing import Any

from ..schema.sse_target import ATTRIBUTES, BY_NAME
from .default_rules import BASE_LOAN
from .jsonlogic import apply, referenced_vars, validate

NUM_OPS = {"<": "less than", "<=": "at most", ">": "greater than", ">=": "at least"}
MAX_DEPTH = 3

# Common mortgage format presets shown in the console (SME picks; pattern is editable).
PATTERN_PRESETS: list[dict] = [
    {"id": "loan_number", "label": "Loan number (A–Z, 0–9, dash; 6–20)", "pattern": "[A-Z0-9-]{6,20}", "field": "loan_number", "ok": "LN-100001", "bad": "AB"},
    {"id": "ssn", "label": "SSN (9 digits, valid ranges)", "pattern": r"(?!000|666|9)\d{3}(?!00)\d{2}(?!0000)\d{4}", "field": "borrower_ssn", "ok": "123456789", "bad": "000121234"},
    {"id": "zip", "label": "ZIP (5 or 9 digits)", "pattern": r"\d{5}(\d{4})?", "field": "property_zip", "ok": "75024", "bad": "750"},
    {"id": "phone_10", "label": "10-digit phone", "pattern": r"\d{10}", "field": "borrower_home_phone", "ok": "2145550100", "bad": "555"},
    {"id": "email", "label": "Simple email", "pattern": r"[^@\s]+@[^@\s]+\.[^@\s]+", "field": "borrower_email", "ok": "a@b.co", "bad": "not-an-email"},
]

SHAPE_META: list[dict] = [
    {"id": "required", "label": "Must be filled", "dtypes": None, "params": ["field"]},
    {"id": "between", "label": "Between two numbers", "dtypes": ["decimal", "int"], "params": ["field", "min", "max"]},
    {"id": "compare_num", "label": "Compare to a number", "dtypes": ["decimal", "int"], "params": ["field", "op", "number"]},
    {"id": "compare_field", "label": "Compare to another field", "dtypes": ["decimal", "int", "date", "string"], "params": ["field", "op", "other"]},
    {"id": "compare_scaled", "label": "Compare to another field × factor", "dtypes": ["decimal", "int"], "params": ["field", "op", "other", "factor"]},
    {"id": "one_of", "label": "Must be one of", "dtypes": ["code", "string"], "params": ["field", "values"]},
    {"id": "not_in", "label": "Must not be one of", "dtypes": ["code", "string"], "params": ["field", "values"]},
    {"id": "equals", "label": "Equals a value", "dtypes": None, "params": ["field", "value"]},
    {"id": "not_equals", "label": "Does not equal a value", "dtypes": None, "params": ["field", "value"]},
    {"id": "digits", "label": "Exactly N digits", "dtypes": ["string", "int"], "params": ["field", "n"]},
    {"id": "length_between", "label": "Text length between", "dtypes": ["string", "code"], "params": ["field", "min", "max"]},
    {"id": "pattern", "label": "Matches a pattern (format)", "dtypes": ["string", "code"], "params": ["field", "pattern"]},
    {"id": "in_codes", "label": "Must be a valid code for the field", "dtypes": ["code"], "params": ["field"]},
    {"id": "is_date", "label": "Must be a valid date", "dtypes": ["date", "string"], "params": ["field"]},
    {"id": "is_true", "label": "Flag must be yes / true", "dtypes": ["bool"], "params": ["field"]},
    {"id": "is_false", "label": "Flag must be no / false", "dtypes": ["bool"], "params": ["field"]},
    {"id": "date_order", "label": "Date before / after another", "dtypes": ["date"], "params": ["field_a", "order", "field_b"]},
    {"id": "days_between", "label": "Days between two dates in a range", "dtypes": ["date"], "params": ["field_a", "field_b", "min", "max"]},
    {"id": "months_between", "label": "Months between two dates in a range", "dtypes": ["date"], "params": ["field_a", "field_b", "min", "max"]},
    {"id": "pmt_within", "label": "Payment within % of amortized P&I", "dtypes": ["decimal"], "params": ["payment_field", "rate_field", "term_field", "amount_field", "pct"]},
    {"id": "blank_or", "label": "Blank is OK, otherwise inner check", "dtypes": None, "params": ["inner"]},
    {"id": "if_flag_then", "label": "If flag is yes, then check", "dtypes": None, "params": ["flag", "then"]},
    {"id": "if_then", "label": "If … then …", "dtypes": None, "params": ["when", "then"]},
    {"id": "all_present", "label": "All fields filled", "dtypes": None, "params": ["fields"]},
]


class ShapeError(ValueError):
    pass


def catalog() -> list[dict]:
    return list(SHAPE_META)


def templates() -> list[dict]:
    return [
        {
            "id": "loan_number_format",
            "name": "Loan number format",
            "description": "Loan number matches A–Z / 0–9 / dash, length 6–20",
            "tree": {"shape": "pattern", "field": "loan_number", "pattern": "[A-Z0-9-]{6,20}", "ok_example": "LN-100001", "bad_example": "AB"},
        },
        {
            "id": "ssn_format",
            "name": "Borrower SSN format",
            "description": "SSN is 9 digits with valid area/group/serial ranges",
            "tree": {
                "shape": "pattern",
                "field": "borrower_ssn",
                "pattern": r"(?!000|666|9)\d{3}(?!00)\d{2}(?!0000)\d{4}",
                "ok_example": "123456789",
                "bad_example": "000121234",
            },
        },
        {
            "id": "zip_format",
            "name": "Property ZIP format",
            "description": "ZIP is 5 digits or ZIP+4",
            "tree": {"shape": "pattern", "field": "property_zip", "pattern": r"\d{5}(\d{4})?", "ok_example": "75024", "bad_example": "750"},
        },
        {
            "id": "state_codes",
            "name": "Property state code list",
            "description": "Property state must be a valid USPS code from the SSE list",
            "tree": {"shape": "in_codes", "field": "property_state"},
        },
        {
            "id": "rate_range",
            "name": "Interest rate range",
            "description": "Interest rate must be between 0.5% and 15%",
            "tree": {"shape": "between", "field": "interest_rate", "min": 0.5, "max": 15},
        },
        {
            "id": "fico_optional_range",
            "name": "FICO blank or 300–850",
            "description": "Blank FICO is OK; if present it must be between 300 and 850",
            "tree": {"shape": "blank_or", "inner": {"shape": "between", "field": "borrower_fico", "min": 300, "max": 850}},
        },
        {
            "id": "fico_floor",
            "name": "Credit score floor",
            "description": "Borrower FICO must be at least 580",
            "tree": {"shape": "compare_num", "field": "borrower_fico", "op": ">=", "number": 580},
        },
        {
            "id": "occupancy_codes",
            "name": "Occupancy codes",
            "description": "Occupancy must be P, S, or I",
            "tree": {"shape": "one_of", "field": "occupancy_type", "values": ["P", "S", "I"]},
        },
        {
            "id": "fha_gnma",
            "name": "FHA → GNMA investor",
            "description": "If loan type is FHA, investor category must be GNMA",
            "tree": {
                "shape": "if_then",
                "when": {"shape": "equals", "field": "loan_type", "value": "FHA"},
                "then": {"shape": "equals", "field": "investor_category", "value": "GNMA"},
            },
        },
        {
            "id": "maturity_after_note",
            "name": "Maturity after note date",
            "description": "Maturity date must be after note date",
            "tree": {"shape": "date_order", "field_a": "maturity_date", "order": "after", "field_b": "note_date"},
        },
        {
            "id": "first_payment_window",
            "name": "First payment 1–125 days after note",
            "description": "Days from note date to first payment must be between 1 and 125",
            "tree": {"shape": "days_between", "field_a": "note_date", "field_b": "first_payment_date", "min": 1, "max": 125},
        },
        {
            "id": "loan_number_required",
            "name": "Loan number required",
            "description": "Loan number must be filled",
            "tree": {"shape": "required", "field": "loan_number"},
        },
        {
            "id": "upb_vs_original",
            "name": "UPB ≤ original × 1.05",
            "description": "Current balance must not exceed original amount by more than 5%",
            "tree": {
                "shape": "compare_scaled",
                "field": "current_principal_balance",
                "op": "<=",
                "other": "original_loan_amount",
                "factor": 1.05,
            },
        },
        {
            "id": "no_fraud_alert",
            "name": "No fraud alert",
            "description": "Fraud alert flag must be false",
            "tree": {"shape": "is_false", "field": "fraud_alert_flag"},
        },
        {
            "id": "ofac_clear",
            "name": "OFAC clear",
            "description": "OFAC screening status must be C (clear)",
            "tree": {"shape": "equals", "field": "ofac_check_status", "value": "C"},
        },
        {
            "id": "escrow_nonneg",
            "name": "Escrow balance ≥ 0 when escrowed",
            "description": "If escrow flag is set, balance cannot be negative",
            "tree": {
                "shape": "if_flag_then",
                "flag": "escrow_flag",
                "then": {"shape": "compare_num", "field": "escrow_balance", "op": ">=", "number": 0},
            },
        },
        {
            "id": "pi_vs_amortization",
            "name": "P&I within 2% of amortized payment",
            "description": "For fixed-rate loans, P&I must be within 2% of the amortized payment",
            "tree": {
                "shape": "pmt_within",
                "payment_field": "principal_interest_payment",
                "rate_field": "interest_rate",
                "term_field": "original_term_months",
                "amount_field": "original_loan_amount",
                "pct": 0.02,
                "skip_when": {"shape": "equals", "field": "amortization_type", "value": "ARM"},
            },
        },
        {
            "id": "ltv_range",
            "name": "LTV 1–125",
            "description": "LTV must be between 1 and 125",
            "tree": {"shape": "between", "field": "ltv_ratio", "min": 1, "max": 125},
        },
        {
            "id": "dti_optional_cap",
            "name": "DTI blank or ≤ 50",
            "description": "Blank DTI is OK; if present it must be at most 50",
            "tree": {"shape": "blank_or", "inner": {"shape": "compare_num", "field": "dti_ratio", "op": "<=", "number": 50}},
        },
        {
            "id": "term_months",
            "name": "Original term 60–480 months",
            "description": "Original term must be between 60 and 480 months",
            "tree": {"shape": "between", "field": "original_term_months", "min": 60, "max": 480},
        },
        {
            "id": "servicing_fee",
            "name": "Servicing fee 0–1%",
            "description": "Servicing fee rate must be between 0 and 1",
            "tree": {"shape": "between", "field": "servicing_fee_rate", "min": 0, "max": 1},
        },
        {
            "id": "gov_loan_gnma",
            "name": "FHA/VA/USDA → GNMA",
            "description": "If loan type is FHA, VA, or USDA, investor must be GNMA",
            "tree": {
                "shape": "if_then",
                "when": {"shape": "one_of", "field": "loan_type", "values": ["FHA", "VA", "USDA"]},
                "then": {"shape": "equals", "field": "investor_category", "value": "GNMA"},
            },
        },
        {
            "id": "mers_min_length",
            "name": "MERS MIN length 18",
            "description": "When present, MERS MIN should be 18 characters (use with blank_or if optional)",
            "tree": {"shape": "blank_or", "inner": {"shape": "length_between", "field": "mers_min", "min": 18, "max": 18}},
        },
    ]


def pattern_presets() -> list[dict]:
    return list(PATTERN_PRESETS)


def _field(name: str, dtypes: list[str] | None = None) -> str:
    if not name or name not in BY_NAME:
        raise ShapeError(f"unknown field: {name}")
    attr = BY_NAME[name]
    if dtypes and attr.dtype not in dtypes:
        raise ShapeError(f"field {name} has type {attr.dtype}; expected one of {dtypes}")
    return name


def _sample(field: str):
    if field in BASE_LOAN:
        return BASE_LOAN[field]
    attr = BY_NAME[field]
    return {"decimal": 100.0, "int": 10, "date": "2025-01-01", "bool": True, "code": (attr.codes or ("X",))[0]}.get(attr.dtype, "ABC")


def _base_with(**kw) -> dict:
    return {**BASE_LOAN, **kw}


def _leaf_expr(node: dict) -> tuple[Any, str, list[dict], str]:
    """Returns expression, primary field, tests [{record, expect}], category."""
    shape = node.get("shape")
    if shape == "required":
        f = _field(node.get("field"))
        expr = {"!": {"is_blank": {"var": f}}}
        tests = [(_base_with(**{f: _sample(f)}), True), (_base_with(**{f: ""}), False), (_base_with(**{f: None}), False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "completeness"

    if shape == "between":
        f = _field(node.get("field"), ["decimal", "int"])
        a, b = float(node["min"]), float(node["max"])
        if a > b:
            a, b = b, a
        expr = {"<=": [a, {"var": f}, b]}
        mid = (a + b) / 2
        tests = [(_base_with(**{f: mid}), True), (_base_with(**{f: b * 10 + 1}), False), (_base_with(**{f: None}), False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "range"

    if shape == "compare_num":
        f = _field(node.get("field"), ["decimal", "int"])
        op = node.get("op")
        if op not in NUM_OPS:
            raise ShapeError(f"unsupported compare op: {op}")
        x = float(node["number"])
        expr = {op: [{"var": f}, x]}
        good = x if op in ("<=", ">=") else (x - 1 if op == "<" else x + 1)
        bad = x + abs(x) + 1 if op in ("<=", "<") else x - abs(x) - 1
        tests = [(_base_with(**{f: good}), True), (_base_with(**{f: bad}), False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "range"

    if shape == "compare_field":
        f = _field(node.get("field"))
        g = _field(node.get("other"))
        op = node.get("op")
        if op not in NUM_OPS and op not in ("==", "!="):
            raise ShapeError(f"unsupported compare op: {op}")
        expr = {op: [{"var": f}, {"var": g}]}
        tests = [
            ({**BASE_LOAN, f: 100, g: 200} if op in ("<", "<=") else {**BASE_LOAN, f: 200, g: 100}, True),
            ({**BASE_LOAN, f: 300, g: 200} if op in ("<", "<=") else {**BASE_LOAN, f: 100, g: 200}, False),
        ]
        if op in ("==", "!="):
            tests = [({**BASE_LOAN, f: 100, g: 100}, op == "=="), ({**BASE_LOAN, f: 100, g: 200}, op == "!=")]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "consistency"

    if shape == "compare_scaled":
        f = _field(node.get("field"), ["decimal", "int"])
        g = _field(node.get("other"), ["decimal", "int"])
        op = node.get("op")
        if op not in NUM_OPS:
            raise ShapeError(f"unsupported compare op: {op}")
        factor = float(node.get("factor", 1))
        expr = {op: [{"var": f}, {"*": [{"var": g}, factor]}]}
        base_g = float(_sample(g) or 100)
        good_f = base_g * factor * (0.9 if op in ("<=", "<") else 1.1)
        bad_f = base_g * factor * (1.2 if op in ("<=", "<") else 0.5)
        tests = [({**BASE_LOAN, f: good_f, g: base_g}, True), ({**BASE_LOAN, f: bad_f, g: base_g}, False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "consistency"

    if shape == "one_of":
        f = _field(node.get("field"))
        vals = [str(v).strip().upper() if BY_NAME[f].dtype == "code" else v for v in (node.get("values") or [])]
        if not vals:
            raise ShapeError("one_of requires at least one value")
        expr = {"in": [{"var": f}, vals]}
        tests = [(_base_with(**{f: vals[0]}), True), (_base_with(**{f: "ZZZ"}), False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "format"

    if shape == "equals":
        f = _field(node.get("field"))
        val = node.get("value")
        if BY_NAME[f].dtype == "code" and isinstance(val, str):
            val = val.upper()
        expr = {"==": [{"var": f}, val]}
        other = (BY_NAME[f].codes or ("__other__",))[0]
        if other == val and len(BY_NAME[f].codes or ()) > 1:
            other = BY_NAME[f].codes[1]
        elif other == val:
            other = "__other__"
        tests = [(_base_with(**{f: val}), True), (_base_with(**{f: other}), False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "format"

    if shape == "not_equals":
        f = _field(node.get("field"))
        val = node.get("value")
        if BY_NAME[f].dtype == "code" and isinstance(val, str):
            val = val.upper()
        expr = {"!=": [{"var": f}, val]}
        other = _sample(f)
        if other == val:
            other = "__other__"
        tests = [(_base_with(**{f: other}), True), (_base_with(**{f: val}), False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "format"

    if shape == "not_in":
        f = _field(node.get("field"))
        vals = [str(v).strip().upper() if BY_NAME[f].dtype == "code" else v for v in (node.get("values") or [])]
        if not vals:
            raise ShapeError("not_in requires at least one value")
        expr = {"!": {"in": [{"var": f}, vals]}}
        ok = _sample(f)
        if ok in vals:
            ok = "__ok__"
        tests = [(_base_with(**{f: ok}), True), (_base_with(**{f: vals[0]}), False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "format"

    if shape == "digits":
        f = _field(node.get("field"), ["string", "int"])
        n = int(node["n"])
        expr = {"matches": [{"var": f}, rf"\d{{{n}}}"]}
        tests = [(_base_with(**{f: "1" * n}), True), (_base_with(**{f: "1" * max(n - 1, 0) or "x"}), False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "format"

    if shape == "pattern":
        f = _field(node.get("field"))
        pat = node.get("pattern") or node.get("regex")
        if not pat or not isinstance(pat, str):
            raise ShapeError("pattern requires a regex string")
        try:
            rx = re.compile(pat)
        except re.error as e:
            raise ShapeError(f"invalid regex pattern: {e}") from e
        expr = {"matches": [{"var": f}, pat]}
        ok = node.get("ok_example")
        bad = node.get("bad_example")
        if ok is None:
            # Prefer BASE_LOAN value when it already matches; else a short alphanumeric guess.
            sample = _sample(f)
            ok = sample if isinstance(sample, str) and rx.fullmatch(str(sample)) else "ABC123"
            if not rx.fullmatch(str(ok)):
                ok = "A" * 8 if rx.fullmatch("A" * 8) else "123456"
                if not rx.fullmatch(str(ok)):
                    raise ShapeError("pattern needs ok_example — could not invent a passing sample")
        if bad is None:
            bad = "!"
            if rx.fullmatch(str(bad)):
                bad = ""
        if not rx.fullmatch(str(ok)):
            raise ShapeError("ok_example does not match the pattern")
        if rx.fullmatch(str(bad)):
            raise ShapeError("bad_example unexpectedly matches the pattern")
        tests = [(_base_with(**{f: ok}), True), (_base_with(**{f: bad}), False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "format"

    if shape == "in_codes":
        f = _field(node.get("field"), ["code"])
        if not BY_NAME[f].codes:
            raise ShapeError(f"field {f} has no SSE code list")
        expr = {"in_codes": [{"var": f}, f]}
        ok = BY_NAME[f].codes[0]
        tests = [(_base_with(**{f: ok}), True), (_base_with(**{f: "ZZ"}), False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "format"

    if shape == "length_between":
        f = _field(node.get("field"), ["string", "code"])
        lo, hi = int(node["min"]), int(node["max"])
        if lo > hi:
            lo, hi = hi, lo
        expr = {"<=": [lo, {"len": {"var": f}}, hi]}
        mid = "A" * max((lo + hi) // 2, 1)
        bad = "A" * (hi + 3)
        tests = [(_base_with(**{f: mid}), True), (_base_with(**{f: bad}), False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "format"

    if shape == "is_date":
        f = _field(node.get("field"))
        expr = {"is_date": {"var": f}}
        tests = [(_base_with(**{f: "2024-01-15"}), True), (_base_with(**{f: "not-a-date"}), False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "format"

    if shape == "is_true":
        f = _field(node.get("field"), ["bool"])
        expr = {"!!": {"var": f}}
        tests = [(_base_with(**{f: True}), True), (_base_with(**{f: False}), False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "format"

    if shape == "is_false":
        f = _field(node.get("field"), ["bool"])
        expr = {"!": {"var": f}}
        tests = [(_base_with(**{f: False}), True), (_base_with(**{f: True}), False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "fraud"

    if shape == "if_flag_then":
        flag = _field(node.get("flag"), ["bool"])
        then = node.get("then")
        if not then:
            raise ShapeError("if_flag_then requires then")
        t_expr, t_f, t_tests, cat = _compile_node(then, 0)
        expr = {"if": [{"var": flag}, t_expr, True]}
        tests = [{"record": _base_with(**{flag: False}), "expect": True}]
        for t in t_tests:
            tests.append({"record": {**t["record"], flag: True}, "expect": t["expect"]})
        return expr, t_f or flag, tests, cat

    if shape == "pmt_within":
        pay = _field(node.get("payment_field"), ["decimal", "int"])
        rate = _field(node.get("rate_field"), ["decimal", "int"])
        term = _field(node.get("term_field"), ["decimal", "int"])
        amt = _field(node.get("amount_field"), ["decimal", "int"])
        pct = float(node.get("pct", 0.02))
        pmt_expr = {"pmt": [{"var": rate}, {"var": term}, {"var": amt}]}
        inner = {"<=": [{"abs": {"-": [{"var": pay}, pmt_expr]}}, {"*": [pmt_expr, pct]}]}
        skip = node.get("skip_when")
        if skip:
            s_expr, _, _, _ = _compile_node(skip, 0)
            expr = {"if": [s_expr, True, inner]}
        else:
            expr = inner
        # Use BASE_LOAN as passing; inflate payment as failing
        tests = [
            ({**BASE_LOAN}, True),
            ({**BASE_LOAN, pay: float(BASE_LOAN.get(pay) or 0) * 3 or 99999}, False),
        ]
        return expr, pay, [{"record": r, "expect": e} for r, e in tests], "consistency"

    if shape == "months_between":
        a = _field(node.get("field_a"), ["date"])
        b = _field(node.get("field_b"), ["date"])
        lo, hi = node.get("min"), node.get("max")
        gap = {"months_between": [{"var": a}, {"var": b}]}
        if lo is not None and hi is not None:
            expr = {"<=": [float(lo), gap, float(hi)]}
        elif lo is not None:
            expr = {">=": [gap, float(lo)]}
        elif hi is not None:
            expr = {"<=": [gap, float(hi)]}
        else:
            raise ShapeError("months_between requires min and/or max")
        from datetime import date

        start = date(2020, 1, 1)
        good = date(2022, 1, 1).isoformat()  # 24 months
        bad = date(2030, 1, 1).isoformat()
        tests = [({**BASE_LOAN, a: start.isoformat(), b: good}, True), ({**BASE_LOAN, a: start.isoformat(), b: bad}, False)]
        # If the configured window wouldn't accept 24 months, still return expression; filter later
        return expr, a, [{"record": r, "expect": e} for r, e in tests], "consistency"

    if shape == "blank_or":
        inner = node.get("inner")
        if not inner:
            raise ShapeError("blank_or requires an inner check")
        inner_expr, field, inner_tests, cat = _compile_node(inner, 0)
        expr = {"or": [{"is_blank": {"var": field}}, inner_expr]}
        tests = [{"record": _base_with(**{field: None}), "expect": True}]
        for t in inner_tests:
            tests.append(t)
        return expr, field, tests, cat

    if shape == "days_between":
        a = _field(node.get("field_a"), ["date"])
        b = _field(node.get("field_b"), ["date"])
        lo = node.get("min")
        hi = node.get("max")
        gap = {"days_between": [{"var": a}, {"var": b}]}
        if lo is not None and hi is not None:
            expr = {"<=": [float(lo), gap, float(hi)]}
        elif lo is not None:
            expr = {">=": [gap, float(lo)]}
        elif hi is not None:
            expr = {"<=": [gap, float(hi)]}
        else:
            raise ShapeError("days_between requires min and/or max")
        # Build calendar samples: a=2024-01-01, b = a + mid days
        from datetime import date, timedelta

        start = date(2024, 1, 1)
        if lo is not None and hi is not None:
            mid = int((float(lo) + float(hi)) / 2)
            good_b = (start + timedelta(days=mid)).isoformat()
            bad_b = (start + timedelta(days=int(float(hi)) + 30)).isoformat()
        elif lo is not None:
            good_b = (start + timedelta(days=int(float(lo)) + 1)).isoformat()
            bad_b = start.isoformat()
        else:
            good_b = (start + timedelta(days=max(int(float(hi)) - 1, 0))).isoformat()
            bad_b = (start + timedelta(days=int(float(hi)) + 10)).isoformat()
        tests = [
            ({**BASE_LOAN, a: start.isoformat(), b: good_b}, True),
            ({**BASE_LOAN, a: start.isoformat(), b: bad_b}, False),
        ]
        return expr, a, [{"record": r, "expect": e} for r, e in tests], "consistency"

    if shape == "date_order":
        a = _field(node.get("field_a"), ["date"])
        b = _field(node.get("field_b"), ["date"])
        order = node.get("order")
        if order not in ("before", "after"):
            raise ShapeError("order must be before or after")
        op = "date_before" if order == "before" else "date_after"
        expr = {op: [{"var": a}, {"var": b}]}
        early, late = "2024-01-01", "2024-06-01"
        if order == "before":
            tests = [({**BASE_LOAN, a: early, b: late}, True), ({**BASE_LOAN, a: late, b: early}, False)]
        else:
            tests = [({**BASE_LOAN, a: late, b: early}, True), ({**BASE_LOAN, a: early, b: late}, False)]
        return expr, a, [{"record": r, "expect": e} for r, e in tests], "consistency"

    if shape == "all_present":
        fields = [_field(f) for f in (node.get("fields") or [])]
        if not fields:
            raise ShapeError("all_present requires fields")
        expr = {"all_present": [{"var": f} for f in fields]}
        ok = _base_with(**{f: _sample(f) for f in fields})
        bad = _base_with(**{f: "" for f in fields})
        tests = [(ok, True), (bad, False)]
        return expr, fields[0], [{"record": r, "expect": e} for r, e in tests], "completeness"

    if shape == "if_then":
        when, then = node.get("when"), node.get("then")
        if not when or not then:
            raise ShapeError("if_then requires when and then")
        w_expr, w_f, w_tests, _ = _compile_node(when, 0)
        t_expr, t_f, t_tests, cat = _compile_node(then, 0)
        expr = {"if": [w_expr, t_expr, True]}
        tests = []
        for t in t_tests:
            # when true: then outcome applies — merge a passing when-record
            when_pass = next((x["record"] for x in w_tests if x["expect"]), w_tests[0]["record"] if w_tests else BASE_LOAN)
            tests.append({"record": {**when_pass, **t["record"]}, "expect": t["expect"]})
        when_fail = next((x["record"] for x in w_tests if not x["expect"]), None)
        if when_fail is not None:
            tests.append({"record": when_fail, "expect": True})
        return expr, t_f or w_f, tests, cat

    raise ShapeError(f"unknown shape: {shape}")


def _compile_node(node: dict, depth: int) -> tuple[Any, str, list[dict], str]:
    if depth > MAX_DEPTH:
        raise ShapeError(f"condition tree deeper than {MAX_DEPTH} levels")
    if not isinstance(node, dict):
        raise ShapeError("invalid tree node")
    if "op" in node and node["op"] in ("and", "or", "xor"):
        kids = node.get("children") or []
        if not kids:
            raise ShapeError("group must have at least one condition")
        parts = [_compile_node(c, depth + 1) for c in kids]
        expr = {node["op"]: [p[0] for p in parts]}
        field = parts[0][1]
        # combine tests: for and, all must pass on BASE; for failures, each child's fail case
        tests: list[dict] = [{"record": dict(BASE_LOAN), "expect": True}]
        for _expr, _f, child_tests, _cat in parts:
            for t in child_tests:
                if not t["expect"]:
                    tests.append(t)
                    break
        cat = parts[0][3]
        return expr, field, tests, cat
    if node.get("shape"):
        return _leaf_expr(node)
    raise ShapeError("node must be a shape or an and/or/xor group")


def summarize(node: dict) -> str:
    if not isinstance(node, dict):
        return ""
    if "op" in node and node["op"] in ("and", "or", "xor"):
        join = {"and": "All of", "or": "Any of", "xor": "Exactly one of"}[node["op"]]
        parts = [summarize(c) for c in (node.get("children") or [])]
        return f"{join}: {'; '.join(p for p in parts if p)}"
    shape = node.get("shape")
    if shape == "required":
        return f"{node.get('field')} must be filled"
    if shape == "between":
        return f"{node.get('field')} between {node.get('min')} and {node.get('max')}"
    if shape == "compare_num":
        return f"{node.get('field')} {NUM_OPS.get(node.get('op'), node.get('op'))} {node.get('number')}"
    if shape == "compare_field":
        return f"{node.get('field')} {node.get('op')} {node.get('other')}"
    if shape == "compare_scaled":
        return f"{node.get('field')} {node.get('op')} {node.get('other')} × {node.get('factor')}"
    if shape == "one_of":
        return f"{node.get('field')} is one of {', '.join(map(str, node.get('values') or []))}"
    if shape == "not_in":
        return f"{node.get('field')} is not one of {', '.join(map(str, node.get('values') or []))}"
    if shape == "equals":
        return f"{node.get('field')} equals {node.get('value')}"
    if shape == "not_equals":
        return f"{node.get('field')} does not equal {node.get('value')}"
    if shape == "digits":
        return f"{node.get('field')} is {node.get('n')} digits"
    if shape == "length_between":
        return f"{node.get('field')} length between {node.get('min')} and {node.get('max')}"
    if shape == "pattern":
        return f"{node.get('field')} matches /{node.get('pattern')}/"
    if shape == "in_codes":
        return f"{node.get('field')} is a valid code for that field"
    if shape == "is_date":
        return f"{node.get('field')} is a valid date"
    if shape == "is_true":
        return f"{node.get('field')} is true"
    if shape == "is_false":
        return f"{node.get('field')} is false"
    if shape == "blank_or":
        return f"may be blank, else {summarize(node.get('inner') or {})}"
    if shape == "days_between":
        return f"days from {node.get('field_a')} to {node.get('field_b')} between {node.get('min')} and {node.get('max')}"
    if shape == "months_between":
        return f"months from {node.get('field_a')} to {node.get('field_b')} between {node.get('min')} and {node.get('max')}"
    if shape == "date_order":
        return f"{node.get('field_a')} {node.get('order')} {node.get('field_b')}"
    if shape == "pmt_within":
        return f"{node.get('payment_field')} within {float(node.get('pct', 0) * 100):.0f}% of amortized P&I"
    if shape == "if_flag_then":
        return f"if {node.get('flag')}, then {summarize(node.get('then') or {})}"
    if shape == "all_present":
        return f"all of {', '.join(node.get('fields') or [])} filled"
    if shape == "if_then":
        return f"if {summarize(node.get('when') or {})}, then {summarize(node.get('then') or {})}"
    return ""


def compile_tree(tree: dict) -> dict:
    """Compile AST → draft body fields (expression, field, fields, tests, summary, category)."""
    expr, field, tests, category = _compile_node(tree, 0)
    problems = validate(expr)
    if problems:
        raise ShapeError("; ".join(problems))
    body = {
        "expression": expr,
        "field": field,
        "fields": sorted(referenced_vars(expr)),
        "tests": [t for t in tests if bool(apply(expr, t["record"])) == bool(t["expect"])] or tests,
        "summary": summarize(tree),
        "category": category,
        "tree": tree,
    }
    return body


def decompile(expression: Any) -> dict | None:
    """Best-effort expression → tree. Returns None when unrecognized."""
    if not isinstance(expression, dict) or len(expression) != 1:
        return None
    op, args = next(iter(expression.items()))
    if not isinstance(args, list):
        args = [args]

    if op == "or" and len(args) == 2 and isinstance(args[0], dict) and "is_blank" in args[0]:
        blank = args[0]["is_blank"]
        var = blank.get("var") if isinstance(blank, dict) else None
        if isinstance(var, list):
            var = var[0]
        inner = decompile(args[1])
        if inner:
            return {"shape": "blank_or", "inner": inner}

    if op in ("and", "or", "xor"):
        kids = [decompile(a) for a in args]
        if any(k is None for k in kids):
            return None
        return {"op": op, "children": kids}

    if op == "!" and isinstance(args[0], dict) and "is_blank" in args[0]:
        inner = args[0]["is_blank"]
        var = inner["var"] if isinstance(inner, dict) else None
        if isinstance(var, list):
            var = var[0]
        if isinstance(var, str):
            return {"shape": "required", "field": var}

    if op == "<=" and len(args) == 3 and isinstance(args[1], dict) and "days_between" in args[1]:
        db = args[1]["days_between"]
        if isinstance(db, list) and len(db) == 2:
            def _v(x):
                if isinstance(x, dict) and "var" in x:
                    v = x["var"]
                    return v[0] if isinstance(v, list) else v
                return None

            fa, fb = _v(db[0]), _v(db[1])
            if fa and fb:
                return {"shape": "days_between", "field_a": fa, "field_b": fb, "min": args[0], "max": args[2]}

    if op == "<=" and len(args) == 3 and isinstance(args[1], dict) and "var" in args[1]:
        var = args[1]["var"]
        if isinstance(var, list):
            var = var[0]
        return {"shape": "between", "field": var, "min": args[0], "max": args[2]}

    if op in NUM_OPS and len(args) == 2 and isinstance(args[0], dict) and "days_between" in args[0] and args[1] == 0:
        db = args[0]["days_between"]
        if isinstance(db, list) and len(db) == 2:
            def _v(x):
                if isinstance(x, dict) and "var" in x:
                    v = x["var"]
                    return v[0] if isinstance(v, list) else v
                return None

            fa, fb = _v(db[0]), _v(db[1])
            if fa and fb and op == ">":
                return {"shape": "date_order", "field_a": fb, "order": "after", "field_b": fa}

    if op in NUM_OPS and len(args) == 2 and isinstance(args[0], dict) and "var" in args[0]:
        var = args[0]["var"]
        if isinstance(var, list):
            var = var[0] if not isinstance(var[0], (int, float)) else var  # rare default form
        if isinstance(var, list):
            # JSON Logic var with default: ["field", default]
            var = var[0]
        if isinstance(args[1], dict) and "var" in args[1]:
            other = args[1]["var"]
            if isinstance(other, list):
                other = other[0]
            return {"shape": "compare_field", "field": var, "op": op, "other": other}
        if isinstance(args[1], dict) and "*" in args[1]:
            mult = args[1]["*"]
            if isinstance(mult, list) and len(mult) == 2 and isinstance(mult[0], dict) and "var" in mult[0]:
                other = mult[0]["var"]
                if isinstance(other, list):
                    other = other[0]
                return {"shape": "compare_scaled", "field": var, "op": op, "other": other, "factor": mult[1]}
        if isinstance(args[1], (int, float)):
            return {"shape": "compare_num", "field": var, "op": op, "number": args[1]}
        return None

    if op == "!" and isinstance(args[0], dict) and "var" in args[0] and "is_blank" not in args[0]:
        var = args[0]["var"]
        if isinstance(var, list):
            var = var[0]
        if isinstance(var, str):
            return {"shape": "is_false", "field": var}

    if op == "!" and isinstance(args[0], dict) and "in" in args[0]:
        inner = decompile({"in": args[0]["in"]})
        if inner and inner.get("shape") == "one_of":
            return {"shape": "not_in", "field": inner["field"], "values": inner["values"]}

    if op == "!!" and isinstance(args[0], dict) and "var" in args[0]:
        var = args[0]["var"]
        if isinstance(var, list):
            var = var[0]
        return {"shape": "is_true", "field": var}

    if op == "in" and isinstance(args[0], dict) and "var" in args[0]:
        var = args[0]["var"]
        if isinstance(var, list):
            var = var[0]
        return {"shape": "one_of", "field": var, "values": list(args[1]) if isinstance(args[1], list) else [args[1]]}

    if op == "==" and isinstance(args[0], dict) and "var" in args[0]:
        var = args[0]["var"]
        if isinstance(var, list):
            var = var[0]
        return {"shape": "equals", "field": var, "value": args[1]}

    if op == "!=" and isinstance(args[0], dict) and "var" in args[0]:
        var = args[0]["var"]
        if isinstance(var, list):
            var = var[0]
        return {"shape": "not_equals", "field": var, "value": args[1]}

    if op == "is_date":
        inner = args[0] if args else None
        if isinstance(inner, dict) and "var" in inner:
            var = inner["var"]
            if isinstance(var, list):
                var = var[0]
            return {"shape": "is_date", "field": var}

    if op == "<=" and len(args) == 3 and isinstance(args[1], dict) and "len" in args[1]:
        ln = args[1]["len"]
        var = ln["var"] if isinstance(ln, dict) and "var" in ln else None
        if isinstance(var, list):
            var = var[0]
        if isinstance(var, str):
            return {"shape": "length_between", "field": var, "min": args[0], "max": args[2]}

    if op == "matches" and isinstance(args[0], dict) and "var" in args[0]:
        var = args[0]["var"]
        if isinstance(var, list):
            var = var[0]
        m = re.fullmatch(r"\\d\{(\d+)\}", str(args[1]))
        if m:
            return {"shape": "digits", "field": var, "n": int(m.group(1))}
        return {"shape": "pattern", "field": var, "pattern": args[1]}

    if op == "in_codes" and isinstance(args[0], dict) and "var" in args[0]:
        var = args[0]["var"]
        if isinstance(var, list):
            var = var[0]
        return {"shape": "in_codes", "field": var}

    if op in ("date_before", "date_after") and len(args) == 2:
        def _v(x):
            if isinstance(x, dict) and "var" in x:
                v = x["var"]
                return v[0] if isinstance(v, list) else v
            return None

        a, b = _v(args[0]), _v(args[1])
        if a and b:
            return {"shape": "date_order", "field_a": a, "order": "before" if op == "date_before" else "after", "field_b": b}

    if op == "all_present":
        fields = []
        for a in args:
            if isinstance(a, dict) and "var" in a:
                v = a["var"]
                fields.append(v[0] if isinstance(v, list) else v)
        if fields:
            return {"shape": "all_present", "fields": fields}

    if op == "if" and len(args) >= 2:
        # if flag then check: first arg is bare var
        if isinstance(args[0], dict) and "var" in args[0] and len(args[0]) == 1:
            var = args[0]["var"]
            if isinstance(var, list):
                var = var[0]
            then = decompile(args[1])
            if isinstance(var, str) and then:
                return {"shape": "if_flag_then", "flag": var, "then": then}
        # pmt_within: if skip then True else abs(pay-pmt)<=pmt*pct
        if len(args) >= 3 and args[1] is True and isinstance(args[2], dict) and "<=" in args[2]:
            skip = decompile(args[0])
            inner = args[2]["<="]
            if (
                isinstance(inner, list)
                and len(inner) == 2
                and isinstance(inner[0], dict)
                and "abs" in inner[0]
                and isinstance(inner[1], dict)
                and "*" in inner[1]
            ):
                diff = inner[0]["abs"]
                if isinstance(diff, dict) and "-" in diff:
                    parts = diff["-"]
                    if isinstance(parts, list) and len(parts) == 2 and isinstance(parts[0], dict) and "var" in parts[0]:
                        pay = parts[0]["var"]
                        if isinstance(pay, list):
                            pay = pay[0]
                        pmt = parts[1].get("pmt") if isinstance(parts[1], dict) else None
                        mult = inner[1]["*"]
                        pct = mult[1] if isinstance(mult, list) and len(mult) == 2 else 0.02
                        if isinstance(pmt, list) and len(pmt) == 3:
                            def _vf(x):
                                if isinstance(x, dict) and "var" in x:
                                    v = x["var"]
                                    return v[0] if isinstance(v, list) else v
                                return None

                            node = {
                                "shape": "pmt_within",
                                "payment_field": pay,
                                "rate_field": _vf(pmt[0]),
                                "term_field": _vf(pmt[1]),
                                "amount_field": _vf(pmt[2]),
                                "pct": pct,
                            }
                            if skip:
                                node["skip_when"] = skip
                            return node
        when, then = decompile(args[0]), decompile(args[1])
        if when and then:
            return {"shape": "if_then", "when": when, "then": then}

    return None


def fields_payload() -> list[dict]:
    return [
        {
            "name": a.name,
            "module": a.module,
            "dtype": a.dtype,
            "codes": list(a.codes),
            "risk": a.risk,
            "required": a.required,
            "description": a.description,
        }
        for a in ATTRIBUTES
    ]
