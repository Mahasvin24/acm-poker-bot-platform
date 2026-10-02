from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TournamentRow(Base):
    __tablename__ = "tournaments"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TableRow(Base):
    __tablename__ = "poker_tables"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tournament_id: Mapped[str] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    current_hand_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TableSnapshotRow(Base):
    """The current private recovery snapshot for a table."""

    __tablename__ = "table_snapshots"

    table_id: Mapped[str] = mapped_column(
        ForeignKey("poker_tables.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PendingDecisionRow(Base):
    __tablename__ = "pending_decisions"

    decision_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    table_id: Mapped[str] = mapped_column(
        ForeignKey("poker_tables.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hand_id: Mapped[str] = mapped_column(String(128), nullable=False)
    table_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    seat: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    legal_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    resolved_action_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_pending_decision_per_table",
            "table_id",
            unique=True,
            postgresql_where=(status == "pending"),
        ),
    )


class ActionRow(Base):
    __tablename__ = "table_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    table_id: Mapped[str] = mapped_column(
        ForeignKey("poker_tables.id", ondelete="CASCADE"), nullable=False
    )
    hand_id: Mapped[str] = mapped_column(String(128), nullable=False)
    table_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    seat: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_to: Mapped[int | None] = mapped_column(BigInteger)
    automatic: Mapped[bool] = mapped_column(nullable=False, default=False)
    failure_reason: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("table_id", "decision_id", name="uq_action_table_decision"),
        UniqueConstraint("table_id", "hand_id", "sequence", name="uq_action_hand_sequence"),
    )


class DomainEventRow(Base):
    __tablename__ = "domain_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    table_id: Mapped[str] = mapped_column(
        ForeignKey("poker_tables.id", ondelete="CASCADE"), nullable=False
    )
    hand_id: Mapped[str] = mapped_column(String(128), nullable=False)
    table_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("table_id", "table_version", "ordinal", name="uq_event_version_ordinal"),
    )


class AuditLogRow(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id: Mapped[str | None] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    command: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
