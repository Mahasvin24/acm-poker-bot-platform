from __future__ import annotations

from datetime import UTC, datetime

import pytest

from poker_bot_platform.domain import EntryKind, MatchConfig, MatchStatus
from poker_bot_platform.match import (
    InMemoryMatchStore,
    MatchCoordinator,
    MatchEntry,
    MatchError,
    MatchRegistry,
    format_join_code,
    generate_join_code,
    normalize_join_code,
)

NOW = datetime(2026, 10, 18, 19, tzinfo=UTC)


def human(name: str, account: str | None = None) -> MatchEntry:
    return MatchEntry(
        entry_id=f"entry-{name}",
        account_id=account or f"account-{name}",
        display_name=name,
        kind=EntryKind.HUMAN,
        joined_at=NOW,
    )


def bot(name: str, account: str, profile: str) -> MatchEntry:
    return MatchEntry(
        entry_id=f"entry-{name}",
        account_id=account,
        display_name=name,
        kind=EntryKind.BOT,
        bot_profile_id=profile,
        joined_at=NOW,
    )


async def lobby(config: MatchConfig | None = None) -> tuple[MatchCoordinator, InMemoryMatchStore]:
    store = InMemoryMatchStore()
    coordinator = await MatchCoordinator.create(
        "m-1",
        "Friday Match",
        config or MatchConfig(),
        "K7Q4PM",
        store,
        created_by="admin",
        created_at=NOW,
        seed_hex="ab" * 32,
    )
    return coordinator, store


def test_join_codes_are_unambiguous_and_forgiving_to_type() -> None:
    code = generate_join_code()
    assert len(code) == 6
    assert not set(code) & set("01ILOU")
    assert normalize_join_code(" k7q-4pm ") == "K7Q4PM"
    assert format_join_code("K7Q4PM") == "K7Q-4PM"
    for bad in ("K7Q4P", "K7Q4PMX", "K7Q4P0", "I7Q4PM"):
        with pytest.raises(ValueError):
            normalize_join_code(bad)


async def test_lobby_enforces_seats_one_human_per_account_and_unique_bots() -> None:
    coordinator, _store = await lobby(MatchConfig(max_seats=3))
    await coordinator.join(human("Ava", "owner"), actor_id="owner")
    await coordinator.join(bot("Atlas", "owner", "profile-1"), actor_id="owner")

    with pytest.raises(MatchError, match="human seat"):
        await coordinator.join(human("Ava Again", "owner"), actor_id="owner")
    with pytest.raises(MatchError, match="already seated"):
        await coordinator.join(bot("Atlas Copy", "owner", "profile-1"), actor_id="owner")
    with pytest.raises(MatchError, match="display name"):
        await coordinator.join(human("ava"), actor_id="x")

    await coordinator.join(human("Ben"), actor_id="ben")
    with pytest.raises(MatchError, match="full"):
        await coordinator.join(human("Cy"), actor_id="cy")

    await coordinator.remove_entry("entry-Ben", actor_id="admin")
    assert [entry.display_name for entry in coordinator.state.entries] == ["Ava", "Atlas"]


async def test_start_requires_two_players_then_seats_everyone_and_schedules_a_hand() -> None:
    coordinator, store = await lobby()
    await coordinator.join(human("Ava"), actor_id="ava")
    with pytest.raises(MatchError, match="at least two"):
        await coordinator.start(actor_id="admin")
    await coordinator.join(human("Ben"), actor_id="ben")
    state = await coordinator.start(actor_id="admin")

    assert state.status is MatchStatus.RUNNING
    assert state.table is not None
    assert {player.seat for player in state.table.players} == {1, 4}
    assert state.table.hand_in_progress
    assert state.table.hand_number == 1
    request = coordinator.hand_request()
    assert request.match_id == "m-1"
    assert sorted(request.deck_order) == sorted(set(request.deck_order))
    with pytest.raises(MatchError, match="already started"):
        await coordinator.join(human("Late"), actor_id="late")
    assert [entry.command for entry in store.audit_entries("m-1")][-1] == "start_match"


async def test_hand_results_record_eliminations_and_complete_the_match() -> None:
    coordinator, _store = await lobby(MatchConfig(starting_stack=1_000))
    for name in ("Ava", "Ben", "Cy"):
        await coordinator.join(human(name), actor_id=name)
    state = await coordinator.start(actor_id="admin")
    assert state.table is not None
    table_id = state.table.table_id

    state = await coordinator.record_hand_completed(
        table_id, {"entry-Ava": 2_000, "entry-Ben": 0, "entry-Cy": 1_000}
    )
    assert state.status is MatchStatus.RUNNING
    assert [(item.display_name, item.position) for item in state.standings] == [("Ben", 3)]
    assert state.table is not None
    assert state.table.hand_number == 2

    state = await coordinator.record_hand_completed(table_id, {"entry-Ava": 3_000, "entry-Cy": 0})
    assert state.status is MatchStatus.COMPLETED
    assert state.join_code is None
    assert [(item.display_name, item.position) for item in state.standings] == [
        ("Ava", 1),
        ("Cy", 2),
        ("Ben", 3),
    ]


async def test_hand_results_must_conserve_chips() -> None:
    coordinator, _store = await lobby()
    await coordinator.join(human("Ava"), actor_id="ava")
    await coordinator.join(human("Ben"), actor_id="ben")
    state = await coordinator.start(actor_id="admin")
    assert state.table is not None
    with pytest.raises(MatchError, match="conserve"):
        await coordinator.record_hand_completed(
            state.table.table_id, {"entry-Ava": 30_000, "entry-Ben": 30_000}
        )


async def test_pause_end_and_cancel_wait_for_or_abandon_the_current_hand() -> None:
    coordinator, _store = await lobby()
    for name in ("Ava", "Ben", "Cy"):
        await coordinator.join(human(name), actor_id=name)
    state = await coordinator.start(actor_id="admin")
    assert state.table is not None
    table_id = state.table.table_id

    state = await coordinator.request_pause(actor_id="admin")
    assert state.status is MatchStatus.PAUSE_REQUESTED
    state = await coordinator.record_hand_completed(
        table_id, {"entry-Ava": 20_000, "entry-Ben": 20_000, "entry-Cy": 20_000}
    )
    assert state.status is MatchStatus.PAUSED
    assert state.table is not None and not state.table.hand_in_progress

    state = await coordinator.resume(actor_id="admin")
    assert state.status is MatchStatus.RUNNING
    assert state.table is not None and state.table.hand_in_progress

    state = await coordinator.request_end(actor_id="admin")
    assert state.end_requested
    state = await coordinator.record_hand_completed(
        table_id, {"entry-Ava": 30_000, "entry-Ben": 20_000, "entry-Cy": 10_000}
    )
    assert state.status is MatchStatus.COMPLETED
    assert [(item.display_name, item.position, item.final_stack) for item in state.standings] == [
        ("Ava", 1, 30_000),
        ("Ben", 2, 20_000),
        ("Cy", 3, 10_000),
    ]
    with pytest.raises(MatchError, match="already over"):
        await coordinator.cancel(actor_id="admin")


async def test_cancel_closes_the_lobby_and_releases_the_code() -> None:
    coordinator, store = await lobby()
    state = await coordinator.cancel(actor_id="admin")
    assert state.status is MatchStatus.CANCELLED
    assert state.join_code is None
    assert await store.find_by_join_code("K7Q4PM") is None


async def test_escalating_blinds_advance_on_ticks_and_apply_to_the_next_hand() -> None:
    config = MatchConfig(blind_increase_minutes=1)
    coordinator, _store = await lobby(config)
    await coordinator.join(human("Ava"), actor_id="ava")
    await coordinator.join(human("Ben"), actor_id="ben")
    state = await coordinator.start(actor_id="admin")
    assert state.table is not None
    assert coordinator.hand_request().big_blind == 200

    state = await coordinator.tick(61)
    assert state.level_number == 2
    assert state.level_remaining_seconds == 59
    assert coordinator.hand_request().big_blind == 200
    await coordinator.record_hand_completed(
        state.table.table_id, {"entry-Ava": 20_000, "entry-Ben": 20_000}
    )
    assert coordinator.hand_request().big_blind == 300


async def test_registry_allocates_codes_and_finds_open_matches() -> None:
    registry = MatchRegistry(InMemoryMatchStore(), clock=lambda: NOW)
    first = await registry.create("One", MatchConfig(), created_by="admin")
    second = await registry.create("Two", MatchConfig(), created_by="admin")
    assert first.state.join_code != second.state.join_code
    assert first.state.join_code is not None
    assert await registry.find_by_code(first.state.join_code) is first

    old_code = first.state.join_code
    await registry.regenerate_code(first.state.match_id, actor_id="admin")
    assert first.state.join_code != old_code
    assert await registry.find_by_code(old_code) is None
    assert [state.name for state in await registry.list_states()] == ["One", "Two"]
