"""Alembic environment: schema is defined in lbp.store.db.metadata; URL from LBP settings."""
from alembic import context
from sqlalchemy import create_engine

from lbp.config import get_settings
from lbp.store.db import metadata

target_metadata = metadata


def run():
    url = get_settings().resolved_database_url()
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run()
