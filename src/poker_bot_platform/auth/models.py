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
    display_name: str | None = None
    deleted_at: datetime | None = None
    created_at: datetime


class CareerSummary(AuthModel):
    career_chip_total: int = 0
    matches_finished: int = 0


class PasswordResetRequest(AuthModel):
    account_id: str
    email: str
    requested_at: datetime


class LeaderboardEntry(AuthModel):
    account_id: str
    email: str
    display_name: str | None
    career_chip_total: int
    matches_finished: int


class MatchResultSummary(AuthModel):
    account_id: str
    entry_id: str
    match_id: str
    match_name: str
    position: int
    final_stack: int
    chip_delta: int
    display_name: str
    kind: EntryKind


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
