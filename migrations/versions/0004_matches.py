"""Replace tournaments with code-joined matches and reusable bot profiles.

The pre-event schema held no data worth keeping, so gameplay tables are recreated
around ``matches`` instead of migrated. This revision cannot be downgraded.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_matches"
down_revision: str | None = "0003_auth_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    for table in (
        "audit_log",
        "domain_events",
        "table_actions",
        "pending_decisions",
        "table_snapshots",
        "poker_tables",
        "tournament_entrants",
        "tournaments",
    ):
        op.drop_table(table)

    op.create_table(
        "matches",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("join_code", sa.String(length=16)),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_matches_status", "matches", ["status"])
    op.create_index(
        "uq_matches_join_code",
        "matches",
        ["join_code"],
        unique=True,
        postgresql_where=sa.text("join_code IS NOT NULL"),
    )

    op.create_table(
        "bot_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("bot_ip", sa.String(length=45), nullable=False),
        sa.Column("bot_port", sa.Integer(), nullable=False),
        sa.Column("bot_token_ciphertext", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_verification_error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("bot_port BETWEEN 1024 AND 65535", name="ck_bot_profiles_port"),
    )
    op.create_index("ix_bot_profiles_account_id", "bot_profiles", ["account_id"])
    op.create_index(
        "uq_bot_profiles_account_name",
        "bot_profiles",
        ["account_id", sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "poker_tables",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column(
            "match_id",
            sa.String(length=128),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("current_hand_id", sa.String(length=128)),
        *_timestamps(),
    )
    op.create_index("ix_poker_tables_match_id", "poker_tables", ["match_id"])
    op.create_table(
        "table_snapshots",
        sa.Column(
            "table_id",
            sa.String(length=128),
            sa.ForeignKey("poker_tables.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "pending_decisions",
        sa.Column("decision_id", sa.String(length=128), primary_key=True),
        sa.Column(
            "table_id",
            sa.String(length=128),
            sa.ForeignKey("poker_tables.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hand_id", sa.String(length=128), nullable=False),
        sa.Column("table_version", sa.BigInteger(), nullable=False),
        sa.Column("seat", sa.Integer(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("legal_actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("resolved_action_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_pending_decisions_table_id", "pending_decisions", ["table_id"])
    op.create_index(
        "uq_pending_decision_per_table",
        "pending_decisions",
        ["table_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "table_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("match_id", sa.String(length=128), nullable=False),
        sa.Column(
            "table_id",
            sa.String(length=128),
            sa.ForeignKey("poker_tables.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hand_id", sa.String(length=128), nullable=False),
        sa.Column("table_version", sa.BigInteger(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.String(length=128), nullable=False),
        sa.Column("seat", sa.Integer(), nullable=False),
        sa.Column("street", sa.String(length=16)),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("amount_to", sa.BigInteger()),
        sa.Column("automatic", sa.Boolean(), nullable=False),
        sa.Column("failure_reason", sa.String(length=32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("table_id", "decision_id", name="uq_action_table_decision"),
        sa.UniqueConstraint("table_id", "hand_id", "sequence", name="uq_action_hand_sequence"),
    )
    op.create_index("ix_table_actions_match_id", "table_actions", ["match_id"])
    op.create_table(
        "domain_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("match_id", sa.String(length=128), nullable=False),
        sa.Column(
            "table_id",
            sa.String(length=128),
            sa.ForeignKey("poker_tables.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hand_id", sa.String(length=128), nullable=False),
        sa.Column("table_version", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "table_id", "table_version", "ordinal", name="uq_event_version_ordinal"
        ),
    )
    op.create_index("ix_domain_events_match_id", "domain_events", ["match_id"])
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("match_id", sa.String(length=128)),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("command", sa.String(length=80), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_log_match_id", "audit_log", ["match_id"])


def downgrade() -> None:
    raise RuntimeError("0004_matches replaced the tournament schema and cannot be downgraded")
