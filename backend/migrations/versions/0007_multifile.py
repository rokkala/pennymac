"""multi-file feeds: layouts, file sets and joined batches

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sources", sa.Column("layout", sa.JSON(), nullable=True))
    op.add_column("sources", sa.Column("readiness", sa.JSON(), nullable=True))
    op.add_column("sources", sa.Column("layout_draft", sa.JSON(), nullable=True))
    op.add_column("sources", sa.Column("readiness_draft", sa.JSON(), nullable=True))
    op.add_column("sources", sa.Column("layout_proposed_by", sa.String(length=80), nullable=True))
    op.add_column("mappings", sa.Column("entity", sa.String(length=40), nullable=False, server_default="loan"))
    op.add_column("batches", sa.Column("file_set_id", sa.String(length=40), nullable=True))
    op.add_column("batches", sa.Column("joined_path", sa.String(length=500), nullable=True))
    op.add_column("batches", sa.Column("join_summary", sa.JSON(), nullable=True))
    op.create_index("ix_batches_file_set_id", "batches", ["file_set_id"])
    op.add_column("exceptions", sa.Column("role", sa.String(length=40), nullable=True))

    op.create_table(
        "file_sets",
        sa.Column("set_id", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=40), nullable=True),
        sa.Column("pairing_key", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("ready_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("batch_id", sa.String(length=40), nullable=True),
        sa.Column("members_sha", sa.String(length=64), nullable=True),
        sa.Column("override", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("set_id"),
    )
    op.create_index("ix_file_sets_source_id", "file_sets", ["source_id"])
    op.create_index("ix_file_sets_pairing_key", "file_sets", ["pairing_key"])
    op.create_index("ix_file_sets_status", "file_sets", ["status"])
    op.create_index("ix_file_sets_members_sha", "file_sets", ["members_sha"])

    op.create_table(
        "batch_files",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("set_id", sa.String(length=40), nullable=True),
        sa.Column("batch_id", sa.String(length=40), nullable=True),
        sa.Column("role", sa.String(length=40), nullable=True),
        sa.Column("filename", sa.String(length=300), nullable=True),
        sa.Column("file_path", sa.String(length=500), nullable=True),
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("set_id", "role", name="uq_batch_file_role"),
    )
    op.create_index("ix_batch_files_set_id", "batch_files", ["set_id"])
    op.create_index("ix_batch_files_batch_id", "batch_files", ["batch_id"])
    op.create_index("ix_batch_files_file_sha256", "batch_files", ["file_sha256"])


def downgrade():
    op.drop_index("ix_batch_files_file_sha256", table_name="batch_files")
    op.drop_index("ix_batch_files_batch_id", table_name="batch_files")
    op.drop_index("ix_batch_files_set_id", table_name="batch_files")
    op.drop_table("batch_files")
    op.drop_index("ix_file_sets_members_sha", table_name="file_sets")
    op.drop_index("ix_file_sets_status", table_name="file_sets")
    op.drop_index("ix_file_sets_pairing_key", table_name="file_sets")
    op.drop_index("ix_file_sets_source_id", table_name="file_sets")
    op.drop_table("file_sets")
    with op.batch_alter_table("exceptions") as b:
        b.drop_column("role")
    op.drop_index("ix_batches_file_set_id", table_name="batches")
    with op.batch_alter_table("batches") as b:
        b.drop_column("join_summary")
        b.drop_column("joined_path")
        b.drop_column("file_set_id")
    with op.batch_alter_table("mappings") as b:
        b.drop_column("entity")
    with op.batch_alter_table("sources") as b:
        b.drop_column("layout_proposed_by")
        b.drop_column("readiness_draft")
        b.drop_column("layout_draft")
        b.drop_column("readiness")
        b.drop_column("layout")
