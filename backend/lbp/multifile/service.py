"""Maker-checker for a feed's multi-file layout and readiness policy.

Mirrors the delivery-profile flow: an analyst or SME proposes, a different SME or admin decides,
approval makes the draft live and publishes a new signed bundle."""
from __future__ import annotations

from .layout import DEFAULT_READINESS, normalize_layout, validate_layout


class LayoutServiceError(ValueError):
    pass


class LayoutPublishError(LayoutServiceError):
    """The layout decision was saved, but publishing the feed configuration failed: the feed refuses files until
    it is republished (never a silent single-file fallback)."""


def _roles(roles: list[str]) -> set[str]:
    from ..security import expand_roles

    return set(expand_roles(roles))


def known_columns(profile: dict | None) -> dict[str, list[str]] | None:
    """Columns of the sampled file, which is the master role's; None when there is no profile."""
    cols = [c["name"] for c in (profile or {}).get("columns", [])]
    return {"master": cols} if cols else None


def propose_layout(source_id: str, layout: dict, readiness: dict, actor: str, roles: list[str]) -> dict:
    from sqlalchemy import select

    from ..store import db

    if not _roles(roles) & {"onboarding", "onboarding_reviewer", "admin"}:
        raise LayoutServiceError("Analyst or SME role required")
    readiness = readiness or {}
    with db.get_engine().begin() as c:
        src = c.execute(select(db.sources).where(db.sources.c.source_id == source_id).with_for_update()).first()
        if not src:
            raise LayoutServiceError("unknown source")
        errs = validate_layout(layout, readiness, known_columns(src.profile))
        from ..pipeline.delivery import profile_of

        lt = profile_of(src.delivery)["load_type"]
        if lt != "full":
            errs.append(f"this feed's delivery profile load type is {lt}; multi-file layouts support full loads only in this "
                        "phase (snapshot and incremental are refused)")
        if errs:
            raise LayoutServiceError("; ".join(errs))
        clean = normalize_layout(layout)
        clean_ready = {**DEFAULT_READINESS, **{k: v for k, v in readiness.items() if v is not None}}
        c.execute(db.sources.update().where(db.sources.c.source_id == source_id).values(
            layout_draft=clean, readiness_draft=clean_ready, layout_proposed_by=actor))
        db.audit(c, actor, "source.layout_propose", "source", source_id, {"layout": clean, "readiness": clean_ready})
    return {"source_id": source_id, "layout_draft": clean, "readiness_draft": clean_ready, "proposed_by": actor}


def decide_layout(source_id: str, actor: str, roles: list[str], approve: bool, comment: str | None = None) -> dict:
    from sqlalchemy import select

    from ..store import db

    if not _roles(roles) & {"onboarding_reviewer", "admin"}:
        raise LayoutServiceError("SME role required")
    with db.get_engine().begin() as c:
        src = c.execute(select(db.sources).where(db.sources.c.source_id == source_id).with_for_update()).first()
        if not src or not src.layout_draft:
            raise LayoutServiceError("no layout change is awaiting approval")
        if actor == src.layout_proposed_by:
            raise LayoutServiceError("maker-checker: the approver must be a different user from the proposer")
        vals = {"layout_draft": None, "readiness_draft": None, "layout_proposed_by": None}
        if approve:
            vals["layout"] = src.layout_draft
            vals["readiness"] = src.readiness_draft
        c.execute(db.sources.update().where(db.sources.c.source_id == source_id).values(**vals))
        db.audit(c, actor, "source.layout_approve" if approve else "source.layout_reject", "source", source_id,
                 {"comment": comment, **({"layout": src.layout_draft, "readiness": src.readiness_draft} if approve else {})})
    if approve and src.active_mapping_id:
        from .. import config_store

        try:
            config_store.publish(source_id, actor, "layout approved")
        except Exception as e:  # noqa: BLE001 - reported, never swallowed
            with db.get_engine().begin() as c:
                db.audit(c, actor, "source.layout_publish_failed", "source", source_id, {"error": e.__class__.__name__})
            raise LayoutPublishError(f"the layout was approved and saved, but publishing the feed configuration failed "
                                     f"({e.__class__.__name__}); the feed refuses files until it is republished "
                                     f"(POST /api/sources/{source_id}/publish)") from None
    return {"source_id": source_id, "approved": approve}


from .preview import preview_join  # noqa: E402,F401  (read-only: preview never writes the DB, audits or publishes)
