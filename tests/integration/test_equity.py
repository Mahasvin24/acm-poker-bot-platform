from poker_bot_platform.integration.equity import showdown_equities


def test_river_winner_is_exact_and_folded_players_have_zero_odds() -> None:
    odds = showdown_equities(
        ("2c", "3d", "7h", "9s", "Jc"),
        ((1, ("As", "Ah"), False), (2, ("Ks", "Kh"), False), (3, ("Js", "Jh"), True)),
    )
    assert odds == {1: 100.0, 2: 0.0, 3: 0.0}


def test_board_tie_splits_the_percentage() -> None:
    odds = showdown_equities(
        ("As", "Ks", "Qs", "Js", "Ts"),
        ((1, ("2c", "3c"), False), (2, ("4d", "5d"), False)),
    )
    assert odds == {1: 50.0, 2: 50.0}


def test_preflop_odds_are_stable_and_sum_to_one_hundred() -> None:
    seats = ((1, ("As", "Ah"), False), (2, ("Ks", "Kh"), False))
    first = showdown_equities((), seats)
    assert first == showdown_equities((), seats)
    assert abs(sum(first.values()) - 100) < 0.2
    assert 70 < first[1] < 90


def test_unknown_cards_do_not_invent_odds() -> None:
    assert showdown_equities((), ((1, (), False), (2, ("As", "Ah"), False))) == {}
