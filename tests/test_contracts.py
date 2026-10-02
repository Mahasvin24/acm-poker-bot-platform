from poker_bot_platform.domain import ActionType, LegalAction, TournamentConfig


def test_default_tournament_contract() -> None:
    config = TournamentConfig()
    assert config.max_players == 36
    assert config.table_size == 6
    assert config.starting_stack == 20_000
    assert config.bot_action_timeout_ms == 3_000
    assert config.bot_connect_timeout_ms == 500
    assert config.level(21).big_blind == 200_000


def test_legal_raise_contract() -> None:
    action = LegalAction(action=ActionType.RAISE, min_amount_to=400, max_amount_to=20_000)
    assert action.min_amount_to == 400
