"""Edit choose_action to change your strategy, then restart the bot."""

from poker_bot_platform.bots.models import BotActionRequest
from poker_bot_platform.domain import ActionType


def choose_action(state: BotActionRequest) -> tuple[ActionType, int | None]:
    """Return (action, raise_to). Use None for raise_to unless raising."""
    allowed = {item.action for item in state.legal_actions}
    if ActionType.CHECK in allowed:
        return ActionType.CHECK, None
    if ActionType.CALL in allowed:
        return ActionType.CALL, None
    return ActionType.FOLD, None
