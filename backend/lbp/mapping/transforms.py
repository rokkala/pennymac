"""No-code transformation library.

A mapping config holds, per SSE target attribute, an ordered list of transform steps, e.g.

    {"target": "interest_rate", "sources": ["Int Rate"],
     "transform": [{"op": "to_decimal"}, {"op": "normalize_rate"}]}

Supported: type casting, lookup translation, composite N:1 merges (concat / template),
1:N splits (split, parse_address), default injection, regex extraction, scaling.
Transforms never raise to the caller; failures are reported as field-level errors so the
loan can be routed to the Exception Manager with the original value intact.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from ..schema.sse_target import BY_NAME

STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY",
    "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
    "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "puerto rico": "PR",
}

LOOKUP_TABLES: dict[str, dict[str, Any]] = {
    "state_name_to_code": STATE_NAMES,
    "amortization_type": {"fixed": "FRM", "fixed rate": "FRM", "frm": "FRM", "adjustable": "ARM", "arm": "ARM", "variable": "ARM"},
    "occupancy_type": {"primary": "P", "primary residence": "P", "owner": "P", "owner occupied": "P", "o": "P", "p": "P",
                       "second home": "S", "secondary": "S", "s": "S", "investment": "I", "investor": "I", "non-owner": "I", "i": "I"},
    "loan_purpose": {"purchase": "PUR", "pur": "PUR", "rate/term refi": "REF", "refinance": "REF", "ref": "REF", "rate term": "REF",
                     "cash-out refi": "CSH", "cash out": "CSH", "cashout": "CSH", "csh": "CSH"},
    "loan_type": {"conventional": "CNV", "conv": "CNV", "cnv": "CNV", "fha": "FHA", "va": "VA", "usda": "USDA", "rd": "USDA"},
    "property_type": {"single family": "SFR", "sfr": "SFR", "sf": "SFR", "condo": "CON", "condominium": "CON", "con": "CON",
                      "pud": "PUD", "multi family": "MFR", "2-4 unit": "MFR", "mfr": "MFR", "manufactured": "MAN", "co-op": "COP"},
    "ofac_status": {"clear": "C", "c": "C", "hit": "H", "h": "H", "pending": "P", "p": "P"},
}

TRUE_VALUES = {"y", "yes", "true", "t", "1", "x"}
FALSE_VALUES = {"n", "no", "false", "f", "0", ""}
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%Y%m%d", "%m-%d-%Y", "%m/%d/%y", "%d-%b-%Y", "%Y/%m/%d"]
# Lenient on state/zip so a bad state or short ZIP surfaces as a rule exception, not a parse failure
ADDRESS_RE = re.compile(r"^\s*(?P<line1>[^,]+),\s*(?P<city>[^,]+),\s*(?P<state>[A-Za-z ]{0,4}?)\s*(?P<zip>\d{0,9}(-\d{4})?)\s*$")


class TransformError(ValueError):
    pass


def _num(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "").replace(" ", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError as e:
        raise TransformError(f"not a number: {v!r}") from e


def _date(v: Any, fmt: str | None = None) -> str:
    if isinstance(v, (date, datetime)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    for f in ([fmt] if fmt else DATE_FORMATS):
        try:
            return datetime.strptime(s, f).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise TransformError(f"unparseable date: {v!r}")


def _empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


# Each op: (value, step_params, all_source_values) -> value
def _op_trim(v, p, _):
    return v.strip() if isinstance(v, str) else v


def _op_upper(v, p, _):
    return v.upper() if isinstance(v, str) else v


def _op_lower(v, p, _):
    return v.lower() if isinstance(v, str) else v


def _op_title(v, p, _):
    return v.title() if isinstance(v, str) else v


def _op_to_decimal(v, p, _):
    return None if _empty(v) else round(_num(v), int(p.get("precision", 6)))


def _op_to_int(v, p, _):
    if _empty(v):
        return None
    n = _num(v)
    return int(round(n))


def _op_to_bool(v, p, _):
    if v is None:
        return None
    s = str(v).strip().lower()
    trues = set(p.get("true_values", TRUE_VALUES))
    if s in trues:
        return True
    if s in FALSE_VALUES or s in set(p.get("false_values", [])):
        return False if s else None
    raise TransformError(f"not a boolean: {v!r}")


def _op_to_date(v, p, _):
    return None if _empty(v) else _date(v, p.get("format"))


def _op_scale(v, p, _):
    return None if v is None else round(_num(v) * float(p.get("factor", 1)), 6)


def _op_divide(v, p, _):
    return None if v is None else round(_num(v) / float(p.get("divisor", 1)), 6)


def _op_normalize_rate(v, p, _):
    """Rates may arrive as 6.5, 0.065 or '6.5%'. SSE stores percent (6.5)."""
    if v is None:
        return None
    n = _num(v)
    return round(n * 100, 6) if 0 < n < float(p.get("decimal_below", 0.25)) else n


def _op_lookup(v, p, _):
    if _empty(v):
        return v
    key = str(v).strip().lower()
    # source-specific value map (edited in the Mapping UI) wins, then the shared lookup table
    for table in (p.get("map") or {}, LOOKUP_TABLES.get(p.get("table", ""), {})):
        if key in table:
            return table[key]
        for k, val in table.items():  # case-insensitive exact over original keys
            if str(k).strip().lower() == key:
                return val
    if p.get("on_miss", "passthrough") == "error":
        raise TransformError(f"no lookup for {v!r} in {p.get('table', 'inline map')}")
    return v


def _op_default(v, p, _):
    return p.get("value") if _empty(v) else v


def _op_constant(v, p, _):
    return p.get("value")


def _op_digits_only(v, p, _):
    return None if v is None else re.sub(r"\D", "", str(v))


def _op_substr(v, p, _):
    if v is None:
        return None
    s = str(v)
    start = int(p.get("start", 0))
    ln = p.get("length")
    return s[start:start + int(ln)] if ln is not None else s[start:]


def _op_pad_left(v, p, _):
    return None if _empty(v) else str(v).rjust(int(p.get("width", 0)), str(p.get("char", "0")))


def _op_truncate(v, p, _):
    return None if v is None else str(v)[: int(p.get("length", 255))]


def _op_split(v, p, _):
    if _empty(v):
        return v
    parts = [x.strip() for x in str(v).split(p.get("delimiter", ","))]
    idx = int(p.get("index", 0))
    return parts[idx] if idx < len(parts) else p.get("missing", None)


def _op_regex_extract(v, p, _):
    if _empty(v):
        return v
    m = re.search(p["pattern"], str(v))
    if not m:
        raise TransformError(f"pattern not found in {v!r}")
    return m.group(p.get("group", 1))


def _op_parse_address(v, p, _):
    if _empty(v):
        return v
    m = ADDRESS_RE.match(str(v))
    if not m:
        raise TransformError(f"cannot parse address: {v!r}")
    out = (m.group(p.get("part", "line1")) or "").strip()
    return out.upper() if p.get("part") == "state" else out


def _op_concat(v, p, srcs):
    sep = p.get("separator", " ")
    return sep.join(str(s).strip() for s in srcs if not _empty(s)) or None


def _op_template(v, p, srcs):
    try:
        return p["template"].format(*[("" if s is None else s) for s in srcs]).strip()
    except (IndexError, KeyError) as e:
        raise TransformError(f"bad template: {e}") from e


def _op_cents_to_dollars(v, p, _):
    return None if _empty(v) else round(_num(v) / 100, 2)


OPS: dict[str, Callable] = {
    "trim": _op_trim, "upper": _op_upper, "lower": _op_lower, "title": _op_title,
    "to_decimal": _op_to_decimal, "to_int": _op_to_int, "to_bool": _op_to_bool, "to_date": _op_to_date,
    "scale": _op_scale, "divide": _op_divide, "normalize_rate": _op_normalize_rate, "cents_to_dollars": _op_cents_to_dollars,
    "lookup": _op_lookup, "default": _op_default, "constant": _op_constant,
    "digits_only": _op_digits_only, "substr": _op_substr, "pad_left": _op_pad_left, "truncate": _op_truncate,
    "split": _op_split, "regex_extract": _op_regex_extract, "parse_address": _op_parse_address,
    "concat": _op_concat, "template": _op_template,
}
MULTI_SOURCE_OPS = {"concat", "template"}

OP_CATALOG = [
    {"op": "trim", "params": [], "group": "text"}, {"op": "upper", "params": [], "group": "text"},
    {"op": "title", "params": [], "group": "text"}, {"op": "digits_only", "params": [], "group": "text"},
    {"op": "substr", "params": ["start", "length"], "group": "text"}, {"op": "pad_left", "params": ["width", "char"], "group": "text"},
    {"op": "truncate", "params": ["length"], "group": "cast"}, {"op": "to_decimal", "params": ["precision"], "group": "cast"},
    {"op": "to_int", "params": [], "group": "cast"}, {"op": "to_bool", "params": ["true_values"], "group": "cast"},
    {"op": "to_date", "params": ["format"], "group": "cast"}, {"op": "scale", "params": ["factor"], "group": "math"},
    {"op": "divide", "params": ["divisor"], "group": "math"}, {"op": "normalize_rate", "params": [], "group": "math"},
    {"op": "cents_to_dollars", "params": [], "group": "math"}, {"op": "lookup", "params": ["table", "map", "on_miss"], "group": "lookup"},
    {"op": "default", "params": ["value"], "group": "default"}, {"op": "constant", "params": ["value"], "group": "default"},
    {"op": "split", "params": ["delimiter", "index"], "group": "composite"},
    {"op": "parse_address", "params": ["part"], "group": "composite"},
    {"op": "regex_extract", "params": ["pattern", "group"], "group": "composite"},
    {"op": "concat", "params": ["separator"], "group": "composite"}, {"op": "template", "params": ["template"], "group": "composite"},
]


def cast_step_for(target: str) -> dict | None:
    """The terminal cast every target field gets so SSE receives the right type."""
    attr = BY_NAME.get(target)
    if not attr:
        return None
    if attr.dtype == "decimal":
        return {"op": "to_decimal"}
    if attr.dtype == "int":
        return {"op": "to_int"}
    if attr.dtype == "date":
        return {"op": "to_date"}
    if attr.dtype == "bool":
        return {"op": "to_bool"}
    if attr.dtype == "code":
        return {"op": "upper"}
    # Strings are never truncated by default: an over-long value becomes a SCHEMA exception
    # instead of silently losing data. Analysts can add an explicit truncate step if intended.
    return None


def apply_field(spec: dict, row: dict[str, str]) -> Any:
    """Apply one field mapping to a raw source row. Raises TransformError."""
    sources = spec.get("sources") or []
    src_vals = [row.get(s) for s in sources]
    value = src_vals[0] if src_vals else None
    for step in spec.get("transform", []):
        fn = OPS.get(step.get("op"))
        if fn is None:
            raise TransformError(f"unknown op {step.get('op')!r}")
        value = fn(value, step, src_vals)
        if step.get("op") in MULTI_SOURCE_OPS:
            src_vals = [value]
    if _empty(value) and "default" in spec:
        value = spec["default"]
    return value


def compile_mapping(fields: list[dict]):
    """Return a fast row -> (record, errors) function for the active fields of a mapping."""
    active = [f for f in fields if f.get("status", "accepted") in ("accepted", "overridden", "approved") and f.get("target")]

    def run(row: dict[str, str]) -> tuple[dict, dict[str, str]]:
        rec, errs = {}, {}
        for spec in active:
            try:
                rec[spec["target"]] = apply_field(spec, row)
            except TransformError as e:
                rec[spec["target"]] = None
                errs[spec["target"]] = str(e)
        return rec, errs

    return run
