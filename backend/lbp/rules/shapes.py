"""Typed rule shapes + condition trees for SME-guided authoring.

Leaves are catalog shapes; groups are and / or / xor. compile_tree() emits JSON Logic,
auto-tests, a primary field, and a plain-English summary. JSON Logic stays the Glue
runtime form; the tree is what the console edits.
"""
from __future__ import annotations

from typing import Any

from ..schema.sse_target import ATTRIBUTES, BY_NAME
from .default_rules import BASE_LOAN
from .jsonlogic import apply, referenced_vars, validate

NUM_OPS = {"<": "less than", "<=": "at most", ">": "greater than", ">=": "at least"}
MAX_DEPTH = 3

SHAPE_META: list[dict] = [
    {"id": "required", "label": "Must be filled", "dtypes": None, "params": ["field"]},
    {"id": "between", "label": "Between two numbers", "dtypes": ["decimal", "int"], "params": ["field", "min", "max"]},
    {"id": "compare_num", "label": "Compare to a number", "dtypes": ["decimal", "int"], "params": ["field", "op", "number"]},
    {"id": "compare_field", "label": "Compare to another field", "dtypes": ["decimal", "int", "date", "string"], "params": ["field", "op", "other"]},
    {"id": "one_of", "label": "Must be one of", "dtypes": ["code", "string"], "params": ["field", "values"]},
    {"id": "equals", "label": "Equals a value", "dtypes": None, "params": ["field", "value"]},
    {"id": "digits", "label": "Exactly N digits", "dtypes": ["string", "int"], "params": ["field", "n"]},
    {"id": "date_order", "label": "Date before / after another", "dtypes": ["date"], "params": ["field_a", "order", "field_b"]},
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
            "id": "rate_range",
            "name": "Interest rate range",
            "description": "Interest rate must be between 0.5% and 15%",
            "tree": {"shape": "between", "field": "interest_rate", "min": 0.5, "max": 15},
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
            "id": "loan_number_required",
            "name": "Loan number required",
            "description": "Loan number must be filled",
            "tree": {"shape": "required", "field": "loan_number"},
        },
    ]


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

    if shape == "digits":
        f = _field(node.get("field"), ["string", "int"])
        n = int(node["n"])
        expr = {"matches": [{"var": f}, rf"\d{{{n}}}"]}
        tests = [(_base_with(**{f: "1" * n}), True), (_base_with(**{f: "1" * max(n - 1, 0) or "x"}), False)]
        return expr, f, [{"record": r, "expect": e} for r, e in tests], "format"

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
    if shape == "one_of":
        return f"{node.get('field')} is one of {', '.join(map(str, node.get('values') or []))}"
    if shape == "equals":
        return f"{node.get('field')} equals {node.get('value')}"
    if shape == "digits":
        return f"{node.get('field')} is {node.get('n')} digits"
    if shape == "date_order":
        return f"{node.get('field_a')} {node.get('order')} {node.get('field_b')}"
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

    if op == "<=" and len(args) == 3 and isinstance(args[1], dict) and "var" in args[1]:
        var = args[1]["var"]
        if isinstance(var, list):
            var = var[0]
        return {"shape": "between", "field": var, "min": args[0], "max": args[2]}

    if op in NUM_OPS and len(args) == 2 and isinstance(args[0], dict) and "var" in args[0]:
        var = args[0]["var"]
        if isinstance(var, list):
            var = var[0]
        if isinstance(args[1], dict) and "var" in args[1]:
            other = args[1]["var"]
            if isinstance(other, list):
                other = other[0]
            return {"shape": "compare_field", "field": var, "op": op, "other": other}
        return {"shape": "compare_num", "field": var, "op": op, "number": args[1]}

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

    if op == "matches" and isinstance(args[0], dict) and "var" in args[0]:
        var = args[0]["var"]
        if isinstance(var, list):
            var = var[0]
        import re

        m = re.fullmatch(r"\\d\{(\d+)\}", str(args[1]))
        if m:
            return {"shape": "digits", "field": var, "n": int(m.group(1))}

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
