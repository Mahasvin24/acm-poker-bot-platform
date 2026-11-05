"""Account profile, password-reset requests, and durable match results."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_account_career"
down_revision: str | None = "0004_matches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("display_name", sa.String(length=80), nullable=True))
    op.add_column("accounts", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "password_reset_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_password_reset_requests_open",
        "password_reset_requests",
        ["account_id"],
        unique=True,
        postgresql_where=sa.text("fulfilled_at IS NULL"),
    )

    op.create_table(
        "match_account_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "match_id",
            sa.String(length=128),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entry_id", sa.String(length=36), nullable=False),
        sa.Column("match_name", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("starting_stack", sa.Integer(), nullable=False),
        sa.Column("final_stack", sa.Integer(), nullable=False),
        sa.Column("chip_delta", sa.Integer(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('human', 'bot')", name="ck_match_account_results_kind"),
        sa.UniqueConstraint("match_id", "entry_id", name="uq_match_account_results_entry"),
    )
    op.create_index(
        "ix_match_account_results_account",
        "match_account_results",
        ["account_id", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_table("match_account_results")
    op.drop_index("ix_password_reset_requests_open", table_name="password_reset_requests")
    op.drop_table("password_reset_requests")
    op.drop_column("accounts", "deleted_at")
    op.drop_column("accounts", "display_name")
