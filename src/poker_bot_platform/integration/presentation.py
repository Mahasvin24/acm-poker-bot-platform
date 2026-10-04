from __future__ import annotations

from pokerkit import StandardHighHand

from poker_bot_platform.api.models import (
    HandAwardResponse,
    HandResultResponse,
    RevealedHandResponse,
)
from poker_bot_platform.domain import HandSnapshot, StartHandRequest


def natural_hand_result(snapshot: HandSnapshot) -> HandResultResponse | None:
    """Build the public, presentation-oriented result from authoritative engine state."""

    if not snapshot.completed:
        return None

    raw_request = snapshot.engine_state.get("start_request")
    if not isinstance(raw_request, dict):
        return None
    request = StartHandRequest.model_validate(raw_request)
    starting_stacks = {seat.seat: seat.stack for seat in request.seats}

    seats_by_number = {seat.seat: seat for seat in snapshot.seats}
    awards: list[HandAwardResponse] = []
    for raw_award in snapshot.engine_state.get("pot_awards", []):
        if not isinstance(raw_award, dict):
            continue
        seat_number = raw_award.get("seat")
        amount = raw_award.get("amount")
        seat = seats_by_number.get(seat_number)
        starting = starting_stacks.get(seat_number)
        if seat is None or starting is None or not isinstance(amount, int) or amount <= 0:
            continue
        awards.append(
            HandAwardResponse(
                seat=seat.seat,
                amount=amount,
                net=seat.stack - starting,
            )
        )

    live_hands = [seat for seat in snapshot.seats if seat.hole_cards and not seat.folded]
    folded = len(live_hands) <= 1
    revealed: list[RevealedHandResponse] = []
    if not folded:
        for seat in live_hands:
            try:
                hand = StandardHighHand.from_game(
                    "".join(seat.hole_cards),
                    "".join(snapshot.community_cards),
                )
            except ValueError:
                continue
            revealed.append(
                RevealedHandResponse(
                    seat=seat.seat,
                    hole_cards=seat.hole_cards,
                    label=hand.entry.label.value,
                    best_five=tuple(repr(card) for card in hand.cards),
                )
            )

    return HandResultResponse(
        reason="fold" if folded else "showdown",
        awards=tuple(awards),
        revealed_hands=tuple(revealed),
    )
