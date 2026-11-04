"""Replay held loans after a mapping or rule fix.

When one mapping defect produces hundreds of exceptions (a wrong date format, an untranslated
code), the right fix is the mapping, not hundreds of manual edits. After the SME approves the
corrected mapping version, replay re-reads the held rows from the original file, applies the
source's current mapping and rule set, carries over values reviewers already corrected, and:

  * boards loans that now pass,
  * supersedes their old exceptions (kept for audit, status 'superseded'),
  * re-triages anything still failing.

dry_run=True returns the outcome without writing anything, so it can be previewed first.
"""
from __future__ import annotations

from sqlalchemy import and_, select

from ..exceptions.manager import OPEN_STATES, Triage, _coerce, _str
from ..ingestion.parser import ParseOptions, iter_rows
from ..rules.executor import RuleExecutor
from ..store import db
from .batch import _exception_rows, _insert_exceptions, _mask_raw, _triage_results, detect_duplicates, process_chunk
from .loader import load_records


def replay_batch(batch_id: str, actor: str, dry_run: bool = False) -> dict:
    eng = db.get_engine()
    with eng.connect() as c:
        b = c.execute(select(db.batches).where(db.batches.c.batch_id == batch_id)).first()
        if not b:
            raise ValueError("batch not found")
        if b.status in ("running", "pausing", "queued", "claimed"):
            raise ValueError("wait for the batch to finish before replaying")
        if (b.load_type or "full") != "full":
            raise ValueError("replay re-boards whole records, so it applies to full tapes only. Held rows from change files are "
                             "resolved in the Exception Manager, where each change is re-applied onto the live SSE record.")
        src = c.execute(select(db.sources).where(db.sources.c.source_id == b.source_id)).first()
        from types import SimpleNamespace

        from ..config_store import load as load_config

        cfg = load_config(b.source_id)  # replays run on the feed's published configuration, like every Glue run
        m = SimpleNamespace(mapping_id=cfg.mapping_id, version=cfg.mapping_version, fields=cfg.fields)
        held = {r.row_number: r for r in c.execute(select(db.loans_staging).where(
            db.loans_staging.c.batch_id == batch_id, db.loans_staging.c.boarded.is_(False), db.loans_staging.c.status != "REJECTED"))}
        exs = c.execute(select(db.exceptions).where(db.exceptions.c.batch_id == batch_id,
                                                     db.exceptions.c.staging_id.in_([r.id for r in held.values()] or [-1]))).all()
    if not held:
        return {"batch_id": batch_id, "dry_run": dry_run, "replayed": 0, "now_boarded": 0, "still_held": 0, "message": "No held loans to replay."}

    by_staging: dict[int, list] = {}
    for e in exs:
        by_staging.setdefault(e.staging_id, []).append(e)

    raws = []
    from ..storage import local_path

    _, it = iter_rows(local_path(b.file_path), ParseOptions(**(cfg.parse_options or {})))
    for i, raw in enumerate(it):
        if i in held:
            raws.append((i, raw))
    rules = cfg.runtime_set
    results = process_chunk([r for _, r in raws], m.fields, rules, 0, f"replay:{m.mapping_id}:{m.version}")
    executor = RuleExecutor(rules)
    for (row_no, _), r in zip(raws, results, strict=True):
        r["row"] = row_no
        st = held[row_no]
        prior = by_staging.get(st.id, [])
        # carry over human corrections made on this loan
        overlays = {e.field: e.resolved_value for e in prior if e.status == "resolved" and e.resolved_value is not None and e.rule_id not in ("DUP01", "DUP02")}
        if overlays:
            for f, v in overlays.items():
                try:
                    r["record"][f] = _coerce(f, v)
                except Exception:  # noqa: BLE001
                    pass
                r["terrs"].pop(f, None)
            ev = executor.evaluate(r["record"])
            r["fails"] = [{"rule_id": x.rule_id, "version": x.version, "name": x.name, "field": x.field, "category": x.category,
                           "severity": x.severity, "message": x.error or x.message, "regulatory_tag": x.regulatory_tag}
                          for x in ev.failures if x.field not in r["terrs"]]
            r["status"] = "FAIL" if r["terrs"] else ev.status
        # an unresolved in-file duplicate stays a duplicate
        if any(e.rule_id == "DUP01" and e.status in OPEN_STATES for e in prior):
            r["fails"].append({"rule_id": "DUP01", "version": 1, "name": "Duplicate loan number in this file", "field": "loan_number",
                               "category": "duplicate", "severity": "FAIL", "message": "Duplicate loan number in this file (carried over)",
                               "regulatory_tag": "SOX"})
            r["status"] = "FAIL"
    detect_duplicates(batch_id, results, check_in_batch=False)
    staged, ex_by_idx, stats = _triage_results(results, Triage())
    now_boarded = [i for i, (_, _, status) in enumerate(staged) if status in ("PASS", "WARN")]
    before_rules: dict[str, int] = {}
    for e in exs:
        if e.status in OPEN_STATES:
            before_rules[e.rule_id] = before_rules.get(e.rule_id, 0) + 1
    after_rules: dict[str, int] = {}
    for v in ex_by_idx.values():
        for e in v:
            if e["status"] != "auto_applied":
                after_rules[e["rule_id"]] = after_rules.get(e["rule_id"], 0) + 1
    summary = {
        "batch_id": batch_id, "dry_run": dry_run, "mapping_id": m.mapping_id, "mapping_version": m.version,
        "replayed": len(staged), "now_boarded": len(now_boarded), "still_held": len(staged) - len(now_boarded),
        "exceptions_before": sum(before_rules.values()), "exceptions_after": sum(after_rules.values()),
        "by_rule_before": dict(sorted(before_rules.items(), key=lambda x: -x[1])),
        "by_rule_after": dict(sorted(after_rules.items(), key=lambda x: -x[1])),
        "examples": [{"loan_number": _str(staged[i][1].get("loan_number")),
                      "was": sorted({e.rule_id for e in by_staging.get(held[staged[i][0]["row"]].id, []) if e.status in OPEN_STATES}),
                      "now": "boards" if i in now_boarded else sorted({e["rule_id"] for e in ex_by_idx.get(i, [])})} for i in range(min(12, len(staged)))],
    }
    if dry_run:
        return summary

    pii_cols = cfg.pii_cols
    with eng.begin() as c:
        ids = [held[r["row"]].id for r, _, _ in staged]
        c.execute(db.exceptions.update().where(and_(db.exceptions.c.staging_id.in_(ids), db.exceptions.c.status.in_(OPEN_STATES)))
                  .values(status="superseded", resolved_at=db.now(), checker=f"replay:{actor}"))
        for (r, rec, status), sid in zip(staged, ids, strict=True):
            c.execute(db.loans_staging.update().where(db.loans_staging.c.id == sid).values(
                record=rec, status=status, transform_errors=r["terrs"], raw=_mask_raw(r["raw"], pii_cols),
                boarded=status in ("PASS", "WARN"), updated_at=db.now()))
        _insert_exceptions(c, _exception_rows(batch_id, src.source_id, ex_by_idx, [_str(rec.get("loan_number")) for _, rec, _ in staged], ids))
        loaded = load_records(c, [(rec, status) for _, rec, status in staged if status in ("PASS", "WARN")], batch_id)
        hist = list(b.replays or []) + [{"ts": db.now().isoformat(), "actor": actor, "mapping_version": m.version,
                                          "replayed": len(staged), "now_boarded": loaded, "still_held": len(staged) - loaded}]
        bt = db.batches
        c.execute(bt.update().where(bt.c.batch_id == batch_id).values(
            loaded=bt.c.loaded + loaded, failed=bt.c.failed - loaded, passed=bt.c.passed + stats["passed"],
            warned=bt.c.warned + stats["warned"], replays=hist))
        from .batch import reconcile

        rec = reconcile(c, batch_id, b.processed or b.total_rows or 0)
        c.execute(bt.update().where(bt.c.batch_id == batch_id).values(reconciliation=rec))
        db.audit(c, actor, "batch.replay", "batch", batch_id, {k: summary[k] for k in ("mapping_version", "replayed", "now_boarded", "still_held")})
    summary["now_boarded"] = loaded
    return summary
