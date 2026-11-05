"""In-app notifications for maker-checker review (rules v1).

Peer pool = demo / header-auth directory of SME + Compliance users (mirrors frontend PERSONAS).
Cognito: when personas.list_users() returns users with roles, those are preferred.
"""
from __future__ import annotations

from sqlalchemy import insert, select, update

from .store import db

# Mirrors frontend PERSONAS used for X-User demo auth.
PEER_DIRECTORY = [
    {"id": "dan.sme", "roles": ["sme", "analyst"]},
    {"id": "ana.compliance", "roles": ["compliance", "checker"]},
    {"id": "admin", "roles": ["admin", "analyst", "sme", "ops", "reviewer", "checker", "compliance"]},
]


def _directory() -> list[dict]:
    try:
        from . import personas

        users = personas.list_users()
        out = []
        for u in users or []:
            uid = u.get("username") or u.get("email") or u.get("id")
            roles = u.get("roles") or ([u["role"]] if u.get("role") else [])
            if uid and roles:
                out.append({"id": uid, "roles": list(roles)})
        if out:
            return out
    except Exception:  # noqa: BLE001 - fall back to demo directory
        pass
    return PEER_DIRECTORY


def peer_user_ids(*, exclude: str | None = None, roles: tuple[str, ...] = ("sme", "compliance")) -> list[str]:
    """Eligible reviewers in the peer pool (not the author)."""
    ids = []
    for u in _directory():
        if exclude and u["id"] == exclude:
            continue
        rs = set(u.get("roles") or [])
        if "admin" in rs or rs.intersection(roles):
            ids.append(u["id"])
    return ids


def create(user_id: str, kind: str, title: str, body: str = "", entity_type: str = "rule", entity_id: str | None = None) -> dict:
    row = {
        "id": db.new_id("ntf"),
        "user_id": user_id,
        "kind": kind,
        "title": title,
        "body": body or "",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "read_at": None,
        "created_at": db.now(),
    }
    with db.get_engine().begin() as c:
        c.execute(insert(db.notifications).values(**row))
    return row


def notify_many(user_ids: list[str], kind: str, title: str, body: str = "", entity_type: str = "rule", entity_id: str | None = None) -> int:
    n = 0
    for uid in dict.fromkeys(user_ids):  # stable unique
        if not uid:
            continue
        create(uid, kind, title, body, entity_type, entity_id)
        n += 1
    return n


def list_for(user_id: str, *, unread_only: bool = False, limit: int = 50) -> list[dict]:
    q = select(db.notifications).where(db.notifications.c.user_id == user_id).order_by(db.notifications.c.created_at.desc()).limit(limit)
    with db.get_engine().connect() as c:
        rows = [dict(r._mapping) for r in c.execute(q)]
    if unread_only:
        rows = [r for r in rows if r.get("read_at") is None]
    return rows


def unread_count(user_id: str) -> int:
    return len(list_for(user_id, unread_only=True, limit=500))


def mark_read(notif_id: str, user_id: str) -> dict | None:
    with db.get_engine().begin() as c:
        row = c.execute(select(db.notifications).where(db.notifications.c.id == notif_id)).first()
        if not row or row.user_id != user_id:
            return None
        if row.read_at is None:
            c.execute(update(db.notifications).where(db.notifications.c.id == notif_id).values(read_at=db.now()))
        out = dict(row._mapping)
        out["read_at"] = out.get("read_at") or db.now()
        return out


def mark_all_read(user_id: str) -> int:
    with db.get_engine().begin() as c:
        res = c.execute(
            update(db.notifications)
            .where(db.notifications.c.user_id == user_id, db.notifications.c.read_at.is_(None))
            .values(read_at=db.now())
        )
        return res.rowcount or 0


def on_rule_transition(body: dict, to: str, actor: str, *, pending: str | None = None) -> None:
    """Emit peer-pool / author notifications after a successful (or pending) rule transition."""
    rid = body.get("rule_id")
    ver = body.get("version")
    name = body.get("name") or rid
    entity = f"{rid}:v{ver}"
    author = body.get("author")

    if to == "in_review":
        peers = peer_user_ids(exclude=author)
        notify_many(
            peers,
            "rule.in_review",
            f"Review requested: {name}",
            f"{actor} submitted {entity} for peer review.",
            entity_id=rid,
        )
        return

    if pending:
        # Peer signed off; Compliance still required
        comps = peer_user_ids(exclude=author, roles=("compliance",))
        notify_many(
            comps,
            "rule.peer_approved",
            f"Compliance review needed: {name}",
            f"{actor} peer-approved {entity}; regulatory tag requires Compliance.",
            entity_id=rid,
        )
        if author and author != actor:
            create(author, "rule.peer_approved", f"Peer approved {name} — waiting on Compliance", f"{actor} recorded a peer approval on {entity}.", entity_id=rid)
        return

    if to == "approved" and author and author != actor:
        create(author, "rule.approved", f"Approved: {name}", f"{actor} approved {entity}. You can try it safely or turn it on.", entity_id=rid)
        return

    if to == "draft" and author and author != actor:
        create(author, "rule.sent_back", f"Sent back: {name}", f"{actor} returned {entity} to draft.", entity_id=rid)
