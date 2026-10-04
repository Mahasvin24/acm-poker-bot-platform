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

    awards: list[HandAwardResponse] = []
    for seat in snapshot.seats:
        starting = starting_stacks.get(seat.seat)
        if starting is None:
            continue
        net = seat.stack - starting
        amount = net + seat.committed_this_hand
        if amount > 0:
            awards.append(HandAwardResponse(seat=seat.seat, amount=amount, net=net))

    live_hands = [seat for seat in snapshot.seats if seat.hole_cards and not seat.folded]
    folded = len(live_hands) <= 1
    revealed: list[RevealedHandResponse] = []
    if not folded:
        for seat in snapshot.seats:
            if seat.eliminated and not seat.hole_cards:
                continue
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
