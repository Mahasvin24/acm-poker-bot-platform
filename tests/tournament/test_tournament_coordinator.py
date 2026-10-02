from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from poker_bot_platform.coordinator import TableCoordinator
from poker_bot_platform.domain import (
    ActionType,
    BlindLevel,
    EntryKind,
    PlayerAction,
    TournamentConfig,
    TournamentStatus,
)
from poker_bot_platform.engine import FakePokerEngine
from poker_bot_platform.persistence import InMemoryTableRepository
from poker_bot_platform.tournament import (
    AuditEntry,
    Entrant,
    InMemoryTournamentStore,
    TournamentCoordinator,
    TournamentError,
    TournamentState,
)

SEED = "12" * 32


def entrant(number: int, *, bot: bool = False) -> Entrant:
    return Entrant(
        entrant_id=f"entrant-{number:02d}",
        account_id=f"account-{number:02d}",
        display_name=f"Player {number}",
        kind=EntryKind.BOT if bot else EntryKind.HUMAN,
        bot_verified=bot,
    )


async def created(
    count: int,
    *,
    tournament_id: str = "tournament-1",
    config: TournamentConfig | None = None,
    seed_hex: str = SEED,
) -> tuple[TournamentCoordinator, InMemoryTournamentStore]:
    store = InMemoryTournamentStore()
    coordinator = await TournamentCoordinator.create(
        tournament_id,
        config or TournamentConfig(),
        store,
        InMemoryTableRepository(),
        seed_hex=seed_hex,
    )
    await coordinator.open_registration(actor_id="admin")
    for number in range(1, count + 1):
        await coordinator.register(entrant(number), actor_id=f"account-{number:02d}")
    return coordinator, store


async def finish_unchanged(coordinator: TournamentCoordinator, table_ids: Sequence[str]) -> None:
    for table_id in table_ids:
        table = next(table for table in coordinator.state.tables if table.table_id == table_id)
        await coordinator.record_hand_completed(
            table_id,
            {player.entrant_id: player.stack for player in table.players},
        )


@pytest.mark.asyncio
async def test_store_lists_only_persisted_active_tournaments() -> None:
    store = InMemoryTournamentStore()
    active = {
        TournamentStatus.RUNNING,
        TournamentStatus.PAUSE_REQUESTED,
        TournamentStatus.PAUSED,
        TournamentStatus.BREAK,
    }
    for status in TournamentStatus:
        await store.create(
            TournamentState(
                tournament_id=f"event-{status.value}",
                config=TournamentConfig(),
                seed_hex=SEED,
                status=status,
                phase_remaining_seconds=900,
            ),
            AuditEntry(actor_id="test", command="create"),
        )

    assert await store.list_active_tournament_ids() == tuple(
        sorted(f"event-{status.value}" for status in active)
    )


@pytest.mark.asyncio
async def test_registration_and_seeded_seating_are_deterministic_and_balanced() -> None:
    first, store = await created(17, tournament_id="first")
    second, _ = await created(17, tournament_id="second")

    await first.seat_entrants(actor_id="admin")
    await second.seat_entrants(actor_id="admin")

    assert [len(table.players) for table in first.state.tables] == [6, 6, 5]
    assert [[player.entrant_id for player in table.players] for table in first.state.tables] == [
        [player.entrant_id for player in table.players] for table in second.state.tables
    ]
    assert len(store.audit_entries("first")) == 20


@pytest.mark.asyncio
async def test_unverified_bot_cannot_be_seated_and_config_freezes_after_draft() -> None:
    coordinator, _ = await created(2)
    state = coordinator.state
    unverified = Entrant(
        entrant_id="bot",
        account_id="bot-account",
        display_name="Bot",
        kind=EntryKind.BOT,
    )
    # Registration is already open, so the draft-only config command is rejected.
    with pytest.raises(TournamentError, match="expected tournament status draft"):
        await coordinator.update_config(TournamentConfig(starting_stack=10_000), actor_id="admin")

    # A separate tournament demonstrates verification as a seating gate.
    other_store = InMemoryTournamentStore()
    other = await TournamentCoordinator.create(
        "bot-event",
        TournamentConfig(),
        other_store,
        InMemoryTableRepository(),
        seed_hex=SEED,
    )
    await other.open_registration(actor_id="admin")
    await other.register(unverified, actor_id="bot-account")
    await other.register(entrant(1), actor_id="account-01")
    with pytest.raises(TournamentError, match="verified"):
        await other.seat_entrants(actor_id="admin")
    await other.verify_bot("bot", actor_id="admin")
    await other.seat_entrants(actor_id="admin")
    assert other.state.status is TournamentStatus.SEATED
    assert state.config.starting_stack == 20_000


@pytest.mark.asyncio
async def test_pause_waits_for_all_hand_boundaries_and_freezes_clock() -> None:
    coordinator, _ = await created(7)
    await coordinator.seat_entrants(actor_id="admin")
    await coordinator.start(actor_id="admin")
    table_ids = [table.table_id for table in coordinator.state.tables]

    await coordinator.tick(23)
    remaining = coordinator.state.phase_remaining_seconds
    await coordinator.request_pause(actor_id="admin")
    assert coordinator.state.status is TournamentStatus.PAUSE_REQUESTED
    await finish_unchanged(coordinator, table_ids)

    assert coordinator.state.status is TournamentStatus.PAUSED
    assert not any(table.hand_in_progress for table in coordinator.state.tables)
    await coordinator.tick(100)
    assert coordinator.state.phase_remaining_seconds == remaining
    await coordinator.resume(actor_id="admin")
    assert coordinator.state.status is TournamentStatus.RUNNING
    assert all(table.hand_in_progress for table in coordinator.state.tables)


@pytest.mark.asyncio
async def test_levels_breaks_and_post_schedule_doubling_apply_between_hands() -> None:
    config = TournamentConfig(
        break_every_levels=2,
        break_duration_seconds=5,
        levels=(
            BlindLevel(small_blind=10, big_blind=20, big_blind_ante=20, duration_seconds=10),
            BlindLevel(small_blind=20, big_blind=40, big_blind_ante=40, duration_seconds=10),
        ),
    )
    coordinator, _ = await created(2, config=config)
    await coordinator.seat_entrants(actor_id="admin")
    await coordinator.start(actor_id="admin")
    table_id = coordinator.state.tables[0].table_id

    await coordinator.tick(10)
    assert coordinator.state.level_number == 2
    request = coordinator.hand_request(table_id)
    assert (request.small_blind, request.big_blind) == (10, 20)

    await coordinator.tick(10)
    assert coordinator.state.break_pending
    table = coordinator.state.tables[0]
    await coordinator.record_hand_completed(
        table_id,
        {player.entrant_id: player.stack for player in table.players},
    )
    assert coordinator.state.status is TournamentStatus.BREAK
    assert not coordinator.state.tables[0].hand_in_progress

    await coordinator.tick(5)
    assert coordinator.state.status is TournamentStatus.RUNNING
    assert coordinator.state.level_number == 3
    request = coordinator.hand_request(table_id)
    assert (request.small_blind, request.big_blind, request.big_blind_ante) == (40, 80, 80)
    assert request.hand_number == 2


@pytest.mark.asyncio
async def test_elimination_tiebreak_and_capacity_table_break() -> None:
    coordinator, _ = await created(8)
    await coordinator.seat_entrants(actor_id="admin")
    await coordinator.start(actor_id="admin")

    # First round establishes unequal start-of-hand stacks for the next hand.
    first_round = [table.table_id for table in coordinator.state.tables]
    first_table = coordinator.state.tables[0]
    first_stacks = [10_000, 20_000, 30_000, 20_000]
    await coordinator.record_hand_completed(
        first_table.table_id,
        {
            player.entrant_id: stack
            for player, stack in zip(first_table.players, first_stacks, strict=True)
        },
    )
    await finish_unchanged(coordinator, first_round[1:])

    table = coordinator.state.tables[0]
    low, high, recipient = table.players[0], table.players[1], table.players[2]
    results = {player.entrant_id: player.stack for player in table.players}
    results[low.entrant_id] = 0
    results[high.entrant_id] = 0
    results[recipient.entrant_id] += low.stack + high.stack
    await coordinator.record_hand_completed(table.table_id, results)
    for other in [item for item in coordinator.state.tables if item.hand_in_progress]:
        await coordinator.record_hand_completed(
            other.table_id,
            {player.entrant_id: player.stack for player in other.players},
        )

    positions = {standing.entrant_id: standing.position for standing in coordinator.state.standings}
    assert positions[high.entrant_id] < positions[low.entrant_id]
    assert len(coordinator.state.tables) == 1
    assert len(coordinator.state.tables[0].players) == 6


@pytest.mark.asyncio
async def test_equal_starting_stacks_share_elimination_position() -> None:
    coordinator, _ = await created(3)
    await coordinator.seat_entrants(actor_id="admin")
    await coordinator.start(actor_id="admin")
    table = coordinator.state.tables[0]
    first, second, winner = table.players

    await coordinator.record_hand_completed(
        table.table_id,
        {
            first.entrant_id: 0,
            second.entrant_id: 0,
            winner.entrant_id: first.stack + second.stack + winner.stack,
        },
    )

    assert coordinator.state.status is TournamentStatus.COMPLETED
    assert {
        standing.position
        for standing in coordinator.state.standings
        if standing.entrant_id in {first.entrant_id, second.entrant_id}
    } == {2}


@pytest.mark.asyncio
async def test_first_and_next_hand_dispatch_through_table_coordinator() -> None:
    coordinator, _ = await created(2)
    await coordinator.seat_entrants(actor_id="admin")
    await coordinator.start(actor_id="admin")
    table_id = coordinator.state.tables[0].table_id
    runtime = TableCoordinator(table_id, FakePokerEngine(), coordinator._table_repository)

    snapshot = await coordinator.dispatch_hand(table_id, runtime)

    assert snapshot.table_id == table_id
    assert snapshot.hand_number == 1
    assert len(snapshot.deck_order) == 52
    assert len(set(snapshot.deck_order)) == 52

    pending = await runtime.open_decision(datetime.now(UTC) + timedelta(seconds=5))
    completed = await runtime.submit_action(
        PlayerAction(
            decision_id=pending.decision_id,
            table_version=pending.table_version,
            seat=pending.seat,
            action=ActionType.CHECK,
        )
    )
    await coordinator.record_hand_completed(
        table_id,
        {seat.entrant_id: seat.stack for seat in completed.seats},
    )
    next_snapshot = await coordinator.dispatch_hand(table_id, runtime)
    assert next_snapshot.hand_number == 2
    assert next_snapshot.table_version == completed.table_version + 1


async def simulate_36(tournament_id: str, *, seed_hex: str = SEED) -> TournamentCoordinator:
    coordinator, _ = await created(36, tournament_id=tournament_id, seed_hex=seed_hex)
    await coordinator.seat_entrants(actor_id="admin")
    await coordinator.start(actor_id="admin")
    safety = 0
    while coordinator.state.status is not TournamentStatus.COMPLETED:
        safety += 1
        assert safety < 100
        active_tables = [table for table in coordinator.state.tables if table.hand_in_progress]
        assert active_tables
        for scheduled in active_tables:
            table = next(
                table for table in coordinator.state.tables if table.table_id == scheduled.table_id
            )
            loser, winner = table.players[0], table.players[1]
            stacks = {player.entrant_id: player.stack for player in table.players}
            stacks[loser.entrant_id] = 0
            stacks[winner.entrant_id] += loser.stack
            await coordinator.record_hand_completed(table.table_id, stacks)
    return coordinator


@pytest.mark.asyncio
async def test_seeded_36_player_headless_lifecycle_reaches_same_winner() -> None:
    first = await simulate_36("simulation-a")
    second = await simulate_36("simulation-b")

    assert len(first.state.standings) == 36
    assert {standing.entrant_id for standing in first.state.standings} == {
        f"entrant-{number:02d}" for number in range(1, 37)
    }
    first_winner = next(item.entrant_id for item in first.state.standings if item.position == 1)
    second_winner = next(item.entrant_id for item in second.state.standings if item.position == 1)
    assert first_winner == second_winner
    assert sum(player.stack for table in first.state.tables for player in table.players) == 720_000


@pytest.mark.asyncio
async def test_one_hundred_seeded_36_player_tournaments_finish_without_chip_drift() -> None:
    for number in range(100):
        coordinator = await simulate_36(
            f"soak-{number:03d}",
            seed_hex=f"{number:064x}",
        )
        assert coordinator.state.status is TournamentStatus.COMPLETED
        assert len(coordinator.state.standings) == 36
        assert (
            sum(player.stack for table in coordinator.state.tables for player in table.players)
            == 720_000
        )
