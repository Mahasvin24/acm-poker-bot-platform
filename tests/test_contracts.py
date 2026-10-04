import pytest
from pydantic import ValidationError

from poker_bot_platform.domain import (
    ActionType,
    BlindLevel,
    LegalAction,
    TournamentConfig,
    default_blind_levels,
)


def test_default_tournament_contract() -> None:
    config = TournamentConfig()
    assert config.max_players == 36
    assert config.table_size == 6
    assert config.starting_stack == 20_000
    assert config.bot_action_timeout_ms == 3_000
    assert config.bot_connect_timeout_ms == 500
    assert config.break_every_levels == 4
    assert config.break_duration_seconds == 300
    assert config.level(21).big_blind == 25_000


def test_default_blind_schedule_starts_deep_and_progresses_smoothly() -> None:
    levels = default_blind_levels()
    assert len(levels) == 29
    assert 20_000 / levels[0].big_blind == 100
    for previous, current in zip(levels[:-1], levels[1:], strict=True):
        assert current.big_blind / previous.big_blind <= 1.5
    assert all(0.5 <= level.small_blind / level.big_blind <= 2 / 3 for level in levels)


def test_legal_raise_contract() -> None:
    action = LegalAction(action=ActionType.RAISE, min_amount_to=400, max_amount_to=20_000)
    assert action.min_amount_to == 400


def test_big_blind_ante_is_fixed_to_big_blind() -> None:
    with pytest.raises(ValidationError, match="big-blind ante"):
        BlindLevel(small_blind=100, big_blind=200, big_blind_ante=0)
