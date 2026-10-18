from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from poker_bot_platform.auth.models import Account, BotProfile
from poker_bot_platform.domain import (
    ActionType,
    EntryKind,
    FailureReason,
    LegalAction,
    MatchConfig,
    MatchStatus,
    Role,
    Street,
    TableStatus,
)

EmailInput = Annotated[StrictStr, StringConstraints(min_length=3, max_length=320)]
PasswordInput = Annotated[StrictStr, StringConstraints(min_length=10, max_length=256)]
NameInput = Annotated[StrictStr, StringConstraints(min_length=1, max_length=80)]
PortInput = Annotated[StrictInt, Field(ge=1024, le=65535)]
IpInput = Annotated[StrictStr, StringConstraints(min_length=1, max_length=45)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Accounts


class RegisterRequest(ApiModel):
    email: EmailInput
    password: PasswordInput


class LoginRequest(ApiModel):
    email: EmailInput
    password: Annotated[StrictStr, StringConstraints(min_length=1, max_length=256)]


class ChangePasswordRequest(ApiModel):
    current_password: Annotated[StrictStr, StringConstraints(min_length=1, max_length=256)]
    new_password: PasswordInput


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


class PasswordResetResponse(ApiModel):
    account: AccountResponse
    temporary_password: str


# Bots


class BotProfileRequest(ApiModel):
    name: NameInput
    ip: IpInput
    port: PortInput


class BotProfileUpdateRequest(ApiModel):
    name: NameInput | None = None
    ip: IpInput | None = None
    port: PortInput | None = None


class BotProfileResponse(ApiModel):
    id: str
    name: str
    ip: str
    port: int
    verified_at: datetime | None
    last_verification_error: str | None
    created_at: datetime

    @classmethod
    def from_profile(cls, profile: BotProfile) -> BotProfileResponse:
        return cls(
            id=profile.id,
            name=profile.name,
            ip=profile.bot_ip,
            port=profile.bot_port,
            verified_at=profile.verified_at,
            last_verification_error=profile.last_verification_error,
            created_at=profile.created_at,
        )


class BotTokenResponse(ApiModel):
    bot: BotProfileResponse
    bearer_token: str


class BotDecisionLogResponse(ApiModel):
    match_id: str
    hand_id: str
    at: datetime
    latency_ms: int = Field(ge=0)
    action: ActionType
    amount_to: int | None = None
    failure_reason: FailureReason | None = None
    explanation: str | None = None


class BotDiagnosticsResponse(ApiModel):
    bot: BotProfileResponse
    decisions: int = Field(ge=0)
    failures: dict[str, int]
    consecutive_failures: int = Field(ge=0)
    recent: tuple[BotDecisionLogResponse, ...]


# Matches


class MatchCreateRequest(ApiModel):
    name: NameInput
    config: MatchConfig = Field(default_factory=MatchConfig)


class JoinMatchRequest(ApiModel):
    code: Annotated[StrictStr, StringConstraints(min_length=1, max_length=16)]
    kind: EntryKind
    display_name: NameInput | None = None
    bot_profile_id: Annotated[StrictStr, StringConstraints(max_length=64)] | None = None

    @model_validator(mode="after")
    def validate_kind(self) -> JoinMatchRequest:
        if self.kind is EntryKind.BOT and self.bot_profile_id is None:
            raise ValueError("choose which of your bots should take the seat")
        if self.kind is EntryKind.HUMAN and self.bot_profile_id is not None:
            raise ValueError("human seats do not use a bot")
        if self.kind is EntryKind.HUMAN and self.display_name is None:
            raise ValueError("enter the name other players will see")
        return self


class MatchPreviewResponse(ApiModel):
    match_id: str
    name: str
    status: MatchStatus
    seats_taken: int = Field(ge=0)
    max_seats: int = Field(ge=2, le=6)
    config: MatchConfig
    joinable: bool
    reason: str | None = None


class StandingResponse(ApiModel):
    entry_id: str
    display_name: str
    kind: EntryKind
    position: int = Field(ge=1)
    eliminated_hand_number: int | None = None
    final_stack: int = Field(ge=0)


class LobbyEntryResponse(ApiModel):
    entry_id: str
    display_name: str
    kind: EntryKind
    mine: bool
    bot_ready: bool | None = None


class MatchViewResponse(ApiModel):
    match_id: str
    name: str
    status: MatchStatus
    max_seats: int
    config: MatchConfig
    entries: tuple[LobbyEntryResponse, ...]
    standings: tuple[StandingResponse, ...]
    level_number: int
    level_remaining_seconds: int | None
    end_requested: bool
    created_at: datetime


class MyMatchResponse(ApiModel):
    match_id: str
    name: str
    status: MatchStatus
    seats_taken: int
    max_seats: int
    my_entries: tuple[LobbyEntryResponse, ...]
    created_at: datetime


class AdminEntryResponse(ApiModel):
    entry_id: str
    display_name: str
    kind: EntryKind
    account_email: str | None
    bot_name: str | None = None
    bot_ready: bool | None = None
    bot_endpoint: str | None = None
    state: Literal["lobby", "seated", "eliminated", "finished"]
    seat: int | None = None
    stack: int | None = None
    away: bool = False
    last_seen_at: datetime | None = None
    bot_decisions: int = 0
    bot_failures: int = 0
    bot_consecutive_failures: int = 0


class AdminMatchSummaryResponse(ApiModel):
    match_id: str
    name: str
    status: MatchStatus
    join_code: str | None
    seats_taken: int
    max_seats: int
    players_remaining: int
    created_at: datetime


class AdminMatchResponse(ApiModel):
    match_id: str
    name: str
    status: MatchStatus
    join_code: str | None
    config: MatchConfig
    entries: tuple[AdminEntryResponse, ...]
    standings: tuple[StandingResponse, ...]
    hand_number: int
    level_number: int
    level_remaining_seconds: int | None
    end_requested: bool
    table_quarantined: bool
    created_at: datetime
    revision: int


# Table projection


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
    duration_ms: int = Field(gt=0)
    legal_actions: tuple[LegalAction, ...]


class PublicTurnResponse(ApiModel):
    seat: int = Field(ge=1, le=6)
    kind: EntryKind
    deadline_at: datetime
    duration_ms: int = Field(gt=0)


class HandAwardResponse(ApiModel):
    seat: int = Field(ge=1, le=6)
    amount: int = Field(ge=0)
    net: int


class RevealedHandResponse(ApiModel):
    seat: int = Field(ge=1, le=6)
    hole_cards: tuple[str, ...]
    label: str
    best_five: tuple[str, ...]


class HandResultResponse(ApiModel):
    reason: Literal["showdown", "fold"]
    awards: tuple[HandAwardResponse, ...]
    winner_seats: tuple[int, ...] = ()
    revealed_hands: tuple[RevealedHandResponse, ...] = ()


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
    away: bool = False
    hole_cards: tuple[str, ...] = ()


class PublicPlayerActionResponse(ApiModel):
    sequence: int
    seat: int
    street: Street | None = None
    action: ActionType
    amount_to: int | None = None
    automatic: bool
    failure_reason: FailureReason | None = None


class PublicSidePotResponse(ApiModel):
    amount: int
    eligible_seats: tuple[int, ...]


class ViewerResponse(ApiModel):
    entry_id: str
    display_name: str
    status: Literal["seated", "eliminated", "winner", "finished"]
    finish_position: int | None = None


class MatchContextResponse(ApiModel):
    name: str
    level_number: int
    level_remaining_seconds: int | None
    next_small_blind: int | None
    next_big_blind: int | None
    players_remaining: int
    max_seats: int
    end_requested: bool
    standings: tuple[StandingResponse, ...]


class LastHandResponse(ApiModel):
    hand_number: int
    community_cards: tuple[str, ...]
    result: HandResultResponse
    names: dict[int, str]


class PlayerTableStateResponse(ApiModel):
    match_id: str
    match_status: MatchStatus
    table_status: TableStatus
    table_id: str
    hand_id: str
    hand_number: int
    table_version: int
    viewer_seat: int | None = Field(default=None, ge=1, le=6)
    viewer: ViewerResponse | None = None
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
    turn: PublicTurnResponse | None = None
    hand_result: HandResultResponse | None = None
    next_action_at: datetime | None = None
    match: MatchContextResponse | None = None
    last_hand: LastHandResponse | None = None


class DemoMatchStateResponse(ApiModel):
    status: Literal["idle", "active", "completed"]
    match_id: str | None = None
    result: Literal["human_win", "bot_win", "tie"] | None = None
    table: PlayerTableStateResponse | None = None

    @model_validator(mode="after")
    def validate_match_shape(self) -> DemoMatchStateResponse:
        if self.status == "idle" and (
            self.table is not None or self.result is not None or self.match_id is not None
        ):
            raise ValueError("idle demo matches cannot expose table state or a result")
        if self.status == "active" and (
            self.table is None or self.result is not None or self.match_id is None
        ):
            raise ValueError("active demo matches require a table and no result")
        if self.status == "completed" and (
            self.table is None or self.result is None or self.match_id is None
        ):
            raise ValueError("completed demo matches require a table and result")
        return self
