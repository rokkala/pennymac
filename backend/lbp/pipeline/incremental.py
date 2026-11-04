"""Incremental and snapshot row planning (pure; runs inside the pipeline worker processes).

For every mapped row the planner decides what the row means for the loan already in SSE:

    add        new loan; validated like a boarding tape (DUP02 still protects existing loans)
    update     the vendor's delta is merged onto the current SSE record and the *merged* record is
               validated, so sparse rows (loan number + changed fields) work. Only fields that
               actually changed are written later, under optimistic concurrency (changes.py).
    close      payoff / transfer out / charge-off: the SSE record is marked closed, never deleted
    unchanged  the row matches SSE exactly; nothing is written (counted in reconciliation)

Guardrails raised as exceptions (same Exception Manager, same tiers):
    ACT01  unrecognised action code                         -> held
    CHG01  change to a protected field                      -> dual control (T4), vendor value proposed
    CHG02  update/close for a loan that is not in SSE       -> held; reviewer can correct the loan number
    CHG03  update for a loan that SSE has closed            -> held; reviewer may reopen
A rule that already failed on the boarded record and is not touched by this change does not block
the update (it is counted, not re-raised): a vendor's balance update is not held hostage by an old
data issue it did not cause.
"""
from __future__ import annotations

from .delivery import is_protected_change, norm

CHANGE_RULES = {
    "ACT01": "Unrecognised action code",
    "CHG01": "Protected field change needs dual control",
    "CHG02": "Change for a loan that is not in SSE",
    "CHG03": "Change for a loan that is closed in SSE",
    "CHG04": "Loan missing from vendor snapshot",
    "CHG05": "Concurrent change conflict",
    "CHG06": "Loan belongs to another vendor",
}


def _fail(rule_id, field, message, category="change_control", severity="FAIL"):
    return {"rule_id": rule_id, "version": 1, "name": CHANGE_RULES[rule_id], "field": field, "category": category,
            "severity": severity, "message": message, "regulatory_tag": "SOX"}


def resolve_action(raw: dict, profile: dict, file_action: str | None, exists: bool, closed: bool) -> tuple[str | None, str | None]:
    """(action, code) where action is None for an unrecognised code."""
    if profile["load_type"] == "snapshot":
        return ("update" if exists else "add"), None
    a = profile["action"]
    mode = a.get("mode", "upsert")
    if mode == "column":
        code = str(raw.get(a.get("column")) or "").strip()
        values = {str(k).strip().upper(): v for k, v in (a.get("values") or {}).items()}
        return values.get(code.upper()), code
    if mode == "filename" and file_action:
        return file_action, None
    return ("update" if exists else "add"), None


def same_value(a, b) -> bool:
    if norm(a) == norm(b):
        return True
    try:
        return a not in (None, "") and b not in (None, "") and abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip().upper() == str(b).strip().upper()


def plan_row(raw: dict, rec: dict, terrs: dict, current: dict | None, profile: dict, file_action: str | None,
             clear_targets: set[str], corrections: dict | None = None, vendor_feeds: list[str] | None = None) -> dict:
    """Decide the row's action and build the record to validate. Returns
    {action, record, delta_fields, changes, base_version, fails, close_reason, skip_rules}."""
    exists = current is not None
    closed = exists and current.get("lbp_status") == "closed"
    action, code = resolve_action(raw, profile, file_action, exists, closed)
    out = {"action": action, "record": rec, "delta_fields": [], "changes": {}, "base_version": None, "fails": [],
           "close_reason": None, "skip_rules": False, "base_values": {}, "set_once_ignored": 0, "corrections_kept": 0}
    ln = rec.get("loan_number")
    if action is None:
        out["action"] = "update" if exists else "add"
        out["fails"].append(_fail("ACT01", "loan_number", f"Action code '{code}' is not mapped for this vendor "
                                  f"(known: {', '.join(sorted((profile['action'].get('values') or {}).keys())) or 'none'})"))
        out["skip_rules"] = True
        return out
    if action == "add":
        if closed and profile["load_type"] == "snapshot":
            out["action"] = "update"
            out["fails"].append(_fail("CHG03", "lbp_status", f"Loan {ln} is closed in SSE but is in the vendor's snapshot. "
                                      "Reopen it only if the closure was wrong."))
            out["skip_rules"] = True
        return out
    if not exists:
        if action == "update":  # keep the delta so a corrected loan number can still be applied
            out["delta_fields"] = sorted(k for k, v in rec.items() if k != "loan_number" and norm(v) is not None)
            out["base_values"] = {}
        out["fails"].append(_fail("CHG02", "loan_number", f"Vendor sent a{'n update' if action == 'update' else ' close'} for loan "
                                  f"{ln}, which is not in SSE. Correct the loan number if it is a typo, otherwise reject."))
        out["skip_rules"] = True
        return out
    owner = current.get("lbp_source_id")
    if vendor_feeds is not None and owner and owner not in vendor_feeds:
        out["fails"].append(_fail("CHG06", "loan_number", f"Loan {ln} is boarded under another vendor. A vendor's file can only change "
                                  "its own loans; approve only for a documented servicing transfer."))
        out["skip_rules"] = True
        out["base_version"] = current.get("lbp_version") or 1
        if action == "update":
            base = {k: v for k, v in current.items() if not k.startswith("lbp_")}
            delta = {k: v for k, v in rec.items() if k != "loan_number" and k not in terrs and norm(v) is not None}
            out["delta_fields"] = sorted(k for k, v in delta.items() if norm(base.get(k)) != norm(v))
            out["base_values"] = {f: base.get(f) for f in out["delta_fields"]}
            out["record"] = {**base, **delta, "loan_number": ln}
        return out
    base = {k: v for k, v in current.items() if not k.startswith("lbp_")}
    out["base_version"] = current.get("lbp_version") or 1
    if action == "close":
        if closed:
            out["action"] = "unchanged"
            out["record"] = base
            return out
        out["record"] = base
        out["close_reason"] = (code or "closed")[:60]
        out["changes"] = {"lbp_status": {"old": "active", "new": "closed"}}
        out["skip_rules"] = True
        return out
    # ---- update: merge the delta onto the boarded record
    if profile["blank_means"] == "clear":
        delta = {k: v for k, v in rec.items() if k != "loan_number" and k not in terrs}
    else:
        delta = {k: v for k, v in rec.items() if k != "loan_number" and k not in terrs and norm(v) is not None}
    for t in clear_targets:
        delta[t] = None
    # A value a person (or an approved auto-fix) already corrected on this loan, re-sent unchanged by the
    # vendor, is the same defect again, not a change: keep the corrected SSE value.
    corrections = corrections or {}
    kept = [k for k, v in delta.items() if k in corrections.get(str(ln), {}) and same_value(v, corrections[str(ln)][k])
            and not same_value(v, base.get(k))]
    delta = {k: v for k, v in delta.items() if k not in kept}
    out["corrections_kept"] = len(kept)
    set_once = set(profile.get("set_once_fields") or ())
    ignored = sorted(k for k in delta if k in set_once and norm(delta[k]) != norm(base.get(k)))
    delta = {k: v for k, v in delta.items() if k not in set_once}
    out["set_once_ignored"] = len(ignored)
    merged = {**base, **delta, "loan_number": ln}
    for k in terrs:  # keep the failed field visible to the exception (value is None from the mapper)
        merged.setdefault(k, None)
    changes = {k: {"old": base.get(k), "new": v} for k, v in delta.items() if norm(base.get(k)) != norm(v)}
    out["record"] = merged
    out["delta_fields"] = sorted(set(changes) | set(terrs))
    out["changes"] = changes
    out["base_values"] = {f: base.get(f) for f in out["delta_fields"]}
    if closed:
        out["fails"].append(_fail("CHG03", "lbp_status", f"Vendor updated loan {ln}, which is closed in SSE. "
                                  "Reopen it only if the closure was wrong."))
        out["skip_rules"] = True
        return out
    if not changes and not terrs:
        out["action"] = "unchanged"
        return out
    for f, ch in changes.items():
        if is_protected_change(profile, f, merged):
            out["fails"].append(_fail("CHG01", f, f"{f} changed from '{ch['old']}' to '{ch['new']}'. "
                                      "Protected fields need a maker and a checker."))
    return out


def preexisting_filter(fails: list[dict], base_failures: set[tuple[str, str]], delta_fields: list[str]) -> tuple[list[dict], int]:
    """Drop failures that already existed on the boarded record and that this change does not touch.

    They are not the vendor's change, so they neither block it nor raise a fresh exception on every
    update; they are counted (change_summary.preexisting_issues) and stay visible in the DQ scorecard.
    """
    out, touched, dropped = [], set(delta_fields), 0
    for f in fails:
        if (f["rule_id"], f["field"]) in base_failures and f["field"] not in touched:
            dropped += 1
        else:
            out.append(f)
    return out, dropped


def feeds_by_column(fields: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in fields:
        if f.get("status", "accepted") in ("rejected",) or not f.get("target"):
            continue
        for s in f.get("sources") or ([f["source"]] if f.get("source") else []):
            out.setdefault(s, []).append(f["target"])
    return out
