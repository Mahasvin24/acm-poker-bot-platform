"""Allow one bot profile per account."""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_one_bot_per_account"
down_revision: str | None = "0006_participant_kind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("uq_bot_profiles_account", "bot_profiles", ["account_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_bot_profiles_account", table_name="bot_profiles")
