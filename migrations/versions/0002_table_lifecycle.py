"""Add optimistic lifecycle versioning to tournaments."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_table_lifecycle"
down_revision: str | None = "0001_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tournaments",
        sa.Column("version", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.alter_column("tournaments", "version", server_default=None)


def downgrade() -> None:
    op.drop_column("tournaments", "version")
