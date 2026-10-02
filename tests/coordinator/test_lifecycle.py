from __future__ import annotations

from datetime import timedelta

import pytest

from poker_bot_platform.coordinator import (
    CoordinatorError,
    CoordinatorNotReadyError,
    TableCoordinator,
)
from poker_bot_platform.domain import (
    ActionType,
    HandSnapshot,
    PendingDecision,
    PlayerAction,
    StartHandRequest,
    TableStatus,
    TournamentStatus,
)
from poker_bot_platform.engine import FakePokerEngine
from poker_bot_platform.persistence import (
    InMemoryTableRepository,
    PersistenceError,
    StatusConflictError,
    VersionConflictError,
)

from .conftest import NOW, start_request


async def _complete_first_hand(
    coordinator: TableCoordinator,
) -> tuple[PendingDecision, HandSnapshot]:
    await coordinator.start_table(start_request())
    pending = await coordinator.open_decision(NOW + timedelta(seconds=30))
    completed = await coordinator.submit_action(
        PlayerAction(
            decision_id=pending.decision_id,
            table_version=pending.table_version,
            seat=pending.seat,
            action=ActionType.CHECK,
        )
    )
    return pending, completed


def _next_request(version: int = 2) -> StartHandRequest:
    return start_request(table_version=version).model_copy(
        update={"hand_id": "hand-2", "hand_number": 2, "button_seat": 2}
    )


@pytest.mark.asyncio
async def test_next_hand_atomically_replaces_completed_snapshot(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    coordinator = TableCoordinator("table-1", engine, repository, clock=lambda: NOW)
    _, completed = await _complete_first_hand(coordinator)

    started = await coordinator.start_next_hand(_next_request())

    assert started.hand_id == "hand-2"
    assert started.hand_number == 2
    assert started.table_version == completed.table_version + 1
    assert started.action_history == ()
    stored = await repository.load_table("table-1")
    assert stored.snapshot == started
    assert stored.pending is None


@pytest.mark.asyncio
async def test_next_hand_requires_completed_current_hand_and_exact_version(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    coordinator = TableCoordinator("table-1", engine, repository, clock=lambda: NOW)
    await coordinator.start_table(start_request())
    with pytest.raises(CoordinatorNotReadyError, match="not complete"):
        await coordinator.start_next_hand(_next_request(version=1))

    pending = await coordinator.open_decision(NOW + timedelta(seconds=30))
    await coordinator.submit_action(
        PlayerAction(
            decision_id=pending.decision_id,
            table_version=0,
            seat=1,
            action=ActionType.CHECK,
        )
    )
    with pytest.raises(CoordinatorError, match="next table version"):
        await coordinator.start_next_hand(_next_request(version=1))


@pytest.mark.asyncio
async def test_next_hand_database_failure_preserves_local_and_durable_state(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    coordinator = TableCoordinator("table-1", engine, repository, clock=lambda: NOW)
    _, completed = await _complete_first_hand(coordinator)
    repository.inject_failure("commit_next_hand")

    with pytest.raises(PersistenceError):
        await coordinator.start_next_hand(_next_request())

    assert coordinator.state.database_paused
    assert coordinator.state.snapshot == completed
    assert (await repository.load_table("table-1")).snapshot == completed


@pytest.mark.asyncio
async def test_next_hand_repository_commit_is_idempotent(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    coordinator = TableCoordinator("table-1", engine, repository, clock=lambda: NOW)
    _, completed = await _complete_first_hand(coordinator)
    transition = engine.start_hand(_next_request())

    first = await repository.commit_next_hand(
        expected_version=completed.table_version,
        snapshot=transition.snapshot,
        events=transition.events,
    )
    event_count = len(repository.events)
    second = await repository.commit_next_hand(
        expected_version=completed.table_version,
        snapshot=transition.snapshot,
        events=transition.events,
    )

    assert not first.idempotent
    assert second.idempotent
    assert first.snapshot == second.snapshot
    assert len(repository.events) == event_count


@pytest.mark.asyncio
async def test_tournament_updates_use_status_and_version_compare_and_swap(
    repository: InMemoryTableRepository,
) -> None:
    initial = await repository.load_tournament("tournament-1")
    assert initial.version == 0
    updated = await repository.update_tournament(
        "tournament-1",
        expected_version=0,
        expected_status=TournamentStatus.DRAFT,
        status=TournamentStatus.REGISTRATION_OPEN,
        config={"starting_stack": 30_000},
    )
    assert updated.version == 1
    assert updated.status is TournamentStatus.REGISTRATION_OPEN
    assert updated.config == {"starting_stack": 30_000}

    with pytest.raises(VersionConflictError):
        await repository.update_tournament(
            "tournament-1",
            expected_version=0,
            expected_status=TournamentStatus.DRAFT,
            status=TournamentStatus.SEATED,
        )
    with pytest.raises(StatusConflictError):
        await repository.update_tournament(
            "tournament-1",
            expected_version=1,
            expected_status=TournamentStatus.DRAFT,
            status=TournamentStatus.SEATED,
        )


@pytest.mark.asyncio
async def test_table_status_update_is_version_checked_and_idempotent(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    coordinator = TableCoordinator("table-1", engine, repository, clock=lambda: NOW)
    initial = await coordinator.start_table(start_request())

    assert await coordinator.set_status(TableStatus.PAUSE_REQUESTED) is TableStatus.PAUSE_REQUESTED
    assert coordinator.state.status is TableStatus.PAUSE_REQUESTED
    assert await coordinator.set_status(TableStatus.PAUSE_REQUESTED) is TableStatus.PAUSE_REQUESTED
    with pytest.raises(VersionConflictError):
        await repository.update_table_status(
            "table-1",
            expected_version=initial.table_version + 1,
            expected_status=TableStatus.PAUSE_REQUESTED,
            status=TableStatus.PAUSED,
        )
