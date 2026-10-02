from __future__ import annotations

from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from poker_bot_platform.domain.models import (
    ActionType,
    Card,
    EntryKind,
    SidePot,
    Street,
)

BOT_PROTOCOL_VERSION = "poker-bot.v1"
WireIdentifier = Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]


class WireModel(BaseModel):
    """Base for externally controlled JSON.

    Integers are declared as StrictInt so JSON booleans and numeric strings are
    never interpreted as chip counts, versions, ports, or seat numbers.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class BotEndpoint(WireModel):
    ip: IPv4Address | IPv6Address
    port: StrictInt = Field(ge=1024, le=65535)


class PublicSeat(WireModel):
    seat: StrictInt = Field(ge=1, le=6)
    entrant_id: WireIdentifier
    display_name: Annotated[StrictStr, StringConstraints(min_length=1, max_length=80)]
    kind: EntryKind
    stack: StrictInt = Field(ge=0)
    committed_this_street: StrictInt = Field(ge=0)
    committed_this_hand: StrictInt = Field(ge=0)
    folded: StrictBool
    all_in: StrictBool
    eliminated: StrictBool


class PublicAction(WireModel):
    sequence: StrictInt = Field(ge=1)
    seat: StrictInt = Field(ge=1, le=6)
    action: ActionType
    amount_to: StrictInt | None = Field(default=None, ge=0)
    automatic: StrictBool = False

    @model_validator(mode="after")
    def validate_amount(self) -> PublicAction:
        if self.action is ActionType.RAISE and self.amount_to is None:
            raise ValueError("raise requires amount_to")
        if self.action is not ActionType.RAISE and self.amount_to is not None:
            raise ValueError("only raise accepts amount_to")
        return self


class BlindState(WireModel):
    small_blind: StrictInt = Field(ge=0)
    big_blind: StrictInt = Field(gt=0)
    big_blind_ante: StrictInt = Field(ge=0)


class PublicSidePot(WireModel):
    amount: StrictInt = Field(ge=0)
    eligible_seats: tuple[StrictInt, ...]

    @classmethod
    def from_domain(cls, pot: SidePot) -> PublicSidePot:
        return cls(amount=pot.amount, eligible_seats=pot.eligible_seats)


class PublicTableState(WireModel):
    street: Street
    button_seat: StrictInt = Field(ge=1, le=6)
    blinds: BlindState
    community_cards: tuple[Card, ...] = ()
    seats: tuple[PublicSeat, ...]
    pot: StrictInt = Field(ge=0)
    side_pots: tuple[PublicSidePot, ...] = ()
    action_history: tuple[PublicAction, ...] = ()


class ActingPlayerState(WireModel):
    seat: StrictInt = Field(ge=1, le=6)
    stack: StrictInt = Field(ge=0)
    committed_this_street: StrictInt = Field(ge=0)
    hole_cards: tuple[Card, ...]


class BotLegalAction(WireModel):
    action: ActionType
    amount: StrictInt | None = Field(default=None, ge=0)
    min_amount_to: StrictInt | None = Field(default=None, ge=0)
    max_amount_to: StrictInt | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_amount_shape(self) -> BotLegalAction:
        if self.action is ActionType.CALL:
            if (
                self.amount is None
                or self.min_amount_to is not None
                or self.max_amount_to is not None
            ):
                raise ValueError("call requires amount and forbids raise bounds")
        elif self.action is ActionType.RAISE:
            if self.min_amount_to is None or self.max_amount_to is None or self.amount is not None:
                raise ValueError("raise requires min_amount_to and max_amount_to")
            if self.min_amount_to > self.max_amount_to:
                raise ValueError("raise minimum cannot exceed maximum")
        elif any(
            value is not None for value in (self.amount, self.min_amount_to, self.max_amount_to)
        ):
            raise ValueError("fold and check do not accept amounts")
        return self


class BotActionRequest(WireModel):
    protocol: Literal["poker-bot.v1"]
    tournament_id: WireIdentifier
    table_id: WireIdentifier
    hand_id: WireIdentifier
    decision_id: WireIdentifier
    table_version: StrictInt = Field(ge=0)
    deadline_at: datetime
    table: PublicTableState
    player: ActingPlayerState
    legal_actions: tuple[BotLegalAction, ...]

    @field_validator("deadline_at")
    @classmethod
    def deadline_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deadline_at must include a UTC offset")
        return value

    @model_validator(mode="after")
    def acting_player_must_match_public_seat(self) -> BotActionRequest:
        seats = [seat for seat in self.table.seats if seat.seat == self.player.seat]
        if len(seats) != 1:
            raise ValueError("acting player must occur exactly once in public seats")
        public = seats[0]
        if public.stack != self.player.stack:
            raise ValueError("acting player stack must match public state")
        if public.committed_this_street != self.player.committed_this_street:
            raise ValueError("acting player commitment must match public state")
        if not self.legal_actions:
            raise ValueError("legal_actions cannot be empty")
        actions = [legal.action for legal in self.legal_actions]
        if len(actions) != len(set(actions)):
            raise ValueError("legal action types must be unique")
        if ActionType.CHECK not in actions and ActionType.FOLD not in actions:
            raise ValueError("legal_actions must permit the deterministic fallback")
        return self


class BotActionResponse(WireModel):
    protocol: Literal["poker-bot.v1"]
    tournament_id: WireIdentifier
    table_id: WireIdentifier
    hand_id: WireIdentifier
    decision_id: WireIdentifier
    table_version: StrictInt = Field(ge=0)
    action: ActionType
    amount_to: StrictInt | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_action_shape(self) -> BotActionResponse:
        if self.action is ActionType.RAISE and self.amount_to is None:
            raise ValueError("raise requires amount_to")
        if self.action is not ActionType.RAISE and self.amount_to is not None:
            raise ValueError("only raise accepts amount_to")
        return self


class VerifyRequest(WireModel):
    protocol: Literal["poker-bot.v1"]
    challenge: Annotated[StrictStr, StringConstraints(min_length=32, max_length=256)]


class VerifyResponse(WireModel):
    protocol: Literal["poker-bot.v1"]
    challenge: Annotated[StrictStr, StringConstraints(min_length=32, max_length=256)]


class HealthResponse(WireModel):
    protocol: Literal["poker-bot.v1"]
    status: Literal["ready"]
