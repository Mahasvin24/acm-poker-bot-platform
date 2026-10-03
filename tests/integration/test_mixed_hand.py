from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from ipaddress import ip_network

import httpx
import pytest
from pokerkit import Deck

from poker_bot_platform.bots import BotEndpoint, BotGateway
from poker_bot_platform.bots.models import BotActionRequest
from poker_bot_platform.bots.reference import deterministic_reference_action
from poker_bot_platform.coordinator import TableCoordinator
from poker_bot_platform.domain import (
    ActionType,
    EntryKind,
    FailureReason,
    PendingDecision,
    PlayerAction,
    SeatState,
    StartHandRequest,
)
from poker_bot_platform.engine import PokerKitEngine
from poker_bot_platform.integration import BotActor
from poker_bot_platform.persistence import InMemoryTableRepository


def full_deck() -> tuple[str, ...]:
    return tuple(map(repr, Deck.STANDARD))


async def start_heads_up_table(repository: InMemoryTableRepository) -> TableCoordinator:
    await repository.create_tournament("tournament-1", {"starting_stack": 20_000})
    coordinator = TableCoordinator("table-1", PokerKitEngine(), repository)
    await coordinator.start_table(
        StartHandRequest(
            tournament_id="tournament-1",
            table_id="table-1",
            hand_id="hand-1",
            hand_number=1,
            table_version=0,
            button_seat=1,
            small_blind=100,
            big_blind=200,
            big_blind_ante=200,
            seats=(
                SeatState(
                    seat=1,
                    entrant_id="bot-1",
                    display_name="Reference Bot",
                    kind=EntryKind.BOT,
                    stack=20_000,
                ),
                SeatState(
                    seat=2,
                    entrant_id="human-1",
                    display_name="Human",
                    kind=EntryKind.HUMAN,
                    stack=20_000,
                ),
            ),
            deck_order=full_deck(),
        )
    )
    return coordinator


@pytest.mark.asyncio
async def test_mixed_bot_hand_persists_through_production_boundaries() -> None:
    bot_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal bot_requests
        assert request.headers["authorization"] == "Bearer event-token"
        payload = BotActionRequest.model_validate(json.loads(request.content))
        bot_requests += 1
        response = deterministic_reference_action(payload)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=response.model_dump_json(),
        )

    repository = InMemoryTableRepository()
    coordinator = await start_heads_up_table(repository)
    snapshot = coordinator.state.snapshot
    assert snapshot is not None

    endpoint = BotEndpoint(ip="192.168.1.50", port=8_080)
    async with BotGateway(
        participant_subnet=ip_network("192.168.1.0/24"),
        transport=httpx.MockTransport(handler),
    ) as gateway:
        bot_actor = BotActor(gateway, endpoint, "event-token")
        while not snapshot.completed:
            deadline = datetime.now(UTC) + timedelta(seconds=3)
            if snapshot.acting_seat == 1:
                snapshot = await coordinator.request_actor_action(bot_actor, deadline)
                continue

            async def human_actor(
                pending: PendingDecision,
                _snapshot: object,
            ) -> PlayerAction:
                legal = {action.action for action in pending.legal_actions}
                action = ActionType.CHECK if ActionType.CHECK in legal else ActionType.FOLD
                return PlayerAction(
                    decision_id=pending.decision_id,
                    table_version=pending.table_version,
                    seat=pending.seat,
                    action=action,
                )

            snapshot = await coordinator.request_actor_action(human_actor, deadline)

    assert snapshot.completed
    assert bot_requests >= 1
    persisted = await repository.load_table("table-1")
    assert persisted.snapshot == snapshot
    assert persisted.pending is None
    assert sum(seat.stack for seat in snapshot.seats) == 40_000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_reason"),
    [
        ("malformed", FailureReason.MALFORMED_JSON),
        ("duplicate", FailureReason.MALFORMED_JSON),
        ("schema", FailureReason.SCHEMA),
        ("stale", FailureReason.STALE),
        ("illegal", FailureReason.ILLEGAL_ACTION),
        ("http", FailureReason.HTTP_STATUS),
        ("content_type", FailureReason.CONTENT_TYPE),
        ("oversized", FailureReason.OVERSIZED),
        ("connection", FailureReason.CONNECTION),
        ("timeout", FailureReason.TIMEOUT),
    ],
)
async def test_bot_failures_become_one_durable_automatic_fallback(
    failure: str,
    expected_reason: FailureReason,
) -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        payload = BotActionRequest.model_validate(json.loads(request.content))
        assert payload.player.seat == 1
        assert payload.player.hole_cards
        public_seats = payload.table.model_dump(mode="json")["seats"]
        assert all("hole_cards" not in seat for seat in public_seats)

        if failure == "malformed":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b"{not-json",
            )
        if failure == "duplicate":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b'{"protocol":"poker-bot.v1","protocol":"poker-bot.v1"}',
            )
        if failure == "schema":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"protocol": "poker-bot.v1"},
            )
        if failure == "http":
            return httpx.Response(503, json={"error": "unavailable"})
        if failure == "content_type":
            return httpx.Response(200, text="not JSON")
        if failure == "oversized":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b"x" * 4097,
            )
        if failure == "connection":
            raise httpx.ConnectError("offline", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("late", request=request)

        response = deterministic_reference_action(payload).model_dump(mode="json")
        if failure == "stale":
            response["decision_id"] = "old-decision"
        elif failure == "illegal":
            response["action"] = "check"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=response,
        )

    repository = InMemoryTableRepository()
    coordinator = await start_heads_up_table(repository)
    endpoint = BotEndpoint(ip="192.168.1.50", port=8_080)
    async with BotGateway(
        participant_subnet=ip_network("192.168.1.0/24"),
        transport=httpx.MockTransport(handler),
    ) as gateway:
        result = await coordinator.request_actor_action(
            BotActor(gateway, endpoint, "event-token"),
            datetime.now(UTC) + timedelta(seconds=3),
        )

    assert requests == 1
    assert result.table_version == 1
    action = result.action_history[-1]
    assert action.action is ActionType.FOLD
    assert action.automatic
    assert action.failure_reason is expected_reason
    persisted = await repository.load_table("table-1")
    assert persisted.snapshot == result
    assert persisted.pending is None
    assert len(repository.actions) == 1
