"""Explicit ownership of the fixed monitoring-host exporter."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("monitored_hosts",
                    sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("tenant_id", sa.String(64), nullable=False),
                    sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
                    sa.Column("source_key", sa.String(32), nullable=False, unique=True),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_monitored_hosts_tenant_id", "monitored_hosts", ["tenant_id"])
    op.create_index("ix_monitored_hosts_project_id", "monitored_hosts", ["project_id"])


def downgrade() -> None:
    op.drop_table("monitored_hosts")
