from __future__ import annotations

import asyncio
from typing import Protocol

from poker_bot_platform.domain import TournamentStatus
from poker_bot_platform.tournament.models import AuditEntry, TournamentState

ACTIVE_TOURNAMENT_STATUSES = frozenset(
    {
        TournamentStatus.RUNNING,
        TournamentStatus.PAUSE_REQUESTED,
        TournamentStatus.PAUSED,
        TournamentStatus.BREAK,
    }
)


class TournamentStoreError(RuntimeError):
    pass


class TournamentVersionConflict(TournamentStoreError):
    pass


class TournamentStore(Protocol):
    async def create(self, state: TournamentState, audit: AuditEntry) -> None: ...

    async def save(
        self,
        state: TournamentState,
        *,
        expected_revision: int,
        audit: AuditEntry,
    ) -> None: ...

    async def load(self, tournament_id: str) -> TournamentState: ...

    async def list_active_tournament_ids(self) -> tuple[str, ...]: ...


class InMemoryTournamentStore:
    """Atomic tournament-state store for tests and headless local simulations."""

    def __init__(self) -> None:
        self._states: dict[str, TournamentState] = {}
        self._audit: dict[str, list[AuditEntry]] = {}
        self._lock = asyncio.Lock()

    async def create(self, state: TournamentState, audit: AuditEntry) -> None:
        async with self._lock:
            if state.tournament_id in self._states:
                raise TournamentStoreError("tournament already exists")
            self._states[state.tournament_id] = state
            self._audit[state.tournament_id] = [audit]

    async def save(
        self,
        state: TournamentState,
        *,
        expected_revision: int,
        audit: AuditEntry,
    ) -> None:
        async with self._lock:
            current = self._states.get(state.tournament_id)
            if current is None:
                raise TournamentStoreError("tournament does not exist")
            if current.revision != expected_revision:
                raise TournamentVersionConflict(
                    f"expected revision {expected_revision}, found {current.revision}"
                )
            if state.revision != expected_revision + 1:
                raise TournamentVersionConflict("saved state must advance exactly one revision")
            self._states[state.tournament_id] = state
            self._audit[state.tournament_id].append(audit)

    async def load(self, tournament_id: str) -> TournamentState:
        async with self._lock:
            try:
                return self._states[tournament_id]
            except KeyError as exc:
                raise TournamentStoreError("tournament does not exist") from exc

    async def list_active_tournament_ids(self) -> tuple[str, ...]:
        async with self._lock:
            return tuple(
                sorted(
                    tournament_id
                    for tournament_id, state in self._states.items()
                    if state.status in ACTIVE_TOURNAMENT_STATUSES
                )
            )

    def audit_entries(self, tournament_id: str) -> tuple[AuditEntry, ...]:
        return tuple(self._audit.get(tournament_id, ()))
