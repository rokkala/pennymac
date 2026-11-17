from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError


def test_existing_insert_paths_still_work(env):
    from lbp.store import db

    now = datetime.now(UTC).replace(tzinfo=None)
    with db.get_engine().begin() as c:
        c.execute(db.sources.insert().values(source_id="s1", name="Src"))
        c.execute(db.mappings.insert().values(mapping_id="m1", source_id="s1", version=1, status="draft", fields=[]))
        c.execute(db.batches.insert().values(batch_id="b1", source_id="s1", filename="f.csv", status="queued"))
        c.execute(db.exceptions.insert().values(exception_id="e1", batch_id="b1", source_id="s1", status="open", created_at=now))
        entity = c.execute(db.select(db.mappings.c.entity).where(db.mappings.c.mapping_id == "m1")).scalar_one()
        src = c.execute(db.select(db.sources).where(db.sources.c.source_id == "s1")).mappings().one()
        bat = c.execute(db.select(db.batches).where(db.batches.c.batch_id == "b1")).mappings().one()
        exc = c.execute(db.select(db.exceptions).where(db.exceptions.c.exception_id == "e1")).mappings().one()
    assert entity == "loan"
    assert src["layout"] is None and src["readiness_draft"] is None
    assert bat["file_set_id"] is None and bat["joined_path"] is None and bat["join_summary"] is None
    assert exc["role"] is None


def test_file_set_role_unique(env):
    from lbp.store import db

    row = {"set_id": "fs1", "role": "master", "filename": "a.csv"}
    with db.get_engine().begin() as c:
        c.execute(db.file_sets.insert().values(set_id="fs1", source_id="s1", pairing_key="k", status="waiting"))
        c.execute(db.batch_files.insert().values(**row))
    with pytest.raises(IntegrityError):
        with db.get_engine().begin() as c:
            c.execute(db.batch_files.insert().values(**row))
    with db.get_engine().begin() as c:
        c.execute(db.batch_files.insert().values(set_id="fs1", role="detail", filename="b.csv"))
