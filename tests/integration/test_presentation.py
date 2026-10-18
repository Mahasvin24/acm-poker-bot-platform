from __future__ import annotations

from pokerkit import Deck

from poker_bot_platform.domain import (
    ActionType,
    EntryKind,
    HandSnapshot,
    PlayerAction,
    SeatState,
    StartHandRequest,
)
from poker_bot_platform.engine import PokerKitEngine
from poker_bot_platform.integration.presentation import natural_hand_result


def check_down(first_cards: tuple[str, ...], *, button_seat: int) -> HandSnapshot:
    rest = [repr(card) for card in Deck.STANDARD if repr(card) not in first_cards]
    engine = PokerKitEngine()
    snapshot = engine.start_hand(
        StartHandRequest(
            match_id="match-1",
            table_id="table-1",
            hand_id="hand-1",
            hand_number=1,
            table_version=0,
            button_seat=button_seat,
            small_blind=100,
            big_blind=200,
            big_blind_ante=0,
            seats=(
                SeatState(
                    seat=1, entrant_id="a", display_name="A", kind=EntryKind.HUMAN, stack=5_000
                ),
                SeatState(
                    seat=2, entrant_id="b", display_name="B", kind=EntryKind.BOT, stack=5_000
                ),
            ),
            deck_order=(*first_cards, *rest),
        )
    ).snapshot
    sequence = 0
    while not snapshot.completed:
        sequence += 1
        legal = {item.action for item in snapshot.legal_actions}
        action = ActionType.CHECK if ActionType.CHECK in legal else ActionType.CALL
        assert snapshot.acting_seat is not None
        snapshot = engine.apply_action(
            snapshot,
            PlayerAction(
                decision_id=f"d-{sequence}",
                table_version=snapshot.table_version,
                seat=snapshot.acting_seat,
                action=action,
            ),
        ).snapshot
    return snapshot


def test_showdown_reveals_only_hands_pokerkit_showed() -> None:
    # Index 0 (seat 2, first to act after the flop) holds aces and shows first; the
    # button's seven-deuce cannot win and is mucked.
    board = ("3c", "Kd", "Qs", "9h", "4c", "4s", "5c", "Jc")
    snapshot = check_down(("As", "7c", "Ah", "2d", *board), button_seat=1)
    result = natural_hand_result(snapshot)
    assert result is not None
    assert result.reason == "showdown"
    assert result.winner_seats == (2,)

    shown = {seat.seat for seat in snapshot.seats if seat.public_hole_cards}
    revealed = {hand.seat for hand in result.revealed_hands}
    assert revealed == shown
    assert 1 not in revealed
    assert all("7c" not in hand.hole_cards for hand in result.revealed_hands)
