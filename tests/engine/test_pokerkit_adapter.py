from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pokerkit import Deck

from poker_bot_platform.domain import (
    ActionType,
    EngineTransition,
    EntryKind,
    HandSnapshot,
    PlayerAction,
    SeatState,
    StartHandRequest,
    Street,
)
from poker_bot_platform.engine.pokerkit_adapter import PokerKitEngine


def _deck(*prefix: str) -> tuple[str, ...]:
    cards = [repr(card) for card in Deck.STANDARD]
    assert len(prefix) == len(set(prefix))
    assert set(prefix) <= set(cards)
    return (*prefix, *(card for card in cards if card not in prefix))


def _seat(number: int, stack: int = 100) -> SeatState:
    return SeatState(
        seat=number,
        entrant_id=f"entrant-{number}",
        display_name=f"Player {number}",
        kind=EntryKind.HUMAN,
        stack=stack,
    )


def _request(
    *seats: SeatState,
    button: int,
    deck: tuple[str, ...] | None = None,
    small_blind: int = 1,
    big_blind: int = 2,
    big_blind_ante: int = 0,
) -> StartHandRequest:
    return StartHandRequest(
        tournament_id="tournament-1",
        table_id="table-1",
        hand_id="hand-1",
        hand_number=1,
        table_version=7,
        button_seat=button,
        small_blind=small_blind,
        big_blind=big_blind,
        big_blind_ante=big_blind_ante,
        seats=seats,
        deck_order=deck or _deck(),
    )


def _act(
    engine: PokerKitEngine,
    snapshot: HandSnapshot,
    action: ActionType,
    amount_to: int | None = None,
) -> EngineTransition:
    # Kept as a helper rather than hiding the exact version/seat binding in
    # tests: every action exercises optimistic concurrency and turn ownership.
    assert snapshot.acting_seat is not None
    return engine.apply_action(
        snapshot,
        PlayerAction(
            decision_id=f"decision-{len(snapshot.action_history) + 1}",
            table_version=snapshot.table_version,
            seat=snapshot.acting_seat,
            action=action,
            amount_to=amount_to,
        ),
    )


def _check_or_call(engine: PokerKitEngine, snapshot: HandSnapshot) -> EngineTransition:
    actions = {candidate.action for candidate in snapshot.legal_actions}
    action = ActionType.CHECK if ActionType.CHECK in actions else ActionType.CALL
    return _act(engine, snapshot, action)


def test_heads_up_button_order_deck_and_big_blind_ante() -> None:
    engine = PokerKitEngine()
    request = _request(
        _seat(1, 250),
        _seat(4, 1_000),
        button=4,
        small_blind=100,
        big_blind=200,
        big_blind_ante=200,
        deck=_deck("As", "Ks", "Ah", "Kh"),
    )

    snapshot = engine.start_hand(request).snapshot

    assert snapshot.acting_seat == 4  # button/SB acts first pre-flop heads-up
    assert snapshot.seats[0].hole_cards == ("As", "Ah")
    assert snapshot.seats[1].hole_cards == ("Ks", "Kh")
    assert snapshot.seats[0].stack == 0
    assert snapshot.seats[0].committed_this_street == 200
    assert snapshot.seats[0].committed_this_hand == 250
    assert snapshot.seats[0].all_in
    assert snapshot.pot == 350
    assert snapshot.legal_actions[1].action is ActionType.CALL
    assert snapshot.legal_actions[1].amount == 100


def test_multiway_short_big_blind_posts_blind_before_remaining_ante() -> None:
    engine = PokerKitEngine()
    snapshot = engine.start_hand(
        _request(
            _seat(1, 1_000),
            _seat(2, 250),
            _seat(3, 1_000),
            button=3,
            small_blind=100,
            big_blind=200,
            big_blind_ante=200,
        )
    ).snapshot

    seats = {seat.seat: seat for seat in snapshot.seats}
    assert snapshot.acting_seat == 3
    assert seats[2].stack == 0
    assert seats[2].committed_this_street == 200
    assert seats[2].committed_this_hand == 250
    assert seats[2].all_in
    assert snapshot.pot == 350


def test_incomplete_all_in_raise_does_not_reopen_action() -> None:
    engine = PokerKitEngine()
    snapshot = engine.start_hand(
        _request(
            _seat(1),
            _seat(2),
            _seat(3),
            _seat(4, 8),
            button=4,
        )
    ).snapshot

    assert snapshot.acting_seat == 3
    snapshot = _act(engine, snapshot, ActionType.RAISE, 6).snapshot
    short_raise = {action.action: action for action in snapshot.legal_actions}
    assert snapshot.acting_seat == 4
    assert short_raise[ActionType.RAISE].min_amount_to == 8
    assert short_raise[ActionType.RAISE].max_amount_to == 8

    snapshot = _act(engine, snapshot, ActionType.RAISE, 8).snapshot
    snapshot = _act(engine, snapshot, ActionType.CALL).snapshot
    snapshot = _act(engine, snapshot, ActionType.CALL).snapshot

    assert snapshot.acting_seat == 3
    assert {action.action for action in snapshot.legal_actions} == {
        ActionType.FOLD,
        ActionType.CALL,
    }


def test_cumulative_incomplete_all_ins_reopen_action() -> None:
    engine = PokerKitEngine()
    snapshot = engine.start_hand(
        _request(
            _seat(1),
            _seat(2),
            _seat(3),
            _seat(4, 8),
            _seat(5, 10),
            button=5,
        )
    ).snapshot

    snapshot = _act(engine, snapshot, ActionType.RAISE, 6).snapshot
    snapshot = _act(engine, snapshot, ActionType.RAISE, 8).snapshot
    snapshot = _act(engine, snapshot, ActionType.RAISE, 10).snapshot
    snapshot = _act(engine, snapshot, ActionType.CALL).snapshot
    snapshot = _act(engine, snapshot, ActionType.CALL).snapshot

    legal = {action.action: action for action in snapshot.legal_actions}
    assert snapshot.acting_seat == 3
    assert ActionType.RAISE in legal
    assert legal[ActionType.RAISE].min_amount_to == 14


def test_odd_chip_goes_to_first_tied_winner_left_of_button() -> None:
    engine = PokerKitEngine()
    # Three players contribute two chips, and the BB contributes a one-chip
    # ante. Seats 1 and 2 tie with Broadway; seat 1 is first left of button 3.
    deck = _deck(
        "As",
        "Ah",
        "2c",
        "Kd",
        "Ks",
        "3d",
        "9c",
        "Qc",
        "Jd",
        "Tc",
        "9d",
        "4h",
        "9h",
        "5h",
    )
    snapshot = engine.start_hand(
        _request(
            _seat(1),
            _seat(2),
            _seat(3),
            button=3,
            big_blind_ante=1,
            deck=deck,
        )
    ).snapshot

    while not snapshot.completed:
        snapshot = _check_or_call(engine, snapshot).snapshot

    assert snapshot.community_cards == ("Qc", "Jd", "Tc", "4h", "5h")
    assert {seat.seat: seat.stack for seat in snapshot.seats} == {1: 102, 2: 100, 3: 98}
    assert sum(seat.stack for seat in snapshot.seats) == 300


def test_multiple_all_ins_create_correct_main_and_side_pot_payouts() -> None:
    engine = PokerKitEngine()
    deck = _deck(
        "As",
        "Ks",
        "Qs",
        "Ad",
        "Kd",
        "Qd",
        "9c",
        "2c",
        "3d",
        "4h",
        "9d",
        "5s",
        "9h",
        "7c",
    )
    transition = engine.start_hand(
        _request(_seat(1, 5), _seat(2, 10), _seat(3, 20), button=3, deck=deck)
    )
    snapshot = transition.snapshot

    snapshot = _act(engine, snapshot, ActionType.RAISE, 10).snapshot
    snapshot = _act(engine, snapshot, ActionType.CALL).snapshot
    transition = _act(engine, snapshot, ActionType.CALL)
    snapshot = transition.snapshot

    assert snapshot.completed
    assert {seat.seat: seat.stack for seat in snapshot.seats} == {1: 15, 2: 10, 3: 10}
    assert sum(seat.stack for seat in snapshot.seats) == 35
    completion = next(event for event in transition.events if event.event_type == "hand_completed")
    assert completion.payload["payouts"] == [
        {"seat": 1, "amount": 15, "stack": 15, "net": 10},
        {"seat": 2, "amount": 10, "stack": 10, "net": 0},
    ]
    assert completion.payload["eliminated_seats"] == []


def test_all_in_from_forced_bets_preserves_private_cards_for_recovery() -> None:
    engine = PokerKitEngine()
    transition = engine.start_hand(
        _request(
            _seat(1, 2),
            _seat(2, 1),
            button=2,
            deck=_deck("As", "Ks", "Ah", "Kh"),
        )
    )

    assert transition.snapshot.completed
    assert transition.snapshot.seats[0].hole_cards == ("As", "Ah")
    assert transition.snapshot.seats[1].hole_cards == ("Ks", "Kh")
    assert engine.restore(transition.snapshot) == transition.snapshot


def test_snapshot_is_json_serializable_and_restore_is_exact() -> None:
    engine = PokerKitEngine()
    snapshot = engine.start_hand(
        _request(
            _seat(1, 1_000),
            _seat(4, 1_000),
            button=4,
            big_blind_ante=2,
            deck=_deck(
                "As",
                "Ks",
                "Ah",
                "Kh",
                "2c",
                "3c",
                "4c",
                "5c",
                "6c",
                "7c",
                "8c",
                "9c",
            ),
        )
    ).snapshot

    for _ in range(3):
        assert engine.restore(snapshot) == snapshot
        json.loads(snapshot.model_dump_json())
        snapshot = _check_or_call(engine, snapshot).snapshot

    assert snapshot.street is Street.FLOP
    assert engine.restore(snapshot) == snapshot

    tampered = snapshot.model_copy(update={"pot": snapshot.pot + 1})
    with pytest.raises(ValueError, match="deterministic action replay"):
        engine.restore(tampered)


def test_invalid_deck_and_wrong_action_are_rejected() -> None:
    engine = PokerKitEngine()
    cards = _deck()
    bad_request = _request(
        _seat(1),
        _seat(2),
        button=2,
        deck=(*cards[:-1], cards[0]),
    )
    with pytest.raises(ValueError, match="each standard card exactly once"):
        engine.start_hand(bad_request)

    snapshot = engine.start_hand(_request(_seat(1), _seat(2), button=2)).snapshot
    with pytest.raises(ValueError, match="illegal check"):
        _act(engine, snapshot, ActionType.CHECK)


@st.composite
def _foldout_configs(draw: st.DrawFn) -> tuple[tuple[int, ...], int]:
    player_count = draw(st.integers(min_value=2, max_value=6))
    stacks = draw(
        st.lists(
            st.integers(min_value=3, max_value=2_000),
            min_size=player_count,
            max_size=player_count,
        ).map(tuple)
    )
    button = draw(st.integers(min_value=1, max_value=player_count))
    return stacks, button


@settings(max_examples=10_000, deadline=None)
@given(_foldout_configs())
def test_generated_foldouts_preserve_core_engine_invariants(
    config: tuple[tuple[int, ...], int],
) -> None:
    stacks, button = config
    engine = PokerKitEngine()
    initial_total = sum(stacks)
    snapshot = engine.start_hand(
        _request(
            *(_seat(index + 1, stack) for index, stack in enumerate(stacks)),
            button=button,
            big_blind_ante=2,
        )
    ).snapshot

    previous_version = snapshot.table_version
    while not snapshot.completed:
        legal = {candidate.action for candidate in snapshot.legal_actions}
        action = ActionType.FOLD if ActionType.FOLD in legal else (
            ActionType.CHECK if ActionType.CHECK in legal else ActionType.CALL
        )
        snapshot = _act(engine, snapshot, action).snapshot
        assert snapshot.table_version == previous_version + 1
        previous_version = snapshot.table_version
        assert engine.restore(snapshot) == snapshot

    cards = [
        card
        for seat in snapshot.seats
        for card in seat.hole_cards
    ] + list(snapshot.community_cards)
    assert len(cards) == len(set(cards))
    assert all(seat.stack >= 0 for seat in snapshot.seats)
    assert sum(seat.stack for seat in snapshot.seats) == initial_total
    assert [record.sequence for record in snapshot.action_history] == list(
        range(1, len(snapshot.action_history) + 1)
    )
