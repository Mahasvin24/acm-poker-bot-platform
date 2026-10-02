from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import HTTPException, status

from poker_bot_platform.api.models import AdminCommandResponse
from poker_bot_platform.auth.models import Entrant as AccountEntrant
from poker_bot_platform.auth.repository import AuthConflictError
from poker_bot_platform.auth.service import BotRegistrationResult, EntrantService
from poker_bot_platform.domain import EntryKind, TournamentConfig, TournamentStatus
from poker_bot_platform.persistence import TableRepository
from poker_bot_platform.tournament import (
    Entrant,
    TournamentCoordinator,
    TournamentError,
    TournamentState,
    TournamentStore,
    TournamentStoreError,
)


class TournamentRegistry:
    """Single-process owner and resolver for tournament coordinators."""

    def __init__(self, store: TournamentStore, tables: TableRepository) -> None:
        self._store = store
        self._tables = tables
        self._coordinators: dict[str, TournamentCoordinator] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        tournament_id: str,
        config: TournamentConfig,
        *,
        actor_id: str,
    ) -> TournamentCoordinator:
        async with self._lock:
            if tournament_id in self._coordinators:
                raise TournamentError("tournament already exists")
            coordinator = await TournamentCoordinator.create(
                tournament_id,
                config,
                self._store,
                self._tables,
                actor_id=actor_id,
            )
            self._coordinators[tournament_id] = coordinator
            return coordinator

    async def get(self, tournament_id: str) -> TournamentCoordinator:
        coordinator = self._coordinators.get(tournament_id)
        if coordinator is not None:
            return coordinator
        async with self._lock:
            coordinator = self._coordinators.get(tournament_id)
            if coordinator is None:
                coordinator = await TournamentCoordinator.restore(
                    tournament_id,
                    self._store,
                    self._tables,
                )
                self._coordinators[tournament_id] = coordinator
            return coordinator


@dataclass(slots=True)
class SyncedEntrantService:
    """Keeps account ownership and tournament seating state in agreement."""

    accounts: EntrantService
    tournaments: TournamentRegistry

    async def register(
        self,
        account_id: str,
        tournament_id: str,
        kind: EntryKind,
        display_name: str,
    ) -> AccountEntrant:
        coordinator = await self._registration_coordinator(tournament_id)
        entrant = await self.accounts.register(account_id, tournament_id, kind, display_name)
        try:
            await coordinator.register(
                Entrant(
                    entrant_id=entrant.id,
                    account_id=entrant.account_id,
                    display_name=entrant.display_name,
                    kind=entrant.kind,
                ),
                actor_id=account_id,
            )
        except TournamentError as exc:
            await self.accounts.repository.delete_entrant(entrant.id)
            raise AuthConflictError(str(exc)) from exc
        return entrant

    async def configure_bot(
        self,
        account_id: str,
        tournament_id: str,
        ip: str,
        port: int,
    ) -> BotRegistrationResult:
        await self._registration_coordinator(tournament_id)
        return await self.accounts.configure_bot(account_id, tournament_id, ip, port)

    async def verify_bot(self, account_id: str, tournament_id: str) -> AccountEntrant:
        coordinator = await self._registration_coordinator(tournament_id)
        entrant = await self.accounts.verify_bot(account_id, tournament_id)
        try:
            await coordinator.verify_bot(entrant.id, actor_id=account_id)
        except TournamentError as exc:
            raise AuthConflictError(str(exc)) from exc
        return entrant

    async def _registration_coordinator(self, tournament_id: str) -> TournamentCoordinator:
        try:
            coordinator = await self.tournaments.get(tournament_id)
        except TournamentStoreError as exc:
            raise AuthConflictError("tournament does not exist") from exc
        if coordinator.state.status is not TournamentStatus.REGISTRATION_OPEN:
            raise AuthConflictError("tournament registration is not open")
        return coordinator


@dataclass(slots=True)
class AdminCoordinatorService:
    tournaments: TournamentRegistry

    async def create_tournament(
        self,
        tournament_id: str,
        config: TournamentConfig,
        actor_id: str,
    ) -> AdminCommandResponse:
        return await self._run_create(tournament_id, config, actor_id)

    async def update_draft(
        self,
        tournament_id: str,
        config: TournamentConfig,
        actor_id: str,
    ) -> AdminCommandResponse:
        return await self._run(
            tournament_id,
            lambda item: item.update_config(config, actor_id=actor_id),
        )

    async def open_registration(self, tournament_id: str, actor_id: str) -> AdminCommandResponse:
        return await self._run(
            tournament_id,
            lambda item: item.open_registration(actor_id=actor_id),
        )

    async def seat(self, tournament_id: str, actor_id: str) -> AdminCommandResponse:
        return await self._run(
            tournament_id,
            lambda item: item.seat_entrants(actor_id=actor_id),
        )

    async def start(self, tournament_id: str, actor_id: str) -> AdminCommandResponse:
        return await self._run(
            tournament_id,
            lambda item: item.start(actor_id=actor_id),
        )

    async def pause(self, tournament_id: str, actor_id: str) -> AdminCommandResponse:
        return await self._run(
            tournament_id,
            lambda item: item.request_pause(actor_id=actor_id),
        )

    async def resume(self, tournament_id: str, actor_id: str) -> AdminCommandResponse:
        return await self._run(
            tournament_id,
            lambda item: item.resume(actor_id=actor_id),
        )

    async def advance_level(self, tournament_id: str, actor_id: str) -> AdminCommandResponse:
        return await self._run(
            tournament_id,
            lambda item: item.advance_level(actor_id=actor_id),
        )

    async def _run_create(
        self,
        tournament_id: str,
        config: TournamentConfig,
        actor_id: str,
    ) -> AdminCommandResponse:
        try:
            coordinator = await self.tournaments.create(
                tournament_id,
                config,
                actor_id=actor_id,
            )
        except (TournamentError, TournamentStoreError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return self._response(coordinator)

    async def _run(
        self,
        tournament_id: str,
        command: Callable[[TournamentCoordinator], Awaitable[TournamentState]],
    ) -> AdminCommandResponse:
        try:
            coordinator = await self.tournaments.get(tournament_id)
            state = await command(coordinator)
        except TournamentStoreError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except (TournamentError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return AdminCommandResponse(
            tournament_id=state.tournament_id,
            status=state.status.value,
        )

    @staticmethod
    def _response(coordinator: TournamentCoordinator) -> AdminCommandResponse:
        return AdminCommandResponse(
            tournament_id=coordinator.state.tournament_id,
            status=coordinator.state.status.value,
        )
