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


class TableRepository(Protocol):
    async def create_tournament(
        self,
        tournament_id: str,
        config: dict[str, object],
        *,
        status: TournamentStatus = TournamentStatus.DRAFT,
    ) -> None: ...

    async def create_table(
        self,
        snapshot: HandSnapshot,
        events: tuple[DomainEvent, ...] = (),
        *,
        status: TableStatus = TableStatus.RUNNING,
    ) -> PersistedTableState: ...

    async def load_table(self, table_id: str) -> PersistedTableState: ...

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
