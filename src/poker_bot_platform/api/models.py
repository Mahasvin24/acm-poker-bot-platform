from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from poker_bot_platform.auth.models import Account, Entrant
from poker_bot_platform.domain import (
    ActionType,
    EntryKind,
    FailureReason,
    LegalAction,
    Role,
    Street,
    TableStatus,
    TournamentConfig,
    TournamentStatus,
)

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


class AdminTournamentStateResponse(ApiModel):
    tournament_id: str
    status: TournamentStatus
    entrant_count: int = Field(ge=0)
    human_count: int = Field(ge=0)
    bot_count: int = Field(ge=0)
    verified_bot_count: int = Field(ge=0)
    table_count: int = Field(ge=0)
    level_number: int = Field(ge=1)
    phase_remaining_seconds: int = Field(ge=0)
    revision: int = Field(ge=0)
    config: TournamentConfig


class PlayerActionRequest(ApiModel):
    decision_id: Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]
    table_version: StrictInt = Field(ge=0)
    action: ActionType
    amount_to: StrictInt | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_amount_shape(self) -> PlayerActionRequest:
        if self.action is ActionType.RAISE and self.amount_to is None:
            raise ValueError("raise requires amount_to")
        if self.action is not ActionType.RAISE and self.amount_to is not None:
            raise ValueError("only raise accepts amount_to")
        return self


class PlayerDecisionResponse(ApiModel):
    decision_id: str
    table_version: int
    deadline_at: datetime
    legal_actions: tuple[LegalAction, ...]


class PublicPlayerSeatResponse(ApiModel):
    seat: int
    entrant_id: str
    display_name: str
    kind: EntryKind
    stack: int
    committed_this_street: int
    committed_this_hand: int
    folded: bool
    all_in: bool
    eliminated: bool
    hole_cards: tuple[str, ...] = ()


class PublicPlayerActionResponse(ApiModel):
    sequence: int
    seat: int
    action: ActionType
    amount_to: int | None = None
    automatic: bool
    failure_reason: FailureReason | None = None


class PublicSidePotResponse(ApiModel):
    amount: int
    eligible_seats: tuple[int, ...]


class PlayerTableStateResponse(ApiModel):
    tournament_id: str
    tournament_status: TournamentStatus
    table_status: TableStatus
    table_id: str
    hand_id: str
    hand_number: int
    table_version: int
    viewer_seat: int = Field(ge=1, le=6)
    acting_seat: int | None = Field(default=None, ge=1, le=6)
    street: Street
    button_seat: int
    small_blind: int
    big_blind: int
    big_blind_ante: int
    community_cards: tuple[str, ...]
    seats: tuple[PublicPlayerSeatResponse, ...]
    pot: int
    side_pots: tuple[PublicSidePotResponse, ...]
    action_history: tuple[PublicPlayerActionResponse, ...]
    completed: bool
    decision: PlayerDecisionResponse | None = None
