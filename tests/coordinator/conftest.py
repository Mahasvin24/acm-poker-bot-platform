from __future__ import annotations

from datetime import UTC, datetime

import pytest

from poker_bot_platform.domain import EntryKind, SeatState, StartHandRequest
from poker_bot_platform.engine import FakePokerEngine
from poker_bot_platform.persistence import InMemoryTableRepository

NOW = datetime(2026, 10, 1, 19, 0, tzinfo=UTC)


def start_request(*, table_version: int = 0) -> StartHandRequest:
    return StartHandRequest(
        tournament_id="tournament-1",
        table_id="table-1",
        hand_id="hand-1",
        hand_number=1,
        table_version=table_version,
        button_seat=1,
        small_blind=100,
        big_blind=200,
        big_blind_ante=200,
        seats=(
            SeatState(
                seat=1,
                entrant_id="human-1",
                display_name="Human",
                kind=EntryKind.HUMAN,
                stack=20_000,
                hole_cards=("As", "Kd"),
            ),
            SeatState(
                seat=2,
                entrant_id="bot-1",
                display_name="Bot",
                kind=EntryKind.BOT,
                stack=20_000,
                hole_cards=("Qh", "Qc"),
            ),
        ),
        deck_order=("2c", "3d", "4h", "5s", "6c"),
    )


@pytest.fixture
async def repository() -> InMemoryTableRepository:
    repository = InMemoryTableRepository()
    await repository.create_tournament("tournament-1", {"starting_stack": 20_000})
    return repository


@pytest.fixture
def engine() -> FakePokerEngine:
    return FakePokerEngine()
