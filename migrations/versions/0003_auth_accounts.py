"""Local accounts, revocable sessions, and tournament entrants."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_auth_accounts"
down_revision: str | None = "0002_table_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('user', 'admin')", name="ck_accounts_role"),
    )
    op.create_table(
        "account_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_account_sessions_account_id", "account_sessions", ["account_id"])
    op.create_index("ix_account_sessions_expiry", "account_sessions", ["expires_at"])
    op.create_table(
        "tournament_entrants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tournament_id",
            sa.String(length=128),
            sa.ForeignKey("tournaments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("bot_ip", sa.String(length=45)),
        sa.Column("bot_port", sa.Integer()),
        sa.Column("bot_token_ciphertext", sa.Text()),
        sa.Column("bot_verified_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "account_id",
            "tournament_id",
            name="uq_tournament_entrant_account",
        ),
        sa.CheckConstraint("kind IN ('human', 'bot')", name="ck_tournament_entrants_kind"),
        sa.CheckConstraint(
            "bot_port IS NULL OR bot_port BETWEEN 1024 AND 65535",
            name="ck_tournament_entrants_bot_port",
        ),
        sa.CheckConstraint(
            "kind = 'bot' OR (bot_ip IS NULL AND bot_port IS NULL "
            "AND bot_token_ciphertext IS NULL AND bot_verified_at IS NULL)",
            name="ck_tournament_entrants_human_has_no_bot_fields",
        ),
    )
    op.create_index("ix_tournament_entrants_account_id", "tournament_entrants", ["account_id"])
    op.create_index(
        "ix_tournament_entrants_tournament_id", "tournament_entrants", ["tournament_id"]
    )


def downgrade() -> None:
    op.drop_table("tournament_entrants")
    op.drop_table("account_sessions")
    op.drop_table("accounts")
