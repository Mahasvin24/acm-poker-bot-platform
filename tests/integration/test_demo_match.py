from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from poker_bot_platform.api.models import PlayerActionRequest
from poker_bot_platform.domain import ActionType
from poker_bot_platform.integration.demo_match import EphemeralDemoMatch


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


async def advance_past_bot_turn(
    demo: EphemeralDemoMatch,
    clock: MutableClock,
):
    before = await demo.current()
    assert before.table is not None
    assert before.table.turn is not None
    assert before.table.turn.kind.value == "bot"
    version = before.table.table_version

    clock.advance(3)
    waiting = await demo.current()
    assert waiting.table is not None
    assert waiting.table.table_version == version

    clock.advance(1)
    return await demo.current()


async def advance_until_human_or_complete(
    demo: EphemeralDemoMatch,
    clock: MutableClock,
    state,
):
    for _ in range(80):
        if state.status != "active" or state.table is None or state.table.decision is not None:
            return state
        if state.table.turn is not None:
            assert state.table.turn.kind.value == "bot"
            state = await advance_past_bot_turn(demo, clock)
            continue
        clock.advance(3)
        state = await demo.current()
    raise AssertionError("demo did not reach a human decision or terminal state")


async def test_demo_match_runs_without_durable_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "poker_bot_platform.integration.demo_match.secrets.choice",
        lambda _choices: 1,
    )
    clock = MutableClock()
    demo = EphemeralDemoMatch(clock=clock)

    assert (await demo.current()).status == "idle"

    started = await demo.start()
    assert started.table is not None
    assert started.table.decision is None
    assert started.table.turn is None

    clock.advance(2)
    still_dealing = await demo.current()
    assert still_dealing.table is not None
    assert still_dealing.table.decision is None
    assert still_dealing.table.turn is None

    clock.advance(1)
    started = await demo.current()
    started = await advance_until_human_or_complete(demo, clock, started)

    assert started.status == "active"
    assert started.result is None
    assert started.table is not None
    assert started.table.decision is not None
    assert len(started.table.seats) == 4
    human = next(seat for seat in started.table.seats if seat.kind.value == "human")
    bots = [seat for seat in started.table.seats if seat.kind.value == "bot"]
    assert len(human.hole_cards) == 2
    assert len(bots) == 3
    assert all(bot.hole_cards == () for bot in bots)

    decision = started.table.decision
    legal = next(
        action
        for action in decision.legal_actions
        if action.action in {ActionType.CHECK, ActionType.CALL, ActionType.FOLD}
    )
    progressed = await demo.submit(
        PlayerActionRequest(
            decision_id=decision.decision_id,
            table_version=decision.table_version,
            action=legal.action,
        )
    )

    assert progressed.table is not None
    assert progressed.table.table_version > started.table.table_version

    completed = await demo.force("human_win")
    assert completed.status == "completed"
    assert completed.result == "human_win"
    assert completed.table is not None
    assert completed.table.completed
    assert completed.table.decision is None
    assert completed.table.turn is None
    assert completed.table.hand_result is not None
    assert completed.table.hand_result.reason == "forced"
    assert completed.table.hand_result.synthetic
    completed_human = next(seat for seat in completed.table.seats if seat.kind.value == "human")
    assert completed_human.stack == 80_000
    assert all(seat.stack == 0 for seat in completed.table.seats if seat.kind.value == "bot")
    assert completed.table.side_pots == ()

    ended = await demo.end()
    assert ended.status == "idle"
    assert ended.table is None


async def test_starting_again_replaces_the_single_ephemeral_match() -> None:
    demo = EphemeralDemoMatch()
    first = await demo.start()
    assert first.table is not None

    await demo.force("bot_win")
    restarted = await demo.start()

    assert restarted.status == "active"
    assert restarted.result is None
    assert restarted.table is not None
    assert restarted.match_id != first.match_id
    assert restarted.table.hand_id == first.table.hand_id
    assert all(seat.stack <= 20_000 for seat in restarted.table.seats)
    assert sum(seat.stack for seat in restarted.table.seats) + restarted.table.pot == 80_000


async def test_demo_match_can_play_through_to_a_natural_result() -> None:
    clock = MutableClock()
    demo = EphemeralDemoMatch(clock=clock)
    state = await demo.start()

    for _ in range(64):
        state = await advance_until_human_or_complete(demo, clock, state)
        if state.status == "completed":
            break
        assert state.table is not None
        assert state.table.decision is not None
        decision = state.table.decision
        legal = next(
            action
            for action in decision.legal_actions
            if action.action in {ActionType.CHECK, ActionType.CALL}
        )
        state = await demo.submit(
            PlayerActionRequest(
                decision_id=decision.decision_id,
                table_version=decision.table_version,
                action=legal.action,
            )
        )

    assert state.status == "completed"
    assert state.result in {"human_win", "bot_win", "tie"}
    assert state.table is not None
    assert state.table.street.value == "complete"
    assert state.table.decision is None
    assert state.table.turn is None
    assert state.table.side_pots == ()
    assert state.table.hand_result is not None
    assert state.table.hand_result.reason in {"fold", "showdown"}
    if state.table.hand_result.reason == "showdown":
        assert len(state.table.hand_result.revealed_hands) == 4
        assert all(hand.best_five for hand in state.table.hand_result.revealed_hands)

    # Terminal state is durable for the life of the ephemeral match. Polling after
    # completion must keep returning the showdown instead of skipping to idle.
    terminal = await demo.current()
    repeated = await demo.current()
    assert terminal == state
    assert repeated == state
