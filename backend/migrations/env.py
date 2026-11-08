"""Alembic environment: schema is defined in lbp.store.db.metadata; URL from LBP settings."""
from alembic import context

from lbp.config import get_settings
from lbp.store import db

target_metadata = db.metadata


def run():
    url = get_settings().resolved_database_url()
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    # get_engine injects the Secrets Manager password; a bare URL has the user only
    engine = db.get_engine(create=False)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run()
