from __future__ import annotations

from poker_bot_platform.bots.models import BotActionRequest, BotActionResponse
from poker_bot_platform.domain.models import ActionType


def deterministic_reference_action(request: BotActionRequest) -> BotActionResponse:
    """A predictable, intentionally simple bot for integration and soak tests."""

    actions = {legal.action for legal in request.legal_actions}
    if ActionType.CHECK in actions:
        action = ActionType.CHECK
    elif ActionType.CALL in actions:
        action = ActionType.CALL
    else:
        action = ActionType.FOLD
    return BotActionResponse(
        protocol="poker-bot.v1",
        tournament_id=request.tournament_id,
        table_id=request.table_id,
        hand_id=request.hand_id,
        decision_id=request.decision_id,
        table_version=request.table_version,
        action=action,
    )
