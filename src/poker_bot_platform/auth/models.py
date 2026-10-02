from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from poker_bot_platform.domain import EntryKind, Role


class AuthModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Account(AuthModel):
    id: str
    email: str
    password_hash: str
    role: Role = Role.USER
    created_at: datetime


class SessionRecord(AuthModel):
    id: str
    account_id: str
    token_hash: str
    expires_at: datetime
    created_at: datetime
    revoked_at: datetime | None = None


class Entrant(AuthModel):
    id: str
    account_id: str
    tournament_id: str
    kind: EntryKind
    display_name: str
    bot_ip: str | None = None
    bot_port: int | None = Field(default=None, ge=1024, le=65535)
    bot_token_ciphertext: str | None = None
    bot_verified_at: datetime | None = None
    created_at: datetime
