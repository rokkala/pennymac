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
    with op.batch_alter_table("sources") as b:
        b.drop_column("retired_from_status")
        b.drop_column("retired_reason")
        b.drop_column("retired_by")
        b.drop_column("retired_at")
