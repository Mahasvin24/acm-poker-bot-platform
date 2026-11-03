from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from typing import Literal

from poker_bot_platform.api.models import (
    BotDecisionLogResponse,
    LastHandResponse,
    MatchContextResponse,
    PlayerActionRequest,
    PlayerDecisionResponse,
    PlayerTableStateResponse,
    PublicPlayerActionResponse,
    PublicPlayerSeatResponse,
    PublicSidePotResponse,
    PublicTurnResponse,
    StandingResponse,
    ViewerResponse,
)
from poker_bot_platform.auth.models import BotProfile
from poker_bot_platform.auth.repository import AuthRepository
from poker_bot_platform.bots import BotEndpoint, BotGateway
from poker_bot_platform.bots.messages import explain_failure
from poker_bot_platform.bots.tokens import EncryptedTokenStore
from poker_bot_platform.coordinator import (
    ActorDecisionFailure,
    CoordinatorNotReadyError,
    EngineInvariantError,
    InvalidActionError,
    TableCoordinator,
)
from poker_bot_platform.domain import (
    BOT_ACTION_TIMEOUT_MS,
    EntryKind,
    FailureReason,
    HandSnapshot,
    MatchStatus,
    PendingDecision,
    PlayerAction,
    TableStatus,
)
from poker_bot_platform.engine import PokerEngine, PokerKitEngine
from poker_bot_platform.integration.actors import BotActor
from poker_bot_platform.integration.presentation import natural_hand_result
from poker_bot_platform.match import (
    MatchCoordinator,
    MatchEntry,
    MatchError,
    MatchRegistry,
    MatchState,
    MatchStoreError,
    MatchTable,
)
from poker_bot_platform.persistence import PersistenceError, TableNotFoundError, TableRepository

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]
TableActor = Callable[[PendingDecision, HandSnapshot], Awaitable[PlayerAction]]
EngineFactory = Callable[[], PokerEngine]

_DRIVING_STATUSES = frozenset({MatchStatus.RUNNING, MatchStatus.PAUSE_REQUESTED})
_BREAKER_REASONS = frozenset(
    {FailureReason.CONNECTION, FailureReason.TIMEOUT, FailureReason.HTTP_STATUS}
)
_PROFILE_CACHE_SECONDS = 30.0
_MAX_STEPS_PER_DRIVE = 64


class GameplayError(RuntimeError):
    pass


class GameplayNotFoundError(GameplayError):
    pass


class GameplayAccessError(GameplayError):
    pass


class GameplayConflictError(GameplayError):
    pass


class GameplayUnavailableError(GameplayError):
    pass


@dataclass(frozen=True, slots=True)
class PacingConfig:
    """Presentation pauses that let humans follow the table; bots never see them."""

    deal_seconds: float = 3.0
    action_seconds: float = 1.5
    street_seconds: float = 2.5
    hand_end_seconds: float = 5.0
    away_after_timeouts: int = 2
    away_timeout_ms: int = 5_000
    breaker_failures: int = 3
    health_probe_seconds: float = 0.5


@dataclass(slots=True)
class _TableRuntime:
    next_action_at: datetime | None = None
    retry_at: datetime | None = None
    backoff_seconds: float = 0.0
    last_hand: LastHandResponse | None = None
    decision_durations: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class BotStats:
    decisions: int = 0
    consecutive_failures: int = 0
    failures: Counter[str] = field(default_factory=Counter)
    recent: deque[BotDecisionLogResponse] = field(default_factory=lambda: deque(maxlen=50))


@dataclass(frozen=True, slots=True)
class EntryActivity:
    last_seen_at: datetime | None
    away: bool


class MatchRuntime:
    """Drives match tables and projects safe per-viewer table state.

    Only the scheduler calls :meth:`drive`, serialized per match. Reads never take the
    drive lock, so a slow bot request cannot stall another player's poll. A bot HTTP
    request is made only after its pending decision has been committed by
    ``TableCoordinator``.
    """

    def __init__(
        self,
        registry: MatchRegistry,
        tables: TableRepository,
        accounts: AuthRepository,
        token_store: EncryptedTokenStore,
        gateway: BotGateway,
        *,
        clock: Clock | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        engine_factory: EngineFactory = PokerKitEngine,
        pacing: PacingConfig | None = None,
    ) -> None:
        self._registry = registry
        self._tables = tables
        self._accounts = accounts
        self._token_store = token_store
        self._gateway = gateway
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic
        self._engine_factory = engine_factory
        self.pacing = pacing or PacingConfig()
        self._coordinators: dict[str, TableCoordinator] = {}
        self._coordinator_locks: dict[str, asyncio.Lock] = {}
        self._drive_locks: dict[str, asyncio.Lock] = {}
        self._tables_runtime: dict[str, _TableRuntime] = {}
        self._last_seen: dict[str, datetime] = {}
        self._timeouts: dict[str, int] = {}
        self._away: set[str] = set()
        self._bot_stats: dict[str, BotStats] = {}
        self._profiles: dict[str, tuple[BotProfile | None, float]] = {}
        self._wake: Callable[[], None] = lambda: None

    def set_wake_callback(self, wake: Callable[[], None]) -> None:
        self._wake = wake

    def wake(self) -> None:
        self._wake()

    # Read path

    async def player_state(self, account_id: str, match_id: str) -> PlayerTableStateResponse:
        match = await self._match(match_id)
        state = match.state
        entry = _viewer_entry(state, account_id)
        if entry is None:
            raise GameplayAccessError("you have not joined this match")
        if entry.kind is EntryKind.HUMAN:
            self._last_seen[entry.entry_id] = self._now()
        return await self._table_view(state, entry)

    async def spectator_state(self, match_id: str) -> PlayerTableStateResponse:
        match = await self._match(match_id)
        return await self._table_view(match.state, None)

    def entry_activity(self, entry_id: str) -> EntryActivity:
        return EntryActivity(
            last_seen_at=self._last_seen.get(entry_id),
            away=entry_id in self._away,
        )

    def bot_stats(self, profile_id: str) -> BotStats:
        return self._bot_stats.get(profile_id) or BotStats()

    # Human commands

    async def submit_human_action(
        self,
        account_id: str,
        match_id: str,
        request: PlayerActionRequest,
    ) -> PlayerTableStateResponse:
        match = await self._match(match_id)
        state = match.state
        entry = next(
            (
                item
                for item in state.entries
                if item.account_id == account_id and item.kind is EntryKind.HUMAN
            ),
            None,
        )
        if entry is None:
            raise GameplayAccessError("only your human seat can act at this table")
        table = state.table
        if table is None or state.status not in _DRIVING_STATUSES:
            raise GameplayConflictError("the match is not in play")
        player = next((item for item in table.players if item.entry_id == entry.entry_id), None)
        if player is None:
            raise GameplayConflictError("you are no longer seated in this match")
        coordinator = await self._coordinator(table.table_id)
        snapshot = coordinator.state.snapshot
        pending = coordinator.state.pending
        if snapshot is None or coordinator.state.status is TableStatus.QUARANTINED:
            raise GameplayConflictError("the table is not accepting actions")
        if pending is None or pending.seat != player.seat:
            raise GameplayConflictError("it is not your turn")
        try:
            after = await coordinator.submit_action(
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
        except EngineInvariantError as exc:
            await self._quarantine(match, table.table_id)
            raise GameplayConflictError("the table was quarantined after an engine error") from exc
        except PersistenceError as exc:
            self._database_failed(table.table_id)
            raise GameplayUnavailableError("the table is reconnecting to the database") from exc
        except CoordinatorNotReadyError as exc:
            if coordinator.state.database_paused:
                self._database_failed(table.table_id)
                raise GameplayUnavailableError("the table is reconnecting to the database") from exc
            raise GameplayConflictError(str(exc)) from exc
        # No await between the commit above and setting the pause, so the scheduler
        # cannot open the next decision before the presentation delay is recorded.
        self._timeouts.pop(entry.entry_id, None)
        self._away.discard(entry.entry_id)
        self._last_seen[entry.entry_id] = self._now()
        self._pace(self._runtime(table.table_id), table, snapshot, after)
        self._wake()
        return await self._table_view(match.state, entry)

    # Scheduler path

    async def drive(self, match_id: str) -> None:
        lock = self._drive_locks.setdefault(match_id, asyncio.Lock())
        if lock.locked():
            return
        async with lock:
            match = await self._registry.get(match_id)
            for _ in range(_MAX_STEPS_PER_DRIVE):
                if not await self._step(match):
                    return

    async def _step(self, match: MatchCoordinator) -> bool:
        state = match.state
        table = state.table
        if state.status not in _DRIVING_STATUSES or table is None or table.quarantined:
            return False
        runtime = self._runtime(table.table_id)
        now = self._now()
        if runtime.retry_at is not None and now < runtime.retry_at:
            return False
        try:
            progressed = await self._step_table(match, table, runtime, now)
        except EngineInvariantError:
            await self._quarantine(match, table.table_id)
            return False
        except PersistenceError:
            logger.exception("table persistence failed", extra={"table": table.table_id})
            self._database_failed(table.table_id)
            return False
        except CoordinatorNotReadyError:
            coordinator = self._coordinators.get(table.table_id)
            if coordinator is not None and coordinator.state.database_paused:
                self._database_failed(table.table_id)
            else:
                logger.exception("table coordinator was not ready", extra={"table": table.table_id})
            return False
        except (MatchStoreError, MatchError):
            logger.exception("match state update failed", extra={"match": state.match_id})
            self._back_off(runtime, now)
            return False
        runtime.backoff_seconds = 0.0
        runtime.retry_at = None
        return progressed

    async def _step_table(
        self,
        match: MatchCoordinator,
        table: MatchTable,
        runtime: _TableRuntime,
        now: datetime,
    ) -> bool:
        coordinator = await self._coordinator(table.table_id)
        if coordinator.state.database_paused:
            self._database_failed(table.table_id)
            return False
        if coordinator.state.status is TableStatus.QUARANTINED:
            await self._quarantine(match, table.table_id)
            return False
        snapshot = coordinator.state.snapshot
        expected_hand_id = f"{table.table_id}-hand-{table.hand_number}"

        if table.hand_in_progress and (snapshot is None or snapshot.hand_id != expected_hand_id):
            if snapshot is not None and not snapshot.completed:
                logger.error("table has an unexpected unfinished hand", extra={"table": table})
                return False
            if runtime.next_action_at is not None and now < runtime.next_action_at:
                return False
            await match.dispatch_hand(coordinator)
            runtime.next_action_at = (
                now + timedelta(seconds=self.pacing.deal_seconds) if _has_human(table) else None
            )
            return True
        if snapshot is None:
            return False

        if snapshot.completed:
            if not table.hand_in_progress or snapshot.hand_id != expected_hand_id:
                return False
            result = natural_hand_result(snapshot)
            if result is not None:
                runtime.last_hand = LastHandResponse(
                    hand_number=snapshot.hand_number,
                    community_cards=snapshot.community_cards,
                    result=result,
                    names={seat.seat: seat.display_name for seat in snapshot.seats},
                )
            runtime.decision_durations.clear()
            await match.record_hand_completed(
                table.table_id,
                {seat.entrant_id: seat.stack for seat in snapshot.seats},
            )
            runtime.next_action_at = (
                now + timedelta(seconds=self.pacing.hand_end_seconds) if _has_human(table) else None
            )
            return True

        if runtime.next_action_at is not None and now < runtime.next_action_at:
            return False
        runtime.next_action_at = None
        acting = next((seat for seat in snapshot.seats if seat.seat == snapshot.acting_seat), None)
        if acting is None:
            logger.error("acting seat is missing", extra={"table": table.table_id})
            return False
        player = next((p for p in table.players if p.entry_id == acting.entrant_id), None)

        if acting.kind is EntryKind.BOT:
            profile_id = player.bot_profile_id if player is not None else None
            actor = await self._bot_actor(profile_id)
            started = self._monotonic()
            after = await coordinator.request_actor_action(
                actor,
                now + timedelta(milliseconds=BOT_ACTION_TIMEOUT_MS),
            )
            self._record_bot_decision(
                profile_id,
                table,
                after,
                latency_ms=int((self._monotonic() - started) * 1000),
            )
            self._pace(runtime, table, snapshot, after)
            return True

        pending = coordinator.state.pending
        if pending is None:
            away = acting.entrant_id in self._away
            duration_ms = (
                min(self.pacing.away_timeout_ms, match.state.config.human_action_timeout_ms)
                if away
                else match.state.config.human_action_timeout_ms
            )
            pending = await coordinator.open_decision(now + timedelta(milliseconds=duration_ms))
            runtime.decision_durations[pending.decision_id] = duration_ms
            return False
        if now < pending.deadline_at:
            return False
        after = await coordinator.expire_decision()
        timeouts = self._timeouts.get(acting.entrant_id, 0) + 1
        self._timeouts[acting.entrant_id] = timeouts
        if timeouts >= self.pacing.away_after_timeouts:
            self._away.add(acting.entrant_id)
        self._pace(runtime, table, snapshot, after)
        return True

    # Helpers

    async def _match(self, match_id: str) -> MatchCoordinator:
        try:
            return await self._registry.get(match_id)
        except MatchStoreError as exc:
            raise GameplayNotFoundError("match does not exist") from exc

    async def _table_view(
        self,
        state: MatchState,
        entry: MatchEntry | None,
    ) -> PlayerTableStateResponse:
        if state.status is MatchStatus.LOBBY or state.table is None:
            raise GameplayConflictError("the match has not started yet")
        try:
            coordinator = await self._coordinator(state.table.table_id)
        except PersistenceError as exc:
            raise GameplayUnavailableError("the table is reconnecting to the database") from exc
        if coordinator.state.snapshot is None:
            raise GameplayConflictError("the first hand is being dealt")
        return self._project(state, coordinator, entry)

    async def _coordinator(self, table_id: str) -> TableCoordinator:
        existing = self._coordinators.get(table_id)
        if existing is not None:
            return existing
        lock = self._coordinator_locks.setdefault(table_id, asyncio.Lock())
        async with lock:
            existing = self._coordinators.get(table_id)
            if existing is not None:
                return existing
            coordinator = TableCoordinator(
                table_id,
                self._engine_factory(),
                self._tables,
                clock=self._clock,
            )
            try:
                await coordinator.restore()
            except TableNotFoundError:
                # restore() flags any persistence error as an outage; a table that was
                # never created is simply waiting for its first hand.
                coordinator = TableCoordinator(
                    table_id,
                    self._engine_factory(),
                    self._tables,
                    clock=self._clock,
                )
            except EngineInvariantError:
                # The coordinator durably quarantined the table before raising.
                pass
            self._coordinators[table_id] = coordinator
            return coordinator

    def _runtime(self, table_id: str) -> _TableRuntime:
        runtime = self._tables_runtime.get(table_id)
        if runtime is None:
            runtime = self._tables_runtime[table_id] = _TableRuntime()
        return runtime

    def _database_failed(self, table_id: str) -> None:
        """Drop the paused coordinator so the next attempt restores from durable state."""

        self._coordinators.pop(table_id, None)
        self._back_off(self._runtime(table_id), self._now())

    @staticmethod
    def _back_off(runtime: _TableRuntime, now: datetime) -> None:
        runtime.backoff_seconds = min(30.0, max(1.0, runtime.backoff_seconds * 2))
        runtime.retry_at = now + timedelta(seconds=runtime.backoff_seconds)

    async def _quarantine(self, match: MatchCoordinator, table_id: str) -> None:
        try:
            await match.mark_table_quarantined(table_id)
        except (MatchStoreError, MatchError):
            logger.exception("could not record table quarantine", extra={"table": table_id})

    def _pace(
        self,
        runtime: _TableRuntime,
        table: MatchTable,
        before: HandSnapshot,
        after: HandSnapshot,
    ) -> None:
        if not _has_human(table) or after.completed:
            runtime.next_action_at = None
            return
        seconds = (
            self.pacing.street_seconds
            if after.street != before.street
            else self.pacing.action_seconds
        )
        runtime.next_action_at = self._now() + timedelta(seconds=seconds)

    async def _bot_actor(self, profile_id: str | None) -> TableActor:
        profile = await self._profile(profile_id) if profile_id else None
        if profile is None or profile.verified_at is None:
            return _unavailable_bot
        try:
            token = self._token_store.decrypt(profile.bot_token_ciphertext)
            endpoint = BotEndpoint(ip=ip_address(profile.bot_ip), port=profile.bot_port)
        except ValueError:
            return _unavailable_bot
        actor = BotActor(self._gateway, endpoint, token)
        stats = self._bot_stats.get(profile.id)
        if stats is None or stats.consecutive_failures < self.pacing.breaker_failures:
            return actor

        gateway = self._gateway
        probe_seconds = self.pacing.health_probe_seconds

        async def probed(pending: PendingDecision, snapshot: HandSnapshot) -> PlayerAction:
            # A bot that keeps failing is probed briefly first so a dead process costs
            # half a second per decision instead of the full three-second deadline.
            if await gateway.health(endpoint, timeout_seconds=probe_seconds) is None:
                raise ActorDecisionFailure(FailureReason.CONNECTION)
            return await actor(pending, snapshot)

        return probed

    async def _profile(self, profile_id: str) -> BotProfile | None:
        cached = self._profiles.get(profile_id)
        now = self._monotonic()
        if cached is not None and now - cached[1] < _PROFILE_CACHE_SECONDS:
            return cached[0]
        profile = await self._accounts.get_bot_profile(profile_id)
        self._profiles[profile_id] = (profile, now)
        return profile

    def _record_bot_decision(
        self,
        profile_id: str | None,
        table: MatchTable,
        after: HandSnapshot,
        *,
        latency_ms: int,
    ) -> None:
        if profile_id is None or not after.action_history:
            return
        record = after.action_history[-1]
        stats = self._bot_stats.setdefault(profile_id, BotStats())
        stats.decisions += 1
        reason = record.failure_reason
        if reason is None:
            stats.consecutive_failures = 0
        else:
            stats.failures[reason.value] += 1
            if reason in _BREAKER_REASONS:
                stats.consecutive_failures += 1
        stats.recent.appendleft(
            BotDecisionLogResponse(
                match_id=after.match_id,
                hand_id=after.hand_id,
                at=self._now(),
                latency_ms=max(0, latency_ms),
                action=record.action,
                amount_to=record.amount_to,
                failure_reason=reason,
                explanation=explain_failure(reason) if reason is not None else None,
            )
        )

    def _project(
        self,
        state: MatchState,
        coordinator: TableCoordinator,
        entry: MatchEntry | None,
    ) -> PlayerTableStateResponse:
        snapshot = coordinator.state.snapshot
        assert snapshot is not None
        assert state.table is not None
        pending = coordinator.state.pending
        runtime = self._runtime(state.table.table_id)
        quarantined = coordinator.state.status is TableStatus.QUARANTINED
        viewer_seat = next(
            (
                seat.seat
                for seat in snapshot.seats
                if entry is not None and seat.entrant_id == entry.entry_id
            ),
            None,
        )
        live = not snapshot.completed and not quarantined and state.status in _DRIVING_STATUSES
        acting = next(
            (seat for seat in snapshot.seats if pending is not None and seat.seat == pending.seat),
            None,
        )
        human_duration = (
            runtime.decision_durations.get(pending.decision_id) if pending is not None else None
        ) or state.config.human_action_timeout_ms

        decision = None
        if (
            live
            and pending is not None
            and entry is not None
            and entry.kind is EntryKind.HUMAN
            and pending.seat == viewer_seat
        ):
            decision = PlayerDecisionResponse(
                decision_id=pending.decision_id,
                table_version=pending.table_version,
                deadline_at=pending.deadline_at,
                duration_ms=human_duration,
                legal_actions=pending.legal_actions,
            )
        turn = (
            PublicTurnResponse(
                seat=pending.seat,
                kind=acting.kind,
                deadline_at=pending.deadline_at,
                duration_ms=(
                    BOT_ACTION_TIMEOUT_MS if acting.kind is EntryKind.BOT else human_duration
                ),
            )
            if live and pending is not None and acting is not None
            else None
        )
        next_action_at = (
            runtime.next_action_at
            if runtime.next_action_at is not None and runtime.next_action_at > self._now()
            else None
        )
        return PlayerTableStateResponse(
            match_id=snapshot.match_id,
            match_status=state.status,
            table_status=coordinator.state.status or TableStatus.QUARANTINED,
            table_id=snapshot.table_id,
            hand_id=snapshot.hand_id,
            hand_number=snapshot.hand_number,
            table_version=snapshot.table_version,
            viewer_seat=viewer_seat,
            viewer=_viewer(state, entry),
            acting_seat=snapshot.acting_seat,
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
                    away=seat.entrant_id in self._away,
                    hole_cards=(
                        seat.hole_cards if seat.seat == viewer_seat else seat.public_hole_cards
                    ),
                )
                for seat in snapshot.seats
            ),
            pot=snapshot.pot,
            side_pots=tuple(
                PublicSidePotResponse(amount=pot.amount, eligible_seats=pot.eligible_seats)
                for pot in snapshot.side_pots
            ),
            action_history=tuple(
                PublicPlayerActionResponse(
                    sequence=action.sequence,
                    seat=action.seat,
                    street=action.street,
                    action=action.action,
                    amount_to=action.amount_to,
                    automatic=action.automatic,
                    failure_reason=action.failure_reason,
                )
                for action in snapshot.action_history
            ),
            completed=snapshot.completed,
            decision=decision,
            turn=turn,
            hand_result=natural_hand_result(snapshot),
            next_action_at=next_action_at,
            match=_match_context(state),
            last_hand=(
                runtime.last_hand
                if runtime.last_hand is not None
                and runtime.last_hand.hand_number != snapshot.hand_number
                else None
            ),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("gameplay clock must return a timezone-aware datetime")
        return value


async def _unavailable_bot(_pending: PendingDecision, _snapshot: HandSnapshot) -> PlayerAction:
    raise ActorDecisionFailure(FailureReason.CONNECTION)


def _has_human(table: MatchTable) -> bool:
    return any(player.kind is EntryKind.HUMAN for player in table.players)


def _viewer_entry(state: MatchState, account_id: str) -> MatchEntry | None:
    """Prefer the account's human seat; bot owners otherwise watch from their bot's seat."""

    owned = [entry for entry in state.entries if entry.account_id == account_id]
    human = next((entry for entry in owned if entry.kind is EntryKind.HUMAN), None)
    return human or (owned[0] if owned else None)


def standing_responses(state: MatchState) -> tuple[StandingResponse, ...]:
    return tuple(
        StandingResponse(
            entry_id=item.entry_id,
            display_name=item.display_name,
            kind=item.kind,
            position=item.position,
            eliminated_hand_number=item.eliminated_hand_number,
            final_stack=item.final_stack,
        )
        for item in sorted(state.standings, key=lambda standing: standing.position)
    )


def _viewer(state: MatchState, entry: MatchEntry | None) -> ViewerResponse | None:
    if entry is None:
        return None
    standing = next((item for item in state.standings if item.entry_id == entry.entry_id), None)
    if standing is not None:
        status: Literal["eliminated", "winner", "finished"] = (
            ("winner" if standing.position == 1 else "finished")
            if state.status is MatchStatus.COMPLETED
            else "eliminated"
        )
        return ViewerResponse(
            entry_id=entry.entry_id,
            display_name=entry.display_name,
            status=status,
            finish_position=standing.position,
        )
    return ViewerResponse(
        entry_id=entry.entry_id,
        display_name=entry.display_name,
        status="seated",
    )


def _match_context(state: MatchState) -> MatchContextResponse:
    next_level = state.config.level(state.level_number + 1) if state.config.escalates else None
    return MatchContextResponse(
        name=state.name,
        level_number=state.level_number,
        level_remaining_seconds=state.level_remaining_seconds,
        next_small_blind=next_level.small_blind if next_level else None,
        next_big_blind=next_level.big_blind if next_level else None,
        players_remaining=state.players_remaining,
        max_seats=state.config.max_seats,
        end_requested=state.end_requested,
        standings=standing_responses(state),
    )
