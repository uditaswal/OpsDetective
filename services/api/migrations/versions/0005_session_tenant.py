"""Bind existing login sessions to their administrator's tenant."""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("login_sessions", sa.Column("tenant_id", sa.String(64), nullable=True))
    op.execute(sa.text("UPDATE login_sessions SET tenant_id = "
                       "(SELECT tenant_id FROM admins WHERE admins.id = login_sessions.admin_id)"))
    op.execute(sa.text("DELETE FROM login_sessions WHERE tenant_id IS NULL"))
    with op.batch_alter_table("login_sessions") as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(64), nullable=False)
        batch.create_index("ix_login_sessions_tenant_id", ["tenant_id"])


def downgrade() -> None:
    with op.batch_alter_table("login_sessions") as batch:
        batch.drop_index("ix_login_sessions_tenant_id")
        batch.drop_column("tenant_id")
