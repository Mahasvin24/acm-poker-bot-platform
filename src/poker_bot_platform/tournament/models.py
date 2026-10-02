from __future__ import annotations

from pydantic import Field, model_validator

from poker_bot_platform.domain.models import ContractModel, EntryKind, TournamentStatus
from poker_bot_platform.domain.tournament import TournamentConfig


class Entrant(ContractModel):
    entrant_id: str = Field(min_length=1, max_length=128)
    account_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    kind: EntryKind
    bot_verified: bool = False

    @model_validator(mode="after")
    def validate_bot_verification(self) -> Entrant:
        if self.kind is EntryKind.HUMAN and self.bot_verified:
            raise ValueError("human entrants cannot be bot-verified")
        return self


class TournamentPlayer(ContractModel):
    entrant_id: str
    account_id: str
    display_name: str
    kind: EntryKind
    seat: int = Field(ge=1, le=6)
    stack: int = Field(ge=0)


class TournamentTable(ContractModel):
    table_id: str
    players: tuple[TournamentPlayer, ...]
    hand_number: int = Field(default=0, ge=0)
    hand_level_number: int = Field(default=0, ge=0)
    button_seat: int = Field(ge=1, le=6)
    hand_in_progress: bool = False
    start_of_hand_stacks: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_table(self) -> TournamentTable:
        seats = [player.seat for player in self.players]
        entrants = [player.entrant_id for player in self.players]
        if len(seats) != len(set(seats)):
            raise ValueError("table seats must be unique")
        if len(entrants) != len(set(entrants)):
            raise ValueError("table entrants must be unique")
        if not 1 <= len(self.players) <= 6:
            raise ValueError("a tournament table requires one to six players")
        if self.button_seat not in seats:
            raise ValueError("button must be occupied")
        if self.hand_in_progress:
            if self.hand_level_number < 1:
                raise ValueError("active hand must capture its blind level")
            expected = {player.entrant_id for player in self.players}
            if set(self.start_of_hand_stacks) != expected:
                raise ValueError("active hand must capture every starting stack")
        return self


class Standing(ContractModel):
    entrant_id: str
    display_name: str
    position: int = Field(ge=1)
    eliminated_hand_number: int | None = Field(default=None, ge=1)
    start_of_hand_stack: int = Field(ge=0)


class AuditEntry(ContractModel):
    actor_id: str
    command: str
    outcome: str = "accepted"
    detail: str | None = None


class TournamentState(ContractModel):
    tournament_id: str
    config: TournamentConfig
    status: TournamentStatus = TournamentStatus.DRAFT
    seed_hex: str = Field(pattern=r"^[0-9a-f]{64}$")
    entrants: tuple[Entrant, ...] = ()
    tables: tuple[TournamentTable, ...] = ()
    standings: tuple[Standing, ...] = ()
    level_number: int = Field(default=1, ge=1)
    phase_remaining_seconds: int = Field(ge=0)
    break_pending: bool = False
    balance_counter: int = Field(default=0, ge=0)
    revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_tournament(self) -> TournamentState:
        entrant_ids = [entrant.entrant_id for entrant in self.entrants]
        account_ids = [entrant.account_id for entrant in self.entrants]
        if len(entrant_ids) != len(set(entrant_ids)):
            raise ValueError("entrant identifiers must be unique")
        if len(account_ids) != len(set(account_ids)):
            raise ValueError("accounts may enter a tournament only once")
        seated = [player.entrant_id for table in self.tables for player in table.players]
        if len(seated) != len(set(seated)):
            raise ValueError("an entrant cannot occupy multiple tables")
        return self
