from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from poker_bot_platform.domain import EntryKind, MatchConfig, MatchStatus
from poker_bot_platform.domain.models import ContractModel

ACTIVE_MATCH_STATUSES = frozenset({MatchStatus.RUNNING, MatchStatus.PAUSE_REQUESTED})
OPEN_MATCH_STATUSES = frozenset(
    {MatchStatus.LOBBY, MatchStatus.RUNNING, MatchStatus.PAUSE_REQUESTED, MatchStatus.PAUSED}
)


class MatchEntry(ContractModel):
    """One seat claimed in the lobby by a human or one of the account's bots."""

    entry_id: str = Field(min_length=1, max_length=128)
    account_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    kind: EntryKind
    bot_profile_id: str | None = None
    joined_at: datetime

    @model_validator(mode="after")
    def validate_kind(self) -> MatchEntry:
        if self.kind is EntryKind.BOT and self.bot_profile_id is None:
            raise ValueError("bot entries require a bot profile")
        if self.kind is EntryKind.HUMAN and self.bot_profile_id is not None:
            raise ValueError("human entries cannot reference a bot profile")
        return self


class MatchPlayer(ContractModel):
    entry_id: str
    account_id: str
    display_name: str
    kind: EntryKind
    bot_profile_id: str | None = None
    seat: int = Field(ge=1, le=6)
    stack: int = Field(ge=0)


class MatchTable(ContractModel):
    table_id: str
    players: tuple[MatchPlayer, ...]
    hand_number: int = Field(default=0, ge=0)
    hand_level_number: int = Field(default=0, ge=0)
    button_seat: int = Field(ge=1, le=6)
    hand_in_progress: bool = False
    quarantined: bool = False
    start_of_hand_stacks: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_table(self) -> MatchTable:
        seats = [player.seat for player in self.players]
        entries = [player.entry_id for player in self.players]
        if len(seats) != len(set(seats)):
            raise ValueError("table seats must be unique")
        if len(entries) != len(set(entries)):
            raise ValueError("table entries must be unique")
        if not 1 <= len(self.players) <= 6:
            raise ValueError("a match table requires one to six players")
        if self.button_seat not in seats:
            raise ValueError("button must be occupied")
        if self.quarantined and self.hand_in_progress:
            raise ValueError("a quarantined table cannot have a hand in progress")
        if self.hand_in_progress:
            if self.hand_level_number < 1:
                raise ValueError("active hand must capture its blind level")
            if set(self.start_of_hand_stacks) != set(entries):
                raise ValueError("active hand must capture every starting stack")
        return self


class Standing(ContractModel):
    entry_id: str
    display_name: str
    kind: EntryKind
    position: int = Field(ge=1)
    eliminated_hand_number: int | None = Field(default=None, ge=1)
    final_stack: int = Field(ge=0)


class AuditEntry(ContractModel):
    actor_id: str
    command: str
    outcome: str = "accepted"
    detail: str | None = None


class MatchState(ContractModel):
    match_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=80)
    join_code: str | None = None
    config: MatchConfig
    status: MatchStatus = MatchStatus.LOBBY
    seed_hex: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: str
    created_at: datetime
    entries: tuple[MatchEntry, ...] = ()
    table: MatchTable | None = None
    standings: tuple[Standing, ...] = ()
    level_number: int = Field(default=1, ge=1)
    level_remaining_seconds: int | None = Field(default=None, ge=0)
    end_requested: bool = False
    revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_match(self) -> MatchState:
        entry_ids = [entry.entry_id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("entry identifiers must be unique")
        human_accounts = [
            entry.account_id for entry in self.entries if entry.kind is EntryKind.HUMAN
        ]
        if len(human_accounts) != len(set(human_accounts)):
            raise ValueError("an account may hold only one human seat per match")
        bot_profiles = [entry.bot_profile_id for entry in self.entries if entry.bot_profile_id]
        if len(bot_profiles) != len(set(bot_profiles)):
            raise ValueError("a bot may hold only one seat per match")
        if len(self.entries) > self.config.max_seats:
            raise ValueError("match has more entries than seats")
        if self.status is MatchStatus.LOBBY and self.table is not None:
            raise ValueError("a lobby match cannot have a table")
        return self

    @property
    def players_remaining(self) -> int:
        return len(self.table.players) if self.table is not None else len(self.entries)

    def entry(self, entry_id: str) -> MatchEntry | None:
        return next((item for item in self.entries if item.entry_id == entry_id), None)
