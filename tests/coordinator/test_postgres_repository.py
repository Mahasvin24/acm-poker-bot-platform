from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from poker_bot_platform.domain import (
    ActionType,
    MatchStatus,
    PendingDecision,
    PlayerAction,
    TableStatus,
)
from poker_bot_platform.engine import FakePokerEngine
from poker_bot_platform.match import AuditEntry, SqlAlchemyMatchStore
from poker_bot_platform.persistence import DecisionConflictError, create_database_components

from ..postgres import lobby_state, migrated_database, requires_postgres
from .conftest import NOW, start_request

pytestmark = requires_postgres
__all__ = ["migrated_database"]


@pytest.mark.asyncio
async def test_postgres_json_round_trip_partial_index_and_atomic_commit(
    migrated_database: str,
) -> None:
    suffix = uuid.uuid4().hex
    match_id = f"match-{suffix}"
    table_id = f"table-{suffix}"
    hand_id = f"hand-{suffix}"
    engine = FakePokerEngine()
    database, sessions, repository = create_database_components(migrated_database)
    try:
        store = SqlAlchemyMatchStore(sessions)
        lobby = lobby_state(match_id, join_code=suffix[:6].upper())
        await store.create(lobby, AuditEntry(actor_id="admin", command="create_match"))
        running = lobby.model_copy(update={"status": MatchStatus.RUNNING, "revision": 1})
        await store.save(
            running,
            expected_revision=0,
            audit=AuditEntry(actor_id="admin", command="start_match"),
        )
        assert await store.load(match_id) == running
        assert match_id in await store.list_active_match_ids()
        request = start_request().model_copy(
            update={
                "match_id": match_id,
                "table_id": table_id,
                "hand_id": hand_id,
            }
        )
        started = engine.start_hand(request)
        await repository.create_table(started.snapshot, started.events)
        pending = PendingDecision(
            decision_id=f"decision-{suffix}",
            table_id=table_id,
            hand_id=hand_id,
            table_version=0,
            seat=1,
            deadline_at=NOW + timedelta(seconds=30),
            legal_actions=started.snapshot.legal_actions,
        )
        await repository.create_pending(pending)
        with pytest.raises(DecisionConflictError):
            await repository.create_pending(
                pending.model_copy(update={"decision_id": f"other-{suffix}"})
            )

        transition = engine.apply_action(
            started.snapshot,
            PlayerAction(
                decision_id=pending.decision_id,
                table_version=0,
                seat=1,
                action=ActionType.CHECK,
            ),
        )
        action = transition.snapshot.action_history[-1]
        committed = await repository.commit_transition(
            expected_version=0,
            snapshot=transition.snapshot,
            action=action,
            events=transition.events,
        )
        loaded = await repository.load_table(table_id)

        assert loaded.snapshot == committed.snapshot
        assert loaded.pending is None
        assert loaded.snapshot.model_dump(mode="json") == transition.snapshot.model_dump(
            mode="json"
        )

        assert (
            await repository.update_table_status(
                table_id,
                expected_version=loaded.snapshot.table_version,
                expected_status=TableStatus.RUNNING,
                status=TableStatus.PAUSE_REQUESTED,
            )
            is TableStatus.PAUSE_REQUESTED
        )
        await repository.update_table_status(
            table_id,
            expected_version=loaded.snapshot.table_version,
            expected_status=TableStatus.PAUSE_REQUESTED,
            status=TableStatus.RUNNING,
        )
        next_request = request.model_copy(
            update={
                "hand_id": f"next-{hand_id}",
                "hand_number": 2,
                "table_version": loaded.snapshot.table_version + 1,
                "button_seat": 2,
            }
        )
        next_transition = engine.start_hand(next_request)
        next_commit = await repository.commit_next_hand(
            expected_version=loaded.snapshot.table_version,
            snapshot=next_transition.snapshot,
            events=next_transition.events,
        )
        assert next_commit.snapshot.hand_id == next_request.hand_id
        assert (await repository.load_table(table_id)).snapshot == next_commit.snapshot
    finally:
        await database.dispose()
