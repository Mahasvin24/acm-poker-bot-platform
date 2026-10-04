from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address, ip_network
from typing import Literal

import httpx
from pokerkit import Deck

from poker_bot_platform.api.models import (
    DemoMatchStateResponse,
    HandAwardResponse,
    HandResultResponse,
    PlayerActionRequest,
    PlayerDecisionResponse,
    PlayerTableStateResponse,
    PublicPlayerActionResponse,
    PublicPlayerSeatResponse,
    PublicSidePotResponse,
    PublicTurnResponse,
    RevealedHandResponse,
)
from poker_bot_platform.bots import BotActionRequest, BotEndpoint, BotGateway
from poker_bot_platform.bots.reference import deterministic_reference_action
from poker_bot_platform.coordinator import InvalidActionError, TableCoordinator
from poker_bot_platform.domain import (
    EntryKind,
    HandSnapshot,
    PlayerAction,
    SeatState,
    StartHandRequest,
    Street,
    TableStatus,
    TournamentStatus,
)
from poker_bot_platform.engine import PokerKitEngine
from poker_bot_platform.integration.actors import BotActor
from poker_bot_platform.integration.presentation import natural_hand_result
from poker_bot_platform.persistence import InMemoryTableRepository

DemoOutcome = Literal["human_win", "bot_win"]

_TOURNAMENT_ID = "ephemeral-human-versus-bot"
_TABLE_ID = "ephemeral-four-player-table"
_HUMAN_ENTRANT_ID = "ephemeral-human"
_HUMAN_SEAT = 1
_BOT_SEATS = (2, 3, 4)
_BOT_IDENTITIES = (
    (2, "ephemeral-reference-bot-1", "Atlas"),
    (3, "ephemeral-reference-bot-2", "Bluff Bot"),
    (4, "ephemeral-reference-bot-3", "River Bot"),
)
_STARTING_STACK = 20_000
_HUMAN_TIMEOUT = timedelta(seconds=30)
_BOT_TIMEOUT = timedelta(seconds=3)
_BOT_DELAY = timedelta(seconds=7)
_BOT_TOKEN = "ephemeral-demo-token"


class DemoMatchError(RuntimeError):
    pass


class EphemeralDemoMatch:
    """Single-process, non-durable four-player match used only by the test page."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._lock = asyncio.Lock()
        self._repository: InMemoryTableRepository | None = None
        self._coordinator: TableCoordinator | None = None
        self._forced_outcome: DemoOutcome | None = None
        self._match_id: str | None = None
        self._bot_action_due_at: datetime | None = None
        self._bot_action_seat: int | None = None
        self._clock = clock or (lambda: datetime.now(UTC))
        self._gateway = BotGateway(
            participant_subnet=ip_network("10.99.0.0/24"),
            transport=httpx.MockTransport(self._test_bot_endpoint),
        )
        self._bot_actor = BotActor(
            gateway=self._gateway,
            endpoint=BotEndpoint(ip=ip_address("10.99.0.2"), port=8_001),
            bearer_token=_BOT_TOKEN,
        )

    async def aclose(self) -> None:
        await self._gateway.aclose()

    async def current(self) -> DemoMatchStateResponse:
        async with self._lock:
            if self._coordinator is None:
                return self._idle_response()
            await self._drive_until_human_or_complete()
            return self._response()

    async def start(self) -> DemoMatchStateResponse:
        async with self._lock:
            repository = InMemoryTableRepository()
            await repository.create_tournament(
                _TOURNAMENT_ID,
                {"starting_stack": _STARTING_STACK, "ephemeral": True},
                status=TournamentStatus.RUNNING,
            )
            coordinator = TableCoordinator(
                _TABLE_ID,
                PokerKitEngine(),
                repository,
                clock=self._clock,
            )
            deck = tuple(map(repr, Deck.STANDARD))
            shuffled = list(deck)
            secrets.SystemRandom().shuffle(shuffled)
            button_seat = secrets.choice((_HUMAN_SEAT, *_BOT_SEATS))
            await coordinator.start_table(
                StartHandRequest(
                    tournament_id=_TOURNAMENT_ID,
                    table_id=_TABLE_ID,
                    hand_id="ephemeral-hand-1",
                    hand_number=1,
                    table_version=0,
                    button_seat=button_seat,
                    small_blind=100,
                    big_blind=200,
                    big_blind_ante=200,
                    seats=(
                        SeatState(
                            seat=_HUMAN_SEAT,
                            entrant_id=_HUMAN_ENTRANT_ID,
                            display_name="You",
                            kind=EntryKind.HUMAN,
                            stack=_STARTING_STACK,
                        ),
                        *(
                            SeatState(
                                seat=seat,
                                entrant_id=entrant_id,
                                display_name=display_name,
                                kind=EntryKind.BOT,
                                stack=_STARTING_STACK,
                            )
                            for seat, entrant_id, display_name in _BOT_IDENTITIES
                        ),
                    ),
                    deck_order=tuple(shuffled),
                )
            )
            self._repository = repository
            self._coordinator = coordinator
            self._forced_outcome = None
            self._match_id = secrets.token_urlsafe(12)
            self._bot_action_due_at = None
            self._bot_action_seat = None
            await self._drive_until_human_or_complete()
            return self._response()

    async def submit(self, request: PlayerActionRequest) -> DemoMatchStateResponse:
        async with self._lock:
            coordinator = self._require_active_coordinator()
            if self._forced_outcome is not None:
                raise DemoMatchError("the forced match result cannot accept actions")
            snapshot = self._require_snapshot(coordinator)
            if snapshot.completed:
                raise DemoMatchError("the hand is already complete")
            pending = coordinator.state.pending
            if pending is None or pending.seat != _HUMAN_SEAT:
                raise DemoMatchError("the human player does not have the pending decision")
            try:
                await coordinator.submit_action(
                    PlayerAction(
                        decision_id=request.decision_id,
                        table_version=request.table_version,
                        seat=_HUMAN_SEAT,
                        action=request.action,
                        amount_to=request.amount_to,
                    )
                )
            except InvalidActionError as exc:
                raise DemoMatchError(str(exc)) from exc
            await self._drive_until_human_or_complete()
            return self._response()

    async def force(self, outcome: DemoOutcome) -> DemoMatchStateResponse:
        async with self._lock:
            self._require_active_coordinator()
            self._forced_outcome = outcome
            self._bot_action_due_at = None
            self._bot_action_seat = None
            return self._response()

    async def end(self) -> DemoMatchStateResponse:
        async with self._lock:
            self._coordinator = None
            self._repository = None
            self._forced_outcome = None
            self._match_id = None
            self._bot_action_due_at = None
            self._bot_action_seat = None
            return self._idle_response()

    async def _drive_until_human_or_complete(self) -> None:
        coordinator = self._require_active_coordinator()
        if self._forced_outcome is not None:
            return
        while True:
            snapshot = self._require_snapshot(coordinator)
            if snapshot.completed:
                self._bot_action_due_at = None
                self._bot_action_seat = None
                return
            if snapshot.acting_seat in _BOT_SEATS:
                if self._bot_action_due_at is None or self._bot_action_seat != snapshot.acting_seat:
                    self._bot_action_due_at = self._now() + _BOT_DELAY
                    self._bot_action_seat = snapshot.acting_seat
                    return
                if self._now() < self._bot_action_due_at:
                    return
                self._bot_action_due_at = None
                self._bot_action_seat = None
                await coordinator.request_actor_action(
                    self._bot_actor,
                    self._now() + _BOT_TIMEOUT,
                )
                continue
            if snapshot.acting_seat != _HUMAN_SEAT:
                raise DemoMatchError("the hand has an unexpected acting seat")
            pending = coordinator.state.pending
            self._bot_action_due_at = None
            self._bot_action_seat = None
            if pending is None:
                await coordinator.open_decision(self._now() + _HUMAN_TIMEOUT)
                return
            if self._now() >= pending.deadline_at:
                await coordinator.expire_decision()
                continue
            return

    @staticmethod
    def _test_bot_endpoint(request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {_BOT_TOKEN}":
            return httpx.Response(401, json={"detail": "invalid bearer token"})
        bot_request = BotActionRequest.model_validate_json(request.content)
        response = deterministic_reference_action(bot_request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=response.model_dump_json(),
        )

    def _response(self) -> DemoMatchStateResponse:
        coordinator = self._require_active_coordinator()
        table = self._project(coordinator)
        match_id = self._require_match_id()
        if self._forced_outcome is not None:
            table = self._forced_table(
                table,
                self._require_snapshot(coordinator),
                self._forced_outcome,
            )
            return DemoMatchStateResponse(
                status="completed",
                match_id=match_id,
                result=self._forced_outcome,
                table=table,
            )
        snapshot = self._require_snapshot(coordinator)
        if snapshot.completed:
            return DemoMatchStateResponse(
                status="completed",
                match_id=match_id,
                result=self._natural_result(snapshot),
                table=table,
            )
        return DemoMatchStateResponse(status="active", match_id=match_id, table=table)

    def _project(self, coordinator: TableCoordinator) -> PlayerTableStateResponse:
        snapshot = self._require_snapshot(coordinator)
        pending = coordinator.state.pending
        decision = None
        if pending is not None and pending.seat == _HUMAN_SEAT and not snapshot.completed:
            decision = PlayerDecisionResponse(
                decision_id=pending.decision_id,
                table_version=pending.table_version,
                deadline_at=pending.deadline_at,
                legal_actions=pending.legal_actions,
            )
        turn = None
        if pending is not None and not snapshot.completed:
            turn = PublicTurnResponse(
                seat=pending.seat,
                kind=EntryKind.HUMAN,
                deadline_at=pending.deadline_at,
                duration_ms=int(_HUMAN_TIMEOUT.total_seconds() * 1000),
            )
        elif self._bot_action_due_at is not None and not snapshot.completed:
            turn = PublicTurnResponse(
                seat=self._bot_action_seat or snapshot.acting_seat or _BOT_SEATS[0],
                kind=EntryKind.BOT,
                deadline_at=self._bot_action_due_at,
                duration_ms=int(_BOT_DELAY.total_seconds() * 1000),
            )
        completed = snapshot.completed
        return PlayerTableStateResponse(
            tournament_id=snapshot.tournament_id,
            tournament_status=(
                TournamentStatus.COMPLETED if completed else TournamentStatus.RUNNING
            ),
            table_status=TableStatus.COMPLETED if completed else TableStatus.RUNNING,
            table_id=snapshot.table_id,
            hand_id=snapshot.hand_id,
            hand_number=snapshot.hand_number,
            table_version=snapshot.table_version,
            viewer_seat=_HUMAN_SEAT,
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
                    hole_cards=(
                        seat.hole_cards
                        if seat.entrant_id == _HUMAN_ENTRANT_ID
                        else seat.public_hole_cards
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
                    action=action.action,
                    amount_to=action.amount_to,
                    automatic=action.automatic,
                    failure_reason=action.failure_reason,
                )
                for action in snapshot.action_history
            ),
            completed=completed,
            decision=decision,
            turn=turn,
            hand_result=natural_hand_result(snapshot),
        )

    @staticmethod
    def _forced_table(
        table: PlayerTableStateResponse,
        snapshot: HandSnapshot,
        outcome: DemoOutcome,
    ) -> PlayerTableStateResponse:
        winner_seat = _HUMAN_SEAT if outcome == "human_win" else _BOT_SEATS[0]
        total_chips = _STARTING_STACK * (len(_BOT_SEATS) + 1)
        seats = tuple(
            seat.model_copy(
                update={
                    "stack": total_chips if seat.seat == winner_seat else 0,
                    "committed_this_street": 0,
                    "committed_this_hand": 0,
                    "folded": False,
                    "all_in": False,
                    "eliminated": seat.seat != winner_seat,
                }
            )
            for seat in table.seats
        )
        return table.model_copy(
            update={
                "tournament_status": TournamentStatus.COMPLETED,
                "table_status": TableStatus.COMPLETED,
                "street": Street.COMPLETE,
                "acting_seat": None,
                "seats": seats,
                "pot": 0,
                "side_pots": (),
                "completed": True,
                "decision": None,
                "turn": None,
                "hand_result": HandResultResponse(
                    reason="forced",
                    awards=(
                        HandAwardResponse(
                            seat=winner_seat,
                            amount=total_chips,
                            net=total_chips - _STARTING_STACK,
                        ),
                    ),
                    revealed_hands=tuple(
                        RevealedHandResponse(
                            seat=seat.seat,
                            hole_cards=seat.hole_cards,
                            label="Test override — not ranked",
                            best_five=(),
                        )
                        for seat in snapshot.seats
                        if seat.hole_cards
                    ),
                    synthetic=True,
                ),
            }
        )

    @staticmethod
    def _natural_result(snapshot: HandSnapshot) -> Literal["human_win", "bot_win", "tie"]:
        stacks = {seat.seat: seat.stack for seat in snapshot.seats}
        human = stacks.get(_HUMAN_SEAT, 0)
        best_bot = max((stacks.get(seat, 0) for seat in _BOT_SEATS), default=0)
        if human > best_bot:
            return "human_win"
        if best_bot > human:
            return "bot_win"
        return "tie"

    def _require_active_coordinator(self) -> TableCoordinator:
        if self._coordinator is None:
            raise DemoMatchError("start the demo match first")
        return self._coordinator

    def _require_match_id(self) -> str:
        if self._match_id is None:
            raise DemoMatchError("the demo match has no active identity")
        return self._match_id

    @staticmethod
    def _require_snapshot(coordinator: TableCoordinator) -> HandSnapshot:
        snapshot = coordinator.state.snapshot
        if snapshot is None:
            raise DemoMatchError("the demo table is not initialized")
        return snapshot

    @staticmethod
    def _idle_response() -> DemoMatchStateResponse:
        return DemoMatchStateResponse(status="idle")

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("demo clock must return a timezone-aware datetime")
        return value
