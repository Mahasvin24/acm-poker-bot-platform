from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, StringConstraints

from poker_bot_platform.auth.models import Account, Entrant
from poker_bot_platform.domain import EntryKind, Role, TournamentConfig

EmailInput = Annotated[StrictStr, StringConstraints(min_length=3, max_length=320)]
PasswordInput = Annotated[StrictStr, StringConstraints(min_length=10, max_length=256)]
DisplayNameInput = Annotated[StrictStr, StringConstraints(min_length=1, max_length=80)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(ApiModel):
    email: EmailInput
    password: PasswordInput


class LoginRequest(ApiModel):
    email: EmailInput
    password: PasswordInput


class AccountResponse(ApiModel):
    id: str
    email: str
    role: Role
    created_at: datetime

    @classmethod
    def from_account(cls, account: Account) -> AccountResponse:
        return cls(
            id=account.id,
            email=account.email,
            role=account.role,
            created_at=account.created_at,
        )


class EntrantRequest(ApiModel):
    kind: EntryKind
    display_name: DisplayNameInput


class BotEndpointRequest(ApiModel):
    ip: StrictStr
    port: StrictInt = Field(ge=1024, le=65535)


class EntrantResponse(ApiModel):
    id: str
    tournament_id: str
    kind: EntryKind
    display_name: str
    bot_ip: str | None
    bot_port: int | None
    bot_verified_at: datetime | None

    @classmethod
    def from_entrant(cls, entrant: Entrant) -> EntrantResponse:
        return cls(
            id=entrant.id,
            tournament_id=entrant.tournament_id,
            kind=entrant.kind,
            display_name=entrant.display_name,
            bot_ip=entrant.bot_ip,
            bot_port=entrant.bot_port,
            bot_verified_at=entrant.bot_verified_at,
        )


class BotEndpointRegistrationResponse(ApiModel):
    entrant: EntrantResponse
    bearer_token: str


class AdminTournamentRequest(ApiModel):
    tournament_id: Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]
    config: TournamentConfig = Field(default_factory=TournamentConfig)


class AdminTournamentUpdateRequest(ApiModel):
    config: TournamentConfig


class AdminCommandResponse(ApiModel):
    tournament_id: str
    status: str
