from sqlalchemy import update

from lbp import config_store
from lbp.store import db

LAYOUT = {
    "files": [
        {"role": "master", "entity": "loan", "name_pattern": r"m_(?P<date>\d{8})\.csv", "key": ["id"], "required": True},
        {"role": "fees", "name_pattern": r"f_(?P<date>\d{8})\.csv", "required": False},
    ],
    "relations": [{"detail": "fees", "to": "master", "on": [{"parent": "id", "detail": "ref"}], "mode": "merge"}],
}
READY = {"require": "all_required", "pairing": "business_date"}


def _set(sid, layout, readiness):
    with db.get_engine().begin() as c:
        c.execute(update(db.sources).where(db.sources.c.source_id == sid).values(layout=layout, readiness=readiness))


def test_legacy_bundle_unchanged(onboarded):
    sid = onboarded["pcg_retail"]["source_id"]
    b = config_store.build(sid)
    assert not {"layout", "readiness", "mappings"} & set(b)
    assert set(b) == {"schema", "source_id", "vendor_id", "feed_name", "vendor_feeds", "mapping", "parse_options",
                      "profile", "delivery", "rules", "rules_key"}
    cfg = config_store.load(sid)
    assert cfg.layout is None and cfg.readiness is None


def test_layout_in_signed_bundle(onboarded):
    sid = onboarded["pcg_retail"]["source_id"]
    _set(sid, LAYOUT, READY)
    b = config_store.build(sid)
    assert b["mappings"] == {"loan": b["mapping"]} and b["mappings"]["loan"] is b["mapping"]
    assert b["layout"]["relations"][0]["cardinality"] == "one"
    config_store.publish(sid, "sme1", "layout")
    cfg = config_store.load(sid)  # verifies the signature
    assert cfg.layout == b["layout"] and cfg.readiness == b["readiness"]
    assert cfg.readiness["pairing"] == "business_date" and cfg.readiness["wait_timeout_minutes"] == 240
    config_store.verify(config_store.bundle_json(sid))


def test_layout_change_creates_new_version(onboarded):
    sid = onboarded["pcg_retail"]["source_id"]
    v0 = config_store.publish(sid, "sme1", "base")["version"]
    _set(sid, LAYOUT, READY)
    v1 = config_store.publish(sid, "sme1", "layout")
    assert v1["version"] == v0 + 1
    assert config_store.publish(sid, "sme1", "again")["unchanged"] is True
    changed = {**LAYOUT, "files": [{**LAYOUT["files"][0], "required": False}, LAYOUT["files"][1]]}
    _set(sid, changed, READY)
    assert config_store.publish(sid, "sme1", "edit")["version"] == v1["version"] + 1
