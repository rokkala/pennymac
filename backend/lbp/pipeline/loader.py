"""SSE target loader: micro-batched, throttled upserts into the typed SSE loan table.

Throttling (LBP_SSE_THROTTLE_RPS) protects the live SSE database during large imports;
in AWS the same limit is enforced per Step Functions Map iteration via MaxConcurrency.
"""
from __future__ import annotations

import threading
import time
from datetime import date

from sqlalchemy import delete

from ..config import get_settings
from ..schema.sse_target import ATTRIBUTES
from ..store import db

_DATE_FIELDS = {a.name for a in ATTRIBUTES if a.dtype == "date"}
_COLUMNS = {a.name for a in ATTRIBUTES}


class TokenBucket:
    def __init__(self, rate_per_sec: int):
        self.rate = rate_per_sec
        self.tokens = float(rate_per_sec)
        self.last = time.monotonic()
        self.lock = threading.Lock()

    def take(self, n: int) -> None:
        if self.rate <= 0:
            return
        with self.lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.rate, self.tokens + (now - self.last) * self.rate)
                self.last = now
                if self.tokens >= min(n, self.rate):
                    self.tokens -= min(n, self.rate)
                    n -= min(n, self.rate)
                    if n <= 0:
                        return
                else:
                    time.sleep((min(n, self.rate) - self.tokens) / self.rate)


_bucket: TokenBucket | None = None


def _get_bucket() -> TokenBucket:
    global _bucket
    if _bucket is None or _bucket.rate != get_settings().sse_throttle_rps:
        _bucket = TokenBucket(get_settings().sse_throttle_rps)
    return _bucket


def to_sse_row(rec: dict, batch_id: str, dq_status: str, source_id: str | None = None) -> dict:
    row = {}
    for k, v in rec.items():
        if k not in _COLUMNS:
            continue
        if k in _DATE_FIELDS and isinstance(v, str) and v:
            try:
                v = date.fromisoformat(v[:10])
            except ValueError:
                v = None
        row[k] = v
    row["lbp_batch_id"] = batch_id
    row["lbp_boarded_at"] = db.now()
    row["lbp_dq_status"] = dq_status
    row["lbp_source_id"] = source_id
    row["lbp_status"] = "active"
    row["lbp_version"] = 1
    return row


def _write(conn, rows: list[dict]) -> None:
    """Insert, or replace a whole record (a full tape re-boarding an existing loan after DUP02 approval).
    A replacement keeps the loan's version history moving forward and is logged in loan_changes."""
    from sqlalchemy import select

    from .changes import masked_changes
    from .delivery import norm

    keys = [r["loan_number"] for r in rows]
    t = db.sse_loans
    existing = {}
    for i in range(0, len(keys), 900):
        for r in conn.execute(select(t).where(t.c.loan_number.in_(keys[i:i + 900]))):
            existing[r.loan_number] = dict(r._mapping)
    if existing:
        log = []
        for r in rows:
            old = existing.get(r["loan_number"])
            if not old:
                continue
            r["lbp_version"] = (old.get("lbp_version") or 1) + 1
            r["lbp_boarded_at"] = old.get("lbp_boarded_at") or r["lbp_boarded_at"]
            r["lbp_updated_at"] = db.now()
            r["lbp_source_id"] = r.get("lbp_source_id") or old.get("lbp_source_id")
            diff = {k: {"old": old.get(k), "new": v} for k, v in r.items()
                    if k in _COLUMNS and norm(old.get(k)) != norm(v)}
            log.append({"batch_id": r["lbp_batch_id"], "source_id": r.get("lbp_source_id"), "loan_number": r["loan_number"],
                        "action": "replace", "changes": masked_changes(diff), "base_version": old.get("lbp_version"),
                        "applied_version": r["lbp_version"], "status": "applied", "actor": "pipeline", "created_at": db.now()})
        ks = list(existing)
        for i in range(0, len(ks), 900):
            conn.execute(delete(t).where(t.c.loan_number.in_(ks[i:i + 900])))
        if log:
            conn.execute(db.loan_changes.insert(), log)
    cols = set().union(*(r.keys() for r in rows))  # uniform rows for executemany
    conn.execute(t.insert(), [{c: r.get(c) for c in cols} for r in rows])


def _copy_cell(v):
    # TEXT COPY can't adapt dict/list — JSON columns need a string.
    if isinstance(v, (dict, list)):
        import json
        return json.dumps(v, default=str)
    return v


def _copy_rows(conn, table: str, cols: list[str], payload: list[dict]) -> bool:
    """True if Postgres COPY succeeded. False = caller should executemany (SQLite / no driver)."""
    if conn.engine.dialect.name != "postgresql":
        return False
    raw = conn.connection.driver_connection
    with raw.cursor() as cur:
        with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as copy:
            for r in payload:
                copy.write_row([_copy_cell(r.get(c)) for c in cols])
    return True


def copy_insert_loans(conn, rows: list[dict]) -> None:
    """Insert brand-new SSE loan rows. Uses Postgres COPY when available; else executemany."""
    if not rows:
        return
    cols = [c.name for c in db.sse_loans.columns]
    payload = [{c: r.get(c) for c in cols} for r in rows]
    if not _copy_rows(conn, "sse_loans", cols, payload):
        conn.execute(db.sse_loans.insert(), payload)


def copy_insert_staging(conn, rows: list[dict]) -> None:
    """Bulk-insert slim staging rows (no autoincrement id — DB fills it)."""
    if not rows:
        return
    cols = ["batch_id", "row_number", "loan_number", "status", "record", "raw", "transform_errors",
            "boarded", "action", "changes", "base_version"]
    payload = [{c: r.get(c) for c in cols} for r in rows]
    if not _copy_rows(conn, "loans_staging", cols, payload):
        conn.execute(db.loans_staging.insert(), payload)


_EXCEPTION_COLS = [c.name for c in db.exceptions.columns]


def copy_insert_exceptions(conn, rows: list[dict]) -> None:
    """Bulk-insert exception tickets. Uses Postgres COPY when available; else executemany."""
    if not rows:
        return
    payload = [{c: r.get(c) for c in _EXCEPTION_COLS} for r in rows]
    if not _copy_rows(conn, "exceptions", _EXCEPTION_COLS, payload):
        conn.execute(db.exceptions.insert(), payload)


def load_records(conn, records: list[tuple[dict, str]], batch_id: str, failures: list | None = None,
                 source_id: str | None = None) -> int:
    """Upsert [(sse_record, dq_status)] by loan_number. Returns rows written.

    With `failures` given, a database rejection of the micro-batch does not fail the batch: the
    rows are retried one by one inside savepoints and each rejected loan is appended to
    `failures` as (loan_number, error) for the caller to turn into an exception.
    """
    rows = [to_sse_row(r, batch_id, s, source_id) for r, s in records if r.get("loan_number")]
    if not rows:
        return 0
    _get_bucket().take(len(rows))
    if failures is None:
        _write(conn, rows)
        return len(rows)
    from sqlalchemy.exc import DBAPIError

    try:
        with conn.begin_nested():
            _write(conn, rows)
        return len(rows)
    except DBAPIError:
        pass
    ok = 0
    for r in rows:
        try:
            with conn.begin_nested():
                _write(conn, [r])
            ok += 1
        except DBAPIError as e:
            failures.append((r["loan_number"], str(getattr(e, "orig", e)).splitlines()[0][:300]))
    return ok
