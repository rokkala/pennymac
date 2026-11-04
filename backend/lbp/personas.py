"""Persona Maintenance: Cognito-native users (one group each) + restrict-only screen matrix.

Screen matrix lives in the policy table (key ``screen_matrix``). Stored values may only
hide screens relative to DEFAULT_ACCESS — never grant beyond the coded baseline.
API authorization remains ROUTE_ROLES; this matrix only drives nav visibility.

Users: when auth_mode=jwt and a Cognito pool is configured, Admin* Cognito APIs.
Otherwise a local directory in the policy table (key ``persona_users``) for dev/tests.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from .config import get_settings
from .security import ROLES
from .store import db

SCREENS: dict[str, str] = {
    "overview": "Overview",
    "guide": "How it works",
    "imports": "Import Monitor",
    "deliveries": "Vendor Deliveries",
    "sources": "Vendors & Mapping",
    "exceptions": "Exception Manager",
    "rules": "Rule Engine",
    "analytics": "Analytics",
    "governance": "Policy & Audit",
    "maintenance": "Maintenance",
    "personas": "Personas",
}

# Baseline visibility per screen (roles that may see it). Admin always sees all via bypass.
DEFAULT_ACCESS: dict[str, tuple[str, ...]] = {
    "overview": ROLES,
    "guide": ROLES,
    "imports": ("ops", "sme", "admin"),
    "deliveries": ("ops", "sme", "analyst", "admin"),
    "sources": ("analyst", "sme", "admin"),
    "exceptions": ("reviewer", "checker", "compliance", "admin"),
    "rules": ("sme", "compliance", "analyst", "admin"),
    "analytics": ("analyst", "sme", "ops", "reviewer", "checker", "compliance", "admin"),
    "governance": ("compliance", "sme", "admin"),
    "maintenance": ("sme", "admin"),
    "personas": ("admin",),
}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MATRIX_KEY = "screen_matrix"
_USERS_KEY = "persona_users"


class PersonaError(ValueError):
    pass


def _default_matrix() -> dict[str, list[str]]:
    """role → screens that role may see (inverse of DEFAULT_ACCESS)."""
    out = {r: [] for r in ROLES}
    for screen, roles in DEFAULT_ACCESS.items():
        for r in roles:
            if r in out:
                out[r].append(screen)
    return out


def get_screen_matrix() -> dict[str, list[str]]:
    base = _default_matrix()
    with db.get_engine().connect() as c:
        row = c.execute(select(db.policy.c.value).where(db.policy.c.key == _MATRIX_KEY)).first()
    stored = (row[0] if row else {}) or {}
    out: dict[str, list[str]] = {}
    for role in ROLES:
        allowed = set(base[role])
        if role in stored and isinstance(stored[role], list):
            out[role] = [s for s in stored[role] if s in allowed]
        else:
            out[role] = list(base[role])
    return out


def set_screen_matrix(partial: dict[str, list[str]], actor: str) -> dict[str, list[str]]:
    base = _default_matrix()
    current = get_screen_matrix()
    for role, screens in partial.items():
        if role not in ROLES:
            raise PersonaError(f"unknown role: {role}")
        if not isinstance(screens, list):
            raise PersonaError(f"screens for {role} must be a list")
        unknown = [s for s in screens if s not in SCREENS]
        if unknown:
            raise PersonaError(f"unknown screens: {sorted(unknown)}")
        grant = set(screens) - set(base[role])
        if grant:
            raise PersonaError(f"cannot grant {sorted(grant)} to {role} beyond default access")
        current[role] = [s for s in SCREENS if s in screens]  # stable order
    with db.get_engine().begin() as c:
        exists = c.execute(select(db.policy.c.key).where(db.policy.c.key == _MATRIX_KEY)).first()
        stmt = db.policy.update().where(db.policy.c.key == _MATRIX_KEY) if exists else db.policy.insert().values(key=_MATRIX_KEY)
        c.execute(stmt.values(value=current, updated_by=actor, approved_by=actor, updated_at=db.now()))
        db.audit(c, actor, "personas.screens.update", "policy", _MATRIX_KEY, {"matrix": current})
    return current


def visible_screens(roles: list[str] | tuple[str, ...]) -> list[str]:
    if "admin" in roles:
        return list(SCREENS)
    matrix = get_screen_matrix()
    seen: list[str] = []
    for screen in SCREENS:
        if any(screen in matrix.get(r, []) for r in roles):
            seen.append(screen)
    return seen


# --- user directory ---------------------------------------------------------

def _use_cognito() -> bool:
    s = get_settings()
    return s.auth_mode == "jwt" and bool(s.cognito_user_pool_id)


def _cognito():
    import boto3

    s = get_settings()
    return boto3.client("cognito-idp", region_name=s.cognito_region), s.cognito_user_pool_id


def _load_local() -> list[dict]:
    with db.get_engine().connect() as c:
        row = c.execute(select(db.policy.c.value).where(db.policy.c.key == _USERS_KEY)).first()
    return list((row[0] if row else []) or [])


def _save_local(users: list[dict], actor: str, action: str, detail: dict) -> None:
    with db.get_engine().begin() as c:
        exists = c.execute(select(db.policy.c.key).where(db.policy.c.key == _USERS_KEY)).first()
        stmt = db.policy.update().where(db.policy.c.key == _USERS_KEY) if exists else db.policy.insert().values(key=_USERS_KEY)
        c.execute(stmt.values(value=users, updated_by=actor, approved_by=actor, updated_at=db.now()))
        db.audit(c, actor, action, "persona", detail.get("email") or detail.get("username") or "-", detail)


def _normalize_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not _EMAIL.match(e):
        raise PersonaError("valid email required")
    return e


def _require_role(role: str) -> str:
    if role not in ROLES:
        raise PersonaError(f"role must be one of: {', '.join(ROLES)}")
    return role


def _admin_count(users: list[dict]) -> int:
    return sum(1 for u in users if u.get("role") == "admin" and u.get("enabled", True))


def _guard_last_admin(users: list[dict], username: str, *, new_role: str | None = None, enabled: bool | None = None) -> None:
    cur = next((u for u in users if u["username"] == username or u.get("email") == username), None)
    if not cur or cur.get("role") != "admin":
        return
    will_lose = False
    if enabled is False:
        will_lose = True
    if new_role is not None and new_role != "admin":
        will_lose = True
    if will_lose and _admin_count(users) <= 1:
        raise PersonaError("cannot disable or demote the last admin")


def list_users() -> list[dict]:
    if _use_cognito():
        return _cognito_list()
    return sorted(_load_local(), key=lambda u: u.get("email") or "")


def get_user(username: str) -> dict:
    key = username.strip().lower()
    for u in list_users():
        if u.get("username") == key or u.get("email") == key:
            return u
    raise PersonaError(f"user not found: {username}")


def create_user(*, email: str, role: str, actor: str, temporary_password: str) -> dict:
    email = _normalize_email(email)
    role = _require_role(role)
    _require_temp_password(temporary_password)
    if _use_cognito():
        return _cognito_create(email, role, temporary_password, actor)
    users = _load_local()
    if any(u["email"] == email for u in users):
        raise PersonaError(f"user already exists: {email}")
    user = {"username": email, "email": email, "role": role, "enabled": True, "status": "FORCE_CHANGE_PASSWORD"}
    users.append(user)
    _save_local(users, actor, "personas.user.create", {"email": email, "role": role})
    return user


def set_user(username: str, *, actor: str, role: str | None = None, enabled: bool | None = None) -> dict:
    key = username.strip().lower()
    if role is not None:
        role = _require_role(role)
    if _use_cognito():
        return _cognito_set(key, actor=actor, role=role, enabled=enabled)
    users = _load_local()
    _guard_last_admin(users, key, new_role=role, enabled=enabled)
    for i, u in enumerate(users):
        if u["username"] == key or u.get("email") == key:
            if role is not None:
                u["role"] = role
            if enabled is not None:
                u["enabled"] = enabled
            users[i] = u
            _save_local(users, actor, "personas.user.update", {"email": u["email"], "role": u["role"], "enabled": u["enabled"]})
            return u
    raise PersonaError(f"user not found: {username}")


def _require_temp_password(temporary_password: str) -> None:
    """Match Cognito pool policy in aws/terraform/api.tf (length 14 + complexity)."""
    pw = temporary_password or ""
    if (len(pw) < 14 or not re.search(r"[a-z]", pw) or not re.search(r"[A-Z]", pw)
            or not re.search(r"\d", pw) or not re.search(r"[^A-Za-z0-9]", pw)):
        raise PersonaError("temporary password needs 14+ chars with upper, lower, number, and symbol")


def reset_password(username: str, *, temporary_password: str, actor: str) -> dict:
    _require_temp_password(temporary_password)
    key = username.strip().lower()
    if _use_cognito():
        return _cognito_reset(key, temporary_password, actor)
    users = _load_local()
    for u in users:
        if u["username"] == key or u.get("email") == key:
            u["status"] = "FORCE_CHANGE_PASSWORD"
            _save_local(users, actor, "personas.user.reset_password", {"email": u["email"]})
            return {"username": u["username"], "email": u["email"], "status": u["status"]}
    raise PersonaError(f"user not found: {username}")


def _cognito_groups_for(username: str, client, pool: str) -> list[str]:
    groups = []
    paginator = client.get_paginator("admin_list_groups_for_user")
    for page in paginator.paginate(UserPoolId=pool, Username=username):
        for g in page.get("Groups") or []:
            name = g.get("GroupName")
            if name in ROLES:
                groups.append(name)
    return groups


def _cognito_primary_role(groups: list[str]) -> str | None:
    for r in ROLES:
        if r in groups:
            return r
    return None


def _cognito_list() -> list[dict]:
    client, pool = _cognito()
    out = []
    paginator = client.get_paginator("list_users")
    for page in paginator.paginate(UserPoolId=pool):
        for u in page.get("Users") or []:
            attrs = {a["Name"]: a["Value"] for a in (u.get("Attributes") or [])}
            email = (attrs.get("email") or u["Username"]).lower()
            groups = _cognito_groups_for(u["Username"], client, pool)
            out.append({
                "username": u["Username"],
                "email": email,
                "role": _cognito_primary_role(groups),
                "enabled": bool(u.get("Enabled", True)),
                "status": u.get("UserStatus"),
            })
    return sorted(out, key=lambda x: x.get("email") or "")


def _cognito_set_single_group(client, pool: str, username: str, role: str) -> None:
    for g in _cognito_groups_for(username, client, pool):
        if g != role:
            client.admin_remove_user_from_group(UserPoolId=pool, Username=username, GroupName=g)
    if role not in _cognito_groups_for(username, client, pool):
        client.admin_add_user_to_group(UserPoolId=pool, Username=username, GroupName=role)


def _cognito_create(email: str, role: str, temporary_password: str, actor: str) -> dict:
    client, pool = _cognito()
    try:
        resp = client.admin_create_user(
            UserPoolId=pool,
            Username=email,
            TemporaryPassword=temporary_password,
            UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}],
            MessageAction="SUPPRESS",  # admin shares the temp password from Persona Maintenance
        )
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        if code in ("UsernameExistsException", "AliasExistsException"):
            raise PersonaError(f"user already exists: {email}") from e
        raise PersonaError(str(e)) from e
    username = resp["User"]["Username"]
    _cognito_set_single_group(client, pool, username, role)
    with db.get_engine().begin() as c:
        db.audit(c, actor, "personas.user.create", "persona", email, {"email": email, "role": role})
    return {"username": username, "email": email, "role": role, "enabled": True, "status": resp["User"].get("UserStatus")}


def _cognito_set(username: str, *, actor: str, role: str | None, enabled: bool | None) -> dict:
    client, pool = _cognito()
    users = _cognito_list()
    _guard_last_admin(users, username, new_role=role, enabled=enabled)
    try:
        if enabled is False:
            client.admin_disable_user(UserPoolId=pool, Username=username)
        elif enabled is True:
            client.admin_enable_user(UserPoolId=pool, Username=username)
        if role is not None:
            _cognito_set_single_group(client, pool, username, role)
    except client.exceptions.UserNotFoundException as e:
        raise PersonaError(f"user not found: {username}") from e
    except PersonaError:
        raise
    except Exception as e:  # noqa: BLE001
        raise PersonaError(str(e)) from e
    with db.get_engine().begin() as c:
        db.audit(c, actor, "personas.user.update", "persona", username, {"role": role, "enabled": enabled})
    return get_user(username)


def _cognito_reset(username: str, temporary_password: str, actor: str) -> dict:
    client, pool = _cognito()
    try:
        client.admin_set_user_password(UserPoolId=pool, Username=username, Password=temporary_password, Permanent=False)
    except client.exceptions.UserNotFoundException as e:
        raise PersonaError(f"user not found: {username}") from e
    except Exception as e:  # noqa: BLE001
        raise PersonaError(str(e)) from e
    with db.get_engine().begin() as c:
        db.audit(c, actor, "personas.user.reset_password", "persona", username, {})
    return {"username": username, "status": "FORCE_CHANGE_PASSWORD"}


def screens_payload() -> dict[str, Any]:
    return {
        "screens": [{"id": k, "label": v} for k, v in SCREENS.items()],
        "roles": list(ROLES),
        "defaults": _default_matrix(),
        "matrix": get_screen_matrix(),
    }
