"""Source data profiling: per-column type inference, completeness, cardinality, patterns, samples.

The profile feeds three consumers: the Mapping UI (what does this column look like?), the AI
mapping engine (value-shape compatibility with target attributes) and the DQ scorecard.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from .pii import detect_column_pii

DATE_PATTERNS = [
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "%Y-%m-%d"),
    (re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$"), "%m/%d/%Y"),
    (re.compile(r"^(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])$"), "%Y%m%d"),
    (re.compile(r"^\d{1,2}-\d{1,2}-\d{4}$"), "%m-%d-%Y"),
]
NUM_RE = re.compile(r"^-?\$?\s?-?[\d,]*\.?\d+%?$")
INT_RE = re.compile(r"^-?\d+$")
BOOL_VALUES = {"y", "n", "yes", "no", "true", "false", "1", "0", "t", "f"}


def _shape(v: str) -> str:
    """Collapse a value into a pattern like 'AAA9999' for pattern profiling."""
    s = re.sub(r"[A-Za-z]", "A", v)
    s = re.sub(r"\d", "9", s)
    return re.sub(r"(.)\1{3,}", lambda m: m.group(1) * 3 + "+", s)[:24]


def infer_type(values: list[str]) -> tuple[str, str | None]:
    """Returns (dtype, date_format)."""
    vals = [v for v in values if v != ""]
    if not vals:
        return "string", None
    lower = {v.lower() for v in vals}
    if lower <= BOOL_VALUES and len(lower) <= 2 and not (lower <= {"1", "0"} and len(vals) < 5):
        return "bool", None
    for rx, fmt in DATE_PATTERNS:
        if sum(1 for v in vals if rx.match(v)) / len(vals) >= 0.9:
            return "date", fmt
    if all(INT_RE.match(v) for v in vals):
        # leading zeros or fixed width ids are identifiers, not numbers
        if any(len(v) > 1 and v.startswith("0") for v in vals):
            return "string", None
        return "int", None
    if sum(1 for v in vals if NUM_RE.match(v.replace(" ", ""))) / len(vals) >= 0.95:
        return "decimal", None
    distinct = len(set(vals))
    if distinct <= 12 and len(vals) >= 20 and max(len(v) for v in vals) <= 20:
        return "code", None
    return "string", None


@dataclass
class ColumnProfile:
    name: str
    inferred_type: str
    date_format: str | None
    non_null: int
    null_pct: float
    distinct: int
    min_len: int
    max_len: int
    min_value: float | None
    max_value: float | None
    top_values: list[tuple[str, int]]
    top_patterns: list[tuple[str, int]]
    samples: list[str]
    pii_type: str | None
    pii_confidence: float = 0.0
    completeness_score: float = 0.0
    validity_score: float = 0.0
    notes: list[str] = field(default_factory=list)


def _to_float(v: str) -> float | None:
    try:
        return float(v.replace("$", "").replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def profile_column(name: str, values: list[str]) -> ColumnProfile:
    total = len(values)
    non_null_vals = [v for v in values if v != ""]
    dtype, date_fmt = infer_type(non_null_vals[:2000])
    counts = Counter(non_null_vals)
    patterns = Counter(_shape(v) for v in non_null_vals)
    nums = [x for x in (_to_float(v) for v in non_null_vals) if x is not None] if dtype in ("int", "decimal") else []
    pii_type, pii_conf = detect_column_pii(name, non_null_vals[:200])
    dominant_pattern_share = (patterns.most_common(1)[0][1] / len(non_null_vals)) if non_null_vals else 0
    notes = []
    if total and len(non_null_vals) / total < 0.95:
        notes.append(f"{100 - round(len(non_null_vals) / total * 100)}% missing")
    if dtype in ("string", "code") and dominant_pattern_share < 0.8 and len(patterns) > 3 and len(counts) > 20:
        notes.append("inconsistent formats")
    return ColumnProfile(
        name=name,
        inferred_type=dtype,
        date_format=date_fmt,
        non_null=len(non_null_vals),
        null_pct=round((1 - len(non_null_vals) / total) * 100, 2) if total else 0.0,
        distinct=len(counts),
        min_len=min((len(v) for v in non_null_vals), default=0),
        max_len=max((len(v) for v in non_null_vals), default=0),
        min_value=min(nums) if nums else None,
        max_value=max(nums) if nums else None,
        top_values=counts.most_common(5),
        top_patterns=patterns.most_common(3),
        samples=[v for v, _ in counts.most_common(3)] if not pii_type else [],  # never surface raw PII
        pii_type=pii_type,
        pii_confidence=pii_conf,
        completeness_score=round(len(non_null_vals) / total * 100, 1) if total else 0.0,
        validity_score=round(dominant_pattern_share * 100, 1),
        notes=notes,
    )


def profile_rows(columns: list[str], rows: list[dict[str, str]]) -> dict:
    cols = [profile_column(c, [r.get(c, "") for r in rows]) for c in columns]
    if cols:
        completeness = sum(c.completeness_score for c in cols) / len(cols)
        validity = sum(c.validity_score for c in cols) / len(cols)
    else:
        completeness = validity = 0.0
    return {
        "row_count_sampled": len(rows),
        "column_count": len(columns),
        "completeness": round(completeness, 1),
        "validity": round(validity, 1),
        "pii_columns": [c.name for c in cols if c.pii_type],
        "columns": [asdict(c) for c in cols],
    }
