"""LLM-assisted rule authoring: SME types English -> JSON Logic DSL + test cases.

With an LLM provider configured the model drafts the rule; the output is validated
(compiles, references only SSE fields) and its generated tests are executed before the
draft is returned. Without a model, a deterministic pattern parser handles the common
rule shapes (required / range / comparison / code list / pattern / date order / conditional).
Either way the result is only ever a *draft*: it still goes through review and approval.
"""
from __future__ import annotations

import json
import re

from ..ai import get_llm
from ..mapping.engine import name_similarity
from ..schema.sse_target import ATTRIBUTES, BY_NAME
from .default_rules import BASE_LOAN
from .jsonlogic import validate
from .registry import run_tests

NUM = r"(-?\d+(?:\.\d+)?)"


def resolve_field(phrase: str) -> tuple[str | None, float]:
    phrase = phrase.strip().strip(".").strip()
    phrase = re.sub(r"^(the|a|an|borrower's|loan's)\s+", "", phrase, flags=re.I)
    if phrase.replace(" ", "_").lower() in BY_NAME:
        return phrase.replace(" ", "_").lower(), 1.0
    best, best_s = None, 0.0
    for a in ATTRIBUTES:
        s, _ = name_similarity(phrase, a)
        if s > best_s:
            best, best_s = a.name, s
    return (best, best_s) if best_s >= 0.45 else (None, best_s)


def _sample_value(field: str):
    if field in BASE_LOAN:
        return BASE_LOAN[field]
    attr = BY_NAME[field]
    return {"decimal": 100.0, "int": 10, "date": "2025-01-01", "bool": True, "code": (attr.codes or ("X",))[0]}.get(attr.dtype, "ABC")


def _base_with(field: str, value) -> dict:
    return {**BASE_LOAN, field: value}


def _heuristic(text: str) -> dict | None:
    s = text.strip().rstrip(".")
    low = s.lower()
    severity = "WARN" if re.search(r"\b(warn|warning|flag|should)\b", low) else "FAIL"
    body = re.sub(r"^(warn|flag|fail)( if| when|:)?\s+", "", s, flags=re.I)

    # conditional: "if <field> is <value>, <clause>" / "when ... then ..."
    m = re.match(r"^(?:if|when)\s+(.+?)\s+(?:is|=|equals)\s+([\w./-]+)\s*(?:,|then)\s*(.+)$", body, re.I)
    if m:
        f, _ = resolve_field(m.group(1))
        inner = _heuristic(m.group(3))
        if f and inner:
            cond_val = m.group(2).upper() if BY_NAME[f].dtype == "code" else m.group(2)
            expr = {"if": [{"==": [{"var": f}, cond_val]}, inner["expression"], True]}
            tests = [{"record": {**t["record"], f: cond_val}, "expect": t["expect"]} for t in inner["tests"]]
            tests.append({"record": _base_with(f, "__other__"), "expect": True})
            return {**inner, "expression": expr, "tests": tests, "severity": severity if severity == "WARN" else inner["severity"]}

    patterns = [
        (rf"^(.+?)\s+must be between\s+{NUM}\s*%?\s+and\s+{NUM}", "between"),
        (r"^(.+?)\s+(?:is required|must be (?:populated|present|provided)|must not be (?:blank|empty|missing)|cannot be (?:blank|empty))", "required"),
        (r"^(.+?)\s+must be (?:one of|in|either)\s*:?\s*(.+)$", "in"),
        (r"^(.+?)\s+must be (?:exactly\s+)?(\d+)\s+digits", "digits"),
        (r"^(.+?)\s+must match (?:pattern |regex )?['\"]?(.+?)['\"]?$", "pattern"),
        (r"^(.+?)\s+must (?:look like|be formatted as|match format)\s+(.+)$", "pattern"),
        (rf"^(.+?)\s+must (?:not exceed|be (?:less than or equal to|at most|<=|no more than))\s+{NUM}\s*%?$", "le_num"),
        (rf"^(.+?)\s+must be (?:greater than or equal to|at least|>=|no less than)\s+{NUM}\s*%?$", "ge_num"),
        (rf"^(.+?)\s+must be (?:less than|below|under|<)\s+{NUM}\s*%?$", "lt_num"),
        (rf"^(.+?)\s+must be (?:greater than|above|over|more than|>)\s+{NUM}\s*%?$", "gt_num"),
        (r"^(.+?)\s+must (?:not exceed|be (?:less than or equal to|at most|no more than))\s+(?:the\s+)?(.+)$", "le_field"),
        (r"^(.+?)\s+must be (?:after|later than)\s+(?:the\s+)?(.+)$", "after"),
        (r"^(.+?)\s+must be (?:before|earlier than)\s+(?:the\s+)?(.+)$", "before"),
        (r"^(.+?)\s+(?:must|should) (?:be|equal)\s+([\w-]+)$", "eq"),
    ]
    for rx, kind in patterns:
        m = re.match(rx, body, re.I)
        if not m:
            continue
        f, conf = resolve_field(m.group(1))
        if not f:
            return None
        v = {"var": f}
        ok_val = _sample_value(f)
        if kind == "between":
            a, b = float(m.group(2)), float(m.group(3))
            expr = {"<=": [a, v, b]}
            tests = [(_base_with(f, (a + b) / 2), True), (_base_with(f, b * 10 + 1), False), (_base_with(f, None), False)]
        elif kind == "required":
            expr = {"!": {"is_blank": v}}
            tests = [(_base_with(f, ok_val), True), (_base_with(f, ""), False), (_base_with(f, None), False)]
        elif kind == "in":
            vals = [x.strip().strip("'\"").upper() for x in re.split(r",|\bor\b|/", m.group(2)) if x.strip()]
            expr = {"in": [v, vals]}
            tests = [(_base_with(f, vals[0]), True), (_base_with(f, "ZZZ"), False)]
        elif kind == "digits":
            n = int(m.group(2))
            expr = {"matches": [v, f"\\d{{{n}}}"]}
            tests = [(_base_with(f, "1" * n), True), (_base_with(f, "1" * (n - 1)), False)]
        elif kind == "pattern":
            from .shapes import compile_tree

            pat = m.group(2).strip().strip("'\"")
            # Special-case the common loan-number wording used in defaults / demos.
            if "loan" in low and "number" in low and "between" not in low:
                pat = pat if re.search(r"[\\\[\{]", pat) else "[A-Z0-9-]{6,20}"
            try:
                drafted = compile_tree({"shape": "pattern", "field": f, "pattern": pat})
            except Exception:
                return None
            return {**drafted, "name": s[:120], "description": s, "severity": severity, "field_confidence": round(conf, 2)}
        elif kind.endswith("_num"):
            x = float(m.group(2))
            op = {"le_num": "<=", "ge_num": ">=", "lt_num": "<", "gt_num": ">"}[kind]
            expr = {op: [v, x]}
            good = x if op in ("<=", ">=") else (x - 1 if op == "<" else x + 1)
            bad = x + abs(x) + 1 if op in ("<=", "<") else x - abs(x) - 1
            tests = [(_base_with(f, good), True), (_base_with(f, bad), False)]
        elif kind == "le_field":
            g, _ = resolve_field(m.group(2))
            if not g:
                return None
            expr = {"<=": [v, {"var": g}]}
            tests = [({**BASE_LOAN, f: 100, g: 200}, True), ({**BASE_LOAN, f: 300, g: 200}, False)]
        elif kind in ("after", "before"):
            g, _ = resolve_field(m.group(2))
            if not g:
                return None
            a, b = (g, f) if kind == "after" else (f, g)
            expr = {">": [{"days_between": [{"var": a}, {"var": b}]}, 0]}
            tests = [({**BASE_LOAN, a: "2024-01-01", b: "2024-06-01"}, True), ({**BASE_LOAN, a: "2024-06-01", b: "2024-01-01"}, False)]
        else:  # eq
            val = m.group(2).upper() if BY_NAME[f].dtype == "code" else m.group(2)
            expr = {"==": [v, val]}
            tests = [(_base_with(f, val), True), (_base_with(f, "__other__"), False)]
        attr = BY_NAME[f]
        return {
            "name": s[:120], "description": s, "expression": expr, "field": f, "fields": [f],
            "severity": severity, "category": "completeness" if kind == "required" else "range" if kind in ("between",) or kind.endswith("_num") else "format" if kind in ("in", "digits", "eq") else "consistency",
            "tests": [{"record": r, "expect": e} for r, e in tests], "field_confidence": round(conf, 2),
            "regulatory_tag": "HMDA" if attr.risk == "high" and attr.module == "PROPERTY" else None,
        }
    return None


SYSTEM = """You convert mortgage servicing business rules written in English into JSON Logic.
Rules evaluate TRUE when the loan PASSES. Allowed operators: var, ==, !=, <, <=, >, >= (3-arg form = between), and, or, !, if,
in, +, -, *, /, abs, min, max, matches (regex fullmatch), is_blank, is_date, days_between(a,b)=b-a in days, months_between,
pmt(rate_pct, term_months, amount), in_codes(value, field_name).
Use only these field names: {fields}
Return JSON: {{"name":str,"expression":<json logic>,"field":<primary field>,"severity":"FAIL"|"WARN",
"category":"completeness|format|range|consistency|compliance|risk","regulatory_tag":str|null,
"tests":[{{"record":{{...only fields used...}},"expect":true|false}}, ...at least 2 passing and 2 failing]}}"""


def draft_from_text(text: str) -> dict:
    """Returns {"draft": rule body | None, "source": "llm"|"heuristic", "test_results": [...], "problems": [...]}"""
    llm = get_llm()
    problems: list[str] = []
    if llm.name != "heuristic":
        fields = ", ".join(f"{a.name}({a.dtype})" for a in ATTRIBUTES)
        out = llm.complete_json(SYSTEM.format(fields=fields), text)
        if isinstance(out, dict) and out.get("expression") is not None:
            out["tests"] = [{"record": {**BASE_LOAN, **(t.get("record") or {})}, "expect": bool(t.get("expect"))} for t in out.get("tests", [])]
            problems = validate(out["expression"])
            if not problems and out.get("field") in BY_NAME:
                out.setdefault("description", text)
                out.setdefault("fields", [out["field"]])
                res = run_tests(out)
                return {"draft": out, "source": "llm", "test_results": res, "problems": [f"test {r['case']} failed" for r in res if not r["passed"]]}
    h = _heuristic(text)
    if not h:
        return {"draft": None, "source": "heuristic", "test_results": [],
                "problems": problems + ["Could not interpret the rule. Try e.g. 'Interest rate must be between 0.5 and 15', "
                                        "'Borrower SSN is required', 'Occupancy must be one of P, S, I', "
                                        "'If loan type is FHA, investor category must be GNMA'."]}
    res = run_tests(h)
    try:
        from .shapes import decompile

        tree = decompile(h["expression"])
        if tree:
            h["tree"] = tree
            h["summary"] = h.get("description") or h.get("name")
    except Exception:  # noqa: BLE001 — authoring must not fail on decompile
        pass
    return {"draft": h, "source": "heuristic", "test_results": res, "problems": [f"test {r['case']} failed" for r in res if not r["passed"]],
            "dsl": json.dumps(h["expression"])}
