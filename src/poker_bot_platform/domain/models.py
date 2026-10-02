from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Card = Annotated[str, StringConstraints(pattern=r"^[2-9TJQKA][cdhs]$")]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Role(StrEnum):
    USER = "user"
    ADMIN = "admin"


class EntryKind(StrEnum):
    HUMAN = "human"
    BOT = "bot"


class TournamentStatus(StrEnum):
    DRAFT = "draft"
    REGISTRATION_OPEN = "registration_open"
    SEATED = "seated"
    RUNNING = "running"
    PAUSE_REQUESTED = "pause_requested"
    PAUSED = "paused"
    BREAK = "break"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TableStatus(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    PAUSE_REQUESTED = "pause_requested"
    PAUSED = "paused"
    COMPLETED = "completed"
    QUARANTINED = "quarantined"


class Street(StrEnum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"
    COMPLETE = "complete"


class ActionType(StrEnum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    RAISE = "raise"


class FailureReason(StrEnum):
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    HTTP_STATUS = "http_status"
    CONTENT_TYPE = "content_type"
    OVERSIZED = "oversized"
    MALFORMED_JSON = "malformed_json"
    SCHEMA = "schema"
    STALE = "stale"
    ILLEGAL_ACTION = "illegal_action"
    RESTART_RECOVERY = "restart_recovery"
    DATABASE = "database"
    ENGINE_INVARIANT = "engine_invariant"


class LegalAction(ContractModel):
    action: ActionType
    amount: int | None = Field(default=None, ge=0)
    min_amount_to: int | None = Field(default=None, ge=0)
    max_amount_to: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_amount_shape(self) -> LegalAction:
        if self.action is ActionType.CALL:
            if self.amount is None or self.min_amount_to is not None or self.max_amount_to is not None:
                raise ValueError("call requires amount and forbids raise bounds")
        elif self.action is ActionType.RAISE:
            if self.min_amount_to is None or self.max_amount_to is None or self.amount is not None:
                raise ValueError("raise requires min_amount_to and max_amount_to")
            if self.min_amount_to > self.max_amount_to:
                raise ValueError("raise minimum cannot exceed maximum")
        elif any(value is not None for value in (self.amount, self.min_amount_to, self.max_amount_to)):
            raise ValueError("fold and check do not accept amounts")
        return self


class PlayerAction(ContractModel):
    decision_id: Identifier
    table_version: int = Field(ge=0)
    seat: int = Field(ge=1, le=6)
    action: ActionType
    amount_to: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_raise_amount(self) -> PlayerAction:
        if self.action is ActionType.RAISE and self.amount_to is None:
            raise ValueError("raise requires amount_to")
        if self.action is not ActionType.RAISE and self.amount_to is not None:
            raise ValueError("only raise accepts amount_to")
        return self


class ActionRecord(ContractModel):
    sequence: int = Field(ge=1)
    decision_id: Identifier
    seat: int = Field(ge=1, le=6)
    action: ActionType
    amount_to: int | None = Field(default=None, ge=0)
    automatic: bool = False
    failure_reason: FailureReason | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SeatState(ContractModel):
    seat: int = Field(ge=1, le=6)
    entrant_id: Identifier
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    kind: EntryKind
    stack: int = Field(ge=0)
    committed_this_street: int = Field(default=0, ge=0)
    committed_this_hand: int = Field(default=0, ge=0)
    folded: bool = False
    all_in: bool = False
    eliminated: bool = False
    hole_cards: tuple[Card, ...] = ()


class SidePot(ContractModel):
    amount: int = Field(ge=0)
    eligible_seats: tuple[int, ...]


class DomainEvent(ContractModel):
    event_type: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    payload: dict[str, Any] = Field(default_factory=dict)


class PendingDecision(ContractModel):
    decision_id: Identifier
    table_id: Identifier
    hand_id: Identifier
    table_version: int = Field(ge=0)
    seat: int = Field(ge=1, le=6)
    deadline_at: datetime
    legal_actions: tuple[LegalAction, ...]


class HandSnapshot(ContractModel):
    ruleset_version: str = "tda-2026-v1"
    adapter_version: str
    tournament_id: Identifier
    table_id: Identifier
    hand_id: Identifier
    hand_number: int = Field(ge=1)
    table_version: int = Field(ge=0)
    street: Street
    button_seat: int = Field(ge=1, le=6)
    small_blind: int = Field(ge=0)
    big_blind: int = Field(gt=0)
    big_blind_ante: int = Field(ge=0)
    deck_order: tuple[Card, ...]
    community_cards: tuple[Card, ...] = ()
    seats: tuple[SeatState, ...]
    pot: int = Field(default=0, ge=0)
    side_pots: tuple[SidePot, ...] = ()
    acting_seat: int | None = Field(default=None, ge=1, le=6)
    legal_actions: tuple[LegalAction, ...] = ()
    action_history: tuple[ActionRecord, ...] = ()
    completed: bool = False
    engine_state: dict[str, Any] = Field(default_factory=dict)


class StartHandRequest(ContractModel):
    tournament_id: Identifier
    table_id: Identifier
    hand_id: Identifier
    hand_number: int = Field(ge=1)
    table_version: int = Field(ge=0)
    button_seat: int = Field(ge=1, le=6)
    small_blind: int = Field(ge=0)
    big_blind: int = Field(gt=0)
    big_blind_ante: int = Field(ge=0)
    seats: tuple[SeatState, ...]
    deck_order: tuple[Card, ...]


class EngineTransition(ContractModel):
    snapshot: HandSnapshot
    events: tuple[DomainEvent, ...] = ()

