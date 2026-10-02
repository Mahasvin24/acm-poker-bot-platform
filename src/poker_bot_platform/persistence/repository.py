from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from poker_bot_platform.domain import (
    ActionRecord,
    DomainEvent,
    HandSnapshot,
    PendingDecision,
    TableStatus,
    TournamentStatus,
)


class PersistenceError(RuntimeError):
    """A durable operation failed; callers must not advance local state."""


class TableNotFoundError(PersistenceError):
    pass


class VersionConflictError(PersistenceError):
    pass


class DecisionConflictError(PersistenceError):
    pass


class StatusConflictError(PersistenceError):
    pass


@dataclass(frozen=True, slots=True)
class PersistedTournamentState:
    tournament_id: str
    status: TournamentStatus
    config: dict[str, object]
    version: int


@dataclass(frozen=True, slots=True)
class PersistedTableState:
    snapshot: HandSnapshot
    status: TableStatus
    pending: PendingDecision | None = None


@dataclass(frozen=True, slots=True)
class CommitResult:
    snapshot: HandSnapshot
    action: ActionRecord
    idempotent: bool = False


@dataclass(frozen=True, slots=True)
class HandStartCommitResult:
    snapshot: HandSnapshot
    idempotent: bool = False


class TableRepository(Protocol):
    async def create_tournament(
        self,
        tournament_id: str,
        config: dict[str, object],
        *,
        status: TournamentStatus = TournamentStatus.DRAFT,
    ) -> PersistedTournamentState: ...

    async def load_tournament(self, tournament_id: str) -> PersistedTournamentState: ...

    async def update_tournament(
        self,
        tournament_id: str,
        *,
        expected_version: int,
        expected_status: TournamentStatus,
        status: TournamentStatus | None = None,
        config: dict[str, object] | None = None,
    ) -> PersistedTournamentState: ...

    async def create_table(
        self,
        snapshot: HandSnapshot,
        events: tuple[DomainEvent, ...] = (),
        *,
        status: TableStatus = TableStatus.RUNNING,
    ) -> PersistedTableState: ...

    async def load_table(self, table_id: str) -> PersistedTableState: ...

    async def update_table_status(
        self,
        table_id: str,
        *,
        expected_version: int,
        expected_status: TableStatus,
        status: TableStatus,
    ) -> TableStatus: ...

    async def commit_next_hand(
        self,
        *,
        expected_version: int,
        snapshot: HandSnapshot,
        events: tuple[DomainEvent, ...],
    ) -> HandStartCommitResult: ...

    async def create_pending(self, decision: PendingDecision) -> PendingDecision: ...

    async def commit_transition(
        self,
        *,
        expected_version: int,
        snapshot: HandSnapshot,
        action: ActionRecord,
        events: tuple[DomainEvent, ...],
    ) -> CommitResult: ...

    async def append_audit(
        self,
        *,
        actor_id: str,
        command: str,
        outcome: str,
        tournament_id: str | None = None,
        payload: dict[str, object] | None = None,
        detail: str | None = None,
    ) -> None: ...


def utc_now() -> datetime:
    return datetime.now(UTC)
