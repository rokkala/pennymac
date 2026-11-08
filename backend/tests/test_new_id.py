"""IDs must stay unique under parallel bulk inserts (10M Glue)."""
from lbp.store import db


def test_new_id_uses_full_uuid_hex():
    # 12-char truncation birthday-collides under parallel exception inserts.
    eid = db.new_id("ex")
    assert eid.startswith("ex_")
    assert len(eid.split("_", 1)[1]) == 32
    assert len(eid) <= 40  # String(40) PK columns
