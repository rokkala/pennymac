"""PII detection and dynamic masking.

Two signals are combined: column-name semantics and value patterns. In AWS mode the same
interface can be backed by Amazon Comprehend DetectPiiEntities / Macie; the regex detector
stays as a fast, deterministic first pass.
"""
from __future__ import annotations

import hashlib
import re

VALUE_PATTERNS = {
    "SSN": re.compile(r"^(?!000|666|9\d\d)\d{3}-?(?!00)\d{2}-?(?!0000)\d{4}$"),
    "EMAIL": re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$"),
    "PHONE": re.compile(r"^(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}$"),
    "ADDRESS": re.compile(r"^\d{1,6}\s+[A-Za-z0-9.' ]+\s(St|Street|Ave|Avenue|Rd|Road|Ln|Lane|Dr|Drive|Blvd|Ct|Court|Way|Pl|Place|Hwy|Pkwy|Cir)\b", re.I),
}
NAME_HINTS = {
    "SSN": ["ssn", "social", "tin", "tax id", "taxid"],
    "DOB": ["dob", "birth"],
    "EMAIL": ["email", "e-mail"],
    "PHONE": ["phone", "mobile", "cell", "tel"],
    "NAME": ["first name", "last name", "fname", "lname", "surname", "borrower name", "middle name", "full name"],
    "ADDRESS": ["address", "addr", "street"],
}


def _norm(s: str) -> str:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def detect_column_pii(column: str, values: list[str]) -> tuple[str | None, float]:
    name = _norm(column)
    name_hit = None
    for pii_type, hints in NAME_HINTS.items():
        if any(h in name or h.replace(" ", "") in name.replace(" ", "") for h in hints):
            name_hit = pii_type
            break
    # token-level hits for abbreviations like B1_FNAME
    tokens = set(name.split())
    if not name_hit and tokens & {"fname", "lname", "mname"}:
        name_hit = "NAME"
    vals = [v for v in values if v]
    best, best_share = None, 0.0
    for pii_type, rx in VALUE_PATTERNS.items():
        if not vals:
            break
        share = sum(1 for v in vals if rx.match(v)) / len(vals)
        if share > best_share:
            best, best_share = pii_type, share
    if name_hit and (best == name_hit or best_share < 0.5):
        return name_hit, round(0.7 + 0.3 * (best_share if best == name_hit else 0.5), 2)
    if best and best_share >= 0.8:
        # 9-digit numerics are SSN only if the name does not say otherwise (avoid loan numbers)
        if best == "SSN" and any(t in name for t in ("loan", "nbr", "zip", "number", "id")) and not name_hit:
            return None, 0.0
        return best, round(best_share * 0.9, 2)
    return None, 0.0


def mask_value(value: str, pii_type: str | None, mode: str = "partial") -> str:
    """partial: keep last 4 (SSN/phone) or first letter (name); hash: deterministic token; full: redact."""
    if not value or not pii_type:
        return value
    if mode == "hash":
        return "tok_" + hashlib.sha256(value.encode()).hexdigest()[:12]
    if mode == "full":
        return "*" * min(len(value), 8)
    digits = re.sub(r"\D", "", value)
    if pii_type == "SSN":
        return f"***-**-{digits[-4:]}" if len(digits) >= 4 else "***"
    if pii_type == "PHONE":
        return f"(***) ***-{digits[-4:]}" if len(digits) >= 4 else "***"
    if pii_type == "EMAIL":
        user, _, domain = value.partition("@")
        return f"{user[:1]}***@{domain}"
    if pii_type == "DOB":
        return "**/**/" + value[-4:] if len(value) >= 4 else "****"
    if pii_type == "NAME":
        return value[:1] + "*" * max(len(value) - 1, 2)
    if pii_type == "ADDRESS":
        parts = value.split(" ", 1)
        return "*** " + (parts[1] if len(parts) > 1 else "")
    return "****"


def mask_record(record: dict, pii_fields: dict[str, str], mode: str = "partial") -> dict:
    return {k: (mask_value(str(v), pii_fields[k], mode) if k in pii_fields and v not in (None, "") else v) for k, v in record.items()}


TARGET_PII_TYPES = {
    "borrower_ssn": "SSN", "coborrower_ssn": "SSN", "borrower_dob": "DOB", "borrower_email": "EMAIL",
    "borrower_home_phone": "PHONE", "borrower_cell_phone": "PHONE", "borrower_first_name": "NAME",
    "borrower_middle_name": "NAME", "borrower_last_name": "NAME", "coborrower_first_name": "NAME",
    "coborrower_last_name": "NAME", "mailing_address_line1": "ADDRESS", "property_address_line1": "ADDRESS",
}
