from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from poker_bot_platform.api.models import PlayerActionRequest, PlayerTableStateResponse
from poker_bot_platform.domain import ActionType, EntryKind, FailureReason, MatchConfig, MatchStatus
from poker_bot_platform.integration import (
    GameplayAccessError,
    GameplayConflictError,
    MatchCommandError,
    PacingConfig,
)

from .match_stack import MatchStack, build_stack

NO_PACING = PacingConfig(deal_seconds=0, action_seconds=0, street_seconds=0, hand_end_seconds=0)


async def human_vs_bots(
    stack: MatchStack,
    *,
    bots: int = 2,
    config: MatchConfig | None = None,
    force: bool = False,
) -> tuple[str, str]:
    ava = await stack.user("ava@example.com")
    owner = await stack.user("owner@example.com")
    match_id, code = await stack.create_match(config)
    await stack.join_human(ava, code, "Ava")
    for index in range(bots):
        profile = await stack.verified_bot(owner, f"Bot {index + 1}", f"10.20.0.{11 + index}")
        await stack.join_bot(owner, code, profile)
    await stack.matches.start(stack.admin, match_id, force=force)
    return match_id, ava.id


async def advance_to_human_decision(
    stack: MatchStack,
    match_id: str,
    account_id: str,
    *,
    assert_pauses: bool = False,
) -> PlayerTableStateResponse:
    for _ in range(200):
        await stack.drive(match_id)
        view = await stack.runtime.player_state(account_id, match_id)
        if view.decision is not None or view.match_status is MatchStatus.COMPLETED:
            return view
        if view.next_action_at is not None:
            if assert_pauses:
                version = view.table_version
                stack.clock.value = view.next_action_at - timedelta(milliseconds=1)
                await stack.drive(match_id)
                held = await stack.runtime.player_state(account_id, match_id)
                assert held.table_version == version
                assert held.decision is None
            stack.clock.value = view.next_action_at
        elif view.turn is not None:
            stack.clock.value = view.turn.deadline_at
        else:
            stack.clock.advance(0.25)
    raise AssertionError("no human decision was reached")


def passive_action(view: PlayerTableStateResponse, *, fold: bool = False) -> PlayerActionRequest:
    assert view.decision is not None
    legal = {item.action for item in view.decision.legal_actions}
    if fold and ActionType.FOLD in legal:
        action = ActionType.FOLD
    else:
        action = ActionType.CHECK if ActionType.CHECK in legal else ActionType.CALL
    return PlayerActionRequest(
        decision_id=view.decision.decision_id,
        table_version=view.decision.table_version,
        action=action,
    )


async def test_human_clock_starts_only_after_presentation_pauses() -> None:
    stack = await build_stack()
    match_id, ava = await human_vs_bots(stack)

    await stack.drive(match_id)
    dealing = await stack.runtime.player_state(ava, match_id)
    assert dealing.decision is None
    assert dealing.turn is None
    assert dealing.next_action_at == stack.clock() + timedelta(seconds=3)
    assert dealing.match is not None and dealing.match.name == "Club Night"
    assert dealing.viewer is not None and dealing.viewer.status == "seated"

    decision_view = await advance_to_human_decision(stack, match_id, ava, assert_pauses=True)
    assert decision_view.decision is not None
    assert decision_view.decision.duration_ms == 30_000
    assert decision_view.decision.deadline_at == stack.clock() + timedelta(seconds=30)
    assert decision_view.turn is not None and decision_view.turn.duration_ms == 30_000

    after = await stack.runtime.submit_human_action(ava, match_id, passive_action(decision_view))
    assert after.decision is None
    assert after.next_action_at is not None
    assert after.next_action_at - stack.clock() in {timedelta(seconds=1.5), timedelta(seconds=2.5)}


async def test_stale_or_out_of_turn_actions_are_rejected_cleanly() -> None:
    stack = await build_stack(NO_PACING)
    match_id, ava = await human_vs_bots(stack)
    view = await advance_to_human_decision(stack, match_id, ava)
    action = passive_action(view)
    await stack.runtime.submit_human_action(ava, match_id, action)
    with pytest.raises(GameplayConflictError):
        await stack.runtime.submit_human_action(ava, match_id, action)


async def test_absent_humans_are_marked_away_and_get_a_short_clock() -> None:
    stack = await build_stack(NO_PACING)
    match_id, ava = await human_vs_bots(stack)

    timeouts = 0
    view = await advance_to_human_decision(stack, match_id, ava)
    while timeouts < 2:
        assert view.decision is not None
        stack.clock.value = view.decision.deadline_at
        await stack.drive(match_id)
        timeouts += 1
        view = await advance_to_human_decision(stack, match_id, ava)

    assert view.decision is not None
    assert view.decision.duration_ms == 5_000
    me = next(seat for seat in view.seats if seat.seat == view.viewer_seat)
    assert me.away
    assert stack.runtime.entry_activity(view.viewer.entry_id if view.viewer else "").away

    await stack.runtime.submit_human_action(ava, match_id, passive_action(view))
    back = await stack.runtime.player_state(ava, match_id)
    assert not next(seat for seat in back.seats if seat.seat == back.viewer_seat).away


async def test_failing_bot_trips_breaker_and_is_probed_instead_of_waited_on() -> None:
    stack = await build_stack(NO_PACING)
    ava = await stack.user("ava@example.com")
    owner = await stack.user("owner@example.com")
    match_id, code = await stack.create_match()
    await stack.join_human(ava, code, "Ava")
    good = await stack.verified_bot(owner, "Good", "10.20.0.11")
    broken = await stack.verified_bot(owner, "Broken", "10.20.0.12")
    await stack.join_bot(owner, code, good)
    await stack.join_bot(owner, code, broken)
    stack.network.broken.add("10.20.0.12")

    with pytest.raises(MatchCommandError, match="Broken did not answer"):
        await stack.matches.start(stack.admin, match_id)
    await stack.matches.start(stack.admin, match_id, force=True)

    for _ in range(20):
        view = await advance_to_human_decision(stack, match_id, ava.id)
        if stack.runtime.bot_stats(broken).consecutive_failures >= 4:
            break
        await stack.runtime.submit_human_action(ava.id, match_id, passive_action(view, fold=True))
    stats = stack.runtime.bot_stats(broken)
    assert stats.consecutive_failures >= 4
    assert stats.failures[FailureReason.HTTP_STATUS.value] == 3
    assert stats.failures[FailureReason.CONNECTION.value] >= 1
    assert stack.network.calls[("10.20.0.12", "/v1/action")] == 3
    assert stack.network.calls[("10.20.0.12", "/v1/health")] >= 2
    assert stats.recent[0].explanation is not None
    assert stack.runtime.bot_stats(good).consecutive_failures == 0

    detail = await stack.matches.admin_detail(match_id)
    broken_entry = next(entry for entry in detail.entries if entry.bot_name == "Broken")
    assert broken_entry.bot_consecutive_failures >= 4


async def test_player_reads_do_not_wait_for_a_slow_bot() -> None:
    stack = await build_stack(NO_PACING)
    match_id, ava = await human_vs_bots(stack)
    stack.network.delay_seconds = 0.4

    await stack.drive(match_id)
    for _ in range(50):
        view = await stack.runtime.spectator_state(match_id)
        acting = next((seat for seat in view.seats if seat.seat == view.acting_seat), None)
        if acting is not None and acting.kind is EntryKind.BOT and not view.completed:
            break
        human_view = await advance_to_human_decision(stack, match_id, ava)
        await stack.runtime.submit_human_action(ava, match_id, passive_action(human_view))
    else:
        raise AssertionError("never reached a bot turn")

    drive = asyncio.create_task(stack.drive(match_id))
    await asyncio.sleep(0.05)
    during = await asyncio.wait_for(stack.runtime.player_state(ava, match_id), timeout=0.1)
    assert not drive.done()
    assert during.turn is not None
    assert during.turn.kind is EntryKind.BOT
    assert during.turn.duration_ms == 3_000
    await drive


async def test_table_recovers_after_a_database_failure() -> None:
    stack = await build_stack(NO_PACING)
    match_id, ava = await human_vs_bots(stack)
    view = await advance_to_human_decision(stack, match_id, ava)

    stack.tables.inject_failure("commit_transition")
    request = passive_action(view)
    with pytest.raises(Exception, match="database"):
        await stack.runtime.submit_human_action(ava, match_id, request)

    # The paused coordinator is discarded; the next access restores durable state and
    # resolves the interrupted decision exactly once.
    stack.clock.advance(1)
    await stack.drive(match_id)
    recovered = await stack.runtime.player_state(ava, match_id)
    assert (recovered.hand_number, recovered.table_version) > (view.hand_number, view.table_version)
    recoveries = [
        action
        for action in stack.tables.actions
        if action.failure_reason is FailureReason.RESTART_RECOVERY
    ]
    assert len(recoveries) == 1
    assert recoveries[0].seat == view.viewer_seat
    assert recoveries[0].automatic


async def test_bot_only_tables_run_without_presentation_pauses() -> None:
    stack = await build_stack()
    owner = await stack.user("owner@example.com")
    match_id, code = await stack.create_match()
    for index in range(2):
        profile = await stack.verified_bot(owner, f"Bot {index}", f"10.20.0.{20 + index}")
        await stack.join_bot(owner, code, profile)
    await stack.matches.start(stack.admin, match_id)

    await stack.drive(match_id)
    view = await stack.runtime.player_state(owner.id, match_id)
    assert view.next_action_at is None
    assert view.hand_number > 1 or view.completed
    assert view.viewer_seat is not None
    own_seat = next(seat for seat in view.seats if seat.seat == view.viewer_seat)
    assert len(own_seat.hole_cards) == 2
    with pytest.raises(GameplayAccessError):
        await stack.runtime.submit_human_action(
            owner.id,
            match_id,
            PlayerActionRequest(decision_id="x", table_version=0, action=ActionType.FOLD),
        )


async def test_match_plays_to_completion_with_standings_and_spectator_privacy() -> None:
    stack = await build_stack(NO_PACING)
    config = MatchConfig(starting_stack=400, small_blind=100, big_blind=200)
    match_id, ava = await human_vs_bots(stack, bots=1, config=config)

    for _ in range(100):
        view = await advance_to_human_decision(stack, match_id, ava)
        if view.match_status is MatchStatus.COMPLETED:
            break
        spectate = await stack.runtime.spectator_state(match_id)
        assert spectate.viewer_seat is None
        assert spectate.decision is None
        assert all(not seat.hole_cards for seat in spectate.seats if not spectate.completed)
        await stack.runtime.submit_human_action(ava, match_id, passive_action(view, fold=True))
    else:
        raise AssertionError("match did not finish")

    final = await stack.runtime.player_state(ava, match_id)
    assert final.match_status is MatchStatus.COMPLETED
    assert final.viewer is not None
    assert final.viewer.status in {"winner", "finished"}
    assert final.match is not None
    assert [item.position for item in final.match.standings] == [1, 2]
    assert final.decision is None
    assert final.turn is None


async def test_bot_requests_carry_v2_context_without_leaking_private_cards() -> None:
    stack = await build_stack(NO_PACING)
    match_id, ava = await human_vs_bots(stack)
    while True:
        view = await advance_to_human_decision(stack, match_id, ava)
        if view.hand_number >= 3:
            break
        await stack.runtime.submit_human_action(ava, match_id, passive_action(view))

    requests = stack.network.action_requests
    assert requests
    assert all(request["protocol"] == "poker-bot.v2" for request in requests)
    for request in requests:
        match = request["match"]
        assert isinstance(match, dict)
        assert match["players_remaining"] == 3
        table = request["table"]
        assert isinstance(table, dict)
        assert all(entry["street"] for entry in table["action_history"])

    later = [request for request in requests if request["previous_hand"] is not None]
    assert later
    for request in later:
        previous = request["previous_hand"]
        assert isinstance(previous, dict)
        assert previous["hand_number"] < request["match"]["hand_number"]  # type: ignore[index]
        assert sum(item["stack"] for item in previous["final_stacks"]) == 60_000
        for hand in previous["shown_hands"]:
            assert len(hand["hole_cards"]) == 2
