from __future__ import annotations

from datetime import UTC, datetime

import pytest

from poker_bot_platform.auth import AuthService, InMemoryAuthRepository
from poker_bot_platform.auth.service import InvalidCredentialsError
from poker_bot_platform.auth.career import match_result_rows
from poker_bot_platform.domain import EntryKind, MatchConfig, MatchStatus, Role
from poker_bot_platform.match import InMemoryMatchStore, MatchState
from poker_bot_platform.match.models import AuditEntry

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


def _completed_state() -> MatchState:
    config = MatchConfig.model_validate(
        {
            "max_seats": 4,
            "starting_stack": 20_000,
            "small_blind": 100,
            "big_blind": 200,
            "big_blind_ante": False,
            "human_action_timeout_ms": 30_000,
            "blind_increase_minutes": None,
        }
    )
    return MatchState.model_validate(
        {
            "match_id": "m-test",
            "name": "Final",
            "join_code": None,
            "config": config.model_dump(),
            "status": MatchStatus.COMPLETED.value,
            "seed_hex": "a" * 64,
            "created_by": "admin",
            "created_at": NOW,
            "entries": [
                {
                    "entry_id": "e1",
                    "account_id": "a1",
                    "display_name": "Winner",
                    "kind": EntryKind.HUMAN.value,
                    "joined_at": NOW,
                },
                {
                    "entry_id": "e2",
                    "account_id": "a2",
                    "display_name": "Runner",
                    "kind": EntryKind.HUMAN.value,
                    "joined_at": NOW,
                },
            ],
            "standings": [
                {
                    "entry_id": "e1",
                    "display_name": "Winner",
                    "kind": EntryKind.HUMAN.value,
                    "position": 1,
                    "final_stack": 25_000,
                },
                {
                    "entry_id": "e2",
                    "display_name": "Runner",
                    "kind": EntryKind.HUMAN.value,
                    "position": 2,
                    "final_stack": 15_000,
                },
            ],
            "revision": 2,
        }
    )


def test_match_result_rows_compute_chip_delta_against_buy_in() -> None:
    rows = match_result_rows(_completed_state())
    assert [(row.account_id, row.chip_delta) for row in rows] == [
        ("a1", 5_000),
        ("a2", -5_000),
    ]


@pytest.mark.asyncio
async def test_match_store_records_career_on_completion() -> None:
    repository = InMemoryAuthRepository()
    winner = await repository.create_account("a1@test.com", "hash", Role.USER)
    runner = await repository.create_account("a2@test.com", "hash", Role.USER)
    state = _completed_state().model_copy(
        update={
            "entries": tuple(
                entry.model_copy(
                    update={"account_id": winner.id if entry.entry_id == "e1" else runner.id}
                )
                for entry in _completed_state().entries
            )
        }
    )
    store = InMemoryMatchStore(repository)
    lobby = state.model_copy(update={"status": MatchStatus.LOBBY, "standings": (), "revision": 0})
    await store.create(lobby, AuditEntry(actor_id="admin", command="create"))
    running = lobby.model_copy(update={"status": MatchStatus.RUNNING, "revision": 1})
    await store.save(
        running,
        expected_revision=0,
        audit=AuditEntry(actor_id="admin", command="start"),
    )
    await store.save(
        state,
        expected_revision=1,
        audit=AuditEntry(actor_id="admin", command="end"),
    )
    summary = await repository.career_summary(winner.id)
    assert summary.career_chip_total == 5_000
    assert summary.matches_finished == 1


@pytest.mark.asyncio
async def test_password_reset_request_and_forgotten_login() -> None:
    repository = InMemoryAuthRepository()
    auth = AuthService(repository, clock=lambda: NOW)
    account = await auth.register("player@test.com", "long-enough-password")
    await auth.request_password_reset("player@test.com")
    requests = await auth.password_reset_requests()
    assert len(requests) == 1
    assert requests[0].email == "player@test.com"
    await auth.delete_account(account, "long-enough-password")
    with pytest.raises(InvalidCredentialsError):
        await auth.login("player@test.com", "long-enough-password")
