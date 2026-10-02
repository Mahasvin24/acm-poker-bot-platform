from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address

from poker_bot_platform.api.models import (
    AdminCommandResponse,
    PlayerActionRequest,
    PlayerDecisionResponse,
    PlayerTableStateResponse,
    PublicPlayerActionResponse,
    PublicPlayerSeatResponse,
    PublicSidePotResponse,
)
from poker_bot_platform.auth.repository import AuthRepository
from poker_bot_platform.bots import BotEndpoint, BotGateway
from poker_bot_platform.bots.tokens import EncryptedTokenStore
from poker_bot_platform.coordinator import (
    ActorDecisionFailure,
    InvalidActionError,
    TableCoordinator,
)
from poker_bot_platform.domain import (
    EntryKind,
    FailureReason,
    HandSnapshot,
    PendingDecision,
    PlayerAction,
    TournamentConfig,
    TournamentStatus,
)
from poker_bot_platform.engine import PokerKitEngine
from poker_bot_platform.integration.actors import BotActor
from poker_bot_platform.integration.services import (
    AdminCoordinatorService,
    TournamentRegistry,
)
from poker_bot_platform.persistence import TableNotFoundError, TableRepository
from poker_bot_platform.tournament import (
    TournamentCoordinator,
    TournamentPlayer,
    TournamentStoreError,
)

Clock = Callable[[], datetime]
TableActor = Callable[[PendingDecision, HandSnapshot], Awaitable[PlayerAction]]


class GameplayError(RuntimeError):
    pass


class GameplayNotFoundError(GameplayError):
    pass


class GameplayAccessError(GameplayError):
    pass


class GameplayConflictError(GameplayError):
    pass


class HeadlessGameplayRuntime:
    """Runs durable table coordinators until each table needs a human action.

    A tournament lock serializes scheduling and player commands in this single-process
    deployment. Individual tables are driven concurrently, and a bot HTTP request is
    made only after its pending decision has been committed by ``TableCoordinator``.
    """

    def __init__(
        self,
        tournaments: TournamentRegistry,
        tables: TableRepository,
        accounts: AuthRepository,
        token_store: EncryptedTokenStore,
        gateway: BotGateway,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._tournaments = tournaments
        self._tables = tables
        self._accounts = accounts
        self._token_store = token_store
        self._gateway = gateway
        self._clock = clock or (lambda: datetime.now(UTC))
        self._coordinators: dict[str, TableCoordinator] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def synchronize(self, tournament_id: str) -> None:
        lock = await self._lock_for(tournament_id)
        async with lock:
            tournament = await self._get_tournament(tournament_id)
            await self._synchronize_locked(tournament)

    async def player_state(
        self,
        account_id: str,
        tournament_id: str,
    ) -> PlayerTableStateResponse:
        lock = await self._lock_for(tournament_id)
        async with lock:
            tournament = await self._get_tournament(tournament_id)
            await self._synchronize_locked(tournament)
            player, table_id = await self._locate_player(
                tournament,
                account_id,
                tournament_id,
            )
            coordinator = self._coordinators.get(table_id)
            if coordinator is None or coordinator.state.snapshot is None:
                raise GameplayNotFoundError("table state is not available")
            return self._project(tournament, coordinator, player)

    async def submit_human_action(
        self,
        account_id: str,
        tournament_id: str,
        request: PlayerActionRequest,
    ) -> PlayerTableStateResponse:
        lock = await self._lock_for(tournament_id)
        async with lock:
            tournament = await self._get_tournament(tournament_id)
            await self._synchronize_locked(tournament)
            player, table_id = await self._locate_player(
                tournament,
                account_id,
                tournament_id,
            )
            if player.kind is not EntryKind.HUMAN:
                raise GameplayAccessError("bot entrants cannot submit human actions")
            coordinator = self._coordinators.get(table_id)
            if coordinator is None or coordinator.state.snapshot is None:
                raise GameplayNotFoundError("table state is not available")
            pending = coordinator.state.pending
            if pending is None or pending.seat != player.seat:
                raise GameplayConflictError("player does not have the pending decision")
            try:
                await coordinator.submit_action(
                    PlayerAction(
                        decision_id=request.decision_id,
                        table_version=request.table_version,
                        seat=player.seat,
                        action=request.action,
                        amount_to=request.amount_to,
                    )
                )
            except InvalidActionError as exc:
                raise GameplayConflictError(str(exc)) from exc

            await self._synchronize_locked(tournament)
            player, table_id = await self._locate_player(
                tournament,
                account_id,
                tournament_id,
            )
            coordinator = self._coordinators.get(table_id)
            if coordinator is None or coordinator.state.snapshot is None:
                raise GameplayNotFoundError("table state is not available")
            return self._project(tournament, coordinator, player)

    async def _synchronize_locked(self, tournament: TournamentCoordinator) -> None:
        while tournament.state.status in {
            TournamentStatus.RUNNING,
            TournamentStatus.PAUSE_REQUESTED,
        }:
            scheduled = tuple(table for table in tournament.state.tables if table.hand_in_progress)
            if not scheduled:
                return
            await asyncio.gather(
                *(self._drive_table(tournament, table.table_id) for table in scheduled)
            )
            current = tuple(table for table in tournament.state.tables if table.hand_in_progress)
            if not current:
                return
            if not any(
                self._hand_needs_dispatch(table.table_id, table.hand_number) for table in current
            ):
                return

    async def _drive_table(
        self,
        tournament: TournamentCoordinator,
        table_id: str,
    ) -> None:
        coordinator = await self._ensure_scheduled_hand(tournament, table_id)
        while True:
            snapshot = coordinator.state.snapshot
            if snapshot is None:
                raise GameplayConflictError("table coordinator has no snapshot")
            if snapshot.completed:
                await tournament.record_hand_completed(
                    table_id,
                    {seat.entrant_id: seat.stack for seat in snapshot.seats},
                )
                return
            acting = next(
                (seat for seat in snapshot.seats if seat.seat == snapshot.acting_seat),
                None,
            )
            if acting is None:
                raise GameplayConflictError("acting seat is missing from the table")
            if acting.kind is EntryKind.BOT:
                actor = await self._bot_actor(acting.entrant_id)
                bot_timeout = timedelta(milliseconds=tournament.state.config.bot_action_timeout_ms)
                await coordinator.request_actor_action(actor, self._now() + bot_timeout)
                continue

            pending = coordinator.state.pending
            if pending is None:
                human_timeout = timedelta(
                    milliseconds=tournament.state.config.human_action_timeout_ms
                )
                pending = await coordinator.open_decision(self._now() + human_timeout)
            if pending.seat != acting.seat:
                raise GameplayConflictError("pending decision does not match the acting seat")
            if self._now() >= pending.deadline_at:
                await coordinator.expire_decision()
                continue
            return

    async def _ensure_scheduled_hand(
        self,
        tournament: TournamentCoordinator,
        table_id: str,
    ) -> TableCoordinator:
        table = next(
            (item for item in tournament.state.tables if item.table_id == table_id),
            None,
        )
        if table is None or not table.hand_in_progress:
            raise GameplayConflictError("table has no scheduled hand")
        coordinator = await self._ensure_coordinator(table_id)
        snapshot = coordinator.state.snapshot
        expected_hand_id = f"{table_id}-hand-{table.hand_number}"
        if snapshot is None or snapshot.hand_id != expected_hand_id:
            if snapshot is not None and not snapshot.completed:
                raise GameplayConflictError("a different hand is already active at the table")
            await tournament.dispatch_hand(table_id, coordinator)
        return coordinator

    async def _ensure_coordinator(self, table_id: str) -> TableCoordinator:
        existing = self._coordinators.get(table_id)
        if existing is not None:
            return existing
        coordinator = TableCoordinator(
            table_id,
            PokerKitEngine(),
            self._tables,
            clock=self._clock,
        )
        try:
            await coordinator.restore()
        except TableNotFoundError:
            pass
        self._coordinators[table_id] = coordinator
        return coordinator

    async def _bot_actor(self, entrant_id: str) -> TableActor:
        entrant = await self._accounts.get_entrant_by_id(entrant_id)
        if (
            entrant is None
            or entrant.kind is not EntryKind.BOT
            or entrant.bot_ip is None
            or entrant.bot_port is None
            or entrant.bot_token_ciphertext is None
            or entrant.bot_verified_at is None
        ):
            return _unavailable_bot
        try:
            token = self._token_store.decrypt(entrant.bot_token_ciphertext)
            endpoint = BotEndpoint(ip=ip_address(entrant.bot_ip), port=entrant.bot_port)
        except ValueError:
            return _unavailable_bot
        return BotActor(self._gateway, endpoint, token)

    async def _locate_player(
        self,
        tournament: TournamentCoordinator,
        account_id: str,
        tournament_id: str,
    ) -> tuple[TournamentPlayer, str]:
        entrant = await self._accounts.get_entrant(account_id, tournament_id)
        if entrant is None:
            raise GameplayAccessError("account is not entered in this tournament")
        for table in tournament.state.tables:
            for player in table.players:
                if player.entrant_id == entrant.id:
                    return player, table.table_id
        raise GameplayNotFoundError("entrant does not have an active table")

    def _project(
        self,
        tournament: TournamentCoordinator,
        coordinator: TableCoordinator,
        player: TournamentPlayer,
    ) -> PlayerTableStateResponse:
        snapshot = coordinator.state.snapshot
        assert snapshot is not None
        pending = coordinator.state.pending
        decision = None
        if pending is not None and pending.seat == player.seat:
            decision = PlayerDecisionResponse(
                decision_id=pending.decision_id,
                table_version=pending.table_version,
                deadline_at=pending.deadline_at,
                legal_actions=pending.legal_actions,
            )
        return PlayerTableStateResponse(
            tournament_id=snapshot.tournament_id,
            tournament_status=tournament.state.status,
            table_id=snapshot.table_id,
            hand_id=snapshot.hand_id,
            hand_number=snapshot.hand_number,
            table_version=snapshot.table_version,
            street=snapshot.street,
            button_seat=snapshot.button_seat,
            small_blind=snapshot.small_blind,
            big_blind=snapshot.big_blind,
            big_blind_ante=snapshot.big_blind_ante,
            community_cards=snapshot.community_cards,
            seats=tuple(
                PublicPlayerSeatResponse(
                    seat=seat.seat,
                    entrant_id=seat.entrant_id,
                    display_name=seat.display_name,
                    kind=seat.kind,
                    stack=seat.stack,
                    committed_this_street=seat.committed_this_street,
                    committed_this_hand=seat.committed_this_hand,
                    folded=seat.folded,
                    all_in=seat.all_in,
                    eliminated=seat.eliminated,
                    hole_cards=seat.hole_cards if seat.entrant_id == player.entrant_id else (),
                )
                for seat in snapshot.seats
            ),
            pot=snapshot.pot,
            side_pots=tuple(
                PublicSidePotResponse(
                    amount=pot.amount,
                    eligible_seats=pot.eligible_seats,
                )
                for pot in snapshot.side_pots
            ),
            action_history=tuple(
                PublicPlayerActionResponse(
                    sequence=action.sequence,
                    seat=action.seat,
                    action=action.action,
                    amount_to=action.amount_to,
                    automatic=action.automatic,
                )
                for action in snapshot.action_history
            ),
            completed=snapshot.completed,
            decision=decision,
        )

    def _hand_needs_dispatch(self, table_id: str, hand_number: int) -> bool:
        coordinator = self._coordinators.get(table_id)
        snapshot = coordinator.state.snapshot if coordinator is not None else None
        return snapshot is None or snapshot.hand_id != f"{table_id}-hand-{hand_number}"

    async def _lock_for(self, tournament_id: str) -> asyncio.Lock:
        lock = self._locks.get(tournament_id)
        if lock is not None:
            return lock
        async with self._locks_guard:
            return self._locks.setdefault(tournament_id, asyncio.Lock())

    async def _get_tournament(self, tournament_id: str) -> TournamentCoordinator:
        try:
            return await self._tournaments.get(tournament_id)
        except TournamentStoreError as exc:
            raise GameplayNotFoundError("tournament does not exist") from exc

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("gameplay clock must return a timezone-aware datetime")
        return value


async def _unavailable_bot(
    _pending: PendingDecision,
    _snapshot: HandSnapshot,
) -> PlayerAction:
    raise ActorDecisionFailure(FailureReason.CONNECTION)


@dataclass(slots=True)
class RuntimeAdminCoordinatorService:
    """Adds hand dispatch to the durable tournament admin state machine."""

    base: AdminCoordinatorService
    gameplay: HeadlessGameplayRuntime
    tournaments: TournamentRegistry

    async def create_tournament(
        self,
        tournament_id: str,
        config: TournamentConfig,
        actor_id: str,
    ) -> AdminCommandResponse:
        return await self.base.create_tournament(tournament_id, config, actor_id)

    async def update_draft(
        self,
        tournament_id: str,
        config: TournamentConfig,
        actor_id: str,
    ) -> AdminCommandResponse:
        return await self.base.update_draft(tournament_id, config, actor_id)

    async def open_registration(
        self,
        tournament_id: str,
        actor_id: str,
    ) -> AdminCommandResponse:
        return await self.base.open_registration(tournament_id, actor_id)

    async def seat(self, tournament_id: str, actor_id: str) -> AdminCommandResponse:
        return await self.base.seat(tournament_id, actor_id)

    async def start(
        self,
        tournament_id: str,
        actor_id: str,
    ) -> AdminCommandResponse:
        await self.base.start(tournament_id, actor_id)
        await self.gameplay.synchronize(tournament_id)
        return await self._response(tournament_id)

    async def pause(self, tournament_id: str, actor_id: str) -> AdminCommandResponse:
        return await self.base.pause(tournament_id, actor_id)

    async def resume(
        self,
        tournament_id: str,
        actor_id: str,
    ) -> AdminCommandResponse:
        await self.base.resume(tournament_id, actor_id)
        await self.gameplay.synchronize(tournament_id)
        return await self._response(tournament_id)

    async def advance_level(self, tournament_id: str, actor_id: str) -> AdminCommandResponse:
        return await self.base.advance_level(tournament_id, actor_id)

    async def _response(self, tournament_id: str) -> AdminCommandResponse:
        state = (await self.tournaments.get(tournament_id)).state
        return AdminCommandResponse(
            tournament_id=state.tournament_id,
            status=state.status.value,
        )
