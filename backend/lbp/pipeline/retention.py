"""Data minimisation for staging (GLBA safeguards).

Once a loan is boarded (or the row is rejected), SSE is the system of record. Staging keeps the raw source row and the
typed record only as long as investigations and replays need them. After the retention period
this job removes the raw row and the change delta (old/new values) and masks NPI in the staged
record. The loan change log (loan_changes) is stored masked from the start. Exceptions and the audit trail
are kept (exception values are already masked in every API view).
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import null, or_, select

from ..ingestion.pii import TARGET_PII_TYPES, mask_record
from ..store import db


def purge_staging_npi(older_than_days: int, actor: str, batch_size: int = 5000) -> dict:
    cutoff = db.now() - timedelta(days=older_than_days)
    st = db.loans_staging
    purged = 0
    with db.get_engine().begin() as c:
        while True:
            rows = c.execute(select(st.c.id, st.c.record).where(
                or_(st.c.boarded.is_(True), st.c.status.in_(("REJECTED", "UNCHANGED"))), st.c.updated_at < cutoff,
                or_(st.c.raw.is_not(None), st.c.changes.is_not(None)))
                .limit(batch_size)).all()
            if not rows:
                break
            for r in rows:
                c.execute(st.update().where(st.c.id == r.id).values(raw=null(), changes=null(),
                                                                    record=mask_record(r.record or {}, TARGET_PII_TYPES, "hash")))
            purged += len(rows)
        db.audit(c, actor, "retention.purge", "staging", "loans_staging", {"older_than_days": older_than_days, "rows": purged})
    return {"purged_rows": purged, "older_than_days": older_than_days, "cutoff": cutoff.isoformat() + "Z"}
