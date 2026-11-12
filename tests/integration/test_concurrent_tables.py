from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from poker_bot_platform.bots import BotActionRequest, BotEndpoint
from poker_bot_platform.bots.gateway import GatewayOutcome
from poker_bot_platform.domain import EntryKind, MatchStatus
from poker_bot_platform.integration import GameplayScheduler

from .match_stack import build_stack
from .test_match_runtime import advance_to_human_decision, passive_action


async def test_three_mixed_tables_keep_playing_while_one_bot_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stack = await build_stack()
    scheduler = GameplayScheduler(stack.registry, stack.runtime)
    blocked = asyncio.Event()
    release = asyncio.Event()
    original = stack.gateway.request_action

    async def slow(endpoint: BotEndpoint, token: str, request: BotActionRequest) -> GatewayOutcome:
        if str(endpoint.ip) == "10.20.0.11":
            blocked.set()
            await release.wait()
        return await original(endpoint, token, request)

    monkeypatch.setattr(stack.gateway, "request_action", slow)
    tables = []
    try:
        for index in range(3):
            match_id, code = await stack.create_match()
            owner = await stack.user(f"bot-{index}@example.com")
            bot = await stack.verified_bot(owner, f"Bot {index}", f"10.20.0.{11 + index}")
            await stack.join_bot(owner, code, bot)
            human = await stack.user(f"human-{index}@example.com")
            await stack.join_human(human, code, f"Player {index}")
            await stack.matches.start(stack.admin, match_id)
            tables.append((match_id, human.id))

        await scheduler.run_once(now=0)
        opening = [await stack.runtime.player_state(human, match) for match, human in tables]
        assert all(view.next_action_at == stack.clock() + timedelta(seconds=3) for view in opening)
        stack.clock.advance(3)
        await scheduler.start()
        slow_id, slow_human = tables[0]
        # Heads-up order depends on the dealer. Advance only the slow table until
        # its bot actually owns the turn; never assume the first actor's seat.
        for _ in range(100):
            if blocked.is_set():
                break
            current = await stack.runtime.player_state(slow_human, slow_id)
            if current.decision:
                await stack.runtime.submit_human_action(
                    slow_human, slow_id, passive_action(current)
                )
            elif current.next_action_at:
                stack.clock.value = current.next_action_at
            scheduler.wake()
            await asyncio.sleep(0.01)
        await asyncio.wait_for(blocked.wait(), 2)
        frozen = await asyncio.wait_for(stack.runtime.player_state(slow_human, slow_id), 0.5)
        assert frozen.turn is not None and frozen.turn.kind is EntryKind.BOT
        for match_id, human in tables[1:]:
            view = await asyncio.wait_for(advance_to_human_decision(stack, match_id, human), 2)
            assert view.decision is not None
            assert view.decision.deadline_at > stack.clock()
            assert view.match_id == match_id
            assert all(not seat.hole_cards for seat in view.seats if seat.seat != view.viewer_seat)
            after = await asyncio.wait_for(
                stack.runtime.submit_human_action(human, match_id, passive_action(view)), 0.5
            )
            assert after.table_version > view.table_version
            assert after.decision is None
            assert after.next_action_at is not None

        held = await stack.runtime.player_state(slow_human, slow_id)
        assert held.table_version == frozen.table_version
        # Organizer commands and match clocks are independently scoped as well.
        paused_id = tables[1][0]
        await asyncio.wait_for(stack.matches.pause(stack.admin, paused_id), 0.5)
        assert (await stack.registry.get(paused_id)).state.status in {
            MatchStatus.PAUSED,
            MatchStatus.PAUSE_REQUESTED,
        }
        assert (await stack.registry.get(tables[2][0])).state.status is MatchStatus.RUNNING

        # Let the stalled endpoint fail: only its table records the fallback.
        stack.network.broken.add("10.20.0.11")
        release.set()
        for _ in range(100):
            await asyncio.sleep(0.01)
            view = await stack.runtime.player_state(slow_human, slow_id)
            if any(action.automatic for action in view.action_history):
                break
        else:
            raise AssertionError("failed bot did not resolve with a recorded automatic action")
    finally:
        release.set()
        await scheduler.stop()
        await stack.gateway.aclose()
