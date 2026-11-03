import pytest
from pydantic import ValidationError

from poker_bot_platform.domain import (
    BOT_ACTION_TIMEOUT_MS,
    BOT_CONNECT_TIMEOUT_MS,
    ActionType,
    BlindLevel,
    LegalAction,
    MatchConfig,
)


def test_default_match_contract() -> None:
    config = MatchConfig()
    assert config.max_seats == 6
    assert config.starting_stack == 20_000
    assert (config.small_blind, config.big_blind) == (100, 200)
    assert not config.escalates
    assert BOT_ACTION_TIMEOUT_MS == 3_000
    assert BOT_CONNECT_TIMEOUT_MS == 500


def test_fixed_blinds_never_change() -> None:
    config = MatchConfig()
    assert config.level(1) == config.level(12)
    assert config.level(5).big_blind_ante == 0


def test_escalating_blinds_scale_from_the_opening_level_and_progress_smoothly() -> None:
    config = MatchConfig(small_blind=50, big_blind=100, blind_increase_minutes=10)
    levels = [config.level(number) for number in range(1, 35)]
    assert (levels[0].small_blind, levels[0].big_blind) == (50, 100)
    for previous, current in zip(levels[:-1], levels[1:], strict=True):
        assert previous.big_blind < current.big_blind <= previous.big_blind * 2
        assert current.small_blind < current.big_blind
    assert config.level_seconds == 600


def test_big_blind_ante_follows_the_big_blind_when_enabled() -> None:
    config = MatchConfig(big_blind_ante=True, blind_increase_minutes=5)
    assert config.level(3).big_blind_ante == config.level(3).big_blind


def test_config_rejects_inverted_blinds_and_tiny_stacks() -> None:
    with pytest.raises(ValidationError, match="small blind"):
        MatchConfig(small_blind=200, big_blind=200)
    with pytest.raises(ValidationError, match="two big blinds"):
        MatchConfig(starting_stack=300)


def test_legal_raise_contract() -> None:
    action = LegalAction(action=ActionType.RAISE, min_amount_to=400, max_amount_to=20_000)
    assert action.min_amount_to == 400


def test_big_blind_ante_is_zero_or_the_big_blind() -> None:
    BlindLevel(small_blind=100, big_blind=200, big_blind_ante=0)
    with pytest.raises(ValidationError, match="big-blind ante"):
        BlindLevel(small_blind=100, big_blind=200, big_blind_ante=100)
