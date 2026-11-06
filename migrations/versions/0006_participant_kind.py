"""Persist the participant type chosen at signup; preserve existing mixed accounts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_participant_kind"
down_revision: str | None = "0005_account_career"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("participant_kind", sa.String(16), nullable=True))
    op.create_check_constraint(
        "ck_accounts_participant_kind", "accounts", "participant_kind IN ('human', 'bot')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_accounts_participant_kind", "accounts", type_="check")
    op.drop_column("accounts", "participant_kind")
