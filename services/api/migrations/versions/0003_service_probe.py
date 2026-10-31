"""Optional fixed demo probe assignment."""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("services", sa.Column("probe_name", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("services", "probe_name")
