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
