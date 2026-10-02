from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from poker_bot_platform.persistence.models import Base


class AccountRow(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="ck_accounts_role"),
    )


class SessionRow(Base):
    __tablename__ = "account_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_account_sessions_expiry", "expires_at"),)


class EntrantRow(Base):
    __tablename__ = "tournament_entrants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tournament_id: Mapped[str] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    bot_ip: Mapped[str | None] = mapped_column(String(45))
    bot_port: Mapped[int | None] = mapped_column(Integer)
    bot_token_ciphertext: Mapped[str | None] = mapped_column(Text)
    bot_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "tournament_id",
            name="uq_tournament_entrant_account",
        ),
        CheckConstraint("kind IN ('human', 'bot')", name="ck_tournament_entrants_kind"),
        CheckConstraint(
            "bot_port IS NULL OR bot_port BETWEEN 1024 AND 65535",
            name="ck_tournament_entrants_bot_port",
        ),
        CheckConstraint(
            "kind = 'bot' OR (bot_ip IS NULL AND bot_port IS NULL "
            "AND bot_token_ciphertext IS NULL AND bot_verified_at IS NULL)",
            name="ck_tournament_entrants_human_has_no_bot_fields",
        ),
    )
