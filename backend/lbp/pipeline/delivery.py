"""Vendor delivery profiles: how a source sends data, and what each row of a file means.

A profile lives on `sources.delivery` and is changed through maker-checker (draft -> second approver):

    load_type        full        every file is a complete boarding tape (default; original behaviour)
                     incremental files carry changes: add / update / close rows
                     snapshot    every file is the vendor's complete current portfolio; the platform
                                 works out adds, updates, unchanged and loans that disappeared
    action           how an incremental row says what it is
        mode         column    a source column holds a code, mapped through `values`
                     filename  the whole file is one action, chosen by a filename pattern
                     upsert    no action given: update if the loan is in SSE, otherwise add
    blank_means      no_change (sparse rows: only populated fields change) | clear
    clear_token      a value meaning "clear this field" when blank_means = no_change (e.g. "#CLEAR")
    sequence         per-vendor file ordering (see sequencing.py)
        source       filename | column | none
        pattern      regex with one group, applied to the filename (source = filename)
        column       source column holding the sequence / as-of date (source = column)
        kind         integer | date
        strict       integer: wait for missing numbers before applying later files
    protected_fields fields that may not change through an update without dual control
    set_once_fields  original terms set at boarding; ignored in change files (counted, never applied)
    snapshot         missing_action: review | ignore; max_missing_pct: above this the file is treated
                     as truncated and no close reviews are raised automatically
"""
from __future__ import annotations

import re
from datetime import date, datetime

LOAD_TYPES = ("full", "incremental", "snapshot")
ACTIONS = ("add", "update", "close")

# Identity, original terms, regulated reporting and investor fields. Routine servicing data
# (balances, due dates, delinquency, escrow, contact details) changes without extra review.
DEFAULT_PROTECTED = [
    "original_loan_amount", "original_interest_rate", "original_term_months", "note_date", "first_payment_date",
    "maturity_date", "interest_rate", "loan_type", "lien_position", "amortization_type",
    "borrower_ssn", "coborrower_ssn", "borrower_first_name", "borrower_last_name", "borrower_dob",
    "property_address_line1", "property_state", "property_zip",
    "investor_code", "investor_category", "servicing_fee_rate",
    "hmda_rate_spread", "hmda_hoepa_status", "apr",
]
# Original terms are set when the loan is boarded. Change files never overwrite them: a vendor's
# "NoteRate" column often feeds both interest_rate and original_interest_rate (1:N mapping), and an
# ARM reset must not rewrite the original rate. Corrections to original terms go through a full
# re-board, where DUP02 puts them in front of a reviewer.
DEFAULT_SET_ONCE = ["original_loan_amount", "original_interest_rate", "original_term_months", "note_date", "first_payment_date"]
# A rate change is routine on an ARM reset; only fixed-rate loans need review for it.
ARM_ROUTINE = {"interest_rate"}

DEFAULT_PROFILE = {
    "load_type": "full",
    "action": {"mode": "upsert", "column": None, "values": {}, "filename_patterns": {}},
    "blank_means": "no_change",
    "clear_token": None,
    "sequence": {"source": "none", "pattern": None, "column": None, "kind": "integer", "strict": True},
    "protected_fields": DEFAULT_PROTECTED,
    "set_once_fields": DEFAULT_SET_ONCE,
    "snapshot": {"missing_action": "review", "max_missing_pct": 5.0},
}


class DeliveryError(ValueError):
    pass


def profile_of(src_delivery: dict | None) -> dict:
    """Effective profile: stored values over defaults (nested one level)."""
    p = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in DEFAULT_PROFILE.items()}
    for k, v in (src_delivery or {}).items():
        if isinstance(v, dict) and isinstance(p.get(k), dict):
            p[k] = {**p[k], **v}
        elif v is not None:
            p[k] = v
    return p


def validate_profile(p: dict, columns: list[str] | None = None) -> list[str]:
    from ..schema.sse_target import BY_NAME

    errs = []
    p = profile_of(p)
    if p["load_type"] not in LOAD_TYPES:
        errs.append(f"load_type must be one of {LOAD_TYPES}")
    a = p["action"]
    if a.get("mode") not in ("column", "filename", "upsert"):
        errs.append("action.mode must be column, filename or upsert")
    if p["load_type"] == "incremental" and a.get("mode") == "column":
        if not a.get("column"):
            errs.append("action.column is required for mode=column")
        bad = sorted({v for v in (a.get("values") or {}).values() if v not in ACTIONS})
        if bad or not a.get("values"):
            errs.append("action.values must map each vendor code to add, update or close")
    if p["load_type"] == "incremental" and a.get("mode") == "filename":
        pats = a.get("filename_patterns") or {}
        if not pats or any(k not in ACTIONS for k in pats):
            errs.append("action.filename_patterns must map add/update/close to a pattern")
        for k, pat in pats.items():
            try:
                re.compile(pat)
            except re.error as e:
                errs.append(f"filename pattern for {k} is not a valid regex: {e}")
    if p["blank_means"] not in ("no_change", "clear"):
        errs.append("blank_means must be no_change or clear")
    s = p["sequence"]
    if s.get("source") not in ("filename", "column", "none"):
        errs.append("sequence.source must be filename, column or none")
    if s.get("kind") not in ("integer", "date"):
        errs.append("sequence.kind must be integer or date")
    if s.get("source") == "filename":
        try:
            rx = re.compile(s.get("pattern") or "")
            if rx.groups != 1:
                errs.append("sequence.pattern needs exactly one capture group")
        except re.error as e:
            errs.append(f"sequence.pattern is not a valid regex: {e}")
    if s.get("source") == "column" and not s.get("column"):
        errs.append("sequence.column is required for source=column")
    unknown = [f for f in list(p["protected_fields"]) + list(p.get("set_once_fields") or []) if f not in BY_NAME]
    if unknown:
        errs.append(f"unknown fields in protected/set-once lists: {unknown[:5]}")
    sn = p["snapshot"]
    if sn.get("missing_action") not in ("review", "ignore"):
        errs.append("snapshot.missing_action must be review or ignore")
    try:
        if not 0 <= float(sn.get("max_missing_pct", 5)) <= 100:
            errs.append("snapshot.max_missing_pct must be 0-100")
    except (TypeError, ValueError):
        errs.append("snapshot.max_missing_pct must be a number")
    return errs


def file_action(profile: dict, filename: str) -> str | None:
    """mode=filename: the action every row of this file carries (None if no pattern matches)."""
    a = profile["action"]
    if profile["load_type"] != "incremental" or a.get("mode") != "filename":
        return None
    for act, pat in (a.get("filename_patterns") or {}).items():
        if re.search(pat, filename or "", re.IGNORECASE):
            return act
    return None


def _norm_seq(raw: str, kind: str) -> str:
    raw = str(raw).strip()
    if kind == "integer":
        if not raw.isdigit():
            raise DeliveryError(f"sequence '{raw}' is not a number")
        return raw.lstrip("0").zfill(12) if raw.strip("0") else "0".zfill(12)
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y", "%m%d%Y", "%Y%m%d%H%M%S", "%Y%m%d%H%M"):
        try:
            d = datetime.strptime(raw, fmt)
            return d.strftime("%Y-%m-%dT%H:%M:%S") if fmt.endswith(("%S", "%M")) else d.strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise DeliveryError(f"sequence '{raw}' is not a recognisable date")


def extract_sequence(profile: dict, filename: str, first_row: dict | None) -> str | None:
    """Sortable sequence for a file, or None when the source is not sequenced."""
    s = profile["sequence"]
    if s.get("source") == "filename":
        m = re.search(s.get("pattern") or "", filename or "")
        if not m:
            raise DeliveryError(f"filename '{filename}' does not contain a sequence (pattern {s.get('pattern')})")
        return _norm_seq(m.group(1), s.get("kind", "integer"))
    if s.get("source") == "column":
        val = (first_row or {}).get(s.get("column"))
        if val in (None, ""):
            raise DeliveryError(f"sequence column '{s.get('column')}' is empty in the first row")
        return _norm_seq(val, s.get("kind", "date"))
    return None


def display_sequence(seq: str | None) -> str | None:
    if seq is None:
        return None
    return seq.lstrip("0") or "0" if seq.isdigit() else seq


def next_integer(seq: str) -> str:
    return str(int(seq) + 1).zfill(12)


def is_protected_change(profile: dict, field: str, merged: dict) -> bool:
    if profile.get("_protect_all"):  # out-of-order file applied by override: every change gets a checker
        return True
    if field not in profile["protected_fields"]:
        return False
    return not (field in ARM_ROUTINE and str(merged.get("amortization_type") or "").upper() == "ARM")


def norm(v):
    """Comparable form of a field value (mapped record vs. typed SSE row)."""
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    if hasattr(v, "is_finite"):  # Decimal
        return round(float(v), 6)
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == datetime.min.time() else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def jsonable(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10] if not isinstance(v, datetime) or v.time() == datetime.min.time() else v.isoformat()
    if hasattr(v, "is_finite"):
        return float(v)
    return v


# ------------------------------------------------------------------ maker-checker on the profile
def propose_profile(source_id: str, profile: dict, actor: str, roles: list[str]) -> dict:
    from sqlalchemy import select

    from ..store import db

    if not set(roles) & {"analyst", "sme", "admin"}:
        raise DeliveryError("Analyst or SME role required")
    with db.get_engine().begin() as c:
        src = c.execute(select(db.sources).where(db.sources.c.source_id == source_id)).first()
        if not src:
            raise DeliveryError("unknown source")
        cols = [col["name"] for col in (src.profile or {}).get("columns", [])] or None
        errs = validate_profile(profile, cols)
        if errs:
            raise DeliveryError("; ".join(errs))
        clean = {k: v for k, v in profile_of(profile).items() if not k.startswith("_")}
        c.execute(db.sources.update().where(db.sources.c.source_id == source_id).values(delivery_draft=clean, delivery_proposed_by=actor))
        db.audit(c, actor, "source.delivery_propose", "source", source_id, {"profile": clean})
    return {"source_id": source_id, "delivery_draft": clean, "proposed_by": actor}


def decide_profile(source_id: str, actor: str, roles: list[str], approve: bool, comment: str | None = None) -> dict:
    from sqlalchemy import select

    from ..store import db

    if not set(roles) & {"sme", "admin"}:
        raise DeliveryError("SME role required")
    with db.get_engine().begin() as c:
        src = c.execute(select(db.sources).where(db.sources.c.source_id == source_id).with_for_update()).first()
        if not src or not src.delivery_draft:
            raise DeliveryError("no delivery profile change is awaiting approval")
        if actor == src.delivery_proposed_by:
            raise DeliveryError("maker-checker: the approver must be a different user from the proposer")
        vals = {"delivery_draft": None, "delivery_proposed_by": None}
        if approve:
            vals["delivery"] = src.delivery_draft
            old_seq = profile_of(src.delivery)["sequence"]
            new_seq = profile_of(src.delivery_draft)["sequence"]
            if (old_seq.get("source"), old_seq.get("kind")) != (new_seq.get("source"), new_seq.get("kind")):
                vals["last_sequence"] = None  # a new numbering scheme starts its own cursor
        c.execute(db.sources.update().where(db.sources.c.source_id == source_id).values(**vals))
        db.audit(c, actor, "source.delivery_approve" if approve else "source.delivery_reject", "source", source_id,
                 {"comment": comment, **({"profile": src.delivery_draft} if approve else {})})
    if approve and src.active_mapping_id:
        from ..config_store import publish

        publish(source_id, actor, "delivery profile approved")
    return {"source_id": source_id, "approved": approve}
