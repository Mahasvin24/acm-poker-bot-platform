"""Cached showdown equity for the admin-only hole-card view."""

from __future__ import annotations

import random
from functools import lru_cache
from itertools import combinations

from pokerkit import Card, StandardHighHand

_DECK = tuple(f"{rank}{suit}" for rank in "23456789TJQKA" for suit in "cdhs")
_SAMPLE_COUNT = 512


@lru_cache(maxsize=256)
def showdown_equities(
    community: tuple[str, ...],
    seats: tuple[tuple[int, tuple[str, ...], bool], ...],
) -> dict[int, float]:
    """Return fractional win shares, splitting ties, assuming no further folds.

    All known cards, including folded hands, are removed from possible runouts.
    River and turn results are exact; earlier streets use deterministic sampling.
    This estimates hand strength, not side-pot payouts or future betting decisions.
    """
    active = [(number, cards) for number, cards, folded in seats if not folded]
    if not active or any(len(cards) != 2 for _, cards in active):
        return {}
    shares = dict.fromkeys((number for number, _, _ in seats), 0.0)
    if len(active) == 1:
        shares[active[0][0]] = 100.0
        return shares
    known = set(community) | {card for _, cards, _ in seats for card in cards}
    remaining = [card for card in _DECK if card not in known]
    missing = 5 - len(community)
    rng = random.Random(repr((community, seats)))
    runouts = (
        list(combinations(remaining, missing))
        if missing <= 1
        else [tuple(rng.sample(remaining, missing)) for _ in range(_SAMPLE_COUNT)]
    )
    holes = [(number, tuple(Card.clean("".join(cards)))) for number, cards in active]
    for runout in runouts:
        board = tuple(Card.clean("".join((*community, *runout))))
        hands = [(number, StandardHighHand.from_game(cards, board)) for number, cards in holes]
        best = max(hand for _, hand in hands)
        winners = [number for number, hand in hands if hand == best]
        for number in winners:
            shares[number] += 100 / len(runouts) / len(winners)
    return {number: round(value, 1) for number, value in shares.items()}
