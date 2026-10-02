"""Core tournament, table, snapshot, decision, action, event, and audit persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tournaments",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "poker_tables",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column(
            "tournament_id",
            sa.String(length=128),
            sa.ForeignKey("tournaments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("current_hand_id", sa.String(length=128)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_poker_tables_tournament_id", "poker_tables", ["tournament_id"])
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
        sa.Column("tournament_id", sa.String(length=128), nullable=False),
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
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("amount_to", sa.BigInteger()),
        sa.Column("automatic", sa.Boolean(), nullable=False),
        sa.Column("failure_reason", sa.String(length=32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("table_id", "decision_id", name="uq_action_table_decision"),
        sa.UniqueConstraint("table_id", "hand_id", "sequence", name="uq_action_hand_sequence"),
    )
    op.create_index("ix_table_actions_tournament_id", "table_actions", ["tournament_id"])
    op.create_table(
        "domain_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tournament_id", sa.String(length=128), nullable=False),
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
    op.create_index("ix_domain_events_tournament_id", "domain_events", ["tournament_id"])
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tournament_id", sa.String(length=128)),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("command", sa.String(length=80), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_log_tournament_id", "audit_log", ["tournament_id"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("domain_events")
    op.drop_table("table_actions")
    op.drop_table("pending_decisions")
    op.drop_table("table_snapshots")
    op.drop_table("poker_tables")
    op.drop_table("tournaments")
