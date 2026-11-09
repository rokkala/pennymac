"""Workflow 1 - New Source Onboarding.

  1 analyst uploads a sample file        -> register_source()
  2 schema profiled                      -> (inside register_source)
  3 AI suggests mappings + confidence    -> (inside register_source, mapping draft v1)
  4 analyst accepts / rejects / overrides -> update_field(), add_field()
     + validation preview before loading  -> preview()
  5 SME approves                         -> submit() then approve()  (maker-checker)
  6 config saved, source is live         -> source.active_mapping_id set
"""
from __future__ import annotations

import copy
from pathlib import Path

from sqlalchemy import select

from ..ai import LLMMappingReranker, get_llm
from ..ingestion.parser import ParseOptions, read_sample
from ..ingestion.pii import TARGET_PII_TYPES, mask_record
from ..ingestion.profiler import profile_rows
from ..rules.executor import RuleExecutor
from ..rules.registry import RuleRegistry
from ..schema.sse_target import BY_NAME
from ..store import db
from .engine import suggest_mappings
from .transforms import compile_mapping


class MappingError(ValueError):
    pass


# ---------------------------------------------------------------- learning loop
def load_memory() -> dict[str, list[dict]]:
    with db.get_engine().connect() as c:
        rows = c.execute(select(db.mapping_memory)).all()
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r.norm_source, []).append(dict(r._mapping))
    return out


def record_memory(c, fields: list[dict], source_name: str, actor: str) -> int:
    """On SME approval, remember every human-confirmed single-column mapping (and rejections)."""
    from .engine import normalize

    n = 0
    for f in fields:
        srcs = f.get("sources") or ([f["source"]] if f.get("source") else [])
        if len(srcs) != 1 or f.get("derived_from"):
            continue
        status = f.get("status")
        if status not in ("accepted", "overridden", "rejected"):
            continue
        norm = normalize(srcs[0])
        row = c.execute(select(db.mapping_memory).where(db.mapping_memory.c.norm_source == norm,
                                                        db.mapping_memory.c.target == f["target"])).first()
        approved = status != "rejected"
        role = "secondary" if f.get("one_to_many") else "primary"
        if row:
            names = list(dict.fromkeys([*(row.source_names or []), source_name]))[-10:]
            c.execute(db.mapping_memory.update().where(db.mapping_memory.c.id == row.id).values(
                approved_count=row.approved_count + (1 if approved else 0), rejected_count=row.rejected_count + (0 if approved else 1),
                transform=f.get("transform") if approved else row.transform, source_names=names, last_actor=actor, updated_at=db.now(),
                role="primary" if (row.role == "primary" or role == "primary") else "secondary"))
        else:
            c.execute(db.mapping_memory.insert().values(norm_source=norm, target=f["target"], transform=f.get("transform"),
                                                        example_source=srcs[0], source_names=[source_name], role=role,
                                                        approved_count=1 if approved else 0, rejected_count=0 if approved else 1,
                                                        last_actor=actor))
        n += 1
    return n


def memory_stats() -> dict:
    with db.get_engine().connect() as c:
        rows = c.execute(select(db.mapping_memory).order_by(db.mapping_memory.c.approved_count.desc())).all()
    return {"entries": len(rows), "approved_pairs": sum(1 for r in rows if r.approved_count > r.rejected_count),
            "rejected_pairs": sum(1 for r in rows if r.rejected_count >= r.approved_count and r.rejected_count),
            "items": [{"source_column": r.example_source, "target": r.target, "approved": r.approved_count, "rejected": r.rejected_count,
                       "sources": r.source_names} for r in rows[:200]]}


def diff_versions(mapping_id: str, against: str | None = None) -> dict:
    """Field-level changes between a mapping version and the previous (or a given) version."""
    with db.get_engine().connect() as c:
        m = c.execute(select(db.mappings).where(db.mappings.c.mapping_id == mapping_id)).first()
        if not m:
            raise MappingError("mapping not found")
        q = select(db.mappings).where(db.mappings.c.source_id == m.source_id)
        other = (c.execute(q.where(db.mappings.c.mapping_id == against)).first() if against
                 else c.execute(q.where(db.mappings.c.version < m.version).order_by(db.mappings.c.version.desc())).first())
    if not other:
        return {"mapping_id": mapping_id, "against": None, "changes": [], "summary": {"added": 0, "removed": 0, "changed": 0}}
    active = lambda fs: {f["target"]: f for f in fs if f.get("status") != "rejected"}  # noqa: E731
    new, old = active(m.fields), active(other.fields)
    changes = []
    for t in sorted(set(new) | set(old)):
        a, b = old.get(t), new.get(t)
        srcs = lambda f: f.get("sources") or ([f["source"]] if f.get("source") else [])  # noqa: E731
        if a and not b:
            changes.append({"target": t, "change": "removed", "before": {"sources": srcs(a), "transform": a.get("transform")}})
        elif b and not a:
            changes.append({"target": t, "change": "added", "after": {"sources": srcs(b), "transform": b.get("transform")}})
        elif srcs(a) != srcs(b) or (a.get("transform") or []) != (b.get("transform") or []):
            what = [x for x, ch in (("source", srcs(a) != srcs(b)), ("transform", (a.get("transform") or []) != (b.get("transform") or []))) if ch]
            changes.append({"target": t, "change": "changed", "what": what,
                            "before": {"sources": srcs(a), "transform": a.get("transform")},
                            "after": {"sources": srcs(b), "transform": b.get("transform")}})
    summary = {k: sum(1 for x in changes if x["change"] == k) for k in ("added", "removed", "changed")}
    return {"mapping_id": mapping_id, "version": m.version, "against": other.mapping_id, "against_version": other.version,
            "changes": changes, "summary": summary}


def register_source(name: str, file_path: Path, actor: str, description: str = "", parse_options: dict | None = None,
                    sample_rows: int = 2000, vendor_id: str | None = None) -> dict:
    """Register a feed. `vendor_id` places it under a vendor; without one, a vendor of the same name is used
    (or created), so older callers keep working."""
    opts = ParseOptions(**(parse_options or {}))
    from ..storage import local_path

    meta, rows = read_sample(local_path(file_path), sample_rows, opts)
    if not meta.columns or not rows:
        raise MappingError("file has no header or no data rows")
    from .. import vendors as vendor_svc

    if vendor_id:
        with db.get_engine().connect() as c:
            if not c.execute(select(db.vendors.c.vendor_id).where(db.vendors.c.vendor_id == vendor_id)).first():
                raise MappingError("vendor not found")
            if c.execute(select(db.sources.c.source_id).where(db.sources.c.vendor_id == vendor_id, db.sources.c.name == name)).first():
                raise MappingError(f"this vendor already has a feed named '{name}'")
    else:
        vendor_id = vendor_svc.ensure_vendor(name, actor)
    profile = profile_rows(meta.columns, rows)
    llm = get_llm()
    memory = load_memory()
    result = suggest_mappings(profile, rows, provider=LLMMappingReranker(llm) if llm.name != "heuristic" else None, memory=memory)
    result["stats"]["memory_hits"] = sum(1 for s in result["suggestions"] if (s.get("signals") or {}).get("memory"))
    sid, mid = db.new_id("src"), db.new_id("map")
    stored_opts = {"format": meta.format, "delimiter": meta.delimiter, **(parse_options or {})}
    with db.get_engine().begin() as c:
        c.execute(db.sources.insert().values(source_id=sid, vendor_id=vendor_id, name=name, description=description, format=meta.format,
                                             parse_options=stored_opts, profile=profile, sample_file=str(file_path),
                                             status="mapping", created_by=actor))
        c.execute(db.mappings.insert().values(mapping_id=mid, source_id=sid, version=1, status="draft", fields=result["suggestions"],
                                              stats={**result["stats"], "unmapped_sources": result["unmapped_sources"],
                                                     "missing_required_targets": result["missing_required_targets"]},
                                              created_by=actor, comments=[]))
        db.audit(c, actor, "source.register", "source", sid, {"name": name, "vendor_id": vendor_id, "columns": len(meta.columns),
                                                              "format": meta.format})
        db.audit(c, "ai", "mapping.suggest", "mapping", mid, result["stats"])
    return {"source_id": sid, "vendor_id": vendor_id, "mapping_id": mid, "profile": profile, **result}


def get_mapping(mapping_id: str) -> dict:
    with db.get_engine().connect() as c:
        m = c.execute(select(db.mappings).where(db.mappings.c.mapping_id == mapping_id)).first()
        if not m:
            raise MappingError("mapping not found")
        src = c.execute(select(db.sources).where(db.sources.c.source_id == m.source_id)).first()
        vname = c.execute(select(db.vendors.c.name).where(db.vendors.c.vendor_id == src.vendor_id)).scalar() if src.vendor_id else None
    out = db.row_to_dict(m)
    out["source"] = {"source_id": src.source_id, "name": src.name, "format": src.format, "status": src.status,
                     "vendor_id": src.vendor_id, "vendor_name": vname,
                     "columns": [col["name"] for col in (src.profile or {}).get("columns", [])]}
    mapped = {f["target"] for f in out["fields"] if f.get("status") not in ("rejected",)}
    out["missing_required_targets"] = [a for a in BY_NAME if BY_NAME[a].required and a not in mapped]
    return out


def _save_fields(c, mapping_id, fields, actor, action, detail):
    c.execute(db.mappings.update().where(db.mappings.c.mapping_id == mapping_id).values(fields=fields))
    db.audit(c, actor, action, "mapping", mapping_id, detail)


def _require_draft(c, mapping_id):
    m = c.execute(select(db.mappings).where(db.mappings.c.mapping_id == mapping_id)).first()
    if not m:
        raise MappingError("mapping not found")
    if m.status != "draft":
        raise MappingError(f"mapping is {m.status}; create a new version to edit")
    return m


def update_field(mapping_id: str, target: str, action: str, actor: str, source: str | None = None,
                 sources: list[str] | None = None, transform: list[dict] | None = None, default=None) -> dict:
    """action: accept | reject | override | remove"""
    if action not in ("accept", "reject", "override", "remove"):
        raise MappingError("action must be accept, reject, override or remove")
    if action == "remove":
        with db.get_engine().begin() as c:
            m = _require_draft(c, mapping_id)
            fields = [f for f in copy.deepcopy(m.fields) if f["target"] != target]
            if len(fields) == len(m.fields):
                raise MappingError(f"{target} is not in this mapping")
            _save_fields(c, mapping_id, fields, actor, "mapping.field_remove", {"target": target})
        return {"target": target, "removed": True}
    with db.get_engine().begin() as c:
        m = _require_draft(c, mapping_id)
        fields = copy.deepcopy(m.fields)
        f = next((x for x in fields if x["target"] == target), None)
        if f is None:
            raise MappingError(f"{target} is not in this mapping; use add_field")
        f["original_suggestion"] = f.get("original_suggestion") or {"source": f["source"], "transform": f["transform"], "confidence": f["confidence"]}
        if action == "accept":
            f["status"] = "accepted"
        elif action == "reject":
            f["status"] = "rejected"
        else:
            if source or sources:
                f["sources"] = sources or [source]
                f["source"] = f["sources"][0]
            if transform is not None:
                f["transform"] = transform
            if default is not None:
                f["default"] = default
            f["status"] = "overridden"
        f["reviewed_by"] = actor
        _save_fields(c, mapping_id, fields, actor, f"mapping.field_{action}", {"target": target, "source": f.get("sources")})
    return f


def accept_all(mapping_id: str, actor: str, min_confidence: float = 0.8) -> int:
    with db.get_engine().begin() as c:
        m = _require_draft(c, mapping_id)
        fields = copy.deepcopy(m.fields)
        n = 0
        for f in fields:
            if f["status"] in ("suggested", "needs_review") and f["confidence"] >= min_confidence:
                f["status"], f["reviewed_by"] = "accepted", actor
                n += 1
        _save_fields(c, mapping_id, fields, actor, "mapping.accept_all", {"min_confidence": min_confidence, "count": n})
    return n


def _columns(c, source_id) -> dict[str, dict]:
    src = c.execute(select(db.sources.c.profile).where(db.sources.c.source_id == source_id)).first()
    return {col["name"]: col for col in ((src[0] if src else None) or {}).get("columns", [])}


def suggest_for(mapping_id: str, sources: list[str], target: str) -> dict:
    """Confidence + proposed transform chain for an analyst-chosen (source column(s) -> SSE attribute) pair."""
    from .engine import score_pair, suggest_transform

    if target not in BY_NAME:
        raise MappingError(f"unknown SSE attribute {target}")
    with db.get_engine().connect() as c:
        m = c.execute(select(db.mappings).where(db.mappings.c.mapping_id == mapping_id)).first()
        if not m:
            raise MappingError("mapping not found")
        cols = _columns(c, m.source_id)
    missing = [s for s in sources if s not in cols]
    if missing:
        raise MappingError(f"unknown source column(s): {missing}")
    attr = BY_NAME[target]
    cents = bool((m.stats or {}).get("cents_detected"))
    if len(sources) == 1:
        conf, signals = score_pair(cols[sources[0]], attr)
        transform = suggest_transform(cols[sources[0]], attr, cents)
    else:
        conf, signals = None, {}
        transform = [{"op": "concat", "separator": " "}] + ([{"op": "truncate", "length": attr.length}] if attr.length else [])
    feeds = {}
    for f in m.fields:
        for s in f.get("sources") or [f.get("source")]:
            if s in sources and f["target"] != target and f["status"] != "rejected":
                feeds.setdefault(s, []).append(f["target"])
    existing = next((f for f in m.fields if f["target"] == target and f["status"] != "rejected"), None)
    return {"target": target, "sources": sources, "confidence": conf, "signals": signals, "transform": transform,
            "already_feeds": feeds, "replaces": {"sources": existing.get("sources"), "status": existing["status"]} if existing else None}


def retarget_field(mapping_id: str, target: str, new_target: str, actor: str) -> dict:
    """Point an existing mapping at a different SSE attribute, keeping its source and steps (type cast re-derived)."""
    from .transforms import cast_step_for

    if new_target not in BY_NAME:
        raise MappingError(f"unknown SSE attribute {new_target}")
    with db.get_engine().begin() as c:
        m = _require_draft(c, mapping_id)
        fields = copy.deepcopy(m.fields)
        f = next((x for x in fields if x["target"] == target), None)
        if f is None:
            raise MappingError(f"{target} is not in this mapping")
        clash = next((x for x in fields if x["target"] == new_target and x["status"] != "rejected"), None)
        if clash:
            raise MappingError(f"{new_target} is already mapped from {', '.join(clash.get('sources') or [clash.get('source')])}; remove or reject it first")
        fields = [x for x in fields if x["target"] not in (target, new_target)]
        casts = {"to_decimal", "to_int", "to_date", "to_bool", "truncate", "upper"}
        steps = list(f.get("transform") or [])
        while steps and steps[-1].get("op") in casts:
            steps.pop()
        new_cast = cast_step_for(new_target)
        attr = BY_NAME[new_target]
        moved = {**f, "target": new_target, "module": attr.module, "required": attr.required, "risk": attr.risk,
                 "transform": steps + ([new_cast] if new_cast else []), "status": "overridden", "reviewed_by": actor,
                 "retargeted_from": target, "rationale": f"Re-pointed by {actor} from {target}",
                 "original_suggestion": f.get("original_suggestion") or {"source": f.get("source"), "target": target,
                                                                          "transform": f.get("transform"), "confidence": f.get("confidence")}}
        fields.append(moved)
        _save_fields(c, mapping_id, fields, actor, "mapping.field_retarget", {"from": target, "to": new_target})
    return moved


def add_field(mapping_id: str, target: str, actor: str, sources: list[str] | None, transform: list[dict], default=None) -> dict:
    """Add (or replace) a mapping for any SSE attribute. A source column may feed any number of targets (1:N)."""
    if target not in BY_NAME:
        raise MappingError(f"unknown SSE attribute {target}")
    if not sources and default is None and not any(s.get("op") == "constant" for s in transform or []):
        raise MappingError("choose at least one source column, a constant step or a default value")
    with db.get_engine().begin() as c:
        m = _require_draft(c, mapping_id)
        cols = _columns(c, m.source_id)
        bad = [s for s in sources or [] if s not in cols]
        if bad:
            raise MappingError(f"unknown source column(s): {bad}")
        fields = [f for f in copy.deepcopy(m.fields) if f["target"] != target]
        attr = BY_NAME[target]
        conf = None
        if sources and len(sources) == 1:
            from .engine import score_pair

            conf = score_pair(cols[sources[0]], attr)[0]
        others = sorted({f["target"] for f in fields for s in (f.get("sources") or [f.get("source")]) if s in (sources or []) and f["status"] != "rejected"})
        f = {"source": (sources or [None])[0], "sources": sources or [], "target": target, "module": attr.module, "confidence": conf if conf is not None else 1.0,
             "transform": transform, "rationale": "Added by analyst" + (f"; source also feeds {', '.join(others)}" if others else ""),
             "composite": len(sources or []) > 1, "one_to_many": bool(others), "status": "overridden",
             "required": attr.required, "risk": attr.risk, "manual": True, "reviewed_by": actor}
        if default is not None:
            f["default"] = default
        fields.append(f)
        _save_fields(c, mapping_id, fields, actor, "mapping.field_add", {"target": target, "sources": sources})
    return f


def preview(mapping_id: str, n: int = 500) -> dict:
    """Validation preview: run the draft mapping + live rules over the sample before anything loads."""
    with db.get_engine().connect() as c:
        m = c.execute(select(db.mappings).where(db.mappings.c.mapping_id == mapping_id)).first()
        src = c.execute(select(db.sources).where(db.sources.c.source_id == m.source_id)).first()
    from ..storage import local_path

    _, rows = read_sample(local_path(src.sample_file), n, ParseOptions(**(src.parse_options or {})))
    fields = [{**f, "status": "accepted" if f["status"] in ("suggested", "needs_review") else f["status"]} for f in m.fields]
    mapper = compile_mapping(fields)
    ex = RuleExecutor(RuleRegistry().runtime_set())
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    by_rule: dict[str, int] = {}
    transform_errors: dict[str, int] = {}
    samples = []
    for raw in rows:
        rec, terrs = mapper(raw)
        ev = ex.evaluate(rec)
        status = "FAIL" if terrs else ev.status
        counts[status] += 1
        for f in ev.failures:
            by_rule[f.rule_id] = by_rule.get(f.rule_id, 0) + 1
        for k in terrs:
            transform_errors[k] = transform_errors.get(k, 0) + 1
        if status != "PASS" and len(samples) < 15:
            samples.append({"record": mask_record(rec, TARGET_PII_TYPES), "failures": [f.rule_id for f in ev.failures], "transform_errors": terrs})
    total = max(len(rows), 1)
    return {"rows": len(rows), "counts": counts, "pass_rate": round((counts["PASS"] + counts["WARN"]) / total * 100, 1),
            "failures_by_rule": dict(sorted(by_rule.items(), key=lambda x: -x[1])), "transform_errors": transform_errors,
            "samples": samples, "first_record": mask_record(mapper(rows[0])[0], TARGET_PII_TYPES) if rows else None}


def submit(mapping_id: str, actor: str) -> dict:
    with db.get_engine().begin() as c:
        m = _require_draft(c, mapping_id)
        pending = [f["target"] for f in m.fields if f["status"] in ("suggested", "needs_review")]
        if pending:
            raise MappingError(f"{len(pending)} field(s) not yet reviewed: {pending[:8]}")
        active = {f["target"] for f in m.fields if f["status"] != "rejected"}
        missing = [a for a in BY_NAME if BY_NAME[a].required and a not in active]
        if missing:
            raise MappingError(f"required SSE attributes unmapped: {missing}")
        c.execute(db.mappings.update().where(db.mappings.c.mapping_id == mapping_id).values(status="in_review", reviewed_by=actor))
        db.audit(c, actor, "mapping.submit", "mapping", mapping_id)
    return get_mapping(mapping_id)


def approve(mapping_id: str, actor: str, roles: list[str], approve_: bool = True, comment: str | None = None) -> dict:
    from ..security import expand_roles

    roles = list(expand_roles(roles))
    with db.get_engine().begin() as c:
        m = c.execute(select(db.mappings).where(db.mappings.c.mapping_id == mapping_id)).first()
        if not m or m.status != "in_review":
            raise MappingError("mapping is not awaiting approval")
        if not set(roles) & {"onboarding_reviewer", "admin"}:
            raise MappingError("Onboarding reviewer role required to approve mappings")
        if actor in (m.created_by, m.reviewed_by):
            raise MappingError("approver must differ from the person who prepared the mapping")
        comments = list(m.comments or []) + ([{"actor": actor, "comment": comment, "ts": db.now().isoformat()}] if comment else [])
        if not approve_:
            c.execute(db.mappings.update().where(db.mappings.c.mapping_id == mapping_id).values(status="draft", comments=comments))
            db.audit(c, actor, "mapping.send_back", "mapping", mapping_id, {"comment": comment})
            return get_mapping(mapping_id)
        c.execute(db.mappings.update().where(db.mappings.c.source_id == m.source_id, db.mappings.c.status == "approved")
                  .values(status="superseded"))
        c.execute(db.mappings.update().where(db.mappings.c.mapping_id == mapping_id)
                  .values(status="approved", approved_by=actor, approved_at=db.now(), comments=comments))
        c.execute(db.sources.update().where(db.sources.c.source_id == m.source_id).values(status="live", active_mapping_id=mapping_id))
        src_name = c.execute(select(db.sources.c.name).where(db.sources.c.source_id == m.source_id)).scalar()
        learned = record_memory(c, m.fields, src_name, actor)
        db.audit(c, actor, "mapping.approve", "mapping", mapping_id, {"source_id": m.source_id, "version": m.version, "learned": learned})
    from ..config_store import publish

    publish(m.source_id, actor, f"mapping v{m.version} approved")  # what Glue will run from now on
    return get_mapping(mapping_id)


def new_version(source_id: str, actor: str) -> dict:
    with db.get_engine().begin() as c:
        latest = c.execute(select(db.mappings).where(db.mappings.c.source_id == source_id).order_by(db.mappings.c.version.desc())).first()
        if not latest:
            raise MappingError("source has no mapping")
        if latest.status in ("draft", "in_review"):
            raise MappingError("a draft already exists")
        mid = db.new_id("map")
        c.execute(db.mappings.insert().values(mapping_id=mid, source_id=source_id, version=latest.version + 1, status="draft",
                                              fields=latest.fields, stats=latest.stats, created_by=actor, comments=[]))
        db.audit(c, actor, "mapping.new_version", "mapping", mid, {"from": latest.mapping_id})
    return get_mapping(mid)


def remap_from_drift(source_id: str, renames: dict[str, str], date_formats: dict[str, str] | None, actor: str) -> dict:
    """Create (or update) a draft mapping version that applies drift fixes: column renames and date formats.

    The draft still needs SME approval; the blocked batch then resumes on the new version.
    """
    from ..pipeline.preflight import remap_fields

    with db.get_engine().connect() as c:
        draft = c.execute(select(db.mappings).where(db.mappings.c.source_id == source_id, db.mappings.c.status == "draft")
                          .order_by(db.mappings.c.version.desc())).first()
    m = get_mapping(draft.mapping_id) if draft else new_version(source_id, actor)
    fields = remap_fields(m["fields"], renames or {}, date_formats or {})
    with db.get_engine().begin() as c:
        cols = _columns(c, source_id)
        for new in (renames or {}).values():
            if new not in cols:
                cols[new] = {"name": new}
        _save_fields(c, m["mapping_id"], fields, actor, "mapping.remap_drift", {"renames": renames, "date_formats": date_formats})
        # register new column names on the source profile so the Mapping UI can offer them
        src = c.execute(select(db.sources).where(db.sources.c.source_id == source_id)).first()
        prof = dict(src.profile or {})
        known = {col["name"] for col in prof.get("columns", [])}
        prof["columns"] = list(prof.get("columns", [])) + [{"name": n, "inferred_type": "string", "null_pct": 0, "distinct": 0, "notes": ["added from drift"],
                                                             "pii_type": None, "samples": [], "top_patterns": []}
                                                            for n in (renames or {}).values() if n not in known]
        c.execute(db.sources.update().where(db.sources.c.source_id == source_id).values(profile=prof))
    return get_mapping(m["mapping_id"])
