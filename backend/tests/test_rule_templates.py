"""Persisted rule template catalog for Maintenance + Author."""
from lbp.rules import template_store as ts


def test_seed_list_and_author_omits_hidden(env):
    n = ts.seed_builtins()
    assert n > 0
    assert ts.seed_builtins() == 0  # idempotent
    active = ts.list_templates(include_hidden=False)
    assert any(t["id"] == "loan_number_format" for t in active)
    assert all(not t["hidden"] for t in active)


def test_create_update_hide_delete_custom(env):
    created = ts.create_template(
        {
            "name": "My rate band",
            "description": "custom",
            "tree": {"shape": "between", "field": "interest_rate", "min": 1, "max": 10},
        },
        "dan",
    )
    assert created["id"].startswith("tpl_") and created["builtin"] is False
    updated = ts.update_template(created["id"], {"name": "Rate band v2"}, "dan")
    assert updated["name"] == "Rate band v2" and updated["version"] == 2

    ts.set_hidden(created["id"], True, "dan")
    assert created["id"] not in {t["id"] for t in ts.list_templates(include_hidden=False)}
    assert created["id"] in {t["id"] for t in ts.list_templates(include_hidden=True)}
    ts.set_hidden(created["id"], False, "dan")
    ts.delete_template(created["id"], "dan")
    assert ts.get_template(created["id"]) is None


def test_builtin_cannot_delete_invalid_tree_rejected(env):
    ts.seed_builtins()
    try:
        ts.delete_template("loan_number_format", "dan")
        assert False, "expected TemplateError"
    except ts.TemplateError:
        pass
    try:
        ts.create_template({"name": "bad", "tree": {"shape": "required", "field": "nope"}}, "dan")
        assert False, "expected TemplateError"
    except ts.TemplateError:
        pass


def test_maintenance_template_api(client):
    h = {"X-User": "dan", "X-Roles": "sme"}
    listed = client.get("/api/maintenance/rule-templates", headers=h)
    assert listed.status_code == 200, listed.text
    assert listed.json()["templates"]
    author = client.get("/api/rules/templates", headers=h).json()["templates"]
    assert author and all(not t.get("hidden") for t in author)

    r = client.post(
        "/api/maintenance/rule-templates",
        json={"name": "API pattern", "tree": {"shape": "pattern", "field": "loan_number", "pattern": "[A-Z0-9-]{6,20}", "ok_example": "LN-1ABCDE", "bad_example": "x"}},
        headers=h,
    )
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    assert client.post(f"/api/maintenance/rule-templates/{tid}/hide", headers=h).status_code == 200
    ids = {t["id"] for t in client.get("/api/rules/templates", headers=h).json()["templates"]}
    assert tid not in ids
    assert client.delete(f"/api/maintenance/rule-templates/{tid}", headers=h).status_code == 200
