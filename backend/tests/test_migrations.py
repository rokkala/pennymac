import os

import pytest

PG = os.environ.get("LBP_MIGRATION_TEST_URL")  # an EMPTY postgres database


@pytest.mark.skipif(not PG, reason="set LBP_MIGRATION_TEST_URL to an empty Postgres database")
def test_migrations_match_models_and_app_starts(monkeypatch):
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from lbp import cli, config
    from lbp.store import db

    monkeypatch.setenv("LBP_DATABASE_URL", PG)
    monkeypatch.setenv("LBP_AUTO_CREATE_SCHEMA", "false")
    config.reset_settings()
    db.reset_engine()
    assert cli.migrate() == 0
    eng = create_engine(PG)
    with eng.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), db.metadata)
    assert diff == [], f"models and migrations differ: {diff[:5]}"
    db.check_schema_current()
    with db.get_engine().begin() as c:
        db.audit(c, "t", "test", "x", "1")
    assert db.verify_audit_chain()["valid"]
    command.downgrade(cli._alembic_cfg(), "base")
    db.reset_engine()
    with pytest.raises(RuntimeError, match="not current"):
        db.check_schema_current()


NEW_COLS = {
    "sources": {"layout", "readiness", "layout_draft", "readiness_draft", "layout_proposed_by"},
    "mappings": {"entity"},
    "batches": {"file_set_id", "joined_path", "join_summary"},
    "exceptions": {"role"},
}
NEW_TABLES = {"file_sets", "batch_files"}


def test_0007_upgrade_downgrade_roundtrip_sqlite(tmp_path, monkeypatch):
    from alembic import command
    from sqlalchemy import create_engine, inspect

    from lbp import cli, config
    from lbp.store import db

    url = f"sqlite:///{tmp_path / 'mig.db'}"
    monkeypatch.setenv("LBP_DATABASE_URL", url)
    monkeypatch.setenv("LBP_AUTO_CREATE_SCHEMA", "false")
    config.reset_settings()
    db.reset_engine()
    cfg = cli._alembic_cfg()
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(url))
    assert NEW_TABLES <= set(insp.get_table_names())
    for table, cols in NEW_COLS.items():
        assert cols <= {c["name"] for c in insp.get_columns(table)}
    command.downgrade(cfg, "0006")
    insp = inspect(create_engine(url))
    assert not NEW_TABLES & set(insp.get_table_names())
    for table, cols in NEW_COLS.items():
        assert not cols & {c["name"] for c in insp.get_columns(table)}
    command.upgrade(cfg, "head")
    db.reset_engine()
    config.reset_settings()
