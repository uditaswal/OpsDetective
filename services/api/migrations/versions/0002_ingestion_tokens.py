"""Ingestion tokens.

Revision ID: 0002
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("ingestion_tokens", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("tenant_id", sa.String(64), nullable=False),
                    sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
                    sa.Column("service_id", sa.String(36), sa.ForeignKey("services.id"), nullable=False),
                    sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
                    sa.Column("prefix", sa.String(12), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    for column in ("tenant_id", "project_id", "service_id"):
        op.create_index(f"ix_ingestion_tokens_{column}", "ingestion_tokens", [column])


def downgrade() -> None:
    op.drop_table("ingestion_tokens")
