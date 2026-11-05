"""Persisted rule templates for SME maintenance + Author catalog."""
from __future__ import annotations

import re

from sqlalchemy import delete, select

from ..store import db
from .shapes import ShapeError, compile_tree, templates as seed_templates


class TemplateError(ValueError):
    pass


def _row(r) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "description": r["description"] or "",
        "tree": r["tree"],
        "builtin": bool(r["builtin"]),
        "hidden": bool(r["hidden"]),
        "version": int(r["version"] or 1),
        "updated_by": r["updated_by"],
        "updated_at": r["updated_at"].isoformat() + "Z" if getattr(r["updated_at"], "isoformat", None) else r["updated_at"],
    }


def seed_builtins(actor: str = "system") -> int:
    """Insert missing built-in templates from shapes.templates(). Idempotent."""
    added = 0
    with db.get_engine().begin() as c:
        existing = {row[0] for row in c.execute(select(db.rule_templates.c.id)).all()}
        for t in seed_templates():
            if t["id"] in existing:
                continue
            compile_tree(t["tree"])  # validate seed
            c.execute(db.rule_templates.insert().values(
                id=t["id"], name=t["name"], description=t.get("description") or "",
                tree=t["tree"], builtin=True, hidden=False, version=1,
                updated_by=actor, updated_at=db.now(),
            ))
            added += 1
    return added


def list_templates(*, include_hidden: bool = False) -> list[dict]:
    seed_builtins()
    q = select(db.rule_templates).order_by(db.rule_templates.c.builtin.desc(), db.rule_templates.c.name)
    with db.get_engine().connect() as c:
        rows = [dict(r._mapping) for r in c.execute(q).all()]
    out = [_row(r) for r in rows]
    if not include_hidden:
        out = [t for t in out if not t["hidden"]]
    return out


def get_template(template_id: str) -> dict | None:
    seed_builtins()
    with db.get_engine().connect() as c:
        r = c.execute(select(db.rule_templates).where(db.rule_templates.c.id == template_id)).first()
    return _row(dict(r._mapping)) if r else None


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "template").lower()).strip("_")[:48] or "template"
    return f"tpl_{s}"


def create_template(body: dict, actor: str) -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        raise TemplateError("name is required")
    tree = body.get("tree")
    if not tree:
        raise TemplateError("tree is required")
    try:
        compile_tree(tree)
    except ShapeError as e:
        raise TemplateError(str(e)) from e
    tid = (body.get("id") or "").strip() or _slug(name)
    if not re.fullmatch(r"[a-z0-9_]{2,80}", tid):
        raise TemplateError("id must be lowercase letters, digits, underscore")
    with db.get_engine().begin() as c:
        if c.execute(select(db.rule_templates.c.id).where(db.rule_templates.c.id == tid)).first():
            raise TemplateError(f"template id already exists: {tid}")
        c.execute(db.rule_templates.insert().values(
            id=tid, name=name, description=body.get("description") or "",
            tree=tree, builtin=False, hidden=False, version=1,
            updated_by=actor, updated_at=db.now(),
        ))
        db.audit(c, actor, "rule_template.create", "rule_template", tid, {"name": name})
    return get_template(tid)


def update_template(template_id: str, changes: dict, actor: str) -> dict:
    cur = get_template(template_id)
    if not cur:
        raise TemplateError("template not found")
    name = changes.get("name", cur["name"])
    description = changes.get("description", cur["description"])
    tree = changes.get("tree", cur["tree"])
    if changes.get("tree") is not None:
        try:
            compile_tree(tree)
        except ShapeError as e:
            raise TemplateError(str(e)) from e
    with db.get_engine().begin() as c:
        c.execute(db.rule_templates.update().where(db.rule_templates.c.id == template_id).values(
            name=name, description=description, tree=tree,
            version=(cur["version"] or 1) + 1, updated_by=actor, updated_at=db.now(),
        ))
        db.audit(c, actor, "rule_template.update", "rule_template", template_id, {"name": name})
    return get_template(template_id)


def set_hidden(template_id: str, hidden: bool, actor: str) -> dict:
    cur = get_template(template_id)
    if not cur:
        raise TemplateError("template not found")
    with db.get_engine().begin() as c:
        c.execute(db.rule_templates.update().where(db.rule_templates.c.id == template_id).values(
            hidden=hidden, version=(cur["version"] or 1) + 1, updated_by=actor, updated_at=db.now(),
        ))
        db.audit(c, actor, "rule_template.hide" if hidden else "rule_template.unhide", "rule_template", template_id, {})
    return get_template(template_id)


def delete_template(template_id: str, actor: str) -> None:
    cur = get_template(template_id)
    if not cur:
        raise TemplateError("template not found")
    if cur["builtin"]:
        raise TemplateError("built-in templates cannot be deleted; hide them instead")
    with db.get_engine().begin() as c:
        c.execute(delete(db.rule_templates).where(db.rule_templates.c.id == template_id))
        db.audit(c, actor, "rule_template.delete", "rule_template", template_id, {"name": cur["name"]})
