"""Record when a player last asked for a match."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_looking_for_match"
down_revision: str | None = "0007_one_bot_per_account"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "accounts", sa.Column("looking_for_match_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("accounts", "looking_for_match_at")
