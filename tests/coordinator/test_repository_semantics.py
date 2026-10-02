from __future__ import annotations

from datetime import timedelta

import pytest

from poker_bot_platform.domain import ActionRecord, ActionType, PendingDecision, PlayerAction
from poker_bot_platform.engine import FakePokerEngine
from poker_bot_platform.persistence import (
    DecisionConflictError,
    InMemoryTableRepository,
    VersionConflictError,
)

from .conftest import NOW, start_request


@pytest.mark.asyncio
async def test_transition_is_idempotent_by_table_and_decision(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    transition = engine.start_hand(start_request())
    await repository.create_table(transition.snapshot, transition.events)
    pending = PendingDecision(
        decision_id="decision-1",
        table_id="table-1",
        hand_id="hand-1",
        table_version=0,
        seat=1,
        deadline_at=NOW + timedelta(seconds=30),
        legal_actions=transition.snapshot.legal_actions,
    )
    await repository.create_pending(pending)
    applied = engine.apply_action(
        transition.snapshot,
        action=PlayerAction(
            decision_id="decision-1",
            table_version=0,
            seat=1,
            action=ActionType.CHECK,
        ),
    )
    action = applied.snapshot.action_history[-1]

    first = await repository.commit_transition(
        expected_version=0,
        snapshot=applied.snapshot,
        action=action,
        events=applied.events,
    )
    second = await repository.commit_transition(
        expected_version=0,
        snapshot=applied.snapshot,
        action=action,
        events=applied.events,
    )

    assert not first.idempotent
    assert second.idempotent
    assert second.snapshot == first.snapshot
    assert len(repository.actions) == 1


@pytest.mark.asyncio
async def test_invalid_transition_is_fully_rolled_back(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    transition = engine.start_hand(start_request())
    await repository.create_table(transition.snapshot, transition.events)
    pending = PendingDecision(
        decision_id="decision-1",
        table_id="table-1",
        hand_id="hand-1",
        table_version=0,
        seat=1,
        deadline_at=NOW + timedelta(seconds=30),
        legal_actions=transition.snapshot.legal_actions,
    )
    await repository.create_pending(pending)
    invalid_snapshot = transition.snapshot.model_copy(update={"table_version": 2})
    action = ActionRecord(
        sequence=1,
        decision_id="decision-1",
        seat=1,
        action=ActionType.CHECK,
    )

    with pytest.raises(VersionConflictError):
        await repository.commit_transition(
            expected_version=0,
            snapshot=invalid_snapshot,
            action=action,
            events=(),
        )

    stored = await repository.load_table("table-1")
    assert stored.snapshot.table_version == 0
    assert stored.pending == pending
    assert repository.actions == ()


@pytest.mark.asyncio
async def test_only_one_unresolved_decision_per_table(
    repository: InMemoryTableRepository, engine: FakePokerEngine
) -> None:
    transition = engine.start_hand(start_request())
    await repository.create_table(transition.snapshot)
    first = PendingDecision(
        decision_id="decision-1",
        table_id="table-1",
        hand_id="hand-1",
        table_version=0,
        seat=1,
        deadline_at=NOW + timedelta(seconds=30),
        legal_actions=transition.snapshot.legal_actions,
    )
    second = first.model_copy(update={"decision_id": "decision-2"})

    assert await repository.create_pending(first) == first
    assert await repository.create_pending(first) == first
    with pytest.raises(DecisionConflictError):
        await repository.create_pending(second)
