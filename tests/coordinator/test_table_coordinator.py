from __future__ import annotations

from datetime import timedelta

import pytest

from poker_bot_platform.coordinator import (
    ActorDecisionFailure,
    CoordinatorNotReadyError,
    InvalidActionError,
    TableCoordinator,
)
from poker_bot_platform.domain import ActionType, FailureReason, PlayerAction
from poker_bot_platform.engine import FakePokerEngine
from poker_bot_platform.persistence import InMemoryTableRepository, PersistenceError

from .conftest import NOW, start_request


@pytest.mark.asyncio
async def test_human_action_is_committed_with_snapshot_and_version(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    coordinator = TableCoordinator("table-1", engine, repository, clock=lambda: NOW)
    await coordinator.start_table(start_request())
    pending = await coordinator.open_decision(NOW + timedelta(seconds=30))

    result = await coordinator.submit_action(
        PlayerAction(
            decision_id=pending.decision_id,
            table_version=pending.table_version,
            seat=pending.seat,
            action=ActionType.CHECK,
        )
    )

    assert result.table_version == 1
    assert result.completed
    assert len(repository.actions) == 1
    stored = await repository.load_table("table-1")
    assert stored.snapshot == result
    assert stored.pending is None


@pytest.mark.asyncio
async def test_pending_decision_is_durable_before_actor_is_awaited(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    coordinator = TableCoordinator("table-1", engine, repository, clock=lambda: NOW)
    await coordinator.start_table(start_request())
    actor_observed_pending = False

    async def actor(pending: object, snapshot: object) -> PlayerAction:
        nonlocal actor_observed_pending
        stored = await repository.load_table("table-1")
        actor_observed_pending = stored.pending is not None
        assert stored.pending is not None
        return PlayerAction(
            decision_id=stored.pending.decision_id,
            table_version=stored.pending.table_version,
            seat=stored.pending.seat,
            action=ActionType.CHECK,
        )

    await coordinator.request_actor_action(actor, NOW + timedelta(seconds=3))

    assert actor_observed_pending


@pytest.mark.asyncio
async def test_actor_failure_records_deterministic_check_fallback(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    coordinator = TableCoordinator("table-1", engine, repository, clock=lambda: NOW)
    await coordinator.start_table(start_request())

    async def failing_actor(pending: object, snapshot: object) -> PlayerAction:
        raise ActorDecisionFailure(FailureReason.MALFORMED_JSON)

    result = await coordinator.request_actor_action(failing_actor, NOW + timedelta(seconds=3))

    action = result.action_history[-1]
    assert action.action is ActionType.CHECK
    assert action.automatic
    assert action.failure_reason is FailureReason.MALFORMED_JSON


@pytest.mark.asyncio
async def test_commit_failure_pauses_without_advancing_memory_or_durable_snapshot(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    coordinator = TableCoordinator("table-1", engine, repository, clock=lambda: NOW)
    initial = await coordinator.start_table(start_request())
    pending = await coordinator.open_decision(NOW + timedelta(seconds=30))
    repository.inject_failure("commit_transition")

    with pytest.raises(PersistenceError):
        await coordinator.submit_action(
            PlayerAction(
                decision_id=pending.decision_id,
                table_version=0,
                seat=1,
                action=ActionType.CHECK,
            )
        )

    assert coordinator.state.database_paused
    assert coordinator.state.snapshot == initial
    stored = await repository.load_table("table-1")
    assert stored.snapshot == initial
    assert stored.pending == pending
    assert repository.actions == ()
    with pytest.raises(CoordinatorNotReadyError):
        await coordinator.submit_action(
            PlayerAction(
                decision_id=pending.decision_id,
                table_version=0,
                seat=1,
                action=ActionType.CHECK,
            )
        )


@pytest.mark.asyncio
async def test_restore_resolves_interrupted_decision_without_redispatch(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    first = TableCoordinator("table-1", engine, repository, clock=lambda: NOW)
    await first.start_table(start_request())
    pending = await first.open_decision(NOW + timedelta(seconds=3))

    recovered = TableCoordinator("table-1", engine, repository, clock=lambda: NOW)
    result = await recovered.restore()

    assert result.table_version == 1
    assert result.action_history[-1].decision_id == pending.decision_id
    assert result.action_history[-1].action is ActionType.CHECK
    assert result.action_history[-1].automatic
    assert result.action_history[-1].failure_reason is FailureReason.RESTART_RECOVERY
    assert (await repository.load_table("table-1")).pending is None


@pytest.mark.asyncio
async def test_illegal_bot_action_falls_back_but_illegal_human_action_is_rejected(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    coordinator = TableCoordinator("table-1", engine, repository, clock=lambda: NOW)
    await coordinator.start_table(start_request())

    async def illegal_actor(pending: object, snapshot: object) -> PlayerAction:
        stored = await repository.load_table("table-1")
        assert stored.pending is not None
        return PlayerAction(
            decision_id=stored.pending.decision_id,
            table_version=stored.pending.table_version,
            seat=stored.pending.seat,
            action=ActionType.CALL,
        )

    result = await coordinator.request_actor_action(illegal_actor, NOW + timedelta(seconds=3))
    assert result.action_history[-1].failure_reason is FailureReason.ILLEGAL_ACTION


@pytest.mark.asyncio
async def test_illegal_human_action_is_rejected_without_resolving_decision(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    coordinator = TableCoordinator("table-1", engine, repository, clock=lambda: NOW)
    await coordinator.start_table(start_request())
    pending = await coordinator.open_decision(NOW + timedelta(seconds=30))

    with pytest.raises(InvalidActionError, match="not legal"):
        await coordinator.submit_action(
            PlayerAction(
                decision_id=pending.decision_id,
                table_version=pending.table_version,
                seat=pending.seat,
                action=ActionType.CALL,
            )
        )

    assert coordinator.state.pending == pending
    assert repository.actions == ()


@pytest.mark.asyncio
async def test_stale_bot_identity_uses_stale_fallback(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    coordinator = TableCoordinator("table-1", engine, repository, clock=lambda: NOW)
    await coordinator.start_table(start_request())

    async def stale_actor(pending: object, snapshot: object) -> PlayerAction:
        return PlayerAction(
            decision_id="some-old-decision",
            table_version=0,
            seat=1,
            action=ActionType.CHECK,
        )

    result = await coordinator.request_actor_action(stale_actor, NOW + timedelta(seconds=3))
    assert result.action_history[-1].failure_reason is FailureReason.STALE


@pytest.mark.asyncio
async def test_expired_human_decision_uses_timeout_fallback(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    now = NOW
    coordinator = TableCoordinator("table-1", engine, repository, clock=lambda: now)
    await coordinator.start_table(start_request())
    await coordinator.open_decision(NOW + timedelta(seconds=30))

    with pytest.raises(CoordinatorNotReadyError):
        await coordinator.expire_decision()

    now = NOW + timedelta(seconds=30)
    pending = coordinator.state.pending
    assert pending is not None
    with pytest.raises(InvalidActionError, match="deadline"):
        await coordinator.submit_action(
            PlayerAction(
                decision_id=pending.decision_id,
                table_version=pending.table_version,
                seat=pending.seat,
                action=ActionType.CHECK,
            )
        )

    result = await coordinator.expire_decision()
    assert result.action_history[-1].automatic
    assert result.action_history[-1].failure_reason is FailureReason.TIMEOUT
