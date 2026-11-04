"""Deterministic correction proposers, one per known defect shape.

Each fixer returns a Proposal (value, confidence, rationale, fix_kind) or None. fix_kind
('format' | 'lookup' | 'derive' | 'scale' | 'recompute') feeds the routing policy: pure
formatting/lookups on medium-risk fields may be treated as low risk; high-risk fields are
never downgraded.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date

from ..mapping.transforms import LOOKUP_TABLES, STATE_NAMES
from ..schema.sse_target import BY_NAME, US_STATES

ZIP3_RANGES = [
    (10, 27, "MA"), (28, 29, "RI"), (30, 38, "NH"), (39, 49, "ME"), (50, 59, "VT"), (60, 69, "CT"), (70, 89, "NJ"),
    (100, 149, "NY"), (150, 196, "PA"), (197, 199, "DE"), (200, 205, "DC"), (206, 219, "MD"), (220, 246, "VA"),
    (247, 268, "WV"), (270, 289, "NC"), (290, 299, "SC"), (300, 319, "GA"), (320, 349, "FL"), (350, 369, "AL"),
    (370, 385, "TN"), (386, 397, "MS"), (398, 399, "GA"), (400, 427, "KY"), (430, 458, "OH"), (460, 479, "IN"),
    (480, 499, "MI"), (500, 528, "IA"), (530, 549, "WI"), (550, 567, "MN"), (570, 577, "SD"), (580, 588, "ND"),
    (590, 599, "MT"), (600, 629, "IL"), (630, 658, "MO"), (660, 679, "KS"), (680, 693, "NE"), (700, 714, "LA"),
    (716, 729, "AR"), (730, 749, "OK"), (750, 799, "TX"), (800, 816, "CO"), (820, 831, "WY"), (832, 838, "ID"),
    (840, 847, "UT"), (850, 865, "AZ"), (870, 884, "NM"), (889, 898, "NV"), (900, 961, "CA"), (967, 968, "HI"),
    (970, 979, "OR"), (980, 994, "WA"), (995, 999, "AK"),
]
STATE_ALIASES = {"TEX": "TX", "CALIF": "CA", "CAL": "CA", "FLA": "FL", "ARIZ": "AZ", "COLO": "CO", "WASH": "WA", "NEV": "NV", "PENN": "PA", "MASS": "MA"}


@dataclass
class Proposal:
    value: object
    confidence: float
    rationale: str
    fix_kind: str
    citations: list | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def state_from_zip(z: str | None) -> str | None:
    digits = re.sub(r"\D", "", str(z or ""))
    if len(digits) < 3:
        return None
    z3 = int(digits[:3])
    for lo, hi, st in ZIP3_RANGES:
        if lo <= z3 <= hi:
            return st
    return None


def fix_state(value, rec, field):
    raw = "" if value is None else str(value)
    compact = re.sub(r"[^A-Za-z]", "", raw).upper()
    if compact in US_STATES and raw != compact:
        return Proposal(compact, 0.97, f"Formatting: '{raw}' → '{compact}'", "format")
    if raw.strip().lower() in STATE_NAMES:
        v = STATE_NAMES[raw.strip().lower()]
        return Proposal(v, 0.97, f"State name lookup: '{raw}' → '{v}'", "lookup")
    if compact in STATE_ALIASES:
        return Proposal(STATE_ALIASES[compact], 0.92, f"Common abbreviation '{raw}' → '{STATE_ALIASES[compact]}'", "lookup")
    zip_field = field.replace("state", "zip")
    st = state_from_zip(rec.get(zip_field))
    if st:
        return Proposal(st, 0.93, f"Derived from ZIP {str(rec.get(zip_field))[:3]}xx (USPS ZIP3 range)", "derive")
    return None


def fix_occupancy(value, rec, field):
    v = LOOKUP_TABLES["occupancy_type"].get(str(value or "").strip().lower())
    if v:
        return Proposal(v, 0.96, f"Code lookup: '{value}' → '{v}'", "lookup")
    return None


def fix_code_lookup(table):
    def _fix(value, rec, field):
        v = LOOKUP_TABLES[table].get(str(value or "").strip().lower())
        return Proposal(v, 0.95, f"Code lookup ({table}): '{value}' → '{v}'", "lookup") if v else None
    return _fix


def fix_fico(value, rec, field):
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    if 3000 <= n <= 8500 and n % 10 == 0:
        return Proposal(n // 10, 0.9, f"Likely extra digit: {n} → {n // 10} (in 300-850 range)", "scale")
    return None


def fix_rate(value, rec, field):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    for div in (10, 100):
        cand = round(n / div, 6)
        if 0.5 <= cand <= 15 and n > 15:
            conf = 0.9 if div == 10 and rec.get("principal_interest_payment") else 0.82
            return Proposal(cand, conf, f"Scaled {n} ÷ {div} → {cand}% (plausible note rate)", "scale")
    return None


def fix_servicing_fee(value, rec, field):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if 1 < n <= 100 and 0 <= n / 100 <= 1:
        return Proposal(round(n / 100, 6), 0.9, f"Basis points/percent confusion: {n} → {n / 100}", "scale")
    return None


def fix_maturity(value, rec, field):
    fp, term = rec.get("first_payment_date"), rec.get("original_term_months")
    try:
        d = date.fromisoformat(str(fp)[:10])
        t = int(term)
    except (TypeError, ValueError):
        return None
    months = d.month - 1 + t - 1
    m = date(d.year + months // 12, months % 12 + 1, 1)
    return Proposal(m.isoformat(), 0.9, f"Recomputed: first payment {fp} + {t - 1} months", "recompute")


def fix_zip(value, rec, field):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 9:
        return Proposal(digits[:5], 0.96, "ZIP+4 trimmed to 5 digits", "format")
    if 0 < len(digits) < 5 and len(digits) >= 3:
        return Proposal(digits.zfill(5), 0.6, f"Left-padded '{digits}' (possible lost leading zeros) — verify", "format")
    return None


def fix_loan_number(value, rec, field):
    v = re.sub(r"[^A-Za-z0-9-]", "", str(value or "")).upper()
    if v and v != value and re.fullmatch(r"[A-Z0-9-]{6,20}", v):
        return Proposal(v, 0.95, f"Formatting: '{value}' → '{v}'", "format")
    return None


def fix_investor_gnma(value, rec, field):
    if rec.get("loan_type") in ("FHA", "VA", "USDA"):
        return Proposal("GNMA", 0.75, f"{rec.get('loan_type')} loans are typically GNMA securitized", "derive")
    return None


FIXERS = {
    "property_state": fix_state, "mailing_state": fix_state, "occupancy_type": fix_occupancy,
    "loan_purpose": fix_code_lookup("loan_purpose"), "property_type": fix_code_lookup("property_type"),
    "amortization_type": fix_code_lookup("amortization_type"), "borrower_fico": fix_fico, "coborrower_fico": fix_fico,
    "interest_rate": fix_rate, "original_interest_rate": fix_rate, "servicing_fee_rate": fix_servicing_fee,
    "maturity_date": fix_maturity, "property_zip": fix_zip, "mailing_zip": fix_zip, "loan_number": fix_loan_number,
    "investor_category": fix_investor_gnma,
}


def propose(field: str, value, rec: dict) -> Proposal | None:
    fn = FIXERS.get(field)
    if not fn or field not in BY_NAME:
        return None
    try:
        return fn(value, rec, field)
    except Exception:  # noqa: BLE001
        return None
