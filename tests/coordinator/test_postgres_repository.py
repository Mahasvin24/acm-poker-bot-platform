from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy.engine import make_url

from poker_bot_platform.domain import ActionType, PendingDecision, PlayerAction
from poker_bot_platform.engine import FakePokerEngine
from poker_bot_platform.persistence import DecisionConflictError, create_database

from .conftest import NOW, start_request

_DATABASE_URL = os.environ.get("POKER_TEST_DATABASE_URL")
_IS_SAFE_TEST_DATABASE = bool(
    _DATABASE_URL and (make_url(_DATABASE_URL).database or "").endswith("_test")
)
pytestmark = pytest.mark.skipif(
    not _IS_SAFE_TEST_DATABASE,
    reason="set POKER_TEST_DATABASE_URL to a dedicated database ending in _test",
)


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[str]:
    assert _DATABASE_URL is not None
    environment = {**os.environ, "POKER_DATABASE_URL": _DATABASE_URL}
    subprocess.run(
        ["python3", "-m", "alembic", "upgrade", "head"],
        check=True,
        env=environment,
    )
    yield _DATABASE_URL
    subprocess.run(
        ["python3", "-m", "alembic", "downgrade", "base"],
        check=True,
        env=environment,
    )


@pytest.mark.asyncio
async def test_postgres_json_round_trip_partial_index_and_atomic_commit(
    migrated_database: str,
) -> None:
    suffix = uuid.uuid4().hex
    tournament_id = f"tournament-{suffix}"
    table_id = f"table-{suffix}"
    hand_id = f"hand-{suffix}"
    engine = FakePokerEngine()
    database, repository = create_database(migrated_database)
    try:
        await repository.create_tournament(tournament_id, {"starting_stack": 20_000})
        request = start_request().model_copy(
            update={
                "tournament_id": tournament_id,
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
    finally:
        await database.dispose()
