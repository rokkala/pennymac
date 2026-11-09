"""Authentication and role-based authorization.

Modes (LBP_AUTH_MODE):
  dev  - identity from X-User / X-Roles headers. Local development only; refused outside env=local.
  jwt  - Authorization: Bearer <Cognito access or id token>, verified against the user pool JWKS:
         signature (RS256), issuer, expiry, client/audience and token_use. Roles = cognito:groups.

API Gateway also validates the token at the edge; the service verifies again (defence in depth),
so a request that reaches ECS some other way is still rejected.

Teams (Cognito groups): onboarding / monitoring / compliance (+ *_reviewer) and admin.
Reviewer groups include their team's member powers via expand_roles().
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from fastapi import Header, HTTPException

from .config import get_settings

ROLES = (
    "onboarding",
    "onboarding_reviewer",
    "monitoring",
    "monitoring_reviewer",
    "compliance",
    "compliance_reviewer",
    "admin",
)

# Old Cognito / header names → team model (dev compatibility + leftover data).
# Note: "compliance" is a real team-member role now — do not alias it.
ROLE_ALIASES: dict[str, str] = {
    "analyst": "onboarding",
    "sme": "onboarding_reviewer",
    "ops": "monitoring",
    "reviewer": "monitoring",
    "checker": "monitoring_reviewer",
}

# Reviewer ⊇ member for the same team.
_REVIEWER_INCLUDES_MEMBER: dict[str, str] = {
    "onboarding_reviewer": "onboarding",
    "monitoring_reviewer": "monitoring",
    "compliance_reviewer": "compliance",
}


def expand_roles(raw: Iterable[str]) -> tuple[str, ...]:
    """Alias legacy names, keep only known roles, and grant member powers to reviewers."""
    out: list[str] = []
    for r in raw:
        key = (r or "").strip()
        if not key:
            continue
        canon = ROLE_ALIASES.get(key, key)
        if canon not in ROLES:
            continue
        for piece in (canon, _REVIEWER_INCLUDES_MEMBER.get(canon)):
            if piece and piece not in out:
                out.append(piece)
    return tuple(out)


@dataclass(frozen=True)
class Principal:
    name: str
    roles: tuple[str, ...]

    def has(self, *roles: str) -> bool:
        return "admin" in self.roles or any(r in self.roles for r in roles)


@lru_cache(maxsize=4)
def _jwks_client(url: str):
    import jwt

    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def verify_token(token: str) -> dict:
    import jwt

    s = get_settings()
    issuer = f"https://cognito-idp.{s.cognito_region}.amazonaws.com/{s.cognito_user_pool_id}"
    key = _jwks_client(f"{issuer}/.well-known/jwks.json").get_signing_key_from_jwt(token).key
    claims = jwt.decode(token, key, algorithms=["RS256"], issuer=issuer, options={"verify_aud": False, "require": ["exp", "iss"]})
    use = claims.get("token_use")
    if use == "id":
        if claims.get("aud") != s.cognito_client_id:
            raise jwt.InvalidAudienceError("audience mismatch")
    elif use == "access":
        if claims.get("client_id") != s.cognito_client_id:
            raise jwt.InvalidAudienceError("client mismatch")
    else:
        raise jwt.InvalidTokenError("unexpected token_use")
    if claims.get("exp", 0) < time.time():
        raise jwt.ExpiredSignatureError("expired")
    return claims


def principal_from_claims(claims: dict) -> Principal:
    groups = claims.get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [g.strip() for g in groups.strip("[]").replace(",", " ").split() if g.strip()]
    name = claims.get("email") or claims.get("username") or claims.get("cognito:username") or claims.get("sub")
    return Principal(name=str(name), roles=expand_roles(groups))


def current_principal(authorization: str | None = Header(default=None), x_user: str | None = Header(default=None),
                      x_roles: str | None = Header(default=None)) -> Principal:
    s = get_settings()
    if s.auth_mode == "dev":
        if s.env != "local":
            raise HTTPException(500, "dev auth is not allowed outside local")
        raw = (x_roles or ",".join(ROLES)).split(",")
        return Principal(name=x_user or "dev.user", roles=expand_roles(raw))
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = verify_token(authorization.split(" ", 1)[1].strip())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(401, f"invalid token: {e.__class__.__name__}", headers={"WWW-Authenticate": "Bearer"}) from None
    p = principal_from_claims(claims)
    if not p.roles:
        raise HTTPException(403, "user has no Loan Boarding role (Cognito group)")
    return p


def require(*roles: str):
    """FastAPI dependency: the caller must hold one of `roles` (admin always passes)."""
    from fastapi import Depends

    def dep(p: Principal = Depends(current_principal)) -> Principal:
        if not p.has(*roles):
            raise HTTPException(403, f"requires one of: {', '.join(roles)}")
        return p

    return dep
