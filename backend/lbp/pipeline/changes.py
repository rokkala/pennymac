"""Apply incremental changes to SSE safely.

Updates write only the fields that changed, under column-level optimistic concurrency:

  * Every SSE row carries `lbp_version`. A delta records the version it was computed against.
  * At write time the live rows are read under a row lock. If the version moved (an exception for
    an older file was resolved, another vendor touched the loan, an operator corrected it), the
    delta is *rebased*: a field is only a conflict if the live value differs from both the value
    the vendor saw (old) and the value the vendor sent (new). Non-overlapping changes merge.
  * Conflicts are held as CHG05 exceptions for a person to decide; nothing is silently overwritten.

Closes mark the loan closed (status, date, reason) and never delete it. Every applied change is
written to `loan_changes` with NPI masked.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import bindparam, select

from ..ingestion.pii import TARGET_PII_TYPES, mask_value
from ..schema.sse_target import ATTRIBUTES
from ..store import db
from .delivery import jsonable, norm

_DATE_FIELDS = {a.name for a in ATTRIBUTES if a.dtype == "date"}
_COLUMNS = {a.name for a in ATTRIBUTES}


def masked_changes(changes: dict) -> dict:
    out = {}
    for f, ch in changes.items():
        old, new = jsonable(ch.get("old")), jsonable(ch.get("new"))
        if f in TARGET_PII_TYPES:
            kind = TARGET_PII_TYPES[f]
            old = mask_value(str(old), kind) if old not in (None, "") else old
            new = mask_value(str(new), kind) if new not in (None, "") else new
        out[f] = {"old": old, "new": new}
    return out


def _typed(field: str, v):
    from datetime import date

    if field in _DATE_FIELDS and isinstance(v, str) and v:
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return v


def current_rows(conn, loan_numbers: list[str], lock: bool = False) -> dict[str, dict]:
    """Live SSE rows (JSON-safe values) for the given loans."""
    out: dict[str, dict] = {}
    nums = sorted({str(x) for x in loan_numbers if x not in (None, "")})
    for i in range(0, len(nums), 900):
        q = select(db.sse_loans).where(db.sse_loans.c.loan_number.in_(nums[i:i + 900]))
        if lock:
            q = q.with_for_update()
        for r in conn.execute(q):
            d = {k: jsonable(v) for k, v in r._mapping.items() if k in _COLUMNS or k in ("lbp_version", "lbp_status", "lbp_source_id")}
            out[d["loan_number"]] = d
    return out


def apply_updates(conn, items: list[dict], batch_id: str, source_id: str, actor: str = "pipeline") -> tuple[list[int], list[dict]]:
    """items: {idx, staging_id, loan_number, record, changes, base_version, dq_status, force_fields?, reopen?}
    Returns (applied idx list, conflicts [{idx, loan_number, fields: {f: {old, new, live}}}])."""
    if not items:
        return [], []
    live = current_rows(conn, [it["loan_number"] for it in items], lock=True)
    applied, conflicts, log_rows = [], [], []
    groups: dict[tuple, list[dict]] = defaultdict(list)
    now = db.now()
    for it in items:
        ln = it["loan_number"]
        cur = live.get(ln)
        if cur is None or (cur.get("lbp_status") == "closed" and not it.get("reopen")):
            conflicts.append({"idx": it["idx"], "loan_number": ln, "fields": {}, "reason": "loan is no longer active in SSE" if cur else "loan is no longer in SSE"})
            continue
        force = set(it.get("force_fields") or ())
        write, clash = {}, {}
        for f, ch in (it["changes"] or {}).items():
            if f.startswith("lbp_") or f not in _COLUMNS:
                continue
            lv = norm(cur.get(f))
            if lv == norm(ch["new"]):
                continue  # already there (e.g. the same correction arrived another way)
            if f not in force and (cur.get("lbp_version") or 1) != (it.get("base_version") or 1) and lv != norm(ch["old"]):
                clash[f] = {"old": ch["old"], "new": ch["new"], "live": cur.get(f)}
                continue
            write[f] = ch["new"]
        if clash:
            conflicts.append({"idx": it["idx"], "loan_number": ln, "fields": clash, "reason": "changed in SSE since the vendor's file was produced"})
            continue
        extra = {"lbp_status": "active", "lbp_closed_at": None, "lbp_close_reason": None} if it.get("reopen") else {}
        if it.get("reassign_source") and it["reassign_source"] != cur.get("lbp_source_id"):
            extra["lbp_source_id"] = it["reassign_source"]  # approved servicing transfer between vendors
        if write or extra:
            groups[tuple(sorted(write)) + tuple(sorted(extra))].append(
                {"b_ln": ln, **{f"v_{k}": _typed(k, v) for k, v in write.items()}, **{f"v_{k}": v for k, v in extra.items()},
                 "v_dq": it.get("dq_status")})
            new_version = (cur.get("lbp_version") or 1) + 1
            ch_log = {f: {"old": cur.get(f), "new": v} for f, v in write.items()}
            if it.get("reopen"):
                ch_log["lbp_status"] = {"old": "closed", "new": "active"}
            if "lbp_source_id" in extra:
                ch_log["lbp_source_id"] = {"old": cur.get("lbp_source_id"), "new": extra["lbp_source_id"]}
            log_rows.append({"batch_id": batch_id, "source_id": source_id, "loan_number": ln, "staging_id": it.get("staging_id"),
                             "action": "update", "changes": masked_changes(ch_log), "base_version": it.get("base_version"),
                             "applied_version": new_version, "status": "applied", "actor": actor, "created_at": now})
        applied.append(it["idx"])
    t = db.sse_loans
    for cols, params in groups.items():
        stmt = (t.update().where(t.c.loan_number == bindparam("b_ln"))
                .values({**{c: bindparam(f"v_{c}") for c in cols}, "lbp_version": t.c.lbp_version + 1, "lbp_updated_at": now,
                         "lbp_dq_status": bindparam("v_dq")}))
        conn.execute(stmt, params)
    if log_rows:
        conn.execute(db.loan_changes.insert(), log_rows)
    return applied, conflicts


def apply_closes(conn, items: list[dict], batch_id: str, source_id: str, actor: str = "pipeline") -> tuple[list[int], list[dict]]:
    """items: {idx, staging_id, loan_number, close_reason}. Closing an already-closed loan is a no-op success."""
    if not items:
        return [], []
    live = current_rows(conn, [it["loan_number"] for it in items], lock=True)
    t, now = db.sse_loans, db.now()
    applied, conflicts, log_rows, params = [], [], [], []
    for it in items:
        cur = live.get(it["loan_number"])
        if cur is None:
            conflicts.append({"idx": it["idx"], "loan_number": it["loan_number"], "fields": {}, "reason": "loan is no longer in SSE"})
            continue
        applied.append(it["idx"])
        if cur.get("lbp_status") == "closed":
            continue
        params.append({"b_ln": it["loan_number"], "v_reason": (it.get("close_reason") or "closed")[:60]})
        log_rows.append({"batch_id": batch_id, "source_id": source_id, "loan_number": it["loan_number"], "staging_id": it.get("staging_id"),
                         "action": "close", "changes": {"lbp_status": {"old": "active", "new": "closed"},
                                                        "lbp_close_reason": {"old": None, "new": it.get("close_reason")}},
                         "base_version": cur.get("lbp_version"), "applied_version": (cur.get("lbp_version") or 1) + 1,
                         "status": "applied", "actor": actor, "created_at": now})
    if params:
        conn.execute(t.update().where(t.c.loan_number == bindparam("b_ln"), t.c.lbp_status != "closed").values(
            lbp_status="closed", lbp_closed_at=now, lbp_close_reason=bindparam("v_reason"), lbp_version=t.c.lbp_version + 1,
            lbp_updated_at=now), params)
        conn.execute(db.loan_changes.insert(), log_rows)
    return applied, conflicts


def conflict_failures(conflict: dict) -> list[dict]:
    from .incremental import CHANGE_RULES

    if not conflict["fields"]:
        return [{"rule_id": "CHG05", "version": 1, "name": CHANGE_RULES["CHG05"], "field": "lbp_status", "category": "change_control",
                 "severity": "FAIL", "message": f"Change not applied: {conflict['reason']}.", "regulatory_tag": "SOX"}]
    return [{"rule_id": "CHG05", "version": 1, "name": CHANGE_RULES["CHG05"], "field": f, "category": "change_control", "severity": "FAIL",
             "message": f"{f}: vendor changed '{v['old']}' to '{v['new']}', but SSE now holds '{v['live']}' ({conflict['reason']}). "
                        "Choose the value to keep.", "regulatory_tag": "SOX",
             "live": jsonable(v["live"]), "vendor": jsonable(v["new"]), "old": jsonable(v["old"])}
            for f, v in conflict["fields"].items()]
