"""Guided rule compose + create-from-tree API."""


def test_shapes_fields_templates_endpoints(client):
    assert client.get("/api/rules/shapes").json()["shapes"]
    assert client.get("/api/rules/fields").json()["fields"]
    assert client.get("/api/rules/templates").json()["templates"]


def test_compose_and_create_from_tree(client):
    h = {"X-User": "dan", "X-Roles": "sme"}
    tree = {"shape": "between", "field": "interest_rate", "min": 0.5, "max": 15}
    c = client.post("/api/rules/compose", json={"tree": tree, "severity": "FAIL"}, headers=h)
    assert c.status_code == 200, c.text
    body = c.json()
    assert body["summary"] and body["draft"]["expression"] and body["draft"]["tree"]
    assert all(t["passed"] for t in body["test_results"])

    r = client.post(
        "/api/rules",
        json={"name": "Rate band", "tree": tree, "severity": "FAIL"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["tree"]["shape"] == "between" and draft["expression"]
    got = client.get(f"/api/rules/{draft['rule_id']}").json()
    assert got["versions"][0]["status"] == "draft"


def test_author_returns_tree_when_possible(client):
    h = {"X-User": "dan", "X-Roles": "sme"}
    d = client.post("/api/rules/author", json={"text": "Interest rate must be between 0.5 and 15"}, headers=h).json()
    assert d["draft"] and d["draft"].get("tree")
