"""feed lifecycle: archive (retire) a feed with who/when/why and the status to restore to

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sources", sa.Column("retired_at", sa.DateTime(), nullable=True))
    op.add_column("sources", sa.Column("retired_by", sa.String(length=80), nullable=True))
    op.add_column("sources", sa.Column("retired_reason", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("retired_from_status", sa.String(length=20), nullable=True))


def downgrade():
    # Older code knows no archive: hand feeds back in the status they were archived from (else 'live' when they
    # have an approved mapping, 'mapping' otherwise), and turn `discarded` mapping versions into `rejected`, so an
    # archived feed is neither stranded nor silently accepting files under a status the old code does not check.
    op.execute("UPDATE sources SET status = retired_from_status WHERE status = 'retired' AND retired_from_status IS NOT NULL")
    op.execute("UPDATE sources SET status = 'live' WHERE status = 'retired' AND active_mapping_id IS NOT NULL")
    op.execute("UPDATE sources SET status = 'mapping' WHERE status = 'retired'")
    op.execute("UPDATE mappings SET status = 'rejected' WHERE status = 'discarded'")
    with op.batch_alter_table("sources") as b:
        b.drop_column("retired_from_status")
        b.drop_column("retired_reason")
        b.drop_column("retired_by")
        b.drop_column("retired_at")
