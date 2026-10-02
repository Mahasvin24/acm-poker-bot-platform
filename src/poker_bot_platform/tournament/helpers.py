from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable

from poker_bot_platform.tournament.models import TournamentPlayer, TournamentTable

_SEATS = tuple(range(1, 7))


def deterministic_rng(seed_hex: str, purpose: str) -> random.Random:
    material = bytes.fromhex(seed_hex) + purpose.encode("utf-8")
    return random.Random(int.from_bytes(hashlib.sha256(material).digest()))


def clockwise_occupied(
    occupied: Iterable[int],
    after_seat: int,
) -> tuple[int, ...]:
    occupied_set = set(occupied)
    return tuple(
        seat
        for offset in range(1, 7)
        if (seat := ((after_seat - 1 + offset) % 6) + 1) in occupied_set
    )


def next_button(table: TournamentTable) -> int:
    return clockwise_occupied((player.seat for player in table.players), table.button_seat)[0]


def next_big_blind_player(table: TournamentTable) -> TournamentPlayer:
    ordered = clockwise_occupied((player.seat for player in table.players), table.button_seat)
    if len(ordered) == 2:
        big_blind_seat = ordered[1]
    else:
        # The next hand's button is ordered[0], followed by its SB and BB.
        big_blind_seat = ordered[2]
    return next(player for player in table.players if player.seat == big_blind_seat)


def worst_legal_vacancy(table: TournamentTable) -> int:
    """Choose the empty seat closest to the next BB without placing a player in the next SB."""

    occupied = {player.seat for player in table.players}
    vacancies = [seat for seat in _SEATS if seat not in occupied]
    if not vacancies:
        raise ValueError("table has no vacant seat")
    scored: list[tuple[int, int]] = []
    for candidate in vacancies:
        augmented = occupied | {candidate}
        ordered = clockwise_occupied(augmented, table.button_seat)
        next_sb = ordered[1] if len(ordered) > 2 else ordered[0]
        if candidate == next_sb and len(vacancies) > 1:
            continue
        next_bb = ordered[1] if len(ordered) == 2 else ordered[2]
        distance = (candidate - next_bb) % 6
        scored.append((distance, candidate))
    if not scored:
        return min(vacancies)
    return min(scored)[1]


def table_sort_key(table: TournamentTable) -> tuple[int, str]:
    suffix = table.table_id.rsplit("-", 1)[-1]
    return (int(suffix) if suffix.isdigit() else 0, table.table_id)
