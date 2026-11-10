from __future__ import annotations

import pytest

from poker_bot_platform.domain import MatchConfig, MatchStatus
from poker_bot_platform.integration import PacingConfig
from poker_bot_platform.integration.runtime import MatchRuntime
from tests.integration.match_stack import MatchStack, build_stack

NO_PACING = PacingConfig(deal_seconds=0, action_seconds=0, street_seconds=0, hand_end_seconds=0)


async def seated_bots(stack: MatchStack) -> str:
    match_id, code = await stack.create_match(
        MatchConfig(starting_stack=200, small_blind=50, big_blind=100)
    )
    for index in range(2):
        owner = await stack.user(f"bot{index}@example.com")
        profile = await stack.verified_bot(owner, f"Bot {index}", f"10.20.0.{11 + index}")
        await stack.join_bot(owner, code, profile)
    return match_id


@pytest.mark.parametrize("admin_end", [False, True])
async def test_hooks_bracket_play_and_reach_every_bot(admin_end: bool) -> None:
    stack = await build_stack(NO_PACING)
    try:
        match_id = await seated_bots(stack)
        match = await stack.registry.get(match_id)
        await stack.matches.start(stack.admin, match_id)
        if admin_end:
            await stack.matches.end(stack.admin, match_id)
        for _ in range(100):
            await stack.drive(match_id)
            if match.state.status is MatchStatus.COMPLETED:
                break
        assert match.state.status is MatchStatus.COMPLETED
        await stack.drive(match_id)
        assert len(stack.network.game_requests) == 4
        starts = [event for event in stack.network.game_requests if "starting_stack" in event]
        ends = [event for event in stack.network.game_requests if "status" in event]
        entries = {entry.entry_id for entry in match.state.entries}
        assert {event["entrant_id"] for event in starts} == entries
        assert {event["entrant_id"] for event in ends} == entries
        assert all(event["status"] == "completed" for event in ends)
        assert all(len(event["standings"]) == 2 for event in ends)
        assert all("hole_cards" not in str(event) for event in stack.network.game_requests)
        assert stack.network.action_requests
        # Additional scheduler polls cannot resend hooks.
        await stack.drive(match_id)
        assert len(stack.network.game_requests) == 4
    finally:
        await stack.gateway.aclose()


async def test_cancel_before_first_drive_sends_only_end_and_lobby_sends_nothing() -> None:
    stack = await build_stack(NO_PACING)
    try:
        match_id = await seated_bots(stack)
        await stack.drive(match_id)
        assert not stack.network.game_requests
        await stack.matches.start(stack.admin, match_id)
        await stack.matches.cancel(stack.admin, match_id)
        await stack.drive(match_id)
        assert len(stack.network.game_requests) == 2
        assert all(event["status"] == "cancelled" for event in stack.network.game_requests)
        assert not stack.network.action_requests
        lobby_id, _ = await stack.create_match()
        await stack.matches.cancel(stack.admin, lobby_id)
        await stack.drive(lobby_id)
        assert len(stack.network.game_requests) == 2
    finally:
        await stack.gateway.aclose()


async def test_start_precedes_actions_and_restart_replays_without_blocking_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stack = await build_stack(NO_PACING)
    try:
        match_id = await seated_bots(stack)
        match = await stack.registry.get(match_id)
        await stack.matches.start(stack.admin, match_id)
        calls: list[str] = []
        start_game = stack.gateway.start_game
        request_action = stack.gateway.request_action

        async def start(*args, **kwargs):
            calls.append("start")
            return await start_game(*args, **kwargs)

        async def action(*args, **kwargs):
            assert calls.count("start") == 2
            calls.append("action")
            return await request_action(*args, **kwargs)

        monkeypatch.setattr(stack.gateway, "start_game", start)
        monkeypatch.setattr(stack.gateway, "request_action", action)
        # Stop after the opening hooks to model a process restart during a match.
        await stack.runtime._notify_game_lifecycle(match.state)
        assert calls == ["start", "start"]
        restarted = MatchRuntime(
            stack.registry, stack.tables, stack.auth_repository, stack.runtime._token_store,
            stack.gateway, clock=stack.clock, pacing=NO_PACING,
        )
        calls.clear()
        # A missing hook on an older bot must not prevent its action endpoint running.
        from poker_bot_platform.bots.gateway import VerificationOutcome
        from poker_bot_platform.domain import FailureReason

        async def missing_start(*args, **kwargs):
            calls.append("start")
            return VerificationOutcome(verified=False, failure_reason=FailureReason.HTTP_STATUS)

        monkeypatch.setattr(stack.gateway, "start_game", missing_start)
        await restarted.drive(match_id)
        assert calls[:2] == ["start", "start"]
        assert "action" in calls
    finally:
        await stack.gateway.aclose()


async def test_pause_resume_preserves_game_and_cancellation_sends_end() -> None:
    stack = await build_stack(NO_PACING)
    try:
        owner = await stack.user("owner@example.com")
        human = await stack.user("human@example.com")
        profile = await stack.verified_bot(owner, "Bot", "10.20.0.11")
        match_id, code = await stack.create_match()
        await stack.join_bot(owner, code, profile)
        await stack.join_human(human, code, "Human")
        await stack.matches.start(stack.admin, match_id)
        await stack.drive(match_id)
        assert len(stack.network.game_requests) == 1
        await stack.matches.pause(stack.admin, match_id)
        await stack.matches.resume(stack.admin, match_id)
        await stack.drive(match_id)
        assert len(stack.network.game_requests) == 1
        await stack.matches.cancel(stack.admin, match_id)
        await stack.drive(match_id)
        assert len(stack.network.game_requests) == 2
        assert stack.network.game_requests[-1]["status"] == "cancelled"
    finally:
        await stack.gateway.aclose()
