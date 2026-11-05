"""Persona Maintenance: restrict-only screen matrix + Cognito-native (local) user directory."""
from __future__ import annotations

import pytest


def test_default_matrix_covers_all_screens_and_roles(env):
    from lbp.personas import DEFAULT_ACCESS, ROLES, SCREENS

    assert set(DEFAULT_ACCESS) == set(SCREENS)
    for screen, roles in DEFAULT_ACCESS.items():
        assert roles, f"{screen} must allow at least one role"
        assert set(roles) <= set(ROLES)


def test_matrix_restrict_only_rejects_grant(env):
    from lbp.personas import PersonaError, get_screen_matrix, set_screen_matrix

    m = get_screen_matrix()
    assert "personas" in m["admin"]
    with pytest.raises(PersonaError, match="cannot grant"):
        set_screen_matrix({"monitoring": list(m["monitoring"]) + ["personas"]}, actor="admin1")


def test_matrix_can_hide_and_visible_for_roles(env):
    from lbp.personas import get_screen_matrix, set_screen_matrix, visible_screens

    m = get_screen_matrix()
    mon = [s for s in m["monitoring"] if s != "analytics"]
    set_screen_matrix({"monitoring": mon}, actor="admin1")
    assert "analytics" not in get_screen_matrix()["monitoring"]
    assert "analytics" not in visible_screens(["monitoring"])
    assert "analytics" in visible_screens(["admin"])  # admin bypasses hide


def test_local_user_crud_single_role(env):
    from lbp.personas import PersonaError, create_user, get_user, list_users, reset_password, set_user

    create_user(email="ops1@example.com", role="monitoring", actor="admin1", temporary_password="TempPass1!abcd")
    users = list_users()
    assert any(u["email"] == "ops1@example.com" and u["role"] == "monitoring" and u["enabled"] for u in users)
    set_user("ops1@example.com", role="monitoring_reviewer", actor="admin1")
    assert get_user("ops1@example.com")["role"] == "monitoring_reviewer"
    set_user("ops1@example.com", enabled=False, actor="admin1")
    assert get_user("ops1@example.com")["enabled"] is False
    reset_password("ops1@example.com", temporary_password="NewTemp12!abcd", actor="admin1")
    with pytest.raises(PersonaError):
        create_user(email="x@example.com", role="not-a-role", actor="admin1", temporary_password="TempPass1!abcd")


def test_cannot_disable_last_admin(env):
    from lbp.personas import PersonaError, create_user, set_user

    create_user(email="admin.only@example.com", role="admin", actor="seed", temporary_password="TempPass1!abcd")
    with pytest.raises(PersonaError, match="last admin"):
        set_user("admin.only@example.com", enabled=False, actor="admin.only@example.com")


def test_demo_cast_seed_and_switcher_api(client):
    from lbp.personas import DEMO_CAST, cast_for_switcher, ensure_demo_cast, list_users

    ensure_demo_cast(actor="test")
    users = list_users()
    emails = {u["email"] for u in users}
    assert {r["email"] for r in DEMO_CAST} <= emails
    cast = cast_for_switcher()
    assert [p["id"] for p in cast[: len(DEMO_CAST)]] == [r["id"] for r in DEMO_CAST]
    assert all(len(p["roles"]) == 1 for p in cast)

    h_mon = {"X-User": "monitoring", "X-Roles": "monitoring"}
    r = client.get("/api/personas/cast", headers=h_mon)
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()["cast"]]
    assert "onboarding.reviewer" in ids and "compliance.reviewer" in ids
    assert client.get("/api/personas/users", headers=h_mon).status_code == 403


def test_api_personas_admin_and_me_screens(client):
    h_admin = {"X-User": "admin", "X-Roles": "admin"}
    h_mon = {"X-User": "monitoring", "X-Roles": "monitoring"}

    r = client.get("/api/personas/me/screens", headers=h_mon)
    assert r.status_code == 200
    assert "overview" in r.json()["screens"]
    assert "personas" not in r.json()["screens"]

    assert client.get("/api/personas/users", headers=h_mon).status_code == 403
    assert client.get("/api/personas/users", headers=h_admin).status_code == 200

    created = client.post("/api/personas/users", headers=h_admin,
                          json={"email": "lee@example.com", "role": "monitoring_reviewer", "temporary_password": "TempPass1!abcd"})
    assert created.status_code == 200
    assert created.json()["user"]["role"] == "monitoring_reviewer"

    mat = client.get("/api/personas/screens", headers=h_admin)
    assert mat.status_code == 200 and "defaults" in mat.json()
    mon_screens = [s for s in mat.json()["matrix"]["monitoring"] if s != "guide"]
    put = client.put("/api/personas/screens", headers=h_admin, json={"matrix": {"monitoring": mon_screens}})
    assert put.status_code == 200
    assert "guide" not in client.get("/api/personas/me/screens", headers=h_mon).json()["screens"]
