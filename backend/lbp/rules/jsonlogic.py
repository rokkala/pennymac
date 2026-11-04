"""Compact, dependency-free JSON Logic evaluator (jsonlogic.com) plus loan-domain operators.

Standard ops: var, missing, missing_some, if, ==, ===, !=, !==, !, !!, or, and, <, <=, >, >=
(incl. 3-arg between), +, -, *, /, %, min, max, cat, substr, in, merge, map, filter, all, some, none.
Domain ops: matches (regex), len, is_date, days_between, months_between, pmt (P&I payment), abs, round,
in_codes (SSE code list lookup), is_blank, xor (exactly one truthy), all_present (none blank),
date_before / date_after (date order).

Rules are compiled once into Python closures so evaluating ~20 rules over 1M loans stays fast.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from functools import cache
from typing import Any

Compiled = Callable[[dict], Any]


def _truthy(v: Any) -> bool:
    if isinstance(v, (list, tuple)):
        return len(v) > 0
    return bool(v) and v != "0" if isinstance(v, str) else bool(v)


def _get(data: Any, path: Any, default: Any = None) -> Any:
    if path is None or path == "":
        return data
    cur = data
    for part in str(path).split("."):
        if isinstance(cur, dict):
            if part not in cur:
                return default
            cur = cur[part]
        elif isinstance(cur, (list, tuple)):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return default
        else:
            return default
    return default if cur is None and default is not None else cur


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cmp(a, b, op):
    if a is None or b is None:
        return False
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None and not (isinstance(a, str) and isinstance(b, str)):
        a, b = na, nb
    try:
        return op(a, b)
    except TypeError:
        return False


def _loose_eq(a, b):
    if a == b:
        return True
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None and not isinstance(a, bool) and not isinstance(b, bool):
        return na == nb
    return False


def _parse_date(v) -> date | None:
    if isinstance(v, date):
        return v
    if not isinstance(v, str) or len(v) < 10:
        return None
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        return None


def _pmt(rate_pct, term, amount):
    r, n, p = _num(rate_pct), _num(term), _num(amount)
    if r is None or n is None or p is None or n <= 0:
        return None
    r = r / 1200
    if r == 0:
        return round(p / n, 2)
    return round(p * r / (1 - (1 + r) ** -n), 2)


@cache
def _regex(p: str):
    return re.compile(p)


def _in_codes(value, field):
    from ..schema.sse_target import BY_NAME

    attr = BY_NAME.get(field)
    return bool(attr and value is not None and str(value) in attr.codes)


SIMPLE: dict[str, Callable[..., Any]] = {
    "==": lambda a, b: _loose_eq(a, b),
    "===": lambda a, b: a == b and type(a) is type(b),
    "!=": lambda a, b: not _loose_eq(a, b),
    "!==": lambda a, b: not (a == b and type(a) is type(b)),
    "!": lambda a: not _truthy(a),
    "!!": lambda a: _truthy(a),
    "+": lambda *a: sum((_num(x) or 0.0) for x in a),
    "*": lambda *a: __import__("math").prod((_num(x) or 0.0) for x in a),
    "-": lambda a, b=None: -(_num(a) or 0) if b is None else (_num(a) or 0) - (_num(b) or 0),
    "/": lambda a, b: None if not _num(b) else (_num(a) or 0) / _num(b),
    "%": lambda a, b: None if not _num(b) else (_num(a) or 0) % _num(b),
    "min": lambda *a: min((_num(x) for x in a if _num(x) is not None), default=None),
    "max": lambda *a: max((_num(x) for x in a if _num(x) is not None), default=None),
    "abs": lambda a: None if _num(a) is None else abs(_num(a)),
    "round": lambda a, d=0: None if _num(a) is None else round(_num(a), int(d)),
    "cat": lambda *a: "".join("" if x is None else str(x) for x in a),
    "substr": lambda s, start, ln=None: (str(s or "")[int(start):] if ln is None else
                                          str(s or "")[int(start):(int(start) + int(ln)) if int(ln) >= 0 else int(ln)]),
    "in": lambda a, b: (a in b) if isinstance(b, (list, tuple)) else (str(a) in str(b) if b is not None and a is not None else False),
    "merge": lambda *a: [y for x in a for y in (x if isinstance(x, list) else [x])],
    "matches": lambda s, p: s is not None and bool(_regex(p).fullmatch(str(s))),
    "len": lambda s: 0 if s is None else len(s) if isinstance(s, (str, list)) else len(str(s)),
    "is_date": lambda v: _parse_date(v) is not None,
    "is_blank": lambda v: v is None or (isinstance(v, str) and v.strip() == ""),
    "days_between": lambda a, b: (None if _parse_date(a) is None or _parse_date(b) is None
                                  else (_parse_date(b) - _parse_date(a)).days),
    "months_between": lambda a, b: (None if _parse_date(a) is None or _parse_date(b) is None
                                    else (_parse_date(b).year - _parse_date(a).year) * 12 + _parse_date(b).month - _parse_date(a).month),
    "pmt": _pmt,
    "in_codes": _in_codes,
    "xor": lambda *a: sum(1 for x in a if _truthy(x)) == 1,
    "all_present": lambda *a: all(not (x is None or (isinstance(x, str) and x.strip() == "")) for x in a),
    "date_before": lambda a, b: (_parse_date(a) is not None and _parse_date(b) is not None and _parse_date(a) < _parse_date(b)),
    "date_after": lambda a, b: (_parse_date(a) is not None and _parse_date(b) is not None and _parse_date(a) > _parse_date(b)),
}


class JsonLogicError(ValueError):
    pass


def compile_logic(logic: Any) -> Compiled:
    if isinstance(logic, list):
        parts = [compile_logic(x) for x in logic]
        return lambda d: [p(d) for p in parts]
    if not isinstance(logic, dict) or len(logic) != 1:
        return lambda d, v=logic: v
    op, args = next(iter(logic.items()))
    if not isinstance(args, list):
        args = [args]

    if op == "var":
        path_c = compile_logic(args[0]) if args else (lambda d: None)
        default = args[1] if len(args) > 1 else None
        return lambda d: _get(d, path_c(d), default)
    if op == "missing":
        cs = [compile_logic(a) for a in args]

        def missing(d):
            keys = []
            for c in cs:
                v = c(d)
                keys.extend(v if isinstance(v, list) else [v])
            return [k for k in keys if _get(d, k) in (None, "")]
        return missing
    if op == "missing_some":
        need_c, keys_c = compile_logic(args[0]), compile_logic(args[1])

        def missing_some(d):
            keys = keys_c(d)
            miss = [k for k in keys if _get(d, k) in (None, "")]
            return [] if len(keys) - len(miss) >= need_c(d) else miss
        return missing_some
    if op in ("if", "?:"):
        cs = [compile_logic(a) for a in args]

        def _if(d):
            i = 0
            while i < len(cs) - 1:
                if _truthy(cs[i](d)):
                    return cs[i + 1](d)
                i += 2
            return cs[i](d) if i < len(cs) else None
        return _if
    if op == "and":
        cs = [compile_logic(a) for a in args]

        def _and(d):
            v = True
            for c in cs:
                v = c(d)
                if not _truthy(v):
                    return v
            return v
        return _and
    if op == "or":
        cs = [compile_logic(a) for a in args]

        def _or(d):
            v = False
            for c in cs:
                v = c(d)
                if _truthy(v):
                    return v
            return v
        return _or
    if op in ("<", "<=", ">", ">="):
        import operator as o

        fn = {"<": o.lt, "<=": o.le, ">": o.gt, ">=": o.ge}[op]
        cs = [compile_logic(a) for a in args]
        if len(cs) == 3:  # between
            return lambda d: _cmp(cs[0](d), cs[1](d), fn) and _cmp(cs[1](d), cs[2](d), fn)
        return lambda d: _cmp(cs[0](d), cs[1](d), fn)
    if op in ("map", "filter", "all", "some", "none"):
        arr_c, body_c = compile_logic(args[0]), compile_logic(args[1])

        def _iter(d):
            arr = arr_c(d) or []
            if op == "map":
                return [body_c(x) for x in arr]
            if op == "filter":
                return [x for x in arr if _truthy(body_c(x))]
            if op == "all":
                return bool(arr) and all(_truthy(body_c(x)) for x in arr)
            if op == "some":
                return any(_truthy(body_c(x)) for x in arr)
            return not any(_truthy(body_c(x)) for x in arr)
        return _iter
    if op in SIMPLE:
        fn = SIMPLE[op]
        cs = [compile_logic(a) for a in args]
        return lambda d: fn(*[c(d) for c in cs])
    raise JsonLogicError(f"unsupported operator: {op}")


def apply(logic: Any, data: dict) -> Any:
    return compile_logic(logic)(data)


def referenced_vars(logic: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(logic, dict):
        for op, args in logic.items():
            if op == "var":
                a = args[0] if isinstance(args, list) and args else args
                if isinstance(a, str):
                    out.add(a.split(".")[0])
            else:
                out |= referenced_vars(args)
    elif isinstance(logic, list):
        for x in logic:
            out |= referenced_vars(x)
    return out


def validate(logic: Any) -> list[str]:
    """Return a list of problems (empty = valid)."""
    try:
        compile_logic(logic)
    except JsonLogicError as e:
        return [str(e)]
    from ..schema.sse_target import BY_NAME

    unknown = sorted(v for v in referenced_vars(logic) if v not in BY_NAME)
    return [f"unknown field: {u}" for u in unknown]
