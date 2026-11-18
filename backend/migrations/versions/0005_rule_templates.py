"""rule templates

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rule_templates",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tree", sa.JSON(), nullable=False),
        sa.Column("builtin", sa.Boolean(), nullable=True),
        sa.Column("hidden", sa.Boolean(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.String(length=80), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("rule_templates")
