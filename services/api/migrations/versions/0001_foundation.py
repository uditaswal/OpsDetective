"""Foundation schema.

Revision ID: 0001
Revises:
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("admins", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("tenant_id", sa.String(64), nullable=False),
                    sa.Column("email", sa.String(320), nullable=False, unique=True),
                    sa.Column("password_hash", sa.Text(), nullable=False))
    op.create_index("ix_admins_tenant_id", "admins", ["tenant_id"])
    op.create_table("login_sessions", sa.Column("token_hash", sa.String(64), primary_key=True),
                    sa.Column("admin_id", sa.String(36), sa.ForeignKey("admins.id"), nullable=False),
                    sa.Column("csrf_hash", sa.String(64), nullable=False),
                    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_login_sessions_admin_id", "login_sessions", ["admin_id"])
    op.create_table("projects", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("tenant_id", sa.String(64), nullable=False),
                    sa.Column("name", sa.String(120), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("tenant_id", "name"))
    op.create_index("ix_projects_tenant_id", "projects", ["tenant_id"])
    op.create_table("services", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("tenant_id", sa.String(64), nullable=False),
                    sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
                    sa.Column("name", sa.String(120), nullable=False),
                    sa.Column("environment", sa.String(64), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("tenant_id", "project_id", "name", "environment"))
    op.create_index("ix_services_tenant_id", "services", ["tenant_id"])
    op.create_index("ix_services_project_id", "services", ["project_id"])
    op.create_table("audit_events", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("tenant_id", sa.String(64), nullable=False),
                    sa.Column("actor_id", sa.String(36), nullable=False),
                    sa.Column("action", sa.String(80), nullable=False),
                    sa.Column("target_id", sa.String(36), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])


def downgrade() -> None:
    for table in ("audit_events", "services", "projects", "login_sessions", "admins"):
        op.drop_table(table)
