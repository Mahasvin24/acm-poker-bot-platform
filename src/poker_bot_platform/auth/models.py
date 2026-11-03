from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from poker_bot_platform.domain import Role


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


class BotProfile(AuthModel):
    """A participant-hosted bot owned by one account and reusable across matches."""

    id: str
    account_id: str
    name: str = Field(min_length=1, max_length=80)
    bot_ip: str
    bot_port: int = Field(ge=1024, le=65535)
    bot_token_ciphertext: str
    verified_at: datetime | None = None
    last_verification_error: str | None = None
    created_at: datetime
